"""Composite setup helpers for multi-step test prerequisites.

Each interesting claim in this PRD requires the system to be walked into a
specific state (venue -> attraction -> pricing -> slot -> open -> guest ->
waiver -> booking -> confirm ...). These helpers encapsulate those chains so
test bodies focus on the assertion under test.

All helpers use get_success_data() (lenient validator) so a broken precondition
surfaces as a clear "setup failed" rather than a confusing assertion failure.
Identity threading: OpsManager / Cashier are opaque; the Guest role is
entity_backed, so ownership-gated Guest calls thread the real Guest id via
make_guest_headers(guest_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_venue_payload,
    create_attraction_payload,
    create_pricing_plan_payload,
    create_heat_payload,
    create_tee_session_payload,
    create_guest_payload,
    create_waiver_payload,
    create_combo_pass_payload,
    create_party_group_payload,
    create_booking_payload,
    top_up_payload,
)
from .test_users import make_ops_manager_headers, make_cashier_headers, make_guest_headers

OPS = make_ops_manager_headers()
CASHIER = make_cashier_headers()

# Default test clock used by every time-gated setup; before all slot windows.
DEFAULT_CLOCK = "2026-06-14T09:00:00Z"


# ─── Tier 0: primitives ───────────────────────────────────────────────────────

def create_venue(name="Test Track", set_clock=DEFAULT_CLOCK):
    """Create an OPEN venue; optionally set its server clock. Returns the venue
    dict after the clock set (so version reflects the clock mutation)."""
    venue = get_success_data(api_client.create_venue(create_venue_payload(name=name), OPS))
    if set_clock is not None:
        venue = get_success_data(
            api_client.set_venue_clock(venue["id"], {"to_iso8601": set_clock}, OPS)
        )
    return venue


def create_attraction(venue_id, kind="GO_KART", min_height_cm=0, lane_count=0, name="Attraction"):
    payload = create_attraction_payload(
        venue_id, name=name, kind=kind, min_height_cm=min_height_cm, lane_count=lane_count
    )
    return get_success_data(api_client.create_attraction(payload, OPS))


def create_pricing_plan(venue_id, mode="PER_HEAT", base_price_cents=1000, **overrides):
    payload = create_pricing_plan_payload(
        venue_id, mode=mode, base_price_cents=base_price_cents, **overrides
    )
    return get_success_data(api_client.create_pricing_plan(payload, OPS))


def create_heat(venue_id, attraction_id, **overrides):
    payload = create_heat_payload(venue_id, attraction_id, **overrides)
    return get_success_data(api_client.create_heat(payload, OPS))


def create_tee_session(venue_id, attraction_id, **overrides):
    payload = create_tee_session_payload(venue_id, attraction_id, **overrides)
    return get_success_data(api_client.create_tee_session(payload, OPS))


def open_heat(heat_id):
    return get_success_data(api_client.open_heat(heat_id, OPS))


def open_tee_session(tee_session_id):
    return get_success_data(api_client.open_tee_session(tee_session_id, OPS))


def create_guest(full_name="Guest", height_cm=175, birthdate=None, as_role="ops"):
    payload = create_guest_payload(full_name=full_name, height_cm=height_cm)
    if birthdate is not None:
        payload["birthdate"] = birthdate
    headers = CASHIER if as_role == "cashier" else OPS
    return get_success_data(api_client.create_guest(payload, headers))


def sign_waiver(guest_id, guardian_name=None):
    payload = create_waiver_payload(guest_id)
    if guardian_name is not None:
        payload["guardian_name"] = guardian_name
    return get_success_data(api_client.create_waiver(payload, OPS))


def get_wallet_for_guest(guest_id):
    """Resolve the auto-created Wallet for a guest via the filtered list."""
    data, _ = _list(api_client.list_wallets(OPS, params={"guest_id": guest_id}))
    assert data, f"setup failed: no wallet for guest {guest_id}"
    return data[0]


def top_up(wallet_id, amount_cents):
    return get_success_data(api_client.top_up_wallet(wallet_id, top_up_payload(amount_cents), OPS))


def create_combo_pass(guest_id, total_credits):
    payload = create_combo_pass_payload(guest_id, total_credits)
    return get_success_data(api_client.create_combo_pass(payload, OPS))


def _list(response):
    """Return (data_list, meta) from a list response, tolerantly."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 1/2: venue + go-kart heat scenario ──────────────────────────────────

