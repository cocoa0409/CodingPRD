"""Return requests: quantity checks, proration preview and two-person settlement."""

from flask import Blueprint

from db import db, make_row, sort_rows, touch
from errors import ApiError
from middleware import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_CUSTOMER,
    identity,
    lookup,
    paginate,
    parse_body,
    parse_pagination,
    parse_query,
    require_owner,
    require_role,
)
from response import list_response, object_response
from services import calc
from services.ledger import reconcile_customer_id, settled_settlements_on_order

bp = Blueprint("returns", __name__)

RETURN_REASONS = ("TORN_LENS", "PRESCRIPTION_CHANGE", "WRONG_PARAMETER")
RETURN_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "SETTLED")


def _settlement_for(order, row):
    return calc.return_settlement(
        order,
        row["reason"],
        row["unopened_boxes"],
        row["opened_box_used_counts"],
        row["torn_lens_count"],
    )


@bp.post("/return-requests")
def create_return_request():
    user_id, role = identity()
    body = parse_body(
        {
            "order_id": {"type": "uuid", "required": True},
            "customer_id": {"type": "uuid", "required": True},
            "reason": {"type": "enum", "values": RETURN_REASONS, "required": True},
            "unopened_boxes": {"type": "int", "min": 0, "default": 0},
            "opened_box_used_counts": {"type": "int_array", "min": 0, "default": []},
            "torn_lens_count": {"type": "int", "min": 0},
        }
    )
    if body["reason"] == "TORN_LENS" and body["torn_lens_count"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "A TORN_LENS return requires torn_lens_count.")
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    order = lookup("order", body["order_id"])
    customer = lookup("customer", body["customer_id"])
    require_owner(role, user_id, customer["id"])
    require_owner(role, user_id, order["customer_id"])

    total_boxes = order["boxes_od"] + order["boxes_os"]
    lenses_per_box = order["lenses_per_box_at_capture"]
    opened = body["opened_box_used_counts"] or []
    if body["unopened_boxes"] + len(opened) > total_boxes:
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_ORDER")
    if any(used > lenses_per_box for used in opened):
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_ORDER")
    if body["torn_lens_count"] is not None and body["torn_lens_count"] > total_boxes * lenses_per_box:
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_ORDER")

    row = make_row(
        {
            "order_id": body["order_id"],
            "customer_id": body["customer_id"],
            "reason": body["reason"],
            "unopened_boxes": body["unopened_boxes"],
            "opened_box_used_counts": opened,
            "torn_lens_count": body["torn_lens_count"],
            "settlement_mode": None,
            "settlement_cents": None,
            "settlement_channel": None,
            "approved_by_user_id": None,
            "settled_by_user_id": None,
            "rejection_reason": None,
            "status": "SUBMITTED",
        }
    )
    mode, cents, channel = _settlement_for(order, row)
    row["settlement_mode"] = mode
    row["settlement_cents"] = cents
    row["settlement_channel"] = channel
    db.return_requests[row["id"]] = row
    return object_response(row, 201)


@bp.get("/return-requests/<return_id>")
def get_return_request(return_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    row = lookup("return_request", return_id)
    require_owner(role, user_id, row["customer_id"])
    return object_response(row)


@bp.get("/return-requests")
def list_return_requests():
    user_id, role = identity()
    filters = parse_query(
        {
            "order_id": {"type": "string"},
            "customer_id": {"type": "string"},
            "reason": {"type": "enum", "values": RETURN_REASONS},
            "status": {"type": "enum", "values": RETURN_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    rows = list(db.return_requests.values())
    if role == ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == user_id]
    for field in ("order_id", "customer_id", "reason", "status"):
        if filters[field]:
            rows = [r for r in rows if r[field] == filters[field]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/return-requests/<return_id>/approve")
def approve_return_request(return_id):
    user_id, role = identity()
    parse_body({})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    row = lookup("return_request", return_id)
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    order = db.orders.get(row["order_id"])
    if order is None or order["fulfillment_state"] not in ("SHIPPED", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    mode, cents, channel = _settlement_for(order, row)
    row["status"] = "APPROVED"
    row["approved_by_user_id"] = user_id
    row["settlement_mode"] = mode
    row["settlement_cents"] = cents
    row["settlement_channel"] = channel
    touch(row)
    return object_response(row)


@bp.post("/return-requests/<return_id>/reject")
def reject_return_request(return_id):
    _, role = identity()
    body = parse_body({"rejection_reason": {"type": "string", "required": True}})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    row = lookup("return_request", return_id)
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["status"] = "REJECTED"
    row["rejection_reason"] = body["rejection_reason"]
    touch(row)
    return object_response(row)


@bp.post("/return-requests/<return_id>/settle")
def settle_return_request(return_id):
    user_id, role = identity()
    parse_body({})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    row = lookup("return_request", return_id)
    if row.get("approved_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if row["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    order = db.orders.get(row["order_id"])
    prior = settled_settlements_on_order(row["order_id"], exclude_id=row["id"])
    if order is not None and (row["settlement_cents"] or 0) + prior > order["total_cents"]:
        raise ApiError("ERR_REFUND_EXCEEDS_CAPTURE")
    row["status"] = "SETTLED"
    row["settled_by_user_id"] = user_id
    touch(row)
    reconcile_customer_id(row["customer_id"])
    offset = settled_settlements_on_order(row["order_id"])
    for claim in sort_rows(
        [c for c in db.reimbursement_claims.values() if c["order_id"] == row["order_id"]]
    ):
        if claim["status"] != "DRAFT":
            continue
        claim["refund_offset_cents"] = offset
        touch(claim)
    return object_response(row)
