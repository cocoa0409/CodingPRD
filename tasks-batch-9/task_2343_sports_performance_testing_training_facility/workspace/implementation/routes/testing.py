"""Movement screens, performance batteries and their scoring (PRD 3.1 / 3.2)."""

from flask import Blueprint

import response
import serializers
from db import create, now_iso, ordered, parse_date, store, today, touch
from errors import ApiError
from middleware import (body_json, guard, pagination, query_enum, query_str,
                        resolve_acting_staff, slice_page, v_enum)
from routes.common import get_athlete, get_test_session
from services import calc, domain

bp = Blueprint("testing", __name__)

BATTERY_TYPES = ("MOVEMENT_SCREEN", "PERFORMANCE_BATTERY")
TEST_STATUSES = ("DRAFT", "FINALIZED")


def new_test_session(athlete_id, battery_type, staff_id, rts_plan_id=None):
    return create(
        store.test_sessions,
        {
            "athlete_id": athlete_id,
            "battery_type": battery_type,
            "administered_by_staff_id": staff_id,
            "rts_plan_id": rts_plan_id,
            "results": [],
            "result_count": 0,
            "status": "DRAFT",
            "age_years_at_test": None,
            "effective_age_years": None,
            "metric_percentiles": None,
            "composite_percentile": None,
            "risk_score": None,
            "asymmetry_points": None,
            "variant_applied": None,
            "finalized_at": None,
            "_norm_cohort": None,
        },
    )


@bp.post("/test-sessions")
def create_test_session():
    ctx = guard("Coach")
    staff = resolve_acting_staff(ctx)
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))
    battery_type = v_enum(body, "battery_type", BATTERY_TYPES)

    if athlete["membership_status"] == "SUSPENDED":
        raise ApiError("ERR_ATHLETE_SUSPENDED", "A suspended athlete may not be tested")
    if battery_type == "PERFORMANCE_BATTERY" and athlete["training_clearance"] == "SCREEN_PENDING":
        raise ApiError(
            "ERR_MOVEMENT_SCREEN_REQUIRED",
            "The intake movement screen must be finalized before a performance battery",
        )
    domain.credential_gate(staff)

    record = new_test_session(athlete["id"], battery_type, staff["id"])
    return response.created(serializers.test_session(record))


def _validate_results(body, battery_type):
    if "results" not in body or body["results"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "results is required")
    rows = body["results"]
    if not isinstance(rows, list):
        raise ApiError("ERR_INVALID_REQUEST", "results must be an array")
    if not rows:
        raise ApiError("ERR_INVALID_REQUEST", "results must hold at least one metric row")

    allowed = (
        calc.MOVEMENT_SCREEN_METRICS
        if battery_type == "MOVEMENT_SCREEN"
        else calc.PERFORMANCE_METRICS
    )
    cleaned = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each results row must be an object")
        code = row.get("metric_code")
        if not isinstance(code, str) or code not in allowed:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "metric_code must be one of %s" % ", ".join(allowed),
            )
        if code in seen:
            raise ApiError("ERR_INVALID_REQUEST", "metric_code %s is duplicated" % code)
        seen.add(code)
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "value must be a number for metric %s" % code)
        if battery_type == "MOVEMENT_SCREEN":
            if not isinstance(value, int) or value < 0 or value > calc.SCREEN_ITEM_MAX:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "movement screen values must be integers from 0 through 3",
                )
        side = row.get("side")
        if side is not None and not isinstance(side, str):
            raise ApiError("ERR_INVALID_REQUEST", "side must be a string when supplied")
        cleaned.append({"metric_code": code, "value": value, "side": side})

    if battery_type == "MOVEMENT_SCREEN" and seen != set(calc.MOVEMENT_SCREEN_METRICS):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "a movement screen must carry exactly the five screen metric codes",
        )
    return cleaned


@bp.post("/test-sessions/<test_session_id>/results")
def submit_results(test_session_id):
    ctx = guard("Coach")
    session = get_test_session(test_session_id)
    resolve_acting_staff(ctx)
    body = body_json()
    cleaned = _validate_results(body, session["battery_type"])
    if session["status"] != "DRAFT":
        raise ApiError("ERR_ALREADY_TERMINAL", "A finalized test session no longer accepts results")

    session["results"] = cleaned
    session["result_count"] = len(cleaned)
    touch(session)
    return response.ok(serializers.test_session(session))