def setup_open_heat_scenario(
    lane_count=5, min_height_cm=0, base_price_cents=1000, mode="PER_HEAT",
    window="OFF_PEAK", set_clock=DEFAULT_CLOCK, plan_overrides=None,
    heat_overrides=None, name="Track",
):
    """Venue (OPEN, clock set) + GO_KART attraction + pricing plan + heat that
    is OPENED. Returns dict with venue, attraction, plan, heat (post-open, so
    heat['version'] is the freshly-opened version)."""
    venue = create_venue(name=name, set_clock=set_clock)
    attraction = create_attraction(
        venue["id"], kind="GO_KART", min_height_cm=min_height_cm, lane_count=lane_count
    )
    plan = create_pricing_plan(
        venue["id"], mode=mode, base_price_cents=base_price_cents, **(plan_overrides or {})
    )
    h_over = {"window": window}
    h_over.update(heat_overrides or {})
    heat = create_heat(venue["id"], attraction["id"], **h_over)
    heat = open_heat(heat["id"])
    return {"venue": venue, "attraction": attraction, "plan": plan, "heat": heat}


def setup_open_tee_scenario(
    party_slot_capacity=10, min_height_cm=0, base_price_cents=1000, mode="PER_ROUND",
    window="OFF_PEAK", set_clock=DEFAULT_CLOCK, plan_overrides=None,
    tee_overrides=None, open_session=True, name="Track",
):
    """Venue (OPEN, clock set) + MINI_GOLF attraction + pricing plan + tee
    session. Opens the session by default. Returns dict with venue, attraction,
    plan, tee_session."""
    venue = create_venue(name=name, set_clock=set_clock)
    attraction = create_attraction(venue["id"], kind="MINI_GOLF", min_height_cm=min_height_cm)
    plan = create_pricing_plan(
        venue["id"], mode=mode, base_price_cents=base_price_cents, **(plan_overrides or {})
    )
    t_over = {"party_slot_capacity": party_slot_capacity, "window": window}
    t_over.update(tee_overrides or {})
    tee = create_tee_session(venue["id"], attraction["id"], **t_over)
    if open_session:
        tee = open_tee_session(tee["id"])
    return {"venue": venue, "attraction": attraction, "plan": plan, "tee_session": tee}


def make_signed_guest(full_name="Guest", height_cm=175, birthdate="1990-01-01"):
    """Create a guest (OpsManager) and sign an (adult) waiver. Returns guest dict."""
    guest = create_guest(full_name=full_name, height_cm=height_cm, birthdate=birthdate)
    sign_waiver(guest["id"])
    return guest


# ─── Tier 3: bookings on a heat ───────────────────────────────────────────────

def create_heat_hold_booking(
    venue_id, guest_id, heat_id, plan_id, party_size=1, units=None,
    combo_pass_id=None, group_id=None, origin="RESERVATION",
):
    """Create a HOLD booking on a heat. Returns the booking dict."""
    over = {"slot_kind": "HEAT", "heat_id": heat_id, "party_size": party_size, "origin": origin}
    if units is not None:
        over["units"] = units
    if combo_pass_id is not None:
        over["combo_pass_id"] = combo_pass_id
    if group_id is not None:
        over["group_id"] = group_id
    payload = create_booking_payload(venue_id, guest_id, plan_id, **over)
    return get_success_data(api_client.create_booking(payload, OPS))


def create_tee_hold_booking(
    venue_id, guest_id, tee_session_id, plan_id, party_size=1, units=None,
    combo_pass_id=None, group_id=None, origin="RESERVATION",
):
    """Create a HOLD booking on a tee session. Returns the booking dict."""
    over = {
        "slot_kind": "TEE_SESSION", "tee_session_id": tee_session_id,
        "party_size": party_size, "origin": origin,
    }
    if units is not None:
        over["units"] = units
    if combo_pass_id is not None:
        over["combo_pass_id"] = combo_pass_id
    if group_id is not None:
        over["group_id"] = group_id
    payload = create_booking_payload(venue_id, guest_id, plan_id, **over)
    return get_success_data(api_client.create_booking(payload, OPS))


