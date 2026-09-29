"""Students, title approvals and seasons."""

from flask import Blueprint

import domain
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
    req_enum,
    req_int,
    req_num,
    req_str,
)
from serialize import dump
from store import db, dec, find, must_find, new_record, parse_date, parse_datetime, touch

bp = Blueprint("routes_b", __name__)

ALL_ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
    "Recruiter",
)
READ_ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "EligibilityOfficer",
    "IntegrityOfficer",
    "Recruiter",
)

SEASON_STAGES = (
    "DRAFT",
    "REGISTRATION_OPEN",
    "ROSTER_LOCKED",
    "REGULAR_SEASON",
    "PLAYOFFS",
    "COMPLETE",
)
PREVIOUS_STAGE = dict(
    (SEASON_STAGES[i], SEASON_STAGES[i - 1]) for i in range(1, len(SEASON_STAGES))
)
BASES = ("MATCH_POINT_BASIS", "WIN_PERCENTAGE_BASIS")


# ---------------------------------------------------------------------------
# students
# ---------------------------------------------------------------------------
@bp.post("/students")
@endpoint("LeagueAdmin", "AthleticDirector", "EligibilityOfficer")
def create_student(ctx):
    body = ctx.body
    school_id = req_str(body, "school_id")
    full_name = req_str(body, "full_name", 1, 120)
    birthdate = req_str(body, "birthdate")
    birthdate_value = parse_date(birthdate)
    if birthdate_value is None:
        fail("ERR_INVALID_REQUEST", "Field 'birthdate' must be a date in YYYY-MM-DD form.")
    grade_level = req_int(body, "grade_level", low=9, high=12)
    enrollment_status = opt_enum(
        body, "enrollment_status", ("ENROLLED", "WITHDRAWN", "GRADUATED"), "ENROLLED"
    )
    credits = opt_num(body, "credits_completed", 0, low=0)
    if find("school", school_id) is None:
        fail("ERR_SCHOOL_NOT_FOUND", "No school with that identifier exists.")
    student = new_record(
        "student",
        school_id=school_id,
        full_name=full_name,
        birthdate=birthdate_value,
        grade_level=grade_level,
        enrollment_status=enrollment_status,
        credits_completed=credits,
        latest_term_label=None,
        latest_term_gpa=None,
        latest_term_credits=None,
        prior_term_gpa=None,
        prior_term_credits=None,
        effective_gpa=None,
        academic_standing="UNEVALUATED",
        standing_basis_applied=None,
        fair_play_status="CLEAR",
        showcase_status="NONE",
        nominating_team_id=None,
        award_tier="NONE",
        provisional_award_cents=0,
        scholarship_award_cents=0,
        scholarship_award_state="NONE",
        recruiting_contact_log=[],
    )
    return created(dump(student))


@bp.get("/students/<student_id>")
@endpoint(*ALL_ROLES)
def read_student(ctx, student_id):
    return ok(dump(must_find("student", student_id)))


@bp.get("/students")
@endpoint(*READ_ROLES)
def list_students(ctx):
    return listing(
        "student",
        ("school_id", "nominating_team_id", "academic_standing", "showcase_status"),
        dump,
    )


@bp.post("/students/<student_id>/academic-postings")
@endpoint("EligibilityOfficer", "LeagueAdmin")
def post_academic_term(ctx, student_id):
    student = must_find("student", student_id)
    body = ctx.body
    term_label = req_str(body, "term_label", 1, 120)
    term_gpa = req_num(body, "term_gpa", low=0, high=4, places=3)
    term_credits = req_num(body, "term_credits")
    if dec(term_credits) <= 0:
        fail("ERR_INVALID_REQUEST", "Field 'term_credits' must be greater than zero.")
    expected = req_int(body, "expected_student_version")
    if expected != student["version"]:
        fail("ERR_STALE_VERSION", "The supplied expected_student_version is not current.")
    domain.update(
        student,
        prior_term_gpa=student.get("latest_term_gpa"),
        prior_term_credits=student.get("latest_term_credits"),
        latest_term_gpa=dec(term_gpa),
        latest_term_credits=term_credits,
        latest_term_label=term_label,
    )
    touch(student)
    _, standing, _ = domain.apply_standing(student)
    if standing == "INELIGIBLE":
        teams = []
        for slot in domain.slots_of_student(student["id"]):
            team = find("team", slot["team_id"])
            if (
                slot.get("academic_status") == "PENDING"
                and team is not None
                and team["status"] in ("DRAFT", "REGISTERED")
            ):
                domain.update(slot, academic_status="BLOCKED", ineligibility_reason="ACADEMIC")
                domain.reconcile_slot(slot)
                if team not in teams:
                    teams.append(team)
        for team in teams:
            domain.recompute_team_rollups(team)
    return ok(dump(student))


