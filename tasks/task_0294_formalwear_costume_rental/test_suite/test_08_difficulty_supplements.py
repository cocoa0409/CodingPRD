"""Second tests for difficulty-design instances (each instance gets >= 2 tests).

Every test here independently satisfies the PRD-first filter and is tagged to the
same difficulty instance it complements.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm, create_measurement_profile, make_customer_headers,
    create_picked_up_reservation, return_reservation,
    create_party, advance_clock,
    ledger_for_reservation, assert_deposit_conserved, available_unit_count,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import (
    create_reservation_payload, create_fit_check_payload, create_alteration_payload,
)

CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}
ONTIME_RESV = {
    "event_date_iso": "2026-09-04T00:00:00Z",
    "pickup_window_start_iso": "2026-09-01T09:00:00Z",
    "return_window_end_iso": "2026-09-03T17:00:00Z",
}


# ── #3 settlement_charges_nested_min_max_branches ─────────────────────

def test_damaged_without_waiver_credit_is_zero(api):
    """PRD §3.7: "when the waiver was not purchased it is 0."
    PRD §3.7: "The `net_charge_cents` — what the customer still owes beyond the deposit — is the gross fees minus the deposit, floored at 0 so it is never negative."

    Design: Difficulty/combinatorial_formula/settlement_charges_nested_min_max_branches
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Gown C2"},
        reservation_overrides={**ONTIME_RESV, "damage_waiver_opted": False})
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "DAMAGED")

    assert settlement["damage_fee_cents"] == 48000
    assert settlement["waiver_credit_cents"] == 0, "no waiver -> no credit"
    # gross 48000 - deposit 20000 = 28000 (no waiver to soften it).
    assert settlement["net_charge_cents"] == 28000


# ── #4 booking_quote_round_per_day_then_multiply ──────────────────────

def test_round_per_day_tier3_eight_days(api):
    """PRD §3.4: "a span of 8 days or more uses 0.80."
    PRD §3.4: "first compute the effective per-day rate by multiplying `daily_rate_cents` by the chosen multiplier and rounding that per-day figure half-up to whole cents, and only then multiply the rounded per-day rate by `rental_days".

    Design: Difficulty/combinatorial_formula/booking_quote_round_per_day_then_multiply
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Suit D2", "daily_rate_cents": 3333})
    create_unit(catalog["id"], "M")
    customer = create_customer()
    # 8-day span: pickup 09-01, return 09-08 -> rental_days 8, tier3 0.80.
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                              event_date_iso="2026-09-09T00:00:00Z",
                              pickup_window_start_iso="2026-09-01T09:00:00Z",
                              return_window_end_iso="2026-09-08T09:00:00Z")
    confirmed = validate_success(confirm(resv["id"]), 200)
    assert confirmed["rental_days"] == 8
    # round(3333*0.80)=2666 *8 = 21328 (NOT round(3333*0.80*8)=21331).
    assert confirmed["quoted_charge_cents"] == 21328, \
        f"round-per-day tier3 must give 21328; got {confirmed['quoted_charge_cents']}"


# ── #7 party_dissolve_cascades_member_cancel_then_unit_release ─────────

def test_dissolve_cancels_pending_member(api):
    """PRD §3.9: "Dissolving moves the `posture` from `FORMING` to the terminal `DISSOLVED` and cascades over the membership: every `PENDING` member reservation is cancelled".

    Design: Difficulty/transitive_cascade/party_dissolve_cascades_member_cancel_then_unit_release
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux G3"})
    create_unit(catalog["id"], "M")
    coordinator = create_customer()
    coord_headers = make_customer_headers(coordinator["id"])
    party = create_party(coordinator["id"], required_member_count=2,
                         event_date_iso="2026-09-06T00:00:00Z")
    # A PENDING member reservation (never confirmed) linked to the party.
    resv = validate_success(api_client.create_reservation(
        create_reservation_payload(coordinator["id"], catalog["id"], requested_size_code="M",
                                   event_date_iso="2026-09-06T00:00:00Z",
                                   party_order_id=party["id"]),
        coord_headers), 201)
    assert resv["status"] == "PENDING"

    dissolved = validate_success(api_client.dissolve_party_order(party["id"], coord_headers), 200)
    assert dissolved["posture"] == "DISSOLVED"
    after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert after["status"] == "CANCELLED", "PENDING member cancelled by dissolve"


# ── #8 lost_return_cascades_unit_retire_then_catalog_recount ──────────

