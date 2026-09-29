"""Surge escalation, outcome surveillance and graduate follow-up (PRD 3.5, 3.9)."""
from flask import Blueprint

import cascade
import clock
import ctx
import derive
import lookup
import response
import serialize
from db import base_record, db, ordered, touch
from errors import ApiError

bp = Blueprint("oversight", __name__)

METRIC_FIELDS = ("cohort_size", "clabsi_count", "mortality_count",
                 "birth_weight_risk_weight", "crude_clabsi_rate",
                 "device_adjusted_clabsi_rate", "variant_applied",
                 "data_completeness_flag", "network_benchmark_flag")


# --------------------------------------------------------------------------
# SurgeEscalation
# --------------------------------------------------------------------------
@bp.post("/surge-escalations")
def create_escalation():
    caller = ctx.authenticate(["UnitDirector"])
    data = ctx.body()
    unit_id = ctx.req_string(data, "unit_id")
    requested_beds = ctx.req_int(data, "requested_beds", minimum=1)
    effective_from = ctx.req_dt(data, "effective_from")
    effective_to = ctx.req_dt(data, "effective_to")
    if not effective_to > effective_from:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "effective_to must be strictly after effective_from.")
    lookup.unit(unit_id)
    ctx.require_scope(caller, unit_id)

    escalation = base_record()
    escalation.update({
        "unit_id": unit_id,
        "requested_beds": requested_beds,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "census_ratio_at_request": None,
        "escalation_tier": None,
        "staffing_waiver_ratio": None,
        "authorized_beds": None,
        "status": "REQUESTED",
        "authorized_by_user_id": None,
        "denial_reason": None,
    })
    db.escalations[escalation["id"]] = escalation
    return response.created(serialize.escalation(escalation))


