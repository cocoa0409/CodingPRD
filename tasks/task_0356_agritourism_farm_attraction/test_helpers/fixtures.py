"""Composite setup helpers for the Agritourism Farm Attraction suite.

Every test starts against an empty database (the harness restarts the server
before each test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() (lenient) so setup
failures surface as clear "Setup failed" errors, not confusing assertion
failures.

Identity threading: Visitor and GroupLeader are entity_backed:Visitor. Any
ownership-gated call (reservation create/confirm/cancel and its line items;
group create/edit/revise/requote/confirm/cancel) uses make_visitor_headers /
make_group_leader_headers with the real Visitor.id — never the shared constant.
GateAgent and FarmManager are opaque, so their shared constants are canonical.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_farm_payload, create_weather_event_payload, create_pricing_policy_payload,
    create_admission_window_payload, create_visitor_payload, create_season_pass_payload,
    create_reservation_payload, create_activity_pass_payload, create_waiver_payload,
    create_pumpkin_purchase_payload, weigh_out_payload, create_concession_order_payload,
    create_group_booking_payload,
)
from .test_users import (
    TEST_USERS, make_visitor_headers, make_group_leader_headers,
)
from .constants import WINDOW_START, WINDOW_END

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_agent_headers"]


# --- Clock ------------------------------------------------------------------

def set_clock(iso8601: str):
    """Set the server's logical UTC clock (FarmManager only)."""
    return api_client.set_clock(iso8601, MANAGER)


# --- Primitives -------------------------------------------------------------

def create_farm(**overrides) -> dict:
    return get_success_data(api_client.create_farm(create_farm_payload(**overrides), MANAGER))


def create_policy(farm_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_pricing_policy(farm_id, create_pricing_policy_payload(**overrides), MANAGER))


def activate_policy(policy_id) -> dict:
    return get_success_data(api_client.activate_pricing_policy(policy_id, MANAGER))


def create_active_policy(farm_id, **overrides) -> dict:
    """Create a DRAFT policy and activate it. Returns the ACTIVE policy."""
    policy = create_policy(farm_id, **overrides)
    return activate_policy(policy["id"])


def create_window(farm_id, capacity=10, starts_at=WINDOW_START, ends_at=WINDOW_END, **overrides) -> dict:
    return get_success_data(api_client.create_admission_window(
        farm_id, create_admission_window_payload(starts_at=starts_at, ends_at=ends_at,
                                                 capacity=capacity, **overrides), MANAGER))


def create_visitor(email="v@example.com", full_name="Test Visitor", **overrides) -> dict:
    return get_success_data(
        api_client.create_visitor(create_visitor_payload(email=email, full_name=full_name, **overrides), MANAGER))


def create_season_pass(farm_id, visitor_id, **overrides) -> dict:
    return get_success_data(api_client.create_season_pass(
        farm_id, create_season_pass_payload(visitor_id, **overrides), MANAGER))


def create_group(farm_id, window_id, leader_id, kind, adult_count=0, child_count=0, **overrides) -> dict:
    return get_success_data(api_client.create_group_booking(
        farm_id,
        create_group_booking_payload(window_id, leader_id, kind, adult_count=adult_count,
                                     child_count=child_count, **overrides),
        make_group_leader_headers(leader_id)))


# --- Standard farm setups ---------------------------------------------------

def setup_farm(capacity=10, policy_overrides=None, window_overrides=None, clock=None):
    """Farm OPEN + ACTIVE policy + one window. Returns dict with farm, policy,
    window. Sets the clock first when given."""
    if clock is not None:
        set_clock(clock)
    farm = create_farm()
    policy = create_active_policy(farm["id"], **(policy_overrides or {}))
    window = create_window(farm["id"], capacity=capacity, **(window_overrides or {}))
    return {"farm": farm, "policy": policy, "window": window}


def setup_farm_with_visitor(capacity=10, policy_overrides=None, window_overrides=None,
                            clock=None, visitor_email="v@example.com"):
    """Farm OPEN + ACTIVE policy + window + one visitor. Returns dict with farm,
    policy, window, visitor."""
    s = setup_farm(capacity=capacity, policy_overrides=policy_overrides,
                   window_overrides=window_overrides, clock=clock)
    s["visitor"] = create_visitor(email=visitor_email)
    return s


# --- Reservation lifecycle --------------------------------------------------

def create_pending_reservation(window_id, visitor_id, expected_window_version,
                               adult_count=1, child_count=0, **overrides) -> dict:
    """Create a PENDING reservation owned by visitor_id (ownership-gated)."""
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(window_id, visitor_id, expected_window_version,
                                   adult_count=adult_count, child_count=child_count, **overrides),
        make_visitor_headers(visitor_id)))


def confirm_reservation(reservation_id, visitor_id) -> dict:
    return get_success_data(api_client.confirm_reservation(
        reservation_id, make_visitor_headers(visitor_id)))


def cancel_reservation(reservation_id, visitor_id) -> dict:
    return get_success_data(api_client.cancel_reservation(
        reservation_id, make_visitor_headers(visitor_id)))


def sign_waiver(reservation_id, visitor_id, participant_name, **overrides) -> dict:
    return get_success_data(api_client.create_waiver(
        reservation_id, create_waiver_payload(participant_name, **overrides),
        make_visitor_headers(visitor_id)))