def confirm_booking_heat(booking_id, heat_version):
    """Confirm a heat booking with the supplied expected_heat_version. Returns
    the booking dict (CONFIRMED or WAITLISTED depending on capacity)."""
    return get_success_data(
        api_client.confirm_booking(booking_id, {"expected_heat_version": heat_version}, OPS)
    )


def confirm_booking_tee(booking_id, tee_version):
    return get_success_data(
        api_client.confirm_booking(
            booking_id, {"expected_tee_session_version": tee_version}, OPS
        )
    )


def get_heat(heat_id):
    return get_success_data(api_client.get_heat(heat_id, OPS))


def get_tee_session(tee_session_id):
    return get_success_data(api_client.get_tee_session(tee_session_id, OPS))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, OPS))


def get_venue(venue_id):
    return get_success_data(api_client.get_venue(venue_id, OPS))


def get_guest(guest_id):
    return get_success_data(api_client.get_guest(guest_id, OPS))


def get_party_group(group_id):
    return get_success_data(api_client.get_party_group(group_id, OPS))


def get_combo_pass(pass_id):
    return get_success_data(api_client.get_combo_pass(pass_id, OPS))


def get_wallet(wallet_id):
    return get_success_data(api_client.get_wallet(wallet_id, OPS))


# ─── Tier 3: confirmed booking on a fresh heat (capacity present) ─────────────

def setup_confirmed_heat_booking(lane_count=5, party_size=1, min_height_cm=0,
                                 base_price_cents=1000, set_clock=DEFAULT_CLOCK):
    """Full chain to a single CONFIRMED booking on an OPEN heat with capacity.
    Returns dict with venue, attraction, plan, heat (post-confirm), guest,
    booking."""
    s = setup_open_heat_scenario(
        lane_count=lane_count, min_height_cm=min_height_cm,
        base_price_cents=base_price_cents, set_clock=set_clock,
    )
    guest = make_signed_guest(height_cm=max(min_height_cm, 175))
    booking = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"], party_size=party_size
    )
    booking = confirm_booking_heat(booking["id"], s["heat"]["version"])
    heat = get_heat(s["heat"]["id"])
    return {
        "venue": s["venue"], "attraction": s["attraction"], "plan": s["plan"],
        "heat": heat, "guest": guest, "booking": booking,
    }


# ─── Tier 4: capacity-at-boundary / waitlist scenarios ───────────────────────

def setup_heat_filled_with_waitlist(lane_count=1, fill_party=1, wait_party=1,
                                    set_clock=DEFAULT_CLOCK):
    """OPEN heat filled to capacity by booking A (CONFIRMED), with booking B
    forced to WAITLISTED. Returns dict: venue, attraction, plan, heat,
    guest_a, guest_b, booking_a (CONFIRMED), booking_b (WAITLISTED)."""
    s = setup_open_heat_scenario(lane_count=lane_count, set_clock=set_clock)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    ga = make_signed_guest(full_name="GA", height_cm=180)
    gb = make_signed_guest(full_name="GB", height_cm=180)

    bk_a = create_heat_hold_booking(venue_id, ga["id"], heat_id, plan_id, party_size=fill_party)
    bk_a = confirm_booking_heat(bk_a["id"], s["heat"]["version"])
    heat_after_a = get_heat(heat_id)

    bk_b = create_heat_hold_booking(venue_id, gb["id"], heat_id, plan_id, party_size=wait_party)
    bk_b = confirm_booking_heat(bk_b["id"], heat_after_a["version"])

    return {
        "venue": s["venue"], "attraction": s["attraction"], "plan": s["plan"],
        "heat": get_heat(heat_id), "guest_a": ga, "guest_b": gb,
        "booking_a": bk_a, "booking_b": bk_b,
    }


# ─── Party-group helpers ──────────────────────────────────────────────────────

def create_party_group(venue_id, host_guest_id, deposit_cents=0, included_unit_count=10,
                       package_name="Party", as_role="ops"):
    payload = create_party_group_payload(
        venue_id, host_guest_id, package_name=package_name,
        included_unit_count=included_unit_count, deposit_cents=deposit_cents,
    )
    headers = CASHIER if as_role == "cashier" else OPS
    return get_success_data(api_client.create_party_group(payload, headers))


def confirm_party_group(group_id, expected_version):
    return get_success_data(
        api_client.confirm_party_group(group_id, {"expected_group_version": expected_version}, OPS)
    )
