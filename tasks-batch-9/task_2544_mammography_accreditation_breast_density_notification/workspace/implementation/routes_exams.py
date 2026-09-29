"""Exam, NotificationLetter, SupplementalScreeningOrder and RepeatImagingRecord
endpoints."""

from datetime import timedelta

from flask import Blueprint, g

import services as svc
from common import (
    ALL_ROLES, DB, ROLE_COORDINATOR, ROLE_PHYSICIAN, ROLE_QA, ROLE_TECHNOLOGIST,
    body_dict, endpoint, fail, filter_rows, new_entity, ok_entity, ok_list,
    plus_days, require_actor_at_facility, sort_rows, touch, v_bool, v_dt, v_enum,
    v_expected_version, v_id, v_int, v_state_code, v_str,
)

bp = Blueprint("exams", __name__)

EXAM_TYPES = ("SCREENING", "DIAGNOSTIC")
DENSITY_CATEGORIES = ("A", "B", "C", "D")
PATHOLOGY_RESULTS = ("PENDING", "BENIGN", "MALIGNANT")
REASON_CODES = ("POSITIONING", "MOTION", "EXPOSURE", "ARTIFACT", "EQUIPMENT_FAILURE")
CHANNELS = ("MAIL", "PORTAL")
ORDER_MODALITIES = ("ULTRASOUND", "MRI", "CEM")
FINAL_REPORT_STATUSES = ("INTERPRETED_FINAL", "AMENDED")
SUPERSEDABLE = ("QUEUED", "SENT", "DELIVERED_ASSUMED")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def _exam_or_404(exam_id):
    exam = DB.get("exam", exam_id)
    if exam is None:
        fail("ERR_EXAM_NOT_FOUND", "exam %s does not exist" % exam_id)
    return exam


def _letter_or_404(letter_id):
    letter = DB.get("letter", letter_id)
    if letter is None:
        fail("ERR_LETTER_NOT_FOUND", "notification letter %s does not exist" % letter_id)
    return letter


