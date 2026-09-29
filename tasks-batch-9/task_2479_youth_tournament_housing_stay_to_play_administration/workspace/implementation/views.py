"""The 44 declared endpoints.

Every view body runs its checks in the order of the global rejection ladder of
PRD 2.11, so the first failing check is the one that answers.  The ladder step
each check implements is named in a comment beside it.
"""

from decimal import Decimal

from flask import Blueprint, g, request

import calc
import domain
from core import (
    ENTRY_SCHEMA,
    array_response,
    endpoint,
    field,
    list_response,
    object_response,
    parse_filters,
    raw_body,
    sort_key,
    validate_body,
)
from errors import ApiError
from store import (
    db,
    day_span,
    midnight,
    new_id,
    nights_between,
    now,
    now_iso,
    parse_date,
    parse_datetime,
)

bp = Blueprint("housing", __name__)

ALL_ROLES = (
    "HousingManager",
    "ExceptionReviewer",
    "TeamManager",
    "HotelRepresentative",
    "RightsHolder",
)

ROOM_TYPES = ("DOUBLE_QUEEN", "KING", "SUITE")
REBATE_MODELS = ("PER_ROOM_NIGHT_FLAT", "PERCENT_OF_ROOM_REVENUE", "TIERED_PER_ROOM_NIGHT")
CONTRACT_STATUSES = ("DRAFT", "NEGOTIATING", "EXECUTED", "CLOSED")
BLOCK_STATUSES = ("OPEN", "RESTRICTED", "RELEASED", "SETTLED")
REGISTRATION_STATUSES = (
    "PENDING_HOUSING",
    "HOUSING_COMPLIANT",
    "EXCEPTION_GRANTED",
    "NON_COMPLIANT",
)
BOOKING_STATUSES = ("DRAFT", "ROOMING_LIST_SUBMITTED", "CONFIRMED", "CHECKED_OUT", "CANCELLED")
REBATE_STATUSES = ("NOT_DUE", "ACCRUED", "INVOICED", "COLLECTED", "SHORT_PAID", "WRITTEN_OFF")
REASON_CODES = (
    "LOCAL_TEAM",
    "FAMILY_MEDICAL",
    "ADA_ACCOMMODATION",
    "FINANCIAL_HARDSHIP",
    "RELATIVE_HOSTING",
)
EXCEPTION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED")
COMPLAINT_CATEGORIES = (
    "PRICING_FAIRNESS",
    "POLICY_FAIRNESS",
    "BLOCK_AVAILABILITY",
    "REBATE_TRANSPARENCY",
)
COMPLAINT_STATUSES = ("FILED", "INVESTIGATING", "ESCALATED", "UPHELD", "DISMISSED")
REMEDY_TYPES = ("NONE", "FEE_WAIVER", "RATE_ADJUSTMENT", "POLICY_EXEMPTION")
INVOICE_STATUSES = ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "WRITTEN_OFF")
DISTRIBUTION_STATUSES = ("CALCULATED", "APPROVED", "PAID")

SYSTEM_AUTO = "SYSTEM_AUTO"


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def versioned_row(fields):
    stamp = now_iso()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def append_only_row(fields):
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    return row


def path_row(collection, row_id, error_id):
    """Ladder step 5 — path-templated resource resolution."""
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def body_ref(body, name, collection, error_id):
    """Ladder step 6 — body reference resolution.

    An absent (or explicitly null) optional reference resolves to nothing and is
    not an error; a supplied value that names no row is the type's 404.
    """
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str) or value not in collection:
        raise ApiError(error_id)
    return collection[value]


def filter_rows(rows, filters):
    out = rows
    for name, value in filters.items():
        out = [r for r in out if r.get(name) == value]
    return out


def require_open(tournament):
    """Ladder step 14."""
    if tournament["posture"] != "OPEN":
        raise ApiError(
            "ERR_TOURNAMENT_NOT_OPEN",
            "The tournament's posture must be OPEN for this operation.",
        )


def require_reconciling(tournament):
    """Ladder step 15."""
    if tournament["posture"] not in ("BOOKING_CLOSED", "RECONCILING"):
        raise ApiError(
            "ERR_TOURNAMENT_NOT_RECONCILING",
            "The tournament's posture must be BOOKING_CLOSED or RECONCILING.",
        )


def require_executed(contract):
    """Ladder step 16."""
    if contract["status"] != "EXECUTED":
        raise ApiError(
            "ERR_CONTRACT_NOT_EXECUTED", "The hotel contract must be EXECUTED."
        )


def require_bookable(block):
    """Ladder step 17."""
    if block["status"] not in ("OPEN", "RESTRICTED"):
        raise ApiError("ERR_BLOCK_NOT_BOOKABLE", "The room block no longer sells rooms.")


def invalid_state(message):
    return ApiError("ERR_INVALID_STATE", message)


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------

TOURNAMENT_SCHEMA = {
    "name": field("string", required=True, non_empty=True),
    "rights_holder_org": field("string", required=True, non_empty=True),
    "destination_org": field("string", required=True, non_empty=True),
    "start_date": field("date", required=True),
    "end_date": field("date", required=True),
    "booking_deadline": field("datetime", required=True),
    "share_pct_organizer": field("number", required=True, minimum=0, maximum=1),
    "share_pct_rights_holder": field("number", required=True, minimum=0, maximum=1),
    "share_pct_destination": field("number", required=True, minimum=0, maximum=1),
    "stay_to_play_required": field("boolean", default=True),
}


