"""Booking, tiered pricing, parallel status dimensions, trip capacity cycling, and OCC."""
from test_helpers import validate_success, validate_error
from test_helpers.fixtures import (
    create_trip, setup_open_trip, create_reservation, trip_version,
)
from test_helpers import TEST_USERS

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]


# ── Dual-variant totals: estimate uses booked party_size, final uses checked-in count ──

def test_estimated_total_uses_booked_party_size(api):
    """PRD §3.2: "First a group-discount fraction is chosen from the booked `party_size`:
    a party of at least 8 guests earns a fraction of 0.15, otherwise a party of at least 4
    guests earns 0.10, and a smaller party earns 0.00."
    PRD §3.2: "The base term is the `base_rate_cents` multiplied by the `party_size`
    multiplied by one minus that discount fraction, rounded half up to a whole number of
    cents. To the rounded base is added a photo fee of 4000 cents when `photo_addon` is
    true, and nothing when it is false."

    Design: Difficulty/dual_variant_calc/reservation_estimate_vs_final_total_diverge
    """
    trip, _, _ = setup_open_trip(api, base_rate_cents=12000, min_age=12, max_capacity=12)
    res = create_reservation(api, trip["id"], party_size=5, photo_addon=True, deposit_cents=14500)
    # disc(party=5)=0.10 -> round(12000*5*0.90)=54000; +4000 photo = 58000
    assert res["estimated_total_cents"] == 58000


def test_final_total_charges_checked_in_count_and_diverges_from_estimate(api):
    """PRD §3.6: "the base term multiplies `base_rate_cents` by the reservation's
    `checked_in_guest_count` and by one minus that fraction, rounded half up to whole
    cents; to this base is added the 4000-cent photo fee when `photo_addon` is true, and
    then the `gratuity_cents`."
    PRD §3.6: "The final total therefore diverges from the estimate exactly when a guest
    was removed between booking and check-in."

    Design: Difficulty/dual_variant_calc/reservation_estimate_vs_final_total_diverge
    """
    from test_helpers.fixtures import setup_checked_in_reservation
    ctx = setup_checked_in_reservation(
        api, party_size=5, photo_addon=True, deposit_cents=14500,
        base_rate_cents=12000, min_age=12, max_capacity=12,
        guest_weight=180, guest_age=30, pfd_min_weight=100, pfd_max_weight=250,
    )
    settled = validate_success(api.settle_reservation(ctx["res"]["id"], RESV, {"gratuity_cents": 5000}), 200)
    # checked_in_guest_count=1; disc keyed on booked party_size=5 -> 0.10
    # base=round(12000*1*0.90)=10800; +4000 photo +5000 gratuity = 19800
    assert settled["estimated_total_cents"] == 58000
    assert settled["final_total_cents"] == 19800
    assert settled["estimated_total_cents"] != settled["final_total_cents"]


# ── Combinatorial estimate: tiered discount + conditional photo branch ──

def test_estimated_total_party_eight_fifteen_percent_with_photo(api):
    """PRD §3.2: "a party of at least 8 guests earns a fraction of 0.15, otherwise a party
    of at least 4 guests earns 0.10, and a smaller party earns 0.00."
    PRD §3.2: "The base term is the `base_rate_cents` multiplied by the `party_size`
    multiplied by one minus that discount fraction, rounded half up to a whole number of
    cents. To the rounded base is added a photo fee of 4000 cents when `photo_addon` is
    true, and nothing when it is false."

    Design: Difficulty/combinatorial_formula/estimated_total_tiered_discount_with_photo_mode_a
    """
    trip, _, _ = setup_open_trip(api, base_rate_cents=12000, max_capacity=20, min_age=12)
    res = create_reservation(api, trip["id"], party_size=8, photo_addon=True, deposit_cents=21400)
    # disc(8)=0.15 -> round(12000*8*0.85)=81600; +4000 = 85600
    assert res["estimated_total_cents"] == 85600


def test_estimated_total_party_eight_without_photo_omits_fee(api):
    """PRD §3.2: "The base term is the `base_rate_cents` multiplied by the `party_size`
    multiplied by one minus that discount fraction, rounded half up to a whole number of
    cents. To the rounded base is added a photo fee of 4000 cents when `photo_addon` is
    true, and nothing when it is false."

    Design: Difficulty/combinatorial_formula/estimated_total_tiered_discount_with_photo_mode_a
    """
    trip, _, _ = setup_open_trip(api, base_rate_cents=12000, max_capacity=20, min_age=12)
    res = create_reservation(api, trip["id"], party_size=8, photo_addon=False, deposit_cents=21400)
    # disc(8)=0.15 -> round(12000*8*0.85)=81600; no photo -> 81600
    assert res["estimated_total_cents"] == 81600


