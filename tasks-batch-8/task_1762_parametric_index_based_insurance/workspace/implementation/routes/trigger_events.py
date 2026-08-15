"""TriggerEvent endpoints (PRD §3.6): review, verify (claim fan-out), reject."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_EVENT_NOT_DETECTED, ERR_EVENT_NOT_UNDER_REVIEW,
    ERR_EVENT_NO_LONGER_BREACHING, ERR_EVENT_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    pagination_params, paginate, sorted_by_created,
    get_program, get_index_in_program, get_event_in_index,
)
from services import domain, calc

bp = Blueprint("trigger_events", __name__)


@bp.get("/programs/<programId>/index-definitions/<indexId>/trigger-events")
def list_events_of_index(programId, indexId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = [e for e in db.trigger_events.values() if e["index_definition_id"] == idx["id"]]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>/index-definitions/<indexId>/trigger-events/<eventId>")
def get_event(programId, indexId, eventId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    ev = get_event_in_index(idx, eventId)
    return success_object(domain.serialize(ev))


@bp.get("/programs/<programId>/trigger-events")
def list_events_in_program(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    limit, offset = pagination_params()
    items = [e for e in db.trigger_events.values() if e["program_id"] == prog["id"]]
    items = _apply_event_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


def _apply_event_filters(items):
    iid = request.args.get("index_definition_id")
    pid = request.args.get("program_id")
    st = request.args.get("status")
    if iid is not None:
        items = [e for e in items if e["index_definition_id"] == iid]
    if pid is not None:
        items = [e for e in items if e["program_id"] == pid]
    if st is not None:
        items = [e for e in items if e["status"] == st]
    return items


@bp.post("/programs/<programId>/index-definitions/<indexId>/trigger-events/<eventId>/open-review")
def open_review(programId, indexId, eventId):
    require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    ev = get_event_in_index(idx, eventId)
    if ev["status"] != "DETECTED":
        raise err(ERR_EVENT_NOT_DETECTED, 409, "Open-review requires event DETECTED")
    ev["status"] = "UNDER_REVIEW"
    domain.touch(ev)
    return success_object(domain.serialize(ev))


@bp.post("/programs/<programId>/index-definitions/<indexId>/trigger-events/<eventId>/verify")
def verify_event(programId, indexId, eventId):
    require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    ev = get_event_in_index(idx, eventId)
    if ev["status"] != "UNDER_REVIEW":
        raise err(ERR_EVENT_NOT_UNDER_REVIEW, 409, "Verify/reject requires event UNDER_REVIEW")

    # Recompute blend from the effective observation set (chronological replay)
    blended, method = calc.compute_blend(idx, ev["window_end_date"])
    max_tier = calc.compute_max_tier(idx, blended)
    if blended is None or max_tier < 1:
        raise err(ERR_EVENT_NO_LONGER_BREACHING, 409,
                  "Recomputed blend no longer breaches any tier (late revision or empty effective set)")

    ev["blended_index_value"] = blended
    ev["max_tier_breached"] = max_tier
    ev["verification_method"] = method
    ev["status"] = "VERIFIED"
    domain.touch(ev)

    # Fan out: one claim per BOUND policy on this index whose coverage window
    # contains window_end_date, in policy created_at ASC order (PRD §3.6).
    wed = ev["window_end_date"]
    covering = sorted(
        (p for p in db.policies.values()
         if p["index_definition_id"] == idx["id"]
         and p["lifecycle_status"] == "BOUND"
         and p["policy_start_date"] <= wed <= p["policy_end_date"]),
        key=lambda p: p["created_at"],
    )
    for pol in covering:
        claim = domain.stamp_new({
            "policy_id": pol["id"],
            "trigger_event_id": ev["id"],
            "tier_applied": max_tier,
            "provisional_payout_cents": calc.provisional_payout_cents(pol, idx, max_tier),
            "final_payout_cents": 0,
            "ceded_recovery_cents": 0,
            "net_payment_cents": 0,
            "approver_user_id": None,
            "status": "GENERATED",
        })
        db.claims[claim["id"]] = claim
        # Late event after quiet: SETTLED_QUIET -> PAYMENT_PENDING happens only
        # when a claim is generated for a quiet policy (PRD §3.5). But claim
        # generation alone does not disturb posture (PRD §3.6) — the posture moves
        # only when a claim reaches APPROVED/FRAUD_HOLD. Keep posture unchanged here.

    return success_object(domain.serialize(ev))


@bp.post("/programs/<programId>/index-definitions/<indexId>/trigger-events/<eventId>/reject")
def reject_event(programId, indexId, eventId):
    require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    ev = get_event_in_index(idx, eventId)
    if ev["status"] != "UNDER_REVIEW":
        raise err(ERR_EVENT_NOT_UNDER_REVIEW, 409, "Verify/reject requires event UNDER_REVIEW")
    ev["status"] = "REJECTED"
    domain.touch(ev)
    return success_object(domain.serialize(ev))


# --- Flat reads ---

@bp.get("/programs/trigger-events")
def list_events_flat():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    items = list(db.trigger_events.values())
    items = _apply_event_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/trigger-events/<eventId>")
def get_event_flat(eventId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    ev = db.trigger_events.get(eventId)
    if not ev:
        raise err(ERR_EVENT_NOT_FOUND, 404, "Trigger event id does not exist")
    return success_object(domain.serialize(ev))
