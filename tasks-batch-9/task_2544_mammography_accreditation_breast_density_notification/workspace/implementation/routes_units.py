"""MammographyUnit, PhysicistSurvey, ClinicalImageReviewSubmission and
EquipmentFailureEvent endpoints."""

from flask import Blueprint, g

import services as svc
from common import (
    ALL_ROLES, DB, ROLE_COORDINATOR, ROLE_PHYSICIST, ROLE_REVIEWER,
    ROLE_TECHNOLOGIST, body_dict, endpoint, fail, filter_rows, new_entity,
    ok_entity, ok_list, plus_days, require_actor_at_facility, sort_rows, touch,
    v_dt, v_enum, v_expected_version, v_num, v_str, v_str_list,
)

bp = Blueprint("units", __name__)

SURVEY_TYPES = ("ANNUAL", "POST_REPAIR", "MOBILE")
FAILURE_CODES = ("DETECTOR", "AEC", "COLLIMATION", "COMPRESSION", "DISPLAY", "SOFTWARE")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
POST_REPAIR_CODES = ("DETECTOR", "AEC", "COLLIMATION")
FINAL_REPORT_STATUSES = ("INTERPRETED_FINAL", "AMENDED")


def _unit_or_404(unit_id):
    unit = DB.get("unit", unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND", "unit %s does not exist" % unit_id)
    return unit


def _survey_or_404(survey_id):
    survey = DB.get("survey", survey_id)
    if survey is None:
        fail("ERR_SURVEY_NOT_FOUND", "survey %s does not exist" % survey_id)
    return survey


def _submission_or_404(submission_id):
    submission = DB.get("submission", submission_id)
    if submission is None:
        fail("ERR_SUBMISSION_NOT_FOUND",
             "clinical image review %s does not exist" % submission_id)
    return submission


def _failure_or_404(failure_id):
    failure = DB.get("failure", failure_id)
    if failure is None:
        fail("ERR_FAILURE_EVENT_NOT_FOUND",
             "equipment failure %s does not exist" % failure_id)
    return failure


@bp.route("/units/<unit_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def unit_read(unit_id):
    return ok_entity(_unit_or_404(unit_id))


# ---------------------------------------------------------------------------
# PhysicistSurvey
# ---------------------------------------------------------------------------
@bp.route("/units/<unit_id>/physicist-surveys", methods=["POST"])
@endpoint([ROLE_PHYSICIST])
def survey_create(unit_id):
    require_actor_at_facility(None, "MEDICAL_PHYSICIST")
    unit = _unit_or_404(unit_id)
    require_actor_at_facility(unit["facility_id"], "MEDICAL_PHYSICIST")

    body = body_dict()
    survey_type = v_enum(body, "survey_type", SURVEY_TYPES, True)
    start = v_dt(body, "effective_start", True)
    end = v_dt(body, "effective_end", True)
    phantom = v_num(body, "phantom_score", False, 0.0, 12.0, default=None)
    mgd = v_num(body, "mean_glandular_dose_mgy", False, 0.0, 10.0, default=None)
    critical = v_str_list(body, "critical_deficiency_codes", False, default=[])
    note = v_str(body, "outcome_note", False, default=None)

    svc.check_survey_window(unit_id, survey_type, start, end)

    survey = new_entity("survey", {
        "unit_id": unit_id,
        "physicist_id": g.user_id,
        "survey_type": survey_type,
        "status": "DRAFT",
        "phantom_score": phantom,
        "mean_glandular_dose_mgy": mgd,
        "critical_deficiency_codes": critical,
        "effective_start": start,
        "effective_end": end,
        "decided_at": None,
        "remediation_attempts": 0,
        "outcome_note": note,
    })
    return ok_entity(survey, 201)


@bp.route("/units/<unit_id>/physicist-surveys", methods=["GET"])
@endpoint(ALL_ROLES)
def unit_surveys_list(unit_id):
    _unit_or_404(unit_id)
    rows = svc.surveys_of_unit(unit_id)
    rows = filter_rows(rows, {"status": "status", "survey_type": "survey_type"})
    return ok_list(sort_rows(rows))


@bp.route("/physicist-surveys/<survey_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def survey_read(survey_id):
    return ok_entity(_survey_or_404(survey_id))


@bp.route("/physicist-surveys", methods=["GET"])
@endpoint(ALL_ROLES)
def surveys_list():
    rows = filter_rows(DB.all("survey"), {
        "unit_id": "unit_id",
        "physicist_id": "physicist_id",
        "status": "status",
        "survey_type": "survey_type",
    })
    return ok_list(sort_rows(rows))


def _read_measurements(body):
    phantom = v_num(body, "phantom_score", True, 0.0, 12.0)
    mgd = v_num(body, "mean_glandular_dose_mgy", True, 0.0, 10.0)
    critical = v_str_list(body, "critical_deficiency_codes", False, default=[])
    note = v_str(body, "outcome_note", False, default=None)
    return phantom, mgd, critical, note


@bp.route("/physicist-surveys/<survey_id>/submit", methods=["POST"])
@endpoint([ROLE_PHYSICIST])
def survey_submit(survey_id):
    require_actor_at_facility(None, "MEDICAL_PHYSICIST")
    survey = _survey_or_404(survey_id)
    unit = _unit_or_404(survey["unit_id"])
    require_actor_at_facility(unit["facility_id"], "MEDICAL_PHYSICIST")
    if survey["physicist_id"] != g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "only the authoring physicist may record this survey decision")

    body = body_dict()
    phantom, mgd, critical, note = _read_measurements(body)

    if survey["status"] != "DRAFT":
        fail("ERR_SURVEY_NOT_DECIDABLE",
             "survey in status %s cannot be decided" % survey["status"])

    survey["phantom_score"] = phantom
    survey["mean_glandular_dose_mgy"] = mgd
    survey["critical_deficiency_codes"] = critical
    if note is not None:
        survey["outcome_note"] = note
    survey["decided_at"] = DB.clock

    if svc.survey_passes(phantom, mgd, critical):
        survey["status"] = "PASSED"
        touch(survey)
        svc.mark_survey_currency_on_pass(unit, survey)
    else:
        survey["status"] = "FAILED_ACTION_REQUIRED"
        touch(survey)
        svc.survey_failure_cascade(unit, critical)
    return ok_entity(survey)


@bp.route("/physicist-surveys/<survey_id>/remediate", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def survey_remediate(survey_id):
    survey = _survey_or_404(survey_id)
    if survey["physicist_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "a remediation may not be recorded by the authoring physicist")
    unit = _unit_or_404(survey["unit_id"])

    body = body_dict()
    phantom, mgd, critical, note = _read_measurements(body)

    if survey["status"] != "FAILED_ACTION_REQUIRED":
        fail("ERR_SURVEY_NOT_DECIDABLE",
             "survey in status %s cannot be remediated" % survey["status"])

    attempts_before = survey["remediation_attempts"]
    survey["remediation_attempts"] = min(attempts_before + 1,
                                        svc.MAX_REMEDIATION_ATTEMPTS)
    survey["phantom_score"] = phantom
    survey["mean_glandular_dose_mgy"] = mgd
    survey["critical_deficiency_codes"] = critical
    if note is not None:
        survey["outcome_note"] = note
    survey["decided_at"] = DB.clock

    if svc.survey_passes(phantom, mgd, critical):
        survey["status"] = "PASSED"
        touch(survey)
        svc.mark_survey_currency_on_pass(unit, survey)
    elif attempts_before == 0:
        # genuine self-loop: measurements overwritten, no unit transition fires
        survey["status"] = "FAILED_ACTION_REQUIRED"
        touch(survey)
    else:
        survey["status"] = "FAILED_FINAL"
        survey["remediation_attempts"] = svc.MAX_REMEDIATION_ATTEMPTS
        touch(survey)
        if unit["operational_state"] != "OUT_OF_SERVICE":
            unit["operational_state"] = "OUT_OF_SERVICE"
            touch(unit)
        svc.recompute_posture(svc.facility_of_unit(unit))
    return ok_entity(survey)


# ---------------------------------------------------------------------------
# ClinicalImageReviewSubmission
# ---------------------------------------------------------------------------
def _packet_checks_stage_a(body):
    """Priority 20 / 22 / 25 for a packet payload."""
    exam_ids = v_str_list(body, "exam_ids", True)
    expected = v_expected_version(body, "expected_unit_version")
    note = v_str(body, "reviewer_note", False, default=None)
    if len(exam_ids) < 2 or len(set(exam_ids)) != len(exam_ids):
        fail("ERR_PACKET_TOO_SMALL",
             "a clinical image packet needs at least 2 distinct exam ids")
    exams = []
    for exam_id in exam_ids:
        exam = DB.get("exam", exam_id)
        if exam is None:
            fail("ERR_EXAM_NOT_FOUND", "exam %s does not exist" % exam_id)
        exams.append(exam)
    return exam_ids, expected, note, exams


def _packet_checks_stage_b(unit, exams):
    """Priorities 56 and 57."""
    for exam in exams:
        if exam["unit_id"] != unit["id"]:
            fail("ERR_EXAM_UNIT_MISMATCH",
                 "exam %s was not acquired on this unit" % exam["id"])
    for exam in exams:
        if exam["report_status"] not in FINAL_REPORT_STATUSES:
            fail("ERR_PACKET_EXAM_NOT_FINAL",
                 "exam %s is not interpreted" % exam["id"])


def _check_open_level_1(facility):
    for inspection in svc.inspections_of_facility(facility["id"]):
        if inspection["inspector_findings_level"] == "LEVEL_1" and \
                inspection["status"] == "CORRECTIVE_ACTION_REQUIRED":
            fail("ERR_OPEN_LEVEL_1_FINDING",
                 "an open LEVEL_1 corrective action blocks packet filing")


def _check_reaccreditation_window(unit):
    if unit.get("_ever_accredited") and unit["accreditation_expires_on"] is not None \
            and unit["accreditation_expires_on"] < DB.clock:
        fail("ERR_REACCREDITATION_WINDOW_CLOSED",
             "the unit's reaccreditation window has closed")


@bp.route("/units/<unit_id>/clinical-image-reviews", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def submission_create(unit_id):
    unit = _unit_or_404(unit_id)
    facility = svc.facility_of_unit(unit)
    body = body_dict()
    exam_ids, expected, note, exams = _packet_checks_stage_a(body)

    if expected != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION",
             "expected_unit_version %s does not match %s" % (expected, unit["version"]))

    if unit["reaccreditation_attempts_remaining"] < 1:
        fail("ERR_REACCREDITATION_ATTEMPTS_EXHAUSTED",
             "the unit has no reaccreditation attempts left")
    if unit["accreditation_status"] == "SUSPENDED":
        fail("ERR_UNIT_ACCREDITATION_SUSPENDED",
             "a suspended unit may not file a clinical image packet")
    _check_open_level_1(facility)
    _packet_checks_stage_b(unit, exams)
    _check_reaccreditation_window(unit)
    for peer in svc.submissions_of_unit(unit_id):
        if peer["status"] in ("SUBMITTED", "REVISION_REQUIRED"):
            fail("ERR_SUBMISSION_ALREADY_OPEN",
                 "a live clinical image review already exists on this unit")
    svc.require_prepaid_credit(facility)

    submission = new_entity("submission", {
        "unit_id": unit_id,
        "exam_ids": list(exam_ids),
        "attempt_number": 1,
        "status": "SUBMITTED",
        "fee_held_cents": 0,
        "review_decision": None,
        "deficiency_categories": [],
        "submitted_at": DB.clock,
        "reviewed_at": None,
        "reviewer_note": note,
    })
    svc.ledger_escrow(facility, submission)
    unit["reaccreditation_attempts_remaining"] -= 1
    touch(unit)
    svc.recompute_posture(facility)
    return ok_entity(submission, 201)


@bp.route("/units/<unit_id>/clinical-image-reviews", methods=["GET"])
@endpoint(ALL_ROLES)
def unit_submissions_list(unit_id):
    _unit_or_404(unit_id)
    rows = filter_rows(svc.submissions_of_unit(unit_id), {"status": "status"})
    return ok_list(sort_rows(rows))


@bp.route("/clinical-image-reviews/<submission_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def submission_read(submission_id):
    return ok_entity(_submission_or_404(submission_id))


@bp.route("/clinical-image-reviews/<submission_id>/review", methods=["POST"])
@endpoint([ROLE_REVIEWER])
def submission_review(submission_id):
    submission = _submission_or_404(submission_id)
    unit = _unit_or_404(submission["unit_id"])
    facility = svc.facility_of_unit(unit)

    body = body_dict()
    decision = v_enum(body, "decision", ("PASS", "REVISION_REQUIRED"), True)
    categories = v_str_list(body, "deficiency_categories", False, default=None)
    note = v_str(body, "reviewer_note", False, default=None)

    if submission["status"] != "SUBMITTED":
        fail("ERR_SUBMISSION_NOT_REVIEWABLE",
             "submission in status %s cannot be reviewed" % submission["status"])

    submission["review_decision"] = decision
    submission["reviewed_at"] = DB.clock
    if note is not None:
        submission["reviewer_note"] = note
    svc.ledger_consume(facility, submission)

    if decision == "PASS":
        submission["status"] = "PASSED"
        touch(submission)
        blocked = (unit["accreditation_status"] == "PROBATION"
                   and unit["survey_compliance"] != "CURRENT")
        if not blocked and unit["accreditation_status"] != "SUSPENDED":
            unit["accreditation_status"] = "ACCREDITED"
            unit["accreditation_expires_on"] = plus_days(DB.clock,
                                                        svc.ACCREDITATION_TERM_DAYS)
            unit["reaccreditation_attempts_remaining"] = svc.MAX_ATTEMPTS
            unit["_ever_accredited"] = True
            touch(unit)
    else:
        if categories is not None:
            submission["deficiency_categories"] = categories
        if unit["reaccreditation_attempts_remaining"] >= 1:
            submission["status"] = "REVISION_REQUIRED"
            touch(submission)
            if unit["accreditation_status"] in ("ACCREDITED", "REACCREDITATION_DUE"):
                unit["accreditation_status"] = "PROBATION"
                touch(unit)
        else:
            submission["status"] = "DENIED_FINAL"
            touch(submission)
            unit["accreditation_status"] = "SUSPENDED"
            unit["operational_state"] = "OUT_OF_SERVICE"
            touch(unit)
    svc.recompute_posture(facility)
    return ok_entity(submission)


@bp.route("/clinical-image-reviews/<submission_id>/resubmit", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def submission_resubmit(submission_id):
    submission = _submission_or_404(submission_id)
    unit = _unit_or_404(submission["unit_id"])
    facility = svc.facility_of_unit(unit)

    body = body_dict()
    exam_ids, expected, note, exams = _packet_checks_stage_a(body)

    if expected != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION",
             "expected_unit_version %s does not match %s" % (expected, unit["version"]))

    if submission["status"] != "REVISION_REQUIRED":
        fail("ERR_SUBMISSION_NOT_REVISABLE",
             "submission in status %s cannot be revised" % submission["status"])
    if unit["reaccreditation_attempts_remaining"] < 1:
        fail("ERR_REACCREDITATION_ATTEMPTS_EXHAUSTED",
             "the unit has no reaccreditation attempts left")
    _check_open_level_1(facility)
    _packet_checks_stage_b(unit, exams)
    _check_reaccreditation_window(unit)
    svc.require_prepaid_credit(facility)

    submission["exam_ids"] = list(exam_ids)
    submission["attempt_number"] = min(submission["attempt_number"] + 1,
                                      svc.MAX_ATTEMPTS)
    submission["status"] = "SUBMITTED"
    submission["submitted_at"] = DB.clock
    submission["reviewed_at"] = None
    submission["review_decision"] = None
    if note is not None:
        submission["reviewer_note"] = note
    svc.ledger_escrow(facility, submission)
    touch(submission)
    unit["reaccreditation_attempts_remaining"] -= 1
    touch(unit)
    svc.recompute_posture(facility)
    return ok_entity(submission)


@bp.route("/clinical-image-reviews/<submission_id>/withdraw", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def submission_withdraw(submission_id):
    submission = _submission_or_404(submission_id)
    unit = _unit_or_404(submission["unit_id"])
    facility = svc.facility_of_unit(unit)

    body = body_dict()
    expected = v_expected_version(body, "expected_unit_version")
    v_str(body, "withdrawal_reason", False, default=None)

    if expected != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION",
             "expected_unit_version %s does not match %s" % (expected, unit["version"]))

    if submission["status"] != "SUBMITTED":
        fail("ERR_SUBMISSION_NOT_WITHDRAWABLE",
             "submission in status %s cannot be withdrawn" % submission["status"])

    submission["status"] = "WITHDRAWN"
    svc.ledger_release(facility, submission)
    touch(submission)
    unit["reaccreditation_attempts_remaining"] = min(
        unit["reaccreditation_attempts_remaining"] + 1, svc.MAX_ATTEMPTS)
    touch(unit)
    svc.recompute_posture(facility)
    return ok_entity(submission)


# ---------------------------------------------------------------------------
# EquipmentFailureEvent
# ---------------------------------------------------------------------------
@bp.route("/units/<unit_id>/equipment-failures", methods=["POST"])
@endpoint([ROLE_COORDINATOR, ROLE_PHYSICIST, ROLE_TECHNOLOGIST])
def failure_create(unit_id):
    unit = _unit_or_404(unit_id)
    body = body_dict()
    failure_code = v_enum(body, "failure_code", FAILURE_CODES, True)
    severity = v_enum(body, "severity", SEVERITIES, True)
    detected_at = v_dt(body, "detected_at", True)
    if detected_at > DB.clock:
        fail("ERR_FUTURE_TIMESTAMP", "detected_at may not be in the future")

    requires_survey = severity == "CRITICAL" or failure_code in POST_REPAIR_CODES
    failure = new_entity("failure", {
        "unit_id": unit_id,
        "failure_code": failure_code,
        "severity": severity,
        "detected_at": detected_at,
        "status": "OPEN",
        "requires_post_repair_survey": requires_survey,
        "resolved_at": None,
        "repair_note": None,
    })
    if requires_survey:
        if unit["operational_state"] != "OUT_OF_SERVICE":
            unit["operational_state"] = "OUT_OF_SERVICE"
            touch(unit)
        svc.recompute_posture(svc.facility_of_unit(unit))
    return ok_entity(failure, 201)


@bp.route("/units/<unit_id>/equipment-failures", methods=["GET"])
@endpoint(ALL_ROLES)
def unit_failures_list(unit_id):
    _unit_or_404(unit_id)
    rows = filter_rows(svc.failures_of_unit(unit_id),
                       {"status": "status", "severity": "severity"})
    return ok_list(sort_rows(rows))


@bp.route("/equipment-failures/<failure_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def failure_read(failure_id):
    return ok_entity(_failure_or_404(failure_id))


@bp.route("/equipment-failures/<failure_id>/restore", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def failure_restore(failure_id):
    failure = _failure_or_404(failure_id)
    unit = _unit_or_404(failure["unit_id"])
    body = body_dict()
    repair_note = v_str(body, "repair_note", True, 1)

    if failure["status"] != "OPEN":
        fail("ERR_FAILURE_ALREADY_RESOLVED", "the failure event is already resolved")
    if unit["accreditation_status"] == "SUSPENDED":
        fail("ERR_UNIT_ACCREDITATION_SUSPENDED",
             "a suspended unit may not be returned to service")
    if failure["requires_post_repair_survey"]:
        certifying = [
            s for s in svc.surveys_of_unit(unit["id"])
            if s["survey_type"] == "POST_REPAIR" and s["status"] == "PASSED"
            and s["effective_start"] >= failure["detected_at"]
        ]
        if not certifying:
            fail("ERR_POST_REPAIR_SURVEY_MISSING",
                 "a PASSED POST_REPAIR survey starting at or after detection is required")

    failure["status"] = "REPAIR_VERIFIED"
    failure["resolved_at"] = DB.clock
    failure["repair_note"] = repair_note
    touch(failure)

    blocking = [
        f for f in svc.failures_of_unit(unit["id"])
        if f["id"] != failure["id"] and f["status"] == "OPEN"
        and f["requires_post_repair_survey"]
    ]
    if not blocking and unit["operational_state"] != "IN_SERVICE":
        unit["operational_state"] = "IN_SERVICE"
        touch(unit)
    svc.recompute_posture(svc.facility_of_unit(unit))
    return ok_entity(failure)
