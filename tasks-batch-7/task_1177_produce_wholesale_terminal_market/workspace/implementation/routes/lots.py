"""PurchaseLot, Inspection, TemperatureReading routes — lot lifecycle,
USDA inspection/dispute cycle, cold-chain accumulation and cascade."""

from flask import Blueprint, request

from db import store
from errors import (
    raise_error,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_PRICE_NOT_POSTED,
    ERR_PRICE_OUT_OF_RANGE,
    ERR_INSPECTION_OPEN,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    get_json_body,
    require_fields,
    req_string,
    req_positive_int,
    req_positive_number,
    req_number,
    req_enum,
    req_date,
    req_datetime,
    is_int,
    is_str,
    is_number,
    lookup,
    stamp_new,
    touch,
    paginate,
    sorted_by_created,
    lot_provisional_cost_cents,
    lot_final_cost_from_defect_cents,
    lot_final_cost_from_agreed_cents,
    recompute_lot_payable,
    recompute_lot_available,
    recompute_shipper_trust_exposure,
    recompute_customer_credit_exposure,
    clock_now,
    now_iso,
    DATE_FMT,
    Decimal,
)

bp = Blueprint("lots", __name__)


# ---------------------------------------------------------------------------
# Purchase lots
# ---------------------------------------------------------------------------

@bp.post("/market/purchase-lots")
def create_purchase_lot():
    require_roles(["Receiver"])
    body = get_json_body()
    require_fields(
        body,
        [
            "shipper_id",
            "commodity_id",
            "market_date",
            "quantity_units",
            "shipper_unit_price",
            "declared_grade",
        ],
    )
    shipper_id = body.get("shipper_id")
    commodity_id = body.get("commodity_id")
    if not is_str(shipper_id):
        raise_error(ERR_VALIDATION, "shipper_id must be a string")
    if not is_str(commodity_id):
        raise_error(ERR_VALIDATION, "commodity_id must be a string")
    market_date = req_date(body, "market_date")
    quantity_units = req_positive_int(body, "quantity_units")
    shipper_unit_price = req_positive_number(body, "shipper_unit_price")
    declared_grade = req_string(body, "declared_grade")

    # FK existence, left-to-right body order (priority 4)
    shipper = lookup(store.shippers, shipper_id, "Shipper")
    commodity = lookup(store.commodities, commodity_id, "Commodity")

    # DailyPrice must exist for (commodity_id, market_date) (priority 9)
    market_date_str = market_date.strftime(DATE_FMT)
    price_row = None
    for dp in store.daily_prices.values():
        if dp["commodity_id"] == commodity_id and dp["market_date"] == market_date_str:
            price_row = dp
            break
    if price_row is None:
        raise_error(
            ERR_PRICE_NOT_POSTED,
            f"No DailyPrice posted for ({commodity_id}, {market_date_str})",
        )
    low = Decimal(str(price_row["low_price"]))
    high = Decimal(str(price_row["high_price"]))
    if shipper_unit_price < low or shipper_unit_price > high:
        raise_error(
            ERR_PRICE_OUT_OF_RANGE,
            f"shipper_unit_price {shipper_unit_price} outside [{low}, {high}]",
        )

    provisional = lot_provisional_cost_cents(quantity_units, shipper_unit_price)
    lot = stamp_new(
        {
            "shipper_id": shipper_id,
            "commodity_id": commodity_id,
            "market_date": market_date_str,
            "quantity_units": quantity_units,
            "shipper_unit_price": float(shipper_unit_price),
            "declared_grade": declared_grade,
            "status": "ORDERED",
            "received_at": None,
            "provisional_cost_cents": provisional,
            "adjusted_cost_cents": provisional,
            "payable_cents": provisional,
            "dumped_units": 0,
            "reserved_units": 0,
            "sold_units": 0,
            "available_units": quantity_units,
            "cold_chain_status": "OK",
            "violation_minutes": 0,
        }
    )
    store.purchase_lots[lot["id"]] = lot
    recompute_shipper_trust_exposure(shipper_id)
    return success_object(lot, 201)


