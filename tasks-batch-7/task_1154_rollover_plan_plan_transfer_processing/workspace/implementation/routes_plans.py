"""Plans and freeze windows (SCAFFOLD §1.5; PRD §3.1, §2.10)."""

from flask import Blueprint, request

import errors
from db import clock_date, create_entity, store, touch
from middleware import ALL_ROLES, body, opt_bool, opt_int, paginate, req_enum, req_str, require_roles
from response import ok, ok_list
from services import (
    PLAN_TYPES,
    SUSPENDABLE_STATUSES,
    case_receiving_account,
    case_source_account,
    parse_date,
    req_date,
    restore_disbursement,
    serialize_freeze_window,
    serialize_plan,
)

bp = Blueprint("plans", __name__)


def get_plan_or_404(plan_id):
    p = store.plans.get(plan_id)
    if p is None:
        raise errors.err_plan_not_found()
    return p


@bp.post("/v1/plans")
@require_roles("PlanSponsorAdmin")
def create_plan():
    data = body()
    plan_name = req_str(data, "plan_name")
    plan_type = req_enum(data, "plan_type", PLAN_TYPES)
    threshold = opt_int(data, "spousal_consent_threshold_cents")
    if threshold is None:
        threshold = 500000
    if threshold < 0:
        raise errors.err_validation("spousal_consent_threshold_cents must be >= 0")
    plan = create_entity(
        store.plans,
        {
            "plan_name": plan_name,
            "plan_type": plan_type,
            "status": "ACTIVE",
            "accepts_incoming_rollovers": opt_bool(data, "accepts_incoming_rollovers", True),
            "accepts_incoming_transfers": opt_bool(data, "accepts_incoming_transfers", True),
            "accepts_loan_transfers": opt_bool(data, "accepts_loan_transfers", True),
            "accepts_after_tax_basis": opt_bool(data, "accepts_after_tax_basis", True),
            "allows_in_plan_roth_conversion": opt_bool(data, "allows_in_plan_roth_conversion", True),
            "requires_spousal_consent": opt_bool(data, "requires_spousal_consent", True),
            "spousal_consent_threshold_cents": threshold,
        },
    )
    return ok(serialize_plan(plan), status=201)


@bp.get("/v1/plans")
@require_roles(*ALL_ROLES)
def list_plans():
    rows = list(store.plans.values())
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows.sort(key=lambda p: p["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_plan(p) for p in page], total, limit, offset)


@bp.get("/v1/plans/<plan_id>")
@require_roles(*ALL_ROLES)
def get_plan(plan_id):
    return ok(serialize_plan(get_plan_or_404(plan_id)))


@bp.post("/v1/plans/<plan_id>/freeze")
@require_roles("PlanSponsorAdmin")
def freeze_plan(plan_id):
    plan = get_plan_or_404(plan_id)
    if plan["status"] == "FROZEN":
        raise errors.err_plan_frozen("Plan is already FROZEN")
    if plan["status"] == "TERMINATED":
        raise errors.err_plan_terminated()
    plan["status"] = "FROZEN"
    touch(plan)
    # Link 1: suspend non-terminal cases touching this plan (idempotent on SUSPENDED).
    affected = []
    for case in sorted(store.cases.values(), key=lambda c: c["_seq"]):
        src = case_source_account(case)
        recv = case_receiving_account(case)
        touches = (src is not None and src["plan_id"] == plan_id) or (recv is not None and recv["plan_id"] == plan_id)
        if not touches:
            continue
        if case["status"] in SUSPENDABLE_STATUSES:
            case["prior_status"] = case["status"]
            case["status"] = "SUSPENDED"
            touch(case)
            affected.append(case)
        # already SUSPENDED -> stays SUSPENDED, prior_status preserved
    # Link 2: PENDING disbursements of just-suspended cases -> CANCELLED.
    for case in affected:
        for disb in sorted(store.disbursements.values(), key=lambda d: d["_seq"]):
            if disb["rollover_case_id"] == case["id"] and disb["status"] == "PENDING":
                disb["status"] = "CANCELLED"
                touch(disb)
                # Link 3: compensating balance restoration.
                restore_disbursement(disb)
    return ok(serialize_plan(plan))


@bp.post("/v1/plans/<plan_id>/unfreeze")
@require_roles("PlanSponsorAdmin")
def unfreeze_plan(plan_id):
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "FROZEN":
        raise errors.err_plan_not_frozen()
    plan["status"] = "ACTIVE"
    touch(plan)
    for case in sorted(store.cases.values(), key=lambda c: c["_seq"]):
        if case["status"] != "SUSPENDED" or not case.get("prior_status"):
            continue
        src = case_source_account(case)
        recv = case_receiving_account(case)
        touches = (src is not None and src["plan_id"] == plan_id) or (recv is not None and recv["plan_id"] == plan_id)
        if touches:
            case["status"] = case["prior_status"]
            case["prior_status"] = None
            touch(case)
    return ok(serialize_plan(plan))


@bp.post("/v1/plans/<plan_id>/terminate")
@require_roles("PlanSponsorAdmin")
def terminate_plan(plan_id):
    plan = get_plan_or_404(plan_id)
    if plan["status"] == "TERMINATED":
        raise errors.err_plan_terminated("Plan is already TERMINATED")
    if plan["status"] != "ACTIVE":
        raise errors.err_plan_frozen("Plan must be ACTIVE to terminate")
    plan["status"] = "TERMINATED"
    touch(plan)
    return ok(serialize_plan(plan))


@bp.post("/v1/plans/<plan_id>/freeze-windows")
@require_roles("PlanSponsorAdmin")
def create_freeze_window(plan_id):
    get_plan_or_404(plan_id)
    data = body()
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    reason = req_str(data, "reason")
    if start_date > end_date:
        raise errors.err_window_range_invalid()
    # Closed-interval collision; windows touching at a boundary date are allowed.
    for w in store.freeze_windows.values():
        if w["plan_id"] != plan_id:
            continue
        s2 = parse_date(w["start_date"])
        e2 = parse_date(w["end_date"])
        intersects = start_date <= e2 and s2 <= end_date
        merely_touching = end_date == s2 or e2 == start_date
        if intersects and not merely_touching:
            raise errors.err_freeze_window_overlap()
    window = create_entity(
        store.freeze_windows,
        {
            "plan_id": plan_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "reason": reason,
        },
    )
    return ok(serialize_freeze_window(window), status=201)


@bp.get("/v1/plans/<plan_id>/freeze-windows")
@require_roles(*ALL_ROLES)
def list_freeze_windows(plan_id):
    get_plan_or_404(plan_id)
    rows = [w for w in store.freeze_windows.values() if w["plan_id"] == plan_id]
    rows.sort(key=lambda w: w["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_freeze_window(w) for w in page], total, limit, offset)
