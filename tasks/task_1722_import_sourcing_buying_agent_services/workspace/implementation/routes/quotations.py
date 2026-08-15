"""Quotations: create, list, get, counter (OCC), accept (creates PO), reject."""

from flask import Blueprint, request

from db import new_id, parse_dt, public, stamp_new, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    opt_int,
    paginate,
    req_delivery_month,
    req_int,
    require_roles,
    sorted_created,
)
from response import success_list, success_object
from services.domain import (
    NEGOTIATION_ROUND_CAP,
    apply_posture,
    committed_units,
    compute_commission,
    compute_posture,
)

bp = Blueprint("quotations", __name__)

QUOTATION_LIVE_STATES = ("OPEN", "COUNTERED")
GRADES_ALLOWED = ("A", "B")


def _get_quotation(quotationId):
    return get_or_404(
        store.quotations, quotationId, "ERR_QUOTATION_NOT_FOUND", "Quotation"
    )


def _check_version(data, quotation):
    expected = data.get("expected_quotation_version")
    if expected is None:
        raise ApiError(
            "ERR_VALIDATION",
            "Missing required field: expected_quotation_version",
            400,
        )
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            "ERR_VALIDATION", "expected_quotation_version must be an integer", 400
        )
    if expected != quotation["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_quotation_version does not match the current version",
            412,
        )


@bp.route("/sourcing/sourcing-requests/<srId>/quotations", methods=["POST"])
def create_quotation(srId):
    uid, _ = require_roles("FactoryRep")
    sr = get_or_404(
        store.sourcing_requests, srId, "ERR_SOURCING_REQUEST_NOT_FOUND", "SourcingRequest"
    )
    data = body_json()
    unit_price_cents = req_int(data, "unit_price_cents")
    moq = req_int(data, "moq")
    lead_time_days = req_int(data, "lead_time_days")
    valid_until_raw = data.get("valid_until")
    if not isinstance(valid_until_raw, str):
        raise ApiError("ERR_VALIDATION", "Missing required field: valid_until", 400)
    valid_until_dt = parse_dt(valid_until_raw)
    if valid_until_dt is None:
        raise ApiError(
            "ERR_VALIDATION", "valid_until must be an ISO 8601 datetime", 400
        )
    if sr["status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError(
            "ERR_SR_NOT_ACTIVE", "SourcingRequest is not OPEN or IN_PROGRESS", 409
        )
    factory = store.factories.get(uid)
    if factory is None:
        raise ApiError("ERR_FACTORY_NOT_FOUND", "Factory not found: %s" % uid, 404)
    if factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_SUSPENDED", "Factory is SUSPENDED", 409)
    if factory["latest_audit_grade"] not in GRADES_ALLOWED:
        raise ApiError(
            "ERR_FACTORY_GRADE_INSUFFICIENT",
            "factory.latest_audit_grade is not in {A, B}",
            409,
        )
    for existing in store.quotations.values():
        if (
            existing["sourcing_request_id"] == sr["id"]
            and existing["factory_id"] == factory["id"]
            and existing["status"] in QUOTATION_LIVE_STATES
        ):
            raise ApiError(
                "ERR_DUPLICATE_QUOTATION",
                "A non-terminal quotation already exists for this "
                "(sourcing_request, factory) pair",
                409,
            )
    quotation = stamp_new(
        {
            "id": new_id(),
            "sourcing_request_id": sr["id"],
            "factory_id": factory["id"],
            "unit_price_cents": unit_price_cents,
            "moq": moq,
            "lead_time_days": lead_time_days,
            "valid_until": valid_until_raw,
            "round_count": 0,
            "last_actor_role": "FACTORY",
            "purchase_order_id": None,
            "status": "OPEN",
            "_valid_until_dt": valid_until_dt,
        }
    )
    store.quotations[quotation["id"]] = quotation
    if sr["status"] == "OPEN":
        sr["status"] = "IN_PROGRESS"
        touch(sr)
    return success_object(public(quotation), 201)


