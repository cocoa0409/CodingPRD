"""Teams and roster slots."""

from decimal import Decimal

from flask import Blueprint

import domain
from errors import fail
from guards import coach_owns_team, director_owns_team, owns
from http_util import (
    created,
    endpoint,
    listing,
    ok,
    opt_enum,
    opt_str,
    req_date,
    req_str,
)
from serialize import dump
from store import clock_date, completed_years, db, find, must_find, new_record, touch

bp = Blueprint("routes_c", __name__)

ALL_ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
    "Recruiter",
)
SLOT_READ_ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
)
WITHDRAWABLE = (
    "REGISTERED",
    "ROSTER_LOCKED",
    "COMPETING",
    "SUSPENDED",
    "PLAYOFF_SEEDED",
    "ELIMINATED",
)


def _recount_registered(season):
    if season is None:
        return
    count = len(
        [
            t
            for t in domain.teams_of_season(season["id"])
            if t["status"] not in ("DRAFT", "WITHDRAWN")
        ]
    )
    domain.update(season, registered_team_count=count)


def _require_coach_ready(coach):
    if coach is None or coach.get("certification_status") != "CERTIFIED":
        fail("ERR_COACH_NOT_CERTIFIED", "The governing coach is not certified.")
    expires_on = coach.get("background_check_expires_on")
    if expires_on is None or expires_on < clock_date():
        fail(
            "ERR_COACH_BACKGROUND_CHECK_EXPIRED",
            "The governing coach's background check has lapsed.",
        )


# ---------------------------------------------------------------------------
# teams
# ---------------------------------------------------------------------------
@bp.post("/teams")
@endpoint("Coach", "AthleticDirector")
def create_team(ctx):
    body = ctx.body
    if isinstance(body.get("coach_id"), str):
        owns(ctx, "Coach", body["coach_id"])
    if isinstance(body.get("school_id"), str):
        owns(ctx, "AthleticDirector", body["school_id"])
    season_id = req_str(body, "season_id")
    school_id = req_str(body, "school_id")
    title_id = req_str(body, "title_id")
    coach_id = req_str(body, "coach_id")
    name = req_str(body, "name", 1, 120)
    season = find("season", season_id)
    if season is None:
        fail("ERR_SEASON_NOT_FOUND", "No season with that identifier exists.")
    if find("school", school_id) is None:
        fail("ERR_SCHOOL_NOT_FOUND", "No school with that identifier exists.")
    if find("title", title_id) is None:
        fail("ERR_TITLE_NOT_FOUND", "No title with that identifier exists.")
    coach = find("coach", coach_id)
    if coach is None:
        fail("ERR_COACH_NOT_FOUND", "No coach with that identifier exists.")
    if coach["school_id"] != school_id:
        fail("ERR_COACH_SCHOOL_MISMATCH", "The designated coach belongs to a different school.")
    if title_id != season["title_id"]:
        fail("ERR_TEAM_TITLE_MISMATCH", "The team's title is not the season's title.")
    for team in domain.teams_of_season(season_id):
        if team["name"] == name:
            fail("ERR_DUPLICATE_TEAM_NAME", "That team name is already used in this season.")
    team = new_record(
        "team",
        season_id=season_id,
        school_id=school_id,
        title_id=title_id,
        coach_id=coach_id,
        name=name,
        status="DRAFT",
        registered_at=None,
        roster_locked_at=None,
        starter_slots_used=0,
        starter_slots_available=season["max_starters"],
        active_starter_count=0,
        entry_fee_cents=0,
        subsidy_granted_cents=0,
        net_fee_due_cents=0,
        match_points=0,
        wins=0,
        losses=0,
        draws=0,
        forfeits_charged=0,
        forfeit_wins=0,
        games_won=0,
        games_lost=0,
        game_differential=0,
        seed_points=Decimal("0.0000"),
        seed_position=None,
        seed_stale=False,
        integrity_score=Decimal("100.00"),
        suspension_reason=None,
    )
    return created(dump(team))


