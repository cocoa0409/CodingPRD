"""Athlete intake, membership administration and progress reporting."""

from flask import Blueprint

import db
import response
import serializers
from db import create, now_iso, ordered, store, today, touch
from errors import ApiError
from middleware import (body_json, guard, pagination, query_str, query_enum,
                        resolve_acting_staff, slice_page, v_date, v_enum,
                        v_int, v_string)
from routes.common import get_athlete, get_injury_record, require_state
from services import calc, domain

bp = Blueprint("athletes", __name__)

SPORTS = ("BASKETBALL", "SOCCER", "BASEBALL", "VOLLEYBALL", "TRACK")
MEMBERSHIP_STATUSES = ("PENDING_INTAKE", "ACTIVE", "SUSPENDED")
CLEARANCES = ("SCREEN_PENDING", "CLEARED", "RESTRICTED", "MEDICAL_HOLD")
BODY_REGIONS = ("KNEE", "SHOULDER", "ANKLE", "HIP", "LUMBAR", "ELBOW")
SEVERITIES = ("MILD", "MODERATE", "SEVERE")
INJURY_STATUSES = ("ACTIVE_REHAB", "RESOLVED")

ALL_ROLES = (
    "PerformanceDirector",
    "Coach",
    "MedicalProvider",
    "FrontDesk",
    "Athlete",
    "Guardian",
)
OPERATOR_ROLES = ("PerformanceDirector", "Coach", "MedicalProvider", "FrontDesk")


# ------------------------------------------------------------------ athletes ----
@bp.post("/athletes")
def create_athlete():
    ctx = guard("FrontDesk", "PerformanceDirector")
    resolve_acting_staff(ctx)
    body = body_json()

    full_name = v_string(body, "full_name", min_len=1, max_len=120)
    dob = v_date(body, "date_of_birth")
    if dob >= today():
        raise ApiError(
            "ERR_INVALID_REQUEST", "date_of_birth must fall strictly before the current logical date"
        )
    sport = v_enum(body, "sport", SPORTS)
    position = v_string(body, "position", min_len=1, max_len=40)
    guardian_email = v_string(body, "guardian_email", required=False, max_len=200)
    maturity_offset_months = v_int(
        body, "maturity_offset_months", required=False, minimum=-36, maximum=36, default=0
    )

    age_years = calc.age_years_from(dob, today())
    if age_years < 18 and not guardian_email:
        raise ApiError(
            "ERR_INVALID_REQUEST", "guardian_email is required for an athlete under 18 years old"
        )

    record = create(
        store.athletes,
        {
            "full_name": full_name,
            "date_of_birth": dob.isoformat(),
            "sport": sport,
            "position": position,
            "guardian_email": guardian_email,
            "maturity_offset_months": maturity_offset_months,
            "team_contract_id": None,
            "membership_status": "PENDING_INTAKE",
            "training_clearance": "SCREEN_PENDING",
            "injury_risk_score": None,
            "screen_count": 0,
            "last_composite_percentile": None,
            "last_performance_test_at": None,
            "next_test_due_on": None,
            "attended_count": 0,
            "no_show_count": 0,
            "no_show_strikes": 0,
        },
    )
    return response.created(serializers.athlete(record))


@bp.get("/athletes/<athlete_id>")
def read_athlete(athlete_id):
    ctx = guard(*ALL_ROLES)
    athlete = get_athlete(athlete_id)
    resolve_acting_staff(ctx)
    domain.enforce_athlete_scope(ctx, athlete)
    return response.ok(serializers.athlete(athlete))


@bp.get("/athletes")
def list_athletes():
    ctx = guard(*OPERATOR_ROLES)
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    sport = query_enum("sport", SPORTS)
    membership_status = query_enum("membership_status", MEMBERSHIP_STATUSES)
    training_clearance = query_enum("training_clearance", CLEARANCES)
    team_contract_id = query_str("team_contract_id")

    rows = ordered(store.athletes)
    if sport:
        rows = [r for r in rows if r["sport"] == sport]
    if membership_status:
        rows = [r for r in rows if r["membership_status"] == membership_status]
    if training_clearance:
        rows = [r for r in rows if r["training_clearance"] == training_clearance]
    if team_contract_id:
        rows = [r for r in rows if r["team_contract_id"] == team_contract_id]

    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.athlete(r) for r in page], limit, offset, total)


@bp.post("/athletes/<athlete_id>/suspend")
def suspend_athlete(athlete_id):
    guard("PerformanceDirector")
    athlete = get_athlete(athlete_id)
    body_json()
    require_state(athlete, "membership_status", ("ACTIVE",), (), "Athlete")
    domain.suspend_athlete(athlete)
    return response.ok(serializers.athlete(athlete))


