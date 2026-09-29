"""Subject registration, consent version pinning, visit scheduling and completion."""

from flask import Blueprint, request

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import actor, require
from errors import ApiError

bp = Blueprint("subjects", __name__, url_prefix="/research-billing")

READ_ROLES = ("StudyCoordinator", "ResearchBillingManager", "ComplianceReviewer",
              "AuditLiaison")


@bp.post("/study-subjects")
@require("StudyCoordinator")
def create_subject():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    subject_number = v.req_str(body, "subject_number")

    study = lookup.study(study_id)
    if study["lifecycle_status"] != "OPEN_TO_ACCRUAL":
        raise ApiError("ERR_STUDY_NOT_OPEN_TO_ACCRUAL")

    for existing in derive.subjects_of(study["id"]):
        if existing["subject_number"] == subject_number:
            raise ApiError("ERR_DUPLICATE_SUBJECT_NUMBER")

    rec = store.base_record()
    rec.update({
        "study_id": study["id"],
        "subject_number": subject_number,
        "consented_calendar_id": None,
        "consented_calendar_generation": None,
        "consent_date": None,
        "status": "SCREENING",
    })
    store.subjects[rec["id"]] = rec
    return envelope.created(serializers.subject(rec))


@bp.get("/study-subjects")
@require(*READ_ROLES)
def list_subjects():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.subjects.values())
    for key in ("study_id", "consented_calendar_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.subject(r) for r in page], limit, offset, total)


@bp.get("/study-subjects/<subject_id>")
@require(*READ_ROLES)
def get_subject(subject_id):
    return envelope.ok(serializers.subject(lookup.subject(subject_id)))


@bp.post("/study-subjects/<subject_id>/consent")
@require("StudyCoordinator")
def consent(subject_id):
    body = v.body()
    consent_date = v.req_date(body, "consent_date")

    rec = lookup.subject(subject_id)
    if rec["status"] != "SCREENING":
        raise ApiError("ERR_SUBJECT_NOT_SCREENING")

    study = lookup.study(rec["study_id"])
    if study["lifecycle_status"] != "OPEN_TO_ACCRUAL":
        raise ApiError("ERR_STUDY_NOT_OPEN_TO_ACCRUAL")
    if study["budget_status"] != "EXECUTED":
        raise ApiError("ERR_BUDGET_NOT_EXECUTED")

    published = [c for c in derive.calendars_of(study["id"]) if c["status"] == "PUBLISHED"]
    if len(published) != 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    calendar = published[0]

    rec["status"] = "CONSENTED"
    rec["consent_date"] = consent_date
    rec["consented_calendar_id"] = calendar["id"]
    rec["consented_calendar_generation"] = calendar["build_generation"]
    store.touch(rec)
    return envelope.ok(serializers.subject(rec))


@bp.post("/subject-visits")
@require("StudyCoordinator")
def create_subject_visit():
    body = v.body()
    subject_id = v.req_id(body, "study_subject_id")
    calendar_visit_id = v.req_id(body, "calendar_visit_id")
    actual_service_date = v.req_date(body, "actual_service_date")

    subject = lookup.subject(subject_id)
    calendar_visit = lookup.calendar_visit(calendar_visit_id)

    pinned_id = subject["consented_calendar_id"]
    if pinned_id is not None:
        pinned = store.calendars.get(pinned_id)
        if pinned is not None and pinned["status"] in ("REBUILD_REQUIRED", "RETIRED"):
            raise ApiError("ERR_CALENDAR_NOT_PUBLISHED")

    if pinned_id is None or calendar_visit["study_calendar_id"] != pinned_id:
        raise ApiError("ERR_CALENDAR_VISIT_NOT_ON_CONSENTED_CALENDAR")

    consent_date = subject["consent_date"]
    window_open = v.shift_date(consent_date, calendar_visit["window_start_day"])
    window_close = v.shift_date(consent_date, calendar_visit["window_end_day"])
    if actual_service_date < window_open or actual_service_date > window_close:
        raise ApiError("ERR_VISIT_DATE_OUTSIDE_WINDOW")

    same_day = [
        sv for sv in derive.subject_visits_of_study(subject["study_id"])
        if sv["actual_service_date"] == actual_service_date
        and sv["status"] in ("SCHEDULED", "OCCURRED")
    ]
    if len(same_day) >= derive.RESEARCH_VISIT_DAILY_CAPACITY:
        raise ApiError("ERR_RESEARCH_VISIT_DAILY_CAPACITY_EXCEEDED")

    calendar = store.calendars.get(calendar_visit["study_calendar_id"])
    rec = store.base_record()
    rec.update({
        "study_subject_id": subject["id"],
        "calendar_visit_id": calendar_visit["id"],
        "actual_service_date": actual_service_date,
        "day_offset_actual": v.days_between(consent_date, actual_service_date),
        "calendar_generation_at_schedule": (
            calendar["build_generation"] if calendar is not None else None),
        "status": "SCHEDULED",
    })
    store.subject_visits[rec["id"]] = rec
    return envelope.created(serializers.subject_visit(rec))


@bp.get("/subject-visits")
@require(*READ_ROLES)
def list_subject_visits():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.subject_visits.values())
    for key in ("study_subject_id", "calendar_visit_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.subject_visit(r) for r in page],
                            limit, offset, total)


@bp.get("/subject-visits/<visit_id>")
@require(*READ_ROLES)
def get_subject_visit(visit_id):
    return envelope.ok(serializers.subject_visit(lookup.subject_visit(visit_id)))


@bp.post("/subject-visits/<visit_id>/complete")
@require("StudyCoordinator")
def complete_subject_visit(visit_id):
    rec = lookup.subject_visit(visit_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    subject = lookup.subject(rec["study_subject_id"])
    if subject["status"] != "CONSENTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    calendar_visit = lookup.calendar_visit(rec["calendar_visit_id"])
    calendar = store.calendars.get(calendar_visit["study_calendar_id"])
    if (calendar is None
            or calendar["status"] != "PUBLISHED"
            or calendar["build_generation"] != rec["calendar_generation_at_schedule"]
            or calendar["build_generation"] != subject["consented_calendar_generation"]):
        raise ApiError("ERR_STALE_CALENDAR_GENERATION")

    rec["status"] = "OCCURRED"
    store.touch(rec)

    for route in derive.routes_of_visit(calendar_visit["id"]):
        item = store.coverage_items.get(route["coverage_item_id"])
        derive.new_charge(
            study_id=subject["study_id"],
            charge_code=item["item_code"] if item is not None else None,
            service_date=rec["actual_service_date"],
            amount_cents=route["expected_amount_cents"],
            source="VISIT_CASCADE",
            subject_visit_id=rec["id"],
            coverage_item_id=route["coverage_item_id"],
            suggested_routing_target=route["routing_target"],
        )
    return envelope.ok(serializers.subject_visit(rec))
