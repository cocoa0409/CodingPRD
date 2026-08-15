"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the server is re-launched before every test, so nothing carries
over). Internal calls use get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_aircraft_payload,
    create_card_payload,
    create_member_payload,
    create_peak_window_payload,
    create_blackout_window_payload,
    create_program_payload,
    create_trip_payload,
)
from .test_users import TEST_USERS, make_member_headers

OPS = TEST_USERS["ops_headers"]


# --- Clock / sweep -----------------------------------------------------------


def set_clock(to_iso8601: str = "2026-06-01T00:00:00Z"):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def run_ops_sweep():
    return get_success_data(api_client.ops_run(OPS))


# --- Tier 1: single-entity creation / state progression ----------------------


def create_program(**overrides) -> dict:
    """Ops creates a CardProgram. Returns the created program."""
    resp = api_client.create_program(create_program_payload(**overrides), OPS)
    return get_success_data(resp)


def create_member(**overrides) -> dict:
    """Ops registers a Member (starts ACTIVE). Returns the member."""
    resp = api_client.create_member(create_member_payload(**overrides), OPS)
    return get_success_data(resp)


def purchase_card(member_id: str, program_id: str) -> dict:
    """Ops purchases a JetCard for the member (PENDING_PAYMENT)."""
    resp = api_client.create_card(member_id, create_card_payload(program_id), OPS)
    return get_success_data(resp)


def activate_card(card_id: str) -> dict:
    """Ops activates the card: PURCHASE_GRANT + EscrowAccount created."""
    return get_success_data(api_client.activate_card(card_id, OPS))


def suspend_card(card_id: str) -> dict:
    return get_success_data(api_client.suspend_card(card_id, OPS))


def resume_card(card_id: str) -> dict:
    return get_success_data(api_client.resume_card(card_id, OPS))


def create_aircraft(**overrides) -> dict:
    """Ops registers an Aircraft (starts AVAILABLE)."""
    resp = api_client.create_aircraft(create_aircraft_payload(**overrides), OPS)
    return get_success_data(resp)


def get_aircraft(aircraft_id: str) -> dict:
    return get_success_data(api_client.get_aircraft(aircraft_id, OPS))


def create_peak_window(program_id: str, **overrides) -> dict:
    resp = api_client.create_peak_window(
        program_id, create_peak_window_payload(**overrides), OPS
    )
    return get_success_data(resp)


def create_blackout_window(program_id: str, **overrides) -> dict:
    resp = api_client.create_blackout_window(
        program_id, create_blackout_window_payload(**overrides), OPS
    )
    return get_success_data(resp)


# --- Tier 2: entity hierarchy ------------------------------------------------


def setup_active_card(
    program_overrides: dict = None,
    member_overrides: dict = None,
    clock: str = "2026-06-01T00:00:00Z",
):
    """Program + member + purchased card + activation. Returns (program, member, card)."""
    set_clock(clock)
    program = create_program(**(program_overrides or {}))
    member = create_member(**(member_overrides or {}))
    card = purchase_card(member["id"], program["id"])
    card = activate_card(card["id"])
    return program, member, card


def get_card(card_id: str) -> dict:
    return get_success_data(api_client.get_card(card_id, OPS))


def get_card_projection(card_id: str) -> dict:
    return get_success_data(api_client.get_card_projection(card_id, OPS))


def get_escrow(card_id: str) -> dict:
    """Escrow is 1:1 with the card; the read returns an array of 0 or 1."""
    data = get_success_data(api_client.get_escrow(card_id, OPS))
    assert isinstance(data, list) and len(data) == 1, "expected exactly one escrow account"
    return data[0]


def get_ledger_entries(card_id: str, entry_kind: str = None) -> list:
    params = {"entry_kind": entry_kind} if entry_kind else None
    return get_success_data(api_client.list_ledger(card_id, OPS, params=params))


# --- Tier 3: trip lifecycle shortcuts ----------------------------------------


