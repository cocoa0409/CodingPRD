"""Spot-booking precondition gates: posture, order state, daypart hours,
flight bounds, daypart quotas, rate-card existence, rate floor, trade credit
and agreement status (PRD §2.8, §3.3, §3.6)."""
from test_helpers import (
    TD,
    ApiErrorId,
    append_adjustment,
    book_spot,
    book_spot_ok,
    create_active_order,
    create_active_clock,
    create_locked_log,
    create_order,
    create_station,
    create_trade_agreement,
    get_success_data,
    import_as_run_ok,
    make_billing_admin_headers,
    make_headers,
    make_sales_rep_headers,
    setup_bookable_scenario,
    setup_bookable_station,
    validate_error,
    validate_success,
)

TD_HEADERS = TD


def test_spot_booking_gated_by_daily_log_posture_locked_ok(api):
    """PRD §3.6: "the target log's posture must be `DRAFT` or `LOCKED`
    (`ERR_LOG_POSTURE_BLOCKED` otherwise)".

    Design: Difficulty/cross_entity_state_dependency/spot_booking_gated_by_daily_log_posture
    """
    env = setup_bookable_scenario(units=2)
    spot = book_spot_ok(env["order"]["id"], env["log"]["id"])
    assert spot["status"] == "SCHEDULED", "booking against a LOCKED log succeeds"


def test_spot_booking_gated_by_daily_log_posture_as_run_blocked(api):
    """PRD §3.6: "the target log's posture must be `DRAFT` or `LOCKED`
    (`ERR_LOG_POSTURE_BLOCKED` otherwise)" — once the log advances to AS_RUN
    the same booking request is rejected.

    Design: Difficulty/cross_entity_state_dependency/spot_booking_gated_by_daily_log_posture
    """
    env = setup_bookable_scenario(units=2)
    order_id = env["order"]["id"]
    log_id = env["log"]["id"]
    s1 = book_spot_ok(order_id, log_id)
    import_as_run_ok(log_id, aired_spot_ids=[s1["id"]])

    order_before = get_success_data(api.get_order(order_id, TD_HEADERS))
    resp = book_spot(order_id, log_id)
    validate_error(resp, ApiErrorId.ERR_LOG_POSTURE_BLOCKED)

    order_after = get_success_data(api.get_order(order_id, TD_HEADERS))
    assert order_after["version"] == order_before["version"], (
        "Order.version unchanged by the rejected booking"
    )


def test_order_not_active_blocks_booking(api):
    """PRD §3.6: "The order must be `ACTIVE` (`ERR_ORDER_NOT_ACTIVE`
    otherwise), the target log's posture must be `DRAFT` or `LOCKED`
    (`ERR_LOG_POSTURE_BLOCKED` otherwise)".

    Design: Corner/validations/order_not_active_blocks_booking
    """
    env = setup_bookable_station()
    order = create_order(env["station"]["id"], rep_user_id="rep-1")  # stays DRAFT
    log = create_locked_log(env["station"]["id"])

    resp = book_spot(
        order["id"], log["id"], expected_order_version=order["version"]
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACTIVE)


def test_spot_hour_must_belong_to_daypart(api):
    """PRD §3.6: "the chosen `hour` must belong to the chosen `daypart`
    (`ERR_DAYPART_HOUR_MISMATCH` otherwise)" and "The daypart hour sets are
    fixed: `MORNING_DRIVE` covers hours 5 through 8, `MIDDAY` covers 9 through
    13".

    Design: Corner/validations/spot_hour_must_belong_to_daypart
    """
    env = setup_bookable_station(weekday="MON", daypart="MIDDAY", hour=10)
    order = create_active_order(
        env["station"]["id"], daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 1}]
    )
    log = create_locked_log(env["station"]["id"])

    resp = book_spot(order["id"], log["id"], daypart="MORNING_DRIVE", hour=10)
    validate_error(resp, ApiErrorId.ERR_DAYPART_HOUR_MISMATCH)


