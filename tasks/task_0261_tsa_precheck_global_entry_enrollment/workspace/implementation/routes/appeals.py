"""Appeals (PRD §3.7).

Filing is reserved to the Applicant; deciding is reserved to the AppealsOfficer
and enforces segregation of duties against the adjudicating VettingOfficer.
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_APPEAL_LIMIT_REACHED,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import current_user_id, require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services.audit import write_audit
from services.lookups import get_or_404

bp = Blueprint("appeals", __name__)

APPEAL_READ_ROLES = ["Applicant", "AppealsOfficer", "SchedulingAdmin"]


@bp.route("/applications/<app_id>/appeals", methods=["POST"])
def file_appeal(app_id):
    require_auth(["Applicant"])
    app = get_or_404(db.applications, app_id, "Application")
    body = get_body()
    require_fields(body, ["filed_reason"])
    filed_reason = require_str(body, "filed_reason")

    # State precondition (priority 7): DENIED.
    if app["status"] != "DENIED":
        raise APIError(ERR_INVALID_STATE, 409, "Application must be DENIED to appeal")
    # Appeal limit (priority 18): at most one per denial.
    if app["appeal_count"] >= 1:
        raise APIError(ERR_APPEAL_LIMIT_REACHED, 409, "An appeal already exists for this denial")

    appeal = {
        "application_id": app_id,
        "filed_reason": filed_reason,
        "decided_by_user_id": None,
        "outcome": None,
        "status": "OPEN",
    }
    stamp_create(appeal)
    db.appeals[appeal["id"]] = appeal

    app["status"] = "APPEAL_PENDING"
    app["appeal_count"] += 1
    touch(app)
    write_audit(app_id, "APPEAL_FILED", "Appeal filed")
    return ok_object(serialize(appeal), 201)


@bp.route("/applications/<app_id>/appeals", methods=["GET"])
def list_appeals(app_id):
    require_auth(APPEAL_READ_ROLES)
    get_or_404(db.applications, app_id, "Application")
    limit, offset = parse_pagination()
    items = [a for a in db.appeals.values() if a.get("application_id") == app_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.route("/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    require_auth(APPEAL_READ_ROLES)
    rec = get_or_404(db.appeals, aid, "Appeal")
    return ok_object(serialize(rec), 200)


@bp.route("/appeals/<aid>/decide", methods=["POST"])
def decide(aid):
    require_auth(["AppealsOfficer"])
    appeal = get_or_404(db.appeals, aid, "Appeal")
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = require_enum(body, "outcome", ["UPHELD", "OVERTURNED"])

    # State precondition (priority 7): OPEN.
    if appeal["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Appeal must be OPEN to decide")

    app = db.applications.get(appeal["application_id"])
    bc = _the_check(appeal["application_id"]) if app is not None else None

    # Segregation of duties (priority 17): decider must differ from the vetting
    # officer who adjudicated the background check.
    if bc is not None and bc.get("adjudicated_by_user_id") is not None:
        if current_user_id() == bc["adjudicated_by_user_id"]:
            raise APIError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "Appeals decider must differ from the adjudicating VettingOfficer")

    appeal["status"] = "DECIDED"
    appeal["outcome"] = outcome
    appeal["decided_by_user_id"] = current_user_id()
    touch(appeal)

    if app is not None:
        if outcome == "OVERTURNED":
            app["status"] = "VETTING"
            if bc is not None and bc["status"] == "ADVERSE":
                bc["status"] = "PENDING"
                touch(bc)
            app["adverse_reason"] = None
            touch(app)
            write_audit(app["id"], "APPEAL_OVERTURNED", "Appeal overturned; vetting reopened")
        else:  # UPHELD
            app["status"] = "DENIED"
            touch(app)
            write_audit(app["id"], "APPEAL_UPHELD", "Appeal upheld; denial stands")

    return ok_object(serialize(appeal), 200)


def _the_check(app_id: str):
    for bc in db.background_checks.values():
        if bc.get("application_id") == app_id:
            return bc
    return None
