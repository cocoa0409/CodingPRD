"""LanguageAssessment endpoints (PRD §3.2)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_ASSESSMENT_PERIOD_OVERLAP,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_INVALID_TRANSITION,
    ERR_VALIDATION,
)
from middleware import authorized, check_liaison_owns_department
from response import success_object
from routes.helpers import get_one, list_endpoint
from services.core import touch
from services.serializers import serialize_assessment
from util import CLOCK, new_id, next_seq, parse_iso, share4
from validate import (
    get_body,
    opt_str,
    reject_unknown_fields,
    req_datetime_str,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("language_assessments", __name__)

CREATE_FIELDS = {
    "department_id", "language_code", "plan_year", "period_start", "period_end",
    "lep_speaker_count", "service_area_population", "encounter_count", "total_encounters",
}
SAFE_HARBOR_SHARE = Decimal("0.05")
SAFE_HARBOR_COUNT = 1000


@bp.post("/language-assessments")
def create_assessment():
    caller = authorized(["DepartmentLiaison"])
    body = get_body()
    # Priority 2 ownership scope before shape: liaison acts on own department.
    check_liaison_owns_department(caller, body.get("department_id"))
    reject_unknown_fields(body, CREATE_FIELDS)
    department_id = req_str(body, "department_id")
    language_code = req_str(body, "language_code")
    plan_year = req_int(body, "plan_year")
    period_start = req_datetime_str(body, "period_start")
    period_end = req_datetime_str(body, "period_end")
    lep_speaker_count = req_int(body, "lep_speaker_count", non_negative=True)
    service_area_population = req_int(body, "service_area_population", positive=True)
    encounter_count = req_int(body, "encounter_count", non_negative=True)
    total_encounters = req_int(body, "total_encounters", positive=True)
    if not parse_iso(period_start) < parse_iso(period_end):
        raise_error(ERR_VALIDATION, "period_start must be earlier than period_end")

    # Priority 4: body FK existence.
    require_path("departments", department_id, ERR_DEPARTMENT_NOT_FOUND)

    # Priority 7 temporal: half-open window overlap per (department, language).
    nps, npe = parse_iso(period_start), parse_iso(period_end)
    for a in db["language_assessments"].values():
        if a["department_id"] == department_id and a["language_code"] == language_code:
            ps, pe = parse_iso(a["period_start"]), parse_iso(a["period_end"])
            if nps < pe and ps < npe:
                raise_error(
                    ERR_ASSESSMENT_PERIOD_OVERLAP,
                    "assessment coverage window overlaps an existing window for this department and language",
                )

    lep_share = share4(lep_speaker_count, service_area_population)
    encounter_share = share4(encounter_count, total_encounters)
    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "department_id": department_id,
        "language_code": language_code,
        "plan_year": plan_year,
        "period_start": period_start,
        "period_end": period_end,
        "lep_speaker_count": lep_speaker_count,
        "service_area_population": service_area_population,
        "encounter_count": encounter_count,
        "total_encounters": total_encounters,
        "lep_share": lep_share,
        "encounter_share": encounter_share,
        "threshold_language_safe": bool(lep_share >= SAFE_HARBOR_SHARE or lep_speaker_count >= SAFE_HARBOR_COUNT),
        "priority_language": bool(encounter_share >= SAFE_HARBOR_SHARE),
        "status": "DRAFT",
        "created_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
        "rejection_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["language_assessments"][rec["id"]] = rec
    return success_object(serialize_assessment(rec), status=201)


@bp.get("/language-assessments")
def list_assessments():
    filters = {
        "department_id": request.args.get("department_id"),
        "plan_year": request.args.get("plan_year"),
        "status": request.args.get("status"),
    }
    return list_endpoint("language_assessments", serialize_assessment, filters,
                         int_filter_fields=("plan_year",))


@bp.get("/language-assessments/<rid>")
def get_assessment(rid):
    return get_one("language_assessments", rid, ERR_ASSESSMENT_NOT_FOUND, serialize_assessment)


@bp.post("/language-assessments/<rid>/review")
def review_assessment(rid):
    caller = authorized(["ComplianceOfficer"])
    body = get_body()
    reject_unknown_fields(body, {"decision", "rejection_note"})
    decision = req_str(body, "decision")
    if decision not in ("CERTIFY", "REJECT"):
        raise_error(ERR_VALIDATION, "decision must be CERTIFY or REJECT")
    rejection_note = opt_str(body, "rejection_note")
    if decision == "REJECT" and rejection_note is None:
        raise_error(ERR_VALIDATION, "rejection_note is required when decision is REJECT")

    rec = require_path("language_assessments", rid, ERR_ASSESSMENT_NOT_FOUND)
    if rec["status"] != "DRAFT":
        raise_error(ERR_INVALID_TRANSITION, "only a DRAFT assessment may be reviewed")

    rec["reviewed_by_user_id"] = caller.user_id
    if decision == "CERTIFY":
        rec["status"] = "CERTIFIED"
    else:
        rec["status"] = "REJECTED"
        rec["rejection_note"] = rejection_note
    touch(rec)
    return success_object(serialize_assessment(rec))
