"""Colonies and their nested resources: cats, complaints, population
surveys, population report (PRD §3.1, §3.7, §3.9).

Nested identifiers are validated left-to-right (PRD §2.10): the colony id in
the path resolves before any body foreign keys.
"""

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_COLONY_NOT_DISSOLVABLE,
                    ERR_SURVEY_INCONSISTENT, ERR_UNIQUENESS_VIOLATION,
                    not_found, validation)
from middleware import json_body, require_roles
from response import paginate, success_object
from services.colony_service import recompute_colony
from services.trend_service import population_report
from util import (now_dt, now_iso, opt_str, parse_datetime, public, req_enum,
                  req_int, req_str, sorted_created, stamp_common, stamp_survey,
                  touch)

bp = Blueprint("colonies", __name__)

CAT_TERMINAL_STATES = {"RETURNED", "COLONY_STERILIZED", "ADOPTED", "DECEASED"}
COMPLAINT_CATEGORIES = {"NOISE", "ODOR", "PROPERTY_DAMAGE", "WILDLIFE_CONFLICT",
                        "OVERPOPULATION"}
HIGH_SEVERITY_CATEGORIES = {"PROPERTY_DAMAGE", "WILDLIFE_CONFLICT"}
KITTEN_AGE_MONTHS = 6


def get_colony_or_404(colony_id):
    colony = db.colonies.get(colony_id)
    if colony is None:
        raise not_found("colony")
    return colony


# --- colonies ---------------------------------------------------------------

@bp.post("/tnr/colonies")
@require_roles("ProgramCoordinator")
def create_colony(user_id, role):
    body = json_body()
    name = req_str(body, "name")
    address = req_str(body, "address")
    caretaker_id = req_str(body, "caretaker_id")
    estimated_population = req_int(body, "estimated_population", minimum=1)

    if caretaker_id not in db.caretakers:
        raise not_found("caretaker")

    colony = stamp_common({
        "name": name,
        "address": address,
        "caretaker_id": caretaker_id,
        "registered_on": now_iso(),
        "estimated_population": estimated_population,
        "monitoring_status": "ACTIVE",
        "sterilized_pct": 0.0,
        "status": "REGISTERED",
    })
    db.colonies[colony["id"]] = colony
    return success_object(public(colony), status=201)


@bp.get("/tnr/colonies/<cid>")
@require_roles("ProgramCoordinator", "Caretaker", "AnimalControlOfficer",
               "ClinicStaff")
def get_colony(cid, user_id, role):
    return success_object(public(get_colony_or_404(cid)))


@bp.get("/tnr/colonies")
@require_roles("ProgramCoordinator", "Caretaker", "AnimalControlOfficer")
def list_colonies(user_id, role):
    rows = list(db.colonies.values())
    caretaker_id = request.args.get("caretaker_id")
    if caretaker_id is not None:
        rows = [c for c in rows if c["caretaker_id"] == caretaker_id]
    monitoring_status = request.args.get("monitoring_status")
    if monitoring_status is not None:
        rows = [c for c in rows if c["monitoring_status"] == monitoring_status]
    return paginate([public(c) for c in sorted_created(rows)])


@bp.post("/tnr/colonies/<cid>/dissolve")
@require_roles("ProgramCoordinator")
def dissolve_colony(cid, user_id, role):
    colony = get_colony_or_404(cid)
    if colony["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Colony is {colony['status']}; only REGISTERED colonies "
                       "can be dissolved.")
    residents = [c for c in db.cats.values() if c["colony_id"] == cid]
    if any(c["status"] not in CAT_TERMINAL_STATES for c in residents):
        raise ApiError(ERR_COLONY_NOT_DISSOLVABLE, 409,
                       "Every resident cat must be in a terminal state "
                       "(RETURNED, COLONY_STERILIZED, ADOPTED, DECEASED) before "
                       "the colony can be dissolved.")
    colony["status"] = "DISSOLVED"
    touch(colony)
    return success_object(public(colony))


# --- cats (nested under colonies) -------------------------------------------