@bp.get("/surge-escalations")
def list_escalations():
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist"])
    limit, offset = ctx.pagination()
    active = ctx.filters("unit_id", "status", "escalation_tier")
    rows = ordered(db.escalations.values())
    for field in ("unit_id", "status", "escalation_tier"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    return response.listing(
        [serialize.escalation(r) for r in ctx.page(rows, limit, offset)],
        limit, offset, len(rows))


@bp.get("/surge-escalations/<escalation_id>")
def read_escalation(escalation_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist"])
    return response.ok(serialize.escalation(lookup.escalation(escalation_id)))


@bp.post("/surge-escalations/<escalation_id>/authorize")
def authorize_escalation(escalation_id):
    caller = ctx.authenticate(["NetworkAdmin"])
    escalation = lookup.escalation(escalation_id)
    ctx.body()
    unit = lookup.unit(escalation["unit_id"])
    if escalation["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409)

    for other in derive.unit_escalations(unit["id"]):
        if other["id"] == escalation["id"] or other["status"] != "ACTIVE":
            continue
        if (escalation["effective_from"] <= other["effective_to"]
                and other["effective_from"] <= escalation["effective_to"]):
            raise ApiError("ERR_ESCALATION_WINDOW_OVERLAP", 409)

    ratio = derive.census_ratio_at_request(unit, escalation)
    tier = derive.tier_for_ratio(ratio)
    if tier is None:
        raise ApiError("ERR_SURGE_THRESHOLD_NOT_MET", 409)
    authorized = derive.authorized_beds_for(unit, escalation, tier)
    if authorized == 0:
        raise ApiError("ERR_SURGE_NO_STAFFED_CAPACITY", 422)

    escalation["census_ratio_at_request"] = ratio
    escalation["escalation_tier"] = tier
    escalation["staffing_waiver_ratio"] = derive.TIER_WAIVER[tier]
    escalation["authorized_beds"] = authorized
    escalation["status"] = "ACTIVE"
    escalation["authorized_by_user_id"] = caller.user_id
    touch(escalation)
    cascade.promote_queue(unit)
    touch(unit)
    return response.ok(serialize.escalation(escalation))


@bp.post("/surge-escalations/<escalation_id>/deny")
def deny_escalation(escalation_id):
    ctx.authenticate(["NetworkAdmin"])
    escalation = lookup.escalation(escalation_id)
    data = ctx.body()
    denial_reason = ctx.req_string(data, "denial_reason")
    if escalation["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    escalation["status"] = "DENIED"
    escalation["denial_reason"] = denial_reason
    touch(escalation)
    return response.ok(serialize.escalation(escalation))


@bp.post("/surge-escalations/<escalation_id>/stand-down")
def stand_down_escalation(escalation_id):
    caller = ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    escalation = lookup.escalation(escalation_id)
    ctx.require_scope(caller, escalation["unit_id"])
    ctx.body()
    if escalation["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409)
    escalation["status"] = "STOOD_DOWN"
    touch(escalation)
    unit = db.units.get(escalation["unit_id"])
    if unit is not None:
        touch(unit)
    return response.ok(serialize.escalation(escalation))


# --------------------------------------------------------------------------
# SurveillanceReport
# --------------------------------------------------------------------------
@bp.post("/surveillance-reports")
def create_report():
    caller = ctx.authenticate(["UnitDirector"])
    data = ctx.body()
    unit_id = ctx.req_string(data, "unit_id")
    period_start = ctx.req_dt(data, "period_start")
    period_end = ctx.req_dt(data, "period_end")
    patient_days = ctx.req_int(data, "reported_patient_days", minimum=0)
    line_days = ctx.req_int(data, "reported_central_line_days", minimum=0)
    if not period_end > period_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "period_end must be strictly after period_start.")
    unit = lookup.unit(unit_id)
    ctx.require_scope(caller, unit_id)
    if period_start < unit["created_at"]:
        raise ApiError("ERR_PERIOD_INVALID", 409)

    report = base_record()
    report.update({
        "unit_id": unit_id,
        "period_start": period_start,
        "period_end": period_end,
        "reported_patient_days": patient_days,
        "reported_central_line_days": line_days,
        "status": "DRAFT",
        "submitted_at": None,
        "submitted_by_user_id": None,
        "rejection_reason": None,
    })
    derive.compute_report_metrics(report)
    db.reports[report["id"]] = report
    return response.created(serialize.report(report))


@bp.get("/surveillance-reports")
def list_reports():
    ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    limit, offset = ctx.pagination()
    active = ctx.filters("unit_id", "status", "network_benchmark_flag",
                         "variant_applied")
    rows = ordered(db.reports.values())
    for field in ("unit_id", "status", "network_benchmark_flag", "variant_applied"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    return response.listing([serialize.report(r) for r in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/surveillance-reports/<report_id>")
def read_report(report_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    return response.ok(serialize.report(lookup.report(report_id)))


@bp.post("/surveillance-reports/<report_id>/submit")
def submit_report(report_id):
    caller = ctx.authenticate(["UnitDirector"])
    report = lookup.report(report_id)
    ctx.require_scope(caller, report["unit_id"])
    data = ctx.body()
    acknowledge = ctx.opt_bool(data, "acknowledge_incomplete", False)
    if report["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409)

    recomputed = dict(report)
    derive.compute_report_metrics(recomputed)
    if recomputed["data_completeness_flag"] != "COMPLETE" and not acknowledge:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A denominator is missing; pass acknowledge_incomplete to submit.")
    for field in METRIC_FIELDS:
        report[field] = recomputed[field]
    report["status"] = "SUBMITTED"
    report["submitted_at"] = clock.now()
    report["submitted_by_user_id"] = caller.user_id
    touch(report)
    return response.ok(serialize.report(report))


@bp.post("/surveillance-reports/<report_id>/accept")
def accept_report(report_id):
    caller = ctx.authenticate(["NetworkAdmin"])
    report = lookup.report(report_id)
    ctx.body()
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if caller.user_id == report.get("submitted_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)
    report["status"] = "ACCEPTED"
    touch(report)
    unit = db.units.get(report["unit_id"])
    if unit is not None and unit["quality_flag"] != report["network_benchmark_flag"]:
        unit["quality_flag"] = report["network_benchmark_flag"]
        touch(unit)
    return response.ok(serialize.report(report))


@bp.post("/surveillance-reports/<report_id>/reject")
def reject_report(report_id):
    ctx.authenticate(["NetworkAdmin"])
    report = lookup.report(report_id)
    data = ctx.body()
    rejection_reason = ctx.req_string(data, "rejection_reason")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    report["status"] = "REJECTED"
    report["rejection_reason"] = rejection_reason
    touch(report)
    return response.ok(serialize.report(report))


# --------------------------------------------------------------------------
# FollowUpEnrollment
# --------------------------------------------------------------------------
@bp.post("/follow-up-enrollments")
def create_enrollment():
    ctx.authenticate(["FollowUpCoordinator"])
    data = ctx.body()
    admission_id = ctx.req_string(data, "admission_id")
    clinic_unit_id = ctx.req_string(data, "clinic_unit_id")
    target = ctx.req_dt(data, "target_appointment_date")
    admission = lookup.admission(admission_id)
    clinic = lookup.unit(clinic_unit_id)

    if admission["care_status"] not in ("DISCHARGED", "TRANSFERRED"):
        raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                       "The admission is not closed.")
    basis = derive.eligibility_basis(admission)
    if basis == "NOT_ELIGIBLE":
        raise ApiError("ERR_NOT_ELIGIBLE_FOR_FOLLOWUP", 422)
    if (clinic["id"] != admission["unit_id"]
            and clinic["hospital_type"] != "COMMUNITY"):
        raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                       "The nominated clinic cannot run this follow-up.")
    for other in db.enrollments.values():
        if other["admission_id"] != admission["id"]:
            continue
        if other["status"] in ("ENROLLED", "SCHEDULED"):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", 409)

    discharged_at = admission["discharged_at"] or clock.now()
    enrollment = base_record()
    enrollment.update({
        "admission_id": admission["id"],
        "clinic_unit_id": clinic["id"],
        "target_appointment_date": target,
        "confirmed_appointment_date": None,
        "appointment_window_start": clock.plus_days(discharged_at, 14),
        "appointment_window_end": clock.plus_days(discharged_at, 90),
        "status": "ENROLLED",
        "attendance_recorded_at": None,
    })
    db.enrollments[enrollment["id"]] = enrollment
    return response.created(serialize.enrollment(enrollment))


@bp.get("/follow-up-enrollments")
def list_enrollments():
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "FollowUpCoordinator"])
    limit, offset = ctx.pagination()
    active = ctx.filters("admission_id", "clinic_unit_id", "status", "risk_tier",
                         "eligibility_basis")
    rows = ordered(db.enrollments.values())
    for field in ("admission_id", "clinic_unit_id", "status"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    if "eligibility_basis" in active or "risk_tier" in active:
        kept = []
        for row in rows:
            admission = db.admissions.get(row["admission_id"])
            basis = derive.eligibility_basis(admission) if admission else "NOT_ELIGIBLE"
            tier = derive.risk_tier(admission, basis) if admission else "MODERATE"
            if "eligibility_basis" in active and basis != active["eligibility_basis"]:
                continue
            if "risk_tier" in active and tier != active["risk_tier"]:
                continue
            kept.append(row)
        rows = kept
    return response.listing(
        [serialize.enrollment(r) for r in ctx.page(rows, limit, offset)],
        limit, offset, len(rows))


@bp.get("/follow-up-enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "FollowUpCoordinator"])
    return response.ok(serialize.enrollment(lookup.enrollment(enrollment_id)))


@bp.post("/follow-up-enrollments/<enrollment_id>/schedule")
def schedule_enrollment(enrollment_id):
    ctx.authenticate(["FollowUpCoordinator"])
    enrollment = lookup.enrollment(enrollment_id)
    data = ctx.body()
    confirmed = ctx.req_dt(data, "confirmed_appointment_date")
    if enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if not (enrollment["appointment_window_start"] <= confirmed
            <= enrollment["appointment_window_end"]):
        raise ApiError("ERR_APPOINTMENT_OUTSIDE_WINDOW", 409)
    clinic = db.units.get(enrollment["clinic_unit_id"])
    capacity = clinic["followup_clinic_daily_capacity"] if clinic else 0
    booked = derive.clinic_day_bookings(enrollment["clinic_unit_id"],
                                        clock.day_bucket(confirmed),
                                        exclude_enrollment_id=enrollment["id"])
    if booked >= capacity:
        raise ApiError("ERR_CLINIC_DAY_FULL", 409)
    enrollment["status"] = "SCHEDULED"
    enrollment["confirmed_appointment_date"] = confirmed
    touch(enrollment)
    return response.ok(serialize.enrollment(enrollment))


@bp.post("/follow-up-enrollments/<enrollment_id>/record-attendance")
def record_attendance(enrollment_id):
    ctx.authenticate(["FollowUpCoordinator"])
    enrollment = lookup.enrollment(enrollment_id)
    data = ctx.body()
    attended = ctx.req_bool(data, "attended")
    if enrollment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409)
    enrollment["status"] = "ATTENDED" if attended else "NO_SHOW"
    enrollment["attendance_recorded_at"] = clock.now()
    touch(enrollment)
    return response.ok(serialize.enrollment(enrollment))