@bp.post("/students/<student_id>/showcase-nomination")
@endpoint("LeagueAdmin")
def nominate_student(ctx, student_id):
    student = must_find("student", student_id)
    team_id = req_str(ctx.body, "nominating_team_id")
    team = find("team", team_id)
    if team is None:
        fail("ERR_TEAM_NOT_FOUND", "No team with that identifier exists.")
    if student.get("fair_play_status") != "CLEAR":
        fail("ERR_STUDENT_FAIR_PLAY_SANCTIONED", "The student is under a fair-play sanction.")
    on_team = [
        s
        for s in domain.slots_of_student(student["id"])
        if s["team_id"] == team_id and s["participation_status"] != "RELEASED"
    ]
    if not on_team:
        fail("ERR_STUDENT_NOT_ON_TEAM", "The student holds no live slot on the nominating team.")
    if student.get("showcase_status") != "NONE":
        fail("ERR_ALREADY_NOMINATED", "The student has already been nominated.")
    provisional, tier, final = domain.project_scholarship(student, team)
    domain.update(
        student,
        showcase_status="NOMINATED",
        nominating_team_id=team_id,
        provisional_award_cents=provisional,
        award_tier=tier,
        scholarship_award_cents=final,
        scholarship_award_state="CURRENT",
    )
    touch(student)
    return ok(dump(student))


@bp.post("/students/<student_id>/recruiting-contacts")
@endpoint("Recruiter")
def log_recruiting_contact(ctx, student_id):
    student = must_find("student", student_id)
    org_code = req_str(ctx.body, "org_code")
    channel = req_str(ctx.body, "channel")
    purpose = req_str(ctx.body, "purpose")
    district = domain.district_of_student(student)
    now = db.now
    if district is not None:
        start = district.get("recruiting_dead_period_start")
        end = district.get("recruiting_dead_period_end")
        if start is not None and end is not None and start <= now <= end:
            fail("ERR_RECRUITING_DEAD_PERIOD", "The district is inside its recruiting dead period.")
    if student.get("showcase_status") != "NOMINATED":
        fail("ERR_SHOWCASE_NOT_NOMINATED", "The student is not on the showcase pathway.")
    if district is not None:
        window_start = now - _days(district["recruiting_window_days"])
        in_window = [
            e for e in student["recruiting_contact_log"] if e["contacted_at"] > window_start
        ]
        if len(in_window) >= district["recruiting_contact_cap_per_window"]:
            fail(
                "ERR_RECRUITING_CONTACT_CAP_EXCEEDED",
                "The rolling recruiting-contact cap for this student is exhausted.",
            )
    student["recruiting_contact_log"] = list(student["recruiting_contact_log"]) + [
        {"contacted_at": now, "org_code": org_code, "channel": channel, "purpose": purpose}
    ]
    touch(student)
    return ok(dump(student))


def _days(count):
    import datetime as _dt

    return _dt.timedelta(days=count)