@bp.post("/athletes/<athlete_id>/reinstate")
def reinstate_athlete(athlete_id):
    guard("PerformanceDirector")
    athlete = get_athlete(athlete_id)
    body_json()
    require_state(athlete, "membership_status", ("SUSPENDED",), (), "Athlete")
    athlete["membership_status"] = "ACTIVE"
    athlete["no_show_strikes"] = 0
    touch(athlete)
    return response.ok(serializers.athlete(athlete))


@bp.post("/athletes/<athlete_id>/medical-hold")
def medical_hold(athlete_id):
    guard("MedicalProvider")
    athlete = get_athlete(athlete_id)
    body_json()
    require_state(athlete, "training_clearance", ("CLEARED", "RESTRICTED"), (), "Athlete")
    domain.place_on_medical_hold(athlete)
    domain.recompute_athlete_sessions(athlete)
    return response.ok(serializers.athlete(athlete))


@bp.get("/athletes/<athlete_id>/progress-report")
def progress_report(athlete_id):
    ctx = guard("PerformanceDirector", "Coach", "Athlete", "Guardian")
    athlete = get_athlete(athlete_id)
    resolve_acting_staff(ctx)
    domain.enforce_athlete_scope(ctx, athlete)

    finalized = domain.finalized_batteries(athlete_id)
    current = finalized[0]["composite_percentile"] if finalized else None
    previous = finalized[1]["composite_percentile"] if len(finalized) > 1 else None
    delta = None
    if current is not None and previous is not None:
        delta = calc.rhu(calc.D(current) - calc.D(previous), 1)

    cohort = None
    if finalized:
        cohort = finalized[0].get("_norm_cohort")

    fee_total = 0
    for enrollment in store.enrollments.values():
        if enrollment["athlete_id"] == athlete_id and enrollment["status"] == "NO_SHOW":
            fee_total += enrollment["no_show_fee_cents"] or 0

    next_due = athlete["next_test_due_on"]
    overdue = False
    if next_due is not None:
        overdue = today() > db.parse_date(next_due)

    return response.ok(
        {
            "athlete_id": athlete_id,
            "composite_percentile_current": calc.as_float(current),
            "composite_percentile_previous": calc.as_float(previous),
            "delta_percentile_points": calc.as_float(delta),
            "tests_included_count": len(finalized),
            "normative_cohort": cohort,
            "readiness_index": calc.as_float(domain.athlete_readiness(athlete)),
            "attendance_rate_pct": calc.as_float(
                calc.attendance_rate_pct(athlete["attended_count"], athlete["no_show_count"])
            ),
            "no_show_fee_total_cents": fee_total,
            "test_overdue": overdue,
            "next_test_due_on": next_due,
        }
    )


# ------------------------------------------------------------ injury records ----
@bp.post("/injury-records")
def create_injury_record():
    ctx = guard("MedicalProvider", "PerformanceDirector")
    resolve_acting_staff(ctx)
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))

    body_region = v_enum(body, "body_region", BODY_REGIONS)
    severity = v_enum(body, "severity", SEVERITIES)
    occurred_on = v_date(body, "occurred_on")
    if occurred_on > today():
        raise ApiError("ERR_INVALID_REQUEST", "occurred_on may not be later than the current logical date")
    rts_required = body.get("rts_required", False)
    if rts_required is None:
        rts_required = False
    if not isinstance(rts_required, bool):
        raise ApiError("ERR_INVALID_REQUEST", "rts_required must be a boolean")

    record = create(
        store.injury_records,
        {
            "athlete_id": athlete["id"],
            "body_region": body_region,
            "severity": severity,
            "occurred_on": occurred_on.isoformat(),
            "rts_required": rts_required,
            "status": "ACTIVE_REHAB",
        },
    )
    return response.created(serializers.injury_record(record))


@bp.get("/injury-records/<injury_record_id>")
def read_injury_record(injury_record_id):
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider", "Athlete", "Guardian")
    record = get_injury_record(injury_record_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.injury_record(record))


@bp.get("/injury-records")
def list_injury_records():
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    athlete_id = query_str("athlete_id")
    status = query_enum("status", INJURY_STATUSES)

    rows = ordered(store.injury_records)
    if athlete_id:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.injury_record(r) for r in page], limit, offset, total)


@bp.post("/injury-records/<injury_record_id>/resolve")
def resolve_injury_record(injury_record_id):
    guard("MedicalProvider")
    record = get_injury_record(injury_record_id)
    body_json()
    require_state(record, "status", ("ACTIVE_REHAB",), (), "InjuryRecord")
    record["status"] = "RESOLVED"
    touch(record)
    return response.ok(serializers.injury_record(record))
