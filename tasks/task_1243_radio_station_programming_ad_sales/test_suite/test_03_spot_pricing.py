"""Spot unit-rate engine: ratings tiers, day-of-week factor, demand tiers,
min-rate floor, trade dual valuation, hour-pool capacity, and OCC on booking
(PRD §2.7, §3.2, §3.3, §3.6)."""
from test_helpers import (
    DATE_TUE,
    TD,
    ApiErrorId,
    assert_trade_agreement_invariants,
    book_spot,
    book_spot_ok,
    create_active_order,
    create_locked_log,
    create_trade_agreement,
    get_success_data,
    make_headers,
    setup_bookable_scenario,
    setup_bookable_station,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Trade dual valuation: cash-equivalent view vs ledger trade view
# ---------------------------------------------------------------------------

def _setup_trade_booking_env():
    """Station (fallback share 2.5), TUE clock, MIDDAY card 5000/1000,
    agreement limit 1000000 ratio 1.2, ACTIVE TRADE order, LOCKED log 2026-05-05."""
    env = setup_bookable_station(
        weekday="TUE", daypart="MIDDAY", hour=10, base_rate_cents=5000, min_rate_cents=1000
    )
    agreement = create_trade_agreement(
        env["station"]["id"], credit_limit_cents=1000000, trade_ratio=1.2
    )
    order = create_active_order(
        env["station"]["id"],
        order_kind="TRADE",
        trade_agreement_id=agreement["id"],
        daypart_targets=[{"daypart": "MIDDAY", "units": 1}],
    )
    log = create_locked_log(env["station"]["id"], log_date=DATE_TUE)
    env.update({"agreement": agreement, "order": order, "log": log})
    return env


def test_trade_spot_cash_equivalent_equals_unit_rate(api):
    """PRD §3.3: "the cash-equivalent view stores `cash_equivalent_cents` equal
    to the spot's `unit_rate_cents` (what a cash buyer would pay)". PRD §3.2:
    "if none exists, it falls back to the station's `default_share_fallback`"
    and "at least 2.0 but below 4.0 yields 1.00".

    Design: Difficulty/dual_variant_calc/trade_value_vs_cash_equivalent_ledger_valuation
    """
    env = _setup_trade_booking_env()
    spot = book_spot_ok(
        env["order"]["id"], env["log"]["id"], daypart="MIDDAY", hour=10,
        headers=make_headers("SalesRep", "rep-1"),
    )
    assert spot["unit_rate_cents"] == 5000, (
        "5000 base x 1.00 (fallback share 2.5 tier) x 1.00 (TUE) x 1.00 (demand)"
    )
    assert spot["cash_equivalent_cents"] == 5000, "cash view of the same spot"


def test_trade_spot_ledger_debit_uses_trade_ratio(api):
    """PRD §3.3: "the trade-ledger view appends a DEBIT of `trade_value` equal
    to the cash-equivalent amount multiplied by the agreement's `trade_ratio`,
    rounded half-up to integer cents." and "`available_cents` is
    `credit_limit_cents` minus `consumed_cents` plus `adjustments_cents`."

    Design: Difficulty/dual_variant_calc/trade_value_vs_cash_equivalent_ledger_valuation
    """
    env = _setup_trade_booking_env()
    spot = book_spot_ok(
        env["order"]["id"], env["log"]["id"], daypart="MIDDAY", hour=10,
        headers=make_headers("SalesRep", "rep-1"),
    )

    entries, _meta = validate_paginated(
        api.list_agreement_ledger_entries(env["agreement"]["id"], make_headers("BillingAdmin", "ba-1"))
    )
    assert len(entries) == 1
    assert entries[0]["entry_kind"] == "DEBIT"
    assert entries[0]["amount_cents"] == 6000, "trade view: round_half_up(5000 x 1.20)"
    assert entries[0]["spot_id"] == spot["id"]

    agreement = get_success_data(
        api.get_trade_agreement(env["agreement"]["id"], make_headers("BillingAdmin", "ba-1"))
    )
    assert agreement["consumed_cents"] == 6000
    assert agreement["available_cents"] == 994000
    assert_trade_agreement_invariants(agreement)
    assert spot["cash_equivalent_cents"] != entries[0]["amount_cents"], (
        "the two valuations diverge whenever the ratio differs from 1.0"
    )


# ---------------------------------------------------------------------------
# Rate floor, ratings fallback, demand tier boundary
# ---------------------------------------------------------------------------

def test_spot_rate_min_rate_floor_applies(api):
    """PRD §3.2: "the final `unit_rate_cents` is the greater of `min_rate_cents`
    and the raw product rounded half-up to integer cents." With share 1.0:
    "a share below 2.0 yields 0.80"; SAT: "The **day-of-week factor** is 0.85
    when the air date's weekday is `SAT` or `SUN`, and 1.00 otherwise."

    Design: Corner/calculations/spot_rate_min_rate_floor_applies
    """
    env = setup_bookable_station(
        weekday="SAT", daypart="AFTERNOON_DRIVE", hour=15,
        base_rate_cents=2000, min_rate_cents=1500, share_value=1.0,
        book_period=("2026-04-01", "2026-06-30"),
    )
    order = create_active_order(
        env["station"]["id"], daypart_targets=[{"daypart": "AFTERNOON_DRIVE", "units": 1}]
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-05-02")

    spot = book_spot_ok(order["id"], log["id"], daypart="AFTERNOON_DRIVE", hour=15)
    assert spot["unit_rate_cents"] == 1500, (
        "raw 2000 x 0.80 x 0.85 x 1.00 = 1360 is below the 1500 floor; max() pins 1500"
    )


def test_ratings_fallback_uses_station_default_share(api):
    """PRD §3.2: "The **ratings multiplier** looks up the `PUBLISHED`
    RatingsBook covering the air date (both period bounds inclusive); if none
    exists, it falls back to the station's `default_share_fallback`." and
    "a share below 2.0 yields 0.80".

    Design: Corner/calculations/ratings_fallback_uses_station_default_share
    """
    env = setup_bookable_station(
        default_share_fallback=1.5, base_rate_cents=10000, min_rate_cents=100
    )
    order = create_active_order(
        env["station"]["id"], daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 1}]
    )
    log = create_locked_log(env["station"]["id"])

    spot = book_spot_ok(order["id"], log["id"])
    assert spot["unit_rate_cents"] == 8000, (
        "10000 x 0.80 (fallback share 1.5 tier) x 1.00 (MON) x 1.00 (demand)"
    )


