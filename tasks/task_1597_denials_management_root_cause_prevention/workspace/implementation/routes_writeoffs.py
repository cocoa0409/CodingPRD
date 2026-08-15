"""Routes: write-off requests (create, approve, reject, revise, rescind)."""

from flask import Blueprint, g, request

from auth import require_roles
from cascades import apply_writeoff_approval, apply_writeoff_rescission
from db import store
from envelope import list_response, ok
from errors import (
    ApiError,
    ERR_AMOUNT_EXCEEDS_OPEN_BALANCE,
    ERR_APPROVAL_LIMIT_EXCEEDED,
    ERR_DENIAL_INVALID_STATE,
    ERR_NOT_REQUEST_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALIDATION,
    ERR_WRITE_OFF_ALREADY_PENDING,
    ERR_WRITE_OFF_EXCEEDS_CEILING,
    ERR_WRITE_OFF_NOT_PENDING,
)
from services import (
    PENDING_WRITEOFF_STATES,
    WRITE_OFF_CEILING_CENTS,
    create_writeoff_record,
    emit_event,
    find_denial,
    find_writeoff,
    has_pending_writeoff,
    initial_writeoff_status,
    public,
    touch,
    writeoff_economics,
)
from util import (
    ALL_ROLES,
    REASON_CODES,
    get_body,
    now_iso,
    req_enum,
    req_int,
    req_str,
    sort_created,
)

bp = Blueprint("writeoffs", __name__)

DECIDERS = ("DenialsManager", "RevenueCycleDirector")
APPROVABLE_DENIAL_STATES = ("QUEUED", "IN_APPEAL", "CLOSED_EXHAUSTED", "CLOSED_EXPIRED")


def _check_amount_gates(denial, amount):
    """Fiscal gates in pinned sub-order: ceiling first, then open balance."""
    if amount > WRITE_OFF_CEILING_CENTS:
        raise ApiError(
            ERR_WRITE_OFF_EXCEEDS_CEILING,
            422,
            "requested_amount_cents exceeds the ceiling of %d" % WRITE_OFF_CEILING_CENTS,
        )
    if amount > denial["open_balance_cents"]:
        raise ApiError(
            ERR_AMOUNT_EXCEEDS_OPEN_BALANCE,
            422,
            "requested_amount_cents exceeds open balance %d"
            % denial["open_balance_cents"],
        )


@bp.post("/rcm/write-off-requests")
@require_roles("DenialsSpecialist")
def create_writeoff():
    body = get_body()
    denial_id = req_str(body, "denial_case_id")
    amount = req_int(body, "requested_amount_cents")
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    if amount <= 0:
        raise ApiError(ERR_VALIDATION, 400, "requested_amount_cents must be > 0")
    denial = find_denial(denial_id)
    if has_pending_writeoff(denial_id):
        raise ApiError(
            ERR_WRITE_OFF_ALREADY_PENDING,
            409,
            "Denial already has a pending write-off request",
        )
    _check_amount_gates(denial, amount)
    wo = create_writeoff_record(denial, amount, reason_code, g.user_id, g.user_role)
    return ok(public(wo), "object", 201)


@bp.get("/rcm/write-off-requests")
@require_roles(*ALL_ROLES)
def list_writeoffs():
    items = list(store.writeoffs.values())
    denial_id = request.args.get("denial_case_id")
    if denial_id is not None:
        items = [w for w in items if w["denial_case_id"] == denial_id]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_response([public(w) for w in sort_created(items)])


@bp.get("/rcm/write-off-requests/<wid>")
@require_roles(*ALL_ROLES)
def get_writeoff(wid):
    return ok(public(find_writeoff(wid)))


