"""Outfall inventory, dry-weather screening, sweeping runs and load assessment."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, fmt_instant, new_row, touch
from errors import ApiError
from middleware import (
    body,
    get_bool,
    get_date,
    get_enum,
    get_int,
    get_number,
    get_str,
    get_datetime,
    require,
)
from response import object_response
from routes.common import find, listing, one, require_active, settle, snapshot
from services import calc, derive
from services.calc import D

bp = Blueprint("outfalls", __name__)

READERS = mw.OPERATIONAL_ROLES

INDICATOR_FIELDS = (
    "indicator_bacteria_mpn",
    "indicator_surfactant_mg_per_l",
    "indicator_ammonia_mg_per_l",
)
SAMPLE_FIELDS = ("pollutant_concentration_mg_per_l", "runoff_volume_kl")


@bp.post("/outfalls")
def create_outfall():
    require([mw.MANAGER, mw.OPS])
    payload = body()
    term_id = get_str(payload, "permit_term_id")
    code = get_str(payload, "outfall_code", min_len=1, max_len=32)
    receiving_water = get_str(payload, "receiving_water")
    drainage = get_number(payload, "drainage_area_acres", exclusive_minimum=0)
    tier = get_enum(payload, "priority_tier", enums.PRIORITY_TIER)
    baseline = get_number(payload, "baseline_concentration_mg_per_l", minimum=0)
    design = get_number(payload, "design_runoff_kl", minimum=0)
    capacity = get_number(
        payload, "sweeping_capacity_lane_miles_per_month", required=False, default=D(0), minimum=0
    )

    term = find("permit_terms", term_id)
    for existing in derive.outfalls_of_term(term["id"]):
        if existing["outfall_code"] == code:
            raise ApiError("ERR_DUPLICATE_OUTFALL_CODE")

    row = new_row(
        {
            "permit_term_id": term["id"],
            "outfall_code": code,
            "receiving_water": receiving_water,
            "drainage_area_acres": calc.num(drainage, 2),
            "priority_tier": tier,
            "baseline_concentration_mg_per_l": calc.num(baseline, 2),
            "design_runoff_kl": calc.num(design, 2),
            "sweeping_capacity_lane_miles_per_month": calc.num(capacity, 2),
            "sweeping_runs": [],
            "swept_lane_miles_ytd": 0.00,
            "screening_status": "NOT_SCREENED",
            "last_screened_at": None,
            "screening_count": 0,
            "open_case_count": 0,
            "tmdl_status": "NOT_ASSESSED",
            "last_assessed_gross_load_lb": 0.00,
            "last_assessed_credit_lb": 0.00,
            "last_assessed_net_load_lb": 0.00,
            "last_assessed_year": None,
            "status": "ACTIVE",
        }
    )
    DB.outfalls[row["id"]] = row
    return one(row, 201)


@bp.get("/outfalls/<outfall_id>")
def read_outfall(outfall_id):
    require(READERS)
    return one(find("outfalls", outfall_id))


@bp.post("/outfalls/<outfall_id>/retire")
def retire_outfall(outfall_id):
    require([mw.MANAGER])
    outfall = find("outfalls", outfall_id)
    if outfall["status"] != "ACTIVE":
        raise ApiError("ERR_OUTFALL_RETIRED")
    if int(outfall.get("open_case_count") or 0) != 0:
        raise ApiError("ERR_OUTFALL_HAS_OPEN_CASES")

    term = derive.term_of_outfall(outfall)
    before = snapshot(term)
    outfall["status"] = "RETIRED"
    touch(outfall)
    settle(term, before, CLOCK.now())
    return one(outfall)


def _forbid(payload, fields, kind):
    for field in fields:
        if field in payload and payload[field] is not None:
            raise ApiError(
                "ERR_OBSERVATION_TYPE_FIELDS_INVALID",
                "%s must not carry %s." % (kind, field),
            )


@bp.post("/outfalls/<outfall_id>/observations")
def create_observation(outfall_id):
    user_id, _role = require([mw.IDDE, mw.OPS])
    payload = body()
    obs_type = get_enum(payload, "observation_type", enums.OBSERVATION_TYPE)
    observed_at, observed_text = get_datetime(payload, "observed_at")
    flow_present = get_bool(payload, "dry_weather_flow_present", required=False, default=None)
    bacteria = get_number(payload, "indicator_bacteria_mpn", required=False, default=None, minimum=0)
    surfactant = get_number(
        payload, "indicator_surfactant_mg_per_l", required=False, default=None, minimum=0
    )
    ammonia = get_number(
        payload, "indicator_ammonia_mg_per_l", required=False, default=None, minimum=0
    )
    concentration = get_number(
        payload, "pollutant_concentration_mg_per_l", required=False, default=None, minimum=0
    )
    volume = get_number(payload, "runoff_volume_kl", required=False, default=None, minimum=0)
    notes = get_str(payload, "field_notes", required=False, default=None, min_len=None)

    outfall = find("outfalls", outfall_id)
    if outfall["status"] != "ACTIVE":
        raise ApiError("ERR_OUTFALL_RETIRED")
    term = derive.term_of_outfall(outfall)
    require_active(term)

    if obs_type == "DRY_WEATHER_SCREENING":
        if flow_present is None:
            raise ApiError(
                "ERR_OBSERVATION_TYPE_FIELDS_INVALID",
                "A dry-weather screening requires dry_weather_flow_present.",
            )
        _forbid(payload, SAMPLE_FIELDS, "A dry-weather screening")
    else:
        if concentration is None or volume is None:
            raise ApiError(
                "ERR_OBSERVATION_TYPE_FIELDS_INVALID",
                "A wet-weather sample requires pollutant_concentration_mg_per_l "
                "and runoff_volume_kl.",
            )
        _forbid(payload, INDICATOR_FIELDS, "A wet-weather sample")

    if obs_type == "DRY_WEATHER_SCREENING":
        for other in derive.observations_of_outfall(outfall["id"]):
            if other["observation_type"] != "DRY_WEATHER_SCREENING":
                continue
            other_at = derive.to_dt(other["observed_at"])
            if other_at is None:
                continue
            if abs(other_at - observed_at) < calc.SCREENING_BUFFER:
                raise ApiError("ERR_SCREENING_INTERVAL_VIOLATION")

    stamp = fmt_instant(observed_at)
    row = new_row(
        {
            "outfall_id": outfall["id"],
            "observation_type": obs_type,
            "observed_at": stamp,
            "dry_weather_flow_present": flow_present,
            "indicator_bacteria_mpn": None if bacteria is None else calc.num(bacteria, 2),
            "indicator_surfactant_mg_per_l": None if surfactant is None else calc.num(surfactant, 2),
            "indicator_ammonia_mg_per_l": None if ammonia is None else calc.num(ammonia, 2),
            "pollutant_concentration_mg_per_l": (
                None if concentration is None else calc.num(concentration, 2)
            ),
            "runoff_volume_kl": None if volume is None else calc.num(volume, 2),
            "field_notes": notes,
            "screening_result": None,
            "sample_load_lb": None,
            "validation_status": "PENDING",
            "validated_at": None,
            "recorded_by_user_id": user_id,
        }
    )
    if obs_type == "DRY_WEATHER_SCREENING":
        row["screening_result"] = calc.screening_result(flow_present, bacteria, surfactant, ammonia)
        row["validation_status"] = "NOT_APPLICABLE"
    else:
        row["sample_load_lb"] = calc.sample_load(concentration, volume)
    DB.observations[row["id"]] = row

    before = snapshot(term)
    if row["screening_result"] == "SUSPECT":
        case = new_row(
            {
                "outfall_id": outfall["id"],
                "origin_observation_id": row["id"],
                "status": "OPEN",
                "opened_at": CLOCK.stamp(),
                "trace_method": None,
                "tracing_attempt_count": 0,
                "reopen_count": 0,
                "source_description": None,
                "responsible_party": None,
                "enforcement_action_count": 0,
                "resolved_at": None,
                "resolution_note": None,
            }
        )
        DB.cases[case["id"]] = case

    settle(term, before, observed_at)
    return one(row, 201)


@bp.get("/outfalls/<outfall_id>/observations")
def list_observations(outfall_id):
    require(READERS)
    spec = {
        "observation_type": ("observation_type", enums.OBSERVATION_TYPE),
        "validation_status": ("validation_status", enums.VALIDATION_STATUS),
        "screening_result": ("screening_result", enums.SCREENING_RESULT),
    }
    return listing(
        spec,
        lambda: derive.observations_of_outfall(find("outfalls", outfall_id)["id"]),
    )


@bp.post("/outfalls/<outfall_id>/sweeping-runs")
def append_sweeping_run(outfall_id):
    require([mw.OPS])
    payload = body()
    run_start = get_date(payload, "run_start_date")
    run_end = get_date(payload, "run_end_date")
    if run_end < run_start:
        raise ApiError("ERR_VALIDATION", "run_end_date must not precede run_start_date.")
    lane_miles = get_number(payload, "lane_miles_swept", minimum=0)

    outfall = find("outfalls", outfall_id)
    if outfall["status"] != "ACTIVE":
        raise ApiError("ERR_OUTFALL_RETIRED")
    term = derive.term_of_outfall(outfall)
    require_active(term)

    for run in outfall.get("sweeping_runs", []):
        other_start = calc.date.fromisoformat(run["run_start_date"])
        other_end = calc.date.fromisoformat(run["run_end_date"])
        if run_start < other_end and other_start < run_end:
            raise ApiError("ERR_SWEEPING_RUN_OVERLAP")

    month_total = D(lane_miles)
    for run in outfall.get("sweeping_runs", []):
        other_start = calc.date.fromisoformat(run["run_start_date"])
        if (other_start.year, other_start.month) == (run_start.year, run_start.month):
            month_total += D(run["lane_miles_swept"])
    if month_total > D(outfall.get("sweeping_capacity_lane_miles_per_month") or 0):
        raise ApiError("ERR_SWEEPING_CAPACITY_EXCEEDED")

    before = snapshot(term)
    outfall["sweeping_runs"].append(
        {
            "run_start_date": run_start.isoformat(),
            "run_end_date": run_end.isoformat(),
            "lane_miles_swept": calc.num(lane_miles, 2),
        }
    )
    touch(outfall)
    settle(term, before, CLOCK.now())
    return one(outfall)


@bp.post("/outfalls/<outfall_id>/load-assessments")
def assess_load(outfall_id):
    require([mw.MANAGER, mw.OPS])
    payload = body()
    variant = get_enum(payload, "variant", enums.LOAD_VARIANT)
    year = get_int(payload, "reporting_year", minimum=1900, maximum=9999)

    outfall = find("outfalls", outfall_id)
    if outfall["status"] != "ACTIVE":
        raise ApiError("ERR_OUTFALL_RETIRED")
    term = derive.term_of_outfall(outfall)

    validated = [
        o
        for o in derive.observations_of_outfall(outfall["id"])
        if o["observation_type"] == "WET_WEATHER_SAMPLE"
        and o["validation_status"] == "VALIDATED"
        and derive.to_dt(o["observed_at"]) is not None
        and derive.to_dt(o["observed_at"]).year == year
    ]
    validated.sort(key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))
    taken = sum((D(o["sample_load_lb"]) for o in validated), D(0))
    shortfall = max(calc.REQUIRED_SAMPLES_PER_YEAR - len(validated), 0)
    if variant == "PROVISIONAL":
        unit = calc.projected_unit_load(
            outfall["baseline_concentration_mg_per_l"], outfall["design_runoff_kl"]
        )
        taken = taken + D(shortfall) * unit
        projected = shortfall
    else:
        projected = 0
    gross = calc.rhu(taken, 2)

    lane_miles = D(0)
    for run in outfall.get("sweeping_runs", []):
        if calc.date.fromisoformat(run["run_start_date"]).year == year:
            lane_miles += D(run["lane_miles_swept"])
    credit = calc.sweeping_credit(lane_miles, gross)
    net = calc.rhu(gross - credit, 2)
    status = calc.tmdl_status(term or {}, net)

    if variant == "FINAL":
        before = snapshot(term)
        outfall["tmdl_status"] = status
        outfall["last_assessed_gross_load_lb"] = float(gross)
        outfall["last_assessed_credit_lb"] = float(credit)
        outfall["last_assessed_net_load_lb"] = float(net)
        outfall["last_assessed_year"] = year
        touch(outfall)
        settle(term, before, CLOCK.now())

    return object_response(
        {
            "variant": variant,
            "reporting_year": year,
            "validated_sample_count": len(validated),
            "projected_sample_count": projected,
            "gross_load_lb": float(gross),
            "sweeping_credit_lb": float(credit),
            "net_load_lb": float(net),
            "tmdl_status": status,
        }
    )