# ---------------------------------------------------------------------------
# title approvals
# ---------------------------------------------------------------------------
@bp.post("/title-approvals")
@endpoint("AthleticDirector", "LeagueAdmin")
def create_title_approval(ctx):
    body = ctx.body
    requested_by = body.get("requested_by_school_id")
    if isinstance(requested_by, str):
        owns(ctx, "AthleticDirector", requested_by)
    district_id = req_str(body, "district_id")
    title_id = req_str(body, "title_id")
    school_id = req_str(body, "requested_by_school_id")
    if find("district", district_id) is None:
        fail("ERR_DISTRICT_NOT_FOUND", "No district with that identifier exists.")
    if find("title", title_id) is None:
        fail("ERR_TITLE_NOT_FOUND", "No title with that identifier exists.")
    if find("school", school_id) is None:
        fail("ERR_SCHOOL_NOT_FOUND", "No school with that identifier exists.")
    if domain.live_approval(district_id, title_id) is not None:
        fail(
            "ERR_DUPLICATE_TITLE_APPROVAL",
            "A pending or approved approval already exists for that district and title.",
        )
    approval = new_record(
        "title_approval",
        district_id=district_id,
        title_id=title_id,
        requested_by_school_id=school_id,
        status="PENDING",
        decided_by_user_id=None,
        decided_at=None,
        decision_note=None,
    )
    return created(dump(approval))


@bp.get("/title-approvals/<approval_id>")
@endpoint("LeagueAdmin", "DistrictAdmin", "AthleticDirector", "Coach")
def read_title_approval(ctx, approval_id):
    return ok(dump(must_find("title_approval", approval_id)))


@bp.get("/title-approvals")
@endpoint("LeagueAdmin", "DistrictAdmin", "AthleticDirector", "Coach")
def list_title_approvals(ctx):
    return listing(
        "title_approval",
        ("district_id", "title_id", "requested_by_school_id", "status"),
        dump,
    )


@bp.post("/title-approvals/<approval_id>/decision")
@endpoint("DistrictAdmin")
def decide_title_approval(ctx, approval_id):
    existing = find("title_approval", approval_id)
    if existing is not None:
        owns(ctx, "DistrictAdmin", existing.get("district_id"))
    approval = must_find("title_approval", approval_id)
    action = req_enum(ctx.body, "action", ("APPROVE", "DENY", "REVOKE"))
    note = opt_str(ctx.body, "decision_note", None, 1, 500)
    required = "APPROVED" if action == "REVOKE" else "PENDING"
    if approval["status"] != required:
        fail("ERR_INVALID_APPROVAL_STATE", "The approval is not in a state that permits that action.")
    if action == "APPROVE":
        district = find("district", approval["district_id"])
        title = find("title", approval["title_id"])
        ceiling = domain.RATING_ORDINAL.get(district["max_age_rating"], 3) if district else 3
        rating = domain.RATING_ORDINAL.get(title["age_rating"], 0) if title else 0
        if rating > ceiling:
            fail(
                "ERR_TITLE_AGE_RATING_EXCEEDS_DISTRICT_CEILING",
                "The title's age rating exceeds the district's ceiling.",
            )
    approval["status"] = {"APPROVE": "APPROVED", "DENY": "DENIED", "REVOKE": "REVOKED"}[action]
    approval["decided_by_user_id"] = ctx.user_id
    approval["decided_at"] = db.now
    if note is not None:
        approval["decision_note"] = note
    touch(approval)
    return ok(dump(approval))