# ── Group-discount tier boundary (corner) ──

def test_group_discount_tier_boundary_at_party_four(api):
    """PRD §3.2: "First a group-discount fraction is chosen from the booked `party_size`:
    a party of at least 8 guests earns a fraction of 0.15, otherwise a party of at least 4
    guests earns 0.10, and a smaller party earns 0.00."

    Design: Corner/calculations/group_discount_tier_boundary_at_party_four
    """
    trip = create_trip(api, base_rate_cents=12000, difficulty_class="CLASS_II")
    res = create_reservation(api, trip["id"], party_size=4, deposit_cents=11000)
    # disc(4)=0.10 -> round(12000*4*0.90)=43200
    assert res["estimated_total_cents"] == 43200


def test_photo_addon_defaults_false(api):
    """PRD §3.2: "an optional `photo_addon` flag defaulting to false"
    PRD §3.2: "To the rounded base is added a photo fee of 4000 cents when `photo_addon`
    is true, and nothing when it is false."

    Design: Corner/entities/create_reservation_photo_addon_defaults_false
    """
    trip = create_trip(api, base_rate_cents=12000)
    # No photo_addon supplied -> defaults false; party_size=1 -> disc 0 -> base 12000, no photo
    payload = {
        "trip_id": trip["id"], "booking_type": "GROUP", "party_size": 1,
        "deposit_cents": 3000, "expected_trip_version": trip["version"],
    }
    res = validate_success(api.create_reservation(payload, RESV), 201)
    assert res["photo_addon"] is False
    assert res["estimated_total_cents"] == 12000


# ── Parallel payment × fulfillment dimensions ──

