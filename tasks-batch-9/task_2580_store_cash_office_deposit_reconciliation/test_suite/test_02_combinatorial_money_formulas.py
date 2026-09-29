"""Pinned money formulas: per-line strap rounding before summation, and the carrier fee's increment key."""

from test_helpers import (
    CLERK_1,
    CLERK_2,
    change_order_payload,
    create_safe,
    create_sales_journal,
    create_store,
    deposit_payload,
    make_clerk_headers,
    read_change_order,
    read_deposit,
    read_safe,
    set_clock,
    unlock_safe,
    validate_success,
)

# The five denomination rows a change order always plans, with the strap_count,
# units and planned_cents each row reaches once its own raw unit count has been
# rounded up to the next whole strap or roll.
EXPECTED_PLANNED_LINES = [
    {
        "denomination_cents": 2000,
        "strap_count": 11,
        "units": 275,
        "planned_cents": 550000,
    },
    {
        "denomination_cents": 1000,
        "strap_count": 9,
        "units": 225,
        "planned_cents": 225000,
    },
    {
        "denomination_cents": 500,
        "strap_count": 7,
        "units": 350,
        "planned_cents": 175000,
    },
    {
        "denomination_cents": 100,
        "strap_count": 21,
        "units": 1050,
        "planned_cents": 105000,
    },
    {
        "denomination_cents": 25,
        "strap_count": 51,
        "units": 2040,
        "planned_cents": 51000,
    },
]

# One hundred twenty-dollar notes plus five one-dollar notes: 200500 cents, a bag
# that straddles the third thousand-dollar increment by 500 cents.
STRADDLING_BAG_LINES = [
    {"denomination_cents": 2000, "quantity": 100},
    {"denomination_cents": 100, "quantity": 5},
]


def _register_baseline_store():
    """Register the store whose standing seasonal_profile is BASELINE."""
    set_clock("2026-08-03T09:00:00Z")
    return create_store(
        store_code="S-1003",
        name="Store 1003",
        region_code="EAST",
        seasonal_profile="BASELINE",
    )


def _file_holiday_change_order(api, store_id):
    """File the seven-day order that overrides the store's profile with HOLIDAY."""
    payload = change_order_payload(
        store_id,
        target_week_start="2026-08-10",
        days_covered=7,
        baseline_daily_cash_demand_cents=80000,
        growth_pct=0,
        seasonal_profile_override="HOLIDAY",
    )
    return validate_success(
        api.create_change_order(payload, make_clerk_headers(CLERK_1)), 201
    )


def test_change_order_plans_each_denomination_row_up_to_a_whole_strap(api):
    """PRD §3.9: "The order's `forecast_demand_cents` is `baseline_daily_cash_demand_cents` multiplied by `days_covered`, multiplied by that seasonal multiplier, multiplied by one plus `growth_pct`, with the result rounded half up to whole cents."

    PRD §3.9: "Twenty-dollar notes take a 0.50 share of the forecast and come in straps of 25 notes; ten-dollar notes take 0.20 and also come in straps of 25; five-dollar notes take 0.15 and come in straps of 50; one-dollar notes take 0.10 and come in straps of 50; and quarters take the remaining 0.05 and come in rolls of 40 coins."

    PRD §3.9: "The row's `strap_count` is that raw count divided by the row's units-per-strap and rounded **up** to the next whole strap or roll."

    Design: Difficulty/combinatorial_formula/change_order_strap_rounding_per_line_before_summation
    """
    store = _register_baseline_store()
    order = _file_holiday_change_order(api, store["id"])

    assert order["applied_seasonal_profile"] == "HOLIDAY", (
        "expected applied_seasonal_profile HOLIDAY, got "
        f"{order['applied_seasonal_profile']}"
    )
    assert order["forecast_demand_cents"] == 1008000, (
        f"expected forecast_demand_cents 1008000, got {order['forecast_demand_cents']}"
    )
    assert order["status"] == "DRAFT", (
        f"expected status DRAFT, got {order['status']}"
    )

    plan = order["planned_lines"]
    assert len(plan) == 5, f"expected exactly 5 planned_lines entries, got {len(plan)}"
    assert [line["denomination_cents"] for line in plan] == [2000, 1000, 500, 100, 25], (
        "expected planned_lines ordered 2000, 1000, 500, 100, 25, got "
        f"{[line['denomination_cents'] for line in plan]}"
    )
    for index, expected in enumerate(EXPECTED_PLANNED_LINES):
        actual = plan[index]
        for field, value in expected.items():
            assert actual[field] == value, (
                f"planned_lines[{index}] {field}: expected {value}, got {actual[field]}"
            )


