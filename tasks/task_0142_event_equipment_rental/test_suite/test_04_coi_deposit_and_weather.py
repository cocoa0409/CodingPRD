"""Insurance-gated confirmation, deposit settlement (release / partial forfeit),
weather-cancellation refunds, and the validation-priority conflicts that pin one
error over another when two would fire.

Difficulty: confirm requires VALID venue COI, fulfill requires a COMPLETED
drop-off run, weather-refund full-vs-deposit-only divergence, state-beats-COI and
state-beats-forfeit priority pairs. Corner: inclusive coverage boundary, partial
forfeit credits remainder, full release on returned order.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    make_customer_headers,
    TEST_USERS,
    ApiErrorId,
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


def _delivery(customer_id, venue_id, ws, we):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, fulfillment="DELIVERY", venue_id=venue_id,
                             event_start=ws, event_end=we), h))


def _will_call(customer_id, ws, we):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, event_start=ws, event_end=we), h))


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


def _returned_will_call(item, qty):
    """WILL_CALL order driven to RETURNED (DEPOSIT_HELD). Returns (cust, order_returned)."""
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], qty, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    returned = get_success_data(api_client.return_order(order["id"], AGENT))
    return cust, returned


# ─── Difficulty: cross-entity confirm gates ───

def test_confirm_blocked_when_coi_only_submitted(api):
    """PRD §3.4: "for every line whose item carries the `requires_coi` flag, the
    order's venue must show `VALID` coverage over the event window, and if any such
    line lacks valid coverage the confirmation is rejected with `ERR_COI_REQUIRED`."
    PRD §3.2: "Otherwise, if any certificate for the venue is still `SUBMITTED`,
    the coverage reads `PENDING`."

    A tent (requires_coi) on a venue whose only COI is SUBMITTED (coverage PENDING,
    not VALID) => confirm rejected with ERR_COI_REQUIRED.

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_venue_coi_valid
    """
    item = _item(category="TENT", total_units=5, daily_rate_cents=30000,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=True)
    cust = _customer()
    venue = _venue(cust["id"])
    _cert(venue["id"], cust["id"], "2026-08-09T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    order = _delivery(cust["id"], venue["id"], "2026-08-10T00:00:00.000Z", "2026-08-10T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    resp = _confirm_raw(order["id"], cust["id"])
    validate_error(resp, ApiErrorId.ERR_COI_REQUIRED.value, 422)


def test_fulfill_blocked_until_dropoff_run_completed(api):
    """PRD §3.5: "For a `DELIVERY` order, fulfillment additionally requires that
    the drop-off run for the order has reached `COMPLETED`; if the drop-off run is
    not yet complete, fulfillment is rejected with `ERR_DELIVERY_NOT_COMPLETED`."

    A DELIVERY order with a still-SCHEDULED DROP_OFF run => fulfill rejected with
    ERR_DELIVERY_NOT_COMPLETED.

    Design: Difficulty/cross_entity_state_dependency/order_fulfill_requires_dropoff_run_completed
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"], "2026-07-05T00:00:00.000Z", "2026-07-05T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    crew = _crew(name="Truck 14", turnaround_minutes=0)
    get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(order["id"], crew["id"], leg="DROP_OFF",
                                    window_start="2026-07-05T08:00:00.000Z",
                                    window_end="2026-07-05T09:00:00.000Z"), AGENT))
    resp = api_client.fulfill_order(order["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_COMPLETED.value, 409)


# ─── Difficulty: weather refund divergence ───

def test_weather_cancel_confirmed_refunds_rental_delivery_and_deposit(api):
    """PRD §3.9: "When the order is still `CONFIRMED` at weather-cancel time — the
    goods have not yet gone out — the rental refund is the full
    `rental_subtotal_cents` plus `cleaning_fee_total_cents`, and the delivery
    refund is the full `delivery_fee_cents`, since the delivery has not yet been
    incurred; the weather refund credited is the sum of these two parts."
    PRD §3.9: "In either case the held deposit is released in full. The computed
    weather refund is credited to the customer's `account_credit_cents`, and the
    deposit release is credited separately through a `RELEASE` ledger entry."

    1 tent, 2 days, daily 30000 disc 0.25: per_unit = 30000 + round_half_up(22500)
    = 52500; subtotal 52500; LOCAL delivery 5000; deposit 20000. Weather-cancel
    while CONFIRMED credits 52500 + 5000 (refund) + 20000 (deposit) = 77500.

    Design: Difficulty/dual_variant_calc/weather_refund_confirmed_full_vs_fulfilled_deposit_only
    """
    item = _item(category="TENT", total_units=5, daily_rate_cents=30000,
                 multi_day_discount_pct=0.25, deposit_per_unit_cents=20000, requires_coi=True)
    cust = _customer()
    venue = _venue(cust["id"])
    cert = _cert(venue["id"], cust["id"], "2026-08-10T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    _approve(venue["id"], cert["id"])
    get_success_data(api_client.create_weather_event(
        create_weather_event_payload(delivery_zone="LOCAL", severity="WARNING",
                                      effective_date="2026-08-10T00:00:00.000Z"), AGENT))
    order = _delivery(cust["id"], venue["id"], "2026-08-10T00:00:00.000Z", "2026-08-11T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    assert confirmed["rental_subtotal_cents"] == 52500, confirmed["rental_subtotal_cents"]
    assert confirmed["delivery_fee_cents"] == 5000, confirmed["delivery_fee_cents"]

    h = make_customer_headers(cust["id"])
    cancelled = validate_success(api_client.weather_cancel_order(order["id"], h), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "DEPOSIT_RELEASED"

    customer = validate_success(api_client.get_customer(cust["id"], AGENT), 200)
    assert customer["account_credit_cents"] == 77500, customer["account_credit_cents"]


# ─── Difficulty: validation-priority conflicts ───

def test_confirm_state_check_beats_coi_check(api):
    """PRD §2.10: "The ordering of validations across the whole system is fixed:
    authentication first, then authorization, then existence of every path- and
    body-referenced resource, then resource ownership for customer-initiated
    mutations, then state-validity of the targeted resource, and only then the
    operation's specific business rules."

    Order is CONFIRMED and its COI was revoked (insurance no longer VALID). A
    second confirm would fail both the state check (already CONFIRMED) and the COI
    check; state is higher priority, so ERR_INVALID_STATE wins.

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


def test_deposit_settle_not_returned_beats_forfeit_excess(api):
    """PRD §3.8: "Settlement is allowed only when the order's `settlement_status`
    is `DEPOSIT_HELD` (otherwise `ERR_INVALID_STATE`) and only when the order's
    `booking_status` is `RETURNED` (otherwise `ERR_NOT_RETURNED`), and the supplied
    `expected_order_version` must match the order's current `version` (otherwise
    `ERR_STALE_VERSION`)."

    A CONFIRMED-but-not-RETURNED order with a forfeit amount far over the held
    balance fails both the not-returned guard and the forfeit-excess guard; the
    not-returned check is evaluated first, so ERR_NOT_RETURNED wins.

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


# ─── Corner: COI inclusive boundary + settlement happy paths ───

def test_confirm_succeeds_with_inclusive_coverage_boundary(api):
    """PRD §3.2: "If at least one approved certificate's `coverage_start` is on or
    before the event start and whose `coverage_end` is on or after the event end —
    the coverage interval being inclusive at both ends, so a certificate whose
    `coverage_start` equals the event start still qualifies — the window's coverage
    is `VALID`."

    APPROVED COI covering exactly 2026-08-10..2026-08-12; order event exactly
    2026-08-10..2026-08-12 (coverage_start==event_start, coverage_end==event_end):
    coverage is VALID, confirm succeeds.

    Design: Corner/calculations/venue_coi_inclusive_coverage_boundary
    """
    item = _item(category="TENT", total_units=5, daily_rate_cents=1000,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=True)
    cust = _customer()
    venue = _venue(cust["id"])
    cert = _cert(venue["id"], cust["id"], "2026-08-10T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    _approve(venue["id"], cert["id"])
    order = _delivery(cust["id"], venue["id"], "2026-08-10T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    assert confirmed["booking_status"] == "CONFIRMED", confirmed["booking_status"]


def test_partial_forfeit_credits_remainder(api):
    """PRD §3.8: "If the forfeited amount is less than the held balance, the system
    additionally appends a deposit ledger entry of kind `RELEASE` for the remainder
    and credits the owning customer's `account_credit_cents` by that remainder."

    Held 2000, forfeit 500 => settlement DEPOSIT_FORFEITED, remainder 1500
    released and credited to the customer.

    Design: Corner/endpoints/deposit_partial_forfeit_credits_remainder
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=400, requires_coi=False)
    cust, returned = _returned_will_call(item, 5)
    settled = validate_success(api_client.settle_deposit(
        returned["id"],
        {"disposition": "FORFEIT", "forfeit_amount_cents": 500,
         "expected_order_version": returned["version"], "reason": "torn fabric"},
        ADJUSTER), 200)
    assert settled["settlement_status"] == "DEPOSIT_FORFEITED", settled["settlement_status"]
    customer = validate_success(api_client.get_customer(cust["id"], AGENT), 200)
    assert customer["account_credit_cents"] == 1500, customer["account_credit_cents"]


def test_full_release_on_returned_order_credits_customer(api):
    """PRD §3.8: "A `RELEASE` disposition advances `settlement_status` `DEPOSIT_HELD
    → DEPOSIT_RELEASED`, appends a deposit ledger entry of kind `RELEASE` for the
    current held balance, and credits the owning customer's `account_credit_cents`
    by the released amount."

    Held 1000, RELEASE on a RETURNED order => DEPOSIT_RELEASED, customer credited
    the full 1000.

    Design: Corner/endpoints/deposit_full_release_on_returned_order
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=200, requires_coi=False)
    cust, returned = _returned_will_call(item, 5)
    settled = validate_success(api_client.settle_deposit(
        returned["id"],
        {"disposition": "RELEASE", "expected_order_version": returned["version"]},
        ADJUSTER), 200)
    assert settled["settlement_status"] == "DEPOSIT_RELEASED", settled["settlement_status"]
    customer = validate_success(api_client.get_customer(cust["id"], AGENT), 200)
    assert customer["account_credit_cents"] == 1000, customer["account_credit_cents"]