@bp.route("/sourcing/quotations", methods=["GET"])
def list_quotations():
    require_roles(*ALL_ROLES)
    items = list(store.quotations.values())
    sr_id = request.args.get("sourcing_request_id")
    factory_id = request.args.get("factory_id")
    po_id = request.args.get("purchase_order_id")
    status = request.args.get("status")
    if sr_id is not None:
        items = [q for q in items if q["sourcing_request_id"] == sr_id]
    if factory_id is not None:
        items = [q for q in items if q["factory_id"] == factory_id]
    if po_id is not None:
        items = [q for q in items if q["purchase_order_id"] == po_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(q) for q in page], limit, offset, total)


@bp.route("/sourcing/quotations/<quotationId>", methods=["GET"])
def get_quotation(quotationId):
    require_roles(*ALL_ROLES)
    return success_object(public(_get_quotation(quotationId)))


@bp.route("/sourcing/quotations/<quotationId>/counter", methods=["POST"])
def counter_quotation(quotationId):
    uid, role = require_roles("BuyerManager", "FactoryRep")
    quotation = _get_quotation(quotationId)
    data = body_json()
    unit_price_cents = req_int(data, "unit_price_cents")
    new_valid_until_raw = data.get("valid_until")
    new_valid_until_dt = None
    if new_valid_until_raw is not None:
        if not isinstance(new_valid_until_raw, str):
            raise ApiError("ERR_VALIDATION", "valid_until must be a string", 400)
        new_valid_until_dt = parse_dt(new_valid_until_raw)
        if new_valid_until_dt is None:
            raise ApiError(
                "ERR_VALIDATION", "valid_until must be an ISO 8601 datetime", 400
            )
    # PRD §3.4 order: state -> OCC -> correct side / ownership -> cap -> expiry.
    if quotation["status"] not in QUOTATION_LIVE_STATES:
        raise ApiError(
            "ERR_QUOTATION_NOT_OPEN", "Quotation is not OPEN or COUNTERED", 409
        )
    _check_version(data, quotation)
    last_side = quotation["last_actor_role"]
    caller_side = "BUYER" if role == "BuyerManager" else "FACTORY"
    if caller_side == last_side:
        raise ApiError(
            "ERR_WRONG_COUNTER_PARTY",
            "The side that set the current terms cannot counter its own offer",
            409,
        )
    if role == "BuyerManager":
        sr = store.sourcing_requests.get(quotation["sourcing_request_id"])
        if sr is None or sr["buyer_id"] != uid:
            raise ApiError(
                "ERR_OWNERSHIP_SCOPE_VIOLATION",
                "Caller does not own the sourcing request",
                403,
            )
    else:
        if quotation["factory_id"] != uid:
            raise ApiError(
                "ERR_OWNERSHIP_SCOPE_VIOLATION",
                "Caller does not belong to the quoting factory",
                403,
            )
    if quotation["round_count"] >= NEGOTIATION_ROUND_CAP:
        raise ApiError(
            "ERR_NEGOTIATION_ROUND_EXCEEDED",
            "round_count has reached the negotiation round cap",
            409,
        )
    if store.clock > quotation["_valid_until_dt"]:
        raise ApiError(
            "ERR_QUOTATION_EXPIRED", "The logical clock is past valid_until", 409
        )
    quotation["round_count"] += 1
    quotation["last_actor_role"] = caller_side
    quotation["unit_price_cents"] = unit_price_cents
    if new_valid_until_raw is not None:
        quotation["valid_until"] = new_valid_until_raw
        quotation["_valid_until_dt"] = new_valid_until_dt
    quotation["status"] = "COUNTERED" if caller_side == "BUYER" else "OPEN"
    touch(quotation)
    return success_object(public(quotation))


