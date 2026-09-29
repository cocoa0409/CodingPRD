"""Contests, officiating offers/responses, results, postponements and forfeits."""
from flask import Blueprint, request

from core import (
    DB, ALL_ROLES, CERT_LEVELS, auth, own, body, ok, ok_list, fail, req_str,
    req_enum, req_int, req_num, req_instant, opt_str, opt_bool, new_record,
    touch, now, pagination, paginate, by_created, get_school, get_season,
    get_contest, get_official, get_assignment, ser_contest, ser_official,
    ser_assignment,
)
import calc
import domain

bp = Blueprint("contests", __name__)


@bp.post("/athletics/contests")
def create_contest():
    p = auth(["SchoolAthleticDirector", "AssociationAdmin"])
    b = body()
    raw_home = b.get("home_school_id")
    if isinstance(raw_home, str):
        own(p, raw_home)
    # tier 5 - body reference existence
    if isinstance(b.get("sport_season_id"), str):
        get_season(b["sport_season_id"])
    if isinstance(raw_home, str):
        get_school(raw_home)
    if isinstance(b.get("away_school_id"), str):
        get_school(b["away_school_id"])
    # tier 6 - body shape
    season_id = req_str(b, "sport_season_id")
    home_id = req_str(b, "home_school_id")
    away_id = req_str(b, "away_school_id")
    starts_at = req_instant(b, "starts_at")
    ends_at = req_instant(b, "ends_at")
    if not (ends_at > starts_at):
        fail("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")
    travel_miles = req_num(b, "travel_miles", minimum=0)
    is_playoff = opt_bool(b, "is_playoff", False)
    expected = req_int(b, "expected_sport_season_version")

    season = DB.seasons[season_id]
    home = DB.schools[home_id]
    away = DB.schools[away_id]

    # tier 8 - season version lock
    if expected != season["version"]:
        fail("ERR_STALE_SEASON_VERSION", "expected_sport_season_version is stale")
    # tier 19 - season window
    d = starts_at.date()
    if d < season["first_contest_date"] or d > season["season_end_date"]:
        fail("ERR_CONTEST_OUTSIDE_SEASON_WINDOW",
             "the contest start date falls outside the season window")
    # tier 20 - venue turnover
    if not calc.venue_turnover_overlap(home, starts_at, ends_at):
        fail("ERR_VENUE_TURNOVER_CONFLICT", "the home venue cannot host this contest")
    # tier 24 - opponent sanity
    if home_id == away_id:
        fail("ERR_SAME_SCHOOL_CONTEST", "home_school_id must differ from away_school_id")
    if home["classification"] != season["classification"] \
            or away["classification"] != season["classification"]:
        fail("ERR_CLASSIFICATION_MISMATCH",
             "both schools must share the season's classification")
    # tier 25 - contest load, home then away
    calc.contest_load_check(season, home_id, away_id, starts_at)

    rec = new_record({
        "sport_season_id": season_id,
        "home_school_id": home_id,
        "away_school_id": away_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "travel_miles": travel_miles,
        "is_playoff": is_playoff,
        "status": "SCHEDULED",
        "accepted_official_count": 0,
        "home_score": None,
        "away_score": None,
        "forfeiting_school_id": None,
        "hold_reason": None,
        "result_recorded_at": None,
    })
    DB.contests[rec["id"]] = rec
    season["scheduled_contest_count"] += 1
    touch(season)
    return ok(ser_contest(rec), 201)