def test_spot_outside_flight_rejected(api):
    """PRD §3.6: "the spot's `air_date` (copied from the log's `log_date` at
    creation) must lie within the order's flight (`ERR_SPOT_OUTSIDE_FLIGHT`
    otherwise)".

    Design: Corner/validations/spot_outside_flight_rejected
    """
    env = setup_bookable_station()
    order = create_active_order(
        env["station"]["id"],
        flight_start="2026-05-01",
        flight_end="2026-05-31",
        daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 1}],
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-06-01")  # a MON

    resp = book_spot(order["id"], log["id"])
    validate_error(resp, ApiErrorId.ERR_SPOT_OUTSIDE_FLIGHT)


def test_daypart_units_exhausted_quota(api):
    """PRD §3.6: "the per-(order, daypart) scheduled count must remain below
    the `units` declared in `daypart_targets` (`ERR_DAYPART_UNITS_EXHAUSTED`
    otherwise)".

    Design: Corner/validations/daypart_units_exhausted_quota
    """
    env = setup_bookable_scenario(units=1)  # quota of exactly 1
    book_spot_ok(env["order"]["id"], env["log"]["id"])

    resp = book_spot(env["order"]["id"], env["log"]["id"])
    validate_error(resp, ApiErrorId.ERR_DAYPART_UNITS_EXHAUSTED)


def test_no_rate_card_rejected(api):
    """PRD §3.6: "the system locates an `ACTIVE` RateCardEntry matching the
    station, daypart, weekday of `air_date`, and effective window — absence
    yields `ERR_NO_RATE_CARD`".

    Design: Corner/validations/no_rate_card_rejected
    """
    station = create_station(default_share_fallback=2.5)
    create_active_clock(station["id"], applies_weekdays=["MON"])
    order = create_active_order(
        station["id"], daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 1}]
    )
    log = create_locked_log(station["id"])

    resp = book_spot(order["id"], log["id"])
    validate_error(resp, ApiErrorId.ERR_NO_RATE_CARD)


def test_rate_floor_override_rep_rejected_manager_allowed(api):
    """PRD §3.6: "A caller may pass `unit_rate_override_cents` to override the
    computed rate; if that override falls below `min_rate_cents`, the booking
    is rejected with `ERR_RATE_FLOOR_VIOLATION` unless the caller is a
    `SalesManager` passing `allow_below_floor` as true."

    Design: Corner/validations/rate_floor_override_rep_rejected_manager_allowed
    """
    env = setup_bookable_scenario(units=1, base_rate_cents=10000, min_rate_cents=5000)
    order_id = env["order"]["id"]
    log_id = env["log"]["id"]

    version_before = get_success_data(
        api.get_order(order_id, make_sales_rep_headers("rep-1"))
    )["version"]

    resp = book_spot(
        order_id, log_id,
        headers=make_sales_rep_headers("rep-1"),
        unit_rate_override_cents=4000,
    )
    validate_error(resp, ApiErrorId.ERR_RATE_FLOOR_VIOLATION)

    version_after = get_success_data(
        api.get_order(order_id, make_sales_rep_headers("rep-1"))
    )["version"]
    assert version_after == version_before, "order version unchanged by the rejection"

    spot = book_spot_ok(
        order_id, log_id,
        headers=make_headers("SalesManager", "mgr-1"),
        unit_rate_override_cents=4000,
        allow_below_floor=True,
    )
    assert spot["unit_rate_cents"] == 4000, "manager's below-floor override stands"


