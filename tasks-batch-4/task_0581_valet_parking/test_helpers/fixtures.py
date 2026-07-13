"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the API server (empty DB) before every test, so every helper
builds its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() (a lenient 2xx validator) so setup failures surface cleanly.

Identity threading: the Attendant role is entity_backed:Attendant (PRD §2.1). Check-in
and the retrieval flow are Attendant-role but NOT ownership-gated; recording tips IS
ownership-gated (X-User-ID must equal shift.attendant_id). Every Attendant call below
threads make_attendant_headers(<attendant id>) so ownership-gated consumers work.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_venue_payload,
    create_event_payload,
    create_lot_payload,
    create_lane_assignment_payload,
    create_attendant_payload,
    create_shift_payload,
    create_ticket_payload,
    create_damage_claim_payload,
    create_retrieval_request_payload,
    create_validation_payload,
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
)
from .test_users import TEST_USERS, make_attendant_headers

SUP = TEST_USERS["supervisor_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# ── Primitive builders ────────────────────────────────────────────────────
def create_venue(name: str = "Grand Hall", address: str = "1 Main St", **overrides) -> dict:
    return get_success_data(api_client.create_venue(
        create_venue_payload(name=name, address=address, **overrides), SUP))


def create_event(venue_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_event(
        create_event_payload(venue_id, **overrides), SUP))


def activate_event(event_id: str) -> dict:
    return get_success_data(api_client.activate_event(event_id, SUP))


def create_active_event(venue_id: str, **overrides) -> dict:
    """Create an event then activate it (SCHEDULED → ACTIVE). Returns the ACTIVE event."""
    event = create_event(venue_id, **overrides)
    return activate_event(event["id"])


def create_lot(venue_id: str, capacity: int = 5, **overrides) -> dict:
    return get_success_data(api_client.create_lot(
        create_lot_payload(venue_id, capacity=capacity, **overrides), SUP))


def create_attendant(venue_id: str, name: str = "Ana") -> dict:
    return get_success_data(api_client.create_attendant(
        create_attendant_payload(venue_id, name=name), SUP))


def create_shift(attendant_id: str, start_at: str, end_at: str, **overrides) -> dict:
    return get_success_data(api_client.create_shift(
        create_shift_payload(attendant_id, start_at, end_at, **overrides), SUP))


def create_active_shift(attendant_id: str,
                        start_at: str = "2026-06-01T07:00:00Z",
                        end_at: str = "2026-06-01T20:00:00Z", **overrides) -> dict:
    """Schedule a shift and start it (SCHEDULED → ACTIVE)."""
    shift = create_shift(attendant_id, start_at, end_at, **overrides)
    return get_success_data(api_client.start_shift(shift["id"], SUP))


def current_lot_version(lot_id: str) -> int:
    """Fetch a lot's live version (the OCC anchor for the next check-in)."""
    return get_success_data(api_client.get_lot(lot_id, SUP))["version"]


def check_in(event_id: str, lot_id: str, attendant_id: str,
             expected_lot_version=None, **overrides) -> dict:
    """Check a vehicle in. When expected_lot_version is omitted, the lot's current
    version is fetched first (so sequential check-ins are not OCC-rejected)."""
    if expected_lot_version is None:
        expected_lot_version = current_lot_version(lot_id)
    payload = create_ticket_payload(event_id, lot_id, attendant_id,
                                    expected_lot_version, **overrides)
    return get_success_data(api_client.create_ticket(
        payload, make_attendant_headers(attendant_id)))


def checkout(ticket_id: str, checkout_at: str = "2026-06-01T12:30:00Z") -> dict:
    return get_success_data(api_client.checkout_ticket(
        ticket_id, {"checkout_at": checkout_at}, CASHIER))


# ── Tier 2: standard environments ─────────────────────────────────────────
def setup_active_event_env(lot_capacity: int = 5, event_overrides=None) -> dict:
    """Venue + ACTIVE event + one lot + one attendant. Returns a dict with keys
    venue, event, lot, attendant. The most common check-in preamble."""
    venue = create_venue()
    event = create_active_event(venue["id"], **(event_overrides or {}))
    lot = create_lot(venue["id"], capacity=lot_capacity)
    attendant = create_attendant(venue["id"])
    return {"venue": venue, "event": event, "lot": lot, "attendant": attendant}


def setup_checked_in_ticket(lot_capacity: int = 5, event_overrides=None,
                            checkin_at: str = "2026-06-01T10:00:00Z",
                            estimated_departure_at: str = "2026-06-01T12:00:00Z",
                            key_tag: str = "K1", license_plate: str = "X1") -> dict:
    """setup_active_event_env + one PARKED ticket. Adds key 'ticket'."""
    env = setup_active_event_env(lot_capacity=lot_capacity, event_overrides=event_overrides)
    ticket = check_in(env["event"]["id"], env["lot"]["id"], env["attendant"]["id"],
                      checkin_at=checkin_at, estimated_departure_at=estimated_departure_at,
                      key_tag=key_tag, license_plate=license_plate)
    env["ticket"] = ticket
    return env


def setup_settled_ticket(checkout_at: str = "2026-06-01T12:30:00Z",
                         event_overrides=None) -> dict:
    """A checked-in ticket driven through checkout (park CLOSED, settlement SETTLED,
    final_fee 2900 for the default 150-minute stay). Adds key 'ticket' (post-checkout)."""
    env = setup_checked_in_ticket(event_overrides=event_overrides)
    env["ticket"] = checkout(env["ticket"]["id"], checkout_at=checkout_at)
    return env


# ── Tier 3: overflow scene ────────────────────────────────────────────────
def setup_overflow_scene() -> dict:
    """Primary lot LP (capacity 1) with overflow lot LO (capacity 5); two check-ins so
    t1 fills LP and t2 spills into LO (LP.overflow_active true, t2.in_overflow true).
    Returns keys venue, event, lo, lp, attendant, t1, t2."""
    venue = create_venue()
    event = create_active_event(venue["id"])
    lo = create_lot(venue["id"], capacity=5, name="LO", is_overflow=True)
    lp = create_lot(venue["id"], capacity=1, name="LP", overflow_lot_id=lo["id"])
    attendant = create_attendant(venue["id"])
    t1 = check_in(event["id"], lp["id"], attendant["id"],
                  expected_lot_version=lp["version"], key_tag="K1", license_plate="OV1")
    t2 = check_in(event["id"], lp["id"], attendant["id"],
                  checkin_at="2026-06-01T10:05:00Z", key_tag="K2", license_plate="OV2")
    return {"venue": venue, "event": event, "lo": lo, "lp": lp,
            "attendant": attendant, "t1": t1, "t2": t2}


# ── Tier 4: two-shift event for the tip pool ──────────────────────────────
def setup_two_shift_event(tip_split_mode: str, s1_end: str, s2_end: str,
                          s1_tips: int, s2_tips: int) -> dict:
    """ACTIVE event with the given tip_split_mode; two attendants each with one shift
    on the event ([08:00,s1_end) and [08:00,s2_end)) that declare s1_tips / s2_tips.
    Shifts are created s1 then s2 so created_at order is s1 < s2. Returns keys
    venue, event, a1, a2, s1, s2."""
    venue = create_venue()
    event = create_active_event(venue["id"], tip_split_mode=tip_split_mode)
    a1 = create_attendant(venue["id"], name="A1")
    a2 = create_attendant(venue["id"], name="A2")
    s1 = create_shift(a1["id"], "2026-06-01T08:00:00Z", s1_end, event_id=event["id"])
    s2 = create_shift(a2["id"], "2026-06-01T08:00:00Z", s2_end, event_id=event["id"])
    get_success_data(api_client.record_tips(
        s1["id"], {"declared_tips_cents": s1_tips}, make_attendant_headers(a1["id"])))
    get_success_data(api_client.record_tips(
        s2["id"], {"declared_tips_cents": s2_tips}, make_attendant_headers(a2["id"])))
    return {"venue": venue, "event": event, "a1": a1, "a2": a2, "s1": s1, "s2": s2}


# ── Tier 5: retrieval flow ────────────────────────────────────────────────
def setup_retrieval_ready() -> dict:
    """Checked-in ticket with its attendant on an ACTIVE shift; a retrieval request
    driven REQUESTED → ASSIGNED → STAGING → READY (ticket park_status now RETRIEVED).
    Returns keys venue, event, lot, attendant, ticket, retrieval."""
    env = setup_checked_in_ticket()
    a_id = env["attendant"]["id"]
    create_active_shift(a_id)
    hdr = make_attendant_headers(a_id)
    rr = get_success_data(api_client.create_retrieval_request(
        create_retrieval_request_payload(env["ticket"]["id"]), hdr))
    get_success_data(api_client.assign_retrieval(rr["id"], {"attendant_id": a_id}, hdr))
    get_success_data(api_client.stage_retrieval(rr["id"], hdr))
    rr = get_success_data(api_client.ready_retrieval(
        rr["id"], {"ready_at": "2026-06-01T11:45:00Z"}, hdr))
    env["retrieval"] = rr
    return env


def setup_requested_retrieval() -> dict:
    """Checked-in ticket + a REQUESTED retrieval request (no runner assigned yet).
    Returns keys venue, event, lot, attendant, ticket, retrieval."""
    env = setup_checked_in_ticket()
    hdr = make_attendant_headers(env["attendant"]["id"])
    rr = get_success_data(api_client.create_retrieval_request(
        create_retrieval_request_payload(env["ticket"]["id"],
                                         requested_at="2026-06-01T11:00:00Z"), hdr))
    env["retrieval"] = rr
    return env


# ── Tier 6: damage-claim helpers ──────────────────────────────────────────
def setup_open_damage_claim(claimed_amount_cents: int = 500,
                            with_active_shift: bool = False, **claim_overrides) -> dict:
    """Checked-in ticket + one OPEN damage claim against it (attendant defaults to the
    ticket's attendant). Optionally puts the attendant on an ACTIVE shift. Returns keys
    venue, event, lot, attendant, ticket, claim (and shift when with_active_shift)."""
    env = setup_checked_in_ticket()
    a_id = env["attendant"]["id"]
    if with_active_shift:
        env["shift"] = create_active_shift(a_id)
    claim = get_success_data(api_client.create_damage_claim(
        create_damage_claim_payload(env["ticket"]["id"],
                                    claimed_amount_cents=claimed_amount_cents,
                                    **claim_overrides),
        make_attendant_headers(a_id)))
    env["claim"] = claim
    return env


def apply_grant(ticket_id: str, grant_type: str, **overrides) -> dict:
    """Apply a validation grant to a ticket (Cashier)."""
    return get_success_data(api_client.create_validation(
        ticket_id, create_validation_payload(grant_type, **overrides), CASHIER))
