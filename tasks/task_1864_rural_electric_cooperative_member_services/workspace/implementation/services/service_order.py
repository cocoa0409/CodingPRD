"""ServiceOrder service: creation, estimation, invoicing, scheduling, construction, cancellation."""
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
import db
from db import store, new_common, touch

# ATC constants per scaffold
LINE_EXTENSION_CENTS_PER_FT = 1200
ROAD_BORE_FLAT_CENTS = 150000
TEMPORARY_MIN_CENTS = 50000
FREE_ALLOWANCE_FT = 250
OVERHEAD_THRESHOLD_CENTS = 200000
OVERHEAD_PCT = 0.10


def create_service_order(body):
    required = ["service_location_id", "order_type", "distance_ft", "requires_road_bore"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")

    loc = store.service_locations.get(body["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")

    if body["order_type"] not in ("NEW_SERVICE", "UPGRADE", "RELOCATION", "TEMPORARY"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid order_type")

    order = new_common({
        "service_location_id": body["service_location_id"],
        "order_type": body["order_type"],
        "status": "DRAFT",
        "distance_ft": body["distance_ft"],
        "requires_road_bore": body["requires_road_bore"],
        "aid_to_construction_cents": 0,
        "row_agreement_id": None,
    })
    store.service_orders[order["id"]] = order
    return order


def get_service_order(order_id):
    o = store.service_orders.get(order_id)
    if not o:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceOrder not found")
    return o


def list_service_orders(service_location_id=None, status=None, row_agreement_id=None):
    rows = list(store.service_orders.values())
    if service_location_id is not None:
        rows = [r for r in rows if r.get("service_location_id") == service_location_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if row_agreement_id is not None:
        rows = [r for r in rows if r.get("row_agreement_id") == row_agreement_id]
    return rows


def estimate_order(order_id):
    order = get_service_order(order_id)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be DRAFT to estimate")

    # Compute aid_to_construction_cents
    distance = Decimal(str(order["distance_ft"]))
    base = LINE_EXTENSION_CENTS_PER_FT * distance
    if order.get("requires_road_bore"):
        base += ROAD_BORE_FLAT_CENTS
    if order["order_type"] == "TEMPORARY":
        base = max(base, Decimal(str(TEMPORARY_MIN_CENTS)))

    allowance = Decimal(str(FREE_ALLOWANCE_FT * LINE_EXTENSION_CENTS_PER_FT))
    excess = base - allowance
    atc = max(Decimal("0"), excess)

    if excess > Decimal(str(OVERHEAD_THRESHOLD_CENTS)):
        overhead = Decimal(str(OVERHEAD_PCT)) * (excess - Decimal(str(OVERHEAD_THRESHOLD_CENTS)))
        atc += overhead

    order["aid_to_construction_cents"] = int(atc.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Auto-create ROW if none exists
    existing_rows = [r for r in store.right_of_way_agreements.values()
                     if r.get("service_location_id") == order["service_location_id"]]
    if not existing_rows:
        row = new_common({
            "service_location_id": order["service_location_id"],
            "status": "REQUESTED",
            "easement_width_ft": 0,
            "consented_at": None,
            "recorded_at": None,
        })
        store.right_of_way_agreements[row["id"]] = row
        order["row_agreement_id"] = row["id"]

    order["status"] = "ESTIMATED"
    touch(order)
    return order


def invoice_atc(order_id):
    order = get_service_order(order_id)
    if order["status"] != "ESTIMATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be ESTIMATED to invoice ATC")
    if order.get("aid_to_construction_cents", 0) <= 0:
        raise ApiError("ERR_ATC_ZERO_NOT_INVOICABLE", 409,
                       "Cannot invoice aid-to-construction of zero; use mark-paid directly")
    order["status"] = "ATC_INVOICED"
    touch(order)
    return order


def mark_paid(order_id):
    order = get_service_order(order_id)
    if order["status"] == "ESTIMATED":
        if order.get("aid_to_construction_cents", 0) != 0:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "ESTIMATED -> PAID requires aid_to_construction_cents == 0")
        order["status"] = "PAID"
    elif order["status"] == "ATC_INVOICED":
        order["status"] = "PAID"
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order must be ESTIMATED or ATC_INVOICED to mark paid")
    touch(order)
    return order


def schedule_order(order_id):
    order = get_service_order(order_id)
    if order["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be PAID to schedule")

    # Check ROW is RECORDED or CONDEMNATION
    loc_id = order["service_location_id"]
    rows = [r for r in store.right_of_way_agreements.values()
            if r.get("service_location_id") == loc_id
            and r.get("status") in ("RECORDED", "CONDEMNATION")]
    if not rows:
        raise ApiError("ERR_ROW_NOT_RECORDED", 409,
                       "Right-of-way agreement not in RECORDED (or CONDEMNATION) status")

    order["status"] = "SCHEDULED"
    touch(order)
    return order


def construct_order(order_id):
    order = get_service_order(order_id)
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be SCHEDULED to construct")
    order["status"] = "CONSTRUCTED"
    touch(order)
    return order


def cancel_order(order_id):
    order = get_service_order(order_id)
    if order["status"] not in ("DRAFT", "ESTIMATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order must be DRAFT or ESTIMATED to cancel")

    # Auto-release ROW if still in REQUESTED
    if order.get("row_agreement_id"):
        row = store.right_of_way_agreements.get(order["row_agreement_id"])
        if row and row["status"] == "REQUESTED":
            row["status"] = "RELEASED"
            touch(row)

    order["status"] = "CANCELLED"
    touch(order)
    return order