@bp.post("/athletics/contests/<cid>/officials")
def offer_official(cid):
    auth(["OfficialsCoordinator"])
    contest = get_contest(cid)
    b = body()
    if isinstance(b.get("official_id"), str):
        get_official(b["official_id"])
    official_id = req_str(b, "official_id")
    expected = req_int(b, "expected_contest_version")
    official = DB.officials[official_id]

    if expected != contest["version"]:
        fail("ERR_STALE_CONTEST_VERSION", "expected_contest_version is stale")
    season = DB.seasons.get(contest["sport_season_id"])
    if season is None or season["status"] not in ("REGULAR_SEASON", "PLAYOFFS"):
        fail("ERR_SEASON_NOT_OPEN", "the governing season does not admit officiating offers")
    if not calc.official_double_booking_overlap(official, contest):
        fail("ERR_OFFICIAL_DOUBLE_BOOKED", "the official is already committed over this window")

    rec = new_record({
        "contest_id": contest["id"],
        "official_id": official_id,
        "status": "OFFERED",
        "stipend_cents": None,
        "responded_at": None,
    })
    DB.assignments[rec["id"]] = rec
    touch(contest)
    return ok(ser_assignment(rec), 201)


@bp.post("/athletics/official-assignments/<aid>/respond")
def respond_assignment(aid):
    p = auth(["Official"])
    assignment = get_assignment(aid)
    own(p, assignment["official_id"])
    b = body()
    response = req_enum(b, "response", ["ACCEPT", "DECLINE"])
    if assignment["status"] != "OFFERED":
        fail("ERR_ALREADY_RESPONDED", "this assignment has already been answered")
    contest = DB.contests.get(assignment["contest_id"])
    if contest is None or contest["status"] not in ("SCHEDULED", "OFFICIALS_ASSIGNED"):
        fail("ERR_CONTEST_NOT_STAFFABLE", "the contest is no longer staffable")

    if response == "DECLINE":
        assignment["status"] = "DECLINED"
        assignment["responded_at"] = now()
        touch(assignment)
        return ok(ser_assignment(assignment))

    season = DB.seasons.get(contest["sport_season_id"])
    official = DB.officials.get(assignment["official_id"])
    assignment["status"] = "ACCEPTED"
    assignment["responded_at"] = now()
    assignment["stipend_cents"] = calc.officials_travel_stipend(official, contest, season)
    touch(assignment)
    contest["accepted_official_count"] += 1
    if official is not None:
        official["accepted_assignment_count"] += 1
        touch(official)
    if contest["status"] == "SCHEDULED" \
            and contest["accepted_official_count"] >= season["required_officials"]:
        contest["status"] = "OFFICIALS_ASSIGNED"
        contest["hold_reason"] = None
    touch(contest)
    return ok(ser_assignment(assignment))


@bp.post("/athletics/contests/<cid>/confirm")
def confirm_contest(cid):
    p = auth(["SchoolAthleticDirector"])
    contest = get_contest(cid)
    own(p, contest["home_school_id"])
    if contest["status"] not in ("SCHEDULED", "OFFICIALS_ASSIGNED"):
        fail("ERR_INVALID_STATE", "a contest in %s may not be confirmed" % contest["status"])
    season = DB.seasons.get(contest["sport_season_id"])
    if season is None or season["status"] not in ("REGULAR_SEASON", "PLAYOFFS"):
        fail("ERR_SEASON_NOT_OPEN", "the governing season does not admit confirmation")
    home = DB.schools.get(contest["home_school_id"])
    if home is not None and home["sanction_status"] == "SUSPENDED":
        fail("ERR_SCHOOL_SANCTIONED", "the home school is SUSPENDED")
    if contest["accepted_official_count"] < season["required_officials"]:
        fail("ERR_OFFICIALS_INCOMPLETE", "the officiating quorum has not been met")
    contest["status"] = "CONFIRMED"
    contest["hold_reason"] = None
    touch(contest)
    return ok(ser_contest(contest))