@bp.post("/rcm/write-off-requests/<wid>/approve")
@require_roles(*DECIDERS)
def approve_writeoff(wid):
    wo = find_writeoff(wid)
    if wo["status"] not in PENDING_WRITEOFF_STATES:
        raise ApiError(
            ERR_WRITE_OFF_NOT_PENDING, 409, "Write-off request is not pending"
        )
    denial = find_denial(wo["denial_case_id"])
    if denial["status"] not in APPROVABLE_DENIAL_STATES:
        raise ApiError(
            ERR_DENIAL_INVALID_STATE,
            409,
            "Denial status %s cannot accept a write-off approval" % denial["status"],
        )
    if g.user_id == wo["requested_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "Approver must differ from the requester",
        )
    if wo["requested_amount_cents"] > denial["open_balance_cents"]:
        raise ApiError(
            ERR_AMOUNT_EXCEEDS_OPEN_BALANCE,
            422,
            "requested_amount_cents exceeds open balance %d"
            % denial["open_balance_cents"],
        )
    if wo["approval_tier"] == "ESCALATED" and g.user_role != "RevenueCycleDirector":
        raise ApiError(
            ERR_APPROVAL_LIMIT_EXCEEDED,
            403,
            "Escalated-tier requests require a RevenueCycleDirector",
        )
    apply_writeoff_approval(wo, denial, g.user_role, g.user_id)
    return ok(public(wo))


@bp.post("/rcm/write-off-requests/<wid>/reject")
@require_roles(*DECIDERS)
def reject_writeoff(wid):
    body = get_body()
    reason = req_str(body, "reason")
    wo = find_writeoff(wid)
    if wo["status"] not in PENDING_WRITEOFF_STATES:
        raise ApiError(
            ERR_WRITE_OFF_NOT_PENDING, 409, "Write-off request is not pending"
        )
    wo["status"] = "REJECTED"
    wo["decision_reason"] = reason
    wo["decided_by_user_id"] = g.user_id
    wo["decided_at"] = now_iso()
    touch(wo)
    emit_event(
        wo["denial_case_id"],
        "WRITE_OFF_REJECTED",
        g.user_role,
        g.user_id,
        "write_off_request_id=%s;reason=%s" % (wo["id"], reason),
    )
    return ok(public(wo))


@bp.post("/rcm/write-off-requests/<wid>/revise")
@require_roles("DenialsSpecialist")
def revise_writeoff(wid):
    body = get_body()
    amount = req_int(body, "requested_amount_cents")
    if amount <= 0:
        raise ApiError(ERR_VALIDATION, 400, "requested_amount_cents must be > 0")
    wo = find_writeoff(wid)
    if wo["status"] != "REJECTED":
        raise ApiError(
            ERR_WRITE_OFF_NOT_PENDING, 409, "Only a REJECTED request can be revised"
        )
    if g.user_id != wo["requested_by_user_id"]:
        raise ApiError(
            ERR_NOT_REQUEST_OWNER,
            403,
            "Only the original requester may revise this request",
        )
    denial = find_denial(wo["denial_case_id"])
    _check_amount_gates(denial, amount)
    tier, projected, recommended = writeoff_economics(denial, amount)
    wo["requested_amount_cents"] = amount
    wo["approval_tier"] = tier
    wo["projected_recovery_cents"] = projected
    wo["recommended_writeoff_cents"] = recommended
    wo["status"] = initial_writeoff_status(tier)
    touch(wo)
    emit_event(
        wo["denial_case_id"],
        "WRITE_OFF_REVISED",
        g.user_role,
        g.user_id,
        "write_off_request_id=%s;requested_amount_cents=%d;approval_tier=%s"
        % (wo["id"], amount, tier),
    )
    return ok(public(wo))


@bp.post("/rcm/write-off-requests/<wid>/rescind")
@require_roles("RevenueCycleDirector")
def rescind_writeoff(wid):
    body = get_body()
    reason = req_str(body, "reason")
    wo = find_writeoff(wid)
    if wo["status"] != "APPROVED":
        raise ApiError(
            ERR_WRITE_OFF_NOT_PENDING, 409, "Only an APPROVED request can be rescinded"
        )
    denial = find_denial(wo["denial_case_id"])
    apply_writeoff_rescission(wo, denial, reason, g.user_role, g.user_id)
    return ok(public(wo))
