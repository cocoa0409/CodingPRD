"""Charter bookings: quoting/settlement pricing, reschedule cycle, loyalty
cascade on completion, guide availability, buffered overlap, and the
state-over-temporal validation-precedence rule."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_customer_headers, make_guide_headers,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]

GUIDE_KW = dict(half_day_rate_cents=25000, full_day_rate_cents=45000,
                per_extra_angler_cents=5000, max_party_size=6, fuel_surcharge_cents=3000)


# --- Corner: validations / val_party_too_large_on_quote ---

def test_quote_party_over_guide_max_rejected(api):
    """PRD 3.5: "Quoting** (`REQUESTED → QUOTED`), performed by a `ShopClerk`, first checks that `party_size` does not exceed the guide's `max_party_size`; if it does, the quote is rejected with `ERR_PARTY_TOO_LARGE` (HTTP 409)."

    Design: Corner/validations/val_party_too_large_on_quote
    """
    customer = fixtures.create_customer(name="Big Party", email="bp@x.com")
    guide = fixtures.create_guide(name="Cap Small", guide_license_no="G-9",
                                  half_day_rate_cents=20000, full_day_rate_cents=40000,
                                  per_extra_angler_cents=5000, max_party_size=4)
    venue = fixtures.create_venue(name="Tiny Pond", water_type="POND")
    booking = fixtures.create_booking(customer["id"], guide["id"], venue["id"],
                                      trip_type="HALF_DAY", party_size=6,
                                      start_at="2026-07-15T08:00:00Z", end_at="2026-07-15T12:00:00Z")
    resp = api.transition_charter_booking(booking["id"], {"action": "QUOTE"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_PARTY_TOO_LARGE.value)


# --- Corner: endpoints / endpoint_charter_bookings_filter_by_guide ---

def test_list_charter_bookings_filtered_by_guide(api):
    """PRD 2.3: "Every list response reports `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring pagination), and `has_more` (true when records remain beyond the current page) inside `meta`."

    Design: Corner/endpoints/endpoint_charter_bookings_filter_by_guide
    """
    customer = fixtures.create_customer(name="Filt Cust", email="fc@x.com")
    guide = fixtures.create_guide(name="Cap Filt", guide_license_no="G-10", **GUIDE_KW)
    venue = fixtures.create_venue(name="Filt Lake", water_type="LAKE")
    booking = fixtures.create_booking(customer["id"], guide["id"], venue["id"],
                                      trip_type="HALF_DAY", party_size=2,
                                      start_at="2026-07-18T08:00:00Z", end_at="2026-07-18T12:00:00Z")
    resp = api.list_charter_bookings(CLERK, params={"guide_id": guide["id"]})
    data, _meta = validate_paginated(resp)
    match = [b for b in data if b["id"] == booking["id"]]
    assert match, f"listing filtered by guide should contain booking {booking['id']}"
    assert match[0]["guide_id"] == guide["id"]


# --- Difficulty: dual_variant_calc / charter_provisional_vs_final_diverge ---

def _setup_confirmed_full_day_july(api):
    """Clock OFF at quote (April), FULL_DAY party 4 + equipment, trip in July.
    Returns (customer, guide, booking) with booking CONFIRMED."""
    fixtures.set_clock("2026-04-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler A", email="a@x.com")
    guide = fixtures.create_guide(name="Cap Joe", guide_license_no="G-1", **GUIDE_KW)
    venue = fixtures.create_venue(name="Blue Lake", water_type="LAKE")
    booking = fixtures.create_booking(customer["id"], guide["id"], venue["id"],
                                      trip_type="FULL_DAY", party_size=4,
                                      start_at="2026-07-10T08:00:00Z",
                                      end_at="2026-07-10T16:00:00Z",
                                      add_equipment_rental=True)
    quoted = fixtures.quote_booking(booking["id"])
    confirmed = fixtures.confirm_booking(booking["id"], customer["id"])
    return customer, guide, confirmed, quoted


def test_charter_provisional_quote_off_season(api):
    """PRD 3.5: "The provisional seasonal multiplier is 1.20 during peak months and 1.00 otherwise; `provisional_total_cents` is the components multiplied by that multiplier and rounded half up. The `deposit_cents` is `provisional_total_cents` multiplied by one quarter and rounded half up."

    Design: Difficulty/dual_variant_calc/charter_provisional_vs_final_diverge
    """
    _c, _g, _b, quoted = _setup_confirmed_full_day_july(api)
    # components = 45000 (full-day) + max(0,4-2)*5000 + 2500*4 = 45000+10000+10000 = 65000
    # clock month April -> OFF -> x1.00
    assert quoted["provisional_total_cents"] == 65000
    assert quoted["deposit_cents"] == 16250, "round(65000 * 0.25)"


def test_charter_final_settlement_diverges_from_provisional(api):
    """PRD 3.5: "The final seasonal multiplier is taken from the month of `start_at` rather than the clock: 1.20 when `start_at` falls in May, June, July, or August, and 1.00 otherwise."
    PRD 3.5: "The `final_total_cents` is the final subtotal minus that tier discount plus the guide's `fuel_surcharge_cents`."
    PRD 3.5: "points_awarded` is `final_total_cents` divided by 100 multiplied by the holder's tier multiplier (1.00 for `BRONZE`, 1.10 for `SILVER`, 1.25 for `GOLD`), rounded half up."

    Design: Difficulty/dual_variant_calc/charter_provisional_vs_final_diverge
    """
    customer, guide, confirmed, _quoted = _setup_confirmed_full_day_july(api)
    completed = fixtures.complete_booking(confirmed["id"], guide["id"])
    # final_subtotal = round(65000 * 1.20) = 78000; BRONZE discount 0; + fuel 3000 = 81000
    assert completed["final_total_cents"] == 81000
    assert completed["points_awarded"] == 810, "round(81000/100 * 1.00)"
    assert completed["final_total_cents"] != confirmed["provisional_total_cents"], (
        "final diverges from provisional for the identical booking"
    )


# --- Difficulty: combinatorial_formula / charter_cost_nonlinear_inputs_mode_a ---

def _setup_half_day_peak_booking(api):
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler C", email="c@x.com")
    guide = fixtures.create_guide(name="Cap Ann", guide_license_no="G-2", **GUIDE_KW)
    venue = fixtures.create_venue(name="Reed River", water_type="RIVER")
    booking = fixtures.create_booking(customer["id"], guide["id"], venue["id"],
                                      trip_type="HALF_DAY", party_size=3,
                                      start_at="2026-07-20T06:00:00Z",
                                      end_at="2026-07-20T10:00:00Z",
                                      add_equipment_rental=False)
    return customer, guide, booking


def test_charter_halfday_peak_provisional_nonlinear(api):
    """PRD 3.5: "The base is the guide's `full_day_rate_cents` for a `FULL_DAY` trip or `half_day_rate_cents` for a `HALF_DAY` trip. The extra-angler charge is the number of anglers above the two included anglers — never below zero — multiplied by `per_extra_angler_cents`."

    Design: Difficulty/combinatorial_formula/charter_cost_nonlinear_inputs_mode_a
    """
    _c, _g, booking = _setup_half_day_peak_booking(api)
    quoted = fixtures.quote_booking(booking["id"])
    # (25000 + max(0,3-2)*5000 + 0) * 1.20 = 30000 * 1.20 = 36000
    assert quoted["provisional_total_cents"] == 36000


def test_confirm_before_quote_rejected_invalid_state(api):
    """PRD 2.8: "When more than one rule could reject a request, checks are evaluated in a fixed priority order, and the first failing check determines the returned error."
    PRD 3.5: "Confirmation** (`QUOTED → CONFIRMED`), performed by the `Customer`, requires that the guide is `AVAILABLE".

    Design: Difficulty/combinatorial_formula/charter_cost_nonlinear_inputs_mode_a
    """
    customer, _g, booking = _setup_half_day_peak_booking(api)
    # booking is REQUESTED (never quoted); CONFIRM is only valid from QUOTED.
    resp = api.transition_charter_booking(
        booking["id"], {"action": "CONFIRM"}, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Difficulty: non_linear_state_machine / charter_reschedule_cycle ---

def _setup_quoted_full_day_off(api):
    fixtures.set_clock("2026-04-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler E", email="e@x.com")
    guide = fixtures.create_guide(name="Cap Bo", guide_license_no="G-3",
                                  half_day_rate_cents=25000, full_day_rate_cents=45000,
                                  per_extra_angler_cents=5000, max_party_size=6)
    venue = fixtures.create_venue(name="Green Pond", water_type="POND")
    booking = fixtures.create_booking(customer["id"], guide["id"], venue["id"],
                                      trip_type="FULL_DAY", party_size=2,
                                      start_at="2026-04-10T08:00:00Z",
                                      end_at="2026-04-10T16:00:00Z")
    quoted = fixtures.quote_booking(booking["id"])
    return customer, guide, booking, quoted


def test_reschedule_returns_booking_to_requested(api):
    """PRD 3.5: "Rescheduling** (`QUOTED → REQUESTED` or `CONFIRMED → REQUESTED`), performed by the `Customer`, applies a new `start_at` and `end_at`, and optionally a new `trip_type` or `party_size`, then clears `provisional_total_cents`, `deposit_cents`, and `season_at_quote` so the booking must be re-quoted before it can be confirmed again."

    Design: Difficulty/non_linear_state_machine/charter_reschedule_cycle
    """
    customer, _g, booking, quoted = _setup_quoted_full_day_off(api)
    assert quoted["provisional_total_cents"] == 45000, "FULL_DAY base, OFF season"
    resched = validate_success(api.transition_charter_booking(
        booking["id"],
        {"action": "RESCHEDULE", "start_at": "2026-04-11T08:00:00Z",
         "end_at": "2026-04-11T12:00:00Z", "trip_type": "HALF_DAY"},
        make_customer_headers(customer["id"]),
    ))
    assert resched["status"] == "REQUESTED", "booking looped back to REQUESTED"


def test_requote_after_reschedule_recomputes_provisional(api):
    """PRD 3.5: "The base is the guide's `full_day_rate_cents` for a `FULL_DAY` trip or `half_day_rate_cents` for a `HALF_DAY` trip."
    PRD 3.5: "then clears `provisional_total_cents`, `deposit_cents`, and `season_at_quote` so the booking must be re-quoted before it can be confirmed again."

    Design: Difficulty/non_linear_state_machine/charter_reschedule_cycle
    """
    customer, _g, booking, _quoted = _setup_quoted_full_day_off(api)
    validate_success(api.transition_charter_booking(
        booking["id"],
        {"action": "RESCHEDULE", "start_at": "2026-04-11T08:00:00Z",
         "end_at": "2026-04-11T12:00:00Z", "trip_type": "HALF_DAY"},
        make_customer_headers(customer["id"]),
    ))
    requoted = fixtures.quote_booking(booking["id"])
    assert requoted["status"] == "QUOTED", "re-quoted after the cycle"
    assert requoted["provisional_total_cents"] == 25000, "HALF_DAY base, OFF season"


# --- Difficulty: transitive_cascade / charter_complete_tier_upgrade_cascade_depth3 ---

def test_charter_complete_mints_points(api):
    """PRD 3.5: "Completion mints loyalty: `points_awarded` is `final_total_cents` divided by 100 multiplied by the holder's tier multiplier (1.00 for `BRONZE`, 1.10 for `SILVER`, 1.25 for `GOLD`), rounded half up."

    Design: Difficulty/transitive_cascade/charter_complete_tier_upgrade_cascade_depth3
    """
    customer, guide, confirmed, _quoted = _setup_confirmed_full_day_july(api)
    completed = fixtures.complete_booking(confirmed["id"], guide["id"])
    assert completed["points_awarded"] == 810


def test_charter_complete_cascades_balance_and_tier(api):
    """PRD 3.5: "A ledger entry with that `delta_points`, a `reason` of `CHARTER_COMPLETE`, and a reference back to the booking is appended to the holder, the holder's `loyalty_points_balance` and `loyalty_tier` are recomputed, and `final_total_cents` is added to the holder's `lifetime_spend_cents`."
    PRD 2.9: "the tier is `BRONZE` when the balance is below 500, `SILVER` when the balance is at least 500 but below 2000, and `GOLD` when the balance is 2000 or more".

    Design: Difficulty/transitive_cascade/charter_complete_tier_upgrade_cascade_depth3
    """
    customer, guide, confirmed, _quoted = _setup_confirmed_full_day_july(api)
    fixtures.complete_booking(confirmed["id"], guide["id"])
    holder = fixtures.get_customer(customer["id"])
    assert holder["loyalty_points_balance"] == 810, "single ledger entry from this completion"
    assert holder["loyalty_tier"] == "SILVER", "810 >= SILVER_MIN 500, crossed by the cascade"


# --- Difficulty: cross_entity_state_dependency / confirm_blocked_by_suspended_guide ---

def _setup_quoted_booking_and_guide(api):
    customer = fixtures.create_customer(name="Angler K", email="k@x.com")
    guide = fixtures.create_guide(name="Cap Fi", guide_license_no="G-6",
                                  half_day_rate_cents=25000, full_day_rate_cents=45000,
                                  per_extra_angler_cents=5000, max_party_size=6)
    venue = fixtures.create_venue(name="Mirror Lake", water_type="LAKE")
    booking = fixtures.create_booking(customer["id"], guide["id"], venue["id"],
                                      trip_type="HALF_DAY", party_size=2,
                                      start_at="2026-07-12T08:00:00Z",
                                      end_at="2026-07-12T12:00:00Z")
    fixtures.quote_booking(booking["id"])
    return customer, guide, booking


def test_confirm_suspended_guide_rejected(api):
    """PRD 3.5: "Confirmation** (`QUOTED → CONFIRMED`), performed by the `Customer`, requires that the guide is `AVAILABLE`; a confirmation against a suspended guide is rejected with `ERR_GUIDE_SUSPENDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_suspended_guide
    """
    customer, guide, booking = _setup_quoted_booking_and_guide(api)
    validate_success(api.update_guide(guide["id"], {"status": "SUSPENDED"}, MANAGER))
    resp = api.transition_charter_booking(
        booking["id"], {"action": "CONFIRM"}, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_GUIDE_SUSPENDED.value)


def test_confirm_succeeds_after_guide_reinstated(api):
    """PRD 3.5: "Suspending a guide leaves existing confirmed bookings intact but blocks new confirmations while suspended."
    PRD 3.5: "Confirmation** (`QUOTED → CONFIRMED`), performed by the `Customer`, requires that the guide is `AVAILABLE".

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_suspended_guide
    """
    customer, guide, booking = _setup_quoted_booking_and_guide(api)
    validate_success(api.update_guide(guide["id"], {"status": "SUSPENDED"}, MANAGER))
    validate_success(api.update_guide(guide["id"], {"status": "AVAILABLE"}, MANAGER))
    confirmed = validate_success(api.transition_charter_booking(
        booking["id"], {"action": "CONFIRM"}, make_customer_headers(customer["id"])
    ))
    assert confirmed["status"] == "CONFIRMED"


# --- Difficulty: resource_temporal_overlap / guide_buffered_overlap_conflict ---

def _setup_confirmed_a_and_quoted_b(api, b_start, b_end):
    guide = fixtures.create_guide(name="Cap Gus", guide_license_no="G-7",
                                  half_day_rate_cents=25000, full_day_rate_cents=45000,
                                  per_extra_angler_cents=5000, max_party_size=6)
    venue = fixtures.create_venue(name="Buffer Bay", water_type="SALTWATER")
    c1 = fixtures.create_customer(name="Cust P", email="p@x.com")
    c2 = fixtures.create_customer(name="Cust Q", email="q@x.com")
    booking_a = fixtures.create_booking(c1["id"], guide["id"], venue["id"],
                                        trip_type="HALF_DAY", party_size=2,
                                        start_at="2026-07-10T08:00:00Z",
                                        end_at="2026-07-10T12:00:00Z")
    fixtures.quote_booking(booking_a["id"])
    fixtures.confirm_booking(booking_a["id"], c1["id"])
    booking_b = fixtures.create_booking(c2["id"], guide["id"], venue["id"],
                                        trip_type="HALF_DAY", party_size=2,
                                        start_at=b_start, end_at=b_end)
    fixtures.quote_booking(booking_b["id"])
    return c2, booking_b


def test_guide_buffered_overlap_confirmation_rejected(api):
    """PRD 3.5: "It also requires that the guide has no other `CONFIRMED` or `COMPLETED` booking whose time window, taken as the half-open interval from `start_at` to `end_at` and padded on both sides by 60 minutes, overlaps this booking's padded window; an overlap is rejected with `ERR_GUIDE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/guide_buffered_overlap_conflict
    """
    # Booking A 08:00-12:00; Booking B 12:30-16:00 — 30-min gap < 60-min buffer.
    c2, booking_b = _setup_confirmed_a_and_quoted_b(api, "2026-07-10T12:30:00Z", "2026-07-10T16:00:00Z")
    resp = api.transition_charter_booking(
        booking_b["id"], {"action": "CONFIRM"}, make_customer_headers(c2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_GUIDE_UNAVAILABLE.value)


def test_guide_confirmation_outside_buffer_succeeds(api):
    """PRD 3.5: "It also requires that the guide has no other `CONFIRMED` or `COMPLETED` booking whose time window, taken as the half-open interval from `start_at` to `end_at` and padded on both sides by 60 minutes, overlaps this booking's padded window; an overlap is rejected with `ERR_GUIDE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/guide_buffered_overlap_conflict
    """
    # Booking A padded = [07:00, 13:00); Booking B 14:00-18:00 padded = [13:00, 19:00) — adjacent, no overlap.
    c2, booking_b = _setup_confirmed_a_and_quoted_b(api, "2026-07-10T14:00:00Z", "2026-07-10T18:00:00Z")
    confirmed = validate_success(api.transition_charter_booking(
        booking_b["id"], {"action": "CONFIRM"}, make_customer_headers(c2["id"])
    ))
    assert confirmed["status"] == "CONFIRMED"


# --- Difficulty: priority_pair_validation_conflict / state_beats_temporal_on_confirm ---

def _setup_confirmed_a_and_requested_overlapping_b(api):
    c1 = fixtures.create_customer(name="Cust One", email="c1@x.com")
    c2 = fixtures.create_customer(name="Cust Two", email="c2@x.com")
    guide = fixtures.create_guide(name="Cap Ed", guide_license_no="G-5",
                                  half_day_rate_cents=25000, full_day_rate_cents=45000,
                                  per_extra_angler_cents=5000, max_party_size=6)
    venue = fixtures.create_venue(name="Twin Lakes", water_type="LAKE")
    booking_a = fixtures.create_booking(c1["id"], guide["id"], venue["id"],
                                        trip_type="HALF_DAY", party_size=2,
                                        start_at="2026-07-10T08:00:00Z",
                                        end_at="2026-07-10T12:00:00Z")
    fixtures.quote_booking(booking_a["id"])
    fixtures.confirm_booking(booking_a["id"], c1["id"])
    # Booking B overlaps A's slot but is left REQUESTED (never quoted).
    booking_b = fixtures.create_booking(c2["id"], guide["id"], venue["id"],
                                        trip_type="HALF_DAY", party_size=2,
                                        start_at="2026-07-10T09:00:00Z",
                                        end_at="2026-07-10T11:00:00Z")
    return c2, booking_b


def test_state_error_precedes_temporal_on_confirm(api):
    """PRD 2.8: "When more than one rule could reject a request, checks are evaluated in a fixed priority order, and the first failing check determines the returned error."
    PRD 2.8: "6. **State** — the target resource is in a state that permits the requested transition or action, else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_confirm
    """
    c2, booking_b = _setup_confirmed_a_and_requested_overlapping_b(api)
    resp = api.transition_charter_booking(
        booking_b["id"], {"action": "CONFIRM"}, make_customer_headers(c2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_requested_booking_cannot_confirm_despite_conflict(api):
    """PRD 2.8: "Because this ordering is fixed, a resource that is simultaneously in the wrong state and would also violate a capacity rule surfaces the state error first."
    PRD 3.5: "Confirmation** (`QUOTED → CONFIRMED`), performed by the `Customer".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_confirm
    """
    c2, booking_b = _setup_confirmed_a_and_requested_overlapping_b(api)
    # Even though B overlaps A's confirmed slot (temporal, priority 9), the
    # un-quoted (REQUESTED) state failure at priority 6 is surfaced first.
    resp = api.transition_charter_booking(
        booking_b["id"], {"action": "CONFIRM"}, make_customer_headers(c2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
