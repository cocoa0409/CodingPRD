"""TranscriptOrder + OrderLineItem-on-order endpoints."""
from flask import Blueprint, request

from db import DB, new_id, logical_now_iso
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    DELIVERY_KINDS,
    ORDER_KINDS,
    _cancel_order_internal,
    advance_order_ready,
    compute_quote,
    emit_audit,
    get_order,
    get_recipient,
    idvs_of_order,
    is_rush_qualified,
    lines_of_order,
    logical_now,
    order_blocks_on_hold,
    payments_of_order,
    ref_lookup,
    ser_line_item,
    ser_order,
    sorted_created,
    stamp,
    touch,
)
from util import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    body,
    pagination_args,
    reject_unknown_fields,
    required,
)

bp = Blueprint("orders", __name__)

READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]
QUOTE_ROLES = ["RegistrarAdmin", "RegistrarOperator", "Student"]


@bp.post("/registrar/orders")
def create_order():
    user_id, role = auth(["Student"])
    data = body()
    reject_unknown_fields(data, {"student_id", "order_kind", "rush_requested"})
    student_id = required(data, "student_id")
    order_kind = as_enum(required(data, "order_kind"), "order_kind", ORDER_KINDS)
    rush_requested = data.get("rush_requested", False)
    if not isinstance(rush_requested, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "rush_requested must be a boolean")
    ref_lookup("students", student_id, "Student")

    rec = {
        "id": new_id(),
        "student_id": student_id,
        "order_kind": order_kind,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "rush_requested": rush_requested,
        "rush_qualified": False,
        "quoted_fee_cents": 0,
        "final_fee_cents": 0,
        "submitted_at": None,
        "cancelled_reason": None,
        "reissue_of_order_id": None,
    }
    stamp(rec)
    DB["orders"][rec["id"]] = rec
    emit_audit("TranscriptOrder", rec["id"], role, user_id, "ORDER_CREATED")
    return ok(ser_order(rec), status=201)


@bp.get("/registrar/orders")
def list_orders():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["orders"].values())
    sid = request.args.get("student_id")
    if sid is not None:
        items = [o for o in items if o["student_id"] == sid]
    fs = request.args.get("fulfillment_status")
    if fs is not None:
        items = [o for o in items if o["fulfillment_status"] == fs]
    ps = request.args.get("payment_status")
    if ps is not None:
        items = [o for o in items if o["payment_status"] == ps]
    ok_kind = request.args.get("order_kind")
    if ok_kind is not None:
        items = [o for o in items if o["order_kind"] == ok_kind]
    ro = request.args.get("reissue_of_order_id")
    if ro is not None:
        items = [o for o in items if o["reissue_of_order_id"] == ro]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_order(o) for o in page], total, limit, offset)


@bp.get("/registrar/orders/<oid>")
def get_one_order(oid):
    auth(READ_ROLES)
    return ok(ser_order(get_order(oid)))


@bp.get("/registrar/orders/<oid>/quote-preview")
def quote_preview(oid):
    auth(QUOTE_ROLES)
    order = get_order(oid)
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Quote preview requires DRAFT order")
    now = logical_now()
    rush = is_rush_qualified(order, now)
    total, schedule = compute_quote(order, now, rush_qualified=rush)
    if schedule is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "No active fee schedule covers the current clock"
        )
    return ok(
        {
            "quoted_fee_cents": total,
            "rush_qualified": rush,
            "schedule_code": schedule["code"],
        }
    )


@bp.post("/registrar/orders/<oid>/line-items")
def add_line_item(oid):
    user_id, role = auth(["Student"])
    order = get_order(oid)
    data = body()
    reject_unknown_fields(
        data,
        {
            "recipient_id",
            "delivery_kind",
            "quantity",
            "expected_order_version",
            "archived_retrieval_id",
        },
    )
    recipient_id = required(data, "recipient_id")
    delivery_kind = as_enum(
        required(data, "delivery_kind"), "delivery_kind", DELIVERY_KINDS
    )
    quantity = as_int(required(data, "quantity"), "quantity")
    if quantity < 1 or quantity > 10:
        raise ApiError("ERR_INVALID_REQUEST", 400, "quantity must be between 1 and 10")
    expected = data.get("expected_order_version")
    if expected is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_order_version is required"
        )
    expected = as_int(expected, "expected_order_version")
    archived_retrieval_id = data.get("archived_retrieval_id")

    # FK existence.
    recipient = ref_lookup("recipients", recipient_id, "Recipient")
    if archived_retrieval_id is not None:
        ref_lookup("archived_retrievals", archived_retrieval_id, "ArchivedRecordRetrieval")

    # State: line-item mutation only on DRAFT orders.
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409, "Order is not in DRAFT")

    # OCC.
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Order version has advanced")

    # Recipient must be active at add time.
    if not recipient["active"]:
        raise ApiError(
            "ERR_RECIPIENT_INACTIVE", 422, "Recipient is no longer active"
        )

    # Routing validity: recipient.kind must match delivery_kind and the
    # kind-specific routing field must be populated.
    _check_routing(recipient, delivery_kind)

    rec = {
        "id": new_id(),
        "order_id": order["id"],
        "recipient_id": recipient_id,
        "delivery_kind": delivery_kind,
        "quantity": quantity,
        "unit_price_cents": 0,
        "line_status": "PENDING",
        "tracking_ref": None,
        "archived_retrieval_id": archived_retrieval_id,
    }
    stamp(rec)
    DB["order_line_items"][rec["id"]] = rec

    # Recompute rush qualification + provisional quote against current clock.
    # The quote pipeline stores each line's per-line rounded unit price on the
    # line (PRD 3.5: "that per-line rounded figure is stored on the line as
    # unit_price_cents"), including the provisional recompute at add time.
    now = logical_now()
    order["rush_qualified"] = is_rush_qualified(order, now)
    total, schedule = compute_quote(order, now, persist_unit_prices=True)
    if schedule is not None:
        order["quoted_fee_cents"] = total
    touch(order)
    return ok(ser_line_item(rec), status=201)