@bp.get("/market/purchase-lots")
def list_purchase_lots():
    require_roles(ALL_ROLES)
    shipper_id = request.args.get("shipper_id")
    commodity_id = request.args.get("commodity_id")
    status = request.args.get("status")
    market_date = request.args.get("market_date")
    items = list(store.purchase_lots.values())
    if shipper_id is not None:
        items = [l for l in items if l["shipper_id"] == shipper_id]
    if commodity_id is not None:
        items = [l for l in items if l["commodity_id"] == commodity_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if market_date is not None:
        items = [l for l in items if l["market_date"] == market_date]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


@bp.get("/market/purchase-lots/<lot_id>")
def get_purchase_lot(lot_id):
    require_roles(ALL_ROLES)
    lot = lookup(store.purchase_lots, lot_id, "PurchaseLot")
    return success_object(lot, 200)


@bp.post("/market/purchase-lots/<lot_id>/receive")
def receive_lot(lot_id):
    require_roles(["Receiver"])
    lot = lookup(store.purchase_lots, lot_id, "PurchaseLot")
    if lot["status"] != "ORDERED":
        raise_error(
            ERR_INVALID_STATE,
            f"Lot must be ORDERED to receive; current status {lot['status']}",
        )
    lot["status"] = "RECEIVED"
    lot["received_at"] = now_iso()
    touch(lot)
    return success_object(lot, 200)


@bp.post("/market/purchase-lots/<lot_id>/dispute")
def dispute_lot(lot_id):
    require_roles(["Receiver"])
    body = get_json_body()
    reason = body.get("reason")
    if reason is not None and not is_str(reason):
        raise_error(ERR_VALIDATION, "reason must be a string")
    lot = lookup(store.purchase_lots, lot_id, "PurchaseLot")
    if lot["status"] != "INSPECTED":
        raise_error(
            ERR_INVALID_STATE,
            f"Lot must be INSPECTED to dispute; current status {lot['status']}",
        )
    has_certified_fail = any(
        i["purchase_lot_id"] == lot_id
        and i["status"] == "CERTIFIED"
        and i["result"] == "FAIL"
        for i in store.inspections.values()
    )
    if not has_certified_fail:
        raise_error(
            ERR_INVALID_STATE,
            "A CERTIFIED inspection with result FAIL is required to open a dispute",
        )
    lot["status"] = "DISPUTED"
    touch(lot)
    return success_object(lot, 200)


@bp.post("/market/purchase-lots/<lot_id>/resolve-dispute")
def resolve_dispute(lot_id):
    require_roles(["MarketAdmin"])
    body = get_json_body()
    require_fields(body, ["outcome"])
    outcome = req_enum(
        body, "outcome", {"ACCEPT_AS_IS", "PRICE_ADJUST", "REJECT_TO_SHIPPER"}
    )
    agreed_unit_price = None
    if outcome == "PRICE_ADJUST":
        if "agreed_unit_price" not in body or body["agreed_unit_price"] is None:
            raise_error(
                ERR_VALIDATION, "agreed_unit_price is required for PRICE_ADJUST"
            )
        agreed_unit_price = req_positive_number(body, "agreed_unit_price")
    elif "agreed_unit_price" in body and body["agreed_unit_price"] is not None:
        if not is_number(body["agreed_unit_price"]):
            raise_error(ERR_VALIDATION, "agreed_unit_price must be a number")

    lot = lookup(store.purchase_lots, lot_id, "PurchaseLot")
    if lot["status"] != "DISPUTED":
        raise_error(
            ERR_INVALID_STATE,
            f"Lot must be DISPUTED to resolve; current status {lot['status']}",
        )

    if outcome == "REJECT_TO_SHIPPER":
        lot["status"] = "REJECTED"
        lot["payable_cents"] = 0
        # Compensating cascade: void any still-SUBMITTED inspection.
        for insp in store.inspections.values():
            if insp["purchase_lot_id"] == lot_id and insp["status"] == "SUBMITTED":
                insp["status"] = "VOIDED"
                touch(insp)
    else:
        lot["status"] = "ACCEPTED"
        if outcome == "PRICE_ADJUST":
            lot["adjusted_cost_cents"] = lot_final_cost_from_agreed_cents(
                lot["quantity_units"], agreed_unit_price
            )
        recompute_lot_payable(lot)
    touch(lot)
    recompute_shipper_trust_exposure(lot["shipper_id"])
    return success_object(lot, 200)


@bp.post("/market/purchase-lots/<lot_id>/close")
def close_lot(lot_id):
    require_roles(["Receiver"])
    lot = lookup(store.purchase_lots, lot_id, "PurchaseLot")
    if lot["status"] != "ACCEPTED":
        raise_error(
            ERR_INVALID_STATE,
            f"Lot must be ACCEPTED to close; current status {lot['status']}",
        )
    active = any(
        b["purchase_lot_id"] == lot_id and b["status"] in {"SCHEDULED", "IN_PROCESS"}
        for b in store.ripening_bookings.values()
    )
    if active:
        raise_error(
            ERR_INVALID_STATE,
            "Lot has active ripening bookings (SCHEDULED or IN_PROCESS)",
        )
    lot["status"] = "CLOSED"
    touch(lot)
    recompute_shipper_trust_exposure(lot["shipper_id"])
    return success_object(lot, 200)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

@bp.post("/market/inspections")
def create_inspection():
    require_roles(["USDAInspector"])
    body = get_json_body()
    require_fields(body, ["purchase_lot_id", "inspected_grade", "defect_pct", "result"])
    purchase_lot_id = body.get("purchase_lot_id")
    if not is_str(purchase_lot_id):
        raise_error(ERR_VALIDATION, "purchase_lot_id must be a string")
    inspected_grade = req_string(body, "inspected_grade")
    defect_pct = req_number(body, "defect_pct")
    if defect_pct < 0 or defect_pct > 100:
        raise_error(ERR_VALIDATION, "defect_pct must be within 0..100")
    result = req_enum(body, "result", {"PASS", "FAIL"})

    lot = lookup(store.purchase_lots, purchase_lot_id, "PurchaseLot")
    if lot["status"] not in {"RECEIVED", "DISPUTED"}:
        raise_error(
            ERR_INVALID_STATE,
            f"Lot must be RECEIVED or DISPUTED to inspect; current status {lot['status']}",
        )
    open_exists = any(
        i["purchase_lot_id"] == purchase_lot_id and i["status"] == "SUBMITTED"
        for i in store.inspections.values()
    )
    if open_exists:
        raise_error(
            ERR_INSPECTION_OPEN,
            "Another SUBMITTED inspection already exists for this lot",
        )

    inspection = stamp_new(
        {
            "purchase_lot_id": purchase_lot_id,
            "inspected_grade": inspected_grade,
            "defect_pct": float(defect_pct),
            "result": result,
            "status": "SUBMITTED",
        }
    )
    store.inspections[inspection["id"]] = inspection
    lot["status"] = "INSPECTED"
    touch(lot)
    return success_object(inspection, 201)


@bp.get("/market/purchase-lots/<lot_id>/inspections")
def list_lot_inspections(lot_id):
    require_roles(ALL_ROLES)
    lookup(store.purchase_lots, lot_id, "PurchaseLot")
    items = [
        i for i in store.inspections.values() if i["purchase_lot_id"] == lot_id
    ]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


@bp.post("/market/inspections/<inspection_id>/certify")
def certify_inspection(inspection_id):
    require_roles(["USDAInspector"])
    inspection = lookup(store.inspections, inspection_id, "Inspection")
    lot = lookup(store.purchase_lots, inspection["purchase_lot_id"], "PurchaseLot")
    if inspection["status"] != "SUBMITTED":
        raise_error(
            ERR_INVALID_STATE,
            f"Inspection must be SUBMITTED to certify; current status {inspection['status']}",
        )
    if lot["status"] != "INSPECTED":
        raise_error(
            ERR_INVALID_STATE,
            f"Lot must be INSPECTED to certify; current status {lot['status']}",
        )
    inspection["status"] = "CERTIFIED"
    touch(inspection)
    if inspection["result"] == "PASS":
        # FINAL landed cost via defect formula
        new_adjusted = lot_final_cost_from_defect_cents(
            lot["quantity_units"],
            Decimal(str(lot["shipper_unit_price"])),
            Decimal(str(inspection["defect_pct"])),
        )
        if new_adjusted is not None:
            lot["adjusted_cost_cents"] = new_adjusted
        # else: defect within tolerance; adjusted stays provisional
        recompute_lot_payable(lot)
        lot["status"] = "ACCEPTED"
        touch(lot)
        recompute_shipper_trust_exposure(lot["shipper_id"])
    # FAIL: lot remains INSPECTED (dispute is a separate Receiver action)
    return success_object(inspection, 200)


# ---------------------------------------------------------------------------
# Temperature readings + cold-chain cascade
# ---------------------------------------------------------------------------

@bp.post("/market/temperature-readings")
def create_temperature_reading():
    require_roles(["Receiver"])
    body = get_json_body()
    require_fields(body, ["purchase_lot_id", "recorded_at", "temp_f", "duration_minutes"])
    purchase_lot_id = body.get("purchase_lot_id")
    if not is_str(purchase_lot_id):
        raise_error(ERR_VALIDATION, "purchase_lot_id must be a string")
    recorded_at = req_datetime(body, "recorded_at")
    temp_f = req_number(body, "temp_f")
    duration_minutes = req_positive_int(body, "duration_minutes")

    lot = lookup(store.purchase_lots, purchase_lot_id, "PurchaseLot")
    commodity = lookup(store.commodities, lot["commodity_id"], "Commodity")

    out_of_range = (
        float(temp_f) < commodity["temp_min_f"]
        or float(temp_f) > commodity["temp_max_f"]
    )

    # Append-only ledger row: id + created_at only (PRD §2.4)
    reading = stamp_new(
        {
            "purchase_lot_id": purchase_lot_id,
            "recorded_at": _format_dt(recorded_at),
            "temp_f": float(temp_f),
            "duration_minutes": duration_minutes,
            "out_of_range": out_of_range,
        },
        common=False,
    )
    store.temperature_readings[reading["id"]] = reading

    if out_of_range:
        lot["violation_minutes"] = lot.get("violation_minutes", 0) + duration_minutes

    flipped = False
    if (
        lot["cold_chain_status"] == "OK"
        and lot["violation_minutes"] > commodity["max_violation_minutes"]
    ):
        # Strictly greater flips; exactly equal stays OK.
        lot["cold_chain_status"] = "VIOLATED"
        flipped = True

    if flipped:
        touch(lot)
        # Cascade hop 2: every CONFIRMED order with a line on this lot ->
        # ON_HOLD (COLD_CHAIN); hop 3: release its line reservations.
        affected_orders = [
            o
            for o in store.sales_orders.values()
            if o["status"] == "CONFIRMED"
            and any(line["lot_id"] == lot["id"] for line in o["lines"])
        ]
        for order in affected_orders:
            for line in order["lines"]:
                line_lot = store.purchase_lots.get(line["lot_id"])
                if line_lot is not None:
                    line_lot["reserved_units"] = max(
                        0, line_lot["reserved_units"] - line["quantity"]
                    )
                    recompute_lot_available(line_lot)
            order["status"] = "ON_HOLD"
            order["hold_reason"] = "COLD_CHAIN"
            touch(order)
            recompute_customer_credit_exposure(order["customer_id"])

    return success_object(reading, 201)


def _format_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.get("/market/purchase-lots/<lot_id>/temperature-readings")
def list_lot_temperature_readings(lot_id):
    require_roles(ALL_ROLES)
    lookup(store.purchase_lots, lot_id, "PurchaseLot")
    items = [
        r
        for r in store.temperature_readings.values()
        if r["purchase_lot_id"] == lot_id
    ]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)
