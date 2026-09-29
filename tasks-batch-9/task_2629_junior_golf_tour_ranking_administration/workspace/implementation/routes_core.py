"""Seasons, members and the logical clock."""
import re
from datetime import timedelta

from flask import Blueprint

import calc
import listing
import services
import validate
from auth import guard, require_member_ownership, require_member_read_access
from envelope import object_response
from errors import ApiError
from store import (
    db, bump, clock, clock_iso, iso, dt_of, date_of, find, insert, new_row,
    parse_dt_str, public, set_clock,
)

bp = Blueprint("core", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
HANDICAP_SOURCES = ("WHS_CLUB", "STATE_ASSOC", "SELF_ATTESTED")
STAFF_READ_ROLES = ("TourAdmin", "RulesOfficial", "ChiefReferee", "ConductCommittee")


def handicap_is_stale(member):
    effective = date_of(member["handicap_effective_date"])
    if effective is None:
        return True
    return (clock().date() - effective).days > calc.HANDICAP_VALIDITY_DAYS


# ---------------------------------------------------------------------------
# seasons
# ---------------------------------------------------------------------------
@bp.route("/seasons", methods=["POST"])
def create_season():
    guard(("TourAdmin",))
    body = validate.body()
    name = validate.req_str(body, "name", 1, 120)
    start_date = validate.req_date(body, "start_date")
    end_date = validate.req_date(body, "end_date")
    age_cutoff_date = validate.req_date(body, "age_cutoff_date")
    ranking_window_start_date = validate.req_date(body, "ranking_window_start_date")
    budget = validate.req_int(body, "assistance_budget_cents", minimum=0)
    if not (end_date > start_date):
        validate.bad("Field 'end_date' must fall strictly after 'start_date'")

    row = new_row()
    row.update(
        {
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "age_cutoff_date": age_cutoff_date,
            "ranking_window_start_date": ranking_window_start_date,
            "assistance_budget_cents": budget,
            "assistance_available_cents": budget,
            "assistance_committed_cents": 0,
            "assistance_disbursed_cents": 0,
            "ranking_epoch": 0,
            "last_ranking_run_at": None,
            "last_ranking_as_of_date": None,
            "ranked_member_count": 0,
        }
    )
    insert("seasons", row)
    return object_response(public(row), 201)


@bp.route("/seasons/<season_id>", methods=["GET"])
def get_season(season_id):
    guard(STAFF_READ_ROLES)
    season = find("seasons", season_id, "ERR_SEASON_NOT_FOUND")
    return object_response(public(season))


@bp.route("/seasons/<season_id>/ranking-runs", methods=["POST"])
def create_ranking_run(season_id):
    guard(("TourAdmin",))
    body = validate.body()
    as_of_date = validate.opt_date(body, "as_of_date")
    season = find("seasons", season_id, "ERR_SEASON_NOT_FOUND")
    services.run_ranking(season, as_of_date)
    return object_response(public(season))


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------
@bp.route("/members", methods=["POST"])
def create_member():
    guard(("Anonymous", "TourAdmin"), public=True)
    body = validate.body()
    season_id = validate.req_id(body, "season_id")
    full_name = validate.req_str(body, "full_name", 1, 120)
    birth_date = validate.req_date(body, "birth_date")
    state_code = validate.req_str(body, "state_code", 2, 2)
    if not STATE_CODE_RE.match(state_code):
        validate.bad("Field 'state_code' must be exactly two uppercase letters")
    guardian_email = validate.req_str(body, "guardian_email", 1, 320)
    handicap_index = validate.req_num(body, "handicap_index", -5.0, 54.0)
    handicap_effective_date = validate.req_date(body, "handicap_effective_date")
    handicap_source = validate.req_enum(body, "handicap_source", HANDICAP_SOURCES)
    publication_opt_in = validate.opt_bool(body, "publication_opt_in", False)

    season = find("seasons", season_id, "ERR_SEASON_NOT_FOUND")

    age = calc.age_at_cutoff(date_of(birth_date), date_of(season["age_cutoff_date"]))
    row = new_row()
    row.update(
        {
            "season_id": season["id"],
            "full_name": full_name,
            "birth_date": birth_date,
            "state_code": state_code,
            "guardian_email": guardian_email,
            "handicap_index": handicap_index,
            "handicap_effective_date": handicap_effective_date,
            "handicap_source": handicap_source,
            "publication_opt_in": publication_opt_in,
            "eligibility_status": "PENDING_VERIFICATION",
            "age_at_cutoff": age,
            "age_division": calc.age_division(age),
            "conduct_points": 0,
            "late_withdrawal_count": 0,
            "provisional_ranking_points": 0.00,
            "provisional_counted_events": 0,
            "certified_ranking_points": None,
            "certified_counted_events": 0,
            "certified_rank_position": None,
            "last_ranking_epoch": None,
        }
    )
    insert("members", row)
    return object_response(public(row), 201)


@bp.route("/members", methods=["GET"])
def list_members():
    guard(STAFF_READ_ROLES)
    return listing.listing("members", ("season_id", "age_division", "eligibility_status"))


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    caller = guard(STAFF_READ_ROLES + ("Member", "Coach"))
    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    require_member_read_access(caller, member["id"])
    return object_response(public(member))


@bp.route("/members/<member_id>/verify-eligibility", methods=["POST"])
def verify_eligibility(member_id):
    guard(("TourAdmin",))
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("VERIFIED", "REJECTED"))
    note = validate.opt_str(body, "note", 1, 2000)
    if decision == "REJECTED" and note is None:
        validate.bad("A REJECTED decision requires a 'note'")

    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if member["eligibility_status"] != "PENDING_VERIFICATION":
        validate.bad("Member eligibility has already been decided")

    if decision == "VERIFIED":
        season = db.seasons.get(member["season_id"])
        if season is not None:
            age = calc.age_at_cutoff(
                date_of(member["birth_date"]), date_of(season["age_cutoff_date"])
            )
            member["age_at_cutoff"] = age
            member["age_division"] = calc.age_division(age)
        if member["age_division"] is None:
            validate.bad("A junior outside the 11-to-19 band cannot be verified")
        if handicap_is_stale(member):
            raise ApiError("ERR_HANDICAP_STALE")
        member["eligibility_status"] = "VERIFIED"
    else:
        member["eligibility_status"] = "REJECTED"
    bump(member)
    return object_response(public(member))