@bp.get("/teams/<team_id>")
@endpoint(*ALL_ROLES)
def read_team(ctx, team_id):
    return ok(dump(must_find("team", team_id)))


@bp.get("/teams")
@endpoint(*ALL_ROLES)
def list_teams(ctx):
    return listing("team", ("season_id", "school_id", "title_id", "coach_id", "status"), dump)


@bp.post("/teams/<team_id>/register")
@endpoint("Coach")
def register_team(ctx, team_id):
    coach_owns_team(ctx, find("team", team_id))
    team = must_find("team", team_id)
    season = domain.season_of(team)
    if season is None or season["status"] != "REGISTRATION_OPEN":
        fail("ERR_INVALID_SEASON_STAGE", "The season is not open for registration.")
    if team["status"] != "DRAFT":
        fail("ERR_INVALID_TEAM_STATE", "Only a draft team may register.")
    _require_coach_ready(find("coach", team["coach_id"]))
    district = domain.district_of_team(team)
    if district is None or domain.approved_approval(district["id"], team["title_id"]) is None:
        fail("ERR_TITLE_NOT_DISTRICT_APPROVED", "The title is not approved in the team's district.")
    now = db.now
    if now < season["registration_opens_at"] or now > season["registration_closes_at"]:
        fail("ERR_REGISTRATION_WINDOW_CLOSED", "The registration window is not open.")
    if team["active_starter_count"] < season["min_starters"]:
        fail("ERR_ROSTER_MINIMUM_NOT_MET", "The team has too few active starters to register.")
    entry, subsidy, net = domain.compute_entry_fee(team, season, district)
    if district["subsidy_pool_cents"] < subsidy:
        fail("ERR_SUBSIDY_POOL_EXHAUSTED", "The district subsidy pool cannot cover this grant.")
    domain.update(district, subsidy_pool_cents=district["subsidy_pool_cents"] - subsidy)
    team["entry_fee_cents"] = entry
    team["subsidy_granted_cents"] = subsidy
    team["net_fee_due_cents"] = net
    team["registered_at"] = db.now
    team["status"] = "REGISTERED"
    touch(team)
    _recount_registered(season)
    return ok(dump(team))


@bp.post("/teams/<team_id>/roster-lock")
@endpoint("Coach")
def lock_team_roster(ctx, team_id):
    coach_owns_team(ctx, find("team", team_id))
    team = must_find("team", team_id)
    season = domain.season_of(team)
    if team["status"] != "REGISTERED":
        fail("ERR_INVALID_TEAM_STATE", "Only a registered team may lock its roster.")
    if season is not None and db.now > season["roster_lock_at"]:
        fail("ERR_ROSTER_LOCK_DEADLINE_PASSED", "The roster-lock deadline has passed.")
    if season is not None and team["active_starter_count"] < season["min_starters"]:
        fail("ERR_ROSTER_MINIMUM_NOT_MET", "The team has too few active starters to lock.")
    team["roster_locked_at"] = db.now
    team["status"] = "ROSTER_LOCKED"
    touch(team)
    return ok(dump(team))


@bp.post("/teams/<team_id>/withdraw")
@endpoint("AthleticDirector")
def withdraw_team(ctx, team_id):
    director_owns_team(ctx, find("team", team_id))
    team = must_find("team", team_id)
    opt_str(ctx.body, "withdrawal_note", None, 1, 500)
    if team["status"] not in WITHDRAWABLE:
        fail("ERR_INVALID_TEAM_STATE", "The team is not in a state that permits withdrawal.")
    season = domain.season_of(team)
    district = domain.district_of_team(team)
    granted = team["subsidy_granted_cents"]
    if district is not None and granted:
        domain.update(district, subsidy_pool_cents=district["subsidy_pool_cents"] + granted)
    team["subsidy_granted_cents"] = 0
    team["net_fee_due_cents"] = 0
    team["status"] = "WITHDRAWN"
    touch(team)
    domain.release_all_slots(team)
    domain.forfeit_unplayed_for_team(team, {"type": "WITHDRAWAL", "team_id": team["id"]})
    _recount_registered(season)
    domain.mark_seeding_stale(season, [team])
    return ok(dump(team))