@bp.post("/housing/tournaments")
@endpoint(["HousingManager"])
def create_tournament():
    body = validate_body(raw_body(), TOURNAMENT_SCHEMA)  # 9

    start = parse_date(body["start_date"])
    end = parse_date(body["end_date"])
    if end <= start:  # 27
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must be after start_date.")

    total = (
        calc.dec(body["share_pct_organizer"])
        + calc.dec(body["share_pct_rights_holder"])
        + calc.dec(body["share_pct_destination"])
    )
    if total != Decimal("1"):  # 40
        raise ApiError(
            "ERR_REVENUE_SHARE_NOT_UNITY", "The three revenue shares must sum to exactly 1."
        )

    row = versioned_row(
        {
            "name": body["name"],
            "rights_holder_org": body["rights_holder_org"],
            "destination_org": body["destination_org"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "booking_deadline": body["booking_deadline"],
            "stay_to_play_required": body["stay_to_play_required"],
            "share_pct_organizer": body["share_pct_organizer"],
            "share_pct_rights_holder": body["share_pct_rights_holder"],
            "share_pct_destination": body["share_pct_destination"],
            "posture": "OPEN",
            "housing_pressure": "NORMAL",
            "executed_contract_count": 0,
            "sold_out_contract_count": 0,
            "night_count": day_span(start, end),
        }
    )
    db.tournaments[row["id"]] = row
    return object_response(row, 201)


@bp.get("/housing/tournaments/<tournament_id>")
@endpoint(ALL_ROLES)
def read_tournament(tournament_id):
    row = path_row(db.tournaments, tournament_id, "ERR_TOURNAMENT_NOT_FOUND")  # 5
    return object_response(row)


@bp.post("/housing/tournaments/<tournament_id>/close-booking")
@endpoint(["HousingManager"])
def close_booking(tournament_id):
    tournament = path_row(db.tournaments, tournament_id, "ERR_TOURNAMENT_NOT_FOUND")  # 5
    if tournament["posture"] != "OPEN":  # 13
        raise invalid_state("Only an OPEN tournament may close its housing window.")
    signed = [
        c
        for c in domain.contracts_of_tournament(tournament["id"])
        if c["status"] in ("EXECUTED", "CLOSED")
    ]
    if not signed:  # 13 (unnamed precondition)
        raise invalid_state(
            "At least one hotel contract must be EXECUTED or CLOSED before closing."
        )
    domain.close_housing_window(tournament)
    return object_response(tournament)


# ---------------------------------------------------------------------------
# Hotel and Team
# ---------------------------------------------------------------------------

HOTEL_SCHEMA = {
    "name": field("string", required=True, non_empty=True),
    "city": field("string", required=True, non_empty=True),
    "total_rooms": field("integer", required=True, minimum=1),
    "distance_miles_from_venue": field("number", required=True, minimum=0),
}


@bp.post("/housing/hotels")
@endpoint(["HousingManager"])
def create_hotel():
    body = validate_body(raw_body(), HOTEL_SCHEMA)  # 9
    row = versioned_row(
        {
            "name": body["name"],
            "city": body["city"],
            "total_rooms": body["total_rooms"],
            "distance_miles_from_venue": body["distance_miles_from_venue"],
        }
    )
    db.hotels[row["id"]] = row
    return object_response(row, 201)


TEAM_SCHEMA = {
    "name": field("string", required=True, non_empty=True),
    "home_city": field("string", required=True, non_empty=True),
    "home_state": field("string", required=True, non_empty=True),
    "org_contact_email": field("string", required=True, non_empty=True),
    "distance_miles_from_venue": field("number", required=True, minimum=0),
}


@bp.post("/housing/teams")
@endpoint(["HousingManager"])
def create_team():
    body = validate_body(raw_body(), TEAM_SCHEMA)  # 9
    row = versioned_row(
        {
            "name": body["name"],
            "home_city": body["home_city"],
            "home_state": body["home_state"],
            "org_contact_email": body["org_contact_email"],
            "distance_miles_from_venue": body["distance_miles_from_venue"],
        }
    )
    db.teams[row["id"]] = row
    return object_response(row, 201)


# ---------------------------------------------------------------------------
# HotelContract
# ---------------------------------------------------------------------------

CONTRACT_SCHEMA = {
    "tournament_id": field("id", required=True),
    "hotel_id": field("id", required=True),
    "negotiated_nightly_rate_cents": field("integer", required=True, minimum=1),
    "rebate_model": field("enum", required=True, members=REBATE_MODELS),
    "attrition_threshold_pct": field("number", required=True, exclusive_minimum=0, maximum=1),
    "attrition_penalty_rate_cents_per_room_night": field("integer", required=True, minimum=0),
    "cutoff_date": field("datetime", required=True),
    "rebate_flat_cents_per_room_night": field("integer"),
    "rebate_percent": field("number"),
}


@bp.post("/housing/hotel-contracts")
@endpoint(["HousingManager"])
def create_contract():
    body = raw_body()
    tournament = body_ref(body, "tournament_id", db.tournaments, "ERR_TOURNAMENT_NOT_FOUND")  # 6
    hotel = body_ref(body, "hotel_id", db.hotels, "ERR_HOTEL_NOT_FOUND")  # 6
    body = validate_body(body, CONTRACT_SCHEMA)  # 9
    require_open(tournament)  # 14

    model = body["rebate_model"]
    flat = body["rebate_flat_cents_per_room_night"]
    percent = body["rebate_percent"]
    if model == "PER_ROOM_NIGHT_FLAT":
        ok = flat is not None and flat >= 1 and percent is None
    elif model == "PERCENT_OF_ROOM_REVENUE":
        ok = (
            percent is not None
            and calc.dec(percent) > 0
            and calc.dec(percent) <= 1
            and flat is None
        )
    else:
        ok = flat is None and percent is None
    if not ok:  # 39
        raise ApiError(
            "ERR_REBATE_MODEL_FIELDS_INVALID",
            "The rebate parameter fields do not match rebate_model %s." % model,
        )

    row = versioned_row(
        {
            "tournament_id": tournament["id"],
            "hotel_id": hotel["id"],
            "status": "DRAFT",
            "negotiated_nightly_rate_cents": body["negotiated_nightly_rate_cents"],
            "rebate_model": model,
            "rebate_flat_cents_per_room_night": 0 if flat is None else flat,
            "rebate_percent": 0 if percent is None else percent,
            "attrition_threshold_pct": body["attrition_threshold_pct"],
            "attrition_penalty_rate_cents_per_room_night": body[
                "attrition_penalty_rate_cents_per_room_night"
            ],
            "cutoff_date": body["cutoff_date"],
            "countersigned_by_hotel_id": None,
            "revision_round": 0,
            "contracted_room_nights": 0,
            "block_posture": "AVAILABLE",
        }
    )
    db.contracts[row["id"]] = row
    return object_response(row, 201)


NEGOTIATION_SCHEMA = {
    "action": field("enum", required=True, members=("SUBMIT", "COUNTERSIGN", "REVISE"))
}

NEGOTIATION_ACTION_ROLES = {
    "SUBMIT": "HousingManager",
    "COUNTERSIGN": "HotelRepresentative",
    "REVISE": "HotelRepresentative",
}


@bp.post("/housing/hotel-contracts/<contract_id>/negotiation")
@endpoint(["HousingManager", "HotelRepresentative"])
def negotiate_contract(contract_id):
    contract = path_row(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")  # 5
    domain.hotel_scope_contract(contract)  # 8
    body = validate_body(raw_body(), NEGOTIATION_SCHEMA)  # 9
    action = body["action"]
    if NEGOTIATION_ACTION_ROLES[action] != g.role:  # 10
        raise ApiError(
            "ERR_ACTION_ROLE_MISMATCH",
            "Action %s is not available to role %s." % (action, g.role),
        )
    tournament = domain.tournament_of_contract(contract)

    if action == "SUBMIT":
        if contract["status"] != "DRAFT":  # 13
            raise invalid_state("Only a DRAFT contract may be submitted.")
        require_open(tournament)  # 14
        if not domain.blocks_of_contract(contract["id"]):  # 13 (unnamed precondition)
            raise invalid_state("A contract with no room block has nothing to negotiate.")
        contract["status"] = "NEGOTIATING"
    elif action == "REVISE":
        if contract["status"] != "NEGOTIATING":  # 13
            raise invalid_state("Only a NEGOTIATING contract may be revised.")
        contract["status"] = "DRAFT"
        contract["revision_round"] = contract["revision_round"] + 1
    else:
        if contract["status"] != "NEGOTIATING":  # 13
            raise invalid_state("Only a NEGOTIATING contract may be countersigned.")
        require_open(tournament)  # 14
        contract["status"] = "EXECUTED"
        contract["countersigned_by_hotel_id"] = g.user_id

    domain.bump(contract)
    domain.recompute_tournament_pressure(tournament)
    return object_response(contract)


@bp.get("/housing/hotel-contracts/<contract_id>")
@endpoint(["HousingManager", "HotelRepresentative", "RightsHolder", "TeamManager"])
def read_contract(contract_id):
    row = path_row(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")  # 5
    return object_response(row)


@bp.get("/housing/hotel-contracts")
@endpoint(["HousingManager", "HotelRepresentative", "RightsHolder", "TeamManager"])
def list_contracts():
    filters = parse_filters(
        {"tournament_id": None, "hotel_id": None, "status": CONTRACT_STATUSES}
    )  # 9
    return list_response(filter_rows(list(db.contracts.values()), filters))


@bp.get("/housing/hotel-contracts/<contract_id>/room-blocks")
@endpoint(["HousingManager", "HotelRepresentative", "RightsHolder", "TeamManager"])
def list_contract_blocks(contract_id):
    contract = path_row(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")  # 5
    filters = parse_filters({"status": BLOCK_STATUSES})  # 9
    rows = domain.blocks_of_contract(contract["id"])
    return list_response(filter_rows(rows, filters))


# ---------------------------------------------------------------------------
# RoomBlock
# ---------------------------------------------------------------------------

ROOM_BLOCK_SCHEMA = {
    "contract_id": field("id", required=True),
    "room_type": field("enum", required=True, members=ROOM_TYPES),
    "block_size_rooms": field("integer", required=True, minimum=1),
    "arrival_date": field("date", required=True),
    "departure_date": field("date", required=True),
    "release_deadline": field("datetime", required=True),
}


@bp.post("/housing/room-blocks")
@endpoint(["HousingManager"])
def create_room_block():
    body = raw_body()
    contract = body_ref(body, "contract_id", db.contracts, "ERR_CONTRACT_NOT_FOUND")  # 6
    body = validate_body(body, ROOM_BLOCK_SCHEMA)  # 9
    tournament = domain.tournament_of_contract(contract)
    require_open(tournament)  # 14

    arrival = parse_date(body["arrival_date"])
    departure = parse_date(body["departure_date"])
    if departure <= arrival:  # 27
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", "departure_date must be after arrival_date."
        )

    pad = calc.BLOCK_WINDOW_PAD_DAYS
    event_start = parse_date(tournament["start_date"])
    event_end = parse_date(tournament["end_date"])
    earliest = event_start.toordinal() - pad
    latest = event_end.toordinal() + pad
    if arrival.toordinal() < earliest or departure.toordinal() > latest:  # 29
        raise ApiError(
            "ERR_BLOCK_OUTSIDE_EVENT_WINDOW",
            "The block window must fall inside the event window padded by %d days." % pad,
        )

    if parse_datetime(body["release_deadline"]) < parse_datetime(contract["cutoff_date"]):  # 31
        raise ApiError(
            "ERR_RELEASE_DEADLINE_BEFORE_CUTOFF",
            "release_deadline must be at or after the contract's cutoff_date.",
        )

    hotel = db.hotels[contract["hotel_id"]]
    size = body["block_size_rooms"]
    same_hotel = [
        b
        for b in db.room_blocks.values()
        if db.contracts[b["contract_id"]]["hotel_id"] == hotel["id"]
        and b["status"] in domain.LIVE_BLOCK_STATUSES
    ]
    for night in nights_between(arrival, departure):
        held = 0
        for other in same_hotel:
            if parse_date(other["arrival_date"]) <= night < parse_date(other["departure_date"]):
                held += other["block_size_rooms"]
        if held + size > hotel["total_rooms"]:  # 33
            raise ApiError(
                "ERR_HOTEL_NIGHT_CAPACITY_EXCEEDED",
                "The property has no room for %d further rooms on %s." % (size, night),
            )

    nights = day_span(arrival, departure)
    row = versioned_row(
        {
            "contract_id": contract["id"],
            "room_type": body["room_type"],
            "block_size_rooms": size,
            "arrival_date": body["arrival_date"],
            "departure_date": body["departure_date"],
            "release_deadline": body["release_deadline"],
            "status": "OPEN",
            "rooms_committed": 0,
            "rooms_available": size,
            "rooms_released_unsold": 0,
            "utilization_pct": calc.ratio_4dp(0, size),
            "threshold_room_nights": calc.block_threshold_room_nights(
                size, nights, contract["attrition_threshold_pct"]
            ),
            "actualized_room_nights": 0,
        }
    )
    db.room_blocks[row["id"]] = row
    domain.recompute_contract_posture(contract)
    return object_response(row, 201)


@bp.post("/housing/room-blocks/<block_id>/release")
@endpoint(["HousingManager"])
def release_room_block(block_id):
    block = path_row(db.room_blocks, block_id, "ERR_ROOM_BLOCK_NOT_FOUND")  # 5
    if block["status"] not in domain.LIVE_BLOCK_STATUSES:  # 13
        raise invalid_state("Only an OPEN or RESTRICTED block may be released.")
    contract = domain.contract_of_block(block)
    require_executed(contract)  # 16
    if now() < parse_datetime(block["release_deadline"]):  # 30
        raise ApiError(
            "ERR_RELEASE_BEFORE_DEADLINE",
            "The block may not be released before its release_deadline.",
        )
    domain.release_block(block)
    return object_response(block)


# ---------------------------------------------------------------------------
# TeamRegistration
# ---------------------------------------------------------------------------

REGISTRATION_SCHEMA = {
    "tournament_id": field("id", required=True),
    "team_id": field("id", required=True),
    "roster_player_count": field("integer", required=True, minimum=1),
    "roster_staff_count": field("integer", required=True, minimum=0),
}


@bp.post("/housing/team-registrations")
@endpoint(["HousingManager", "TeamManager"])
def create_registration():
    body = raw_body()
    tournament = body_ref(body, "tournament_id", db.tournaments, "ERR_TOURNAMENT_NOT_FOUND")  # 6
    team = body_ref(body, "team_id", db.teams, "ERR_TEAM_NOT_FOUND")  # 6
    if g.role == "TeamManager" and (team is None or team["id"] != g.user_id):  # 7
        raise ApiError(
            "ERR_TEAM_SCOPE_VIOLATION", "A team manager may only register its own team."
        )
    body = validate_body(body, REGISTRATION_SCHEMA)  # 9
    require_open(tournament)  # 14

    row = versioned_row(
        {
            "tournament_id": tournament["id"],
            "team_id": team["id"],
            "roster_player_count": body["roster_player_count"],
            "roster_staff_count": body["roster_staff_count"],
            "local_team_flag": calc.dec(team["distance_miles_from_venue"])
            <= calc.LOCAL_TEAM_RADIUS_MILES,
            "required_rooms_registered": 0,
            "required_room_nights": 0,
            "minimum_rooms_for_compliance": 0,
            "exempt_rooms_granted": 0,
            "effective_required_rooms": 0,
            "committed_rooms": 0,
            "status": "PENDING_HOUSING",
            "compliance_evaluated_at": now_iso(),
        }
    )
    db.registrations[row["id"]] = row
    # The creation recompute derives both occupancy variants and the status.
    g.bumped.add(row["id"])
    domain.recompute_registration(row)
    return object_response(row, 201)


@bp.get("/housing/team-registrations/<registration_id>")
@endpoint(["HousingManager", "TeamManager", "ExceptionReviewer"])
def read_registration(registration_id):
    row = path_row(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")  # 5
    return object_response(row)


@bp.get("/housing/team-registrations")
@endpoint(["HousingManager", "TeamManager", "ExceptionReviewer"])
def list_registrations():
    filters = parse_filters(
        {"tournament_id": None, "team_id": None, "status": REGISTRATION_STATUSES}
    )  # 9
    return list_response(filter_rows(list(db.registrations.values()), filters))


@bp.get("/housing/team-registrations/<registration_id>/exception-requests")
@endpoint(["HousingManager", "ExceptionReviewer", "TeamManager"])
def list_registration_exceptions(registration_id):
    registration = path_row(
        db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND"
    )  # 5
    filters = parse_filters({"status": EXCEPTION_STATUSES})  # 9
    rows = domain.requests_of_registration(registration["id"])
    return list_response(filter_rows(rows, filters))


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

BOOKING_SCHEMA = {
    "registration_id": field("id", required=True),
    "room_block_id": field("id", required=True),
    "rooms_requested": field("integer", required=True, minimum=1),
    "check_in_date": field("date", required=True),
    "check_out_date": field("date", required=True),
    "expected_registration_version": field("integer", required=True),
    "supersedes_booking_id": field("id"),
}


@bp.post("/housing/bookings")
@endpoint(["HousingManager", "TeamManager"])
def create_booking():
    body = raw_body()
    registration = body_ref(
        body, "registration_id", db.registrations, "ERR_REGISTRATION_NOT_FOUND"
    )  # 6
    block = body_ref(body, "room_block_id", db.room_blocks, "ERR_ROOM_BLOCK_NOT_FOUND")  # 6
    superseded = body_ref(body, "supersedes_booking_id", db.bookings, "ERR_BOOKING_NOT_FOUND")  # 6
    if g.role == "TeamManager" and (
        registration is None or registration["team_id"] != g.user_id
    ):  # 7
        raise ApiError(
            "ERR_TEAM_SCOPE_VIOLATION",
            "A team manager may only book for its own registration.",
        )
    body = validate_body(body, BOOKING_SCHEMA)  # 9

    if body["expected_registration_version"] != registration["version"]:  # 11
        raise ApiError(
            "ERR_STALE_REGISTRATION_VERSION",
            "expected_registration_version does not match the registration's version.",
        )

    tournament = domain.tournament_of_registration(registration)
    require_open(tournament)  # 14
    contract = domain.contract_of_block(block)
    require_executed(contract)  # 16
    require_bookable(block)  # 17

    if now() > parse_datetime(tournament["booking_deadline"]):  # 26
        raise ApiError(
            "ERR_BOOKING_DEADLINE_PASSED", "The tournament's booking deadline has passed."
        )

    check_in = parse_date(body["check_in_date"])
    check_out = parse_date(body["check_out_date"])
    if check_out <= check_in:  # 27
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", "check_out_date must be after check_in_date."
        )

    if check_in < parse_date(block["arrival_date"]) or check_out > parse_date(
        block["departure_date"]
    ):  # 28
        raise ApiError(
            "ERR_STAY_OUTSIDE_BLOCK_WINDOW",
            "The stay must fall inside the block's held window.",
        )

    for other in db.bookings.values():  # 32 — CLOSED intervals, adjacency forbidden
        if other["room_block_id"] == block["id"]:
            continue
        if other["booking_status"] not in domain.HELD_BOOKING_STATUSES:
            continue
        if domain.registration_of_booking(other)["team_id"] != registration["team_id"]:
            continue
        other_in = parse_date(other["check_in_date"])
        other_out = parse_date(other["check_out_date"])
        if other_in <= check_out and check_in <= other_out:
            raise ApiError(
                "ERR_TEAM_STAY_OVERLAP",
                "The team already has a live stay touching these dates at another block.",
            )

    if block["status"] == "RESTRICTED" and registration["status"] != "PENDING_HOUSING":  # 37
        raise ApiError(
            "ERR_BLOCK_RESTRICTED_TO_UNHOUSED_TEAMS",
            "A RESTRICTED block admits only registrations that are still PENDING_HOUSING.",
        )

    if superseded is not None:  # 38
        if superseded["registration_id"] != registration["id"] or superseded[
            "booking_status"
        ] not in ("DRAFT", "ROOMING_LIST_SUBMITTED", "CONFIRMED"):
            raise ApiError(
                "ERR_SUPERSEDE_TARGET_INVALID",
                "supersedes_booking_id must name an eligible booking of the same registration.",
            )

    rooms = body["rooms_requested"]
    if rooms > registration["required_rooms_registered"]:  # 48
        raise ApiError(
            "ERR_ROOMS_EXCEED_ROSTER_REQUIREMENT",
            "rooms_requested exceeds the registration's segregated-occupancy requirement.",
        )

    for night in nights_between(check_in, check_out):  # 49
        if domain.held_occupancy_on(block, night) + rooms > block["block_size_rooms"]:
            raise ApiError(
                "ERR_BLOCK_CAPACITY_EXCEEDED",
                "The block has no room for %d further rooms on %s." % (rooms, night),
            )

    nights = day_span(check_in, check_out)
    row = versioned_row(
        {
            "registration_id": registration["id"],
            "room_block_id": block["id"],
            "supersedes_booking_id": None if superseded is None else superseded["id"],
            "rooms_requested": rooms,
            "check_in_date": body["check_in_date"],
            "check_out_date": body["check_out_date"],
            "booking_status": "DRAFT",
            "rebate_status": "NOT_DUE",
            "nights": nights,
            "projected_room_nights": rooms * nights,
            "actualized_room_nights": 0,
            "rebate_accrued_cents": 0,
            "penalty_cents": 0,
            "penalty_room_nights": 0,
            "penalty_credit_cents": 0,
            "cancellation_reason": None,
            "cancelled_at": None,
        }
    )
    db.bookings[row["id"]] = row

    if superseded is not None:
        domain.cancel_booking(superseded, "SUPERSEDED")
    domain.bump(registration)
    return object_response(row, 201)


@bp.get("/housing/bookings/<booking_id>")
@endpoint(["HousingManager", "TeamManager", "HotelRepresentative"])
def read_booking(booking_id):
    row = path_row(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")  # 5
    return object_response(row)


@bp.get("/housing/bookings")
@endpoint(["HousingManager", "TeamManager", "HotelRepresentative"])
def list_bookings():
    filters = parse_filters(
        {
            "registration_id": None,
            "room_block_id": None,
            "supersedes_booking_id": None,
            "booking_status": BOOKING_STATUSES,
            "rebate_status": REBATE_STATUSES,
        }
    )  # 9
    return list_response(filter_rows(list(db.bookings.values()), filters))


ROOMING_LIST_SCHEMA = {"entries": field("entry_list", required=True)}


@bp.post("/housing/bookings/<booking_id>/rooming-list")
@endpoint(["HousingManager", "TeamManager"])
def submit_rooming_list(booking_id):
    booking = path_row(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")  # 5
    registration = domain.registration_of_booking(booking)
    domain.team_scope_registration(registration)  # 7
    body = validate_body(raw_body(), ROOMING_LIST_SCHEMA)  # 9
    entries = body["entries"]

    if booking["booking_status"] not in ("DRAFT", "ROOMING_LIST_SUBMITTED"):  # 13
        raise invalid_state("The booking no longer accepts a rooming list.")
    require_open(domain.tournament_of_registration(registration))  # 14

    for entry in entries:  # 21
        if entry["minor_occupant_count"] >= 1 and not (entry["chaperone_name"] or "").strip():
            raise ApiError(
                "ERR_CHAPERONE_REQUIRED",
                "A room lodging a minor must name a chaperone.",
            )
    for entry in entries:  # 22
        if (
            entry["occupant_count"] > calc.MAX_OCCUPANTS_PER_ROOM
            or entry["minor_occupant_count"] > entry["occupant_count"]
        ):
            raise ApiError(
                "ERR_ROOM_OCCUPANCY_EXCEEDED",
                "A room may hold at most %d occupants and no more minors than occupants."
                % calc.MAX_OCCUPANTS_PER_ROOM,
            )

    expected_indices = list(range(1, booking["rooms_requested"] + 1))
    if sorted(e["room_index"] for e in entries) != expected_indices:  # 34
        raise ApiError(
            "ERR_ROOMING_LIST_INDEX_INVALID",
            "room_index values must form the contiguous sequence 1..%d."
            % booking["rooms_requested"],
        )
    if len(entries) != booking["rooms_requested"]:  # 35
        raise ApiError(
            "ERR_ROOMING_LIST_ROOM_COUNT_MISMATCH",
            "The number of entries must equal the booking's rooms_requested.",
        )
    occupants = sum(e["occupant_count"] for e in entries)
    roster = registration["roster_player_count"] + registration["roster_staff_count"]
    if occupants < 1 or occupants > roster:  # 36
        raise ApiError(
            "ERR_ROOMING_LIST_OCCUPANT_MISMATCH",
            "Total occupants must be between 1 and the registration's roster size.",
        )

    for existing in domain.entries_of_booking(booking["id"]):
        del db.rooming_entries[existing["id"]]
    for entry in entries:
        row = append_only_row(
            {
                "booking_id": booking["id"],
                "room_index": entry["room_index"],
                "occupant_count": entry["occupant_count"],
                "minor_occupant_count": entry["minor_occupant_count"],
                "chaperone_name": entry["chaperone_name"],
            }
        )
        db.rooming_entries[row["id"]] = row

    booking["booking_status"] = "ROOMING_LIST_SUBMITTED"
    domain.bump(booking)
    return object_response(booking)


@bp.get("/housing/bookings/<booking_id>/rooming-list")
@endpoint(["HousingManager", "TeamManager", "HotelRepresentative"])
def list_rooming_list(booking_id):
    booking = path_row(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")  # 5
    rows = domain.entries_of_booking(booking["id"])
    return list_response(rows)


@bp.post("/housing/bookings/<booking_id>/confirm")
@endpoint(["HousingManager"])
def confirm_booking(booking_id):
    booking = path_row(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")  # 5
    if booking["booking_status"] != "ROOMING_LIST_SUBMITTED":  # 13
        raise invalid_state("Only a ROOMING_LIST_SUBMITTED booking may be confirmed.")
    registration = domain.registration_of_booking(booking)
    require_open(domain.tournament_of_registration(registration))  # 14
    block = domain.block_of_booking(booking)
    require_executed(domain.contract_of_block(block))  # 16
    require_bookable(block)  # 17

    booking["booking_status"] = "CONFIRMED"
    domain.bump(booking)
    # The four-link confirm chain, in the order PRD 3.4 pins.
    domain.recompute_registration(registration)
    domain.recompute_block_occupancy(block)
    return object_response(booking)


CANCEL_SCHEMA = {"cancellation_reason": field("string", required=True)}


@bp.post("/housing/bookings/<booking_id>/cancel")
@endpoint(["HousingManager", "TeamManager"])
def cancel_booking_view(booking_id):
    booking = path_row(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")  # 5
    registration = domain.registration_of_booking(booking)
    domain.team_scope_registration(registration)  # 7
    body = validate_body(raw_body(), CANCEL_SCHEMA)  # 9
    if booking["booking_status"] not in ("DRAFT", "ROOMING_LIST_SUBMITTED", "CONFIRMED"):  # 13
        raise invalid_state("The booking is no longer cancellable.")
    tournament = domain.tournament_of_registration(registration)
    if tournament["posture"] not in ("OPEN", "BOOKING_CLOSED"):  # 13 (unnamed precondition)
        raise invalid_state("Cancellation requires an OPEN or BOOKING_CLOSED tournament.")

    domain.cancel_booking(booking, body["cancellation_reason"])
    return object_response(booking)


ACTUALIZATION_SCHEMA = {
    "reported_room_nights": field("integer", required=True, minimum=0),
    "report_note": field("string"),
}


@bp.post("/housing/bookings/<booking_id>/actualizations")
@endpoint(["HotelRepresentative"])
def create_actualization(booking_id):
    booking = path_row(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")  # 5
    block = domain.block_of_booking(booking)
    contract = domain.contract_of_block(block)
    domain.hotel_scope_contract(contract)  # 8
    body = validate_body(raw_body(), ACTUALIZATION_SCHEMA)  # 9
    require_reconciling(domain.tournament_of_booking(booking))  # 15

    prior = domain.reports_of_booking(booking["id"])
    expected = "CONFIRMED" if not prior else "CHECKED_OUT"
    if booking["booking_status"] != expected:  # 18
        raise ApiError(
            "ERR_BOOKING_NOT_CONFIRMED",
            "The booking's status must be %s for this report." % expected,
        )

    report = append_only_row(
        {
            "booking_id": booking["id"],
            "sequence_no": len(prior) + 1,
            "reported_room_nights": body["reported_room_nights"],
            "report_note": body["report_note"],
        }
    )
    db.actualizations[report["id"]] = report

    # Axis A moves first, so the contract-wide tier total already counts this stay.
    if not prior:
        booking["booking_status"] = "CHECKED_OUT"
    booking["actualized_room_nights"] = body["reported_room_nights"]

    if booking["rebate_status"] == "NOT_DUE":
        if body["reported_room_nights"] > 0 and booking["booking_status"] in (
            "CONFIRMED",
            "CHECKED_OUT",
        ):
            booking["rebate_status"] = "ACCRUED"
            booking["rebate_accrued_cents"] = domain.booking_rebate_line(booking)
    elif booking["rebate_status"] == "ACCRUED":
        booking["rebate_accrued_cents"] = domain.booking_rebate_line(booking)

    domain.bump(booking)
    domain.recompute_block_actualized(block)
    return object_response(report, 201)


@bp.get("/housing/bookings/<booking_id>/actualization-reports")
@endpoint(["HousingManager", "HotelRepresentative", "RightsHolder"])
def list_actualizations(booking_id):
    booking = path_row(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")  # 5
    rows = domain.reports_of_booking(booking["id"])
    return list_response(rows, sorter=lambda r: r["sequence_no"])


# ---------------------------------------------------------------------------
# ExceptionRequest
# ---------------------------------------------------------------------------

EXCEPTION_SCHEMA = {
    "registration_id": field("id", required=True),
    "reason_code": field("enum", required=True, members=REASON_CODES),
    "requested_rooms_exempt": field("integer", required=True, minimum=1),
    "justification": field("string", required=True),
}


@bp.post("/housing/exception-requests")
@endpoint(["HousingManager", "TeamManager"])
def create_exception_request():
    body = raw_body()
    registration = body_ref(
        body, "registration_id", db.registrations, "ERR_REGISTRATION_NOT_FOUND"
    )  # 6
    if g.role == "TeamManager" and (
        registration is None or registration["team_id"] != g.user_id
    ):  # 7
        raise ApiError(
            "ERR_TEAM_SCOPE_VIOLATION",
            "A team manager may only file against its own registration.",
        )
    body = validate_body(body, EXCEPTION_SCHEMA)  # 9
    tournament = domain.tournament_of_registration(registration)
    require_open(tournament)  # 14

    reason = body["reason_code"]
    requested = body["requested_rooms_exempt"]
    if reason == "LOCAL_TEAM" and not registration["local_team_flag"]:  # 42
        raise ApiError(
            "ERR_LOCAL_EXEMPTION_NOT_ELIGIBLE",
            "A LOCAL_TEAM exemption requires a registration flagged local.",
        )
    if reason == "FAMILY_MEDICAL" and requested > 1:  # 43
        raise ApiError(
            "ERR_EXEMPTION_SCOPE_TOO_BROAD",
            "A FAMILY_MEDICAL exemption may ask for at most one room.",
        )
    if requested > registration["minimum_rooms_for_compliance"]:  # 44
        raise ApiError(
            "ERR_EXEMPTION_EXCEEDS_REQUIREMENT",
            "requested_rooms_exempt exceeds the registration's compliance minimum.",
        )
    for other in domain.requests_of_registration(registration["id"]):  # 45
        if other["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED"):
            raise ApiError(
                "ERR_DUPLICATE_OPEN_EXCEPTION",
                "The registration already has a live exception request.",
            )

    row = versioned_row(
        {
            "registration_id": registration["id"],
            "reason_code": reason,
            "requested_rooms_exempt": requested,
            "justification": body["justification"],
            "status": "SUBMITTED",
            "approved_rooms_exempt": 0,
            "review_round": 0,
            "appeal_count": 0,
            "decided_by_user_id": None,
            "decision_note": None,
        }
    )
    db.exception_requests[row["id"]] = row

    if (
        reason == "LOCAL_TEAM"
        and registration["local_team_flag"]
        and tournament["housing_pressure"] == "CONSTRAINED"
    ):
        row["status"] = "APPROVED"
        row["approved_rooms_exempt"] = requested
        row["decided_by_user_id"] = SYSTEM_AUTO
        g.bumped.add(row["id"])
        domain.recompute_registration(registration)

    return object_response(row, 201)


@bp.get("/housing/exception-requests/<request_id>")
@endpoint(["HousingManager", "ExceptionReviewer", "TeamManager"])
def read_exception_request(request_id):
    row = path_row(db.exception_requests, request_id, "ERR_EXCEPTION_REQUEST_NOT_FOUND")  # 5
    return object_response(row)


REVIEW_SCHEMA = {
    "action": field(
        "enum", required=True, members=("START_REVIEW", "REQUEST_INFO", "APPROVE", "DENY")
    ),
    "approved_rooms_exempt": field("integer"),
    "decision_note": field("string"),
}


@bp.post("/housing/exception-requests/<request_id>/review")
@endpoint(["ExceptionReviewer"])
def review_exception_request(request_id):
    row = path_row(db.exception_requests, request_id, "ERR_EXCEPTION_REQUEST_NOT_FOUND")  # 5
    body = validate_body(raw_body(), REVIEW_SCHEMA)  # 9
    action = body["action"]
    registration = db.registrations[row["registration_id"]]
    tournament = domain.tournament_of_registration(registration)

    expected = {
        "START_REVIEW": "SUBMITTED",
        "REQUEST_INFO": "UNDER_REVIEW",
        "APPROVE": "UNDER_REVIEW",
        "DENY": "UNDER_REVIEW",
    }[action]
    if row["status"] != expected:  # 13
        raise invalid_state("Action %s requires status %s." % (action, expected))

    if action in ("START_REVIEW", "APPROVE"):
        require_open(tournament)  # 14

    if action in ("APPROVE", "DENY") and row["appeal_count"] >= 1:  # 23
        if row["decided_by_user_id"] == g.user_id:
            raise ApiError(
                "ERR_SOD_SAME_REVIEWER",
                "An appeal must be decided by a different reviewer.",
            )

    if action == "APPROVE":
        granted = body["approved_rooms_exempt"]
        if granted is None or granted < 1 or granted > row["requested_rooms_exempt"]:  # 46
            raise ApiError(
                "ERR_APPROVED_EXEMPTION_OUT_OF_RANGE",
                "approved_rooms_exempt must be between 1 and requested_rooms_exempt.",
            )
        if row["reason_code"] == "LOCAL_TEAM" and granted != row["requested_rooms_exempt"]:  # 47
            raise ApiError(
                "ERR_PARTIAL_LOCAL_EXEMPTION_FORBIDDEN",
                "A LOCAL_TEAM exemption is all-or-nothing.",
            )

    if action == "START_REVIEW":
        row["status"] = "UNDER_REVIEW"
        row["review_round"] = row["review_round"] + 1
    elif action == "REQUEST_INFO":
        row["status"] = "INFO_REQUESTED"
        if body["decision_note"] is not None:
            row["decision_note"] = body["decision_note"]
    elif action == "APPROVE":
        row["status"] = "APPROVED"
        row["approved_rooms_exempt"] = body["approved_rooms_exempt"]
        row["decided_by_user_id"] = g.user_id
        if body["decision_note"] is not None:
            row["decision_note"] = body["decision_note"]
    else:
        row["status"] = "DENIED"
        row["approved_rooms_exempt"] = 0
        row["decided_by_user_id"] = g.user_id
        if body["decision_note"] is not None:
            row["decision_note"] = body["decision_note"]

    domain.bump(row)
    if action in ("APPROVE", "DENY"):
        domain.recompute_registration(registration)
    return object_response(row)


TEAM_ACTION_SCHEMA = {
    "action": field("enum", required=True, members=("RESUBMIT", "APPEAL")),
    "justification": field("string"),
}


@bp.post("/housing/exception-requests/<request_id>/team-action")
@endpoint(["TeamManager"])
def team_action_exception_request(request_id):
    row = path_row(db.exception_requests, request_id, "ERR_EXCEPTION_REQUEST_NOT_FOUND")  # 5
    registration = db.registrations[row["registration_id"]]
    domain.team_scope_registration(registration)  # 7
    body = validate_body(raw_body(), TEAM_ACTION_SCHEMA)  # 9
    action = body["action"]

    expected = "INFO_REQUESTED" if action == "RESUBMIT" else "DENIED"
    if row["status"] != expected:  # 13
        raise invalid_state("Action %s requires status %s." % (action, expected))
    require_open(domain.tournament_of_registration(registration))  # 14

    if action == "APPEAL" and row["appeal_count"] >= calc.MAX_EXCEPTION_APPEALS:  # 20
        raise ApiError(
            "ERR_APPEAL_LIMIT_REACHED", "The single permitted appeal has been used."
        )

    row["status"] = "UNDER_REVIEW"
    row["review_round"] = row["review_round"] + 1
    if action == "RESUBMIT":
        if body["justification"] is not None:
            row["justification"] = body["justification"]
    else:
        row["appeal_count"] = row["appeal_count"] + 1
    domain.bump(row)
    return object_response(row)


# ---------------------------------------------------------------------------
# Complaint
# ---------------------------------------------------------------------------

COMPLAINT_SCHEMA = {
    "tournament_id": field("id", required=True),
    "category": field("enum", required=True, members=COMPLAINT_CATEGORIES),
    "narrative": field("string", required=True),
    "registration_id": field("id"),
    "cited_exception_request_id": field("id"),
    "affected_booking_id": field("id"),
}


@bp.post("/housing/complaints")
@endpoint(["HousingManager", "TeamManager"])
def create_complaint():
    body = raw_body()
    tournament = body_ref(body, "tournament_id", db.tournaments, "ERR_TOURNAMENT_NOT_FOUND")  # 6
    registration = body_ref(
        body, "registration_id", db.registrations, "ERR_REGISTRATION_NOT_FOUND"
    )  # 6
    cited = body_ref(
        body,
        "cited_exception_request_id",
        db.exception_requests,
        "ERR_EXCEPTION_REQUEST_NOT_FOUND",
    )  # 6
    affected = body_ref(body, "affected_booking_id", db.bookings, "ERR_BOOKING_NOT_FOUND")  # 6
    if g.role == "TeamManager" and registration is not None:  # 7
        if registration["team_id"] != g.user_id:
            raise ApiError(
                "ERR_TEAM_SCOPE_VIOLATION",
                "A team manager may only complain about its own registration.",
            )
    body = validate_body(body, COMPLAINT_SCHEMA)  # 9

    if registration is None and cited is None and affected is None:  # 55
        raise ApiError(
            "ERR_COMPLAINT_SUBJECT_MISSING", "A complaint must cite at least one subject."
        )

    row = versioned_row(
        {
            "tournament_id": tournament["id"],
            "registration_id": None if registration is None else registration["id"],
            "cited_exception_request_id": None if cited is None else cited["id"],
            "affected_booking_id": None if affected is None else affected["id"],
            "category": body["category"],
            "narrative": body["narrative"],
            "status": "FILED",
            "route": None,
            "remedy_type": "NONE",
            "remedy_amount_cents": 0,
            "remedy_credit_cents": 0,
            "triaged_by_user_id": None,
            "adjudicated_by_user_id": None,
        }
    )
    db.complaints[row["id"]] = row
    return object_response(row, 201)


@bp.get("/housing/complaints/<complaint_id>")
@endpoint(["HousingManager", "RightsHolder", "TeamManager"])
def read_complaint(complaint_id):
    row = path_row(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")  # 5
    return object_response(row)


@bp.get("/housing/complaints")
@endpoint(["HousingManager", "RightsHolder", "TeamManager"])
def list_complaints():
    filters = parse_filters(
        {
            "tournament_id": None,
            "registration_id": None,
            "cited_exception_request_id": None,
            "affected_booking_id": None,
            "category": COMPLAINT_CATEGORIES,
            "status": COMPLAINT_STATUSES,
        }
    )  # 9
    return list_response(filter_rows(list(db.complaints.values()), filters))


TRIAGE_SCHEMA = {"route": field("enum", required=True, members=("INVESTIGATE", "ESCALATE"))}


@bp.post("/housing/complaints/<complaint_id>/triage")
@endpoint(["HousingManager"])
def triage_complaint(complaint_id):
    complaint = path_row(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")  # 5
    body = validate_body(raw_body(), TRIAGE_SCHEMA)  # 9
    if complaint["status"] != "FILED":  # 13
        raise invalid_state("Only a FILED complaint may be triaged.")
    tournament = db.tournaments[complaint["tournament_id"]]
    if tournament["posture"] == "SETTLED":  # 13 (unnamed precondition)
        raise invalid_state("A SETTLED tournament admits no further complaint handling.")

    route = body["route"]
    complaint["route"] = route
    complaint["triaged_by_user_id"] = g.user_id
    complaint["status"] = "INVESTIGATING" if route == "INVESTIGATE" else "ESCALATED"
    domain.bump(complaint)

    if route == "ESCALATE" and complaint["cited_exception_request_id"]:
        cited = db.exception_requests[complaint["cited_exception_request_id"]]
        if cited["status"] == "DENIED":
            cited["appeal_count"] = 0
            domain.bump(cited)

    return object_response(complaint)


ADJUDICATE_SCHEMA = {
    "outcome": field("enum", required=True, members=("UPHOLD", "DISMISS")),
    "remedy_type": field("enum", required=True, members=REMEDY_TYPES),
    "remedy_amount_cents": field("integer"),
}

ROUTE_REMEDIES = {
    "INVESTIGATE": ("NONE", "FEE_WAIVER"),
    "ESCALATE": ("NONE", "FEE_WAIVER", "RATE_ADJUSTMENT", "POLICY_EXEMPTION"),
}


@bp.post("/housing/complaints/<complaint_id>/adjudicate")
@endpoint(["RightsHolder"])
def adjudicate_complaint(complaint_id):
    complaint = path_row(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")  # 5
    body = validate_body(raw_body(), ADJUDICATE_SCHEMA)  # 9
    if complaint["status"] not in ("INVESTIGATING", "ESCALATED"):  # 13
        raise invalid_state("Only a triaged complaint may be adjudicated.")

    cited = None
    if complaint["cited_exception_request_id"]:
        cited = db.exception_requests[complaint["cited_exception_request_id"]]
        if cited["decided_by_user_id"] == g.user_id:  # 24
            raise ApiError(
                "ERR_SOD_ADJUDICATOR_CONFLICT",
                "The decider of the cited exception request may not adjudicate.",
            )

    remedy = body["remedy_type"]
    amount = body["remedy_amount_cents"]
    if remedy == "FEE_WAIVER":  # 53
        if amount is None or amount < 1 or not complaint["affected_booking_id"]:
            raise ApiError(
                "ERR_REMEDY_FIELDS_INVALID",
                "A FEE_WAIVER requires remedy_amount_cents >= 1 and an affected booking.",
            )
    elif amount is not None:  # 53
        raise ApiError(
            "ERR_REMEDY_FIELDS_INVALID",
            "remedy_amount_cents is only permitted with a FEE_WAIVER.",
        )

    if remedy not in ROUTE_REMEDIES[complaint["route"]]:  # 54
        raise ApiError(
            "ERR_REMEDY_NOT_AVAILABLE_ON_ROUTE",
            "Remedy %s is not available on the %s branch." % (remedy, complaint["route"]),
        )

    branch = complaint["status"]
    complaint["adjudicated_by_user_id"] = g.user_id

    if body["outcome"] == "DISMISS":
        complaint["status"] = "DISMISSED"
        complaint["remedy_type"] = "NONE"
        complaint["remedy_credit_cents"] = 0
        domain.bump(complaint)
        return object_response(complaint)

    complaint["status"] = "UPHELD"
    complaint["remedy_type"] = remedy
    if remedy == "FEE_WAIVER":
        complaint["remedy_amount_cents"] = amount

    booking = None
    if complaint["affected_booking_id"]:
        booking = db.bookings[complaint["affected_booking_id"]]
    uncredited = 0
    if booking is not None:
        uncredited = max(0, booking["penalty_cents"] - booking["penalty_credit_cents"])

    if remedy == "FEE_WAIVER":
        credit = min(complaint["remedy_amount_cents"], uncredited)
    elif remedy == "RATE_ADJUSTMENT" and booking is not None:
        rate = domain.contract_of_booking(booking)["negotiated_nightly_rate_cents"]
        credit = min(
            calc.rate_adjustment_credit(booking["projected_room_nights"], rate), uncredited
        )
    else:
        credit = 0
    complaint["remedy_credit_cents"] = credit

    moves_money = ("FEE_WAIVER",) if branch == "INVESTIGATING" else (
        "FEE_WAIVER",
        "RATE_ADJUSTMENT",
    )
    if remedy in moves_money and booking is not None:
        booking["penalty_credit_cents"] = booking["penalty_credit_cents"] + credit
        domain.bump(booking)

    domain.bump(complaint)

    # CASCADE-REMEDY, exclusive to the escalated branch.
    if branch == "ESCALATED" and remedy == "POLICY_EXEMPTION" and cited is not None:
        if cited["status"] == "DENIED":
            cited["status"] = "APPROVED"
            cited["approved_rooms_exempt"] = cited["requested_rooms_exempt"]
            cited["decided_by_user_id"] = SYSTEM_AUTO
            domain.bump(cited)
            domain.recompute_registration(db.registrations[cited["registration_id"]])

    return object_response(complaint)


# ---------------------------------------------------------------------------
# RebateInvoice
# ---------------------------------------------------------------------------

INVOICE_SCHEMA = {
    "contract_id": field("id", required=True),
    "period_label": field("string", required=True, non_empty=True),
}


@bp.post("/housing/rebate-invoices")
@endpoint(["HousingManager"])
def create_invoice():
    body = raw_body()
    contract = body_ref(body, "contract_id", db.contracts, "ERR_CONTRACT_NOT_FOUND")  # 6
    body = validate_body(body, INVOICE_SCHEMA)  # 9
    tournament = domain.tournament_of_contract(contract)
    require_reconciling(tournament)  # 15
    require_executed(contract)  # 16

    for other in domain.invoices_of_contract(contract["id"]):  # 41
        if other["period_label"] == body["period_label"]:
            raise ApiError(
                "ERR_DUPLICATE_INVOICE_PERIOD",
                "period_label is already used on this contract.",
            )

    scope = sorted(
        [
            b
            for b in domain.bookings_of_contract(contract["id"])
            if b["booking_status"] == "CHECKED_OUT" and b["rebate_status"] == "ACCRUED"
        ],
        key=sort_key,
    )
    invoiced_nights = sum(b["actualized_room_nights"] for b in scope)
    if not scope or invoiced_nights < 1:  # 51
        raise ApiError(
            "ERR_NO_BILLABLE_ROOM_NIGHTS",
            "The invoice scope contains no billable room night.",
        )

    total_nights = domain.contract_total_checked_out_nights(contract["id"])
    invoiced_cents = 0
    for booking in scope:  # rounded per line, then summed
        invoiced_cents += calc.rebate_line_cents(
            contract, booking["actualized_room_nights"], total_nights
        )

    per_block = 0
    threshold_total = 0
    actual_total = 0
    for block in domain.blocks_of_contract(contract["id"]):
        if block["status"] not in domain.COUNTED_BLOCK_STATUSES:
            continue
        nights = day_span(
            parse_date(block["arrival_date"]), parse_date(block["departure_date"])
        )
        threshold = calc.block_threshold_room_nights(
            block["block_size_rooms"], nights, contract["attrition_threshold_pct"]
        )
        actual = block["actualized_room_nights"]
        per_block += max(0, threshold - actual)
        threshold_total += threshold
        actual_total += actual
    aggregate = max(0, threshold_total - actual_total)

    penalty = per_block * contract["attrition_penalty_rate_cents_per_room_night"]
    total_due = max(0, invoiced_cents - penalty)

    row = versioned_row(
        {
            "contract_id": contract["id"],
            "period_label": body["period_label"],
            "status": "DRAFT",
            "invoiced_room_nights": invoiced_nights,
            "invoiced_rebate_cents": invoiced_cents,
            "attrition_shortfall_room_nights_per_block": per_block,
            "attrition_shortfall_room_nights_aggregate": aggregate,
            "attrition_penalty_cents": penalty,
            "total_due_cents": total_due,
            "collected_cents": 0,
            "written_off_cents": 0,
            "outstanding_cents": total_due,
            "distributed_cents": 0,
            "dispute_note": None,
        }
    )
    db.invoices[row["id"]] = row

    for booking in scope:
        booking["rebate_status"] = "INVOICED"
        domain.bump(booking)

    return object_response(row, 201)


@bp.get("/housing/rebate-invoices/<invoice_id>")
@endpoint(["HousingManager", "HotelRepresentative", "RightsHolder"])
def read_invoice(invoice_id):
    row = path_row(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")  # 5
    return object_response(row)


@bp.get("/housing/rebate-invoices")
@endpoint(["HousingManager", "HotelRepresentative", "RightsHolder"])
def list_invoices():
    filters = parse_filters({"contract_id": None, "status": INVOICE_STATUSES})  # 9
    return list_response(filter_rows(list(db.invoices.values()), filters))


LIFECYCLE_SCHEMA = {
    "action": field("enum", required=True, members=("ISSUE", "DISPUTE", "WRITE_OFF")),
    "dispute_note": field("string"),
}

LIFECYCLE_ACTION_ROLES = {
    "ISSUE": "HousingManager",
    "DISPUTE": "HotelRepresentative",
    "WRITE_OFF": "HousingManager",
}


@bp.post("/housing/rebate-invoices/<invoice_id>/lifecycle")
@endpoint(["HousingManager", "HotelRepresentative"])
def invoice_lifecycle(invoice_id):
    invoice = path_row(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")  # 5
    contract = db.contracts[invoice["contract_id"]]
    domain.hotel_scope_contract(contract)  # 8
    body = validate_body(raw_body(), LIFECYCLE_SCHEMA)  # 9
    action = body["action"]
    if LIFECYCLE_ACTION_ROLES[action] != g.role:  # 10
        raise ApiError(
            "ERR_ACTION_ROLE_MISMATCH",
            "Action %s is not available to role %s." % (action, g.role),
        )

    tournament = domain.tournament_of_contract(contract)

    if action == "ISSUE":
        if invoice["status"] != "DRAFT":  # 13
            raise invalid_state("Only a DRAFT invoice may be issued.")
        if invoice["total_due_cents"] < 1:  # 52
            raise ApiError(
                "ERR_INVOICE_TOTAL_NOT_POSITIVE",
                "An invoice with no amount due may not be issued.",
            )
        invoice["status"] = "ISSUED"
        domain.bump(invoice)
        domain.try_reconcile_tournament(tournament)
    elif action == "DISPUTE":
        if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):  # 13
            raise invalid_state("Only an ISSUED or PARTIALLY_PAID invoice may be disputed.")
        invoice["status"] = "DISPUTED"
        if body["dispute_note"] is not None:
            invoice["dispute_note"] = body["dispute_note"]
        domain.bump(invoice)
    else:
        if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):  # 13
            raise invalid_state("The invoice is not in a writable-off state.")
        invoice["written_off_cents"] = invoice["outstanding_cents"]
        invoice["outstanding_cents"] = 0
        invoice["status"] = "WRITTEN_OFF"
        domain.bump(invoice)
        target = "SHORT_PAID" if invoice["collected_cents"] > 0 else "WRITTEN_OFF"
        domain.resolve_invoiced_bookings(contract, target)
        domain.try_settle_tournament(tournament)

    return object_response(invoice)


REMIT_SCHEMA = {"amount_cents": field("integer", required=True)}


@bp.post("/housing/rebate-invoices/<invoice_id>/remit")
@endpoint(["HotelRepresentative"])
def remit_invoice(invoice_id):
    invoice = path_row(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")  # 5
    contract = db.contracts[invoice["contract_id"]]
    domain.hotel_scope_contract(contract)  # 8
    body = validate_body(raw_body(), REMIT_SCHEMA)  # 9
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):  # 13
        raise invalid_state("The invoice does not accept a remittance.")

    amount = body["amount_cents"]
    if amount < 1 or amount > invoice["outstanding_cents"]:  # 50
        raise ApiError(
            "ERR_REMITTANCE_EXCEEDS_OUTSTANDING",
            "amount_cents must be between 1 and the invoice's outstanding balance.",
        )

    clears = amount == invoice["outstanding_cents"]
    if not clears and invoice["status"] == "DISPUTED":  # 13 (no partial path out of DISPUTED)
        raise invalid_state("A DISPUTED invoice accepts only a full clearing remittance.")

    tournament = domain.tournament_of_contract(contract)

    if clears:
        invoice["collected_cents"] = invoice["total_due_cents"] - invoice["written_off_cents"]
        invoice["outstanding_cents"] = 0
        invoice["status"] = "PAID"
        domain.bump(invoice)
        domain.resolve_invoiced_bookings(contract, "COLLECTED")
        domain.try_settle_tournament(tournament)
    else:
        invoice["collected_cents"] = invoice["collected_cents"] + amount
        invoice["outstanding_cents"] = (
            invoice["total_due_cents"]
            - invoice["collected_cents"]
            - invoice["written_off_cents"]
        )
        invoice["status"] = "PARTIALLY_PAID"
        domain.bump(invoice)

    return object_response(invoice)


# ---------------------------------------------------------------------------
# RevenueDistribution
# ---------------------------------------------------------------------------

DISTRIBUTION_SCHEMA = {
    "tournament_id": field("id", required=True),
    "source_invoice_id": field("id", required=True),
    "expected_invoice_version": field("integer", required=True),
}


@bp.post("/housing/revenue-distributions")
@endpoint(["HousingManager"])
def create_distribution():
    body = raw_body()
    tournament = body_ref(body, "tournament_id", db.tournaments, "ERR_TOURNAMENT_NOT_FOUND")  # 6
    invoice = body_ref(body, "source_invoice_id", db.invoices, "ERR_INVOICE_NOT_FOUND")  # 6
    body = validate_body(body, DISTRIBUTION_SCHEMA)  # 9

    if body["expected_invoice_version"] != invoice["version"]:  # 12
        raise ApiError(
            "ERR_STALE_INVOICE_VERSION",
            "expected_invoice_version does not match the invoice's version.",
        )
    if invoice["status"] not in ("PARTIALLY_PAID", "PAID"):  # 19
        raise ApiError(
            "ERR_INVOICE_NOT_COLLECTED",
            "The source invoice must be PARTIALLY_PAID or PAID.",
        )

    split = calc.revenue_split(
        invoice["collected_cents"],
        tournament["share_pct_organizer"],
        tournament["share_pct_rights_holder"],
        tournament["share_pct_destination"],
    )
    row = versioned_row(
        {
            "tournament_id": tournament["id"],
            "source_invoice_id": invoice["id"],
            "status": "CALCULATED",
            "gross_collected_cents": invoice["collected_cents"],
            "admin_fee_pct": split["admin_fee_pct"],
            "admin_fee_cents": split["admin_fee_cents"],
            "distributable_cents": split["distributable_cents"],
            "organizer_cents": split["organizer_cents"],
            "rights_holder_cents": split["rights_holder_cents"],
            "destination_cents": split["destination_cents"],
            "rounding_remainder_cents": split["rounding_remainder_cents"],
            "approved_by_user_id": None,
        }
    )
    db.distributions[row["id"]] = row

    invoice["distributed_cents"] = sum(
        d["gross_collected_cents"] for d in domain.distributions_of_invoice(invoice["id"])
    )
    domain.bump(invoice)
    return object_response(row, 201)


@bp.get("/housing/revenue-distributions/<distribution_id>")
@endpoint(["HousingManager", "RightsHolder"])
def read_distribution(distribution_id):
    row = path_row(db.distributions, distribution_id, "ERR_DISTRIBUTION_NOT_FOUND")  # 5
    return object_response(row)


@bp.get("/housing/revenue-distributions")
@endpoint(["HousingManager", "RightsHolder"])
def list_distributions():
    filters = parse_filters(
        {
            "tournament_id": None,
            "source_invoice_id": None,
            "status": DISTRIBUTION_STATUSES,
        }
    )  # 9
    return list_response(filter_rows(list(db.distributions.values()), filters))


ADVANCE_SCHEMA = {"action": field("enum", required=True, members=("APPROVE", "PAY"))}

ADVANCE_ACTION_ROLES = {"APPROVE": "RightsHolder", "PAY": "HousingManager"}


@bp.post("/housing/revenue-distributions/<distribution_id>/advance")
@endpoint(["HousingManager", "RightsHolder"])
def advance_distribution(distribution_id):
    row = path_row(db.distributions, distribution_id, "ERR_DISTRIBUTION_NOT_FOUND")  # 5
    body = validate_body(raw_body(), ADVANCE_SCHEMA)  # 9
    action = body["action"]
    if ADVANCE_ACTION_ROLES[action] != g.role:  # 10
        raise ApiError(
            "ERR_ACTION_ROLE_MISMATCH",
            "Action %s is not available to role %s." % (action, g.role),
        )

    tournament = db.tournaments[row["tournament_id"]]

    if action == "APPROVE":
        if row["status"] != "CALCULATED":  # 13
            raise invalid_state("Only a CALCULATED distribution may be approved.")
        for complaint in db.complaints.values():  # 25
            if (
                complaint["tournament_id"] == tournament["id"]
                and complaint["category"] == "REBATE_TRANSPARENCY"
                and complaint["status"] == "UPHELD"
                and complaint["adjudicated_by_user_id"] == g.user_id
            ):
                raise ApiError(
                    "ERR_SOD_DISTRIBUTION_APPROVER_CONFLICT",
                    "An upholder of a rebate-transparency complaint may not approve this payout.",
                )
        row["status"] = "APPROVED"
        row["approved_by_user_id"] = g.user_id
        domain.bump(row)
    else:
        if row["status"] != "APPROVED":  # 13
            raise invalid_state("Only an APPROVED distribution may be paid.")
        row["status"] = "PAID"
        domain.bump(row)
        domain.try_settle_tournament(tournament)

    return object_response(row)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_SCHEMA = {"to_iso8601": field("datetime", required=True)}


@bp.post("/_clock/set_current_utc")
@endpoint(["HousingManager"])
def set_current_utc():
    body = validate_body(raw_body(), CLOCK_SCHEMA)  # 9
    db.current_utc = parse_datetime(body["to_iso8601"])
    return object_response({"current_utc": now_iso()})
