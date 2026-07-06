"""Composite setup helpers for the Snow Tubing Winter Park API.

Every test runs against a freshly launched, empty server, so each fixture builds
its full precondition chain from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: GuestPatron / GroupHost are entity-backed roles. Any
ownership-gated call uses make_guest_patron_headers(patron_id) /
make_group_host_headers(host_id) with the real Patron.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_guest_patron_headers,
    make_group_host_headers,
)
from . import factories as f

# Opaque-role headers (shared constants are canonical for opaque roles).
OPERATOR = TEST_USERS["park_operator_headers"]
MARSHAL = TEST_USERS["safety_marshal_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Low-level single-step helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (also runs the daily sweep)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPERATOR))


def create_park(**overrides) -> dict:
    """Create a park (bootstrap, no auth needed)."""
    return get_success_data(api_client.create_park(f.create_park_payload(**overrides), ANON))


def create_patron(**overrides) -> dict:
    """Register a patron (bootstrap, no auth needed)."""
    return get_success_data(api_client.create_patron(f.create_patron_payload(**overrides), ANON))


def create_lane(park_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_lane(park_id, f.create_lane_payload(**overrides), OPERATOR))


def create_time_block(park_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_time_block(park_id, f.create_time_block_payload(**overrides), OPERATOR))


def activate_block(time_block_id: str) -> dict:
    return get_success_data(api_client.activate_time_block(time_block_id, OPERATOR))


def create_weather_log(park_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_weather_log(park_id, f.create_weather_log_payload(**overrides), OPERATOR))


def sign_waiver(patron_id: str, park_id: str, **overrides) -> dict:
    payload = f.create_waiver_payload(patron_id=patron_id, park_id=park_id, **overrides)
    return get_success_data(api_client.create_waiver(payload, make_guest_patron_headers(patron_id)))


def create_season_pass(park_id: str, holder_patron_id: str, **overrides) -> dict:
    payload = f.create_season_pass_payload(park_id=park_id, holder_patron_id=holder_patron_id, **overrides)
    return get_success_data(api_client.create_season_pass(payload, OPERATOR))


def create_ticket(park_id: str, time_block_id: str, holder_patron_id: str, **overrides) -> dict:
    payload = f.create_ticket_payload(
        park_id=park_id, time_block_id=time_block_id, holder_patron_id=holder_patron_id, **overrides
    )
    return get_success_data(api_client.create_ticket(payload, make_guest_patron_headers(holder_patron_id)))


def block_version(time_block_id: str, as_patron_id: str = None) -> int:
    """Read the current TimeBlock.version (the OCC token)."""
    headers = make_guest_patron_headers(as_patron_id) if as_patron_id else OPERATOR
    tb = get_success_data(api_client.get_time_block(time_block_id, headers))
    return tb["version"]


def confirm_ticket(ticket_id: str, holder_patron_id: str, time_block_id: str) -> dict:
    """Confirm a ticket using the current block version as the OCC token."""
    v = block_version(time_block_id, holder_patron_id)
    return get_success_data(
        api_client.confirm_ticket(ticket_id, v, make_guest_patron_headers(holder_patron_id))
    )


def dispatch_tube(ticket_id: str, tube_size: str = "MEDIUM") -> dict:
    payload = f.create_equipment_rental_payload(ticket_id=ticket_id, equipment_type="TUBE", tube_size=tube_size)
    return get_success_data(api_client.create_equipment_rental(payload, MARSHAL))


def gear_up(ticket_id: str) -> dict:
    return get_success_data(api_client.gear_up_ticket(ticket_id, MARSHAL))


def board(ticket_id: str, lane_id: str, boarded_at: str) -> dict:
    payload = f.create_board_payload(lane_id=lane_id, boarded_at=boarded_at)
    return get_success_data(api_client.board_ticket(ticket_id, payload, MARSHAL))


def create_group_reservation(park_id, host_patron_id, time_block_id, **overrides) -> dict:
    payload = f.create_group_reservation_payload(
        park_id=park_id, host_patron_id=host_patron_id, time_block_id=time_block_id, **overrides
    )
    return get_success_data(api_client.create_group_reservation(payload, make_group_host_headers(host_patron_id)))


def hold_group_reservation(res_id, host_patron_id, time_block_id) -> dict:
    v = block_version(time_block_id, host_patron_id)
    return get_success_data(
        api_client.hold_group_reservation(res_id, v, make_group_host_headers(host_patron_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: Entity-hierarchy bundles
# ---------------------------------------------------------------------------

def setup_park_with_lane_and_block(
    *, clock="2026-03-01T10:30:00Z", lane_capacity=5, conveyor_cycle_seconds=30,
    block_starts="2026-03-01T10:00:00Z", block_ends="2026-03-01T12:00:00Z",
    activate=True, num_lanes=1, park_overrides=None,
):
    """Create an OPEN park, N OPEN lane(s), and one time block (optionally ACTIVE).

    Returns dict: park, lanes (list), lane (first lane), block.
    """
    if park_overrides is None:
        park_overrides = {}
    set_clock(clock)
    park = create_park(**park_overrides)
    lanes = [
        create_lane(park["id"], label=f"L{i+1}",
                    rider_capacity_per_block=lane_capacity,
                    conveyor_cycle_seconds=conveyor_cycle_seconds)
        for i in range(num_lanes)
    ]
    block = create_time_block(park["id"], starts_at=block_starts, ends_at=block_ends)
    if activate:
        block = activate_block(block["id"])
    return {"park": park, "lanes": lanes, "lane": lanes[0] if lanes else None, "block": block}


def setup_waivered_patron(park_id, *, signed_at="2026-03-01T09:00:00Z", guardian_name=None,
                          patron_overrides=None):
    """Register a patron and sign an ACTIVE waiver for them at the park.

    Returns (patron, waiver).
    """
    if patron_overrides is None:
        patron_overrides = {}
    patron = create_patron(**patron_overrides)
    extra = {}
    if guardian_name is not None:
        extra["guardian_name"] = guardian_name
    waiver = sign_waiver(patron["id"], park_id, signed_at=signed_at, **extra)
    return patron, waiver


# ---------------------------------------------------------------------------
# Tier 3: Full lifecycle shortcuts for tickets
# ---------------------------------------------------------------------------

def setup_confirmed_ticket(
    *, clock="2026-03-01T10:30:00Z", lane_capacity=5, num_lanes=1,
    block_starts="2026-03-01T10:00:00Z", block_ends="2026-03-01T12:00:00Z",
    rider_height_cm=175, rider_age_years=30, guardian_name=None, park_overrides=None,
):
    """Full chain to a CONFIRMED ticket in an ACTIVE block of an OPEN park.

    park -> lane(s) -> block(ACTIVE) -> waivered patron -> ticket -> confirm.
    Returns dict: park, lanes, lane, block, patron, waiver, ticket.
    """
    base = setup_park_with_lane_and_block(
        clock=clock, lane_capacity=lane_capacity, num_lanes=num_lanes,
        block_starts=block_starts, block_ends=block_ends, activate=True,
        park_overrides=park_overrides,
    )
    patron, waiver = setup_waivered_patron(base["park"]["id"], guardian_name=guardian_name)
    ticket = create_ticket(
        base["park"]["id"], base["block"]["id"], patron["id"],
        rider_height_cm=rider_height_cm, rider_age_years=rider_age_years,
    )
    ticket = confirm_ticket(ticket["id"], patron["id"], base["block"]["id"])
    return {**base, "patron": patron, "waiver": waiver, "ticket": ticket}


def setup_reserved_ticket(
    *, clock="2026-03-01T10:30:00Z", lane_capacity=5, num_lanes=1,
    block_starts="2026-03-01T10:00:00Z", block_ends="2026-03-01T12:00:00Z",
    activate=True, sign_waiver_flag=True, guardian_name=None,
    rider_height_cm=175, rider_age_years=30, park_overrides=None,
):
    """Chain to a RESERVED (not yet confirmed) ticket.

    Returns dict: park, lanes, lane, block, patron, waiver (or None), ticket.
    """
    base = setup_park_with_lane_and_block(
        clock=clock, lane_capacity=lane_capacity, num_lanes=num_lanes,
        block_starts=block_starts, block_ends=block_ends, activate=activate,
        park_overrides=park_overrides,
    )
    patron = create_patron()
    waiver = None
    if sign_waiver_flag:
        extra = {}
        if guardian_name is not None:
            extra["guardian_name"] = guardian_name
        waiver = sign_waiver(patron["id"], base["park"]["id"], **extra)
    ticket = create_ticket(
        base["park"]["id"], base["block"]["id"], patron["id"],
        rider_height_cm=rider_height_cm, rider_age_years=rider_age_years,
    )
    return {**base, "patron": patron, "waiver": waiver, "ticket": ticket}


def setup_geared_up_ticket(
    *, clock="2026-03-01T10:30:00Z", lane_capacity=5, num_lanes=1,
    block_starts="2026-03-01T10:00:00Z", block_ends="2026-03-01T12:00:00Z",
    rider_height_cm=175, rider_age_years=30, tube_size="MEDIUM", park_overrides=None,
):
    """Chain to a CONFIRMED + GEARED_UP ticket with a DISPATCHED TUBE.

    Returns dict: park, lanes, lane, block, patron, waiver, ticket, rental.
    """
    state = setup_confirmed_ticket(
        clock=clock, lane_capacity=lane_capacity, num_lanes=num_lanes,
        block_starts=block_starts, block_ends=block_ends,
        rider_height_cm=rider_height_cm, rider_age_years=rider_age_years,
        park_overrides=park_overrides,
    )
    rental = dispatch_tube(state["ticket"]["id"], tube_size=tube_size)
    ticket = gear_up(state["ticket"]["id"])
    return {**state, "ticket": ticket, "rental": rental}


def setup_boarded_ticket(
    *, clock="2026-03-01T10:30:00Z", lane_capacity=5,
    block_starts="2026-03-01T10:00:00Z", block_ends="2026-03-01T12:00:00Z",
    boarded_at="2026-03-01T10:30:00Z", park_overrides=None,
):
    """Chain to a ticket ON_LANE with one BOARDED ConveyorTurn.

    Returns dict: park, lanes, lane, block, patron, waiver, ticket, rental, turn.
    """
    state = setup_geared_up_ticket(
        clock=clock, lane_capacity=lane_capacity, num_lanes=1,
        block_starts=block_starts, block_ends=block_ends,
        park_overrides=park_overrides,
    )
    ticket = board(state["ticket"]["id"], state["lane"]["id"], boarded_at)
    turns = get_success_data(
        api_client.list_conveyor_turns(OPERATOR, params={"lane_id": state["lane"]["id"]})
    )
    turn = turns[0] if isinstance(turns, list) and turns else None
    return {**state, "ticket": ticket, "turn": turn}


# ---------------------------------------------------------------------------
# Tier 4: Pass / pricing targeting
# ---------------------------------------------------------------------------

def setup_pass_holder(
    *, clock="2026-03-02T09:00:00Z", tier="GOLD",
    valid_from="2026-03-01T00:00:00Z", valid_until="2026-12-01T00:00:00Z",
    resident_zip_prefixes=None, patron_zip="11111", park_overrides=None,
    block_starts="2026-03-02T10:00:00Z", block_ends="2026-03-02T12:00:00Z",
):
    """Create a park (optionally with resident prefixes), a patron, a SCHEDULED
    block, and an ACTIVE season pass of the given tier for the patron.

    Returns dict: park, patron, block, season_pass.
    """
    if park_overrides is None:
        park_overrides = {}
    if resident_zip_prefixes is not None:
        park_overrides = {**park_overrides, "resident_zip_prefixes": resident_zip_prefixes}
    set_clock(clock)
    park = create_park(**park_overrides)
    patron = create_patron(zip_code=patron_zip)
    block = create_time_block(park["id"], starts_at=block_starts, ends_at=block_ends)
    season_pass = create_season_pass(
        park["id"], patron["id"], tier=tier, valid_from=valid_from, valid_until=valid_until
    )
    return {"park": park, "patron": patron, "block": block, "season_pass": season_pass}


# ---------------------------------------------------------------------------
# Tier 5: Group reservation setups
# ---------------------------------------------------------------------------

def setup_group_park(
    *, clock="2026-03-01T09:00:00Z", num_lanes=2, lane_capacity=8,
    block_starts="2026-03-01T10:00:00Z", block_ends="2026-03-01T12:00:00Z",
    park_overrides=None,
):
    """OPEN park with N OPEN lanes, a SCHEDULED block, and a GroupHost patron.

    Returns dict: park, lanes, lane (first), block, host.
    """
    if park_overrides is None:
        park_overrides = {}
    set_clock(clock)
    park = create_park(**park_overrides)
    lanes = [
        create_lane(park["id"], label=f"L{i+1}", rider_capacity_per_block=lane_capacity)
        for i in range(num_lanes)
    ]
    block = create_time_block(park["id"], starts_at=block_starts, ends_at=block_ends)
    host = create_patron()
    return {"park": park, "lanes": lanes, "lane": lanes[0], "block": block, "host": host}
