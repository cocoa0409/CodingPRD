"""Guests, waivers, age/guardian rules, guest-removal cascade, and check-in prerequisites."""
from test_helpers import validate_success, validate_error
from test_helpers import TEST_USERS, make_guest_headers
from test_helpers.fixtures import (
    create_trip, create_reservation, add_guest, waiver_for_guest, sign_waiver,
    setup_confirmed_reservation,
)

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]


# ── Guest removal cascade (depth-2 transitive chain) ──

def test_guest_removal_releases_gear(api):
    """PRD §3.5: "Removal releases that guest's `ASSIGNED` gear assignments (each release
    returning its gear item to `AVAILABLE`), voids the guest's waiver, and recomputes the
    parent reservation's `checked_in_guest_count`."

    Design: Difficulty/transitive_cascade/guest_remove_releases_gear_and_voids_waiver_depth2
    """
    ctx = setup_confirmed_reservation(api, with_gear=True, sign=True, guest_weight=150, guest_age=31)
    removed = validate_success(api.remove_guest(ctx["guest"]["id"], RESV), 200)
    assert removed["status"] == "REMOVED"
    gasg = validate_success(api.get_gear_assignment(ctx["gasg"]["id"], RESV), 200)
    assert gasg["status"] == "RELEASED"
    item = validate_success(api.get_gear_item(ctx["pfd"]["id"], RESV), 200)
    assert item["status"] == "AVAILABLE"


def test_guest_removal_voids_waiver(api):
    """PRD §3.5: "Removal releases that guest's `ASSIGNED` gear assignments (each release
    returning its gear item to `AVAILABLE`), voids the guest's waiver, and recomputes the
    parent reservation's `checked_in_guest_count`."

    Design: Difficulty/transitive_cascade/guest_remove_releases_gear_and_voids_waiver_depth2
    """
    ctx = setup_confirmed_reservation(api, with_gear=True, sign=True, guest_weight=150, guest_age=31)
    validate_success(api.remove_guest(ctx["guest"]["id"], RESV), 200)
    waiver = validate_success(api.get_waiver(ctx["waiver"]["id"], RESV), 200)
    assert waiver["status"] == "VOID"


# ── Check-in blocked by unsigned waiver (cross-entity dependency) ──

def test_checkin_blocked_when_waiver_not_signed(api):
    """PRD §3.5: "every non-`REMOVED` guest on the reservation must have a `SIGNED` waiver,
    otherwise `ERR_WAIVER_NOT_SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_guest_waiver_not_signed
    """
    ctx = setup_confirmed_reservation(api, with_gear=True, sign=False, guest_weight=165, guest_age=26)
    validate_error(api.check_in_reservation(ctx["res"]["id"], RESV), "ERR_WAIVER_NOT_SIGNED")


def test_checkin_succeeds_when_waiver_signed_and_gear_assigned(api):
    """PRD §3.5: "On a successful check-in, every non-`REMOVED` guest on the reservation
    moves from `BOOKED` to `CHECKED_IN`, and the reservation's `checked_in_guest_count` —
    the count of its guests in `status` `CHECKED_IN` — is recomputed."

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_guest_waiver_not_signed
    """
    ctx = setup_confirmed_reservation(api, with_gear=True, sign=True, guest_weight=165, guest_age=26)
    checked_in = validate_success(api.check_in_reservation(ctx["res"]["id"], RESV), 200)
    assert checked_in["fulfillment_status"] == "CHECKED_IN"
    guest = validate_success(api.get_guest(ctx["guest"]["id"], RESV), 200)
    assert guest["status"] == "CHECKED_IN"


# ── Waiver idempotency (corner) ──

def test_sign_waiver_twice_returns_not_pending(api):
    """PRD §3.3: "A waiver that is not `PENDING` cannot be signed; such an attempt is
    rejected with `ERR_WAIVER_NOT_PENDING`."

    Design: Corner/state_machines/sign_waiver_twice_second_returns_not_pending
    """
    trip = create_trip(api, difficulty_class="CLASS_II")
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Ann", age=40, weight_lbs=150)
    waiver = waiver_for_guest(api, guest["id"])
    sign_waiver(api, waiver["id"], guest["id"])
    validate_error(api.sign_waiver(waiver["id"], make_guest_headers(guest["id"]), {}),
                   "ERR_WAIVER_NOT_PENDING")


# ── Age & guardian safety (corner) ──

def test_add_guest_under_min_age_returns_under_min_age(api):
    """PRD §3.3: "the guest's `age` must be at least the trip's `min_age`, otherwise the
    guest is rejected with `ERR_GUEST_UNDER_MIN_AGE`."

    Design: Corner/validations/add_guest_under_min_age_returns_under_min_age
    """
    trip = create_trip(api, min_age=12)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    payload = {"reservation_id": res["id"], "full_name": "Kid", "age": 8, "weight_lbs": 60}
    validate_error(api.create_guest(payload, RESV), "ERR_GUEST_UNDER_MIN_AGE")


def test_minor_waiver_without_guardian_returns_guardian_required(api):
    """PRD §3.3: "If the waiver's `guardian_required` flag is true, a `guardian_name` must
    be supplied in the signing request, otherwise `ERR_GUARDIAN_REQUIRED`."
    PRD §3.3: "it is true when the guest is younger than 18 years old at creation, and
    false otherwise."

    Design: Corner/validations/minor_waiver_signed_without_guardian_returns_guardian_required
    """
    trip = create_trip(api, min_age=8, difficulty_class="CLASS_II")
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Lil", age=10, weight_lbs=70)
    waiver = waiver_for_guest(api, guest["id"])
    validate_error(api.sign_waiver(waiver["id"], make_guest_headers(guest["id"]), {}),
                   "ERR_GUARDIAN_REQUIRED")


# ── Check-in without gear (corner) ──

def test_checkin_without_gear_returns_gear_not_assigned(api):
    """PRD §3.5: "every non-`REMOVED` guest must have an `ASSIGNED` gear assignment for a
    `PFD`, otherwise `ERR_GEAR_NOT_ASSIGNED`."

    Design: Corner/validations/checkin_without_gear_returns_gear_not_assigned
    """
    ctx = setup_confirmed_reservation(api, with_gear=False, sign=True, guest_weight=175, guest_age=33)
    validate_error(api.check_in_reservation(ctx["res"]["id"], RESV), "ERR_GEAR_NOT_ASSIGNED")


# ── Waiver ownership (corner) ──

def test_guest_cannot_sign_another_guests_waiver(api):
    """PRD §3.3: "The signer must be the waiver's owner — the acting `X-User-ID` must equal
    the waiver's `guest_id`, otherwise `ERR_NOT_WAIVER_OWNER`."

    Design: Corner/rbac/guest_cannot_sign_another_guests_waiver_returns_not_owner
    """
    trip = create_trip(api, difficulty_class="CLASS_II")
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Owner", age=40, weight_lbs=150)
    waiver = waiver_for_guest(api, guest["id"])
    other = make_guest_headers("00000000-0000-4000-8000-0000000000ff")
    validate_error(api.sign_waiver(waiver["id"], other, {}), "ERR_NOT_WAIVER_OWNER")