def _check_routing(recipient, delivery_kind):
    if recipient["kind"] != delivery_kind:
        raise ApiError(
            "ERR_RECIPIENT_ROUTING_INVALID",
            422,
            "Recipient kind does not match delivery_kind",
        )
    needed = {
        "ELECTRONIC_NETWORK": "network_code",
        "EMAIL_PDF": "email_address",
        "PAPER_MAIL": "postal_address",
        "PICKUP": None,
    }[delivery_kind]
    if needed is not None and not recipient.get(needed):
        raise ApiError(
            "ERR_RECIPIENT_ROUTING_INVALID",
            422,
            f"Recipient is missing required routing field {needed}",
        )


@bp.get("/registrar/orders/<oid>/line-items")
def list_order_line_items(oid):
    auth(READ_ROLES)
    order = get_order(oid)
    limit, offset = pagination_args()
    items = lines_of_order(order["id"])
    st = request.args.get("line_status")
    if st is not None:
        items = [l for l in items if l["line_status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_line_item(l) for l in page], total, limit, offset)


@bp.post("/registrar/orders/<oid>/submit")
def submit_order(oid):
    user_id, role = auth(["Student"])
    order = get_order(oid)
    data = body()
    reject_unknown_fields(data, {"expected_order_version"})
    expected = data.get("expected_order_version")
    if expected is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_order_version is required"
        )
    expected = as_int(expected, "expected_order_version")

    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not in DRAFT")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Order version has advanced")

    lines = lines_of_order(order["id"])
    if len(lines) < 1:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Order must carry at least one line item"
        )

    # Identity verification gate.
    verified = any(v["status"] == "VERIFIED" for v in idvs_of_order(order["id"]))
    if not verified:
        raise ApiError(
            "ERR_IDENTITY_NOT_VERIFIED",
            422,
            "Order submission requires a VERIFIED IdentityVerification",
        )

    now = logical_now()
    order["submitted_at"] = logical_now_iso()
    order["rush_qualified"] = is_rush_qualified(order, now)
    total, schedule = compute_quote(order, now, persist_unit_prices=True)
    if schedule is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "No active fee schedule covers the submit clock"
        )
    order["quoted_fee_cents"] = total
    order["final_fee_cents"] = total
    order["fulfillment_status"] = "SUBMITTED"
    touch(order)
    emit_audit("TranscriptOrder", order["id"], role, user_id, "ORDER_SUBMIT")

    # Immediate routing onward from SUBMITTED.
    if order_blocks_on_hold(order):
        order["fulfillment_status"] = "HOLD_CHECK"
        touch(order)
    else:
        advance_order_ready(order)
    return ok(ser_order(order))


@bp.post("/registrar/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = auth(["Student"])
    order = get_order(oid)
    data = body()
    reject_unknown_fields(data, {"cancelled_reason"})
    reason = data.get("cancelled_reason")
    if reason is not None:
        reason = as_str(reason, "cancelled_reason")

    if order["fulfillment_status"] not in (
        "HOLD_CHECK",
        "READY_TO_FULFILL",
        "IDENTITY_PENDING",
    ):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Order cannot be cancelled from its current state",
        )
    if order["payment_status"] not in ("UNPAID", "AUTHORIZED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Order payment state does not admit cancellation",
        )
    order["cancelled_reason"] = reason
    _cancel_order_internal(order)
    emit_audit("TranscriptOrder", order["id"], role, user_id, "ORDER_CANCELLED")
    return ok(ser_order(order))
