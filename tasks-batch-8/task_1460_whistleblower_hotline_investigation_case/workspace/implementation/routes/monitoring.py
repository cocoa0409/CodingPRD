"""Closure notice and monitoring plan endpoints (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    CHECKIN_INTERVAL_DAYS,
    acknowledge_notice,
    bump,
    get_case,
    get_notice,
    get_plan,
    notice_view,
    paginate,
    plan_view,
)
from util import pagination_args
from db import now_dt

bp = Blueprint("monitoring", __name__)


@bp.get("/hotline/cases/<cid>/closure-notices")
def list_notices(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [n for n in DB["closure_notices"].values() if n["case_id"] == cid]
    page, total = paginate(records, limit, offset)
    return ok_list([notice_view(n) for n in page], total, limit, offset)


@bp.post("/hotline/closure-notices/<nid>/acknowledge")
def acknowledge(nid):
    user_id, role = auth(["HotlineReporter"])
    notice = get_notice(nid)
    case = DB["cases"].get(notice["case_id"])
    if case is not None and user_id != case["reporter_access_key"]:
        raise ApiError(
            "ERR_REPORTER_ACCESS_DENIED", 403, "X-User-ID does not match the case access key"
        )
    if notice["status"] != "SENT":
        raise ApiError("ERR_NOTICE_NOT_SENT", 409, "Acknowledge requires notice SENT")
    acknowledge_notice(notice, case, role, user_id)
    return ok(notice_view(notice))


@bp.get("/hotline/cases/<cid>/monitoring-plans")
def list_plans(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [p for p in DB["monitoring_plans"].values() if p["case_id"] == cid]
    page, total = paginate(records, limit, offset)
    return ok_list([plan_view(p) for p in page], total, limit, offset)


@bp.post("/hotline/monitoring-plans/<pid>/check-in")
def check_in(pid):
    auth(["ComplianceOfficer"])
    plan = get_plan(pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Check-in requires plan ACTIVE")
    now = now_dt()
    plan["last_check_in_at"] = now
    plan["next_check_in_due"] = now + timedelta(days=CHECKIN_INTERVAL_DAYS)
    bump(plan)
    return ok(plan_view(plan))