def test_confirm_advances_fulfillment_leaves_payment_unpaid(api):
    """PRD §3.2: "A reservation carries two independent status dimensions: `payment_status`
    (one of `UNPAID`, `DEPOSIT_PAID`, `SETTLED`, `REFUNDED`) tracks money, and
    `fulfillment_status` (one of `PENDING`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`,
    `CANCELLED`) tracks the guest journey; the two move independently."
    PRD §3.2: "Confirming a reservation advances its `fulfillment_status` from `PENDING`
    to `CONFIRMED` and commits its guests against trip capacity."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_and_fulfillment_dimensions
    """
    trip, _, _ = setup_open_trip(api)
    res = create_reservation(api, trip["id"], party_size=2, deposit_cents=6000)
    confirmed = validate_success(api.confirm_reservation(res["id"], RESV), 200)
    assert confirmed["fulfillment_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "UNPAID"


def test_pay_deposit_advances_payment_leaves_fulfillment_confirmed(api):
    """PRD §3.6: "Recording it advances the reservation's `payment_status` from `UNPAID`
    to `DEPOSIT_PAID`."
    PRD §3.2: "A reservation carries two independent status dimensions: `payment_status`
    (one of `UNPAID`, `DEPOSIT_PAID`, `SETTLED`, `REFUNDED`) tracks money, and
    `fulfillment_status` (one of `PENDING`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`,
    `CANCELLED`) tracks the guest journey; the two move independently."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_and_fulfillment_dimensions
    """
    trip, _, _ = setup_open_trip(api)
    res = create_reservation(api, trip["id"], party_size=2, deposit_cents=6000)
    validate_success(api.confirm_reservation(res["id"], RESV), 200)
    paid = validate_success(api.pay_deposit(res["id"], RESV), 200)
    assert paid["payment_status"] == "DEPOSIT_PAID"
    assert paid["fulfillment_status"] == "CONFIRMED"


# ── Trip cyclic OPEN -> FULL -> OPEN ──

def test_confirm_to_capacity_drives_trip_full(api):
    """PRD §3.2: "If that recomputation brings `committed_guests` up to `max_capacity`, or
    if the confirming reservation is `PRIVATE`, the trip transitions from `OPEN` to `FULL`;
    a `PRIVATE` confirmation additionally sets the trip's `booking_mode` to `PRIVATE`."

    Design: Difficulty/non_linear_state_machine/trip_cyclic_full_then_reopen_on_cancel
    """
    trip, _, _ = setup_open_trip(api, max_capacity=2)
    res = create_reservation(api, trip["id"], party_size=2, deposit_cents=6000)
    validate_success(api.confirm_reservation(res["id"], RESV), 200)
    trip_after = validate_success(api.get_trip(trip["id"], RESV), 200)
    assert trip_after["status"] == "FULL"


def test_cancel_reservation_reopens_full_trip(api):
    """PRD §3.2: "When a `CONFIRMED` or `CHECKED_IN` reservation later cancels and frees
    capacity, the trip returns from `FULL` to `OPEN` provided two conditions hold: after
    the cancellation the trip's `committed_guests` is strictly below `max_capacity`, and
    the trip's `booking_mode` is `GROUP`."

    Design: Difficulty/non_linear_state_machine/trip_cyclic_full_then_reopen_on_cancel
    """
    trip, _, _ = setup_open_trip(api, max_capacity=2)
    res = create_reservation(api, trip["id"], party_size=2, deposit_cents=6000)
    validate_success(api.confirm_reservation(res["id"], RESV), 200)
    assert validate_success(api.get_trip(trip["id"], RESV), 200)["status"] == "FULL"
    validate_success(api.cancel_reservation(res["id"], RESV), 200)
    trip_after = validate_success(api.get_trip(trip["id"], RESV), 200)
    assert trip_after["status"] == "OPEN"


# ── Capacity & private conflict (corner) ──

def test_confirm_beyond_capacity_returns_capacity_exceeded(api):
    """PRD §3.2: "The trip must have room: the trip's current `committed_guests` plus this
    reservation's `party_size` must not exceed `max_capacity`, otherwise
    `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/confirm_beyond_capacity_returns_capacity_exceeded
    """
    trip, _, _ = setup_open_trip(api, max_capacity=2)
    res = create_reservation(api, trip["id"], party_size=3, deposit_cents=9000)
    validate_error(api.confirm_reservation(res["id"], RESV), "ERR_CAPACITY_EXCEEDED")


def test_private_confirm_conflicts_with_existing_confirmed(api):
    """PRD §3.2: "if the `booking_type` is `PRIVATE`, no other reservation on the trip may
    already be `CONFIRMED` or `CHECKED_IN`, otherwise `ERR_PRIVATE_CONFLICT`; the same
    conflict error guards a `GROUP` confirmation attempted while a `PRIVATE` booking
    already holds the trip."

    Design: Corner/validations/private_confirm_conflicts_with_existing_confirmed_reservation
    """
    trip, _, _ = setup_open_trip(api)
    res_group = create_reservation(api, trip["id"], booking_type="GROUP", party_size=1, deposit_cents=3000)
    validate_success(api.confirm_reservation(res_group["id"], RESV), 200)
    v = trip_version(api, trip["id"])
    res_priv = create_reservation(api, trip["id"], version=v, booking_type="PRIVATE", party_size=1, deposit_cents=3000)
    validate_error(api.confirm_reservation(res_priv["id"], RESV), "ERR_PRIVATE_CONFLICT")


def test_confirm_reflects_new_state_in_same_response(api):
    """PRD §3.2: "Confirming a reservation advances its `fulfillment_status` from `PENDING`
    to `CONFIRMED` and commits its guests against trip capacity."
    PRD §2.2: "operations that create or modify a resource will return the created or
    updated resource object in the data field."

    Design: Corner/consistency_model/confirm_reflects_new_state_in_same_response
    """
    trip, _, _ = setup_open_trip(api)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    confirmed = validate_success(api.confirm_reservation(res["id"], RESV), 200)
    assert confirmed["fulfillment_status"] == "CONFIRMED"


# ── Optimistic concurrency on the trip version ──

def test_reservation_create_with_stale_trip_version_rejected(api):
    """PRD §2.9: "If `expected_trip_version` does not equal the trip's current `version`,
    the create is rejected with `ERR_STALE_TRIP_VERSION` (HTTP 412)"
    PRD §2.9: "two strictly sequential creates carrying the same `expected_trip_version`
    behave as expected: the first advances the version and succeeds, and the second, still
    carrying the now-behind value, is rejected as stale."

    Design: Corner/cross_cutting/reservation_create_with_stale_trip_version_rejected
    """
    trip = create_trip(api, difficulty_class="CLASS_II")
    v = trip["version"]
    from test_helpers.factories import create_reservation_payload
    validate_success(api.create_reservation(create_reservation_payload(trip["id"], v), RESV), 201)
    validate_error(api.create_reservation(create_reservation_payload(trip["id"], v), RESV),
                   "ERR_STALE_TRIP_VERSION")


def test_reservation_create_with_current_version_succeeds_and_bumps_version(api):
    """PRD §2.9: "On success, the booking increments the `RiverTrip.version` by one, so
    that two strictly sequential creates carrying the same `expected_trip_version` behave
    as expected: the first advances the version and succeeds, and the second, still
    carrying the now-behind value, is rejected as stale."

    Design: Corner/cross_cutting/reservation_create_with_current_trip_version_succeeds
    """
    from test_helpers.factories import create_reservation_payload
    trip = create_trip(api, difficulty_class="CLASS_II")
    validate_success(api.create_reservation(create_reservation_payload(trip["id"], trip["version"]), RESV), 201)
    trip_after = validate_success(api.get_trip(trip["id"], RESV), 200)
    assert trip_after["version"] == 2
