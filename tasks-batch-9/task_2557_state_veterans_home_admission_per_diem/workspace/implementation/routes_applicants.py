"""Application intake, eligibility, waitlist queues, clinical assessments and
the admission decision."""
from flask import Blueprint

import calc
import services
from calc import (
    CARE_LEVELS,
    DISCHARGE_CHARACTERS,
    MAX_REDETERMINATIONS,
    MIN_RESIDENCY_YEARS,
    MIN_SERVICE_DAYS,
    NURSING_MIN_SKILLED_HOURS,
    QUALIFYING_DISCHARGES,
    applicant_out,
    assessment_out,
    resident_out,
    waitlist_out,
)
from common import (
    f_bool,
    f_date,
    f_enum,
    f_id,
    f_int,
    f_number,
    f_str,
    fail,
    guard,
    json_body,
    object_response,
    pagination,
    paginate,
    present,
    q_str,
)
from store import new_record, now_iso, order_key, store, touch, touch_once

bp = Blueprint("applicants", __name__)

APPLICANT_STATUSES = ("SUBMITTED", "ELIGIBLE", "INELIGIBLE", "WAITLISTED", "ADMITTED", "DENIED")


def find_applicant(applicant_id):
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        fail("ERR_APPLICANT_NOT_FOUND", "No applicant with id %s." % applicant_id)
    return applicant


def find_assessment(assessment_id):
    assessment = store.assessments.get(assessment_id)
    if assessment is None:
        fail("ERR_ASSESSMENT_NOT_FOUND", "No clinical assessment with id %s." % assessment_id)
    return assessment


def first_failing_criterion(applicant):
    if applicant["discharge_character"] not in QUALIFYING_DISCHARGES:
        return "DISCHARGE_CHARACTER_DISQUALIFYING"
    if not (
        applicant["service_days"] >= MIN_SERVICE_DAYS
        or applicant["nursing_care_for_service_connected"]
    ):
        return "SERVICE_DAYS_INSUFFICIENT"
    if applicant["state_residency_years"] < MIN_RESIDENCY_YEARS:
        return "RESIDENCY_INSUFFICIENT"
    return None


# ------------------------------------------------------------------ reads ----
@bp.get("/applicants/<applicant_id>")
def get_applicant(applicant_id):
    guard(
        "StateProgramAdmin",
        "AdmissionsCoordinator",
        "ClinicalAssessor",
        "BusinessOfficeManager",
    )
    return object_response(applicant_out(find_applicant(applicant_id)))


@bp.get("/applicants/<applicant_id>/waitlist-entries")
def list_applicant_waitlist(applicant_id):
    guard("StateProgramAdmin", "AdmissionsCoordinator", "ClinicalAssessor")
    limit, offset = pagination()
    applicant = find_applicant(applicant_id)
    status = q_str("status")
    rows = services.applicant_entries(applicant["id"])
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    rows = sorted(rows, key=lambda w: (w["listed_at"], w["created_at"], w["_seq"]))
    return paginate(rows, limit, offset, waitlist_out)