def _finalize_screen(session, athlete):
    values = {row["metric_code"]: row["value"] for row in session["results"]}
    prior_screens = athlete["screen_count"]
    risk, asymmetry, variant, _multiplier = calc.movement_screen_risk(
        values, prior_screens, domain.active_rehab_count(athlete["id"])
    )
    session["risk_score"] = risk
    session["asymmetry_points"] = asymmetry
    session["variant_applied"] = variant

    athlete["injury_risk_score"] = risk
    athlete["screen_count"] = prior_screens + 1
    domain.apply_screen_clearance(athlete, risk)
    if prior_screens == 0 and athlete["membership_status"] == "PENDING_INTAKE":
        athlete["membership_status"] = "ACTIVE"
    touch(athlete)


def _finalize_battery(session, athlete):
    dob = parse_date(athlete["date_of_birth"])
    age_at_test = calc.age_years_from(dob, today())
    lookup_age, variant = calc.maturity_lookup_age(age_at_test, athlete["maturity_offset_months"])

    scored = []
    entries = []
    cohort = None
    for row in session["results"]:
        norm_row = calc.find_norm_row(
            athlete["sport"], athlete["position"], lookup_age, row["metric_code"]
        )
        if norm_row is None:
            continue
        percentile = calc.metric_percentile(row["value"], norm_row)
        label = calc.band_label(
            athlete["sport"], athlete["position"], (norm_row[2], norm_row[3])
        )
        if cohort is None:
            cohort = label
        scored.append((row["metric_code"], percentile))
        entries.append(
            {
                "metric_code": row["metric_code"],
                "percentile": percentile,
                "norm_band_matched": label,
            }
        )

    if not scored:
        raise ApiError(
            "ERR_NORM_BAND_UNAVAILABLE",
            "No normative band matches this athlete's sport, position and age for the submitted metrics",
        )

    composite = calc.composite_percentile(scored)
    session["age_years_at_test"] = age_at_test
    session["effective_age_years"] = lookup_age
    session["variant_applied"] = variant
    session["metric_percentiles"] = entries
    session["composite_percentile"] = composite
    session["_norm_cohort"] = cohort

    athlete["last_composite_percentile"] = composite
    athlete["last_performance_test_at"] = session["finalized_at"]
    athlete["next_test_due_on"] = domain.next_test_due_on(today())
    touch(athlete)


@bp.post("/test-sessions/<test_session_id>/finalize")
def finalize_test_session(test_session_id):
    ctx = guard("Coach")
    session = get_test_session(test_session_id)
    resolve_acting_staff(ctx)
    body_json()

    if session["status"] != "DRAFT":
        raise ApiError("ERR_ALREADY_TERMINAL", "This test session has already been finalized")
    if session["result_count"] < 1:
        raise ApiError("ERR_NO_TEST_RESULTS", "A test session with no result rows cannot be finalized")

    athlete = store.athletes.get(session["athlete_id"])
    session["finalized_at"] = now_iso()
    if session["battery_type"] == "MOVEMENT_SCREEN":
        _finalize_screen(session, athlete)
    else:
        _finalize_battery(session, athlete)
    session["status"] = "FINALIZED"
    touch(session)
    return response.ok(serializers.test_session(session))


@bp.get("/test-sessions/<test_session_id>")
def read_test_session(test_session_id):
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider", "Athlete", "Guardian")
    session = get_test_session(test_session_id)
    resolve_acting_staff(ctx)
    athlete = store.athletes.get(session["athlete_id"])
    if athlete is not None:
        domain.enforce_athlete_scope(ctx, athlete)
    return response.ok(serializers.test_session(session))


@bp.get("/test-sessions")
def list_test_sessions():
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    athlete_id = query_str("athlete_id")
    battery_type = query_enum("battery_type", BATTERY_TYPES)
    status = query_enum("status", TEST_STATUSES)
    staff_id = query_str("administered_by_staff_id")
    rts_plan_id = query_str("rts_plan_id")

    rows = ordered(store.test_sessions)
    if athlete_id:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if battery_type:
        rows = [r for r in rows if r["battery_type"] == battery_type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if staff_id:
        rows = [r for r in rows if r["administered_by_staff_id"] == staff_id]
    if rts_plan_id:
        rows = [r for r in rows if r["rts_plan_id"] == rts_plan_id]

    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.test_session(r) for r in page], limit, offset, total)