# ---------------------------------------------------------------------------
# roster slots
# ---------------------------------------------------------------------------
@bp.post("/roster-slots")
@endpoint("Coach")
def create_roster_slot(ctx):
    body = ctx.body
    if isinstance(body.get("team_id"), str):
        coach_owns_team(ctx, find("team", body["team_id"]))
    team_id = req_str(body, "team_id")
    student_id = req_str(body, "student_id")
    slot_role = opt_enum(body, "slot_role", ("STARTER", "SUB"), "STARTER")
    team = find("team", team_id)
    if team is None:
        fail("ERR_TEAM_NOT_FOUND", "No team with that identifier exists.")
    student = find("student", student_id)
    if student is None:
        fail("ERR_STUDENT_NOT_FOUND", "No student with that identifier exists.")
    if team["status"] not in ("DRAFT", "REGISTERED"):
        fail("ERR_ROSTER_LOCKED", "The team's roster is no longer open for changes.")
    if student["enrollment_status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
    if student["fair_play_status"] != "CLEAR":
        fail("ERR_STUDENT_FAIR_PLAY_SANCTIONED", "The student is under a fair-play sanction.")
    if student["school_id"] != team["school_id"]:
        fail("ERR_STUDENT_SCHOOL_MISMATCH", "The student attends a different school.")
    for slot in domain.slots_of_team(team_id):
        if slot["student_id"] == student_id and slot["participation_status"] != "RELEASED":
            fail("ERR_DUPLICATE_ROSTER_SLOT", "The student already holds a live slot on this team.")
    season = domain.season_of(team)
    if slot_role == "STARTER" and season is not None:
        if team["starter_slots_used"] >= season["max_starters"]:
            fail("ERR_STARTER_CAPACITY_EXCEEDED", "The team has no starting capacity left.")
    slot = new_record(
        "roster_slot",
        team_id=team_id,
        student_id=student_id,
        slot_role=slot_role,
        verification_status="UNVERIFIED",
        academic_status="PENDING",
        participation_status="PROSPECTIVE",
        enrollment_verified_by_user_id=None,
        academics_verified_by_user_id=None,
        enrollment_document_ref=None,
        verified_birthdate=None,
        age_at_cutoff=None,
        standing_at_verification=None,
        effective_gpa_at_verification=None,
        released_at=None,
        ineligibility_reason=None,
    )
    domain.recompute_team_rollups(team)
    return created(dump(slot))


@bp.get("/roster-slots/<slot_id>")
@endpoint(*SLOT_READ_ROLES)
def read_roster_slot(ctx, slot_id):
    return ok(dump(must_find("roster_slot", slot_id)))


@bp.get("/roster-slots")
@endpoint(*SLOT_READ_ROLES)
def list_roster_slots(ctx):
    return listing(
        "roster_slot", ("team_id", "student_id", "slot_role", "participation_status"), dump
    )


def _roster_open(slot):
    """Rungs 15 and 16, in ladder order: roster openness precedes slot release."""
    team = find("team", slot["team_id"])
    if team is None or team["status"] not in ("DRAFT", "REGISTERED"):
        fail("ERR_ROSTER_LOCKED", "The team's roster is no longer open for changes.")
    if slot["participation_status"] == "RELEASED":
        fail("ERR_ROSTER_SLOT_RELEASED", "The slot has been released and is terminal.")
    return team


@bp.post("/roster-slots/<slot_id>/verify-enrollment")
@endpoint("EligibilityOfficer")
def verify_enrollment(ctx, slot_id):
    slot = must_find("roster_slot", slot_id)
    document_ref = req_str(ctx.body, "enrollment_document_ref", 1, 200)
    verified_birthdate = req_date(ctx.body, "verified_birthdate")
    team = _roster_open(slot)
    _require_coach_ready(find("coach", team["coach_id"]))
    student = find("student", slot["student_id"])
    if student is None or student["enrollment_status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
    school = domain.school_of(student)
    if school is None or school["enrollment_verified_through"] < clock_date():
        fail(
            "ERR_ENROLLMENT_CERTIFICATION_LAPSED",
            "The school's registrar certification has lapsed.",
        )
    if verified_birthdate != student["birthdate"]:
        fail(
            "ERR_BIRTHDATE_DOCUMENT_MISMATCH",
            "The document birthdate does not match the student record.",
        )
    season = domain.season_of(team)
    title = find("title", team["title_id"])
    age_at_cutoff = completed_years(verified_birthdate, season["age_cutoff_date"])
    if title is not None and age_at_cutoff < title["min_player_age"]:
        fail("ERR_STUDENT_BELOW_TITLE_MIN_AGE", "The student is below the publisher age floor.")
    if age_at_cutoff >= season["max_age"]:
        fail("ERR_STUDENT_OVER_AGE_LIMIT", "The student is at or above the league age ceiling.")
    domain.update(
        slot,
        verification_status="ENROLLMENT_VERIFIED",
        enrollment_document_ref=document_ref,
        verified_birthdate=verified_birthdate,
        age_at_cutoff=age_at_cutoff,
        enrollment_verified_by_user_id=ctx.user_id,
    )
    domain.reconcile_slot(slot)
    touch(slot)
    domain.recompute_team_rollups(team)
    return ok(dump(slot))


@bp.post("/roster-slots/<slot_id>/verify-academics")
@endpoint("EligibilityOfficer")
def verify_academics(ctx, slot_id):
    slot = must_find("roster_slot", slot_id)
    team = _roster_open(slot)
    if slot.get("enrollment_verified_by_user_id") == ctx.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who verified enrollment may not clear academics.",
        )
    student = find("student", slot["student_id"])
    if student is None or student.get("latest_term_gpa") is None:
        fail("ERR_ACADEMIC_STANDING_INELIGIBLE", "The student has no posted academic term.")
    district = domain.district_of_student(student)
    effective, standing, _ = domain.evaluate_standing(student, district)
    if standing == "INELIGIBLE":
        fail("ERR_ACADEMIC_STANDING_INELIGIBLE", "The student's academic standing is ineligible.")
    if standing == "PROBATION" and slot["slot_role"] == "STARTER":
        fail(
            "ERR_PROBATION_STARTER_RESTRICTED",
            "A student on probation may not hold a starting slot.",
        )
    if student["fair_play_status"] != "CLEAR":
        fail("ERR_STUDENT_FAIR_PLAY_SANCTIONED", "The student is under a fair-play sanction.")
    domain.apply_standing(student)
    touch(student)
    domain.update(
        slot,
        academic_status="CLEARED",
        standing_at_verification=standing,
        effective_gpa_at_verification=effective,
        academics_verified_by_user_id=ctx.user_id,
    )
    domain.reconcile_slot(slot)
    touch(slot)
    domain.recompute_team_rollups(team)
    return ok(dump(slot))


@bp.post("/roster-slots/<slot_id>/release")
@endpoint("Coach")
def release_roster_slot(ctx, slot_id):
    existing = find("roster_slot", slot_id)
    if existing is not None:
        coach_owns_team(ctx, find("team", existing["team_id"]))
    slot = must_find("roster_slot", slot_id)
    opt_str(ctx.body, "release_note", None, 1, 500)
    team = _roster_open(slot)
    domain.update(slot, released_at=db.now)
    domain.reconcile_slot(slot)
    touch(slot)
    domain.recompute_team_rollups(team)
    return ok(dump(slot))