@bp.route("/sourcing/quotations/<quotationId>/accept", methods=["POST"])
def accept_quotation(quotationId):
    uid, _ = require_roles("BuyerManager")
    quotation = _get_quotation(quotationId)
    data = body_json()
    ordered_qty = req_int(data, "ordered_qty")
    delivery_month = req_delivery_month(data)
    freight_cents = opt_int(data, "freight_cents", default=0)
    insurance_cents = opt_int(data, "insurance_cents", default=0)
    # PRD §3.4 order: state -> ownership -> OCC -> expiry -> factory ACTIVE ->
    # grade -> MOQ -> capacity.
    if quotation["status"] not in QUOTATION_LIVE_STATES:
        raise ApiError(
            "ERR_QUOTATION_NOT_OPEN", "Quotation is not OPEN or COUNTERED", 409
        )
    sr = store.sourcing_requests.get(quotation["sourcing_request_id"])
    if sr is None or sr["buyer_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not own the sourcing request",
            403,
        )
    _check_version(data, quotation)
    if store.clock > quotation["_valid_until_dt"]:
        raise ApiError(
            "ERR_QUOTATION_EXPIRED", "The logical clock is past valid_until", 409
        )
    factory = store.factories.get(quotation["factory_id"])
    if factory is None:
        raise ApiError(
            "ERR_FACTORY_NOT_FOUND", "Factory not found: %s" % quotation["factory_id"], 404
        )
    if factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_SUSPENDED", "Factory is SUSPENDED", 409)
    if factory["latest_audit_grade"] not in GRADES_ALLOWED:
        raise ApiError(
            "ERR_FACTORY_GRADE_INSUFFICIENT",
            "factory.latest_audit_grade is not in {A, B}",
            409,
        )
    if ordered_qty < quotation["moq"]:
        raise ApiError(
            "ERR_QTY_BELOW_MOQ", "ordered_qty is below the quotation moq", 422
        )
    if (
        committed_units(factory["id"], delivery_month) + ordered_qty
        > factory["monthly_capacity_units"]
    ):
        raise ApiError(
            "ERR_CAPACITY_EXCEEDED",
            "Capacity ceiling exceeded for the delivery month",
            422,
        )
    total_cents = ordered_qty * quotation["unit_price_cents"]
    po = stamp_new(
        {
            "id": new_id(),
            "quotation_id": quotation["id"],
            "sourcing_request_id": quotation["sourcing_request_id"],
            "buyer_id": sr["buyer_id"],
            "factory_id": factory["id"],
            "assigned_agent_id": sr["assigned_agent_id"],
            "ordered_qty": ordered_qty,
            "unit_price_cents": quotation["unit_price_cents"],
            "total_cents": total_cents,
            "delivery_month": delivery_month,
            "freight_cents": freight_cents,
            "insurance_cents": insurance_cents,
            "shipped_qty": 0,
            "cancelled_qty": 0,
            "open_qty": ordered_qty,
            "milestone_plan_locked": False,
            "progress_pct": 0,
            "production_status": "PLACED",
            "latest_psi_result": "NONE",
            "document_status": "PENDING",
            "ship_blocked": False,
            "provisional_commission_cents": 0,
            "final_commission_cents": None,
            "commission_rate_bp": 0,
            "remaining_payable_cents": total_cents,
            "status": "ACTIVE",
        }
    )
    store.purchase_orders[po["id"]] = po
    # Provisional commission: tier basis includes this PO (already stored).
    commission, rate_bp = compute_commission(po, sr)
    po["provisional_commission_cents"] = commission
    po["commission_rate_bp"] = rate_bp
    # Posture recompute accounts for the new live PO (PRD §3.4 side effect).
    new_posture = compute_posture(factory["id"])
    po["ship_blocked"] = new_posture == "NON_COMPLIANT"
    apply_posture(factory, new_posture)
    quotation["status"] = "ACCEPTED"
    quotation["purchase_order_id"] = po["id"]
    touch(quotation)
    if sr["status"] in ("OPEN", "IN_PROGRESS"):
        sr["status"] = "PO_PLACED"
        touch(sr)
    # PRD §2.13: accept/counter/reject calls return HTTP 200 (the PO creation
    # is a side effect of the accept state transition, not a creation endpoint).
    return success_object(public(po), 200)


@bp.route("/sourcing/quotations/<quotationId>/reject", methods=["POST"])
def reject_quotation(quotationId):
    uid, _ = require_roles("BuyerManager")
    quotation = _get_quotation(quotationId)
    sr = store.sourcing_requests.get(quotation["sourcing_request_id"])
    if sr is None or sr["buyer_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not own the sourcing request",
            403,
        )
    if quotation["status"] not in QUOTATION_LIVE_STATES:
        raise ApiError(
            "ERR_QUOTATION_NOT_OPEN", "Quotation is not OPEN or COUNTERED", 409
        )
    quotation["status"] = "REJECTED"
    touch(quotation)
    return success_object(public(quotation))