def create_trip(card_id: str, member_id: str, **overrides) -> dict:
    """Member creates a TripRequest in QUOTE."""
    mh = make_member_headers(member_id)
    resp = api_client.create_trip(card_id, create_trip_payload(**overrides), mh)
    return get_success_data(resp)


def confirm_trip(trip_id: str, member_id: str) -> dict:
    mh = make_member_headers(member_id)
    return get_success_data(api_client.confirm_trip(trip_id, mh))


def dispatch_trip(trip_id: str, aircraft_id: str) -> dict:
    return get_success_data(
        api_client.dispatch_trip(trip_id, {"dispatched_aircraft_id": aircraft_id}, OPS)
    )


def depart_trip(trip_id: str) -> dict:
    return get_success_data(api_client.depart_trip(trip_id, OPS))


def get_trip_legs(trip_id: str) -> list:
    data = get_success_data(api_client.list_trip_legs(trip_id, OPS))
    assert isinstance(data, list), "expected a list of legs"
    return data


def complete_trip(trip_id: str, block_minutes) -> dict:
    """Complete an IN_FLIGHT trip. ``block_minutes`` is an int (applied to every
    leg) or a list of per-leg minute values aligned with leg order."""
    legs = get_trip_legs(trip_id)
    if isinstance(block_minutes, int):
        minutes = [block_minutes] * len(legs)
    else:
        minutes = list(block_minutes)
    payload = {
        "legs": [
            {"leg_seq": leg["leg_seq"], "actual_block_minutes": minutes[i]}
            for i, leg in enumerate(legs)
        ]
    }
    return get_success_data(api_client.complete_trip(trip_id, payload, OPS))


def fly_trip(card_id: str, member_id: str, aircraft_id: str,
             block_minutes=120, trip_overrides: dict = None):
    """Full lifecycle: create -> confirm -> dispatch -> depart -> complete.
    Returns (completed_trip, legs)."""
    trip = create_trip(card_id, member_id, **(trip_overrides or {}))
    confirm_trip(trip["id"], member_id)
    dispatch_trip(trip["id"], aircraft_id)
    depart_trip(trip["id"])
    completed = complete_trip(trip["id"], block_minutes)
    return completed, get_trip_legs(trip["id"])


def get_trip(trip_id: str) -> dict:
    return get_success_data(api_client.get_trip(trip_id, OPS))


def get_trip_invoice(trip_id: str) -> dict:
    """Invoice is 1:1 with the trip; the read returns an array of 0 or 1."""
    data = get_success_data(api_client.get_trip_invoice(trip_id, OPS))
    assert isinstance(data, list) and len(data) == 1, "expected exactly one invoice"
    return data[0]


# --- Tier 4: refund / upgrade helpers ----------------------------------------


def create_refund(card_id: str, member_id: str) -> dict:
    """OCC-guarded refund creation: reads the current card version first."""
    version = get_card(card_id)["version"]
    mh = make_member_headers(member_id)
    resp = api_client.create_refund(card_id, {"expected_card_version": version}, mh)
    return get_success_data(resp)


def submit_refund(refund_id: str, member_id: str) -> dict:
    mh = make_member_headers(member_id)
    return get_success_data(api_client.submit_refund(refund_id, mh))


def approve_refund(refund_id: str) -> dict:
    return get_success_data(api_client.approve_refund(refund_id, OPS))


def settle_refund(refund_id: str) -> dict:
    return get_success_data(api_client.settle_refund(refund_id, OPS))


def get_refund_via_list(card_id: str, refund_id: str) -> dict:
    data = get_success_data(api_client.list_refunds(card_id, OPS))
    matches = [r for r in data if r["id"] == refund_id]
    assert len(matches) == 1, f"refund {refund_id} not found in card refund list"
    return matches[0]


# --- Tier 5: terminal states --------------------------------------------------


def expire_card_via_sweep(card_id: str, past_expiry_clock: str) -> dict:
    """Advance the logical clock past expires_at and run the ops sweep.
    Returns the card after the sweep."""
    set_clock(past_expiry_clock)
    run_ops_sweep()
    return get_card(card_id)
