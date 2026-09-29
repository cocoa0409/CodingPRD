"""PRD 3.1-3.3 — rider registration, the intake packet, submission cycles and
professional verification."""

from flask import Blueprint

import lookups
import owners
import serializers
import shapes
from auth import actor_id, require
from envelope import created, ok
from errors import ApiError
from store import (
    base_record,
    db,
    elapsed_days,
    now,
    plus_days,
    today,
    touch,
)

bp = Blueprint("intake", __name__)

DETERMINATION_WINDOW_DAYS = 21

ACTIVE_PIPELINE_STATUSES = (
    "SUBMITTED",
    "RETURNED_INCOMPLETE",
    "PENDING_VERIFICATION",
    "ASSESSMENT_REQUIRED",
    "ASSESSMENT_SCHEDULED",
    "ASSESSMENT_COMPLETE",
)


def _body_reference(payload, field, resolver):
    """PRD 2.5 stage 7: a reference carried in the body must resolve.  A field
    that is absent altogether is a stage 9 shape failure instead."""
    if field not in payload or payload[field] is None:
        return None
    return resolver(payload[field])


# ---------------------------------------------------------------------------
# POST /applicants
# ---------------------------------------------------------------------------

@bp.post("/applicants")
@require(("IntakeClerk", "AccessibilityOfficeAdmin"))
def register_applicant():
    payload = shapes.body()
    full_name = shapes.req_str(payload, "full_name")
    date_of_birth = shapes.req_iso_date(payload, "date_of_birth")
    residence_zone = shapes.req_enum(payload, "residence_zone", shapes.RESIDENCE_ZONES)
    mobility_aid = shapes.opt_enum(payload, "mobility_aid", shapes.MOBILITY_AIDS, "NONE")
    primary_language = shapes.opt_str(payload, "primary_language", "EN")
    home_agency_name = shapes.opt_str(payload, "home_agency_name", None)

    rec = base_record()
    rec.update(
        {
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "residence_zone": residence_zone,
            "mobility_aid": mobility_aid,
            "primary_language": primary_language,
            "home_agency_name": home_agency_name,
            "current_eligibility_status": "NONE",
            "eligibility_category": None,
            "active_determination_id": None,
        }
    )
    db.applicants[rec["id"]] = rec
    return created(serializers.applicant(rec))


# ---------------------------------------------------------------------------
# POST /applications
# ---------------------------------------------------------------------------

@bp.post("/applications")
@require(("Applicant", "IntakeClerk"), ownership=owners.applicant_body)
def open_application():
    payload = shapes.body()
    applicant = _body_reference(payload, "applicant_id", lookups.applicant)

    if applicant is None:
        shapes.req_str(payload, "applicant_id")
    application_type = shapes.req_enum(payload, "application_type", shapes.APPLICATION_TYPES)
    answers = shapes.questionnaire_object(payload, "functional_answers", required=True)
    claimed = shapes.opt_array(payload, "claimed_conditions", [])

    # PRD 3.1: one rider may have only one packet open at a time.
    for other in lookups.applications_of(applicant["id"]):
        if other["status"] != "DETERMINED":
            raise ApiError("ERR_DUPLICATE_OPEN_APPLICATION")

    rec = base_record()
    rec.update(
        {
            "applicant_id": applicant["id"],
            "application_type": application_type,
            "status": "DRAFT",
            "functional_answers": answers,
            "claimed_conditions": list(claimed),
            "submitted_at": None,
            "completeness_established_at": None,
            "missing_items": [],
            "resubmission_count": 0,
            "verification_excluded_days": 0,
            "applicant_delay_days": 0,
            "determination_due_date": None,
            "presumptive_granted_at": None,
            "attests_permanent": None,
            "_frozen_pending": None,
        }
    )
    db.applications[rec["id"]] = rec
    return created(serializers.application(rec))


# ---------------------------------------------------------------------------
# POST /applications/{id}/submit
# ---------------------------------------------------------------------------

@bp.post("/applications/<application_id>/submit")
@require(("Applicant", "IntakeClerk"), ownership=owners.application_path)
def submit_application(application_id):
    app_rec = lookups.application(application_id)
    payload = shapes.body()
    supplied = shapes.questionnaire_object(payload, "functional_answers", required=False)

    # PRD 3.2 / 2.5 stage 9: the five-key completeness test bites here.
    effective = supplied if supplied is not None else app_rec["functional_answers"]
    if not shapes.questionnaire_complete(effective):
        shapes.bad(
            "functional_answers must carry all five keys with non-null values before submission."
        )

    status = app_rec["status"]
    if status not in ("DRAFT", "RETURNED_INCOMPLETE"):
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    # PRD 3.2: no other packet of the same rider anywhere in the active pipeline.
    for other in lookups.applications_of(app_rec["applicant_id"]):
        if other["id"] == app_rec["id"]:
            continue
        if other["status"] in ACTIVE_PIPELINE_STATUSES:
            raise ApiError("ERR_DUPLICATE_OPEN_APPLICATION")

    if supplied is not None:
        app_rec["functional_answers"] = supplied

    instant = now()
    app_rec["submitted_at"] = instant
    app_rec["completeness_established_at"] = instant
    app_rec["determination_due_date"] = plus_days(instant.date(), DETERMINATION_WINDOW_DAYS)
    app_rec["missing_items"] = []
    app_rec["_frozen_pending"] = None
    if status == "RETURNED_INCOMPLETE":
        app_rec["resubmission_count"] += 1
    app_rec["status"] = "SUBMITTED"
    touch(app_rec)
    return ok(serializers.application(app_rec))


