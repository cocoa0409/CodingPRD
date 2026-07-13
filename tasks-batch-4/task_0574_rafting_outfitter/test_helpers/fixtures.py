"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors rather than confusing assertion failures. Every helper
builds its preconditions from scratch using only PRD-declared endpoints, because the
harness restarts the server (empty database) before every individual test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_trip_payload,
    create_guide_payload,
    create_guide_assignment_payload,
    create_reservation_payload,
    create_guest_payload,
    create_gear_item_payload,
    create_gear_assignment_payload,
)
from .test_users import TEST_USERS, make_guest_headers

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# ── Primitive creators ─────────────────────────────────────────────────────

def create_trip(api, **overrides):
    return get_success_data(api.create_trip(create_trip_payload(**overrides), MGR))


def create_guide(api, max_class="CLASS_III", full_name="Test Guide"):
    return get_success_data(
        api.create_guide(create_guide_payload(full_name=full_name, max_class=max_class), MGR)
    )


def assign_guide(api, trip_id, guide_id, role="LEAD"):
    return get_success_data(
        api.create_guide_assignment(create_guide_assignment_payload(trip_id, guide_id, role), MGR)
    )


def open_trip(api, trip_id):
    return get_success_data(api.open_trip(trip_id, MGR))


def get_trip(api, trip_id):
    return get_success_data(api.get_trip(trip_id, RESV))


def trip_version(api, trip_id):
    return get_trip(api, trip_id)["version"]


def create_reservation(api, trip_id, version=None, **overrides):
    if version is None:
        version = trip_version(api, trip_id)
    return get_success_data(
        api.create_reservation(create_reservation_payload(trip_id, version, **overrides), RESV)
    )


def add_guest(api, reservation_id, **overrides):
    return get_success_data(
        api.create_guest(create_guest_payload(reservation_id, **overrides), RESV)
    )


def waiver_for_guest(api, guest_id):
    waivers = get_success_data(api.list_waivers(RESV, params={"guest_id": guest_id}))
    assert waivers, f"setup: no waiver found for guest {guest_id}"
    return waivers[0]


def sign_waiver(api, waiver_id, guest_id, guardian_name=None):
    payload = {}
    if guardian_name is not None:
        payload["guardian_name"] = guardian_name
    return get_success_data(api.sign_waiver(waiver_id, make_guest_headers(guest_id), payload))


def create_gear_item(api, gear_type="PFD", size_label="L", min_weight_lbs=100, max_weight_lbs=250):
    return get_success_data(
        api.create_gear_item(
            create_gear_item_payload(
                gear_type=gear_type,
                size_label=size_label,
                min_weight_lbs=min_weight_lbs,
                max_weight_lbs=max_weight_lbs,
            ),
            MGR,
        )
    )


def assign_gear(api, gear_item_id, guest_id, trip_id):
    return get_success_data(
        api.create_gear_assignment(
            create_gear_assignment_payload(gear_item_id, guest_id, trip_id), RESV
        )
    )


# ── Tier 1 / 2: State progression + hierarchy ──────────────────────────────

def setup_open_trip(api, guide_class="CLASS_III", role="LEAD", **trip_overrides):
    """Create a trip, assign one guide, and open it. Returns (trip, guide, ga).

    The returned trip is re-read after opening so its status/version are current.
    """
    trip = create_trip(api, **trip_overrides)
    guide = create_guide(api, max_class=guide_class)
    ga = assign_guide(api, trip["id"], guide["id"], role)
    open_trip(api, trip["id"])
    trip = get_trip(api, trip["id"])
    return trip, guide, ga


# ── Tier 3: Full lifecycle shortcuts ───────────────────────────────────────

def setup_confirmed_reservation(
    api,
    party_size=1,
    deposit_cents=3000,
    photo_addon=False,
    booking_type="GROUP",
    with_gear=True,
    sign=False,
    pay_deposit=False,
    guest_age=30,
    guest_weight=175,
    pfd_min_weight=100,
    pfd_max_weight=250,
    **trip_overrides,
):
    """Open trip + one reservation walked to CONFIRMED with one guest.

    Flags control how far the guest's prerequisites are taken:
      with_gear  -> assign an AVAILABLE PFD to the guest
      sign       -> sign the guest's waiver
      pay_deposit-> record the deposit before confirming
    Returns a dict with trip, guide, ga, pfd, res, guest, waiver, gasg.
    """
    trip, guide, ga = setup_open_trip(api, **trip_overrides)
    pfd = None
    gasg = None
    if with_gear:
        pfd = create_gear_item(api, gear_type="PFD", min_weight_lbs=pfd_min_weight, max_weight_lbs=pfd_max_weight)
    res = create_reservation(
        api, trip["id"], party_size=party_size, deposit_cents=deposit_cents,
        photo_addon=photo_addon, booking_type=booking_type,
    )
    guest = add_guest(api, res["id"], age=guest_age, weight_lbs=guest_weight)
    waiver = waiver_for_guest(api, guest["id"])
    if with_gear:
        gasg = assign_gear(api, pfd["id"], guest["id"], trip["id"])
    if sign:
        sign_waiver(api, waiver["id"], guest["id"])
    if pay_deposit:
        get_success_data(api.pay_deposit(res["id"], RESV))
    get_success_data(api.confirm_reservation(res["id"], RESV))
    res = get_success_data(api.get_reservation(res["id"], RESV))
    return {
        "trip": trip, "guide": guide, "ga": ga, "pfd": pfd,
        "res": res, "guest": guest, "waiver": waiver, "gasg": gasg,
    }


