"""Tournaments and exemption grants."""
from flask import Blueprint

import calc
import listing
import services
import validate
from auth import guard, require_member_ownership
from envelope import object_response
from errors import ApiError
from store import (
    db, bump, clock, clock_iso, dt_of, date_of, day_start, find, insert,
    new_row, public,
)

bp = Blueprint("tournaments", __name__)

DIVISIONS = ("U13", "U15", "U17", "U19")
CATEGORIES = (
    "DEFENDING_CHAMPION",
    "QUALIFIER_WINNER",
    "NATIONAL_TEAM",
    "SPONSOR_INVITE",
)
PUBLIC_READ_ROLES = (
    "Anonymous",
    "TourAdmin",
    "RulesOfficial",
    "ChiefReferee",
    "ConductCommittee",
    "Member",
    "Coach",
)


@bp.route("/tournaments", methods=["POST"])
def create_tournament():
    guard(("TourAdmin",))
    body = validate.body()
    season_id = validate.req_id(body, "season_id")
    name = validate.req_str(body, "name", 1, 120)
    division = validate.req_enum(body, "division", DIVISIONS)
    tier = validate.req_enum(body, "tier", calc.TIERS)
    start_date = validate.req_date(body, "start_date")
    end_date = validate.req_date(body, "end_date")
    entry_open_at = validate.req_dt(body, "entry_open_at")
    entry_close_at = validate.req_dt(body, "entry_close_at")
    withdrawal_deadline_at = validate.req_dt(body, "withdrawal_deadline_at")
    field_size_limit = validate.req_int(body, "field_size_limit", minimum=1)
    max_handicap_index = validate.req_num(body, "max_handicap_index")
    entry_fee_cents = validate.req_int(body, "entry_fee_cents", minimum=0)
    round_count = validate.req_int(body, "round_count", 1, 4)
    course_rating = validate.req_num(body, "course_rating")
    slope_rating = validate.req_int(body, "slope_rating", 55, 155)
    tee_group_size = validate.opt_int(body, "tee_group_size", 1, 4, 3)
    tee_interval_minutes = validate.opt_int(body, "tee_interval_minutes", 1, 30, 10)
    qualifies_into = validate.opt_id(body, "qualifies_into_tournament_id")
    if end_date < start_date:
        validate.bad("Field 'end_date' must fall on or after 'start_date'")
    if not (dt_of(entry_close_at) > dt_of(entry_open_at)):
        validate.bad("Field 'entry_close_at' must fall strictly after 'entry_open_at'")

    season = find("seasons", season_id, "ERR_SEASON_NOT_FOUND")
    if qualifies_into is not None:
        find("tournaments", qualifies_into, "ERR_TOURNAMENT_NOT_FOUND")

    row = new_row()
    row.update(
        {
            "season_id": season["id"],
            "name": name,
            "division": division,
            "tier": tier,
            "start_date": start_date,
            "end_date": end_date,
            "entry_open_at": entry_open_at,
            "entry_close_at": entry_close_at,
            "withdrawal_deadline_at": withdrawal_deadline_at,
            "field_size_limit": field_size_limit,
            "max_handicap_index": max_handicap_index,
            "entry_fee_cents": entry_fee_cents,
            "round_count": round_count,
            "course_rating": course_rating,
            "slope_rating": slope_rating,
            "tee_group_size": tee_group_size,
            "tee_interval_minutes": tee_interval_minutes,
            "qualifies_into_tournament_id": qualifies_into,
            "status": "SCHEDULED",
            "entry_count": 0,
            "applied_count": 0,
            "accepted_count": 0,
            "waitlist_count": 0,
            "closed_count": 0,
            "open_slot_count": field_size_limit,
            "finished_count": 0,
            "field_quality_factor": None,
            "winner_entry_id": None,
            "completed_at": None,
            "cancellation_reason": None,
        }
    )
    insert("tournaments", row)
    return object_response(public(row), 201)


@bp.route("/tournaments", methods=["GET"])
def list_tournaments():
    guard(PUBLIC_READ_ROLES)
    return listing.listing(
        "tournaments",
        ("season_id", "division", "status", "qualifies_into_tournament_id",
         "winner_entry_id"),
    )


@bp.route("/tournaments/<tournament_id>", methods=["GET"])
def get_tournament(tournament_id):
    guard(PUBLIC_READ_ROLES)
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    return object_response(public(tournament))


