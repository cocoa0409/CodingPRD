"""Assessment phases, contaminant findings, submission and agency review."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import actor_id, endpoint
from routes.common import apply_filter, fetch, party_or_404, require_party_type
from services import calc, derive
from services.constants import (
    DELINEATION_CONFIDENCE,
    MEDIA,
    PHASE_STATUS,
    PHASE_TYPES,
)
from services.serialize import dump_finding, dump_phase

bp = Blueprint("phases", __name__)

READ_ROLES = ["EnvironmentalConsultant", "StateAgencyReviewer", "Redeveloper",
              "Insurer", "Lender"]
FINDING_READ_ROLES = ["EnvironmentalConsultant", "StateAgencyReviewer",
                      "Redeveloper", "Insurer"]


def _recompute_max_ef(phase):
    factors = [calc.D(f["exceedance_factor"])
               for f in derive.findings_of_phase(phase["id"])]
    phase["max_exceedance_factor"] = float(max(factors)) if factors else 0
    return phase["max_exceedance_factor"]


@bp.post("/assessment-phases")
@endpoint(["EnvironmentalConsultant"])
def create_phase():
    body = V.json_body()
    site_id = V.id_field(body, "site_id", True)
    consultant_party_id = V.id_field(body, "consultant_party_id", True)
    phase_type = V.enum_field(body, "phase_type", PHASE_TYPES, True)
    start = V.date_field(body, "field_start_date", True)
    end = V.date_field(body, "field_end_date", True)
    confidence = V.enum_field(body, "delineation_confidence",
                              DELINEATION_CONFIDENCE, True)
    aai_report_date = V.date_field(body, "aai_report_date", False)
    delineation_complete = V.bool_field(body, "delineation_complete", False,
                                        default=False)
    supersedes_phase_id = V.id_field(body, "supersedes_phase_id", False)

    if end < start:
        V.fail("Field field_end_date must be on or after field_start_date.")
    if phase_type == "PHASE_I" and aai_report_date is None:
        V.fail("Field aai_report_date is required when phase_type is PHASE_I.")
    if phase_type != "PHASE_I" and aai_report_date is not None:
        V.fail("Field aai_report_date is only allowed when phase_type is PHASE_I.")

    site = fetch("sites", site_id)
    consultant = party_or_404(consultant_party_id)
    if supersedes_phase_id is not None:
        fetch("assessment_phases", supersedes_phase_id)
    require_party_type(consultant, "CONSULTANT")
    derive.assert_not_frozen(site)

    row = db.insert("assessment_phases", {
        "site_id": site["id"],
        "consultant_party_id": consultant_party_id,
        "supersedes_phase_id": supersedes_phase_id,
        "phase_type": phase_type,
        "field_start_date": start.isoformat(),
        "field_end_date": end.isoformat(),
        "aai_report_date": aai_report_date.isoformat() if aai_report_date else None,
        "delineation_confidence": confidence,
        "delineation_complete": delineation_complete,
        "status": "DRAFT",
        "review_round": 0,
        "findings_count": 0,
        "max_exceedance_factor": 0,
        "submitted_at": None,
        "reviewed_by_user_id": None,
        "review_comment": None,
    })
    return response.created(dump_phase(row))


@bp.get("/assessment-phases")
@endpoint(READ_ROLES)
def list_phases():
    rows = db.ordered(db.all_rows("assessment_phases"))
    rows = apply_filter(rows, "site_id", V.query_string("site_id"))
    rows = apply_filter(rows, "consultant_party_id",
                        V.query_string("consultant_party_id"))
    rows = apply_filter(rows, "supersedes_phase_id",
                        V.query_string("supersedes_phase_id"))
    rows = apply_filter(rows, "phase_type", V.query_enum("phase_type", PHASE_TYPES))
    rows = apply_filter(rows, "status", V.query_enum("status", PHASE_STATUS))
    return response.list_response(rows, dump_phase)


@bp.get("/assessment-phases/<phase_id>")
@endpoint(READ_ROLES)
def get_phase(phase_id):
    return response.object_response(dump_phase(fetch("assessment_phases", phase_id)))


# ------------------------------------------------------- contaminant findings


@bp.post("/assessment-phases/<phase_id>/contaminant-findings")
@endpoint(["EnvironmentalConsultant"])
def create_finding(phase_id):
    body = V.json_body()
    contaminant_code = V.string_field(body, "contaminant_code", True, 1, 24,
                                      upper=True)
    media = V.enum_field(body, "media", MEDIA, True)
    sample_location_code = V.string_field(body, "sample_location_code", True, 1, 40)
    max_conc = V.number_field(body, "max_concentration_ugl", True, ge=0)
    screening = V.number_field(body, "screening_level_ugl", True, gt=0)
    delineated = V.bool_field(body, "delineated", False, default=False)

    phase = fetch("assessment_phases", phase_id)
    site = db.get("sites", phase["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if phase["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_PHASE_STATE",
                       "Findings may only be added to a DRAFT or "
                       "REVISION_REQUESTED phase.")

    row = db.insert("contaminant_findings", {
        "assessment_phase_id": phase["id"],
        "contaminant_code": contaminant_code,
        "media": media,
        "sample_location_code": sample_location_code,
        "max_concentration_ugl": max_conc,
        "screening_level_ugl": screening,
        "delineated": delineated,
        "exceedance_factor": calc.exceedance_factor(max_conc, screening),
    })

    phase["findings_count"] = int(phase["findings_count"]) + 1
    _recompute_max_ef(phase)
    db.touch(phase)
    return response.created(dump_finding(row))


@bp.get("/assessment-phases/<phase_id>/contaminant-findings")
@endpoint(FINDING_READ_ROLES)
def list_findings(phase_id):
    phase = fetch("assessment_phases", phase_id)
    rows = derive.findings_of_phase(phase["id"])
    rows = apply_filter(rows, "media", V.query_enum("media", MEDIA))
    return response.list_response(rows, dump_finding)


@bp.get("/contaminant-findings/<finding_id>")
@endpoint(FINDING_READ_ROLES)
def get_finding(finding_id):
    return response.object_response(
        dump_finding(fetch("contaminant_findings", finding_id)))


# ------------------------------------------------------- submit and review


@bp.post("/assessment-phases/<phase_id>/submit")
@endpoint(["EnvironmentalConsultant"])
def submit_phase(phase_id):
    phase = fetch("assessment_phases", phase_id)
    site = db.get("sites", phase["site_id"])
    if actor_id() != phase["consultant_party_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the phase's consultant may submit it.")
    if site is not None:
        derive.assert_not_frozen(site)
    if phase["status"] == "REJECTED" or int(phase["review_round"]) >= 3:
        raise ApiError("ERR_ASSESSMENT_REVISION_LIMIT",
                       "The phase has exhausted its revision rounds.")
    if phase["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_PHASE_STATE",
                       "Only a DRAFT or REVISION_REQUESTED phase may be submitted.")
    if int(phase["findings_count"]) < 1:
        raise ApiError("ERR_NO_FINDINGS",
                       "A phase must carry at least one finding to be submitted.")
    if phase["phase_type"] == "PHASE_I" and phase.get("aai_report_date") is None:
        V.fail("A PHASE_I phase requires aai_report_date before submission.")

    phase["submitted_at"] = db.now_ts()
    phase["review_round"] = int(phase["review_round"]) + 1
    _recompute_max_ef(phase)
    phase["status"] = "SUBMITTED"
    phase["status"] = "UNDER_REVIEW"
    db.touch(phase)
    return response.object_response(dump_phase(phase))


def _mark_inquiry_deficient(site):
    protection = derive.protection_for_site(site["id"])
    if protection is None:
        return
    protection["inquiry_state"] = "AAI_DEFICIENT"
    derive.recompute_protection(protection, site)
    db.touch(protection)


@bp.post("/assessment-phases/<phase_id>/review")
@endpoint(["StateAgencyReviewer"])
def review_phase(phase_id):
    body = V.json_body()
    decision = V.enum_field(body, "decision", ("APPROVE", "REQUEST_REVISION"), True)
    review_comment = V.string_field(body, "review_comment", False, 1, 2000)

    phase = fetch("assessment_phases", phase_id)
    site = db.get("sites", phase["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if phase["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PHASE_STATE",
                       "Only an UNDER_REVIEW phase may be decided.")

    if decision == "APPROVE":
        if (phase["phase_type"] in ("PHASE_II", "SUPPLEMENTAL")
                and phase["delineation_complete"]):
            for finding in derive.findings_of_phase(phase["id"]):
                if (calc.D(finding["exceedance_factor"]) > calc.D("1.0")
                        and not finding["delineated"]):
                    raise ApiError(
                        "ERR_MEDIA_NOT_DELINEATED",
                        "Finding %s exceeds its screening level but is not "
                        "delineated." % finding["id"])
        phase["status"] = "APPROVED"
        phase["reviewed_by_user_id"] = actor_id()
        db.touch(phase)

        if site is not None:
            changed = False
            if phase["phase_type"] == "PHASE_I":
                if site["delineation_status"] != "DELINEATED":
                    if site["delineation_status"] != "SCREENED":
                        changed = True
                    site["delineation_status"] = "SCREENED"
            elif phase["delineation_complete"]:
                if site["delineation_status"] != "DELINEATED":
                    changed = True
                site["delineation_status"] = "DELINEATED"
            if changed:
                db.touch(site)
            for goal in derive.goals_of_site(site["id"]):
                before = (goal["goal_ugl"], goal["contaminant_count_in_media"],
                          goal["cumulative_cap_applied"])
                derive.recompute_goal(goal, site)
                derive.replay_attainment(goal)
                after = (goal["goal_ugl"], goal["contaminant_count_in_media"],
                         goal["cumulative_cap_applied"])
                if before != after:
                    db.touch(goal)
        return response.object_response(dump_phase(phase))

    # REQUEST_REVISION
    if int(phase["review_round"]) >= 3:
        phase["status"] = "REJECTED"
    else:
        phase["status"] = "REVISION_REQUESTED"
    phase["reviewed_by_user_id"] = actor_id()
    phase["review_comment"] = review_comment
    db.touch(phase)
    if phase["phase_type"] == "PHASE_I" and site is not None:
        _mark_inquiry_deficient(site)
    return response.object_response(dump_phase(phase))