def setup_checked_in_reservation(
    api,
    party_size=1,
    photo_addon=False,
    deposit_cents=3000,
    guest_age=30,
    guest_weight=180,
    pfd_min_weight=100,
    pfd_max_weight=250,
    **trip_overrides,
):
    """Open trip + one reservation walked all the way to CHECKED_IN with one guest
    (signed waiver, assigned PFD, deposit paid, confirmed, checked in).

    Note: exactly ONE guest is added even when party_size > 1, so that
    checked_in_guest_count == 1 diverges from the booked party_size.
    Returns a dict with trip, guide, ga, pfd, res, guest, waiver.
    """
    trip, guide, ga = setup_open_trip(api, **trip_overrides)
    pfd = create_gear_item(api, gear_type="PFD", min_weight_lbs=pfd_min_weight, max_weight_lbs=pfd_max_weight)
    res = create_reservation(
        api, trip["id"], party_size=party_size, deposit_cents=deposit_cents, photo_addon=photo_addon,
    )
    guest = add_guest(api, res["id"], age=guest_age, weight_lbs=guest_weight)
    waiver = waiver_for_guest(api, guest["id"])
    sign_waiver(api, waiver["id"], guest["id"])
    assign_gear(api, pfd["id"], guest["id"], trip["id"])
    get_success_data(api.pay_deposit(res["id"], RESV))
    get_success_data(api.confirm_reservation(res["id"], RESV))
    get_success_data(api.check_in_reservation(res["id"], RESV))
    res = get_success_data(api.get_reservation(res["id"], RESV))
    return {"trip": trip, "guide": guide, "ga": ga, "pfd": pfd, "res": res, "guest": guest, "waiver": waiver}


def setup_settled_trip_three_guides(api, gratuity_cents=10000, **trip_overrides):
    """Trip staffed by three guides created in order LEAD, SAFETY, SWEEP, with one
    reservation fully checked in and SETTLED carrying gratuity_cents into the pool.

    Returns a dict with trip, ga_lead, ga_safety, ga_sweep, res.
    The trip is NOT completed (call complete_trip separately for the final split).
    """
    trip = create_trip(api, **trip_overrides)
    g_lead = create_guide(api, max_class="CLASS_IV", full_name="Lead Guide")
    ga_lead = assign_guide(api, trip["id"], g_lead["id"], "LEAD")
    g_safety = create_guide(api, max_class="CLASS_III", full_name="Safety Guide")
    ga_safety = assign_guide(api, trip["id"], g_safety["id"], "SAFETY")
    g_sweep = create_guide(api, max_class="CLASS_III", full_name="Sweep Guide")
    ga_sweep = assign_guide(api, trip["id"], g_sweep["id"], "SWEEP")
    open_trip(api, trip["id"])
    pfd = create_gear_item(api, gear_type="PFD", min_weight_lbs=100, max_weight_lbs=250)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], age=40, weight_lbs=190)
    waiver = waiver_for_guest(api, guest["id"])
    sign_waiver(api, waiver["id"], guest["id"])
    assign_gear(api, pfd["id"], guest["id"], trip["id"])
    get_success_data(api.pay_deposit(res["id"], RESV))
    get_success_data(api.confirm_reservation(res["id"], RESV))
    get_success_data(api.check_in_reservation(res["id"], RESV))
    get_success_data(api.settle_reservation(res["id"], RESV, {"gratuity_cents": gratuity_cents}))
    return {"trip": trip, "ga_lead": ga_lead, "ga_safety": ga_safety, "ga_sweep": ga_sweep, "res": res}


def guide_assignment_now(api, ga_id):
    return get_success_data(api.get_guide_assignment(ga_id, MGR))
