"""Plan amendments (PRD 3.1)."""

from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, body, opt_str, req_enum, req_str, req_ts
from response import object_response, paginated
from services import lookup, serialize

bp = Blueprint("amendments", __name__)

AMENDMENT_STATUSES = ("DRAFTED", "ADOPTED", "NOTICE_SENT", "EFFECTIVE",
                      "RESCINDED")
NOTICE_CHANNELS = ("EMAIL", "MAIL", "PORTAL")
TRANSITIONS = (("DRAFTED", "ADOPTED"), ("ADOPTED", "NOTICE_SENT"),
               ("NOTICE_SENT", "EFFECTIVE"), ("ADOPTED", "RESCINDED"),
               ("NOTICE_SENT", "RESCINDED"))


@bp.post("/plan-amendments")
def create_amendment():
    auth("BenefitsAdministrator")
    payload = body()
    plan_year_id = req_str(payload, "plan_year_id")
    document_ref = req_str(payload, "document_ref")
    effective_date, effective_dt = req_ts(payload, "effective_date")
    lookup.plan_year(plan_year_id)
    row = {
        "plan_year_id": plan_year_id,
        "document_ref": document_ref,
        "effective_date": effective_date,
        "status": "DRAFTED",
        "adopted_at": None,
        "notice_sent_at": None,
        "effective_at": None,
        "notice_channel": None,
        "rescinded_reason": None,
        "_effective_dt": effective_dt,
    }
    db.stamp_new(row)
    db.db.plan_amendments[row["id"]] = row
    return object_response(serialize.plan_amendment(row), 201)


@bp.get("/plan-amendments")
def list_amendments():
    auth("BenefitsAdministrator", "ComplianceAuditor")
    rows = db.rows("plan_amendments")
    plan_year_id = request.args.get("plan_year_id")
    if plan_year_id:
        rows = [r for r in rows if r["plan_year_id"] == plan_year_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, serialize.plan_amendment)


@bp.get("/plan-amendments/<amendment_id>")
def get_amendment(amendment_id):
    auth("BenefitsAdministrator", "ComplianceAuditor")
    return object_response(serialize.plan_amendment(
        lookup.amendment(amendment_id)))


@bp.post("/plan-amendments/<amendment_id>/status")
def set_amendment_status(amendment_id):
    auth("BenefitsAdministrator")
    payload = body()
    to_status = req_enum(payload, "to_status", AMENDMENT_STATUSES)
    notice_channel = None
    rescinded_reason = None
    if to_status == "NOTICE_SENT":
        notice_channel = req_enum(payload, "notice_channel", NOTICE_CHANNELS)
    if to_status == "RESCINDED":
        rescinded_reason = req_str(payload, "rescinded_reason")

    amendment = lookup.amendment(amendment_id)
    current = amendment["status"]
    if (current, to_status) not in TRANSITIONS:
        fail("ERR_AMENDMENT_STATE_INVALID",
             "amendment cannot move from %s to %s" % (current, to_status))

    if to_status in ("ADOPTED", "EFFECTIVE"):
        py = db.db.plan_years.get(amendment["plan_year_id"])
        if py is None or py["status"] not in ("DRAFT", "OPEN"):
            fail("ERR_PLAN_YEAR_LOCKED",
                 "the amendment's plan year no longer accepts this transition")

    if to_status == "EFFECTIVE":
        if db.now() < amendment["_effective_dt"]:
            fail("ERR_AMENDMENT_EFFECTIVE_DATE_FUTURE",
                 "the amendment's effective_date has not yet arrived")

    amendment["status"] = to_status
    if to_status == "ADOPTED":
        amendment["adopted_at"] = db.now_iso()
    elif to_status == "NOTICE_SENT":
        amendment["notice_channel"] = notice_channel
        amendment["notice_sent_at"] = db.now_iso()
    elif to_status == "EFFECTIVE":
        amendment["effective_at"] = db.now_iso()
    elif to_status == "RESCINDED":
        amendment["rescinded_reason"] = rescinded_reason
    db.touch(amendment)
    return object_response(serialize.plan_amendment(amendment))
