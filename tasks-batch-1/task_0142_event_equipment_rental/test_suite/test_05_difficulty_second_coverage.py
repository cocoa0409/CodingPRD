"""Second-coverage tests for each difficulty instance.

Every difficulty instance is exercised by at least two tests. This file holds
the complementary scenario for each (the accepting side of a boundary, the
positive branch of a gate, a deeper loop iteration, or a distinct observable of
the same cascade), each still derived solely from verbatim PRD prose.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    api_client,
    make_customer_headers,
    TEST_USERS,
    ApiErrorId,
    compute_held_balance,
    create_catalog_item_payload,
    create_customer_payload,
    create_venue_payload,
    create_certificate_payload,
    create_order_payload,
    add_line_payload,
    create_crew_payload,
    create_delivery_run_payload,
    create_weather_event_payload,
    get_success_data,
)

AGENT = TEST_USERS["rental_agent_headers"]
ADJUSTER = TEST_USERS["deposit_adjuster_headers"]


def _item(**ov):
    return get_success_data(api_client.create_catalog_item(create_catalog_item_payload(**ov), AGENT))


def _customer():
    return get_success_data(api_client.create_customer(create_customer_payload(), AGENT))


def _venue(customer_id, zone="LOCAL"):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_venue(
        create_venue_payload(customer_id, delivery_zone=zone), h))


def _cert(venue_id, customer_id, cs, ce):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_certificate(
        venue_id, create_certificate_payload(coverage_start=cs, coverage_end=ce), h))


def _approve(venue_id, cert_id):
    return get_success_data(api_client.approve_certificate(venue_id, cert_id, AGENT))


def _will_call(customer_id, ws, we):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, event_start=ws, event_end=we), h))


def _delivery(customer_id, venue_id, ws, we):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, fulfillment="DELIVERY", venue_id=venue_id,
                             event_start=ws, event_end=we), h))


def _add_line(order_id, item_id, qty, customer_id):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.add_line(order_id, add_line_payload(item_id, qty), h))


def _confirm_raw(order_id, customer_id):
    h = make_customer_headers(customer_id)
    cur = get_success_data(api_client.get_order(order_id, h))
    return api_client.confirm_order(order_id, {"expected_order_version": cur["version"]}, h)


def _confirm_ok(order_id, customer_id):
    return validate_success(_confirm_raw(order_id, customer_id), 200)


def _crew(**ov):
    return get_success_data(api_client.create_crew(create_crew_payload(**ov), AGENT))


def _run(order_id, crew_id, leg, ws, we):
    return get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(order_id, crew_id, leg=leg, window_start=ws, window_end=we), AGENT))


# 1. inventory capacity boundary — accepting side (60 + 40 == 100)
def test_inventory_capacity_exact_total_units_confirms(api):
    """PRD §3.4: "the units already reserved on overlapping windows plus this
    line's `quantity` must not exceed the item's `total_units`, and a shortfall is
    rejected with `ERR_INVENTORY_UNAVAILABLE`."

    Boundary X (== total_units): 60 reserved + a 40-unit overlapping line equals
    exactly total_units 100, which does not exceed it, so the confirm succeeds.

    Design: Difficulty/boundary_precision_check/inventory_capacity_exact_boundary_on_confirm
    """
    item = _item(category="CHAIR", total_units=100, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    oa = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-03T00:00:00.000Z")
    _add_line(oa["id"], item["id"], 60, cust["id"])
    _confirm_ok(oa["id"], cust["id"])
    ob = _will_call(cust["id"], "2026-06-03T00:00:00.000Z", "2026-06-05T00:00:00.000Z")
    _add_line(ob["id"], item["id"], 40, cust["id"])
    confirmed = _confirm_ok(ob["id"], cust["id"])
    assert confirmed["booking_status"] == "CONFIRMED", confirmed["booking_status"]


# 2. delivery fee multi-input — REMOTE zone, no surcharge, no waiver
def test_delivery_fee_remote_zone_base_only(api):
    """PRD §3.3: "For a `DELIVERY` order the fee starts from a zone base
    determined by the venue's `delivery_zone`: a local zone contributes a base of
    5000 cents, an extended zone 9000 cents, and a remote zone 15000 cents."

    REMOTE base 15000, 1 unit (< 100 so no surcharge), subtotal 200 (< 200000 so
    no waiver) => delivery_fee 15000.

    Design: Difficulty/combinatorial_formula/delivery_fee_multi_input_nonlinear_mode_a
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"], "REMOTE")
    order = _delivery(cust["id"], venue["id"], "2026-06-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    assert confirmed["delivery_fee_cents"] == 15000, confirmed["delivery_fee_cents"]


# 3. round-then-multiply — a second divergent rounding case
def test_line_rental_per_unit_rounding_independent_of_quantity(api):
    """PRD §3.3: "Each additional day is billed at a discounted day rate, which is
    the item's `daily_rate_cents` multiplied by one minus the item's
    `multi_day_discount_pct`, rounded half up to a whole number of cents."
    PRD §3.3: "This per-unit price is computed and rounded to whole cents
    **first**, and only then multiplied by the line's `quantity` to give that
    line's `line_rental_cents`."

    daily=100, disc=0.333, 2 days: disc_day=round_half_up(100*0.667)=
    round_half_up(66.7)=67; per_unit=100+67=167; qty 3 => 167*3=501 (multiply-then-
    round would give 500).

    Design: Difficulty/combinatorial_formula/line_rental_round_then_multiply_order_mode_b
    """
    item = _item(category="TABLE", total_units=50, daily_rate_cents=100,
                 multi_day_discount_pct=0.333, deposit_per_unit_cents=0,
                 requires_cleaning=False, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-09-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z")
    _add_line(order["id"], item["id"], 3, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    assert confirmed["rental_subtotal_cents"] == 501, confirmed["rental_subtotal_cents"]


# 4. deposit conservation via settle RELEASE on returned order (held -> 0)
def test_deposit_settle_release_drives_held_balance_to_zero(api):
    """PRD §3.7: "The current held-deposit balance of an order is derived by
    replaying its ledger entries in `created_at` ascending order, starting from
    zero, adding each `HOLD` entry's `amount_cents` and subtracting each `RELEASE`
    and each `FORFEIT` entry's `amount_cents`."
    PRD §3.8: "A `RELEASE` disposition advances `settlement_status` `DEPOSIT_HELD →
    DEPOSIT_RELEASED`, appends a deposit ledger entry of kind `RELEASE` for the
    current held balance, and credits the owning customer's `account_credit_cents`
    by the released amount."

    Confirm holds 1000; a RELEASE settle on the returned order appends a RELEASE
    of 1000; the ledger then replays to held balance 0.

    Design: Difficulty/compensating_invariant/deposit_ledger_hold_then_release_conserves_balance
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=200, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    returned = get_success_data(api_client.return_order(order["id"], AGENT))
    validate_success(api_client.settle_deposit(
        returned["id"],
        {"disposition": "RELEASE", "expected_order_version": returned["version"]},
        ADJUSTER), 200)
    entries = validate_success(api_client.get_deposit_ledger(order["id"], AGENT), 200)
    assert compute_held_balance(entries) == 0, entries


# 5. inventory conservation — reserve leg observable (held window shows 0 available)
def test_inventory_reserve_leg_zeroes_availability_over_window(api):
    """PRD §2.7: "Availability over a queried window is the item's `total_units`
    minus the number of units already reserved on lines whose reserved window
    overlaps the queried window."
    PRD §3.4: "Every line's `status` moves `PENDING → RESERVED`, and the order's
    `event_start` and `event_end` are copied onto each line as its
    `reserved_window_start` and `reserved_window_end`, establishing the inventory
    hold over that window."

    Reserving all 40 units over Jun1-2 drops available_units over that window to 0
    (the reserve leg of the reserve/release conservation invariant).

    Design: Difficulty/compensating_invariant/inventory_units_reserve_then_release_conserves_availability
    """
    item = _item(category="CHAIR", total_units=40, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z")
    _add_line(order["id"], item["id"], 40, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    avail = validate_success(api_client.get_item_availability(
        item["id"], "2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z", AGENT), 200)
    assert avail["reserved_units"] == 40, avail["reserved_units"]
    assert avail["available_units"] == 0, avail["available_units"]


# 6. COI gate positive branch — APPROVED coverage permits confirm
def test_confirm_succeeds_when_coi_approved_and_valid(api):
    """PRD §3.4: "for every line whose item carries the `requires_coi` flag, the
    order's venue must show `VALID` coverage over the event window, and if any such
    line lacks valid coverage the confirmation is rejected with `ERR_COI_REQUIRED`."
    PRD §3.2: "Approving a submitted certificate advances its `status` `SUBMITTED →
    APPROVED` and recomputes the venue's `coi_status`; approval is permitted only
    when the certificate is `SUBMITTED` (otherwise `ERR_INVALID_STATE`) and
    additionally requires that the `coverage_end` be on or after the
    `coverage_start`, failing which the approval is rejected with
    `ERR_INVALID_COVERAGE_WINDOW`."

    A tent line on a venue whose COI is APPROVED and covers the window => coverage
    VALID, confirm succeeds.

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_venue_coi_valid
    """
    item = _item(category="TENT", total_units=5, daily_rate_cents=30000,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=True)
    cust = _customer()
    venue = _venue(cust["id"])
    cert = _cert(venue["id"], cust["id"], "2026-08-09T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    _approve(venue["id"], cert["id"])
    order = _delivery(cust["id"], venue["id"], "2026-08-10T00:00:00.000Z", "2026-08-10T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    assert confirmed["booking_status"] == "CONFIRMED", confirmed["booking_status"]


# 7. fulfill gate positive branch — completed drop-off run permits fulfill
def test_fulfill_succeeds_after_dropoff_run_completed(api):
    """PRD §3.6: "Reporting `SUCCESS` advances a scheduled run `SCHEDULED →
    COMPLETED`; a successful drop-off run is what unblocks the order's
    fulfillment, and a successful pickup run is what unblocks the order's return."
    PRD §3.5: "For a `DELIVERY` order, fulfillment additionally requires that the
    drop-off run for the order has reached `COMPLETED`; if the drop-off run is not
    yet complete, fulfillment is rejected with `ERR_DELIVERY_NOT_COMPLETED`."

    After the DROP_OFF run is COMPLETED, fulfilling the DELIVERY order succeeds
    and booking_status advances to FULFILLED.

    Design: Difficulty/cross_entity_state_dependency/order_fulfill_requires_dropoff_run_completed
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"], "2026-07-05T00:00:00.000Z", "2026-07-05T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    crew = _crew(name="Truck 14b", turnaround_minutes=0)
    run = _run(order["id"], crew["id"], "DROP_OFF",
               "2026-07-05T08:00:00.000Z", "2026-07-05T09:00:00.000Z")
    get_success_data(api_client.attempt_delivery_run(run["id"], {"outcome": "SUCCESS"}, AGENT))
    fulfilled = validate_success(api_client.fulfill_order(order["id"], AGENT), 200)
    assert fulfilled["booking_status"] == "FULFILLED", fulfilled["booking_status"]


# 8. full-term pricing — single-day order bills only the full first day
def test_single_day_rental_bills_full_day_only(api):
    """PRD §3.3: "The first day is billed at the item's full `daily_rate_cents`."
    PRD §3.3: "The per-unit price is then the full first-day rate plus the
    discounted day rate applied to each of the remaining days — that is, the
    discounted day rate multiplied by one fewer than the number of rental days,
    added to the full first-day rate."

    A 1-day rental has zero additional days, so per_unit == full daily_rate; CHAIR
    daily 200, 1 day, 100 units => rental_subtotal 200*100 = 20000 (the discount
    never applies to the single billed day).

    Design: Difficulty/dual_variant_calc/line_rental_full_term_vs_weather_prorated
    """
    item = _item(category="CHAIR", total_units=100, daily_rate_cents=200,
                 multi_day_discount_pct=0.20, deposit_per_unit_cents=50,
                 requires_cleaning=False, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 100, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    assert confirmed["rental_subtotal_cents"] == 20000, confirmed["rental_subtotal_cents"]


# 9. weather refund — FULFILLED variant refunds nothing on rental/delivery
def test_weather_cancel_fulfilled_refunds_deposit_only(api):
    """PRD §3.9: "When the order is already `FULFILLED` at weather-cancel time —
    the goods are out — the rental and delivery refunds are both 0, because the
    rental has effectively been consumed once the goods are in the field. In either
    case the held deposit is released in full."

    A WILL_CALL order fulfilled then weather-cancelled credits only the released
    deposit (1000), with no rental/delivery refund.

    Design: Difficulty/dual_variant_calc/weather_refund_confirmed_full_vs_fulfilled_deposit_only
    """
    item = _item(category="TENT", total_units=5, daily_rate_cents=30000,
                 multi_day_discount_pct=0, deposit_per_unit_cents=200, requires_coi=False)
    cust = _customer()
    get_success_data(api_client.create_weather_event(
        create_weather_event_payload(delivery_zone="LOCAL", severity="WARNING",
                                      effective_date="2026-08-10T00:00:00.000Z"), AGENT))
    order = _will_call(cust["id"], "2026-08-10T00:00:00.000Z", "2026-08-10T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    h = make_customer_headers(cust["id"])
    cancelled = validate_success(api_client.weather_cancel_order(order["id"], h), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    customer = validate_success(api_client.get_customer(cust["id"], AGENT), 200)
    # deposit 5 * 200 = 1000 released; no rental/delivery refund on a FULFILLED order.
    assert customer["account_credit_cents"] == 1000, customer["account_credit_cents"]


# 10. delivery-run cycle — second loop iteration reaches attempt_count 2
def test_delivery_run_second_failure_increments_attempt_count(api):
    """PRD §3.6: "Reporting `FAILED` advances a scheduled run `SCHEDULED →
    ATTEMPTED` and increments its `attempt_count` by one."
    PRD §3.6: "An attempted run can be rescheduled back to a fresh window,
    advancing `status` `ATTEMPTED → SCHEDULED` and updating its `window_start` and
    `window_end`."

    Fail (count 1) -> reschedule -> fail again (count 2): two laps of the cycle,
    attempt_count == 2 and status ATTEMPTED.

    Design: Difficulty/non_linear_state_machine/delivery_run_cyclic_scheduled_attempted_loop
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"], "2026-07-01T00:00:00.000Z", "2026-07-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    crew = _crew(name="Truck 1b", turnaround_minutes=0)
    run = _run(order["id"], crew["id"], "DROP_OFF",
               "2026-06-30T09:00:00.000Z", "2026-06-30T10:00:00.000Z")
    get_success_data(api_client.attempt_delivery_run(run["id"], {"outcome": "FAILED"}, AGENT))
    get_success_data(api_client.reschedule_delivery_run(
        run["id"], {"window_start": "2026-06-30T13:00:00.000Z",
                    "window_end": "2026-06-30T14:00:00.000Z"}, AGENT))
    second = validate_success(api_client.attempt_delivery_run(run["id"], {"outcome": "FAILED"}, AGENT), 200)
    assert second["status"] == "ATTEMPTED", second["status"]
    assert second["attempt_count"] == 2, second["attempt_count"]


# 11. parallel dimensions — settle moves settlement while booking stays RETURNED
def test_settlement_advances_independently_of_returned_booking(api):
    """PRD §2.6: "A `RentalOrder` is governed by two parallel, independent status
    fields that evolve on different triggers and must be tracked separately."
    PRD §3.8: "A `RELEASE` disposition advances `settlement_status` `DEPOSIT_HELD →
    DEPOSIT_RELEASED`, appends a deposit ledger entry of kind `RELEASE` for the
    current held balance, and credits the owning customer's `account_credit_cents`
    by the released amount."

    On a RETURNED order, settling the deposit moves settlement_status to
    DEPOSIT_RELEASED while booking_status remains RETURNED — the two axes move
    independently.

    Design: Difficulty/non_linear_state_machine/rental_order_parallel_booking_and_settlement_dimensions
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=100, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-10T00:00:00.000Z", "2026-06-10T00:00:00.000Z")
    _add_line(order["id"], item["id"], 10, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    returned = get_success_data(api_client.return_order(order["id"], AGENT))
    settled = validate_success(api_client.settle_deposit(
        returned["id"],
        {"disposition": "RELEASE", "expected_order_version": returned["version"]},
        ADJUSTER), 200)
    assert settled["booking_status"] == "RETURNED", settled["booking_status"]
    assert settled["settlement_status"] == "DEPOSIT_RELEASED", settled["settlement_status"]


# 12. state-beats-COI — the rejected confirm leaves booking_status unchanged
def test_state_beats_coi_leaves_booking_unchanged(api):
    """PRD §2.10: "Earlier checks always mask later ones, so a missing header
    surfaces as `ERR_UNAUTHENTICATED` even if the targeted resource also happens
    not to exist."

    Re-confirming an already-CONFIRMED order whose COI was revoked is rejected with
    the higher-priority ERR_INVALID_STATE; the order stays CONFIRMED (the
    business-rule COI path never runs and nothing changes).

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_coi_safety
    """
    item = _item(category="TENT", total_units=5, daily_rate_cents=30000,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=True)
    cust = _customer()
    venue = _venue(cust["id"])
    cert = _cert(venue["id"], cust["id"], "2026-08-09T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    _approve(venue["id"], cert["id"])
    order = _delivery(cust["id"], venue["id"], "2026-08-10T00:00:00.000Z", "2026-08-10T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    get_success_data(api_client.revoke_certificate(venue["id"], cert["id"], AGENT))
    h = make_customer_headers(cust["id"])
    resp = api_client.confirm_order(
        order["id"], {"expected_order_version": confirmed["version"]}, h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api_client.get_order(order["id"], h), 200)
    assert after["booking_status"] == "CONFIRMED", after["booking_status"]


# 13. state-beats-forfeit — the rejected settle leaves settlement_status unchanged
def test_not_returned_beats_forfeit_leaves_settlement_held(api):
    """PRD §3.8: "Settlement is allowed only when the order's `settlement_status`
    is `DEPOSIT_HELD` (otherwise `ERR_INVALID_STATE`) and only when the order's
    `booking_status` is `RETURNED` (otherwise `ERR_NOT_RETURNED`), and the supplied
    `expected_order_version` must match the order's current `version` (otherwise
    `ERR_STALE_VERSION`)."

    A FORFEIT-over-held attempt on a CONFIRMED (not RETURNED) order is rejected
    with the higher-priority ERR_NOT_RETURNED, and settlement_status stays
    DEPOSIT_HELD (the forfeit never executes).

    Design: Difficulty/priority_pair_validation_conflict/deposit_settle_state_beats_forfeit_fiscal
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=100, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-20T00:00:00.000Z", "2026-06-20T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    resp = api_client.settle_deposit(
        order["id"],
        {"disposition": "FORFEIT", "forfeit_amount_cents": 999999,
         "expected_order_version": confirmed["version"], "reason": "over"},
        ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_NOT_RETURNED.value, 409)
    after = validate_success(api_client.get_order(order["id"], AGENT), 200)
    assert after["settlement_status"] == "DEPOSIT_HELD", after["settlement_status"]


# 14. crew buffer — windows exactly one buffer apart do NOT conflict
def test_crew_runs_exactly_one_buffer_apart_allowed(api):
    """PRD §3.6: "two windows conflict if they overlap or sit closer together than
    the buffer allows — returning `ERR_CREW_WINDOW_CONFLICT`."

    turnaround=60; first run closes 10:00, second opens 11:00 — exactly 60 minutes
    later, not closer than the buffer, so the second run schedules successfully.

    Design: Difficulty/resource_temporal_overlap/crew_half_open_plus_turnaround_buffer_overlap
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"])
    oa = _delivery(cust["id"], venue["id"], "2026-07-10T00:00:00.000Z", "2026-07-10T00:00:00.000Z")
    _add_line(oa["id"], item["id"], 1, cust["id"])
    _confirm_ok(oa["id"], cust["id"])
    ob = _delivery(cust["id"], venue["id"], "2026-07-10T00:00:00.000Z", "2026-07-10T00:00:00.000Z")
    _add_line(ob["id"], item["id"], 1, cust["id"])
    _confirm_ok(ob["id"], cust["id"])
    crew = _crew(name="Truck 16b", turnaround_minutes=60)
    _run(oa["id"], crew["id"], "DROP_OFF", "2026-07-10T09:00:00.000Z", "2026-07-10T10:00:00.000Z")
    resp = api_client.create_delivery_run(
        create_delivery_run_payload(ob["id"], crew["id"], leg="DROP_OFF",
                                    window_start="2026-07-10T11:00:00.000Z",
                                    window_end="2026-07-10T12:00:00.000Z"), AGENT)
    run2 = validate_success(resp, 201)
    assert run2["status"] == "SCHEDULED", run2["status"]


# 15. inventory overlap — non-overlapping windows do NOT aggregate
def test_inventory_non_overlapping_windows_do_not_aggregate(api):
    """PRD §2.7: "Two day-spans overlap when each begins on or before the other
    ends; a reservation that ends on the very day another begins is treated as
    overlapping, since both occupy that shared day."

    total_units=100; OD1 reserves 80 over Jun1-2; OD2 requests 30 over Jun4-5
    (no shared day with Jun1-2) — the two do not aggregate, so OD2 confirms.

    Design: Difficulty/resource_temporal_overlap/inventory_closed_interval_aggregate_capacity_overlap
    """
    item = _item(category="CHAIR", total_units=100, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    od1 = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z")
    _add_line(od1["id"], item["id"], 80, cust["id"])
    _confirm_ok(od1["id"], cust["id"])
    od2 = _will_call(cust["id"], "2026-06-04T00:00:00.000Z", "2026-06-05T00:00:00.000Z")
    _add_line(od2["id"], item["id"], 30, cust["id"])
    confirmed = _confirm_ok(od2["id"], cust["id"])
    assert confirmed["booking_status"] == "CONFIRMED", confirmed["booking_status"]


# 16. cancel cascade depth-3 — the RELEASE ledger entry records the full held amount
def test_cancel_appends_release_ledger_for_held_balance(api):
    """PRD §3.5: "the system appends a deposit ledger entry of kind `RELEASE` for
    the current held balance, and the owning customer's `account_credit_cents` is
    recomputed to reflect that release."

    Cancelling a DEPOSIT_HELD order (held 1500) appends exactly one RELEASE ledger
    entry of 1500 — the hop-2 observable of the cancel cascade.

    Design: Difficulty/transitive_cascade/order_cancel_releases_deposit_credits_customer_depth3
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=300, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-15T00:00:00.000Z", "2026-06-15T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    h = make_customer_headers(cust["id"])
    validate_success(api_client.cancel_order(
        order["id"], {"expected_order_version": confirmed["version"]}, h), 200)
    entries = validate_success(api_client.get_deposit_ledger(order["id"], AGENT), 200)
    releases = [e for e in entries if e["kind"] == "RELEASE"]
    assert len(releases) == 1, f"expected one RELEASE entry, got {len(releases)}"
    assert releases[0]["amount_cents"] == 1500, releases[0]["amount_cents"]


# 17. confirm cascade depth-2 — hop-1 observable: lines move PENDING -> RESERVED
def test_confirm_reserves_lines_as_first_hop(api):
    """PRD §3.4: "When all gates pass, confirmation advances `booking_status`
    `DRAFT → CONFIRMED` and triggers a cascade. Every line's `status` moves
    `PENDING → RESERVED`, and the order's `event_start` and `event_end` are copied
    onto each line as its `reserved_window_start` and `reserved_window_end`,
    establishing the inventory hold over that window."

    Confirm flips the line status PENDING -> RESERVED (hop 1 of the
    confirm -> hold -> ledger chain).

    Design: Difficulty/transitive_cascade/order_confirm_holds_deposit_appends_ledger_depth2
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=300, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-16T00:00:00.000Z", "2026-06-16T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    assert confirmed["booking_status"] == "CONFIRMED"
    h = make_customer_headers(cust["id"])
    lines, _ = validate_paginated(api_client.list_lines(order["id"], h))
    assert all(ln["status"] == "RESERVED" for ln in lines), [ln["status"] for ln in lines]