def test_two_damage_strikes_auto_retire_recounts_catalog(api):
    """PRD §3.7: "If the disposition was `DAMAGED` or `LOST`, the unit's `condition_grade` is downgraded by one grade and its `damage_strike_count` is increased by 1; and the unit is automatically retired — carried to `RETIRED` — when its `damage_strike_count` reaches 2 or more".
    PRD §3.7: "A unit auto-retired in this way has its owning catalog's `active_unit_count` recomputed downward."

    Design: Difficulty/transitive_cascade/lost_return_cascades_unit_retire_then_catalog_recount
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux H3"})
    unit = create_unit(catalog["id"], "M")
    cust1 = create_customer()
    cust2 = create_customer()
    mp1 = create_measurement_profile(cust1["id"], chest_cm=100)
    mp2 = create_measurement_profile(cust2["id"], chest_cm=100)

    # First DAMAGED return: strike 1, grade downgraded, unit goes IN_CLEANING (not retired).
    resv1 = create_reservation(cust1["id"], catalog["id"], requested_size_code="M",
                               **ONTIME_RESV)
    validate_success(confirm(resv1["id"]), 200)
    validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv1["id"], mp1["id"]), CLERK), 201)
    validate_success(api_client.pickup_reservation(resv1["id"], CLERK), 200)
    return_reservation(resv1["id"], "2026-09-03T12:00:00Z", "DAMAGED")
    mid = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert mid["damage_strike_count"] == 1
    assert mid["status"] != "RETIRED", "one strike does not retire"

    # Clear cleaning so the unit is AVAILABLE again (buffer elapsed by 09-06).
    advance_clock("2026-09-06T12:00:00Z")
    cleared = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert cleared["status"] == "AVAILABLE"

    # Second DAMAGED return: strike 2 -> auto-retire, catalog recount to 0.
    resv2 = create_reservation(cust2["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-12T00:00:00Z",
                               pickup_window_start_iso="2026-09-07T09:00:00Z",
                               return_window_end_iso="2026-09-11T17:00:00Z")
    validate_success(confirm(resv2["id"]), 200)
    validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv2["id"], mp2["id"]), CLERK), 201)
    validate_success(api_client.pickup_reservation(resv2["id"], CLERK), 200)
    return_reservation(resv2["id"], "2026-09-11T12:00:00Z", "DAMAGED")

    unit_after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert unit_after["damage_strike_count"] == 2
    assert unit_after["status"] == "RETIRED", "two strikes -> auto-retire"
    catalog_after = validate_success(api_client.get_catalog(catalog["id"], CLERK), 200)
    assert catalog_after["active_unit_count"] == 0, "recount after retire"


# ── #9 pickup_alteration_pending_beats_balance_outstanding ────────────

def test_pickup_blocked_by_balance_outstanding_alone(api):
    """PRD §3.6: "Finally, the customer must owe nothing: if the customer's `balance_owed_cents` is greater than 0, pickup is blocked with `ERR_BALANCE_OUTSTANDING` until the outstanding fees are cleared."

    Design: Difficulty/priority_pair_validation_conflict/pickup_alteration_pending_beats_balance_outstanding
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux I2"})
    create_unit(catalog["id"], "M")
    create_unit(catalog["id"], "M")
    customer = create_customer()
    mp = create_measurement_profile(customer["id"], chest_cm=100)

    # Prior reservation: complete an alteration (fee 4000) -> balance 4000.
    pre = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                             event_date_iso="2026-09-20T00:00:00Z",
                             pickup_window_start_iso="2026-09-15T09:00:00Z",
                             return_window_end_iso="2026-09-19T09:00:00Z")
    validate_success(confirm(pre["id"]), 200)
    alt = validate_success(api_client.create_alteration(
        create_alteration_payload(pre["id"], kind="HEM", fee_cents=4000), CLERK), 201)
    validate_success(api_client.complete_alteration(alt["id"], CLERK), 200)

    # Reservation under test: confirm + PASS fit-check, NO pending alteration.
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                              event_date_iso="2026-09-06T00:00:00Z",
                              pickup_window_start_iso="2026-09-01T09:00:00Z",
                              return_window_end_iso="2026-09-05T09:00:00Z")
    validate_success(confirm(resv["id"]), 200)
    validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv["id"], mp["id"]), CLERK), 201)

    res = api_client.pickup_reservation(resv["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_BALANCE_OUTSTANDING)


# ── #10 cancel_invalid_state_beats_party_locked ──────────────────────

def test_cancel_confirmed_member_in_locked_party_rejected(api):
    """PRD §3.9: "This freeze is enforced at cancellation time: a `CONFIRMED` member reservation whose party is `LOCKED` cannot be cancelled, and the attempt is rejected with `ERR_PARTY_LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/cancel_invalid_state_beats_party_locked
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux J3"})
    create_unit(catalog["id"], "M")
    coordinator = create_customer()
    coord_headers = make_customer_headers(coordinator["id"])
    party = validate_success(api_client.create_party_order(
        {"coordinator_customer_id": coordinator["id"],
         "event_date_iso": "2026-09-06T00:00:00Z", "required_member_count": 1},
        coord_headers), 201)
    resv = validate_success(api_client.create_reservation(
        create_reservation_payload(coordinator["id"], catalog["id"], requested_size_code="M",
                                   event_date_iso="2026-09-06T00:00:00Z",
                                   party_order_id=party["id"]),
        coord_headers), 201)
    validate_success(confirm(resv["id"], expected_party_order_version=party["version"]), 200)
    party_v1 = validate_success(api_client.get_party_order(party["id"], coord_headers), 200)["version"]
    validate_success(api_client.lock_party_order(
        party["id"], {"expected_party_order_version": party_v1}, coord_headers), 200)

    # Member is CONFIRMED (non-terminal) inside a LOCKED party -> ERR_PARTY_LOCKED.
    confirmed = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert confirmed["status"] == "CONFIRMED"
    res = api_client.cancel_reservation(resv["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_PARTY_LOCKED)


# ── #11 late_fee_exact_window_end_is_zero_days ───────────────────────

def test_return_one_second_late_is_one_day(api):
    """PRD §3.7: "The `late_days` is the number of whole calendar days the `returned_at_iso` falls strictly after the `return_window_end_iso`, taking the ceiling of the day difference, and is 0 when the return is on or before the window end".

    Design: Difficulty/boundary_precision_check/late_fee_exact_window_end_is_zero_days
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux K2"}, reservation_overrides=ONTIME_RESV)
    # One second past the window end -> ceil of a fractional day = 1 late day.
    settlement = return_reservation(resv["id"], "2026-09-03T17:00:01Z", "CLEAN")
    assert settlement["late_days"] == 1, "ceil of any positive fraction of a day is 1"
    assert settlement["late_fee_cents"] == 2000, "1 * 2000"


# ── #13 confirm_depends_on_party_posture_open ────────────────────────

def test_confirm_member_into_open_party_succeeds(api):
    """PRD §3.4: "If the reservation names a `party_order_id`, the linked party's `posture` must be `FORMING` or `READY` and the party's `event_date_iso` must equal the reservation's `event_date_iso".

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_party_posture_open
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux L3"})
    create_unit(catalog["id"], "M")
    coordinator = create_customer()
    coord_headers = make_customer_headers(coordinator["id"])
    party = create_party(coordinator["id"], required_member_count=2,
                         event_date_iso="2026-09-06T00:00:00Z")  # stays FORMING
    resv = validate_success(api_client.create_reservation(
        create_reservation_payload(coordinator["id"], catalog["id"], requested_size_code="M",
                                   event_date_iso="2026-09-06T00:00:00Z",
                                   party_order_id=party["id"]),
        coord_headers), 201)

    confirmed = validate_success(
        confirm(resv["id"], expected_party_order_version=party["version"]), 200)
    assert confirmed["status"] == "CONFIRMED", "confirm into a FORMING party is allowed"


# ── #14 confirm_depends_on_garment_unit_availability ─────────────────

def test_confirm_allocates_when_unit_available(api):
    """PRD §3.4: "An allocatable unit is one of the reservation's `catalog_id` whose `size_code` equals the `requested_size_code`, whose `status` is `AVAILABLE`, whose `condition_grade` is `GRADE_A` or `GRADE_B".
    PRD §3.4: "that unit transitions from `AVAILABLE` to `RESERVED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_garment_unit_availability
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux M3"})
    unit = create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")
    confirmed = validate_success(confirm(resv["id"]), 200)
    assert confirmed["garment_unit_id"] == unit["id"], "the AVAILABLE unit is allocated"
    after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert after["status"] == "RESERVED"


# ── #15 garment_unit_cleaning_buffer_overlap_blocks_confirm ──────────

def test_confirm_succeeds_after_cleaning_buffer_elapses(api):
    """PRD §3.10: "any unit `IN_CLEANING` whose `available_from_iso` the clock has now reached or passed is returned to `AVAILABLE`."
    PRD §3.4: "An allocatable unit is one of the reservation's `catalog_id` whose `size_code` equals the `requested_size_code`, whose `status` is `AVAILABLE`, whose `condition_grade` is `GRADE_A` or `GRADE_B` (a `GRADE_C` unit is never allocated), and whose `available_from_iso` is either null or on or before the `pickup_window_start_iso`."

    Design: Difficulty/resource_temporal_overlap/garment_unit_cleaning_buffer_overlap_blocks_confirm
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux N3"})
    unit = create_unit(catalog["id"], "M")
    cust1 = create_customer()
    cust2 = create_customer()
    mp1 = create_measurement_profile(cust1["id"], chest_cm=100)

    resv1 = create_reservation(cust1["id"], catalog["id"], requested_size_code="M", **ONTIME_RESV)
    validate_success(confirm(resv1["id"]), 200)
    validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv1["id"], mp1["id"]), CLERK), 201)
    validate_success(api_client.pickup_reservation(resv1["id"], CLERK), 200)
    return_reservation(resv1["id"], "2026-09-03T12:00:00Z", "CLEAN")  # available_from 09-05T12:00

    # Advance past the buffer so the sweep returns the unit to AVAILABLE.
    advance_clock("2026-09-05T13:00:00Z")
    cleared = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert cleared["status"] == "AVAILABLE"

    # Second reservation whose pickup window starts after available_from -> allocatable.
    resv2 = create_reservation(cust2["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-12T00:00:00Z",
                               pickup_window_start_iso="2026-09-06T09:00:00Z",
                               return_window_end_iso="2026-09-11T09:00:00Z")
    confirmed2 = validate_success(confirm(resv2["id"]), 200)
    assert confirmed2["status"] == "CONFIRMED", "unit free after the buffer -> confirm succeeds"


# ── #16 customer_rental_window_overlap_half_open_blocks_confirm ──────

def test_touching_windows_half_open_do_not_conflict(api):
    """PRD §3.4: "the rental window is the half-open interval running from `pickup_window_start_iso` up to but not including `return_window_end_iso`, compared with no added buffer, and any overlap is rejected with `ERR_CUSTOMER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/customer_rental_window_overlap_half_open_blocks_confirm
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux O3"})
    create_unit(catalog["id"], "M")
    create_unit(catalog["id"], "M")
    customer = create_customer()

    # resv1 window [09-01T09:00, 09-05T09:00); resv2 starts exactly at 09-05T09:00.
    resv1 = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-06T00:00:00Z",
                               pickup_window_start_iso="2026-09-01T09:00:00Z",
                               return_window_end_iso="2026-09-05T09:00:00Z")
    validate_success(confirm(resv1["id"]), 200)
    resv2 = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-10T00:00:00Z",
                               pickup_window_start_iso="2026-09-05T09:00:00Z",
                               return_window_end_iso="2026-09-09T09:00:00Z")
    # Half-open intervals touching at 09-05T09:00 do not overlap -> confirm succeeds.
    confirmed2 = validate_success(confirm(resv2["id"]), 200)
    assert confirmed2["status"] == "CONFIRMED"


