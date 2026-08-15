"""Document finding endpoints."""
from datetime import date

from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_FINDING_STATE_INVALID,
    ERR_CORRECTION_WINDOW_EXPIRED,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_string,
    req_int,
    req_enum,
    get_or_404,
    stamp_new,
    touch,
    recompute_plan_posture,
)
from util import CLOCK, fmt_date, parse_date

bp = Blueprint("document_findings", __name__)


def finding_view(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "plan_id": f["plan_id"],
        "description": f["description"],
        "failure_year": f["failure_year"],
        "correction_deadline": f["correction_deadline"],
        "correction_text": f["correction_text"],
        "status": f["status"],
        "filed_by_user_id": f["filed_by_user_id"],
        "adjudicated_by_user_id": f["adjudicated_by_user_id"],
    }


@bp.post("/api/document-findings")
def create_finding():
    data = body()
    from errors import ERR_INVALID_REQUEST

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    description = req_string(data, "description")
    failure_year = req_int(data, "failure_year")
    if failure_year > CLOCK.date().year:
        raise_err(ERR_INVALID_REQUEST, "failure_year may not exceed the current clock year")

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to report a document finding")

    finding = stamp_new(
        {
            "plan_id": plan_id,
            "description": description,
            "failure_year": failure_year,
            "correction_deadline": fmt_date(date(failure_year + 2, 12, 31)),
            "correction_text": None,
            "status": "REPORTED",
            "filed_by_user_id": None,
            "adjudicated_by_user_id": None,
        }
    )
    db.document_findings[finding["id"]] = finding
    recompute_plan_posture(plan)
    return ok_object(finding_view(finding), 201)


@bp.get("/api/document-findings")
def list_findings():
    user_context()
    items = list(db.document_findings.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [f for f in items if f["plan_id"] == plan_id]
    return _list_response([finding_view(f) for f in items], request.args)


@bp.get("/api/document-findings/<findingId>")
def get_finding(findingId):
    user_context()
    f = get_or_404(db.document_findings, findingId, "DocumentFinding")
    return ok_object(finding_view(f))


@bp.post("/api/document-findings/<findingId>/file-correction")
def file_correction(findingId):
    data = body()
    correction_text = req_string(data, "correction_text")

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    finding = get_or_404(db.document_findings, findingId, "DocumentFinding")

    if finding["status"] != "REPORTED":
        raise_err(ERR_FINDING_STATE_INVALID, "file-correction requires REPORTED")
    if CLOCK.date() > parse_date(finding["correction_deadline"]):
        raise_err(ERR_CORRECTION_WINDOW_EXPIRED, "Correction deadline has passed")

    finding["correction_text"] = correction_text
    finding["filed_by_user_id"] = user_id
    finding["status"] = "CORRECTION_FILED"
    touch(finding)
    plan = db.plans[finding["plan_id"]]
    recompute_plan_posture(plan)
    return ok_object(finding_view(finding))


@bp.post("/api/document-findings/<findingId>/adjudicate")
def adjudicate_finding(findingId):
    data = body()
    outcome = req_enum(data, "outcome", {"CORRECTED", "REJECTED"})

    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    finding = get_or_404(db.document_findings, findingId, "DocumentFinding")

    if finding["status"] != "CORRECTION_FILED":
        raise_err(ERR_FINDING_STATE_INVALID, "adjudicate requires CORRECTION_FILED")

    finding["adjudicated_by_user_id"] = user_id
    if outcome == "CORRECTED":
        finding["status"] = "CORRECTED"
    else:
        finding["status"] = "REPORTED"
    touch(finding)
    plan = db.plans[finding["plan_id"]]
    recompute_plan_posture(plan)
    return ok_object(finding_view(finding))
