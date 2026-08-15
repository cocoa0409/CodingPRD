"""ConservationProgram + FundingPool + PaymentScheduleRate + RankingCriterion."""
from flask import Blueprint

import serializers
from db import STORE, new_id
from errors import ApiError
from helpers import (
    apply_filters, as_dt, as_enum, as_int, as_list, as_num, as_str, body,
    get_pool, get_program, paginate, req_field, sorted_created, stamp_new, touch,
)
from middleware import ANY_ROLE, require_roles
from response import ok, ok_list
from services.calc import run_ranking_waterfall
from util import dec

bp = Blueprint("programs", __name__)

POOL_TYPES = {
    "GENERAL", "HU_BEGINNING_FARMER", "HU_SOCIALLY_DISADVANTAGED",
    "HU_LIMITED_RESOURCE", "HU_VETERAN",
}
PRACTICE_CODES = {
    "COVER_CROP", "PRESCRIBED_GRAZING", "WATERING_FACILITY", "FENCE",
    "NUTRIENT_MANAGEMENT",
}
UNITS = {"ACRE", "FOOT", "EACH"}


# ---------------- Programs ----------------

@bp.post("/eqip/programs")
@require_roles("ProgramAdmin")
def create_program(_uid, _role):
    data = body()
    program_name = as_str(req_field(data, "program_name"), "program_name")
    fiscal_year = as_int(req_field(data, "fiscal_year"), "fiscal_year")
    state_code = as_str(req_field(data, "state_code"), "state_code")
    window_start = as_dt(req_field(data, "window_start"), "window_start")
    window_end = as_dt(req_field(data, "window_end"), "window_end")
    if window_end < window_start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "window_end must not precede window_start")
    spot_check_modulus = data.get("spot_check_modulus", 5)
    spot_check_modulus = as_int(spot_check_modulus, "spot_check_modulus")
    if spot_check_modulus < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "spot_check_modulus must be >= 1")
    advance_cap_pct = data.get("advance_cap_pct", 0.5)
    advance_cap_pct = as_num(advance_cap_pct, "advance_cap_pct")
    if dec(advance_cap_pct) <= 0 or dec(advance_cap_pct) > 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "advance_cap_pct must be > 0 and <= 1")

    # Window overlap per state_code — closed intervals: touching windows conflict.
    for p in STORE.programs.values():
        if p["state_code"] != state_code:
            continue
        if window_start <= p["window_end"] and p["window_start"] <= window_end:
            raise ApiError(
                "ERR_WINDOW_OVERLAP", 409,
                "Application window overlaps another program for this state_code",
            )

    p = {
        "id": new_id(),
        "program_name": program_name,
        "fiscal_year": fiscal_year,
        "state_code": state_code,
        "window_start": window_start,
        "window_end": window_end,
        "spot_check_modulus": spot_check_modulus,
        "advance_cap_pct": advance_cap_pct,
        "status": "SETUP",
        "ranking_run_count": 0,
    }
    stamp_new(p)
    STORE.programs[p["id"]] = p
    return ok(serializers.program(p), 201)


@bp.get("/eqip/programs")
@require_roles(*ANY_ROLE)
def list_programs(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.programs.values()),
        [("state_code", "state_code"), ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.program(p) for p in page], meta)


@bp.get("/eqip/programs/<pid>")
@require_roles(*ANY_ROLE)
def get_one_program(pid, _uid, _role):
    return ok(serializers.program(get_program(pid)))


@bp.post("/eqip/programs/<pid>/open")
@require_roles("ProgramAdmin")
def open_program(pid, _uid, _role):
    p = get_program(pid)
    if p["status"] != "SETUP":
        raise ApiError("ERR_PROGRAM_NOT_IN_SETUP", 409, "open requires status SETUP")
    has_pool = any(x["program_id"] == pid for x in STORE.pools.values())
    has_rate = any(x["program_id"] == pid for x in STORE.rates.values())
    has_crit = any(x["program_id"] == pid for x in STORE.criteria.values())
    if not (has_pool and has_rate and has_crit):
        raise ApiError(
            "ERR_PROGRAM_INCOMPLETE_CONFIG", 409,
            "open requires at least one pool, one rate and one ranking criterion",
        )
    p["status"] = "OPEN"
    touch(p)
    return ok(serializers.program(p))


@bp.post("/eqip/programs/<pid>/close")
@require_roles("ProgramAdmin")
def close_program(pid, _uid, _role):
    p = get_program(pid)
    if p["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN", 409, "close requires status OPEN")
    p["status"] = "CLOSED"
    touch(p)
    return ok(serializers.program(p))


@bp.post("/eqip/programs/<pid>/run-ranking")
@require_roles("ProgramAdmin")
def run_ranking(pid, _uid, _role):
    p = get_program(pid)
    if p["status"] != "CLOSED":
        raise ApiError("ERR_PROGRAM_NOT_CLOSED", 409, "run-ranking requires status CLOSED")
    if p["ranking_run_count"] != 0:
        raise ApiError("ERR_RANKING_ALREADY_RUN", 409, "ranking has already been run")
    result = run_ranking_waterfall(p)
    return ok(result)


# ---------------- Funding pools ----------------

