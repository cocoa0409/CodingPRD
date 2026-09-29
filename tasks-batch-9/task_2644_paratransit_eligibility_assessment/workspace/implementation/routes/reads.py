"""The 22 read endpoints of PRD 4."""

from flask import Blueprint, request

import lookups
import owners
import serializers
from auth import actor_id, actor_role, require
from envelope import listing, ok
from store import db, ordered

bp = Blueprint("reads", __name__)

ALL_ROLES = (
    "Applicant",
    "IntakeClerk",
    "Evaluator",
    "EligibilitySpecialist",
    "IndependentReviewer",
    "ConductOfficer",
    "TravelTrainer",
    "AccessibilityOfficeAdmin",
)


def _filter_eq(records, field, arg_name=None):
    value = request.args.get(arg_name or field)
    if value is None:
        return records
    return [r for r in records if r.get(field) == value]


def _filter_bool(records, field):
    value = request.args.get(field)
    if value is None:
        return records
    wanted = value.strip().lower() in ("true", "1", "yes")
    return [r for r in records if bool(r.get(field)) is wanted]


# ---------------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------------

@bp.get("/applicants/<applicant_id>")
@require(ALL_ROLES, ownership=owners.applicant_path)
def get_applicant(applicant_id):
    rec = lookups.applicant(applicant_id)
    return ok(serializers.applicant(rec))


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

@bp.get("/applications/<application_id>")
@require(
    ("Applicant", "IntakeClerk", "EligibilitySpecialist", "IndependentReviewer", "AccessibilityOfficeAdmin"),
    ownership=owners.application_path,
)
def get_application(application_id):
    rec = lookups.application(application_id)
    return ok(serializers.application(rec))


@bp.get("/applications")
@require(
    ("Applicant", "IntakeClerk", "EligibilitySpecialist", "AccessibilityOfficeAdmin"),
    ownership=owners.query_applicant_filter,
)
def list_applications():
    records = list(db.applications.values())
    if actor_role() == "Applicant":
        records = [r for r in records if r["applicant_id"] == actor_id()]
    records = _filter_eq(records, "applicant_id")
    records = _filter_eq(records, "status")
    records = _filter_eq(records, "application_type")
    return listing(ordered(records), serializers.application)


@bp.get("/applications/<application_id>/verifications")
@require(("IntakeClerk", "EligibilitySpecialist", "IndependentReviewer", "AccessibilityOfficeAdmin"))
def list_verifications(application_id):
    app_rec = lookups.application(application_id)
    records = lookups.verifications_of(app_rec["id"])
    records = _filter_eq(records, "status")
    return listing(ordered(records), serializers.verification)


# ---------------------------------------------------------------------------
# AssessmentSlot / FunctionalAssessment
# ---------------------------------------------------------------------------

@bp.get("/assessment-slots/<slot_id>")
@require(("IntakeClerk", "Evaluator", "EligibilitySpecialist", "AccessibilityOfficeAdmin"))
def get_slot(slot_id):
    return ok(serializers.slot(lookups.slot(slot_id)))


@bp.get("/assessments/<assessment_id>")
@require(
    ("Applicant", "IntakeClerk", "Evaluator", "EligibilitySpecialist", "IndependentReviewer", "AccessibilityOfficeAdmin")
)
def get_assessment(assessment_id):
    return ok(serializers.assessment(lookups.assessment(assessment_id)))


@bp.get("/assessments")
@require(("IntakeClerk", "Evaluator", "EligibilitySpecialist", "AccessibilityOfficeAdmin"))
def list_assessments():
    records = list(db.assessments.values())
    records = _filter_eq(records, "application_id")
    records = _filter_eq(records, "slot_id")
    records = _filter_eq(records, "rescheduled_from_assessment_id")
    records = _filter_eq(records, "attendance_status")
    return listing(ordered(records), serializers.assessment)


# ---------------------------------------------------------------------------
# Vehicle / TransportationBooking
# ---------------------------------------------------------------------------

@bp.get("/vehicles/<vehicle_id>")
@require(("IntakeClerk", "AccessibilityOfficeAdmin"))
def get_vehicle(vehicle_id):
    return ok(serializers.vehicle(lookups.vehicle(vehicle_id)))


@bp.get("/transportation-bookings/<booking_id>")
@require(("Applicant", "IntakeClerk", "AccessibilityOfficeAdmin"))
def get_booking(booking_id):
    return ok(serializers.booking(lookups.booking(booking_id)))


@bp.get("/transportation-bookings")
@require(("IntakeClerk", "AccessibilityOfficeAdmin"))
def list_bookings():
    records = list(db.bookings.values())
    records = _filter_eq(records, "assessment_id")
    records = _filter_eq(records, "vehicle_id")
    records = _filter_eq(records, "status")
    return listing(ordered(records), serializers.booking)


# ---------------------------------------------------------------------------
# Determination / TripCondition / Appeal
# ---------------------------------------------------------------------------

DETERMINATION_READ_ROLES = (
    "Applicant",
    "IntakeClerk",
    "EligibilitySpecialist",
    "IndependentReviewer",
    "ConductOfficer",
    "TravelTrainer",
    "AccessibilityOfficeAdmin",
)


