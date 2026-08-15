"""Coach roster (PRD §3.1, §2.7)."""
from flask import Blueprint, request

from auth import authenticate, require_role, body, get_str, get_int
from db import store
from engine import cancel_scheduled_sessions_of_coach
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_DUPLICATE_RESOURCE, ERR_SEGREGATION_OF_DUTIES, not_found)
from serializers import coach as ser_coach, fit_assessment as ser_fit, base_row, touch
from timeutil import parse_date, today

bp = Blueprint("coaches", __name__)

CREDENTIAL_LEVELS = ("ACC", "PCC", "MCC")


@bp.post("/coaches")
def create_coach():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager"))
    b = body()
    email = get_str(b, "email")
    # Priority 15 uniqueness precedes priority 20 request shape.
    if email is not None and any(c["email"] == email for c in store.coaches.values()):
        raise ApiError(ERR_DUPLICATE_RESOURCE, 409, "Coach email already exists")
    display_name = get_str(b, "display_name")
    level = b.get("credential_level")
    expires = parse_date(b.get("credential_expires_on"))
    max_clients = get_int(b, "max_concurrent_clients")
    if (display_name is None or email is None
            or level not in CREDENTIAL_LEVELS
            or expires is None
            or max_clients is None or max_clients < 1):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: display_name, email, credential_level in {ACC,PCC,MCC}, "
                       "credential_expires_on (ISO date), max_concurrent_clients >= 1")
    c = base_row()
    c.update({
        "display_name": display_name,
        "email": email,
        "credential_level": level,
        "credential_expires_on": expires,
        "credential_status": "PENDING_VERIFICATION",
        "ethics_status": "ACTIVE",
        "max_concurrent_clients": max_clients,
    })
    store.coaches[c["id"]] = c
    return success(ser_coach(c)), 201


@bp.get("/coaches/<cid>")
def get_coach(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    c = store.coaches.get(cid)
    if c is None:
        raise not_found("Coach not found")
    return success(ser_coach(c))


@bp.get("/coaches")
def list_coaches():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.coaches.values())
    cs = request.args.get("credential_status")
    if cs is not None:
        rows = [c for c in rows if c["credential_status"] == cs]
    rows.sort(key=lambda c: (c["created_at"], c["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_coach(c) for c in page], meta)


@bp.post("/coaches/<cid>/verify-credential")
def verify_credential(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PracticeManager",))
    c = store.coaches.get(cid)
    if c is None:
        raise not_found("Coach not found")
    # State first (priority 4), then segregation of duties (priority 16).
    if c["credential_status"] != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING_VERIFICATION credential can be verified")
    if not (c["credential_expires_on"] > today()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Credential expiry date must lie strictly after the current UTC date")
    if uid is not None and any(coach["id"] == uid for coach in store.coaches.values()):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The acting PracticeManager's X-User-ID must not coincide with any coach id")
    c["credential_status"] = "VERIFIED"
    touch(c)
    return success(ser_coach(c))


@bp.post("/coaches/<cid>/revoke-credential")
def revoke_credential(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PracticeManager",))
    c = store.coaches.get(cid)
    if c is None:
        raise not_found("Coach not found")
    if c["credential_status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a VERIFIED credential can be revoked")
    c["credential_status"] = "REVOKED"
    touch(c)
    # Cascade (PRD §3.1): cancel the coach's SCHEDULED sessions (each version
    # +1) and advance each affected enrollment's version as counts recompute.
    cancel_scheduled_sessions_of_coach(c["id"])
    return success(ser_coach(c))


@bp.post("/coaches/<cid>/suspend-ethics")
def suspend_ethics(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PracticeManager",))
    c = store.coaches.get(cid)
    if c is None:
        raise not_found("Coach not found")
    if c["ethics_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE ethics posture can be suspended")
    c["ethics_status"] = "SUSPENDED"
    touch(c)
    # Same session ripple as revocation, plus the coach's OPEN / IN_PROGRESS
    # cohorts are CANCELLED and their ACTIVE / WAITLISTED memberships REMOVED
    # (PRD §3.1). The cohort flips first, so waitlist promotion does not fire.
    cancel_scheduled_sessions_of_coach(c["id"])
    for cohort in store.cohorts.values():
        if cohort["coach_id"] == c["id"] and cohort["cohort_status"] in ("OPEN", "IN_PROGRESS"):
            cohort["cohort_status"] = "CANCELLED"
            touch(cohort)
            for m in store.memberships.values():
                if (m["cohort_id"] == cohort["id"]
                        and m["member_status"] in ("ACTIVE", "WAITLISTED")):
                    m["member_status"] = "REMOVED"
    return success(ser_coach(c))


@bp.get("/coaches/<cid>/fit-assessments")
def coach_fit_assessments(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach"))
    c = store.coaches.get(cid)
    if c is None:
        raise not_found("Coach not found")
    if role == "Coach" and uid != cid:
        from errors import forbidden
        raise forbidden("A coach may only list their own graded assessments")
    rows = [f for f in store.fit_assessments.values() if f["assessor_coach_id"] == cid]
    rows.sort(key=lambda f: (f["created_at"], f["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_fit(f) for f in page], meta)
