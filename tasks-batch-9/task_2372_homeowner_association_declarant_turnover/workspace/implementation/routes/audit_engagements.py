"""Transition audit engagements: engagement over a period and report issuance."""
from flask import Blueprint

import auth
import calc
import cascades
import constants
import response
import util
import validation as v
from db import db, new_record, serialize, touch
from errors import ApiError
from routes import common

bp = Blueprint("audit_engagements", __name__)


@bp.post("/hoa/audit-engagements")
def create_engagement():
    auth.require_roles(constants.ROLE_AUDITOR)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")

    period_start, start_dt = v.get_datetime(body, "period_start")
    period_end, end_dt = v.get_datetime(body, "period_end")
    if end_dt < start_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST", "period_end must be at or after period_start."
        )

    # closed-interval overlap against every ENGAGED or ISSUED engagement
    for existing in calc.engagements_of(association["id"]):
        if existing["status"] not in ("ENGAGED", "ISSUED"):
            continue
        other_start = util.parse_dt(existing["period_start"])
        other_end = util.parse_dt(existing["period_end"])
        if start_dt <= other_end and other_start <= end_dt:
            raise ApiError("ERR_AUDIT_PERIOD_OVERLAP")

    engagement = new_record({
        "association_id": association["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "ENGAGED",
        "finding_status": "CLEAN",
        "unreconciled_delta_cents": 0,
        "audited_receivable_snapshot_cents": 0,
        "issued_by_user_id": None,
    })
    db.audit_engagements[engagement["id"]] = engagement
    return response.object_response(serialize(engagement), 201)


@bp.post("/hoa/audit-engagements/<engagement_id>/issue")
def issue_engagement(engagement_id):
    auth.require_roles(constants.ROLE_AUDITOR)
    engagement = common.audit_engagement_or_404(engagement_id, scoped=True)

    # ---- segregation of duties (ladder step 3) ----
    low = util.month_of(util.parse_dt(engagement["period_start"]))
    high = util.month_of(util.parse_dt(engagement["period_end"]))
    actor = auth.current_user_id()
    for entry in calc.entries_of(engagement["association_id"]):
        if entry["status"] != "POSTED":
            continue
        if not (low <= entry["period_month"] <= high):
            continue
        if entry["posted_by_user_id"] == actor:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if engagement["status"] != "ENGAGED":
        raise ApiError("ERR_AUDIT_NOT_ISSUABLE")

    association = db.associations[engagement["association_id"]]
    engagement["status"] = "ISSUED"
    engagement["issued_by_user_id"] = actor
    engagement["audited_receivable_snapshot_cents"] = calc.audit_snapshot(engagement)
    delta = calc.audit_delta(engagement, association)
    engagement["unreconciled_delta_cents"] = delta
    engagement["finding_status"] = "CLEAN" if delta == 0 else "EXCEPTION_NOTED"
    touch(engagement)

    cascades.refresh_issued_engagements(association)
    return response.object_response(serialize(engagement))