@bp.get("/determinations/<determination_id>")
@require(DETERMINATION_READ_ROLES, ownership=owners.determination_path)
def get_determination(determination_id):
    return ok(serializers.determination(lookups.determination(determination_id)))


@bp.get("/determinations")
@require(DETERMINATION_READ_ROLES, ownership=owners.query_applicant_filter)
def list_determinations():
    records = list(db.determinations.values())
    if actor_role() == "Applicant":
        records = [r for r in records if r["applicant_id"] == actor_id()]
    records = _filter_eq(records, "application_id")
    records = _filter_eq(records, "applicant_id")
    records = _filter_eq(records, "status")
    records = _filter_eq(records, "category")
    records = _filter_eq(records, "origin")
    return listing(ordered(records), serializers.determination)


@bp.get("/determinations/<determination_id>/trip-conditions")
@require(
    ("Applicant", "IntakeClerk", "EligibilitySpecialist", "IndependentReviewer", "TravelTrainer", "AccessibilityOfficeAdmin"),
    ownership=owners.determination_path,
)
def list_trip_conditions(determination_id):
    det = lookups.determination(determination_id)
    records = lookups.conditions_of(det["id"])
    return listing(ordered(records), serializers.trip_condition)


@bp.get("/determinations/<determination_id>/appeals")
@require(
    ("Applicant", "EligibilitySpecialist", "IndependentReviewer", "AccessibilityOfficeAdmin"),
    ownership=owners.determination_path,
)
def list_determination_appeals(determination_id):
    det = lookups.determination(determination_id)
    records = lookups.appeals_of_determination(det["id"])
    records = _filter_eq(records, "status")
    return listing(ordered(records), serializers.appeal)


@bp.get("/appeals/<appeal_id>")
@require(("Applicant", "EligibilitySpecialist", "IndependentReviewer", "AccessibilityOfficeAdmin"))
def get_appeal(appeal_id):
    return ok(serializers.appeal(lookups.appeal(appeal_id)))


# ---------------------------------------------------------------------------
# TripEvent / SuspensionProceeding
# ---------------------------------------------------------------------------

@bp.get("/applicants/<applicant_id>/trip-events")
@require(("Applicant", "ConductOfficer", "AccessibilityOfficeAdmin"), ownership=owners.applicant_path)
def list_trip_events(applicant_id):
    rec = lookups.applicant(applicant_id)
    records = lookups.trip_events_of(rec["id"])
    records = _filter_eq(records, "event_type")
    records = _filter_bool(records, "excused")
    records = sorted(records, key=lambda r: (r["trip_date"], r["created_at"], r["_seq"]))
    return listing(records, serializers.trip_event)


@bp.get("/applicants/<applicant_id>/suspension-proceedings")
@require(
    ("Applicant", "ConductOfficer", "IndependentReviewer", "AccessibilityOfficeAdmin"),
    ownership=owners.applicant_path,
)
def list_proceedings(applicant_id):
    rec = lookups.applicant(applicant_id)
    records = lookups.proceedings_of(rec["id"])
    records = _filter_eq(records, "status")
    return listing(ordered(records), serializers.proceeding)


@bp.get("/suspension-proceedings/<proceeding_id>")
@require(("Applicant", "ConductOfficer", "IndependentReviewer", "AccessibilityOfficeAdmin"))
def get_proceeding(proceeding_id):
    return ok(serializers.proceeding(lookups.proceeding(proceeding_id)))


# ---------------------------------------------------------------------------
# TravelTrainingReferral
# ---------------------------------------------------------------------------

REFERRAL_READ_ROLES = ("Applicant", "TravelTrainer", "EligibilitySpecialist", "AccessibilityOfficeAdmin")


@bp.get("/travel-training-referrals/<referral_id>")
@require(REFERRAL_READ_ROLES)
def get_referral(referral_id):
    return ok(serializers.referral(lookups.referral(referral_id)))


@bp.get("/travel-training-referrals")
@require(REFERRAL_READ_ROLES)
def list_referrals():
    records = list(db.referrals.values())
    records = _filter_eq(records, "applicant_id")
    records = _filter_eq(records, "determination_id")
    records = _filter_eq(records, "status")
    return listing(ordered(records), serializers.referral)


# ---------------------------------------------------------------------------
# VisitorEligibility
# ---------------------------------------------------------------------------

@bp.get("/applicants/<applicant_id>/visitor-eligibilities")
@require(("Applicant", "IntakeClerk", "AccessibilityOfficeAdmin"), ownership=owners.applicant_path)
def list_visitor_records(applicant_id):
    rec = lookups.applicant(applicant_id)
    records = lookups.visitor_records_of(rec["id"])
    records = _filter_eq(records, "status")
    return listing(ordered(records), serializers.visitor_record)


@bp.get("/visitor-eligibilities/<visitor_record_id>")
@require(("Applicant", "IntakeClerk", "AccessibilityOfficeAdmin"))
def get_visitor_record(visitor_record_id):
    return ok(serializers.visitor_record(lookups.visitor_record(visitor_record_id)))