def test_demand_tier_boundary_at_exactly_070(api):
    """PRD §3.2: "A `u` below 0.70 yields 1.00; at least 0.70 but below 0.85
    yields 1.15; at least 0.85 yields 1.30 — so a utilization of exactly 0.70
    already pushes the multiplier to 1.15, and exactly 0.85 pushes it to 1.30."

    Design: Corner/calculations/demand_tier_boundary_at_exactly_070
    """
    env = setup_bookable_station(base_rate_cents=5000, min_rate_cents=100)
    order = create_active_order(
        env["station"]["id"], daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 8}]
    )
    log = create_locked_log(env["station"]["id"])

    for _ in range(6):
        book_spot_ok(order["id"], log["id"])

    seventh = book_spot_ok(order["id"], log["id"])
    assert seventh["unit_rate_cents"] == 5000, "u = 6/10 = 0.60 -> x1.00"

    eighth = book_spot_ok(order["id"], log["id"])
    assert eighth["unit_rate_cents"] == 5750, "u = 7/10 = 0.70 exactly -> x1.15"


# ---------------------------------------------------------------------------
# Hour pool capacity: unit-count boundary and seconds-aggregate boundary
# ---------------------------------------------------------------------------

def _setup_two_unit_hour_env():
    return setup_bookable_scenario(capacity_units=2, capacity_seconds=600, units=5)


def test_hour_units_capacity_equality_allows_reaching_cap(api):
    """PRD §3.6: "A new unit of one count and `duration_sec` seconds fits if
    and only if occupied units plus one is at most `capacity_units` and
    occupied seconds plus `duration_sec` is at most `capacity_seconds` —
    reaching the cap exactly is allowed; exceeding it by any amount rejects
    with `ERR_HOUR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/hour_units_capacity_equality_blocks_third_spot
    """
    env = _setup_two_unit_hour_env()
    s1 = book_spot_ok(env["order"]["id"], env["log"]["id"])
    s2 = book_spot_ok(env["order"]["id"], env["log"]["id"])
    assert s1["status"] == "SCHEDULED" and s2["status"] == "SCHEDULED", (
        "occupancy reaches exactly 2/2 units"
    )


