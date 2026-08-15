from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import ApiError
from helpers import (
    base_fields,
    get_req_or_404,
    get_wo_or_404,
    list_response,
    pub,
    touch,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("requisitions", __name__, url_prefix="/mro")

ACTIVE_SET = ("REQUESTED", "PMA_PENDING_CUSTOMER", "APPROVED", "RECEIVED")


@bp.route("/work-orders/<workOrderId>/parts-requisitions", methods=["POST"])
@require_roles("Technician")
def create_requisition(workOrderId):
    wo = get_wo_or_404(workOrderId)
    body = validate_body(
        get_json_body(),
        {
            "part_number": ("str", True),
            "quantity": ("int", True, None, 1, None),
            "requested_source": ("enum", True, ["OEM", "PMA"]),
        },
    )
    rq = dict(base_fields())
    rq.update(
        {
            "work_order_id": wo["id"],
            "part_number": body["part_number"],
            "quantity": body["quantity"],
            "requested_source": body["requested_source"],
            "approved_source": None,
            "status": "REQUESTED" if body["requested_source"] == "OEM" else "PMA_PENDING_CUSTOMER",
            "unit_cost_cents": None,
            "extended_price_cents": None,
        }
    )
    store.requisitions[rq["id"]] = rq
    if wo["status"] == "REPAIR_IN_PROGRESS":
        wo["status"] = "AWAITING_PARTS"
        touch(wo)
    return ok(pub(rq), 201)


@bp.route("/work-orders/<workOrderId>/parts-requisitions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_requisitions(workOrderId):
    wo = get_wo_or_404(workOrderId)
    return list_response([r for r in store.requisitions.values() if r["work_order_id"] == wo["id"]])


@bp.route("/parts-requisitions/<requisitionId>/source-approval", methods=["POST"])
@require_roles("PartsBuyer")
def source_approval(requisitionId):
    rq = get_req_or_404(requisitionId)
    body = validate_body(
        get_json_body(),
        {"approved": ("bool", True), "source_override": ("enum", False, ["OEM", "PMA"])},
    )
    approved = body["approved"]
    override = body["source_override"]
    prev = rq["status"]
    if prev in ("REQUESTED", "SOURCE_REJECTED"):
        if approved:
            rq["status"] = "APPROVED"
            rq["approved_source"] = (
                override if (prev == "SOURCE_REJECTED" and override is not None) else "OEM"
            )
        else:
            rq["status"] = "SOURCE_REJECTED"
    elif prev == "PMA_REJECTED":
        if not approved:
            raise ApiError(
                "ERR_REQUISITION_INVALID_STATE", 409, "Requisition not in an approvable state"
            )
        if override != "OEM":
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "source_override must be OEM from PMA_REJECTED"
            )
        rq["status"] = "APPROVED"
        rq["approved_source"] = "OEM"
    else:
        raise ApiError(
            "ERR_REQUISITION_INVALID_STATE", 409, "Requisition not in an approvable state"
        )
    touch(rq)
    return ok(pub(rq))


@bp.route("/parts-requisitions/<requisitionId>/pma-approval", methods=["POST"])
@require_roles("Customer")
def pma_approval(requisitionId):
    rq = get_req_or_404(requisitionId)
    body = validate_body(get_json_body(), {"approved": ("bool", True)})
    if rq["status"] != "PMA_PENDING_CUSTOMER":
        raise ApiError(
            "ERR_REQUISITION_INVALID_STATE", 409, "Requisition not in PMA_PENDING_CUSTOMER"
        )
    wo = store.work_orders[rq["work_order_id"]]
    if request.user_id != wo["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the work-order customer")
    if body["approved"]:
        rq["status"] = "APPROVED"
        rq["approved_source"] = "PMA"
    else:
        rq["status"] = "PMA_REJECTED"
    touch(rq)
    return ok(pub(rq))


@bp.route("/parts-requisitions/<requisitionId>/receive", methods=["POST"])
@require_roles("PartsBuyer")
def receive_requisition(requisitionId):
    rq = get_req_or_404(requisitionId)
    body = validate_body(get_json_body(), {"unit_cost_cents": ("int", True, None, 0, None)})
    if rq["status"] != "APPROVED":
        raise ApiError("ERR_REQUISITION_INVALID_STATE", 409, "Requisition not in APPROVED")
    unit_cost = body["unit_cost_cents"]
    # Markup tier keyed on unit_cost_cents (per-line rounding pinned).
    if unit_cost <= 100000:
        factor = Decimal("1.25")
    elif unit_cost <= 1000000:
        factor = Decimal("1.15")
    else:
        factor = Decimal("1.10")
    extended = int(
        (Decimal(rq["quantity"]) * Decimal(unit_cost) * factor).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    rq["unit_cost_cents"] = unit_cost
    rq["extended_price_cents"] = extended
    rq["status"] = "RECEIVED"
    touch(rq)
    return ok(pub(rq))


@bp.route("/parts-requisitions/<requisitionId>/issue", methods=["POST"])
@require_roles("Technician")
def issue_requisition(requisitionId):
    rq = get_req_or_404(requisitionId)
    if rq["status"] != "RECEIVED":
        raise ApiError("ERR_REQUISITION_INVALID_STATE", 409, "Requisition not in RECEIVED")
    wo = store.work_orders[rq["work_order_id"]]
    if wo["status"] not in ("REPAIR_IN_PROGRESS", "AWAITING_PARTS"):
        raise ApiError(
            "ERR_WORK_ORDER_INVALID_STATE",
            409,
            "Work order not in REPAIR_IN_PROGRESS or AWAITING_PARTS",
        )
    rq["status"] = "ISSUED"
    touch(rq)
    # Ledger sync: per-line rounded extended price added to the work order.
    wo["parts_charge_cents"] = (wo["parts_charge_cents"] or 0) + (rq["extended_price_cents"] or 0)
    if wo["status"] == "AWAITING_PARTS":
        still_active = any(
            other["work_order_id"] == wo["id"] and other["status"] in ACTIVE_SET
            for other in store.requisitions.values()
        )
        if not still_active:
            wo["status"] = "REPAIR_IN_PROGRESS"
    touch(wo)
    return ok(pub(rq))
