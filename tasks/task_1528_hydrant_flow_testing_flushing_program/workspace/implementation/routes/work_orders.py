"""RepairWorkOrder endpoints: create, list, get, part-lines, submit, approve
(OCC + fiscal gates), reject, complete, cancel."""
from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_HYDRANT_NOT_FOUND,
    ERR_INSUFFICIENT_PART_QUANTITY,
    ERR_PART_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_WORK_ORDER_BUDGET_EXCEEDED,
    ERR_WORK_ORDER_NOT_APPROVED,
    ERR_WORK_ORDER_NOT_CANCELLABLE,
    ERR_WORK_ORDER_NOT_DRAFT,
    ERR_WORK_ORDER_NOT_FOUND,
    ERR_WORK_ORDER_NOT_SUBMITTED,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import work_order_view
from services import part_available_qty, work_order_total
from validation import F, paginate, validate_body, validate_empty_body

bp = Blueprint("work_orders", __name__)


def get_work_order_or_404(work_order_id):
    w = db.store.work_orders.get(work_order_id)
    if w is None:
        raise not_found(ERR_WORK_ORDER_NOT_FOUND, "RepairWorkOrder")
    return w


@bp.post("/work-orders")
def create_work_order():
    user_id, role = auth()
    body = validate_body([
        F("hydrant_id", "str"),
        F("description", "str"),
        F("budget_cap_cents", "int", required=False, nullable=True),
    ])
    require_role(role, {"FieldOperator"})
    if body["hydrant_id"] not in db.store.hydrants:
        raise not_found(ERR_HYDRANT_NOT_FOUND, "Hydrant")
    wo = new_base()
    wo.update({
        "hydrant_id": body["hydrant_id"],
        "source_inspection_id": None,
        "description": body["description"],
        "budget_cap_cents": body["budget_cap_cents"],
        "status": "DRAFT",
        "part_lines": [],
        "quoted_subtotal_cents": None,
        "quoted_discount_cents": None,
        "quoted_fee_cents": None,
        "quoted_total_cents": None,
        "actual_total_cents": None,
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "last_rejection_reason": None,
    })
    db.store.work_orders[wo["id"]] = wo
    return success_object(work_order_view(wo), code=201)


@bp.get("/work-orders")
def list_work_orders():
    auth_any()
    items = list(db.store.work_orders.values())
    for field in ("hydrant_id", "source_inspection_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [w for w in items if w[field] == value]
    page, meta = paginate(items)
    return success_list([work_order_view(w) for w in page], meta)


@bp.get("/work-orders/<work_order_id>")
def get_work_order(work_order_id):
    auth_any()
    return success_object(work_order_view(get_work_order_or_404(work_order_id)))


@bp.post("/work-orders/<work_order_id>/part-lines")
def add_part_line(work_order_id):
    user_id, role = auth()
    body = validate_body([
        F("part_id", "str"),
        F("qty", "int"),
    ])
    if body["qty"] <= 0:
        from errors import invalid_request
        raise invalid_request("qty must be > 0")
    require_role(role, {"FieldOperator"})
    wo = get_work_order_or_404(work_order_id)
    if body["part_id"] not in db.store.parts:
        raise not_found(ERR_PART_NOT_FOUND, "Part")
    if wo["status"] != "DRAFT":
        raise ApiError(
            ERR_WORK_ORDER_NOT_DRAFT,
            "Part lines can only be added while the work order is DRAFT",
            409,
        )
    wo["part_lines"].append({
        "part_id": body["part_id"],
        "qty": body["qty"],
        "unit_price_cents": None,  # snapshot at approval
        "status": "PENDING",
    })
    touch(wo)
    return success_object(work_order_view(wo))


@bp.post("/work-orders/<work_order_id>/submit")
def submit_work_order(work_order_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"FieldOperator"})
    wo = get_work_order_or_404(work_order_id)
    if wo["status"] != "DRAFT":
        raise ApiError(ERR_WORK_ORDER_NOT_DRAFT, "Work order must be DRAFT to submit", 409)
    wo["status"] = "SUBMITTED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.post("/work-orders/<work_order_id>/approve")