@bp.post("/tnr/colonies/<cid>/cats")
@require_roles("ProgramCoordinator", "Caretaker")
def create_cat(cid, user_id, role):
    colony = get_colony_or_404(cid)
    body = json_body()
    intake_tag = req_str(body, "intake_tag")
    sex = req_enum(body, "sex", {"MALE", "FEMALE", "UNKNOWN"})
    age = req_int(body, "approximate_age_months", minimum=0)

    if any(c["colony_id"] == cid and c["intake_tag"] == intake_tag
           for c in db.cats.values()):
        raise ApiError(ERR_UNIQUENESS_VIOLATION, 409,
                       f"A cat with intake_tag {intake_tag!r} already exists in "
                       "this colony.")

    cat = stamp_common({
        "colony_id": cid,
        "intake_tag": intake_tag,
        "sex": sex,
        "approximate_age_months": age,
        "is_kitten": age < KITTEN_AGE_MONTHS,
        "ear_tipped": False,
        "vaccinated_rabies": False,
        "status": "AT_LARGE",
        "pathway": None,
    })
    db.cats[cat["id"]] = cat
    # Intake enlarges the resident set — recompute (PRD §2.6).
    recompute_colony(colony)
    return success_object(public(cat), status=201)


@bp.get("/tnr/colonies/<cid>/cats")
@require_roles("ProgramCoordinator", "Caretaker", "AnimalControlOfficer",
               "ClinicStaff", "FosterVolunteer")
def list_colony_cats(cid, user_id, role):
    get_colony_or_404(cid)
    rows = [c for c in db.cats.values() if c["colony_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return paginate([public(c) for c in sorted_created(rows)])


# --- complaints (nested under colonies) -------------------------------------

@bp.post("/tnr/colonies/<cid>/complaints")
@require_roles("AnimalControlOfficer")
def create_complaint(cid, user_id, role):
    colony = get_colony_or_404(cid)
    body = json_body()
    complainant_name = req_str(body, "complainant_name")
    category = req_enum(body, "category", COMPLAINT_CATEGORIES)

    complaint = stamp_common({
        "colony_id": cid,
        "complainant_name": complainant_name,
        "category": category,
        "filed_at": now_iso(),
        "severity": "HIGH" if category in HIGH_SEVERITY_CATEGORIES else "STANDARD",
        "status": "OPEN",
    })
    db.complaints[complaint["id"]] = complaint
    # A new OPEN complaint re-derives the colony posture (PRD §2.6/§3.7).
    recompute_colony(colony)
    return success_object(public(complaint), status=201)


@bp.get("/tnr/colonies/<cid>/complaints")
@require_roles("ProgramCoordinator", "AnimalControlOfficer", "Caretaker")
def list_colony_complaints(cid, user_id, role):
    get_colony_or_404(cid)
    rows = [c for c in db.complaints.values() if c["colony_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return paginate([public(c) for c in sorted_created(rows)])


# --- population surveys & report --------------------------------------------

@bp.post("/tnr/colonies/<cid>/population-surveys")
@require_roles("ProgramCoordinator", "Caretaker")
def create_population_survey(cid, user_id, role):
    get_colony_or_404(cid)
    body = json_body()
    observed_count = req_int(body, "observed_count", minimum=0)
    eartipped_count = req_int(body, "eartipped_count", minimum=0)
    notes = opt_str(body, "notes", "")
    raw_surveyed_on = body.get("surveyed_on")
    if raw_surveyed_on is None:
        raise validation("Missing required field: 'surveyed_on'.")
    surveyed_on = parse_datetime(raw_surveyed_on, "surveyed_on")

    if eartipped_count > observed_count:
        raise ApiError(ERR_SURVEY_INCONSISTENT, 422,
                       "eartipped_count may not exceed observed_count.")
    # The survey date may not lie in the future relative to the logical clock
    # (compared as a calendar date).
    if surveyed_on.date() > now_dt().date():
        raise ApiError(ERR_SURVEY_INCONSISTENT, 422,
                       "surveyed_on may not be in the future.")

    survey = stamp_survey({
        "colony_id": cid,
        "surveyed_on": raw_surveyed_on,
        "observed_count": observed_count,
        "eartipped_count": eartipped_count,
        "notes": notes,
    })
    survey["_surveyed_on"] = surveyed_on
    db.population_surveys[survey["id"]] = survey
    return success_object(public(survey), status=201)


@bp.get("/tnr/colonies/<cid>/population-surveys")
@require_roles("ProgramCoordinator", "Caretaker", "AnimalControlOfficer")
def list_population_surveys(cid, user_id, role):
    get_colony_or_404(cid)
    rows = [s for s in db.population_surveys.values() if s["colony_id"] == cid]
    return paginate([public(s) for s in sorted_created(rows)])


@bp.get("/tnr/colonies/<cid>/population-report")
@require_roles("ProgramCoordinator", "AnimalControlOfficer")
def get_population_report(cid, user_id, role):
    colony = get_colony_or_404(cid)
    return success_object(population_report(colony))
