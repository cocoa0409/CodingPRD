"""Permit, notification, and smoke-management routes."""
from flask import Blueprint, request

from core import (
    DB,
    ApiError,
    Validator,
    auth,
    body,
    clock,
    ok,
    paginate,
    parse_date,
    require_role,
    stamp_new,
    touch,
)
from domain import (
    accepted_contingency,
    get_notification,
    get_permit,
    get_plan,
    get_smoke,
    permit_rollups,
    ser_notification,
    ser_permit,
    ser_smoke,
    suspend_permit_cascade,
    the_association,
)

bp = Blueprint("permits", __name__)


def _plan_author_or_403(plan, uid):
    if uid != plan["author_boss_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the plan's author")


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------


@bp.post("/burn-plans/<pid>/permits")
def create_permit(pid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _plan_author_or_403(plan, uid)
    if plan["status"] not in ("SUBMITTED", "APPROVED"):
        raise ApiError(
            "ERR_PLAN_NOT_SUBMITTED", 409, "Plan must be SUBMITTED or APPROVED to request a permit"
        )
    for p in DB["permits"].values():
        if p["burn_plan_id"] == plan["id"] and p["status"] in (
            "UNDER_REVIEW",
            "ISSUED",
            "SUSPENDED",
        ):
            raise ApiError(
                "ERR_PERMIT_ALREADY_OPEN", 409, "Plan already has an open permit"
            )
    v = Validator(data, {"notifications_required"})
    v.req("notifications_required", int)
    if v.typed("notifications_required", int) is not None and v.typed("notifications_required", int) < 0:
        v.invalid("notifications_required must be >= 0")
    v.finish()
    permit = stamp_new(
        {
            "burn_plan_id": plan["id"],
            "notifications_required": data["notifications_required"],
            "issued_by_boss_id": None,
            "status": "UNDER_REVIEW",
        }
    )
    DB["permits"][permit["id"]] = permit
    return ok(ser_permit(permit), 201)


@bp.get("/permits/<pid>")
def get_one_permit(pid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_permit(get_permit(pid)))


@bp.get("/permits")
def list_permits():
    _, role = auth()
    require_role(role, None)
    items = list(DB["permits"].values())
    for key in ("burn_plan_id", "issued_by_boss_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    return paginate(items, ser_permit)


@bp.get("/burn-plans/<pid>/permits")
def list_plan_permits(pid):
    _, role = auth()
    require_role(role, None)
    plan = get_plan(pid)
    items = [p for p in DB["permits"].values() if p["burn_plan_id"] == plan["id"]]
    return paginate(items, ser_permit)


@bp.post("/permits/<pid>/issue")
def issue_permit(pid):
    body()
    uid, role = auth()
    require_role(role, {"AgencyReviewer"})
    permit = get_permit(pid)
    plan = DB["plans"].get(permit["burn_plan_id"])
    # SoD (priority 5) before state (priority 7)
    if plan is not None and uid == plan["author_boss_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Reviewer may not issue a permit on their own authored plan",
        )
    if permit["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PERMIT_NOT_UNDER_REVIEW", 409, "Permit must be UNDER_REVIEW")
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    if accepted_contingency(plan["id"]) is None:
        raise ApiError(
            "ERR_CONTINGENCY_NOT_ACCEPTED",
            409,
            "An ACCEPTED contingency plan is required",
        )
    completed, _ = permit_rollups(permit)
    if completed < permit["notifications_required"]:
        raise ApiError(
            "ERR_NOTIFICATIONS_INCOMPLETE",
            409,
            "notifications_completed below notifications_required",
        )
    if plan["planned_window_end"] < clock().date():
        raise ApiError("ERR_PLAN_WINDOW_LAPSED", 422, "Plan window has lapsed")
    permit["status"] = "ISSUED"
    permit["issued_by_boss_id"] = uid
    touch(permit)
    return ok(ser_permit(permit))


@bp.post("/permits/<pid>/deny")
def deny_permit(pid):
    body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    permit = get_permit(pid)
    if permit["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PERMIT_NOT_UNDER_REVIEW", 409, "Permit must be UNDER_REVIEW")
    permit["status"] = "DENIED"
    touch(permit)
    return ok(ser_permit(permit))


@bp.post("/permits/<pid>/suspend")
def suspend_permit(pid):
    body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    permit = get_permit(pid)
    if permit["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Permit must be ISSUED")
    suspend_permit_cascade(permit)
    return ok(ser_permit(permit))


@bp.post("/permits/<pid>/reinstate")
def reinstate_permit(pid):
    body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    permit = get_permit(pid)
    if permit["status"] != "SUSPENDED":
        raise ApiError("ERR_PERMIT_NOT_SUSPENDED", 409, "Permit must be SUSPENDED")
    plan = DB["plans"].get(permit["burn_plan_id"])
    if plan is None or plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    permit["status"] = "ISSUED"
    touch(permit)
    return ok(ser_permit(permit))


@bp.post("/permits/<pid>/revoke")
def revoke_permit(pid):
    body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    permit = get_permit(pid)
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        raise ApiError(
            "ERR_PERMIT_NOT_REVOKABLE", 409, "Permit must be ISSUED or SUSPENDED"
        )
    permit["status"] = "REVOKED"
    touch(permit)
    return ok(ser_permit(permit))


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@bp.post("/permits/<pid>/notifications")
def create_notification(pid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    permit = get_permit(pid)
    plan = DB["plans"].get(permit["burn_plan_id"])
    if plan is not None:
        _plan_author_or_403(plan, uid)
    v = Validator(data, {"recipient_name", "channel"})
    v.req("recipient_name", str)
    v.enum("channel", {"MAIL", "PHONE", "IN_PERSON"})
    v.finish()
    note = stamp_new(
        {
            "burn_permit_id": permit["id"],
            "recipient_name": data["recipient_name"],
            "channel": data["channel"],
            "confirmed_at": None,
            "status": "REQUESTED",
        }
    )
    DB["notifications"][note["id"]] = note
    return ok(ser_notification(note), 201)


@bp.get("/permits/<pid>/notifications")
def list_notifications(pid):
    _, role = auth()
    require_role(role, None)
    permit = get_permit(pid)
    items = [n for n in DB["notifications"].values() if n["burn_permit_id"] == permit["id"]]
    return paginate(items, ser_notification)


@bp.post("/notifications/<nid>/confirm")
def confirm_notification(nid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    note = get_notification(nid)
    permit = DB["permits"].get(note["burn_permit_id"])
    plan = DB["plans"].get(permit["burn_plan_id"]) if permit else None
    if plan is not None:
        _plan_author_or_403(plan, uid)
    if note["status"] != "REQUESTED":
        raise ApiError(
            "ERR_NOTIFICATION_NOT_REQUESTED", 409, "Notification must be REQUESTED"
        )
    note["status"] = "CONFIRMED"
    note["confirmed_at"] = clock()
    touch(note)
    return ok(ser_notification(note))


# ---------------------------------------------------------------------------
# Smoke approvals
# ---------------------------------------------------------------------------


@bp.post("/burn-plans/<pid>/smoke-approvals")
def create_smoke(pid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _plan_author_or_403(plan, uid)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    v = Validator(data, {"requested_burn_date", "requested_acres"})
    v.date("requested_burn_date")
    v.req("requested_acres", int)
    ra = v.typed("requested_acres", int)
    if ra is not None and ra <= 0:
        v.prescription("requested_acres must be positive")
    if ra is not None and ra > plan["planned_acres"]:
        v.prescription("requested_acres must not exceed planned_acres")
    v.finish()
    # supersede any non-terminal approval on the same plan (version-silent)
    for s in DB["smoke_approvals"].values():
        if s["burn_plan_id"] == plan["id"] and s["status"] in (
            "SUBMITTED",
            "APPROVED",
            "CONDITIONALLY_APPROVED",
        ):
            s["status"] = "SUPERSEDED"
    parcel = DB["parcels"].get(plan["parcel_id"])
    smoke = stamp_new(
        {
            "burn_plan_id": plan["id"],
            "airshed_id": parcel["airshed_id"] if parcel else None,
            "requested_burn_date": parse_date(data["requested_burn_date"]),
            "requested_acres": data["requested_acres"],
            "decision_note": None,
            "status": "SUBMITTED",
        }
    )
    DB["smoke_approvals"][smoke["id"]] = smoke
    return ok(ser_smoke(smoke), 201)


@bp.get("/smoke-approvals/<sid>")
def get_one_smoke(sid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_smoke(get_smoke(sid)))


@bp.get("/burn-plans/<pid>/smoke-approvals")
def list_plan_smoke(pid):
    _, role = auth()
    require_role(role, None)
    plan = get_plan(pid)
    items = [s for s in DB["smoke_approvals"].values() if s["burn_plan_id"] == plan["id"]]
    return paginate(items, ser_smoke)


@bp.post("/smoke-approvals/<sid>/decide")
def decide_smoke(sid):
    data = body()
    _, role = auth()
    require_role(role, {"AirQualityOfficer"})
    smoke = get_smoke(sid)
    if smoke["status"] != "SUBMITTED":
        raise ApiError("ERR_SMOKE_NOT_SUBMITTED", 409, "SmokeApproval must be SUBMITTED")
    v = Validator(data, {"decision", "decision_note"})
    v.enum("decision", {"APPROVED", "CONDITIONALLY_APPROVED", "DENIED"})
    v.opt("decision_note", str)
    v.finish()
    decision = data["decision"]
    if decision in ("APPROVED", "CONDITIONALLY_APPROVED"):
        assoc = the_association()
        if assoc is not None:
            committed = sum(
                s["requested_acres"]
                for s in DB["smoke_approvals"].values()
                if s["id"] != smoke["id"]
                and s["status"] in ("APPROVED", "CONDITIONALLY_APPROVED")
                and s["airshed_id"] == smoke["airshed_id"]
                and s["requested_burn_date"] == smoke["requested_burn_date"]
            )
            if committed + smoke["requested_acres"] > assoc["airshed_daily_acres_cap"]:
                raise ApiError(
                    "ERR_AIRSHED_CAPACITY_EXCEEDED",
                    409,
                    "Airshed daily approved acres would exceed the cap",
                )
    smoke["status"] = decision
    if data.get("decision_note") is not None:
        smoke["decision_note"] = data["decision_note"]
    touch(smoke)
    return ok(ser_smoke(smoke))


@bp.post("/smoke-approvals/<sid>/withdraw")
def withdraw_smoke(sid):
    body()
    _, role = auth()
    require_role(role, {"AirQualityOfficer"})
    smoke = get_smoke(sid)
    if smoke["status"] not in ("APPROVED", "CONDITIONALLY_APPROVED"):
        raise ApiError(
            "ERR_SMOKE_NOT_WITHDRAWABLE",
            409,
            "SmokeApproval must be APPROVED or CONDITIONALLY_APPROVED",
        )
    smoke["status"] = "WITHDRAWN"
    touch(smoke)
    return ok(ser_smoke(smoke))


@bp.post("/smoke-approvals/<sid>/clear-conditions")
def clear_conditions(sid):
    body()
    _, role = auth()
    require_role(role, {"AirQualityOfficer"})
    smoke = get_smoke(sid)
    if smoke["status"] != "CONDITIONALLY_APPROVED":
        raise ApiError(
            "ERR_SMOKE_NOT_CONDITIONAL", 409, "SmokeApproval must be CONDITIONALLY_APPROVED"
        )
    smoke["status"] = "APPROVED"
    touch(smoke)
    return ok(ser_smoke(smoke))