def approve_work_order(work_order_id):
    user_id, role = auth()
    body = validate_body([F("expected_work_order_version", "int")])
    require_role(role, {"UtilitySupervisor"})
    wo = get_work_order_or_404(work_order_id)
    # Segregation of duties (priority 6) precedes OCC (7) and state (8)
    if user_id == wo["created_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Approver must differ from the work order creator",
            403,
        )
    if body["expected_work_order_version"] != wo["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_work_order_version does not match the work order's current version",
            412,
        )
    if wo["status"] != "SUBMITTED":
        raise ApiError(
            ERR_WORK_ORDER_NOT_SUBMITTED,
            "Work order must be SUBMITTED to approve",
            409,
        )
    # Fiscal checks, in order: part availability, then budget cap. All
    # preconditions are checked before any mutation (atomic approval).
    for line in wo["part_lines"]:
        if part_available_qty(line["part_id"]) < line["qty"]:
            raise ApiError(
                ERR_INSUFFICIENT_PART_QUANTITY,
                "Part available_qty is below a line's qty",
                422,
            )
    # Quoted variant: unit prices snapshot from current Part.unit_price_cents
    price_pairs = [
        (line["qty"], db.store.parts[line["part_id"]]["unit_price_cents"])
        for line in wo["part_lines"]
    ]
    subtotal, discount, fee, total = work_order_total(price_pairs)
    if wo["budget_cap_cents"] is not None and total > wo["budget_cap_cents"]:
        raise ApiError(
            ERR_WORK_ORDER_BUDGET_EXCEEDED,
            "quoted_total_cents exceeds budget_cap_cents",
            422,
        )
    for line in wo["part_lines"]:
        line["unit_price_cents"] = db.store.parts[line["part_id"]]["unit_price_cents"]
        line["status"] = "RESERVED"
    wo["quoted_subtotal_cents"] = subtotal
    wo["quoted_discount_cents"] = discount
    wo["quoted_fee_cents"] = fee
    wo["quoted_total_cents"] = total
    wo["approved_by_user_id"] = user_id
    wo["status"] = "APPROVED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.post("/work-orders/<work_order_id>/reject")
def reject_work_order(work_order_id):
    user_id, role = auth()
    body = validate_body([F("rejection_reason", "str")])
    require_role(role, {"UtilitySupervisor"})
    wo = get_work_order_or_404(work_order_id)
    if wo["status"] != "SUBMITTED":
        raise ApiError(
            ERR_WORK_ORDER_NOT_SUBMITTED,
            "Work order must be SUBMITTED to reject",
            409,
        )
    wo["last_rejection_reason"] = body["rejection_reason"]
    wo["status"] = "DRAFT"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.post("/work-orders/<work_order_id>/complete")
def complete_work_order(work_order_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"FieldOperator"})
    wo = get_work_order_or_404(work_order_id)
    if wo["status"] != "APPROVED":
        raise ApiError(
            ERR_WORK_ORDER_NOT_APPROVED,
            "Work order must be APPROVED to complete",
            409,
        )
    # Actual variant: unit prices are the CURRENT Part.unit_price_cents
    price_pairs = [
        (line["qty"], db.store.parts[line["part_id"]]["unit_price_cents"])
        for line in wo["part_lines"]
    ]
    _, _, _, actual_total = work_order_total(price_pairs)
    touched_parts = set()
    for line in wo["part_lines"]:
        line["status"] = "CONSUMED"
        part = db.store.parts[line["part_id"]]
        part["on_hand_qty"] -= line["qty"]
        touched_parts.add(part["id"])
    for part_id in touched_parts:
        touch(db.store.parts[part_id])
    wo["actual_total_cents"] = actual_total
    wo["status"] = "COMPLETED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.post("/work-orders/<work_order_id>/cancel")
def cancel_work_order(work_order_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"FieldOperator"})
    wo = get_work_order_or_404(work_order_id)
    if wo["status"] not in ("DRAFT", "SUBMITTED", "APPROVED"):
        raise ApiError(
            ERR_WORK_ORDER_NOT_CANCELLABLE,
            "Work order must be DRAFT, SUBMITTED, or APPROVED to cancel",
            409,
        )
    if wo["status"] == "APPROVED":
        # COMPENSATION: release reservations; on_hand_qty untouched
        for line in wo["part_lines"]:
            line["status"] = "RELEASED"
    wo["status"] = "CANCELLED"
    touch(wo)
    return success_object(work_order_view(wo))