def sign_waivers_for_party(reservation_id, visitor_id, adult_count, child_count):
    """Sign one SIGNED waiver per participant so waiver_satisfied becomes true.
    Children are signed as minors with a guardian to satisfy ERR_GUARDIAN_REQUIRED."""
    n = 0
    for i in range(adult_count):
        sign_waiver(reservation_id, visitor_id, f"Adult {i + 1}")
        n += 1
    for i in range(child_count):
        sign_waiver(reservation_id, visitor_id, f"Child {i + 1}",
                    is_minor=True, guardian_name="Adult 1")
        n += 1
    return n


def check_in_reservation(reservation_id) -> dict:
    """Check in a CONFIRMED reservation (GateAgent)."""
    return get_success_data(api_client.check_in_reservation(reservation_id, GATE))


def settle_reservation(reservation_id) -> dict:
    """Settle a CHECKED_IN reservation (GateAgent)."""
    return get_success_data(api_client.settle_reservation(reservation_id, GATE))


def add_activity_pass(reservation_id, visitor_id, activity, quantity=1) -> dict:
    return get_success_data(api_client.create_activity_pass(
        reservation_id, create_activity_pass_payload(activity, quantity),
        make_visitor_headers(visitor_id)))


def add_concession(reservation_id, visitor_id, food_cents=0, vehicle_count=0) -> dict:
    return get_success_data(api_client.create_concession_order(
        reservation_id, create_concession_order_payload(food_cents=food_cents,
                                                         vehicle_count=vehicle_count),
        make_visitor_headers(visitor_id)))


def add_pumpkin(reservation_id, visitor_id, estimated_weight_lb) -> dict:
    return get_success_data(api_client.create_pumpkin_purchase(
        reservation_id, create_pumpkin_purchase_payload(estimated_weight_lb),
        make_visitor_headers(visitor_id)))


def weigh_out(pumpkin_id, scale_weight_lb) -> dict:
    """Record authoritative scale weight (GateAgent)."""
    return get_success_data(api_client.weigh_out_pumpkin(
        pumpkin_id, weigh_out_payload(scale_weight_lb), GATE))


def window_version(window_id) -> int:
    return get_success_data(api_client.get_admission_window(window_id, MANAGER))["version"]


# --- Composite lifecycle shortcuts ------------------------------------------

def create_confirmed_reservation(window_id, visitor_id, expected_window_version,
                                 adult_count=1, child_count=0, **overrides) -> dict:
    """Create a PENDING reservation then confirm it. Returns the CONFIRMED
    reservation."""
    res = create_pending_reservation(window_id, visitor_id, expected_window_version,
                                     adult_count=adult_count, child_count=child_count, **overrides)
    return confirm_reservation(res["id"], visitor_id)


def create_checked_in_reservation(window_id, visitor_id, expected_window_version,
                                  adult_count=1, child_count=0, **overrides) -> dict:
    """Create -> confirm -> sign waivers for the whole party -> check in.
    Returns the CHECKED_IN reservation."""
    res = create_confirmed_reservation(window_id, visitor_id, expected_window_version,
                                       adult_count=adult_count, child_count=child_count, **overrides)
    sign_waivers_for_party(res["id"], visitor_id, adult_count, child_count)
    return check_in_reservation(res["id"])


def setup_checked_in(capacity=10, adult_count=1, child_count=0, clock=None):
    """Full setup to a CHECKED_IN reservation with no pumpkins yet. Returns dict
    with farm, policy, window, visitor, reservation."""
    s = setup_farm_with_visitor(capacity=capacity, clock=clock)
    res = create_checked_in_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"],
                                        adult_count=adult_count, child_count=child_count)
    s["reservation"] = res
    return s


def create_settled_reservation(window_id, visitor_id, expected_window_version,
                               adult_count=1, child_count=0) -> dict:
    """Create -> confirm -> waivers -> check in -> settle (no pumpkins).
    Returns the SETTLED reservation."""
    res = create_checked_in_reservation(window_id, visitor_id, expected_window_version,
                                        adult_count=adult_count, child_count=child_count)
    return settle_reservation(res["id"])


# --- Group lifecycle --------------------------------------------------------

def confirm_group(group_id, leader_id, expected_window_version) -> dict:
    return get_success_data(api_client.confirm_group_booking(
        group_id, {"expected_window_version": expected_window_version},
        make_group_leader_headers(leader_id)))


def revise_group(group_id, leader_id) -> dict:
    return get_success_data(api_client.revise_group_booking(
        group_id, make_group_leader_headers(leader_id)))


def edit_group(group_id, leader_id, **fields) -> dict:
    return get_success_data(api_client.edit_group_booking(
        group_id, fields, make_group_leader_headers(leader_id)))


def requote_group(group_id, leader_id) -> dict:
    return get_success_data(api_client.requote_group_booking(
        group_id, make_group_leader_headers(leader_id)))


# --- Weather ----------------------------------------------------------------

def declare_hold(farm_id, note="Lightning in area") -> dict:
    return get_success_data(api_client.create_weather_event(
        farm_id, create_weather_event_payload("HOLD", note=note), MANAGER))


def declare_cleared(farm_id, note="Cleared") -> dict:
    return get_success_data(api_client.create_weather_event(
        farm_id, create_weather_event_payload("CLEARED", note=note), MANAGER))


def declare_closure(farm_id, affected_span_start="2026-10-11T00:00:00Z",
                    affected_span_end="2026-10-12T00:00:00Z", note="Severe storm") -> dict:
    return get_success_data(api_client.create_weather_event(
        farm_id,
        create_weather_event_payload("CLOSURE", affected_span_start=affected_span_start,
                                     affected_span_end=affected_span_end, note=note),
        MANAGER))