@bp.post("/athletics/contests/<cid>/postpone")
def postpone_contest(cid):
    auth(["AssociationAdmin"])
    contest = get_contest(cid)
    b = body()
    new_starts_at = req_instant(b, "new_starts_at")
    new_ends_at = req_instant(b, "new_ends_at")
    if not (new_ends_at > new_starts_at):
        fail("ERR_INVALID_REQUEST", "new_ends_at must be strictly after new_starts_at")
    opt_str(b, "postpone_note", None)
    if contest["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "only a CONFIRMED contest may be postponed")
    if not (new_starts_at > now()):
        fail("ERR_CONTEST_TIME_IN_PAST", "new_starts_at must be strictly after the logical clock")

    contest["starts_at"] = new_starts_at
    contest["ends_at"] = new_ends_at
    contest["status"] = "SCHEDULED"
    contest["hold_reason"] = "ADMIN_POSTPONE"
    contest["accepted_official_count"] = 0
    touch(contest)
    domain.withdraw_assignments(contest)
    domain.cancel_trips(contest, ("REQUESTED", "APPROVED"))
    return ok(ser_contest(contest))


@bp.post("/athletics/contests/<cid>/result")
def record_result(cid):
    p = auth(["SchoolAthleticDirector"])
    contest = get_contest(cid)
    own(p, contest["home_school_id"])
    b = body()
    home_score = req_int(b, "home_score", minimum=0)
    away_score = req_int(b, "away_score", minimum=0)
    if contest["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "only a CONFIRMED contest may record a result")
    if now() < contest["starts_at"]:
        fail("ERR_RESULT_BEFORE_TIPOFF", "the contest has not started yet")
    contest["home_score"] = home_score
    contest["away_score"] = away_score
    contest["result_recorded_at"] = now()
    contest["status"] = "PLAYED"
    touch(contest)
    for t in DB.transports.values():
        if t["contest_id"] == contest["id"] and t["status"] == "APPROVED":
            t["status"] = "COMPLETED"
            touch(t)
    return ok(ser_contest(contest))


@bp.post("/athletics/contests/<cid>/forfeit")
def forfeit_contest(cid):
    auth(["AssociationAdmin"])
    contest = get_contest(cid)
    b = body()
    forfeiting_school_id = req_str(b, "forfeiting_school_id")
    opt_str(b, "forfeit_note", None)
    if contest["status"] not in ("SCHEDULED", "OFFICIALS_ASSIGNED", "CONFIRMED"):
        fail("ERR_INVALID_STATE", "a contest in %s may not be forfeited" % contest["status"])
    if forfeiting_school_id not in (contest["home_school_id"], contest["away_school_id"]):
        fail("ERR_SCHOOL_NOT_IN_CONTEST",
             "the forfeiting school is neither the home nor the away school")
    school = DB.schools.get(forfeiting_school_id)
    domain.cascade_b(contest, school)
    return ok(ser_contest(contest))


@bp.get("/athletics/contests/<cid>")
def read_contest(cid):
    auth(ALL_ROLES)
    return ok(ser_contest(get_contest(cid)))


@bp.get("/athletics/contests")
def list_contests():
    auth(ALL_ROLES)
    limit, offset = pagination()
    rows = list(DB.contests.values())
    for key in ("sport_season_id", "home_school_id", "away_school_id",
                "forfeiting_school_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [c for c in rows if c[key] == val]
    rows.sort(key=lambda c: (c["starts_at"], c["created_at"], c["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_contest(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Officials
# ---------------------------------------------------------------------------
@bp.post("/athletics/officials")
def create_official():
    auth(["AssociationAdmin"])
    b = body()
    rec = new_record({
        "full_name": req_str(b, "full_name"),
        "certification_level": req_enum(b, "certification_level", CERT_LEVELS),
        "home_region_code": req_str(b, "home_region_code"),
        "accepted_assignment_count": 0,
    })
    DB.officials[rec["id"]] = rec
    return ok(ser_official(rec), 201)


@bp.get("/athletics/official-assignments/<aid>")
def read_assignment(aid):
    auth(ALL_ROLES)
    return ok(ser_assignment(get_assignment(aid)))


@bp.get("/athletics/official-assignments")
def list_assignments():
    auth(ALL_ROLES)
    limit, offset = pagination()
    rows = list(DB.assignments.values())
    for key in ("contest_id", "official_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [a for a in rows if a[key] == val]
    rows = by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_assignment(a) for a in page], limit, offset, total)
