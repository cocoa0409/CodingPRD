"""Applicant routes + the prosecution risk score (PRD §3.1, §3.7)."""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success
from services import models
from services.body import get_json_body, require_nonempty_string, require_enum
from services import calc

bp = Blueprint("applicants", __name__)

ENTITY_TYPES = {"INDIVIDUAL", "CORPORATION", "PARTNERSHIP", "LLC"}


@bp.post("/applicants")
@require_roles("Attorney", "Applicant")
def create_applicant(_user_id, _role):
    body = get_json_body()
    legal_name = require_nonempty_string(body, "legal_name")
    entity_type = require_enum(body, "entity_type", ENTITY_TYPES)
    country_code = require_nonempty_string(body, "country_code")
    if not (len(country_code) == 2 and country_code.isalpha() and country_code.isupper()):
        raise_api("ERR_VALIDATION", "country_code must be 2 uppercase letters")

    rec = models.make_record({
        "legal_name": legal_name,
        "entity_type": entity_type,
        "country_code": country_code,
    })
    db.applicants[rec["id"]] = rec
    return success(models.ser_applicant(rec), 201)


@bp.get("/applicants/<rid>")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def get_applicant(rid, _user_id, _role):
    rec = models.get_or_404(db.applicants, rid, "Applicant")
    return success(models.ser_applicant(rec), 200)


@bp.get("/applicants/<rid>/risk-score")
@require_roles("Attorney", "Examiner")
def risk_score(rid, _user_id, _role):
    applicant = models.get_or_404(db.applicants, rid, "Applicant")

    include_pending = request.args.get("include_pending_deadlines", "")
    projected = str(include_pending).lower() == "true"

    # Applications owned by this applicant.
    app_ids = {
        a["id"] for a in db.applications.values() if a["applicant_id"] == rid
    }

    base = 0
    # 15 per OUTSTANDING OfficeAction across this applicant's applications.
    base += calc.W_OPEN_OA * sum(
        1
        for oa in db.office_actions.values()
        if oa["application_id"] in app_ids and oa["status"] == "OUTSTANDING"
    )
    # 10 per OfficeActionResponse with days_late > 0 across this applicant's applications.
    oa_ids = {
        oa["id"] for oa in db.office_actions.values() if oa["application_id"] in app_ids
    }
    base += calc.W_LATE_RESP * sum(
        1
        for r in db.office_action_responses.values()
        if r["office_action_id"] in oa_ids and r["days_late"] > 0
    )
    # 40 per DEFAULTED TTABProceeding where the targeted mark belongs to this applicant.
    reg_ids_owned = {
        reg["id"]
        for reg in db.registrations.values()
        if reg["application_id"] in app_ids
    }
    base += calc.W_DEFAULT * sum(
        1
        for p in db.ttab_proceedings.values()
        if p["defense_status"] == "DEFAULTED"
        and (
            (p.get("target_application_id") in app_ids)
            or (p.get("target_registration_id") in reg_ids_owned)
        )
    )
    # 20 per GRACE Registration owned by the applicant via its application.
    base += calc.W_GRACE_REG * sum(
        1
        for reg in db.registrations.values()
        if reg["application_id"] in app_ids and reg["status"] == "GRACE"
    )

    variant = "snapshot"
    if projected:
        variant = "projected"
        now = db.current_utc_dt()
        from db import parse_iso
        # PENDING deadlines reachable from this applicant: those rolling up to one
        # of its applications (application_id), plus MAINTENANCE deadlines (which
        # carry no application_id) keyed to a registration the applicant owns.
        for d in db.docket_deadlines.values():
            if d["status"] != "PENDING":
                continue
            reachable = d.get("application_id") in app_ids
            if not reachable and d["subject_type"] == "MAINTENANCE":
                reachable = d["subject_id"] in reg_ids_owned
            if not reachable:
                continue
            if parse_iso(d["due_at"]) < now:
                base += calc.W_OPEN_OA

    score = min(calc.SCORE_CEILING, base)
    return success(
        {"applicant_id": rid, "risk_score": score, "variant": variant}, 200
    )
