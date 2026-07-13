"""Home try-on kits: sample holds, returns, late fees and the risk score (PRD 3.4)."""
from flask import Blueprint, request

import calc
import schema
import store
from auth import authenticate, require_owner
from envelope import array_response, object_response, paginate
from errors import err
from serializers import dump, dump_all

bp = Blueprint("kits", __name__)

MAX_KIT_FRAMES = 5
LIVE_KIT_STATUSES = ("REQUESTED", "SHIPPED", "OVERDUE")


def _items_of(kit_id):
    return [i for i in store.ordered(store.kit_items) if i["kit_id"] == kit_id]


@bp.post("/home-try-on-kits")
def create_kit():
    actor = authenticate("Customer")
    b = schema.body()
    customer_id = schema.string_field(b, "customer_id")
    frame_ids = schema.string_list_field(b, "frame_ids")
    ship_raw, ship_dt = schema.datetime_field(b, "ship_date")
    due_raw, due_dt = schema.datetime_field(b, "due_date")
    schema.strictly_after("due_date", due_dt, "ship_date", ship_dt)

    # Priority 5 -- body reference existence.
    schema.get_customer(customer_id)
    frames = [schema.get_frame(fid) for fid in frame_ids]

    # Priority 6 -- ownership.
    customer = store.customers[customer_id]
    require_owner(actor, customer_id)

    # Priority 20 / 21 -- kit sizing.
    if len(frame_ids) == 0:
        raise err("ERR_KIT_EMPTY")
    if len(set(frame_ids)) > MAX_KIT_FRAMES:
        raise err("ERR_KIT_SIZE_EXCEEDED")

    # Priority 22 -- the return-risk gate fires at >= 70, not merely above 70.
    if customer["return_risk_score"] >= calc.BLOCK_THRESHOLD:
        raise err("ERR_CUSTOMER_TRYON_BLOCKED")

    # Priority 23 -- CLOSED [ship_date, due_date], capacity 1, touching counts.
    for other in store.ordered(store.kits):
        if other["customer_id"] != customer_id or other["status"] not in LIVE_KIT_STATUSES:
            continue
        if ship_dt <= other["_due_date_dt"] and other["_ship_date_dt"] <= due_dt:
            raise err("ERR_TRYON_WINDOW_CONFLICT")

    # Priority 24 -- every requested frame needs a free sample unit.
    for frame in frames:
        if frame["tryon_available"] < 1:
            raise err("ERR_TRYON_STOCK_UNAVAILABLE")

    kit = store.new_record(
        customer_id=customer_id,
        ship_date=ship_raw,
        due_date=due_raw,
        status="REQUESTED",
        was_overdue=False,
        item_count=len(frame_ids),
        kept_count=0,
        late_fee_cents=0,
    )
    kit["_ship_date_dt"] = ship_dt
    kit["_due_date_dt"] = due_dt
    store.kits[kit["id"]] = kit

    for frame in frames:
        item = {
            "id": store.new_id(),
            "created_at": store.wall_now_iso(),
            "_seq": store.next_seq(),
            "kit_id": kit["id"],
            "frame_id": frame["id"],
            "outcome": "PENDING",
        }
        store.kit_items[item["id"]] = item
        frame["tryon_available"] -= 1
        store.touch(frame)

    return object_response(dump("kit", kit), 201)


@bp.get("/home-try-on-kits/<kit_id>")
def read_kit(kit_id):
    actor = authenticate("Customer", "StoreAssociate", "PlatformAdmin")
    kit = schema.get_kit(kit_id)
    require_owner(actor, kit["customer_id"])
    return object_response(dump("kit", kit))


@bp.get("/customers/<customer_id>/home-try-on-kits")
def list_customer_kits(customer_id):
    actor = authenticate("Customer", "StoreAssociate", "PlatformAdmin")
    schema.get_customer(customer_id)
    require_owner(actor, customer_id)

    items = [k for k in store.ordered(store.kits) if k["customer_id"] == customer_id]
    status = request.args.get("status")
    if status:
        items = [k for k in items if k["status"] == status]
    window, meta = paginate(items)
    return array_response(dump_all("kit", window), meta)


@bp.get("/home-try-on-kits/<kit_id>/items")
def list_kit_items(kit_id):
    actor = authenticate("Customer", "StoreAssociate", "PlatformAdmin")
    kit = schema.get_kit(kit_id)
    require_owner(actor, kit["customer_id"])
    window, meta = paginate(_items_of(kit_id))
    return array_response(dump_all("kit_item", window), meta)


@bp.post("/home-try-on-kits/<kit_id>/ship")
def ship_kit(kit_id):
    authenticate("StoreAssociate")
    kit = schema.get_kit(kit_id)
    if kit["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE")
    kit["status"] = "SHIPPED"
    store.touch(kit)
    return object_response(dump("kit", kit))


@bp.post("/home-try-on-kits/<kit_id>/return")
def return_kit(kit_id):
    actor = authenticate("Customer")
    b = schema.body()
    kept_frame_ids = schema.string_list_field(b, "kept_frame_ids")

    kit = schema.get_kit(kit_id)

    # Priority 5 -- every kept id must name a frame that is actually on this kit.
    items = _items_of(kit_id)
    kit_frame_ids = set(i["frame_id"] for i in items)
    for fid in kept_frame_ids:
        if fid not in kit_frame_ids:
            raise err("ERR_FRAME_NOT_FOUND")

    require_owner(actor, kit["customer_id"])
    if kit["status"] not in ("SHIPPED", "OVERDUE"):
        raise err("ERR_INVALID_STATE")

    kept = set(kept_frame_ids)

    # CASCADE L1 -- the kit returns and its late fee is computed.
    kit["status"] = "RETURNED"
    kit["late_fee_cents"] = calc.kit_late_fee(kit)

    # CASCADE L2 / L3 -- resolve every PENDING item; both resolutions release the hold.
    kept_count = 0
    for item in items:
        if item["outcome"] != "PENDING":
            continue
        item["outcome"] = "KEPT" if item["frame_id"] in kept else "RETURNED"
        if item["outcome"] == "KEPT":
            kept_count += 1
        frame = store.frames.get(item["frame_id"])
        if frame is not None:
            frame["tryon_available"] += 1
            store.touch(frame)

    kit["kept_count"] = kept_count
    store.touch(kit)

    customer = store.customers.get(kit["customer_id"])
    if customer is not None:
        calc.recompute_return_risk(customer)

    return object_response(dump("kit", kit))
