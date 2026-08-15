"""Enrollments: creation, OCC-guarded lifecycle writes, subordinate listings
(PRD §3.3, §3.5, §2.8).
"""
from flask import Blueprint, request

import calc
from auth import (authenticate, require_role, require_ownership, body,
                  get_int)
from db import store
from engine import (cancel_scheduled_sessions_of_enrollment,
                    remove_enrollment_memberships)
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_COACH_NOT_CREDENTIALED,
                    ERR_FIT_NOT_ESTABLISHED, ERR_COACH_CAPACITY_FULL,
                    ERR_TIER_RETIRED, ERR_PAYMENT_PLAN_INVALID, not_found)
from serializers import (enrollment as ser_enrollment,
                         installment as ser_installment,
                         membership as ser_membership,
                         base_row, append_row, touch)

bp = Blueprint("enrollments", __name__)


def _get_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise not_found("Enrollment not found")
    return e


def _check_occ(e, b):
    """Priority 5 OCC (pause/resume/cancel only). A missing or non-integer
    expected version is a request-shape failure (priority 20)."""
    expected = b.get("expected_enrollment_version")
    if expected is None or not (isinstance(expected, int) and not isinstance(expected, bool)):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_enrollment_version is required and must be an integer")
    if expected != e["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_enrollment_version does not match the enrollment's current version")


@bp.post("/enrollments")
def create_enrollment():
    role, uid = authenticate()
    require_role(role, uid, ("Client", "PracticeManager"))
    b = body()
    client_id = b.get("client_id")
    coach_id = b.get("coach_id")
    tier_id = b.get("program_tier_id")
    call_id = b.get("discovery_call_id")
    if role == "Client":
        require_ownership(client_id if isinstance(client_id, str) else None, uid)
    # Existence in declared body order (priority 3).
    if not isinstance(client_id, str) or client_id not in store.clients:
        raise not_found("client_id does not reference an existing client")
    if not isinstance(coach_id, str) or coach_id not in store.coaches:
        raise not_found("coach_id does not reference an existing coach")
    if not isinstance(tier_id, str) or tier_id not in store.tiers:
        raise not_found("program_tier_id does not reference an existing program tier")
    if not isinstance(call_id, str) or call_id not in store.discovery_calls:
        raise not_found("discovery_call_id does not reference an existing discovery call")
    coach = store.coaches[coach_id]
    tier = store.tiers[tier_id]
    # Priority 7: fit gate.
    fit = next((f for f in store.fit_assessments.values()
                if f["discovery_call_id"] == call_id), None)
    if fit is None or fit["outcome"] != "PROCEED":
        raise ApiError(ERR_FIT_NOT_ESTABLISHED, 422,
                       "Enrollment requires a fit assessment with outcome PROCEED")
    # Priority 13: coach capacity at creation (ACTIVE lifecycle count).
    active_count = sum(1 for x in store.enrollments.values()
                       if x["coach_id"] == coach_id and x["lifecycle_status"] == "ACTIVE")
    if active_count >= coach["max_concurrent_clients"]:
        raise ApiError(ERR_COACH_CAPACITY_FULL, 422,
                       "Coach has reached max_concurrent_clients")
    # Priority 17: tier must be ACTIVE.
    if tier["tier_status"] != "ACTIVE":
        raise ApiError(ERR_TIER_RETIRED, 422, "RETIRED tiers cannot accept new enrollments")
    # Priority 18: payment-plan shape. Missing/non-integer is a request-shape
    # failure (priority 20); an in-hand but out-of-range count is the plan error.
    ic_raw = b.get("installment_count")
    ic = get_int(b, "installment_count")
    if ic is not None and not (1 <= ic <= tier["installment_count_allowed"]):
        raise ApiError(ERR_PAYMENT_PLAN_INVALID, 422,
                       "installment_count must lie between 1 and the tier's "
                       "installment_count_allowed inclusive")
    if ic is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "installment_count is required and must be an integer")
    e = base_row()
    e.update({
        "client_id": client_id,
        "coach_id": coach_id,
        "program_tier_id": tier_id,
        "discovery_call_id": call_id,
        "lifecycle_status": "PENDING_PAYMENT",
        "payment_status": "CURRENT",
        "activated_at": None,
        # Pinned at creation; immune to later tier price edits (PRD §3.3).
        "sessions_total": tier["session_count"],
        "sessions_total_price_basis": tier["price_cents"],
        "late_reschedules_used": 0,
        "pauses_used": 0,
    })
    store.enrollments[e["id"]] = e
    # Installment schedule: equal floor split, remainder onto the LAST
    # installment; due_on resolves only at activation (PRD §3.3).
    amounts = calc.installment_amounts(tier["price_cents"], ic)
    for idx, amount in enumerate(amounts, start=1):
        inst = append_row()
        inst.update({
            "enrollment_id": e["id"],
            "sequence_no": idx,
            "amount_cents": amount,
            "due_on": None,
            "installment_status": "PENDING",
        })
        store.installments[inst["id"]] = inst
    return success(ser_enrollment(e)), 201