def test_change_order_total_sums_the_rounded_up_lines_not_the_exact_targets(api):
    """PRD §3.9: "Only after every line has been rounded up individually is `total_planned_cents` formed as the sum of the lines' `planned_cents`."

    PRD §3.9: "This order is pinned and is not interchangeable with summing the exact per-line targets and rounding the total once: for a `forecast_demand_cents` of 1008000, rounding each line up first yields a `total_planned_cents` of 1106000, whereas summing first and rounding once yields 1007200."

    Design: Difficulty/combinatorial_formula/change_order_strap_rounding_per_line_before_summation
    """
    store = _register_baseline_store()
    order = _file_holiday_change_order(api, store["id"])

    assert order["forecast_demand_cents"] == 1008000, (
        f"expected forecast_demand_cents 1008000, got {order['forecast_demand_cents']}"
    )
    assert order["total_planned_cents"] == 1106000, (
        f"expected total_planned_cents 1106000, got {order['total_planned_cents']}"
    )
    assert order["total_planned_cents"] != 1007200, (
        "total_planned_cents must not be the summed-then-rounded-once figure 1007200, "
        f"got {order['total_planned_cents']}"
    )

    # The stored order agrees with the creation response.
    stored = read_change_order(order["id"])
    assert stored["total_planned_cents"] == 1106000, (
        f"expected total_planned_cents 1106000 on read, got {stored['total_planned_cents']}"
    )


def _setup_open_safe_for_the_straddling_bag():
    """Register the store, commission and open SAFE-A, and open the day's journal."""
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1004",
        name="Store 1004",
        region_code="EAST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], "2026-08-03")
    # Arm at 09:00Z and open at 09:05Z, the boundary instant of the five-minute delay.
    safe = unlock_safe(
        safe["id"],
        "2026-08-03T09:00:00Z",
        delay_minutes=5,
        requester_user_id=CLERK_1,
        opener_user_id=CLERK_2,
    )
    return {"store": store, "safe": safe, "journal": journal}


def _prepare_straddling_bag(api, safe_id, journal_id):
    """Prepare the 200500-cent bag out of the open safe, pricing the carrier fee."""
    payload = deposit_payload(
        safe_id,
        journal_id,
        STRADDLING_BAG_LINES,
        read_safe(safe_id)["version"],
        business_date="2026-08-03",
    )
    return validate_success(
        api.create_deposit(payload, make_clerk_headers(CLERK_1)), 201
    )


def test_carrier_fee_counts_increments_on_the_declared_total(api):
    """PRD §3.6: "The fee is twelve dollars — `1200` cents — plus thirty-five cents for every thousand-dollar increment of the bag, where the number of increments is `declared_total_cents` divided by 100000 and rounded **up** to the next whole increment."

    PRD §3.6: "That result is stored as `carrier_fee_cents`, and `expected_credit_cents` is then `declared_total_cents` minus `carrier_fee_cents`."

    PRD §3.6: "The increment count is keyed on `declared_total_cents` — the amount the store hands over — and never on `expected_credit_cents`, which already has the fee subtracted and would make the calculation self-referential."

    Design: Difficulty/combinatorial_formula/carrier_fee_tier_keyed_on_declared_total_not_expected_credit
    """
    ctx = _setup_open_safe_for_the_straddling_bag()
    deposit = _prepare_straddling_bag(api, ctx["safe"]["id"], ctx["journal"]["id"])

    assert deposit["declared_total_cents"] == 200500, (
        f"expected declared_total_cents 200500, got {deposit['declared_total_cents']}"
    )
    assert deposit["carrier_fee_cents"] == 1305, (
        f"expected carrier_fee_cents 1305, got {deposit['carrier_fee_cents']}"
    )
    assert deposit["expected_credit_cents"] == 199195, (
        f"expected expected_credit_cents 199195, got {deposit['expected_credit_cents']}"
    )


def test_carrier_fee_is_not_the_figure_a_net_keyed_increment_count_would_give(api):
    """PRD §3.6: "The difference is real whenever the fee straddles a thousand-dollar boundary: a bag of `declared_total_cents` 200500 is priced at a `carrier_fee_cents` of 1305 and an `expected_credit_cents` of 199195, whereas keying the increment count on the net figure would have given 1270 and 199230."

    PRD §3.3: "The cycle closes when a prepared bag is sealed, which returns the safe from `UNLOCKED` to `LOCKED` and clears all three timing fields; preparing a bag does *not* relock the safe, which is precisely why several bags may be prepared inside one opening."

    Design: Difficulty/combinatorial_formula/carrier_fee_tier_keyed_on_declared_total_not_expected_credit
    """
    ctx = _setup_open_safe_for_the_straddling_bag()
    created = _prepare_straddling_bag(api, ctx["safe"]["id"], ctx["journal"]["id"])

    deposit = read_deposit(created["id"])
    assert deposit["carrier_fee_cents"] != 1270, (
        "carrier_fee_cents must not be the net-keyed figure 1270, got "
        f"{deposit['carrier_fee_cents']}"
    )
    assert deposit["expected_credit_cents"] != 199230, (
        "expected_credit_cents must not be the net-keyed figure 199230, got "
        f"{deposit['expected_credit_cents']}"
    )
    assert deposit["status"] == "PREPARING", (
        f"expected status PREPARING, got {deposit['status']}"
    )

    safe = read_safe(ctx["safe"]["id"])
    assert safe["balance_cents"] == 299500, (
        f"expected balance_cents 299500 after the removal, got {safe['balance_cents']}"
    )
    assert safe["open_state"] == "UNLOCKED", (
        f"expected open_state UNLOCKED after preparation, got {safe['open_state']}"
    )