def test_hour_units_capacity_equality_blocks_third_spot(api):
    """PRD §3.6: "reaching the cap exactly is allowed; exceeding it by any
    amount rejects with `ERR_HOUR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/hour_units_capacity_equality_blocks_third_spot
    """
    env = _setup_two_unit_hour_env()
    s1 = book_spot_ok(env["order"]["id"], env["log"]["id"])
    s2 = book_spot_ok(env["order"]["id"], env["log"]["id"])

    resp = book_spot(env["order"]["id"], env["log"]["id"])
    validate_error(resp, ApiErrorId.ERR_HOUR_CAPACITY_EXCEEDED)

    for spot_id in (s1["id"], s2["id"]):
        after = get_success_data(api.get_spot(spot_id, TD))
        assert after["status"] == "SCHEDULED", "no partial write from the rejected booking"


def test_hour_seconds_aggregate_allows_exact_fill(api):
    """PRD §3.6: "Occupancy counts both units and seconds across Spots and
    BarterAvails in `SCHEDULED` or `AIRED` at that (log, hour)." and "reaching
    the cap exactly is allowed".

    Design: Difficulty/resource_temporal_overlap/hour_seconds_aggregate_capacity_boundary
    """
    env = setup_bookable_scenario(capacity_units=10, capacity_seconds=120, units=3)
    s1 = book_spot_ok(env["order"]["id"], env["log"]["id"], duration_sec=60)
    s2 = book_spot_ok(env["order"]["id"], env["log"]["id"], duration_sec=60)
    assert s1["status"] == s2["status"] == "SCHEDULED", (
        "two 60s spots occupy exactly 120 == capacity_seconds"
    )


def test_hour_seconds_aggregate_blocks_overflow_by_one_unit(api):
    """PRD §3.6: "exceeding it by any amount rejects with
    `ERR_HOUR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/hour_seconds_aggregate_capacity_boundary
    """
    env = setup_bookable_scenario(capacity_units=10, capacity_seconds=120, units=3)
    book_spot_ok(env["order"]["id"], env["log"]["id"], duration_sec=60)
    book_spot_ok(env["order"]["id"], env["log"]["id"], duration_sec=60)

    resp = book_spot(env["order"]["id"], env["log"]["id"], duration_sec=15)
    validate_error(resp, ApiErrorId.ERR_HOUR_CAPACITY_EXCEEDED)


# ---------------------------------------------------------------------------
# Immediate consistency + OCC on spot booking
# ---------------------------------------------------------------------------

def test_booking_response_reflects_writes_immediately(api):
    """PRD §3.6: "On success, the spot is created `SCHEDULED`,
    `billed_rate_cents` is set at booking when the order's `reprice_policy` is
    `LOCKED_AT_BOOKING` (null otherwise), `cash_equivalent_cents` is set when
    the order is TRADE (null otherwise), a TRADE DEBIT ledger entry is appended
    (possibly flipping the agreement `ACTIVE → EXHAUSTED`), and the order's
    `units_scheduled` is recomputed with `version` bumped."

    Design: Corner/consistency_model/booking_response_reflects_writes_immediately
    """
    env = setup_bookable_scenario(units=1)
    order_id = env["order"]["id"]
    version_at_activate = env["order"]["version"]

    spot = book_spot_ok(order_id, env["log"]["id"])
    assert spot["unit_rate_cents"] == 1000 and spot["status"] == "SCHEDULED", (
        "create response already carries the computed rate and SCHEDULED status"
    )
    assert spot["billed_rate_cents"] == 1000, "LOCKED_AT_BOOKING pins billed at booking"
    assert spot["cash_equivalent_cents"] is None, "CASH order: no cash-equivalent stored"

    order = get_success_data(api.get_order(order_id, TD))
    assert order["units_scheduled"] == 1
    assert order["version"] == version_at_activate + 1, "version bumped by the booking"


def test_occ_stale_order_version_returns_412(api):
    """PRD §2.7: "Booking a spot requires `expected_order_version` matching the
    target Order's current `version`." and "In each case, a mismatch — which
    signals that another writer has mutated the parent since the client last
    read it (for example, by booking or cancelling a spot, by appending a music
    placement, or by scheduling another avail) — is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_order_version_returns_412
    """
    env = setup_bookable_scenario(units=2)
    order_id = env["order"]["id"]
    log_id = env["log"]["id"]
    stale_version = env["order"]["version"]

    first = book_spot_ok(order_id, log_id, expected_order_version=stale_version)
    assert first["status"] == "SCHEDULED"

    order = get_success_data(api.get_order(order_id, TD))
    assert order["version"] == stale_version + 1, "first booking bumped the version"

    resp = book_spot(order_id, log_id, expected_order_version=stale_version)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
