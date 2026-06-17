"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Setup
calls use the lenient get_success_data() validator so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: GuestApp is entity_backed:Guest. Any ownership-gated call
(reservations, parties, purchases) uses make_guest_headers(guest_id) with the
real Guest.id, never the shared GuestApp constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_park_admin_headers, make_ride_operator_headers, make_guest_headers
from .constants import OPERATING_DATE, CLOCK_BASE, WINDOW_START, WINDOW_END

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


# ----------------------------------------------------------------------
# Atomic creation helpers
# ----------------------------------------------------------------------

def create_park(gate_capacity=100, peak_threshold_pct=None, operating_date=OPERATING_DATE, name="P"):
    payload = {"name": name, "gate_capacity": gate_capacity, "operating_date": operating_date}
    if peak_threshold_pct is not None:
        payload["peak_threshold_pct"] = peak_threshold_pct
    resp = api_client.create_park(payload, ADMIN)
    return get_success_data(resp)


def set_clock(park_id, to_iso8601):
    resp = api_client.set_clock({"park_id": park_id, "to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def create_ride(park_id, hourly_throughput=100, name="R", **overrides):
    payload = {"name": name, "hourly_throughput": hourly_throughput}
    payload.update(overrides)
    resp = api_client.create_ride(park_id, payload, ADMIN)
    return get_success_data(resp)


def create_window(ride_id, window_start_utc=WINDOW_START, window_end_utc=WINDOW_END):
    resp = api_client.create_return_window(
        ride_id,
        {"window_start_utc": window_start_utc, "window_end_utc": window_end_utc},
        ADMIN,
    )
    return get_success_data(resp)


def create_guest(park_id, height_cm=170, full_name="G", uses_wheelchair=None):
    payload = {"full_name": full_name, "height_cm": height_cm}
    if uses_wheelchair is not None:
        payload["uses_wheelchair"] = uses_wheelchair
    resp = api_client.create_guest(park_id, payload, ADMIN)
    return get_success_data(resp)


def create_day_ticket(park_id, guest_id, ticket_date=OPERATING_DATE):
    resp = api_client.create_day_ticket(
        park_id, {"guest_id": guest_id, "ticket_date": ticket_date}, ADMIN
    )
    return get_success_data(resp)


def admit(park_id, ticket_id):
    resp = api_client.admit(park_id, {"ticket_id": ticket_id}, ADMIN)
    return get_success_data(resp)


def create_plan(park_id, tier="MULTI_PASS", price_cents=1500, max_concurrent_holds=3, surge_multiplier=None):
    payload = {"tier": tier, "price_cents": price_cents, "max_concurrent_holds": max_concurrent_holds}
    if surge_multiplier is not None:
        payload["surge_multiplier"] = surge_multiplier
    resp = api_client.create_entitlement_plan(park_id, payload, ADMIN)
    return get_success_data(resp)


def book_vq(ride_id, guest_id, window_id, expected_version, queue_type="VIRTUAL_QUEUE"):
    """Create a HELD reservation as the acting guest (ownership-threaded)."""
    payload = {
        "ride_id": ride_id,
        "guest_id": guest_id,
        "return_window_id": window_id,
        "queue_type": queue_type,
        "expected_return_window_id_version": expected_version,
    }
    resp = api_client.create_reservation(payload, make_guest_headers(guest_id))
    return get_success_data(resp)


def confirm(reservation_id, guest_id):
    resp = api_client.confirm_reservation(reservation_id, make_guest_headers(guest_id))
    return get_success_data(resp)


# ----------------------------------------------------------------------
# Tier 2/3: composite scenarios
# ----------------------------------------------------------------------

def setup_park_ride_window(gate_capacity=100, hourly_throughput=100,
                           clock=CLOCK_BASE, ride_overrides=None,
                           window_start=WINDOW_START, window_end=WINDOW_END,
                           peak_threshold_pct=None):
    """Active park (clock set) + one OPEN ride + one OPEN return window.

    Returns (park, ride, window). The window dict carries the live version
    needed for the OCC expected_return_window_id_version on the first booking.
    """
    park = create_park(gate_capacity=gate_capacity, peak_threshold_pct=peak_threshold_pct)
    if clock is not None:
        set_clock(park["id"], clock)
    ride = create_ride(park["id"], hourly_throughput=hourly_throughput, **(ride_overrides or {}))
    window = create_window(ride["id"], window_start, window_end)
    return park, ride, window


def fill_window_to_exhausted(ride_id, window, park_id, count=2):
    """Create `count` tall guests each booking a VIRTUAL_QUEUE slot on `window`,
    threading the window version forward across bookings. Returns the list of
    reservation dicts plus the latest observed window version.

    Each booking observes the version returned by the prior booking's response.
    """
    current_version = window["version"]
    reservations = []
    for i in range(count):
        guest = create_guest(park_id, full_name=f"Filler{i}")
        res = book_vq(ride_id, guest["id"], window["id"], current_version)
        reservations.append(res)
        current_version = res["version"]
    return reservations, current_version


def setup_loaded_ride_for_peak_price(price_cents=1500, surge_multiplier=2.0, tier="MULTI_PASS"):
    """Build a small ride whose VQ load reaches RIDE_PEAK_LOAD so a Lightning
    Lane purchase surges, plus a buyer guest GB and an entitlement plan.

    Ride R5 (throughput 5) -> a 60-min window has slot_capacity floor(5*1*0.40)=2.
    Two VIRTUAL_QUEUE reservations make ride_load = 2/2 = 1.0 >= 0.75 (PEAK).

    Returns (park, ride, window, buyer_guest, plan).
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    # First filler guest (GA) books slot 1.
    ga = create_guest(park["id"], full_name="GA")
    res_a = book_vq(ride["id"], ga["id"], window["id"], window["version"])
    # Second buyer guest (GB) books slot 2; load now 2/2 = PEAK.
    gb = create_guest(park["id"], full_name="GB")
    book_vq(ride["id"], gb["id"], window["id"], res_a["version"])
    plan = create_plan(park["id"], tier=tier, price_cents=price_cents,
                       max_concurrent_holds=(1 if tier == "SINGLE_PASS" else 3),
                       surge_multiplier=surge_multiplier)
    return park, ride, window, gb, plan


def setup_booked_reservation(hourly_throughput=100, clock=CLOCK_BASE,
                             window_start=WINDOW_START, window_end=WINDOW_END,
                             ride_overrides=None, gate_capacity=100):
    """Park + ride + window + guest + a single VIRTUAL_QUEUE reservation confirmed
    to BOOKED. Returns (park, ride, window, guest, reservation)."""
    park, ride, window = setup_park_ride_window(
        gate_capacity=gate_capacity, hourly_throughput=hourly_throughput, clock=clock,
        ride_overrides=ride_overrides, window_start=window_start, window_end=window_end,
    )
    guest = create_guest(park["id"], full_name="G1")
    res = book_vq(ride["id"], guest["id"], window["id"], window["version"])
    booked = confirm(res["id"], guest["id"])
    return park, ride, window, guest, booked


def setup_held_reservation(hourly_throughput=100, clock=CLOCK_BASE, queue_type="VIRTUAL_QUEUE",
                           ride_overrides=None, gate_capacity=100,
                           window_start=WINDOW_START, window_end=WINDOW_END):
    """Park + ride + window + guest + a single HELD reservation (not confirmed).
    Returns (park, ride, window, guest, reservation)."""
    park, ride, window = setup_park_ride_window(
        gate_capacity=gate_capacity, hourly_throughput=hourly_throughput, clock=clock,
        ride_overrides=ride_overrides, window_start=window_start, window_end=window_end,
    )
    guest = create_guest(park["id"], full_name="G1")
    res = book_vq(ride["id"], guest["id"], window["id"], window["version"], queue_type=queue_type)
    return park, ride, window, guest, res


def setup_party_with_member(hourly_throughput=5, with_window=True, clock=CLOCK_BASE):
    """Park + (optional ride+window) + leader GL + member GM linked, party FORMING.
    Returns (park, ride, window, leader, member, party). ride/window may be None
    when with_window is False.

    Captures party versions in party["_v0"]/party["_v1"] for OCC tests.
    """
    park = create_park()
    if clock is not None:
        set_clock(park["id"], clock)
    ride = window = None
    if with_window:
        ride = create_ride(park["id"], hourly_throughput=hourly_throughput, name="R5")
        window = create_window(ride["id"])
    leader = create_guest(park["id"], full_name="GL")
    member = create_guest(park["id"], full_name="GM")
    party = get_success_data(
        api_client.create_party(park["id"], {"leader_guest_id": leader["id"]},
                                make_guest_headers(leader["id"]))
    )
    v0 = party["version"]
    membership = get_success_data(
        api_client.add_member(party["id"], {"guest_id": member["id"]},
                              make_guest_headers(leader["id"]))
    )
    v1 = membership["version"]
    party["_v0"] = v0
    party["_v1"] = v1
    party["_leader_membership"] = None
    party["_member_membership_id"] = membership["id"]
    return park, ride, window, leader, member, party


def setup_active_lightning_lane(price_cents=1500, surge_multiplier=2.0, tier="MULTI_PASS"):
    """Park + ride + guest + plan + one ACTIVE LightningLanePurchase on an unloaded
    ride (OPEN-phase flat price). Returns (park, ride, guest, plan, purchase)."""
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    plan = create_plan(park["id"], tier=tier, price_cents=price_cents,
                       max_concurrent_holds=(1 if tier == "SINGLE_PASS" else 3),
                       surge_multiplier=surge_multiplier)
    purchase = get_success_data(
        api_client.create_lightning_lane_purchase(
            {"park_id": park["id"], "guest_id": guest["id"],
             "ride_id": ride["id"], "plan_id": plan["id"]},
            make_guest_headers(guest["id"]),
        )
    )
    return park, ride, guest, plan, purchase


def setup_admitted_to_peak(gate_capacity=4, peak_threshold_pct=0.5, admit_count=2):
    """Park admitted to PEAK day_phase by admitting `admit_count` guests, plus an
    OPEN ride+window and one extra non-admitted guest GX for the booking attempt.
    Returns (park, ride, window, extra_guest)."""
    park, ride, window = setup_park_ride_window(
        gate_capacity=gate_capacity, peak_threshold_pct=peak_threshold_pct,
    )
    for i in range(admit_count):
        g = create_guest(park["id"], full_name=f"A{i}")
        t = create_day_ticket(park["id"], g["id"])
        admit(park["id"], t["id"])
    extra = create_guest(park["id"], full_name="GX")
    return park, ride, window, extra


def setup_redistributed_single_window():
    """Ride with one window, one BOOKED reservation, ride declared DOWN (reservation
    -> REDISTRIBUTED), clock advanced past the window, ride restored (window EXPIRED).
    No future replacement remains. Returns (park, ride, window, guest, reservation)."""
    park, ride, window = setup_park_ride_window(hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    res = book_vq(ride["id"], guest["id"], window["id"], window["version"])
    confirm(res["id"], guest["id"])
    get_success_data(api_client.declare_down(ride["id"], OPERATOR))
    set_clock(park["id"], "2026-06-15T11:30:00.000Z")
    get_success_data(api_client.restore_ride(ride["id"], OPERATOR))
    return park, ride, window, guest, res