def test_trade_agreement_inactive_blocks_booking(api):
    """PRD §3.3: "A `BillingAdmin` may suspend an `ACTIVE` agreement (moving it
    to `SUSPENDED`), which blocks new trade submits, approvals, and bookings
    with `ERR_TRADE_AGREEMENT_INACTIVE`."

    Design: Corner/validations/trade_agreement_inactive_blocks_booking
    """
    env = setup_bookable_station(
        weekday="TUE", daypart="MIDDAY", hour=10, base_rate_cents=5000, min_rate_cents=1000
    )
    agreement = create_trade_agreement(env["station"]["id"], credit_limit_cents=100000)
    order = create_active_order(
        env["station"]["id"],
        order_kind="TRADE",
        trade_agreement_id=agreement["id"],
        daypart_targets=[{"daypart": "MIDDAY", "units": 1}],
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-05-05")
    get_success_data(
        api.suspend_trade_agreement(agreement["id"], make_billing_admin_headers("ba-1"))
    )

    resp = book_spot(
        order["id"], log["id"], daypart="MIDDAY", hour=10,
        headers=make_sales_rep_headers("rep-1"),
    )
    validate_error(resp, ApiErrorId.ERR_TRADE_AGREEMENT_INACTIVE)


# ---------------------------------------------------------------------------
# Validation priority: posture gate beats trade fiscal headroom
# ---------------------------------------------------------------------------

def _setup_posture_vs_fiscal_env(api):
    """TRADE order ACTIVE against an agreement drained to 1 cent; the log is
    walked LOCKED -> AS_RUN -> RECONCILING so booking violates both the posture
    gate and trade credit headroom."""
    env = setup_bookable_station(
        weekday="TUE", daypart="MIDDAY", hour=10, base_rate_cents=5000, min_rate_cents=1000
    )
    agreement = create_trade_agreement(
        env["station"]["id"], credit_limit_cents=10000, trade_ratio=1.0
    )
    append_adjustment(agreement["id"], -9999, note="drain")
    order = create_active_order(
        env["station"]["id"],
        order_kind="TRADE",
        trade_agreement_id=agreement["id"],
        daypart_targets=[{"daypart": "MIDDAY", "units": 1}],
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-05-05")
    import_as_run_ok(log["id"])
    get_success_data(api.begin_reconciliation(log["id"], TD_HEADERS))
    env.update({"agreement": agreement, "order": order, "log": log})
    return env


def test_posture_state_beats_trade_fiscal_error_id(api):
    """PRD §2.8: "then the log posture gate (`ERR_LOG_POSTURE_BLOCKED`),
    order-active gate (`ERR_ORDER_NOT_ACTIVE`), reconcile gate
    (`ERR_UNRESOLVED_DISCREPANCIES`), and clock-pinning gate
    (`ERR_NO_ACTIVE_CLOCK`)" comes before "finally fiscal rules in their
    declared sub-order (rate-card existence, then rate floor, then trade
    credit headroom)."

    Design: Difficulty/priority_pair_validation_conflict/posture_state_beats_trade_fiscal_on_spot_booking
    """
    env = _setup_posture_vs_fiscal_env(api)
    resp = book_spot(
        env["order"]["id"], env["log"]["id"], daypart="MIDDAY", hour=10,
        headers=make_sales_rep_headers("rep-1"),
    )
    err = validate_error(resp, ApiErrorId.ERR_LOG_POSTURE_BLOCKED)
    assert err["error_id"] != ApiErrorId.ERR_TRADE_CREDIT_EXCEEDED, (
        "posture gate (state tier) precedes trade credit headroom (fiscal tier) "
        "even though the trade value 5000 exceeds available 1"
    )
    assert resp.status_code == 409


def test_posture_state_beats_trade_fiscal_no_side_effects(api):
    """PRD §2.8: "then the log posture gate (`ERR_LOG_POSTURE_BLOCKED`),
    order-active gate (`ERR_ORDER_NOT_ACTIVE`), reconcile gate
    (`ERR_UNRESOLVED_DISCREPANCIES`), and clock-pinning gate
    (`ERR_NO_ACTIVE_CLOCK`)" precede the fiscal tier, so a booking rejected at
    the posture gate mutates nothing — no ledger DEBIT is appended and the
    agreement balance is untouched.

    Design: Difficulty/priority_pair_validation_conflict/posture_state_beats_trade_fiscal_on_spot_booking
    """
    env = _setup_posture_vs_fiscal_env(api)
    agreement_id = env["agreement"]["id"]
    before = get_success_data(
        api.get_trade_agreement(agreement_id, make_billing_admin_headers("ba-1"))
    )
    assert before["available_cents"] == 1

    resp = book_spot(
        env["order"]["id"], env["log"]["id"], daypart="MIDDAY", hour=10,
        headers=make_sales_rep_headers("rep-1"),
    )
    validate_error(resp, ApiErrorId.ERR_LOG_POSTURE_BLOCKED)

    after = get_success_data(
        api.get_trade_agreement(agreement_id, make_billing_admin_headers("ba-1"))
    )
    assert after["available_cents"] == 1, "rejected booking consumed no credit"
    assert after["consumed_cents"] == before["consumed_cents"]