def _order_or_404(order_id):
    order = DB.get("order", order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND", "supplemental order %s does not exist" % order_id)
    return order


def _repeat_or_404(record_id):
    record = DB.get("repeat", record_id)
    if record is None:
        fail("ERR_REPEAT_RECORD_NOT_FOUND",
             "repeat imaging record %s does not exist" % record_id)
    return record


def _unit_of_exam(exam):
    return DB.get("unit", exam["unit_id"])


def _facility_of_exam(exam):
    return svc.facility_of_exam(exam)


def _governing_policy(exam):
    policy = svc.governing_policy_for_exam(exam)
    if policy is None:
        fail("ERR_STATE_POLICY_NOT_FOUND",
             "no state policy governs this exam")
    return policy


def _recall_flag(exam_type, birads):
    return exam_type == "SCREENING" and birads == 0


# ---------------------------------------------------------------------------
# Exam
# ---------------------------------------------------------------------------
@bp.route("/exams", methods=["POST"])
@endpoint([ROLE_TECHNOLOGIST])
def exam_create():
    # priority 3, part one: the caller must be a technologist personnel row at all
    actor = require_actor_at_facility(None, "TECHNOLOGIST")

    body = body_dict()
    unit_id = v_id(body, "unit_id", True)
    technologist_id = v_id(body, "technologist_id", True)
    patient_ref = v_str(body, "patient_ref", True, 1)
    patient_state_code = v_state_code(body, "patient_state_code", True)
    exam_type = v_enum(body, "exam_type", EXAM_TYPES, True)
    performed_at = v_dt(body, "performed_at", True)
    original_image_count = v_int(body, "original_image_count", True, 1)

    # priority 25: body references
    unit = DB.get("unit", unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND", "unit %s does not exist" % unit_id)
    technologist = DB.get("personnel", technologist_id)
    if technologist is None:
        fail("ERR_PERSONNEL_NOT_FOUND", "personnel %s does not exist" % technologist_id)

    # priority 3, part two: membership of the unit's facility and self-attribution
    if actor["facility_id"] != unit["facility_id"]:
        fail("ERR_ACTOR_NOT_AT_FACILITY",
             "acting technologist is not personnel of this unit's facility")
    if technologist_id != g.user_id:
        fail("ERR_ACTOR_NOT_AT_FACILITY",
             "technologist_id must equal the calling X-User-ID")
    if technologist["facility_id"] != unit["facility_id"]:
        fail("ERR_ACTOR_NOT_AT_FACILITY",
             "the named technologist is not personnel of this unit's facility")

    # priority 41
    if unit["operational_state"] != "IN_SERVICE":
        fail("ERR_UNIT_NOT_IN_SERVICE", "the unit is out of service")
    # priority 50
    if technologist["qualification_status"] != "QUALIFIED":
        fail("ERR_TECHNOLOGIST_NOT_QUALIFIED",
             "the technologist is not QUALIFIED")
    # priority 52
    if unit["modality"] not in (technologist["modality_certifications"] or []):
        fail("ERR_MODALITY_NOT_CERTIFIED",
             "the technologist is not certified for %s" % unit["modality"])
    # priority 53
    if unit["accreditation_status"] == "SUSPENDED":
        fail("ERR_UNIT_ACCREDITATION_SUSPENDED",
             "the unit's accreditation is suspended")
    # priority 60
    if performed_at > DB.clock:
        fail("ERR_FUTURE_TIMESTAMP", "performed_at may not be in the future")

    policy = _governing_policy({"unit_id": unit_id,
                                "patient_state_code": patient_state_code})
    report_due_at = plus_days(performed_at, policy["report_turnaround_days"])

    exam = new_entity("exam", {
        "unit_id": unit_id,
        "technologist_id": technologist_id,
        "interpreting_physician_id": None,
        "patient_ref": patient_ref,
        "patient_state_code": patient_state_code,
        "exam_type": exam_type,
        "performed_at": performed_at,
        "original_image_count": original_image_count,
        "report_status": "AWAITING_INTERPRETATION",
        "notification_status": "NOT_REQUIRED",
        "follow_up_status": "NOT_REQUIRED",
        "birads_assessment": None,
        "density_category": None,
        "recall_flag": False,
        "biopsy_performed": False,
        "pathology_result": None,
        "outcome_recorded_at": None,
        "repeat_image_count": 0,
        "report_due_at": report_due_at,
        "interpreted_at": None,
        "interpreted_late": False,
        "notification_deadline_at": None,
        "amendment_count": 0,
    })
    svc.recompute_unit_repeat_rate(unit)
    return ok_entity(exam, 201)


@bp.route("/exams/<exam_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def exam_read(exam_id):
    return ok_entity(_exam_or_404(exam_id))


@bp.route("/exams", methods=["GET"])
@endpoint(ALL_ROLES)
def exams_list():
    rows = filter_rows(DB.all("exam"), {
        "unit_id": "unit_id",
        "technologist_id": "technologist_id",
        "interpreting_physician_id": "interpreting_physician_id",
        "exam_type": "exam_type",
        "report_status": "report_status",
        "notification_status": "notification_status",
        "follow_up_status": "follow_up_status",
        "density_category": "density_category",
    })
    return ok_list(sort_rows(rows))


@bp.route("/exams/<exam_id>/interpret", methods=["POST"])
@endpoint([ROLE_PHYSICIAN])
def exam_interpret(exam_id):
    actor = require_actor_at_facility(None, "INTERPRETING_PHYSICIAN")
    exam = _exam_or_404(exam_id)
    unit = _unit_of_exam(exam)
    if unit is not None and actor["facility_id"] != unit["facility_id"]:
        fail("ERR_ACTOR_NOT_AT_FACILITY",
             "acting physician is not personnel of this exam's facility")

    body = body_dict()
    birads = v_int(body, "birads_assessment", True, 0, 6)
    density = v_enum(body, "density_category", DENSITY_CATEGORIES, False, default=None)

    # priority 40
    if exam["report_status"] not in ("AWAITING_INTERPRETATION", "DELAYED"):
        fail("ERR_EXAM_NOT_INTERPRETABLE",
             "an exam in report_status %s cannot be interpreted" % exam["report_status"])
    # priority 51
    if actor["qualification_status"] != "QUALIFIED":
        fail("ERR_PHYSICIAN_NOT_QUALIFIED", "the interpreting physician is not QUALIFIED")
    # priority 52
    if unit is not None and unit["modality"] not in (actor["modality_certifications"] or []):
        fail("ERR_MODALITY_NOT_CERTIFIED",
             "the physician is not certified for %s" % unit["modality"])
    # priority 74
    if exam["exam_type"] == "SCREENING" and density is None:
        fail("ERR_DENSITY_CATEGORY_REQUIRED",
             "a screening exam requires a density_category at interpretation")

    policy = _governing_policy(exam)

    exam["birads_assessment"] = birads
    if density is not None:
        exam["density_category"] = density
    exam["interpreting_physician_id"] = g.user_id
    exam["interpreted_at"] = DB.clock
    exam["report_status"] = "INTERPRETED_FINAL"
    if birads in svc.URGENT_BIRADS:
        exam["report_due_at"] = plus_days(exam["performed_at"],
                                          policy["urgent_report_turnaround_days"])
    exam["interpreted_late"] = exam["interpreted_at"] > exam["report_due_at"]
    exam["recall_flag"] = _recall_flag(exam["exam_type"], birads)
    exam["notification_status"] = "PENDING"
    exam["follow_up_status"] = "PENDING" if exam["recall_flag"] else "NOT_REQUIRED"
    touch(exam)
    svc.recompute_open_notices(_facility_of_exam(exam))
    return ok_entity(exam)


@bp.route("/exams/<exam_id>/amend", methods=["POST"])
@endpoint([ROLE_PHYSICIAN])
def exam_amend(exam_id):
    actor = require_actor_at_facility(None, "INTERPRETING_PHYSICIAN")
    exam = _exam_or_404(exam_id)
    unit = _unit_of_exam(exam)
    if unit is not None and actor["facility_id"] != unit["facility_id"]:
        fail("ERR_ACTOR_NOT_AT_FACILITY",
             "acting physician is not personnel of this exam's facility")

    # priority 6 -- ownership; an exam never interpreted has no owner
    if exam["interpreting_physician_id"] is not None and \
            exam["interpreting_physician_id"] != g.user_id:
        fail("ERR_NOT_INTERPRETING_PHYSICIAN",
             "only the exam's interpreting physician may amend it")

    body = body_dict()
    birads = v_int(body, "birads_assessment", False, 0, 6, default=None)
    density = v_enum(body, "density_category", DENSITY_CATEGORIES, False, default=None)
    v_str(body, "amendment_reason", False, 1, default=None)

    # priority 40
    if exam["report_status"] not in FINAL_REPORT_STATUSES:
        fail("ERR_EXAM_NOT_AMENDABLE",
             "an exam in report_status %s cannot be amended" % exam["report_status"])
    # priority 51
    if actor["qualification_status"] != "QUALIFIED":
        fail("ERR_PHYSICIAN_NOT_QUALIFIED", "the amending physician is not QUALIFIED")
    # priority 73
    changes_birads = birads is not None and birads != exam["birads_assessment"]
    changes_density = density is not None and density != exam["density_category"]
    if not (changes_birads or changes_density):
        fail("ERR_AMENDMENT_NO_CHANGE",
             "an amendment must change birads_assessment or density_category")

    if changes_birads:
        exam["birads_assessment"] = birads
    if changes_density:
        exam["density_category"] = density
    exam["report_status"] = "AMENDED"
    exam["amendment_count"] += 1
    exam["recall_flag"] = _recall_flag(exam["exam_type"], exam["birads_assessment"])

    # cascade level 2: supersede the letter the patient is holding
    superseded_any = False
    for letter in svc.in_order(svc.letters_of_exam(exam_id), "created_at"):
        if letter["status"] in SUPERSEDABLE:
            letter["status"] = "SUPERSEDED"
            touch(letter)
            superseded_any = True
    # cascade level 3: reopen the notification obligation
    if superseded_any:
        exam["notification_status"] = "PENDING"
        exam["notification_deadline_at"] = None
    touch(exam)

    # fan-out to the audit ledger (not part of the cascade chain)
    for cycle in svc.in_order(DB.all("cycle"), "created_at"):
        if cycle["radiologist_id"] != exam["interpreting_physician_id"]:
            continue
        if cycle["status"] != "LOCKED":
            continue
        if cycle["period_start"] <= exam["performed_at"] < cycle["period_end"]:
            cycle["status"] = "AMENDED"
            touch(cycle)

    svc.recompute_open_notices(_facility_of_exam(exam))
    return ok_entity(exam)


@bp.route("/exams/<exam_id>/outcome", methods=["POST"])
@endpoint([ROLE_QA])
def exam_outcome(exam_id):
    exam = _exam_or_404(exam_id)
    # priority 4 -- the officer may not be the physician who signed the read
    if exam["interpreting_physician_id"] is not None and \
            exam["interpreting_physician_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the interpreting physician may not record the pathology outcome")

    body = body_dict()
    biopsy = v_bool(body, "biopsy_performed", True)
    result = v_enum(body, "pathology_result", PATHOLOGY_RESULTS, True)

    # priority 40
    if exam["pathology_result"] in ("BENIGN", "MALIGNANT"):
        fail("ERR_OUTCOME_ALREADY_RECORDED",
             "the pathology outcome is already settled")

    exam["biopsy_performed"] = biopsy
    exam["pathology_result"] = result
    exam["outcome_recorded_at"] = DB.clock
    touch(exam)
    return ok_entity(exam)


# ---------------------------------------------------------------------------
# RepeatImagingRecord
# ---------------------------------------------------------------------------
@bp.route("/exams/<exam_id>/repeat-records", methods=["POST"])
@endpoint([ROLE_TECHNOLOGIST, ROLE_COORDINATOR])
def repeat_create(exam_id):
    exam = _exam_or_404(exam_id)
    body = body_dict()
    reason_code = v_enum(body, "reason_code", REASON_CODES, True)
    count = v_int(body, "repeat_image_count", True, 1)
    failure_id = v_id(body, "equipment_failure_id", False, default=None)

    # priority 20 -- conditional pairing
    if reason_code == "EQUIPMENT_FAILURE":
        if failure_id is None:
            fail("ERR_INVALID_REQUEST",
                 "equipment_failure_id is required when reason_code is EQUIPMENT_FAILURE")
    elif failure_id is not None:
        fail("ERR_INVALID_REQUEST",
             "equipment_failure_id may only accompany reason_code EQUIPMENT_FAILURE")

    # priority 25
    failure = None
    if failure_id is not None:
        failure = DB.get("failure", failure_id)
        if failure is None:
            fail("ERR_FAILURE_EVENT_NOT_FOUND",
                 "equipment failure event %s does not exist" % failure_id)
    # priority 58
    if failure is not None and failure["unit_id"] != exam["unit_id"]:
        fail("ERR_FAILURE_UNIT_MISMATCH",
             "the failure event belongs to a different unit than the exam")

    record = new_entity("repeat", {
        "exam_id": exam_id,
        "equipment_failure_id": failure_id,
        "reason_code": reason_code,
        "repeat_image_count": count,
        "retracted": False,
        "retraction_reason": None,
        "documented_at": DB.clock,
    })
    unit = _unit_of_exam(exam)
    if unit is not None:
        svc.recompute_unit_repeat_rate(unit)
    return ok_entity(record, 201)


@bp.route("/exams/<exam_id>/repeat-records", methods=["GET"])
@endpoint(ALL_ROLES)
def exam_repeats_list(exam_id):
    _exam_or_404(exam_id)
    rows = svc.repeats_of_exam(exam_id)
    rows = filter_rows(rows, {"retracted": "retracted"})
    return ok_list(sort_rows(rows))


@bp.route("/repeat-records/<record_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def repeat_read(record_id):
    return ok_entity(_repeat_or_404(record_id))


@bp.route("/repeat-records", methods=["GET"])
@endpoint(ALL_ROLES)
def repeats_list():
    rows = filter_rows(DB.all("repeat"), {
        "exam_id": "exam_id",
        "equipment_failure_id": "equipment_failure_id",
        "reason_code": "reason_code",
        "retracted": "retracted",
    })
    return ok_list(sort_rows(rows))


@bp.route("/repeat-records/<record_id>/retract", methods=["POST"])
@endpoint([ROLE_QA])
def repeat_retract(record_id):
    record = _repeat_or_404(record_id)
    body = body_dict()
    reason = v_str(body, "retraction_reason", True, 1)
    # priority 40
    if record["retracted"]:
        fail("ERR_REPEAT_RECORD_ALREADY_RETRACTED",
             "the repeat record has already been retracted")
    record["retracted"] = True
    record["retraction_reason"] = reason
    touch(record)
    exam = DB.get("exam", record["exam_id"])
    unit = _unit_of_exam(exam) if exam is not None else None
    if unit is not None:
        svc.recompute_unit_repeat_rate(unit)
    return ok_entity(record)


# ---------------------------------------------------------------------------
# NotificationLetter
# ---------------------------------------------------------------------------
@bp.route("/exams/<exam_id>/notification-letters", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def letter_create(exam_id):
    exam = _exam_or_404(exam_id)
    body = body_dict()
    expected = v_expected_version(body, "expected_exam_version")
    channel = v_enum(body, "dispatch_channel", CHANNELS, False, default="MAIL")

    # priority 30
    if expected != exam["version"]:
        fail("ERR_STALE_EXAM_VERSION",
             "expected_exam_version %s does not match the exam's current version %s"
             % (expected, exam["version"]))
    # priority 40
    if exam["report_status"] not in FINAL_REPORT_STATUSES or \
            exam["notification_status"] != "PENDING":
        fail("ERR_LETTER_NOT_SENDABLE",
             "a letter can only be generated for a final exam whose notification "
             "obligation is PENDING")

    policy = _governing_policy(exam)
    req = svc.notification_requirements(exam, policy)
    deadline_at = plus_days(DB.clock, req["deadline_days"])

    # The replacement points at the exam's most recent previous letter (null only on
    # the exam's very first letter) and supersedes every letter not already SUPERSEDED.
    history = svc.in_order(svc.letters_of_exam(exam_id), "created_at")
    prior = [l for l in history if l["status"] != "SUPERSEDED"]
    letter = new_entity("letter", {
        "exam_id": exam_id,
        "supersedes_letter_id": history[-1]["id"] if history else None,
        "letter_type": req["letter_type"],
        "status": "QUEUED",
        "required_notice_codes": req["required_notice_codes"],
        "density_statement_code": req["density_statement_code"],
        "reading_grade_level": req["reading_grade_level"],
        "deadline_at": deadline_at,
        "governing_state_code": req["governing_state_code"],
        "dispatch_channel": channel,
        "generated_at": DB.clock,
        "sent_at": None,
        "undeliverable_reason": None,
    })
    for old in prior:
        old["status"] = "SUPERSEDED"
        touch(old)

    exam["notification_status"] = "GENERATED"
    exam["notification_deadline_at"] = deadline_at
    touch(exam)
    svc.recompute_open_notices(_facility_of_exam(exam))
    return ok_entity(letter, 201)


@bp.route("/exams/<exam_id>/notification-letters", methods=["GET"])
@endpoint(ALL_ROLES)
def exam_letters_list(exam_id):
    _exam_or_404(exam_id)
    rows = filter_rows(svc.letters_of_exam(exam_id), {"status": "status"})
    return ok_list(sort_rows(rows))


@bp.route("/notification-letters/<letter_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def letter_read(letter_id):
    return ok_entity(_letter_or_404(letter_id))


@bp.route("/notification-letters", methods=["GET"])
@endpoint(ALL_ROLES)
def letters_list():
    rows = filter_rows(DB.all("letter"), {
        "exam_id": "exam_id",
        "supersedes_letter_id": "supersedes_letter_id",
        "status": "status",
        "letter_type": "letter_type",
    })
    return ok_list(sort_rows(rows))


@bp.route("/notification-letters/<letter_id>/send", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def letter_send(letter_id):
    letter = _letter_or_404(letter_id)
    body_dict()
    exam = DB.get("exam", letter["exam_id"])
    # priority 40
    if letter["status"] != "QUEUED":
        fail("ERR_LETTER_NOT_SENDABLE",
             "a letter in status %s cannot be dispatched" % letter["status"])
    if exam is None or exam["report_status"] not in FINAL_REPORT_STATUSES:
        fail("ERR_LETTER_NOT_SENDABLE",
             "the letter's exam is no longer in a final report status")

    letter["status"] = "SENT"
    letter["sent_at"] = DB.clock
    touch(letter)
    exam["notification_status"] = "SENT"
    touch(exam)
    svc.recompute_open_notices(_facility_of_exam(exam))
    return ok_entity(letter)


@bp.route("/notification-letters/<letter_id>/mark-undeliverable", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def letter_mark_undeliverable(letter_id):
    letter = _letter_or_404(letter_id)
    body = body_dict()
    reason = v_str(body, "undeliverable_reason", True, 1)
    # priority 40
    if letter["status"] != "SENT":
        fail("ERR_LETTER_NOT_SENT",
             "a letter in status %s cannot be marked undeliverable" % letter["status"])

    letter["status"] = "UNDELIVERABLE"
    letter["undeliverable_reason"] = reason
    touch(letter)
    exam = DB.get("exam", letter["exam_id"])
    if exam is not None:
        exam["notification_status"] = "PENDING"
        exam["notification_deadline_at"] = None
        touch(exam)
        svc.recompute_open_notices(_facility_of_exam(exam))
    return ok_entity(letter)


# ---------------------------------------------------------------------------
# SupplementalScreeningOrder
# ---------------------------------------------------------------------------
@bp.route("/exams/<exam_id>/supplemental-orders", methods=["POST"])
@endpoint([ROLE_PHYSICIAN, ROLE_COORDINATOR])
def order_create(exam_id):
    exam = _exam_or_404(exam_id)
    body = body_dict()
    modality = v_enum(body, "modality", ORDER_MODALITIES, True)
    v_str(body, "recommendation_note", False, 1, default=None)

    # priority 75
    if exam["report_status"] not in FINAL_REPORT_STATUSES or \
            exam["density_category"] is None:
        fail("ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL",
             "supplemental screening requires a final exam carrying a density_category")

    policy = _governing_policy(exam)
    order = new_entity("order", {
        "exam_id": exam_id,
        "modality": modality,
        "status": "RECOMMENDED",
        "coverage_outcome": "UNDETERMINED",
        "allowed_amount_cents": None,
        "covered_amount_cents": None,
        "patient_responsibility_cents": None,
        "coverage_tier": None,
        "governing_state_code": None,
        "recommended_at": DB.clock,
        "followup_due_at": plus_days(DB.clock, policy["followup_grace_days"]),
        "appointment_start": None,
        "appointment_end": None,
        "completed_at": None,
        "external_referral_note": None,
    })
    if exam["follow_up_status"] != "PENDING":
        exam["follow_up_status"] = "PENDING"
        touch(exam)
    return ok_entity(order, 201)


@bp.route("/exams/<exam_id>/supplemental-orders", methods=["GET"])
@endpoint(ALL_ROLES)
def exam_orders_list(exam_id):
    _exam_or_404(exam_id)
    rows = filter_rows(svc.orders_of_exam(exam_id), {"status": "status"})
    return ok_list(sort_rows(rows))


@bp.route("/supplemental-orders/<order_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def order_read(order_id):
    return ok_entity(_order_or_404(order_id))


@bp.route("/supplemental-orders", methods=["GET"])
@endpoint(ALL_ROLES)
def orders_list():
    rows = filter_rows(DB.all("order"), {
        "exam_id": "exam_id",
        "status": "status",
        "modality": "modality",
        "coverage_outcome": "coverage_outcome",
    })
    return ok_list(sort_rows(rows))


@bp.route("/supplemental-orders/<order_id>/coverage-determination", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def order_coverage_determination(order_id):
    order = _order_or_404(order_id)
    body_dict()
    # priority 40
    if order["status"] != "RECOMMENDED":
        fail("ERR_ORDER_NOT_DETERMINABLE",
             "an order in status %s cannot be priced" % order["status"])
    exam = DB.get("exam", order["exam_id"])
    if exam is None or exam["density_category"] is None:
        fail("ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL",
             "the exam no longer carries a density_category")

    policy = _governing_policy(exam)
    result = svc.determine_coverage(exam, order, policy)
    order["governing_state_code"] = policy["state_code"]
    order["coverage_outcome"] = result["coverage_outcome"]
    order["allowed_amount_cents"] = result["allowed_amount_cents"]
    order["covered_amount_cents"] = result["covered_amount_cents"]
    order["patient_responsibility_cents"] = result["patient_responsibility_cents"]
    order["coverage_tier"] = result["coverage_tier"]
    order["status"] = "COVERAGE_DETERMINED"
    touch(order)
    return ok_entity(order)


@bp.route("/supplemental-orders/<order_id>/schedule", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def order_schedule(order_id):
    order = _order_or_404(order_id)
    body = body_dict()
    start = v_dt(body, "appointment_start", True)

    # priority 40
    if order["status"] not in ("COVERAGE_DETERMINED", "LOST_TO_FOLLOW_UP"):
        fail("ERR_ORDER_NOT_SCHEDULABLE",
             "an order in status %s cannot be scheduled" % order["status"])
    exam = DB.get("exam", order["exam_id"])
    facility = _facility_of_exam(exam) if exam is not None else None
    # priority 42
    if facility is not None and facility["compliance_posture"] == "SUSPENDED":
        fail("ERR_FACILITY_SUSPENDED",
             "the facility's compliance posture is SUSPENDED")
    # priority 65
    if start < DB.clock:
        fail("ERR_APPOINTMENT_IN_PAST",
             "appointment_start may not be before the logical clock")
    # priority 76
    if order["coverage_outcome"] == "UNDETERMINED":
        fail("ERR_COVERAGE_NOT_DETERMINED",
             "coverage must be determined before the study is scheduled")

    end = start + timedelta(minutes=svc.SLOT_MINUTES[order["modality"]])
    # priority 77
    if facility is not None:
        svc.check_appointment_capacity(facility, order, start, end)

    order["status"] = "SCHEDULED"
    order["appointment_start"] = start
    order["appointment_end"] = end
    touch(order)
    if exam is not None and exam["follow_up_status"] != "PENDING":
        exam["follow_up_status"] = "PENDING"
        touch(exam)
    return ok_entity(order)


@bp.route("/supplemental-orders/<order_id>/complete", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def order_complete(order_id):
    order = _order_or_404(order_id)
    body = body_dict()
    v_str(body, "completion_note", False, 1, default=None)
    # priority 40
    if order["status"] != "SCHEDULED":
        fail("ERR_ORDER_NOT_COMPLETABLE",
             "an order in status %s cannot be completed" % order["status"])

    order["status"] = "COMPLETED"
    order["completed_at"] = DB.clock
    touch(order)

    exam = DB.get("exam", order["exam_id"])
    if exam is not None:
        outstanding = [o for o in svc.orders_of_exam(exam["id"])
                       if o["id"] != order["id"]
                       and o["status"] not in svc.ORDER_TERMINAL]
        if not outstanding and exam["follow_up_status"] != "COMPLETED":
            exam["follow_up_status"] = "COMPLETED"
            touch(exam)
    return ok_entity(order)
