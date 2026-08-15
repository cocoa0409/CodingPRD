"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before each test). Setup calls use
get_success_data() so failures surface as clear "Setup failed" errors.

Identity threading: TeamMember is entity-backed (X-User-ID == member id), so
dispute/submit calls use make_team_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO, TEST_DEFAULTS
from .factories import (
    create_team_payload, create_season_payload, create_trip_payload,
    create_member_payload, create_charter_contract_payload, create_flight_leg_payload,
    create_manifest_entry_payload, create_hotel_block_payload,
    create_room_assignment_payload, create_per_diem_payload, create_equipment_payload,
    create_contingency_payload, create_credential_payload,
)
from .test_users import TEST_USERS, make_team_member_headers

OPS = TEST_USERS["ops_admin_headers"]
MGR = TEST_USERS["manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]
EQ = TEST_USERS["equipment_headers"]
SEC = TEST_USERS["security_headers"]
APPR = TEST_USERS["approver_headers"]
VENDOR = TEST_USERS["vendor_headers"]
ANY = TEST_USERS["any_headers"]


# ─── Tier 0: clock ────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.8). Returns the clock response data."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def reset_clock():
    """Restore the logical clock to its startup instant."""
    return set_clock(CLOCK_START_ISO)


# ─── Tier 1: base hierarchy ───────────────────────────────────────────

def create_team(**overrides):
    return get_success_data(api_client.create_team(create_team_payload(**overrides), OPS))


def create_season(team_id, **overrides):
    return get_success_data(
        api_client.create_season(team_id, create_season_payload(**overrides), FIN))


def create_trip(team_id, season_id, **overrides):
    return get_success_data(
        api_client.create_trip(team_id, create_trip_payload(season_id, **overrides), MGR))


def setup_team_season(budget_cents=TEST_DEFAULTS["TRAVEL_BUDGET_CENTS"], **team_overrides):
    """Team + open season. Returns (team, season)."""
    reset_clock()
    team = create_team(**team_overrides)
    season = create_season(team["id"], travel_budget_cents=budget_cents)
    return team, season


def setup_team_season_trip(budget_cents=TEST_DEFAULTS["TRAVEL_BUDGET_CENTS"],
                           trip_overrides=None, **team_overrides):
    """Team + open season + DRAFT trip. Returns (team, season, trip)."""
    team, season = setup_team_season(budget_cents, **team_overrides)
    trip = create_trip(team["id"], season["id"], **(trip_overrides or {}))
    return team, season, trip


# ─── Tier 2: roster, legs, contracts, hotel blocks ────────────────────

def add_member(team_id, trip_id, **overrides):
    return get_success_data(
        api_client.add_member(team_id, trip_id, create_member_payload(**overrides), MGR))


def create_leg(team_id, trip_id, **overrides):
    return get_success_data(
        api_client.create_flight_leg(team_id, trip_id,
                                     create_flight_leg_payload(**overrides), COORD))


def create_and_book_leg(team_id, trip_id, **overrides):
    """Create a leg and move it PLANNED -> BOOKED. Returns the booked leg."""
    leg = create_leg(team_id, trip_id, **overrides)
    return get_success_data(api_client.book_leg(team_id, trip_id, leg["id"], COORD))


def create_contract(team_id, trip_id, **overrides):
    return get_success_data(
        api_client.create_charter_contract(
            team_id, trip_id, create_charter_contract_payload(**overrides), MGR))


def create_executed_contract(team_id, trip_id, **overrides):
    """Draft -> submit -> countersign -> execute. Returns TEAM_EXECUTED contract."""
    contract = create_contract(team_id, trip_id, **overrides)
    get_success_data(api_client.submit_contract(team_id, trip_id, contract["id"], MGR))
    countersigned = get_success_data(
        api_client.countersign_contract(team_id, trip_id, contract["id"], VENDOR))
    return get_success_data(
        api_client.execute_contract(
            team_id, trip_id, contract["id"], countersigned["version"], FIN))


def create_active_contract_with_leg(team_id, trip_id, contract_overrides=None,
                                    leg_overrides=None):
    """Executed contract + one charter leg booked on it (contract flips to ACTIVE).
    Returns (contract, leg)."""
    contract = create_executed_contract(team_id, trip_id, **(contract_overrides or {}))
    leg_kwargs = {"is_charter": True, "contract_id": contract["id"]}
    leg_kwargs.update(leg_overrides or {})
    leg = create_and_book_leg(team_id, trip_id, **leg_kwargs)
    return contract, leg


def create_hotel_block(team_id, trip_id, **overrides):
    return get_success_data(
        api_client.create_hotel_block(team_id, trip_id,
                                      create_hotel_block_payload(**overrides), COORD))


def add_manifest_entry(team_id, trip_id, leg_id, member_id, **overrides):
    return get_success_data(
        api_client.add_manifest_entry(
            team_id, trip_id, leg_id,
            create_manifest_entry_payload(member_id, **overrides), COORD))


def confirm_manifest_entry(team_id, trip_id, leg_id, entry_id):
    return get_success_data(
        api_client.confirm_manifest_entry(team_id, trip_id, leg_id, entry_id, COORD))


def create_per_diem(team_id, trip_id, member_id, **overrides):
    return get_success_data(
        api_client.create_per_diem(team_id, trip_id, member_id,
                                   create_per_diem_payload(**overrides), FIN))


def create_equipment(team_id, trip_id, **overrides):
    return get_success_data(
        api_client.create_equipment(team_id, trip_id,
                                    create_equipment_payload(**overrides), EQ))


# ─── Tier 3: lockable / locked trips ──────────────────────────────────

def setup_lockable_trip(budget_cents=TEST_DEFAULTS["TRAVEL_BUDGET_CENTS"],
                        trip_overrides=None, member_overrides=None,
                        leg_overrides=None, hotel_overrides=None):
    """Trip with one IN member, one BOOKED outbound leg, and one HOLDING hotel
    block — every trip-lock precondition of PRD §3.2 satisfied.

    Returns dict(team, season, trip, member, leg, block)."""
    team, season, trip = setup_team_season_trip(budget_cents, trip_overrides)
    member = add_member(team["id"], trip["id"], **(member_overrides or {}))
    leg = create_and_book_leg(team["id"], trip["id"], **(leg_overrides or {}))
    block = create_hotel_block(team["id"], trip["id"], **(hotel_overrides or {}))
    return {"team": team, "season": season, "trip": trip,
            "member": member, "leg": leg, "block": block}


def lock_trip(ctx):
    """Lock the trip from ctx with a freshly-read expected_trip_version.
    Returns the LOCKED trip."""
    fresh = get_success_data(api_client.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
    return get_success_data(
        api_client.lock_trip(ctx["team"]["id"], ctx["trip"]["id"], fresh["version"], MGR))


def setup_locked_trip(**kwargs):
    """setup_lockable_trip + lock. Returns ctx with ctx["trip"] now LOCKED."""
    ctx = setup_lockable_trip(**kwargs)
    ctx["trip"] = lock_trip(ctx)
    return ctx


def setup_disrupted_trip(ctx=None, **kwargs):
    """LOCKED trip + a contingency opened on its booked leg -> DISRUPTED,
    leg -> REBOOKING (PRD §3.9). Returns ctx with ctx["event"]."""
    if ctx is None:
        ctx = setup_locked_trip(**kwargs)
    event = get_success_data(
        api_client.create_contingency(
            ctx["team"]["id"], ctx["trip"]["id"],
            create_contingency_payload(ctx["leg"]["id"]), MGR))
    ctx["event"] = event
    ctx["trip"] = get_success_data(
        api_client.get_trip(ctx["team"]["id"], ctx["trip"]["id"], ANY))
    return ctx


# ─── Tier 4: charter / manifest / equipment composites ────────────────

def setup_trip_with_executed_contract(budget_cents=1000000000,
                                      contract_overrides=None,
                                      num_members=0,
                                      trip_overrides=None):
    """Team/season/trip + executed charter contract (+ N IN members).
    Returns dict(team, season, trip, contract, members)."""
    team, season, trip = setup_team_season_trip(budget_cents, trip_overrides)
    members = [add_member(team["id"], trip["id"]) for _ in range(num_members)]
    contract = create_executed_contract(team["id"], trip["id"],
                                        **(contract_overrides or {}))
    return {"team": team, "season": season, "trip": trip,
            "contract": contract, "members": members}


def setup_charter_leg_booked(budget_cents=1000000000,
                             contract_overrides=None,
                             num_members=1,
                             leg_overrides=None,
                             trip_overrides=None):
    """Executed contract + charter leg BOOKED (contract ACTIVE) + N IN members.
    Returns dict(team, season, trip, contract, leg, members)."""
    ctx = setup_trip_with_executed_contract(budget_cents, contract_overrides,
                                            num_members, trip_overrides)
    leg_kwargs = {"is_charter": True, "contract_id": ctx["contract"]["id"]}
    leg_kwargs.update(leg_overrides or {})
    leg = create_and_book_leg(ctx["team"]["id"], ctx["trip"]["id"], **leg_kwargs)
    ctx["leg"] = leg
    # Refresh contract (first book flips TEAM_EXECUTED -> ACTIVE).
    ctx["contract"] = get_success_data(
        api_client.get_charter_contract(ctx["team"]["id"], ctx["trip"]["id"],
                                        ctx["contract"]["id"], ANY))
    return ctx


def setup_disrupted_charter_trip(num_members=2, budget_cents=1000000000,
                                 base_price_cents=8000000,
                                 fuel_surcharge_cap_cents=800000,
                                 penalty_bands=None,
                                 game_tipoff_utc="2026-12-20T00:00:00Z",
                                 destination_code="BOS"):
    """LOCKED trip with ACTIVE charter contract, one BOOKED charter leg carrying
    PENDING manifest entries for each member, one HOLDING hotel block, then a
    contingency opened -> trip DISRUPTED. For trip-cancel cascade tests.

    Returns dict(team, season, trip, contract, leg, block, members, entries, event)."""
    bands = penalty_bands or [{"days_before": 30, "penalty_pct": 10}]
    ctx = setup_charter_leg_booked(
        budget_cents=budget_cents,
        contract_overrides={
            "base_price_cents": base_price_cents,
            "fuel_surcharge_cap_cents": fuel_surcharge_cap_cents,
            "penalty_bands": bands,
        },
        num_members=num_members,
        trip_overrides={"game_tipoff_utc": game_tipoff_utc,
                        "destination_code": destination_code},
    )
    entries = [add_manifest_entry(ctx["team"]["id"], ctx["trip"]["id"],
                                  ctx["leg"]["id"], m["id"],
                                  seat_assignment=f"{i + 1}A")
               for i, m in enumerate(ctx["members"])]
    block = create_hotel_block(ctx["team"]["id"], ctx["trip"]["id"])
    ctx["entries"] = entries
    ctx["block"] = block
    ctx["trip"] = lock_trip(ctx)
    return setup_disrupted_trip(ctx)


# ─── Tier 5: full lifecycle / terminal states ─────────────────────────

def setup_closed_trip(budget_cents=TEST_DEFAULTS["TRAVEL_BUDGET_CENTS"], **kwargs):
    """Entire lifecycle through CLOSED: lockable trip -> lock -> depart ->
    arrive (last leg) -> RECOVERING -> close. Returns ctx with CLOSED trip."""
    ctx = setup_locked_trip(budget_cents=budget_cents, **kwargs)
    get_success_data(
        api_client.depart_leg(ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"], COORD))
    get_success_data(
        api_client.arrive_leg(ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"], COORD))
    ctx["trip"] = get_success_data(
        api_client.close_trip(ctx["team"]["id"], ctx["trip"]["id"], FIN))
    return ctx


def setup_closed_season():
    """Team + season with zero trips, closed immediately (all-trips-terminal
    precondition vacuously true, projected == committed == 0)."""
    team, season = setup_team_season()
    closed = get_success_data(api_client.close_season(team["id"], season["id"], FIN))
    return team, closed


# ─── Tier 6: credential workflow composites ───────────────────────────

def create_credential_request(team_id, trip_id, member_id, **overrides):
    """Submit a credential as the member themselves (SoD anchor)."""
    return get_success_data(
        api_client.create_credential(
            team_id, trip_id, create_credential_payload(member_id, **overrides),
            make_team_member_headers(member_id)))


def setup_credential_in_review(team_id, trip_id, member_id,
                               reviewer_id="sec-officer-1", **overrides):
    """SUBMITTED -> SECURITY_REVIEW by a distinct SecurityOfficer."""
    from .test_users import make_security_officer_headers
    cred = create_credential_request(team_id, trip_id, member_id, **overrides)
    return get_success_data(
        api_client.security_review_credential(
            team_id, trip_id, cred["id"], make_security_officer_headers(reviewer_id)))


def setup_approved_credential(team_id, trip_id, member_id,
                              reviewer_id="sec-officer-1",
                              approver_id="venue-approver-1", **overrides):
    """Full credential chain through APPROVED with three distinct user ids."""
    from .test_users import make_security_officer_headers, make_approver_headers
    cred = create_credential_request(team_id, trip_id, member_id, **overrides)
    get_success_data(
        api_client.security_review_credential(
            team_id, trip_id, cred["id"], make_security_officer_headers(reviewer_id)))
    return get_success_data(
        api_client.approve_credential(
            team_id, trip_id, cred["id"], make_approver_headers(approver_id)))


# ─── Tier 7: hotel block in NAME_LIST_DUE ─────────────────────────────

def setup_block_name_list_due(team_id, trip_id, members, clock_iso,
                              block_overrides=None):
    """Hotel block moved HOLDING -> NAME_LIST_DUE by advancing the logical clock
    to/past cutoff_date - 7d, with one room assignment per IN member.
    Returns (block, assignments)."""
    block_kwargs = {"room_count": max(1, len(members))}
    block_kwargs.update(block_overrides or {})
    block = create_hotel_block(team_id, trip_id, **block_kwargs)
    assignments = [get_success_data(
        api_client.create_room_assignment(
            team_id, trip_id, block["id"],
            create_room_assignment_payload(m["id"]), COORD))
        for m in members]
    set_clock(clock_iso)
    block = get_success_data(api_client.get_hotel_block(team_id, trip_id, block["id"], ANY))
    return block, assignments