@bp.route("/tournaments/<tournament_id>/open-entries", methods=["POST"])
def open_entries(tournament_id):
    guard(("TourAdmin",))
    validate.body()
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    if tournament["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    if not (clock() < dt_of(tournament["entry_close_at"])):
        raise ApiError(
            "ERR_INVALID_TOURNAMENT_STATE",
            "The entry window has already elapsed",
        )
    tournament["status"] = "ENTRY_OPEN"
    bump(tournament)
    return object_response(public(tournament))


@bp.route("/tournaments/<tournament_id>/close-entries", methods=["POST"])
def close_entries(tournament_id):
    guard(("TourAdmin",))
    validate.body()
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    if tournament["status"] != "ENTRY_OPEN":
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    if clock() < dt_of(tournament["entry_close_at"]):
        raise ApiError("ERR_ENTRY_WINDOW_OPEN")
    tournament["status"] = "ENTRY_CLOSED"
    bump(tournament)
    return object_response(public(tournament))


@bp.route("/tournaments/<tournament_id>/set-field", methods=["POST"])
def set_field(tournament_id):
    guard(("TourAdmin",))
    validate.body()
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    if tournament["status"] != "ENTRY_CLOSED":
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")

    applied = [
        e
        for e in services.entries_of_tournament(tournament["id"])
        if e["entry_status"] == "APPLIED"
    ]
    applied.sort(key=lambda e: (e["created_at"], e["_seq"]))

    candidates = []
    for entry in applied:
        member = services.member_of_entry(entry)
        status = member["eligibility_status"] if member else None
        if status == "VERIFIED":
            candidates.append(entry)
            continue
        entry["entry_status"] = "REJECTED"
        entry["rejection_reason"] = (
            "MEMBER_SUSPENDED" if status == "SUSPENDED" else "MEMBER_NOT_VERIFIED"
        )
        bump(entry)

    candidates.sort(key=calc.priority_sort_key)
    limit = tournament["field_size_limit"]
    for index, entry in enumerate(candidates):
        if index < limit:
            entry["entry_status"] = "ACCEPTED"
            entry["waitlist_position"] = None
            bump(entry)
            services.consume_grant(entry)
        else:
            entry["entry_status"] = "WAITLISTED"
            entry["waitlist_position"] = index - limit + 1
            bump(entry)

    services.recompute_census(tournament)
    services.recompute_field_quality(tournament)
    tournament["status"] = "FIELD_SET"
    bump(tournament)
    return object_response(public(tournament))


@bp.route("/tournaments/<tournament_id>/start", methods=["POST"])
def start_tournament(tournament_id):
    guard(("TourAdmin", "ChiefReferee"))
    validate.body()
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    if tournament["status"] != "FIELD_SET":
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    if clock() < day_start(tournament["start_date"]):
        raise ApiError(
            "ERR_INVALID_TOURNAMENT_STATE",
            "The tournament start date has not been reached",
        )
    if tournament["accepted_count"] < 1:
        raise ApiError("ERR_EMPTY_FIELD")
    for entry in services.entries_of_tournament(tournament["id"]):
        if entry["entry_status"] != "ACCEPTED":
            continue
        if entry["amount_paid_cents"] < entry["net_fee_due_cents"]:
            raise ApiError("ERR_ENTRY_FEE_OUTSTANDING")
    tournament["status"] = "IN_PROGRESS"
    bump(tournament)
    return object_response(public(tournament))


@bp.route("/tournaments/<tournament_id>/cancel", methods=["POST"])
def cancel_tournament_route(tournament_id):
    guard(("TourAdmin",))
    body = validate.body()
    reason = validate.req_str(body, "cancellation_reason", 1, 2000)
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    if tournament["status"] not in ("SCHEDULED", "ENTRY_OPEN", "ENTRY_CLOSED", "FIELD_SET"):
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    services.cancel_tournament(tournament, reason)
    return object_response(public(tournament))


# ---------------------------------------------------------------------------
# exemption grants
# ---------------------------------------------------------------------------
@bp.route("/exemption-grants", methods=["POST"])
def create_exemption_grant():
    guard(("TourAdmin",))
    body = validate.body()
    member_id = validate.req_id(body, "member_id")
    tournament_id = validate.req_id(body, "tournament_id")
    category = validate.req_enum(body, "category", CATEGORIES)
    expires_at = validate.req_dt(body, "expires_at")
    source_tournament_id = validate.opt_id(body, "source_tournament_id")

    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    if source_tournament_id is not None:
        find("tournaments", source_tournament_id, "ERR_TOURNAMENT_NOT_FOUND")

    if tournament["status"] not in ("SCHEDULED", "ENTRY_OPEN"):
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    if member["eligibility_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED")
    if member["eligibility_status"] != "VERIFIED":
        raise ApiError("ERR_MEMBER_NOT_VERIFIED")
    if member["age_division"] != tournament["division"]:
        raise ApiError("ERR_DIVISION_MISMATCH")

    row = new_row()
    row.update(
        {
            "member_id": member["id"],
            "tournament_id": tournament["id"],
            "source_tournament_id": source_tournament_id,
            "category": category,
            "expires_at": expires_at,
            "status": "ACTIVE",
            "consumed_by_entry_id": None,
        }
    )
    insert("exemption_grants", row)
    return object_response(public(row), 201)


@bp.route("/exemption-grants", methods=["GET"])
def list_exemption_grants():
    guard(("TourAdmin", "RulesOfficial", "ChiefReferee"))
    return listing.listing(
        "exemption_grants",
        ("member_id", "tournament_id", "source_tournament_id",
         "consumed_by_entry_id", "status"),
    )


@bp.route("/exemption-grants/<grant_id>", methods=["GET"])
def get_exemption_grant(grant_id):
    caller = guard(("TourAdmin", "RulesOfficial", "ChiefReferee", "Member"))
    grant = find("exemption_grants", grant_id, "ERR_GRANT_NOT_FOUND")
    require_member_ownership(caller, grant["member_id"])
    return object_response(public(grant))
