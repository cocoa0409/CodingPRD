"""Chronic-care enrollment, periodicity, visits and the lapse cycle."""

from flask import Blueprint, request

import calc
import serializers
import store
from constants import (
    CHRONIC_MISSED_ESCALATION_COUNT, CONDITION_CODE, SEVERITY, TIER_ESCALATION_STEP,
    TIER_PERIODICITY_DAYS, VISIT_OUTCOME,
)
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx

bp = Blueprint("chronic", __name__)


def intake_gate(ctx):
    """Rung 11: an OVERDUE RECEIVING screening blocks downstream clinical ordering."""
    def check():
        if ctx.inmate is None:
            return
        for row in store.intake_screenings.values():
            if (row["inmate_id"] == ctx.inmate["id"]
                    and row["screening_type"] == "RECEIVING"
                    and row["status"] == "OVERDUE"):
                raise ApiError("ERR_INTAKE_SCREENING_OVERDUE",
                               "an overdue receiving screening gates this operation")
    ctx.safety(check)


@bp.post("/inmates/<inmate_id>/chronic-care-enrollments")
def enrol(inmate_id):
    ctx = Ctx(roles=("Provider",))
    ctx.path_inmate(inmate_id)
    ctx.freeze_gate()
    ctx.custody_gate()
    ctx.require("condition_code", "severity")
    ctx.enum("condition_code", CONDITION_CODE)
    ctx.enum("severity", SEVERITY)
    intake_gate(ctx)

    def unique_active():
        for row in store.chronic_enrollments.values():
            if (row["inmate_id"] == inmate_id
                    and row["condition_code"] == ctx.body.get("condition_code")
                    and row["status"] == "ACTIVE"):
                raise ApiError("ERR_DUPLICATE_KEY",
                               "an ACTIVE enrollment already exists for this condition")
    ctx.caps(unique_active)
    ctx.run()

    tier, periodicity = calc.chronic_tier_assignment(ctx.body["severity"])
    row = store.base_row()
    row.update({
        "inmate_id": inmate_id,
        "condition_code": ctx.body["condition_code"],
        "severity": ctx.body["severity"],
        "tier": tier,
        "periodicity_days": periodicity,
        "enrolled_at": store.now(),
        "last_visit_at": None,
        "missed_visit_count": 0,
        "status": "ACTIVE",
        "escalated": False,
    })
    row["next_due_date"] = calc.chronic_next_due_date(row)
    store.chronic_enrollments[row["id"]] = row
    return created(serializers.chronic_enrollment(row))


@bp.get("/inmates/<inmate_id>/chronic-care-enrollments")
def list_enrollments(inmate_id):
    ctx = Ctx(roles=("Provider", "Nurse", "HealthServicesAdmin"))
    ctx.path_inmate(inmate_id)
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [e for e in store.chronic_enrollments.values() if e["inmate_id"] == inmate_id]
    if request.args.get("status"):
        rows = [e for e in rows if e["status"] == request.args["status"]]
    if request.args.get("condition_code"):
        rows = [e for e in rows if e["condition_code"] == request.args["condition_code"]]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.chronic_enrollment, rows), limit, offset)


@bp.get("/chronic-care-enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    ctx = Ctx(roles=("Provider", "Nurse", "HealthServicesAdmin"))
    ctx.need("enrollment", store.chronic_enrollments, enrollment_id, "ERR_RECORD_NOT_FOUND")
    ctx.run()
    return ok(serializers.chronic_enrollment(ctx.row("enrollment")))


@bp.post("/chronic-care-enrollments/<enrollment_id>/re-enroll")
def re_enroll(enrollment_id):
    ctx = Ctx(roles=("Provider",))

    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need("enrollment", store.chronic_enrollments, enrollment_id,
             "ERR_RECORD_NOT_FOUND", on_found=bind)
    ctx.freeze_gate()
    ctx.custody_gate()
    ctx.require("severity")
    ctx.enum("severity", SEVERITY)
    ctx.status_in(lambda: ctx.row("enrollment"), ("LAPSED",))
    ctx.run()

    row = ctx.row("enrollment")
    tier, periodicity = calc.chronic_tier_assignment(ctx.body["severity"])
    row.update({
        "severity": ctx.body["severity"],
        "tier": tier,
        "periodicity_days": periodicity,
        "status": "ACTIVE",
        "enrolled_at": store.now(),
        "last_visit_at": None,
        "missed_visit_count": 0,
        "escalated": False,
    })
    row["next_due_date"] = calc.chronic_next_due_date(row)
    store.touch(row)
    return ok(serializers.chronic_enrollment(row))


@bp.post("/chronic-care-enrollments/<enrollment_id>/visits")
def record_visit(enrollment_id):
    ctx = Ctx(roles=("Nurse",))

    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need("enrollment", store.chronic_enrollments, enrollment_id,
             "ERR_RECORD_NOT_FOUND", on_found=bind)
    ctx.freeze_gate()
    ctx.require("outcome")
    ctx.enum("outcome", VISIT_OUTCOME)
    ctx.status_in(lambda: ctx.row("enrollment"), ("ACTIVE",))
    ctx.run()

    enrollment = ctx.row("enrollment")
    outcome = ctx.body["outcome"]

    visit = store.base_row(with_version=False)
    visit.update({
        "enrollment_id": enrollment["id"],
        "recorded_at": store.now(),
        "outcome": outcome,
        "due_at_snapshot": enrollment.get("next_due_date"),
        "recorded_by_user_id": ctx.user_id,
    })
    store.chronic_visits[visit["id"]] = visit

    if outcome == "COMPLETED":
        enrollment["last_visit_at"] = store.now()
        enrollment["missed_visit_count"] = 0
        enrollment["next_due_date"] = calc.chronic_next_due_date(enrollment)
    elif outcome == "MISSED":
        enrollment["missed_visit_count"] += 1
        if (enrollment["missed_visit_count"] >= CHRONIC_MISSED_ESCALATION_COUNT
                and not enrollment["escalated"]):
            enrollment["tier"] = TIER_ESCALATION_STEP[enrollment["tier"]]
            enrollment["periodicity_days"] = TIER_PERIODICITY_DAYS[enrollment["tier"]]
            enrollment["escalated"] = True
            enrollment["next_due_date"] = calc.chronic_next_due_date(enrollment)
    # REFUSED changes no counter and does not move next_due_date.

    store.touch(enrollment)
    return created(serializers.chronic_visit(visit))


@bp.get("/chronic-care-enrollments/<enrollment_id>/visits")
def list_visits(enrollment_id):
    ctx = Ctx(roles=("Nurse", "Provider", "HealthServicesAdmin"))
    ctx.need("enrollment", store.chronic_enrollments, enrollment_id, "ERR_RECORD_NOT_FOUND")
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [v for v in store.chronic_visits.values() if v["enrollment_id"] == enrollment_id]
    if request.args.get("outcome"):
        rows = [v for v in rows if v["outcome"] == request.args["outcome"]]
    rows = store.sort_rows(rows, key="recorded_at")
    return listing(serializers.many(serializers.chronic_visit, rows), limit, offset)
