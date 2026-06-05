"""Participants, screenings, and enrollment creation/retrieval (PRD §3.3, §3.4).

Screening runs the matching engine and freezes match_result /
failed_criteria_count / match_score. Enrollment creation re-runs eligibility
live (drift check) against the current participant snapshot.
"""
from flask import Blueprint, request

import calc
import db
import domain
from errors import err
from middleware import require
from response import object_response, array_response
from serialize import serialize
from validate import (
    get_json, require_fields, check_int, check_number, check_string,
    check_bool, pagination,
)

bp = Blueprint("matching", __name__)


# --- Participant -----------------------------------------------------------

@bp.route("/participants", methods=["POST"])
@require("CoordinatorStaff")
def create_participant(caller_id=None, caller_role=None):
    body = get_json()
    require_fields(body, "full_name", "age_years", "weight_kg", "hba1c")
    full_name = check_string(body, "full_name")
    age = check_int(body, "age_years", minimum=0)
    weight = check_number(body, "weight_kg")
    hba1c = check_number(body, "hba1c")

    prior = 0
    if body.get("prior_trials_count") is not None:
        prior = check_int(body, "prior_trials_count", minimum=0)
    biomarker = False
    if body.get("biomarker_positive") is not None:
        biomarker = check_bool(body, "biomarker_positive")

    rec = domain.make_base()
    rec.update({
        "full_name": full_name,
        "age_years": age,
        "weight_kg": weight,
        "hba1c": hba1c,
        "prior_trials_count": prior,
        "biomarker_positive": biomarker,
    })
    db.participants[rec["id"]] = rec
    return object_response(serialize("Participant", rec), 201)


@bp.route("/participants/<participant_id>", methods=["PATCH"])
@require("CoordinatorStaff")
def update_participant(participant_id, caller_id=None, caller_role=None):
    p = db.participants.get(participant_id)
    if p is None:
        err("ERR_NOT_FOUND", "Participant not found")
    body = get_json()

    if "age_years" in body and body["age_years"] is not None:
        p["age_years"] = check_int(body, "age_years", minimum=0)
    if "weight_kg" in body and body["weight_kg"] is not None:
        p["weight_kg"] = check_number(body, "weight_kg")
    if "hba1c" in body and body["hba1c"] is not None:
        p["hba1c"] = check_number(body, "hba1c")
    if "prior_trials_count" in body and body["prior_trials_count"] is not None:
        p["prior_trials_count"] = check_int(body, "prior_trials_count", minimum=0)
    if "biomarker_positive" in body and body["biomarker_positive"] is not None:
        p["biomarker_positive"] = check_bool(body, "biomarker_positive")

    domain.touch(p)
    return object_response(serialize("Participant", p), 200)


# --- Screening -------------------------------------------------------------

@bp.route("/trials/<trial_id>/screen-participant", methods=["POST"])
@require("CoordinatorStaff")
def screen_participant(trial_id, caller_id=None, caller_role=None):
    t = db.trials.get(trial_id)
    if t is None:
        err("ERR_NOT_FOUND", "Trial not found")
    body = get_json()
    require_fields(body, "participant_id")
    participant_id = body["participant_id"]
    participant = db.participants.get(participant_id)
    if participant is None:
        err("ERR_REFERENCE_NOT_FOUND", "participant_id does not resolve")

    criteria = domain.sorted_by_created(domain.trial_criteria(trial_id))
    result, failed = calc.eligibility_match(criteria, participant)
    score = calc.match_score(criteria, participant)

    rec = domain.make_base()
    rec.update({
        "trial_id": trial_id,
        "participant_id": participant_id,
        "match_result": result,
        "failed_criteria_count": failed,
        "match_score": score,
    })
    db.screenings[rec["id"]] = rec
    return object_response(serialize("Screening", rec), 201)


@bp.route("/screenings/<screening_id>", methods=["GET"])
@require("CoordinatorStaff", "Sponsor")
def get_screening(screening_id, caller_id=None, caller_role=None):
    s = db.screenings.get(screening_id)
    if s is None:
        err("ERR_NOT_FOUND", "Screening not found")
    return object_response(serialize("Screening", s), 200)


@bp.route("/screenings", methods=["GET"])
@require("CoordinatorStaff", "Sponsor")
def list_screenings(caller_id=None, caller_role=None):
    items = list(db.screenings.values())
    trial_id = request.args.get("trial_id")
    participant_id = request.args.get("participant_id")
    match_result = request.args.get("match_result")
    if trial_id is not None:
        items = [s for s in items if s["trial_id"] == trial_id]
    if participant_id is not None:
        items = [s for s in items if s["participant_id"] == participant_id]
    if match_result is not None:
        items = [s for s in items if s["match_result"] == match_result]
    items = domain.sorted_by_created(items)

    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    data = [serialize("Screening", s) for s in page]
    return array_response(data, limit, offset, total, status=200)


# --- Enrollment (create / get / list) --------------------------------------

@bp.route("/enrollments", methods=["POST"])
@require("CoordinatorStaff")
def create_enrollment(caller_id=None, caller_role=None):
    body = get_json()
    require_fields(body, "screening_id")
    screening_id = body["screening_id"]
    screening = db.screenings.get(screening_id)
    if screening is None:
        err("ERR_REFERENCE_NOT_FOUND", "screening_id does not resolve")

    # Screening must be ELIGIBLE (priority 14).
    if screening["match_result"] != "ELIGIBLE":
        err("ERR_SCREENING_NOT_ELIGIBLE", "Referenced screening is not ELIGIBLE")

    # Live re-evaluation: eligibility drift (priority 15).
    trial_id = screening["trial_id"]
    participant = db.participants.get(screening["participant_id"])
    criteria = domain.sorted_by_created(domain.trial_criteria(trial_id))
    live_result, _ = calc.eligibility_match(criteria, participant)
    if live_result != "ELIGIBLE":
        err("ERR_ELIGIBILITY_DRIFTED", "Live eligibility re-evaluation yields INELIGIBLE")

    rec = domain.make_base()
    rec.update({
        "trial_id": trial_id,
        "participant_id": screening["participant_id"],
        "screening_id": screening_id,
        "enrollment_status": "SCREENED",
        "safety_status": "CLEAR",
        "arm_id": None,
        "signed_consent_document_id": None,
        "signed_consent_version": None,
        "completed_visits_count": 0,
    })
    db.enrollments[rec["id"]] = rec
    return object_response(serialize("Enrollment", rec), 201)


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
@require("CoordinatorStaff", "Sponsor", "SafetyOfficer")
def get_enrollment(enrollment_id, caller_id=None, caller_role=None):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        err("ERR_NOT_FOUND", "Enrollment not found")
    return object_response(serialize("Enrollment", e), 200)


@bp.route("/enrollments", methods=["GET"])
@require("CoordinatorStaff", "Sponsor", "SafetyOfficer")
def list_enrollments(caller_id=None, caller_role=None):
    items = list(db.enrollments.values())
    filters = {
        "trial_id": "trial_id",
        "participant_id": "participant_id",
        "screening_id": "screening_id",
        "arm_id": "arm_id",
        "signed_consent_document_id": "signed_consent_document_id",
        "enrollment_status": "enrollment_status",
        "safety_status": "safety_status",
    }
    for param, field in filters.items():
        val = request.args.get(param)
        if val is not None:
            items = [e for e in items if e[field] == val]
    items = domain.sorted_by_created(items)

    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    data = [serialize("Enrollment", e) for e in page]
    return array_response(data, limit, offset, total, status=200)