# ── #17 deposit_conservation_hold_equals_release_plus_capture ────────

def test_clean_close_releases_full_deposit_captures_nothing(api):
    """PRD §2.9: "A clean close with no fees refunds the entire hold and captures nothing; a close with damage or late fees captures part or all of the deposit and posts a `FEE_CHARGE` only for any overflow beyond the deposit."

    Design: Difficulty/compensating_invariant/deposit_conservation_hold_equals_release_plus_capture
    """
    catalog, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux P2"}, reservation_overrides=ONTIME_RESV)
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "CLEAN")
    # Finalize so the DEPOSIT_RELEASE for the refund is posted.
    validate_success(api_client.finalize_settlement(settlement["id"], CLERK), 200)

    entries = ledger_for_reservation(resv["id"])
    hold, release, capture = assert_deposit_conserved(entries)
    assert hold == 20000
    assert release == 20000, "clean close refunds the entire hold"
    assert capture == 0, "clean close captures nothing"


# ── #18 unit_pool_conservation_confirm_then_cancel ───────────────────

def test_unit_pool_two_units_confirm_then_cancel(api):
    """PRD §3.4: "that unit transitions from `AVAILABLE` to `RESERVED`."
    PRD §3.9: "on success the allocated unit is released from `RESERVED` back to `AVAILABLE".

    Design: Difficulty/compensating_invariant/unit_pool_conservation_confirm_then_cancel
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux Q2"})
    create_unit(catalog["id"], "M")
    create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")

    assert available_unit_count(catalog["id"], "M") == 2
    validate_success(confirm(resv["id"]), 200)
    assert available_unit_count(catalog["id"], "M") == 1, "confirm reserves one of two"
    validate_success(api_client.cancel_reservation(resv["id"], CLERK), 200)
    assert available_unit_count(catalog["id"], "M") == 2, "cancel restores the pool"