# ---------------------------------------------------------------------------
# POST /applications/{id}/return-incomplete
# ---------------------------------------------------------------------------

@bp.post("/applications/<application_id>/return-incomplete")
@require(("IntakeClerk",))
def return_incomplete(application_id):
    app_rec = lookups.application(application_id)
    payload = shapes.body()
    missing = shapes.req_string_array(payload, "missing_items")

    if app_rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    app_rec["status"] = "RETURNED_INCOMPLETE"
    app_rec["missing_items"] = list(missing)
    # PRD 3.2: returning stops the statutory clock hard.
    app_rec["completeness_established_at"] = None
    app_rec["determination_due_date"] = None
    app_rec["_frozen_pending"] = None
    touch(app_rec)
    return ok(serializers.application(app_rec))


# ---------------------------------------------------------------------------
# POST /applications/{id}/verifications
# ---------------------------------------------------------------------------

@bp.post("/applications/<application_id>/verifications")
@require(("IntakeClerk",))
def request_verification(application_id):
    app_rec = lookups.application(application_id)
    payload = shapes.body()
    provider_name = shapes.req_str(payload, "provider_name")
    provider_type = shapes.req_enum(payload, "provider_type", shapes.PROVIDER_TYPES)
    license_number = shapes.req_str(payload, "provider_license_number")

    if app_rec["status"] not in ("SUBMITTED", "PENDING_VERIFICATION"):
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    existing = lookups.verifications_of(app_rec["id"])
    if any(v["status"] == "REQUESTED" for v in existing):
        raise ApiError("ERR_VERIFICATION_PENDING")

    rec = base_record()
    rec.update(
        {
            "application_id": app_rec["id"],
            "provider_name": provider_name,
            "provider_type": provider_type,
            "provider_license_number": license_number,
            "status": "REQUESTED",
            "requested_at": now(),
            "received_at": None,
            "attests_conditions": None,
            "attests_permanent": None,
            "insufficiency_reason": None,
            "wait_days": 0,
        }
    )
    db.verifications[rec["id"]] = rec

    # PRD 3.3: SUBMITTED -> PENDING_VERIFICATION on the first request; the
    # re-request from PENDING_VERIFICATION is a self-loop that leaves status and
    # completeness_established_at exactly as they were.
    app_rec["status"] = "PENDING_VERIFICATION"
    touch(app_rec)
    return created(serializers.verification(rec))


# ---------------------------------------------------------------------------
# POST /applications/{id}/verifications/{verification_id}/receive
# ---------------------------------------------------------------------------

@bp.post("/applications/<application_id>/verifications/<verification_id>/receive")
@require(("IntakeClerk",))
def receive_verification(application_id, verification_id):
    app_rec = lookups.application(application_id)
    ver = lookups.verification_under(app_rec, verification_id)
    payload = shapes.body()
    outcome = shapes.req_enum(payload, "outcome", shapes.VERIFICATION_OUTCOMES)

    if outcome == "ACCEPTED":
        attests_conditions = shapes.req_string_array(payload, "attests_conditions")
        attests_permanent = shapes.req_bool(payload, "attests_permanent")
        insufficiency_reason = None
    else:
        attests_conditions = None
        attests_permanent = None
        insufficiency_reason = shapes.req_str(payload, "insufficiency_reason")

    if ver["status"] != "REQUESTED":
        raise ApiError("ERR_VERIFICATION_STATE_INVALID")

    instant = now()
    wait_days = elapsed_days(ver["requested_at"], instant)
    ver["received_at"] = instant
    ver["wait_days"] = wait_days

    if outcome == "ACCEPTED":
        ver["status"] = "RECEIVED"
        ver["attests_conditions"] = list(attests_conditions)
        ver["attests_permanent"] = attests_permanent
        app_rec["attests_permanent"] = attests_permanent
        app_rec["status"] = "ASSESSMENT_REQUIRED"
    else:
        ver["status"] = "INSUFFICIENT"
        ver["insufficiency_reason"] = insufficiency_reason
        # PRD 3.3: the packet stays in PENDING_VERIFICATION — a self-loop, not a
        # regression — and completeness_established_at is not disturbed.

    touch(ver)
    app_rec["verification_excluded_days"] += wait_days
    touch(app_rec)
    return ok(serializers.verification(ver))
