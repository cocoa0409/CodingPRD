"""Multi-store sourcing allocation (PRD 3.7). All-or-nothing."""
import db
from errors import ApiError
from services import stock as stock_svc


def _ranked_candidates(order, store_region, sku, virtual_available):
    """Candidate stores for a SKU, ranked on the four keys in sequence."""
    candidates = []
    for store in db.all_of("stores"):
        if store["region_code"] != store_region:
            continue
        stock = stock_svc.find_stock(store["id"], sku)
        if stock is None:
            continue
        avail = virtual_available.get((store["id"], sku))
        if avail is None:
            avail = stock["on_hand_units"] - stock["reserved_units"]
        # Eligibility reads the *actual* stock position, not the running plan.
        if stock["on_hand_units"] - stock["reserved_units"] <= 0:
            continue
        candidates.append((store, avail))
    candidates.sort(key=lambda pair: (
        0 if pair[0]["id"] == order["fulfillment_store_id"] else 1,
        pair[0]["distance_rank"],
        -pair[1],
        pair[0]["created_at"],
        pair[0]["_seq"],
    ))
    return candidates


def plan(order, lines):
    """Return the planned [(order_line, store_id, sku, qty)] or raise."""
    fulfillment_store = db.get("stores", order["fulfillment_store_id"])
    region = fulfillment_store["region_code"]

    # Availability consumed by the plan so far, so two lines on the same SKU do
    # not both claim the same units.
    virtual = {}
    planned = []
    for line in lines:
        candidates = _ranked_candidates(order, region, line["sku"], virtual)
        if not candidates:
            raise ApiError("ERR_NO_SOURCING_CANDIDATES", 409)
        remaining = line["qty_units"]
        for store, avail in candidates:
            if remaining <= 0:
                break
            take = min(remaining, avail)
            if take > 0:
                planned.append((line, store["id"], line["sku"], take))
                virtual[(store["id"], line["sku"])] = avail - take
                remaining -= take
            if remaining == 0:
                break
        if remaining > 0:
            raise ApiError("ERR_INSUFFICIENT_JOB_LOT", 409)

    if order.get("job_lot_required"):
        stores_used = {item[1] for item in planned}
        if len(stores_used) > 1:
            raise ApiError("ERR_JOB_LOT_SPLIT_NOT_ALLOWED", 409)
    return planned


def commit(order, planned):
    """Persist the plan as HELD reservations and recompute every touched store."""
    created = []
    for line, store_id, sku, qty in planned:
        res = db.new_record("reservations", {
            "pro_order_id": order["id"],
            "order_line_id": line["id"],
            "store_id": store_id,
            "sku": sku,
            "qty_units": qty,
            "status": "HELD",
            "released_reason_code": None,
        })
        created.append(res)
    for _line, store_id, sku, _qty in planned:
        stock_svc.recompute(store_id, sku)
    return created


def release(reservation, reason_code):
    reservation["status"] = "RELEASED"
    reservation["released_reason_code"] = reason_code
    db.touch(reservation)
    stock_svc.recompute(reservation["store_id"], reservation["sku"])
    return reservation


def revert_order_if_all_released(order):
    """Conditional cascade: an order whose every reservation is RELEASED falls back."""
    reservations = db.where("reservations", pro_order_id=order["id"])
    if not reservations:
        return False
    if all(res["status"] == "RELEASED" for res in reservations):
        if order["fulfillment_status"] in ("RESERVED", "STAGED"):
            order["fulfillment_status"] = "SUBMITTED"
            db.touch(order)
            return True
    return False
