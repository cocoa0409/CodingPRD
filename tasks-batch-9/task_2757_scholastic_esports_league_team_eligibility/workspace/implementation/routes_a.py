"""Districts, schools, coaches, titles and the logical clock."""

import re

from flask import Blueprint

from errors import fail
from guards import owns
from http_util import (
    created,
    endpoint,
    listing,
    ok,
    opt_date,
    opt_dt,
    opt_enum,
    opt_int,
    opt_num,
    opt_str,
    req_dt,
    req_enum,
    req_str,
)
from serialize import dump
from store import db, dec, find, must_find, new_record, parse_date, touch

bp = Blueprint("routes_a", __name__)

ALL_ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
    "Recruiter",
)
RATINGS = ("E", "E10", "T", "M")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------------------
# districts
# ---------------------------------------------------------------------------
@bp.post("/districts")
@endpoint("LeagueAdmin")
def create_district(ctx):
    body = ctx.body
    name = req_str(body, "name", 1, 120)
    state_code = req_str(body, "state_code")
    if not STATE_CODE_RE.match(state_code):
        fail("ERR_INVALID_REQUEST", "Field 'state_code' must be exactly two uppercase letters.")
    max_age_rating = opt_enum(body, "max_age_rating", RATINGS, "T")
    basis = opt_enum(
        body, "academic_standing_basis", ("TERM_SNAPSHOT", "ROLLING_CUMULATIVE"), "TERM_SNAPSHOT"
    )
    min_gpa = opt_num(body, "min_gpa", dec("2.000"), low=0, high=4, places=3)
    floor_gpa = opt_num(body, "probation_gpa_floor", dec("1.750"), low=0, high=4, places=3)
    dispute_window_hours = opt_int(body, "dispute_window_hours", 48, low=1, high=336)
    subsidy_pct = opt_num(body, "subsidy_pct", dec("0.250"), low=0, high=1, places=3)
    pool = opt_int(body, "subsidy_pool_cents", 5000000, low=0)
    dead_start = opt_dt(body, "recruiting_dead_period_start")
    dead_end = opt_dt(body, "recruiting_dead_period_end")
    cap = opt_int(body, "recruiting_contact_cap_per_window", 3, low=1, high=50)
    window_days = opt_int(body, "recruiting_window_days", 30, low=1, high=365)
    buffer_minutes = opt_int(body, "broadcast_buffer_minutes", 15, low=0, high=240)
    if dec(floor_gpa) > dec(min_gpa):
        fail(
            "ERR_INVALID_GPA_THRESHOLDS",
            "probation_gpa_floor may not exceed min_gpa.",
        )
    district = new_record(
        "district",
        name=name,
        state_code=state_code,
        max_age_rating=max_age_rating,
        academic_standing_basis=basis,
        min_gpa=dec(min_gpa),
        probation_gpa_floor=dec(floor_gpa),
        dispute_window_hours=dispute_window_hours,
        subsidy_pct=dec(subsidy_pct),
        subsidy_pool_cents=pool,
        subsidy_pool_initial_cents=pool,
        recruiting_dead_period_start=dead_start,
        recruiting_dead_period_end=dead_end,
        recruiting_contact_cap_per_window=cap,
        recruiting_window_days=window_days,
        broadcast_buffer_minutes=buffer_minutes,
    )
    return created(dump(district))


@bp.get("/districts/<district_id>")
@endpoint(*ALL_ROLES)
def read_district(ctx, district_id):
    return ok(dump(must_find("district", district_id)))


@bp.get("/districts")
@endpoint("LeagueAdmin", "DistrictAdmin", "EligibilityOfficer", "IntegrityOfficer", "Recruiter")
def list_districts(ctx):
    return listing("district", ("state_code",), dump)


# ---------------------------------------------------------------------------
# schools
# ---------------------------------------------------------------------------
@bp.post("/schools")
@endpoint("LeagueAdmin", "DistrictAdmin")
def create_school(ctx):
    body = ctx.body
    district_id = req_str(body, "district_id")
    name = req_str(body, "name", 1, 120)
    nces_code = req_str(body, "nces_code", 1, 24)
    verified_through = opt_date(body, "enrollment_verified_through", parse_date("2027-06-30"))
    capacity = opt_int(body, "concurrent_broadcast_capacity", 1, low=1, high=4)
    district = find("district", district_id)
    if district is None:
        fail("ERR_DISTRICT_NOT_FOUND", "No district with that identifier exists.")
    for school in db.all("school"):
        if school["district_id"] == district_id and school["nces_code"] == nces_code:
            fail("ERR_DUPLICATE_NCES_CODE", "That NCES code is already used in this district.")
    school = new_record(
        "school",
        district_id=district_id,
        name=name,
        nces_code=nces_code,
        enrollment_verified_through=verified_through,
        concurrent_broadcast_capacity=capacity,
        status="ACTIVE",
    )
    return created(dump(school))