@bp.route("/members/<member_id>/handicap-revisions", methods=["POST"])
def create_handicap_revision(member_id):
    guard(("TourAdmin", "RulesOfficial"))
    body = validate.body()
    handicap_index = validate.req_num(body, "handicap_index", -5.0, 54.0)
    handicap_effective_date = validate.req_date(body, "handicap_effective_date")
    handicap_source = validate.req_enum(body, "handicap_source", HANDICAP_SOURCES)
    expected_version = validate.req_int(body, "expected_member_version")

    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    if member["eligibility_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED")

    member["handicap_index"] = handicap_index
    member["handicap_effective_date"] = handicap_effective_date
    member["handicap_source"] = handicap_source
    bump(member)
    return object_response(public(member))


@bp.route("/members/<member_id>/ranking", methods=["GET"])
def get_member_ranking(member_id):
    caller = guard(("TourAdmin", "RulesOfficial", "ChiefReferee", "Member", "Coach"))
    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    require_member_ownership(caller, member["id"])
    if caller.is_coach:
        from auth import live_coach_grant

        if live_coach_grant(caller, member["id"]) is None:
            raise ApiError("ERR_COACH_ACCESS_DENIED")
    season = db.seasons.get(member["season_id"])
    data = {
        "member_id": member["id"],
        "age_division": member["age_division"],
        "provisional_ranking_points": member["provisional_ranking_points"],
        "provisional_counted_events": member["provisional_counted_events"],
        "certified_ranking_points": member["certified_ranking_points"],
        "certified_counted_events": member["certified_counted_events"],
        "certified_rank_position": member["certified_rank_position"],
        "last_ranking_epoch": member["last_ranking_epoch"],
        "ranking_epoch": season["ranking_epoch"] if season else None,
    }
    return object_response(data)


@bp.route("/members/<member_id>/published-results", methods=["GET"])
def get_member_published_results(member_id):
    caller = guard(("TourAdmin", "Member", "Coach"))
    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    require_member_ownership(caller, member["id"])
    if not member["publication_opt_in"]:
        raise ApiError("ERR_PUBLICATION_NOT_CONSENTED")
    if caller.is_coach:
        from auth import live_coach_grant

        if live_coach_grant(caller, member["id"]) is None:
            raise ApiError("ERR_COACH_ACCESS_DENIED")

    finished = [
        e
        for e in services.entries_of_member(member["id"])
        if e["entry_status"] == "FINISHED"
    ]
    positions = [e["finish_position"] for e in finished if e["finish_position"] is not None]
    diffs = [
        e["avg_scoring_differential"]
        for e in finished
        if e["avg_scoring_differential"] is not None
    ]
    data = {
        "member_id": member["id"],
        "full_name": member["full_name"],
        "age_division": member["age_division"],
        "handicap_index": member["handicap_index"],
        "publication_opt_in": member["publication_opt_in"],
        "certified_ranking_points": member["certified_ranking_points"],
        "certified_rank_position": member["certified_rank_position"],
        "finished_event_count": len(finished),
        "best_finish_position": min(positions) if positions else None,
        "avg_scoring_differential": calc.average_differential(diffs),
    }
    return object_response(data)


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    guard(
        (
            "Anonymous",
            "TourAdmin",
            "RulesOfficial",
            "ChiefReferee",
            "ConductCommittee",
            "Member",
            "Coach",
        ),
        public=True,
    )
    body = validate.body()
    current = validate.req_dt(body, "current_utc")
    previous = clock_iso()
    set_clock(parse_dt_str(current))
    return object_response({"current_utc": clock_iso(), "previous_utc": previous})
