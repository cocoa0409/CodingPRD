"""VisitFinding endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404
from util import (
    as_enum,
    as_int,
    as_str,
    body,
    paginate,
    pagination,
    required,
    stamp_new,
    touch,
)

bp = Blueprint("findings", __name__)

SEVERITIES = {"COMMENDATION", "RECOMMENDATION", "REQUIRED_ACTION"}
FOLLOW_UP_MONTHS = {6, 12, 18}


def finding_view(f):
    return {k: v for k, v in f.items() if not k.startswith("_")}


@bp.post("/accreditation/visits/<id>/findings")
def create_finding(id):
    auth(["Reviewer"])
    visit = get_or_404("visits", id, "VisitEvent")
    data = body()
    standard_id = required(data, "standard_id")
    severity = as_enum(required(data, "severity"), "severity", SEVERITIES)
    narrative = as_str(required(data, "narrative"), "narrative")
    follow_up_months = data.get("follow_up_months")
    if severity == "REQUIRED_ACTION":
        if follow_up_months is None:
            raise ApiError(
                "ERR_VALIDATION",
                400,
                "follow_up_months is required when severity is REQUIRED_ACTION",
            )
        if not isinstance(follow_up_months, int) or isinstance(follow_up_months, bool):
            raise ApiError(
                "ERR_VALIDATION", 400, "follow_up_months must be an integer"
            )
        if follow_up_months not in FOLLOW_UP_MONTHS:
            raise ApiError(
                "ERR_VALIDATION", 400, "follow_up_months must be 6, 12, or 18"
            )
    else:
        if follow_up_months is not None:
            if not isinstance(follow_up_months, int) or isinstance(follow_up_months, bool):
                raise ApiError(
                    "ERR_VALIDATION", 400, "follow_up_months must be an integer"
                )
    standard = DB["standards"].get(standard_id)
    if standard is None:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "standard_id does not exist")
    record = {
        "id": new_id(),
        "visit_id": id,
        "standard_id": standard_id,
        "severity": severity,
        "follow_up_months": follow_up_months,
        "narrative": narrative,
        "status": "DRAFT",
    }
    stamp_new(record, with_version=True)
    DB["findings"][record["id"]] = record
    return ok(finding_view(record), status=201)


@bp.get("/accreditation/visits/<id>/findings")
def list_visit_findings(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    get_or_404("visits", id, "VisitEvent")
    limit, offset = pagination()
    rows = [f for f in DB["findings"].values() if f["visit_id"] == id]
    rows.sort(key=lambda f: f["created_at"])
    severity = request.args.get("severity")
    status = request.args.get("status")
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([finding_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/findings/<id>")
def get_finding(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    row = get_or_404("findings", id, "VisitFinding")
    return ok(finding_view(row))


@bp.post("/accreditation/findings/<id>/issue")
def issue_finding(id):
    user_id, _ = auth(["Reviewer"])
    finding = get_or_404("findings", id, "VisitFinding")
    if finding["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Finding is not DRAFT")
    visit = DB["visits"].get(finding["visit_id"])
    if visit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent visit not found")
    if visit["lead_reviewer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Only the lead reviewer may issue findings"
        )
    if visit["status"] not in ("IN_FIELD", "REPORT_DRAFT"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Parent visit must be IN_FIELD or REPORT_DRAFT",
        )
    finding["status"] = "ISSUED"
    touch(finding)
    return ok(finding_view(finding))


@bp.post("/accreditation/findings/<id>/supersede")
def supersede_finding(id):
    user_id, _ = auth(["Reviewer"])
    finding = get_or_404("findings", id, "VisitFinding")
    if finding["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Finding is not DRAFT")
    visit = DB["visits"].get(finding["visit_id"])
    if visit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent visit not found")
    if visit["lead_reviewer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Only the lead reviewer may supersede findings"
        )
    if visit["status"] != "REPORT_DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Parent visit must be REPORT_DRAFT",
        )
    finding["status"] = "SUPERSEDED"
    touch(finding)
    return ok(finding_view(finding))