@bp.get("/applicants/<applicant_id>/clinical-assessments")
def list_applicant_assessments(applicant_id):
    guard("StateProgramAdmin", "AdmissionsCoordinator", "ClinicalAssessor")
    limit, offset = pagination()
    applicant = find_applicant(applicant_id)
    status = q_str("status")
    rows = [a for a in store.assessments.values() if a["applicant_id"] == applicant["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = sorted(
        rows,
        key=lambda a: (a["assessment_date"], a["created_at"], a["_seq"]),
        reverse=True,
    )
    return paginate(rows, limit, offset, assessment_out)


# ----------------------------------------------------------------- writes ----
@bp.post("/applicants")
def file_applicant():
    guard("AdmissionsCoordinator")
    body = json_body()
    veterans_home_id = f_id(body, "veterans_home_id")
    full_name = f_str(body, "full_name", 1, 200)
    date_of_birth = f_date(body, "date_of_birth")
    service_days = f_int(body, "service_days", minimum=0)
    discharge_character = f_enum(body, "discharge_character", DISCHARGE_CHARACTERS)
    wartime_service = f_bool(body, "wartime_service")
    disability_pct = f_int(body, "service_connected_disability_pct", minimum=0, maximum=100)
    nursing_for_sc = f_bool(body, "nursing_care_for_service_connected")
    residency_years = f_int(body, "state_residency_years", minimum=0)
    requested_care_level = f_enum(body, "requested_care_level", CARE_LEVELS)
    application_received_date = f_date(body, "application_received_date")

    home = store.homes.get(veterans_home_id)
    if home is None:
        fail("ERR_HOME_NOT_FOUND", "No veterans home with id %s." % veterans_home_id)

    applicant = new_record()
    applicant.update(
        {
            "veterans_home_id": home["id"],
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "service_days": service_days,
            "discharge_character": discharge_character,
            "wartime_service": wartime_service,
            "service_connected_disability_pct": disability_pct,
            "nursing_care_for_service_connected": nursing_for_sc,
            "state_residency_years": residency_years,
            "requested_care_level": requested_care_level,
            "application_received_date": application_received_date,
            "status": "SUBMITTED",
            "eligibility_reason_code": None,
            "priority_class": None,
            "priority_score": 0,
            "declined_offer_count": 0,
            "redetermination_count": 0,
            "decided_by_user_id": None,
            "decision_note": None,
        }
    )
    store.applicants[applicant["id"]] = applicant
    touch_once(home)
    return object_response(applicant_out(applicant), 201)


@bp.post("/applicants/<applicant_id>/eligibility-determination")
def eligibility_determination(applicant_id):
    guard("AdmissionsCoordinator")
    body = json_body()
    amended_service_days = f_int(body, "amended_service_days", minimum=0, required=False)
    amended_residency = f_int(body, "amended_state_residency_years", minimum=0, required=False)
    amended_discharge = f_enum(
        body, "amended_discharge_character", DISCHARGE_CHARACTERS, required=False
    )
    review_note = f_str(body, "review_note", required=False)
    applicant = find_applicant(applicant_id)

    previous_status = applicant["status"]
    if previous_status not in ("SUBMITTED", "INELIGIBLE"):
        fail(
            "ERR_APPLICANT_STATE_INVALID",
            "An eligibility determination requires a SUBMITTED or INELIGIBLE applicant.",
        )
    amended_supplied = (
        present(body, "amended_service_days")
        or present(body, "amended_state_residency_years")
        or present(body, "amended_discharge_character")
    )
    if previous_status == "INELIGIBLE":
        if not amended_supplied:
            fail(
                "ERR_APPLICANT_STATE_INVALID",
                "Reopening an INELIGIBLE applicant requires at least one amended evidence field.",
            )
        if applicant["redetermination_count"] >= MAX_REDETERMINATIONS:
            fail("ERR_REDETERMINATION_LIMIT", "The redetermination limit has been reached.")

    if amended_service_days is not None:
        applicant["service_days"] = amended_service_days
    if amended_residency is not None:
        applicant["state_residency_years"] = amended_residency
    if amended_discharge is not None:
        applicant["discharge_character"] = amended_discharge
    applicant["decision_note"] = review_note

    if previous_status == "INELIGIBLE":
        applicant["redetermination_count"] += 1
        applicant["status"] = "SUBMITTED"
        applicant["eligibility_reason_code"] = None
        touch(applicant)

    reason = first_failing_criterion(applicant)
    if reason is None:
        applicant["status"] = "ELIGIBLE"
        applicant["eligibility_reason_code"] = "ELIGIBLE"
        applicant["priority_class"] = calc.compute_priority_class(applicant)
        applicant["priority_score"] = calc.compute_priority_score(applicant)
    else:
        applicant["status"] = "INELIGIBLE"
        applicant["eligibility_reason_code"] = reason
        applicant["priority_class"] = None
        applicant["priority_score"] = 0
    touch(applicant)

    for entry in services.applicant_entries(applicant["id"]):
        services.recompute_queue(entry["care_unit_id"])
    return object_response(applicant_out(applicant))


@bp.post("/waitlist-entries")
def create_waitlist_entry():
    guard("AdmissionsCoordinator")
    body = json_body()
    applicant_id = f_id(body, "applicant_id")
    care_unit_id = f_id(body, "care_unit_id")

    # Pinned foreign-key resolution order: care_unit_id before applicant_id.
    unit = store.care_units.get(care_unit_id)
    if unit is None:
        fail("ERR_CARE_UNIT_NOT_FOUND", "No care unit with id %s." % care_unit_id)
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        fail("ERR_APPLICANT_NOT_FOUND", "No applicant with id %s." % applicant_id)

    if applicant["status"] not in ("ELIGIBLE", "WAITLISTED"):
        fail(
            "ERR_APPLICANT_STATE_INVALID",
            "Waitlist placement requires an ELIGIBLE or WAITLISTED applicant.",
        )
    if unit["certification_status"] == "DECERTIFIED":
        fail("ERR_UNIT_NOT_CERTIFIED", "A decertified unit accepts no waitlist entries.")
    if applicant["requested_care_level"] != unit["care_level"]:
        fail(
            "ERR_CARE_LEVEL_MISMATCH",
            "The applicant's requested_care_level does not match the unit's care_level.",
        )
    for existing in services.unit_entries(unit["id"]):
        if existing["applicant_id"] == applicant["id"] and existing["status"] in (
            "ACTIVE",
            "OFFERED",
        ):
            fail(
                "ERR_DUPLICATE_WAITLIST_ENTRY",
                "The applicant already holds a live entry on this unit.",
            )

    entry = new_record()
    entry.update(
        {
            "applicant_id": applicant["id"],
            "care_unit_id": unit["id"],
            "status": "ACTIVE",
            "listed_at": now_iso(),
            "offer_expires_at": None,
            "priority_class_snapshot": applicant["priority_class"],
            "rank_score_snapshot": applicant["priority_score"],
            "queue_position": 0,
        }
    )
    store.waitlist_entries[entry["id"]] = entry
    applicant["status"] = "WAITLISTED"
    touch_once(applicant)
    touch_once(unit)
    services.recompute_queue(unit["id"])
    return object_response(waitlist_out(entry), 201)


@bp.post("/applicants/<applicant_id>/clinical-assessments")
def create_assessment(applicant_id):
    user_id, _role = guard("ClinicalAssessor")
    body = json_body()
    assessed_care_level = f_enum(body, "assessed_care_level", CARE_LEVELS)
    adl = f_int(body, "adl_dependency_count", minimum=0, maximum=6)
    cognitive = f_bool(body, "cognitive_impairment")
    behavioral = f_bool(body, "behavioral_risk_flag")
    hours = f_number(body, "skilled_nursing_hours_per_day", minimum=0, maximum=24, decimals=2)
    assessment_date = f_date(body, "assessment_date")
    applicant = find_applicant(applicant_id)

    assessment = new_record()
    assessment.update(
        {
            "applicant_id": applicant["id"],
            "assessed_care_level": assessed_care_level,
            "adl_dependency_count": adl,
            "cognitive_impairment": cognitive,
            "behavioral_risk_flag": behavioral,
            "skilled_nursing_hours_per_day": hours,
            "assessment_date": assessment_date,
            "assessor_user_id": user_id,
            "status": "DRAFT",
            "acuity_points": 0,
            "rejection_reason": None,
        }
    )
    assessment["acuity_points"] = calc.compute_acuity_points(assessment)
    store.assessments[assessment["id"]] = assessment
    touch_once(applicant)
    return object_response(assessment_out(assessment), 201)


@bp.post("/clinical-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    guard("ClinicalAssessor")
    json_body()
    assessment = find_assessment(assessment_id)
    if assessment["status"] != "DRAFT":
        fail("ERR_ASSESSMENT_STATE_INVALID", "Only a DRAFT assessment may be submitted.")
    applicant = store.applicants.get(assessment["applicant_id"])
    if applicant is None or applicant["status"] not in ("ELIGIBLE", "WAITLISTED"):
        fail(
            "ERR_APPLICANT_STATE_INVALID",
            "Submission requires an ELIGIBLE or WAITLISTED applicant.",
        )
    if (
        assessment["assessed_care_level"] == "NURSING"
        and assessment["skilled_nursing_hours_per_day"] < NURSING_MIN_SKILLED_HOURS
    ):
        fail(
            "ERR_CARE_LEVEL_MISMATCH",
            "A NURSING assessment requires at least 2.00 skilled nursing hours per day.",
        )

    assessment["status"] = "SUBMITTED"
    assessment["acuity_points"] = calc.compute_acuity_points(assessment)
    touch_once(assessment)
    services.recompute_applicant_score(applicant)
    return object_response(assessment_out(assessment))


@bp.post("/applicants/<applicant_id>/admission-decision")
def admission_decision(applicant_id):
    user_id, _role = guard("AdmissionsCoordinator")
    body = json_body()
    decision = f_enum(body, "decision", ("APPROVED", "DENIED"))
    care_unit_id = f_id(body, "care_unit_id")
    clinical_assessment_id = f_id(body, "clinical_assessment_id")
    expected_version = f_int(body, "expected_care_unit_version", minimum=0)
    admission_date = f_date(body, "admission_date")
    decision_note = f_str(body, "decision_note", required=False)

    applicant = find_applicant(applicant_id)
    unit = store.care_units.get(care_unit_id)
    if unit is None:
        fail("ERR_CARE_UNIT_NOT_FOUND", "No care unit with id %s." % care_unit_id)
    assessment = store.assessments.get(clinical_assessment_id)
    if assessment is None:
        fail("ERR_ASSESSMENT_NOT_FOUND", "No clinical assessment with id %s." % clinical_assessment_id)

    if expected_version != unit["version"]:
        fail("ERR_CARE_UNIT_VERSION_STALE", "expected_care_unit_version does not match the unit.")
    if applicant["status"] != "WAITLISTED":
        fail("ERR_APPLICANT_STATE_INVALID", "An admission decision requires a WAITLISTED applicant.")
    if assessment["applicant_id"] != applicant["id"] or assessment["status"] != "SUBMITTED":
        fail(
            "ERR_ASSESSMENT_STATE_INVALID",
            "The cited assessment must belong to this applicant and be SUBMITTED.",
        )
    if user_id == assessment["assessor_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The deciding coordinator may not be the assessing clinician.",
        )
    if unit["certification_status"] != "CERTIFIED":
        fail("ERR_UNIT_NOT_CERTIFIED", "The target unit must be CERTIFIED.")
    if calc.operational_posture(unit) != "OPEN":
        fail("ERR_UNIT_POSTURE_BLOCKED", "The target unit's operational posture is not OPEN.")
    if assessment["assessed_care_level"] != unit["care_level"]:
        fail(
            "ERR_CARE_LEVEL_MISMATCH",
            "The assessment's assessed_care_level does not match the unit's care_level.",
        )
    unit_entry = None
    for entry in services.unit_entries(unit["id"]):
        if entry["applicant_id"] == applicant["id"] and entry["status"] in ("ACTIVE", "OFFERED"):
            unit_entry = entry
            break
    if unit_entry is None:
        fail(
            "ERR_NO_WAITLIST_ENTRY_FOR_UNIT",
            "The applicant holds no live waitlist entry on the target unit.",
        )
    if calc.available_bed_count(unit) < 1:
        fail("ERR_NO_AVAILABLE_BED", "The target unit has no free bed.")

    applicant["decided_by_user_id"] = user_id
    applicant["decision_note"] = decision_note

    if decision == "DENIED":
        applicant["status"] = "DENIED"
        assessment["status"] = "REJECTED"
        assessment["rejection_reason"] = "ADMISSION_DENIED"
        touch_once(assessment)
        affected = set()
        for entry in sorted(services.applicant_entries(applicant["id"]), key=order_key):
            if entry["status"] in ("ACTIVE", "OFFERED"):
                entry["status"] = "CANCELLED"
                entry["offer_expires_at"] = None
                entry["queue_position"] = 0
                touch_once(entry)
                affected.add(entry["care_unit_id"])
        for unit_id in affected:
            other = store.care_units.get(unit_id)
            if other:
                touch_once(other)
            services.recompute_queue(unit_id)
        touch_once(applicant)
        return object_response(None, 201)

    applicant["status"] = "ADMITTED"
    assessment["status"] = "ACCEPTED"
    touch_once(assessment)

    resident = new_record()
    resident.update(
        {
            "applicant_id": applicant["id"],
            "care_unit_id": unit["id"],
            "admission_date": admission_date,
            "occupancy_status": "ADMITTED",
            "billing_status": "PROVISIONAL_COST_SHARE",
            "current_care_level": unit["care_level"],
            "bed_hold_days_used": 0,
            "bed_hold_started_on": None,
            "last_hospitalization_end_date": None,
            "hospitalization_count": 0,
            "readmission_count": 0,
            "last_census_date": None,
            "discharge_date": None,
            "discharge_reason": None,
        }
    )
    store.residents[resident["id"]] = resident

    # Hop 1: the admitting entry is consumed; every other live entry is cancelled.
    unit_entry["status"] = "ADMITTED"
    unit_entry["offer_expires_at"] = None
    unit_entry["queue_position"] = 0
    touch_once(unit_entry)
    other_units = set()
    for entry in sorted(services.applicant_entries(applicant["id"]), key=order_key):
        if entry["id"] == unit_entry["id"]:
            continue
        if entry["status"] in ("ACTIVE", "OFFERED"):
            entry["status"] = "CANCELLED"
            entry["offer_expires_at"] = None
            entry["queue_position"] = 0
            touch_once(entry)
            other_units.add(entry["care_unit_id"])
    for unit_id in other_units:
        other = store.care_units.get(unit_id)
        if other:
            touch_once(other)
        services.recompute_queue(unit_id)

    # Hops 2-4: bed occupancy, posture, then offer revocation on the admitting unit.
    touch_once(unit)
    home = calc.home_of_unit(unit)
    if home:
        touch_once(home)
    services.revoke_offers_when_restricted(unit)
    services.recompute_queue(unit["id"])
    touch_once(applicant)
    return object_response(resident_out(resident), 201)