# ---------------------------------------------------------------------------
# seasons
# ---------------------------------------------------------------------------
@bp.post("/seasons")
@endpoint("LeagueAdmin")
def create_season(ctx):
    body = ctx.body
    title_id = req_str(body, "title_id")
    name = req_str(body, "name", 1, 120)
    division = opt_enum(body, "division", ("VARSITY", "JV"), "VARSITY")
    opens_at = opt_dt(body, "registration_opens_at", parse_datetime("2026-08-01T00:00:00.000Z"))
    closes_at = opt_dt(body, "registration_closes_at", parse_datetime("2026-09-15T23:59:59.999Z"))
    roster_lock_at = opt_dt(body, "roster_lock_at", parse_datetime("2026-09-20T00:00:00.000Z"))
    season_end_at = opt_dt(
        body, "regular_season_end_at", parse_datetime("2026-11-30T00:00:00.000Z")
    )
    age_cutoff_date = opt_date(body, "age_cutoff_date", parse_date("2026-09-01"))
    max_age = opt_int(body, "max_age", 19, low=14, high=25)
    min_starters = opt_int(body, "min_starters", 1, low=1, high=5)
    max_starters = opt_int(body, "max_starters", 3, low=1, high=8)
    base_fee = opt_int(body, "base_entry_fee_cents", 12510, low=0)
    starter_fee = opt_int(body, "per_starter_fee_cents", 3335, low=0)
    seeding_basis = opt_enum(body, "seeding_basis", BASES, "MATCH_POINT_BASIS")
    playoff_slots = opt_int(body, "playoff_slots", 2, low=1, high=16)
    if find("title", title_id) is None:
        fail("ERR_TITLE_NOT_FOUND", "No title with that identifier exists.")
    season = new_record(
        "season",
        title_id=title_id,
        name=name,
        division=division,
        registration_opens_at=opens_at,
        registration_closes_at=closes_at,
        roster_lock_at=roster_lock_at,
        regular_season_end_at=season_end_at,
        age_cutoff_date=age_cutoff_date,
        max_age=max_age,
        min_starters=min_starters,
        max_starters=max_starters,
        base_entry_fee_cents=base_fee,
        per_starter_fee_cents=starter_fee,
        seeding_basis=seeding_basis,
        seeding_basis_applied=None,
        playoff_slots=playoff_slots,
        status="DRAFT",
        seeding_state="UNSEEDED",
        seed_order=[],
        registered_team_count=0,
        match_point_pool=0,
    )
    return created(dump(season))


@bp.get("/seasons/<season_id>")
@endpoint(*ALL_ROLES)
def read_season(ctx, season_id):
    return ok(dump(must_find("season", season_id)))


@bp.get("/seasons")
@endpoint(*ALL_ROLES)
def list_seasons(ctx):
    return listing("season", ("title_id", "status", "division"), dump)


@bp.post("/seasons/<season_id>/advance")
@endpoint("LeagueAdmin")
def advance_season(ctx, season_id):
    season = must_find("season", season_id)
    to_status = req_enum(ctx.body, "to_status", SEASON_STAGES[1:])
    if season["status"] != PREVIOUS_STAGE[to_status]:
        fail(
            "ERR_INVALID_SEASON_STAGE",
            "The season is not in the stage that precedes %s." % to_status,
        )
    teams = domain.teams_of_season(season["id"])
    if to_status == "ROSTER_LOCKED":
        locked = [t for t in teams if t["status"] == "ROSTER_LOCKED"]
        if len(locked) < 2:
            fail(
                "ERR_INVALID_SEASON_STAGE",
                "At least two teams must have locked their rosters.",
            )
    if to_status == "PLAYOFFS" and season["seeding_state"] != "SEEDED":
        fail("ERR_SEASON_SEEDING_NOT_CURRENT", "The seed order is not current.")
    if to_status == "COMPLETE":
        outstanding = [
            m
            for m in domain.matches_of_season(season["id"])
            if m["play_status"] not in ("FINALIZED", "FORFEITED")
        ]
        if outstanding:
            fail("ERR_INVALID_SEASON_STAGE", "Every match must be finalized or forfeited.")
    season["status"] = to_status
    touch(season)
    if to_status == "REGULAR_SEASON":
        for team in teams:
            if team["status"] == "ROSTER_LOCKED":
                domain.update(team, status="COMPETING")
    return ok(dump(season))


@bp.post("/seasons/<season_id>/seeding")
@endpoint("LeagueAdmin")
def run_season_seeding(ctx, season_id):
    season = must_find("season", season_id)
    basis_override = opt_enum(ctx.body, "basis_override", BASES)
    if season["status"] not in ("REGULAR_SEASON", "PLAYOFFS"):
        fail("ERR_INVALID_SEASON_STAGE", "Seeding runs only during the regular season or playoffs.")
    if not domain.eligible_seed_teams(season):
        fail("ERR_SEED_ORDER_EMPTY", "No team in this season is eligible for seeding.")
    domain.run_seeding(season, basis_override or season["seeding_basis"])
    return ok(dump(season))