@bp.get("/schools/<school_id>")
@endpoint(*ALL_ROLES)
def read_school(ctx, school_id):
    return ok(dump(must_find("school", school_id)))


@bp.get("/schools")
@endpoint(
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "EligibilityOfficer",
    "IntegrityOfficer",
    "Recruiter",
)
def list_schools(ctx):
    return listing("school", ("district_id", "status"), dump)


# ---------------------------------------------------------------------------
# coaches
# ---------------------------------------------------------------------------
@bp.post("/coaches")
@endpoint("LeagueAdmin", "AthleticDirector")
def create_coach(ctx):
    body = ctx.body
    school_id = req_str(body, "school_id")
    full_name = req_str(body, "full_name", 1, 120)
    email = req_str(body, "email")
    if "@" not in email:
        fail("ERR_INVALID_REQUEST", "Field 'email' must contain an at-sign.")
    if find("school", school_id) is None:
        fail("ERR_SCHOOL_NOT_FOUND", "No school with that identifier exists.")
    coach = new_record(
        "coach",
        school_id=school_id,
        full_name=full_name,
        email=email,
        certification_status="PENDING",
        background_check_expires_on=None,
        certified_at=None,
    )
    return created(dump(coach))


@bp.get("/coaches/<coach_id>")
@endpoint(
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
)
def read_coach(ctx, coach_id):
    return ok(dump(must_find("coach", coach_id)))


@bp.get("/coaches")
@endpoint(
    "LeagueAdmin", "DistrictAdmin", "AthleticDirector", "EligibilityOfficer", "IntegrityOfficer"
)
def list_coaches(ctx):
    return listing("coach", ("school_id", "certification_status"), dump)


@bp.post("/coaches/<coach_id>/certification")
@endpoint("AthleticDirector", "LeagueAdmin")
def certify_coach(ctx, coach_id):
    existing = find("coach", coach_id)
    if existing is not None:
        owns(ctx, "AthleticDirector", existing.get("school_id"))
    coach = must_find("coach", coach_id)
    action = req_enum(ctx.body, "action", ("CERTIFY", "SUSPEND"))
    expires_on = opt_date(ctx.body, "background_check_expires_on")
    if action == "CERTIFY":
        coach["certification_status"] = "CERTIFIED"
        if expires_on is not None:
            coach["background_check_expires_on"] = expires_on
        coach["certified_at"] = db.now
    else:
        coach["certification_status"] = "SUSPENDED"
    touch(coach)
    return ok(dump(coach))


# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------
@bp.post("/titles")
@endpoint("LeagueAdmin")
def create_title(ctx):
    body = ctx.body
    name = req_str(body, "name", 1, 120)
    publisher = req_str(body, "publisher")
    age_rating = opt_enum(body, "age_rating", RATINGS, "T")
    min_player_age = opt_int(body, "min_player_age", 13, low=6, high=21)
    server_pool_id = opt_str(body, "server_pool_id", "POOL-DEFAULT")
    server_pool_capacity = opt_int(body, "server_pool_capacity", 1, low=1, high=8)
    duration = opt_int(body, "match_duration_minutes", 60, low=15, high=240)
    for title in db.all("title"):
        if title["name"] == name:
            fail("ERR_DUPLICATE_TITLE_NAME", "That title name is already in the catalogue.")
    title = new_record(
        "title",
        name=name,
        publisher=publisher,
        age_rating=age_rating,
        min_player_age=min_player_age,
        server_pool_id=server_pool_id,
        server_pool_capacity=server_pool_capacity,
        match_duration_minutes=duration,
    )
    return created(dump(title))


@bp.get("/titles/<title_id>")
@endpoint(
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
)
def read_title(ctx, title_id):
    return ok(dump(must_find("title", title_id)))


@bp.get("/titles")
@endpoint(
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
)
def list_titles(ctx):
    return listing("title", ("age_rating", "server_pool_id"), dump)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint("LeagueAdmin")
def set_clock(ctx):
    current_utc = req_dt(ctx.body, "current_utc")
    if current_utc < db.now:
        fail("ERR_CLOCK_REWIND_FORBIDDEN", "The logical clock never moves backwards.")
    db.set_clock(current_utc)
    return ok({})