@bp.post("/eqip/programs/<pid>/pools")
@require_roles("ProgramAdmin")
def create_pool(pid, _uid, _role):
    p = get_program(pid)
    if p["status"] != "SETUP":
        raise ApiError("ERR_PROGRAM_NOT_IN_SETUP", 409, "pool creation requires program SETUP")
    data = body()
    pool_type = as_enum(req_field(data, "pool_type"), "pool_type", POOL_TYPES)
    allocated = as_int(req_field(data, "allocated_cents"), "allocated_cents")
    if allocated < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "allocated_cents must be >= 1")
    pool = {
        "id": new_id(),
        "program_id": pid,
        "pool_type": pool_type,
        "allocated_cents": allocated,
        "obligated_cents": 0,
        "paid_cents": 0,
    }
    stamp_new(pool)
    STORE.pools[pool["id"]] = pool
    return ok(serializers.pool(pool), 201)


@bp.get("/eqip/programs/<pid>/pools")
@require_roles(*ANY_ROLE)
def list_pools(pid, _uid, _role):
    get_program(pid)
    items = [x for x in sorted_created(STORE.pools.values()) if x["program_id"] == pid]
    items = apply_filters(items, [("pool_type", "pool_type")])
    page, meta = paginate(items)
    return ok_list([serializers.pool(x) for x in page], meta)


@bp.get("/eqip/pools/<pid>")
@require_roles(*ANY_ROLE)
def get_one_pool(pid, _uid, _role):
    return ok(serializers.pool(get_pool(pid)))


# ---------------- Payment schedule rates ----------------

@bp.post("/eqip/programs/<pid>/rates")
@require_roles("ProgramAdmin")
def create_rate(pid, _uid, _role):
    p = get_program(pid)
    if p["status"] != "SETUP":
        raise ApiError("ERR_PROGRAM_NOT_IN_SETUP", 409, "rate creation requires program SETUP")
    data = body()
    practice_code = as_enum(req_field(data, "practice_code"), "practice_code", PRACTICE_CODES)
    unit = as_enum(req_field(data, "unit"), "unit", UNITS)
    standard = as_int(req_field(data, "standard_rate_cents"), "standard_rate_cents")
    hu = as_int(req_field(data, "hu_rate_cents"), "hu_rate_cents")
    lifespan = as_int(req_field(data, "lifespan_years"), "lifespan_years")
    if standard < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "standard_rate_cents must be >= 1")
    if hu < standard:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hu_rate_cents must be >= standard_rate_cents")
    if lifespan < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "lifespan_years must be >= 1")
    for r in STORE.rates.values():
        if r["program_id"] == pid and r["practice_code"] == practice_code:
            raise ApiError(
                "ERR_DUPLICATE_RATE", 409,
                "A rate for this practice_code already exists in the program",
            )
    r = {
        "id": new_id(),
        "program_id": pid,
        "practice_code": practice_code,
        "unit": unit,
        "standard_rate_cents": standard,
        "hu_rate_cents": hu,
        "lifespan_years": lifespan,
        "_common_fields": False,
    }
    stamp_new(r)
    STORE.rates[r["id"]] = r
    return ok(serializers.rate(r), 201)


@bp.get("/eqip/programs/<pid>/rates")
@require_roles(*ANY_ROLE)
def list_rates(pid, _uid, _role):
    get_program(pid)
    items = [x for x in sorted_created(STORE.rates.values()) if x["program_id"] == pid]
    items = apply_filters(items, [("practice_code", "practice_code")])
    page, meta = paginate(items)
    return ok_list([serializers.rate(x) for x in page], meta)


# ---------------- Ranking criteria ----------------

@bp.post("/eqip/programs/<pid>/ranking-criteria")
@require_roles("ProgramAdmin")
def create_criterion(pid, _uid, _role):
    p = get_program(pid)
    if p["status"] != "SETUP":
        raise ApiError("ERR_PROGRAM_NOT_IN_SETUP", 409, "criterion creation requires program SETUP")
    data = body()
    criterion_code = as_str(req_field(data, "criterion_code"), "criterion_code")
    weight = as_num(req_field(data, "weight"), "weight")
    max_points = as_int(req_field(data, "max_points"), "max_points")
    if dec(weight) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight must be > 0")
    if max_points < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "max_points must be >= 1")
    for c in STORE.criteria.values():
        if c["program_id"] == pid and c["criterion_code"] == criterion_code:
            raise ApiError(
                "ERR_DUPLICATE_CRITERION", 409,
                "A criterion with this criterion_code already exists in the program",
            )
    c = {
        "id": new_id(),
        "program_id": pid,
        "criterion_code": criterion_code,
        "weight": weight,
        "max_points": max_points,
        "_common_fields": False,
    }
    stamp_new(c)
    STORE.criteria[c["id"]] = c
    return ok(serializers.criterion(c), 201)


@bp.get("/eqip/programs/<pid>/ranking-criteria")
@require_roles(*ANY_ROLE)
def list_criteria(pid, _uid, _role):
    get_program(pid)
    items = [x for x in sorted_created(STORE.criteria.values()) if x["program_id"] == pid]
    page, meta = paginate(items)
    return ok_list([serializers.criterion(x) for x in page], meta)