@bp.get("/enrollments/<eid>")
def get_enrollment(eid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    return success(ser_enrollment(_get_enrollment(eid)))


@bp.get("/enrollments")
def list_enrollments():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.enrollments.values())
    for param in ("client_id", "coach_id", "program_tier_id",
                  "discovery_call_id", "lifecycle_status"):
        v = request.args.get(param)
        if v is not None:
            rows = [e for e in rows if e[param] == v]
    rows.sort(key=lambda e: (e["created_at"], e["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_enrollment(e) for e in page], meta)


@bp.get("/enrollments/<eid>/installments")
def list_installments(eid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    _get_enrollment(eid)
    # Ordered by sequence_no ASC rather than default creation order (PRD §3.3).
    rows = sorted((i for i in store.installments.values()
                   if i["enrollment_id"] == eid),
                  key=lambda i: i["sequence_no"])
    page, meta = paginate(rows)
    return success_list([ser_installment(i) for i in page], meta)


@bp.get("/enrollments/<eid>/cohort-memberships")
def list_enrollment_memberships(eid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    _get_enrollment(eid)
    rows = [m for m in store.memberships.values() if m["enrollment_id"] == eid]
    rows.sort(key=lambda m: (m["created_at"], m["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_membership(m) for m in page], meta)


@bp.post("/enrollments/<eid>/pause")
def pause_enrollment(eid):
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    e = _get_enrollment(eid)
    require_ownership(e["client_id"], uid)
    # Priority 4 state: must be ACTIVE, and at most PAUSE_LIMIT (2) completed
    # pauses across the enrollment's life (PRD §3.5).
    if e["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE enrollment can be paused")
    if e["pauses_used"] >= calc.PAUSE_LIMIT:
        raise ApiError(ERR_INVALID_STATE, 409, "Pause limit reached for this enrollment")
    _check_occ(e, body())
    e["lifecycle_status"] = "PAUSED"
    e["pauses_used"] += 1
    touch(e)
    # Cascade: every SCHEDULED session of the enrollment -> CANCELLED.
    cancel_scheduled_sessions_of_enrollment(e["id"])
    return success(ser_enrollment(e))


@bp.post("/enrollments/<eid>/resume")
def resume_enrollment(eid):
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    e = _get_enrollment(eid)
    require_ownership(e["client_id"], uid)
    if e["lifecycle_status"] != "PAUSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PAUSED enrollment can be resumed")
    if e["payment_status"] != "CURRENT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Resume requires payment_status CURRENT")
    _check_occ(e, body())
    # Priority 6: coach must remain delivery-eligible.
    coach = store.coaches.get(e["coach_id"])
    if (coach is None or coach["credential_status"] != "VERIFIED"
            or coach["ethics_status"] != "ACTIVE"):
        raise ApiError(ERR_COACH_NOT_CREDENTIALED, 422,
                       "Coach is not delivery-eligible (credential VERIFIED and ethics ACTIVE required)")
    e["lifecycle_status"] = "ACTIVE"
    touch(e)
    # The program window is NOT extended: paused time is lost time (PRD §3.5).
    return success(ser_enrollment(e))


@bp.post("/enrollments/<eid>/cancel")
def cancel_enrollment(eid):
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    e = _get_enrollment(eid)
    require_ownership(e["client_id"], uid)
    if e["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or PAUSED enrollment can be cancelled")
    _check_occ(e, body())
    e["lifecycle_status"] = "CANCELLED"
    touch(e)
    cancel_scheduled_sessions_of_enrollment(e["id"])
    # ACTIVE memberships -> REMOVED, firing waitlist promotion per cohort (PRD §3.5).
    remove_enrollment_memberships(e["id"])
    return success(ser_enrollment(e))
