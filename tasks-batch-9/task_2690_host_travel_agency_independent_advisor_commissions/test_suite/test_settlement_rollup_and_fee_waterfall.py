"""Round-then-sum roll-up and the five-step host economics waterfall."""
from test_helpers import (
    api_client,
    confirm_booking,
    controller,
    new_booking,
    new_client,
    new_consortium,
    new_split_schedule,
    new_supplier,
    open_run,
    read_booking,
    record_receipt,
    set_clock,
    setup_active_advisor,
    statements_for_run,
    validate_success,
)

REMIT_CLOCK = "2026-10-05T00:00:00Z"
REMIT_DATE = "2026-10-05"
REMIT_PERIOD = "2026-10"

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
TWO_RUNG_FEE_TIERS = [
    {"min_share_cents": 0, "fee_pct": 0.05},
    {"min_share_cents": 1_000_000, "fee_pct": 0.03},
]


def _consortium_advisor_with_outside_supplier(supplier_overrides):
    """A consortium-member advisor selling a supplier that joined no consortium."""
    schedule = new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=TWO_RUNG_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )
    consortium = new_consortium(
        name="Voyager Alliance",
        membership_fee_cents=5_000_000,
        marketing_fund_accrual_pct=0.02,
        consortium_channel_bonus_pct=0.01,
    )
    supplier = new_supplier(**supplier_overrides)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=[supplier],
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    return {
        "advisor": ctx["advisor"],
        "client": client,
        "supplier": supplier,
        "schedule": schedule,
        "consortium": consortium,
    }


def _paid_bookings(scenario, gross_and_windows, paid_cents):
    """Submit, confirm and collect each booking, then open the monthly run."""
    bookings = []
    for gross, start, end in gross_and_windows:
        booking = new_booking(
            scenario["advisor"]["id"],
            scenario["supplier"]["id"],
            scenario["client"]["id"],
            channel="SUPPLIER_DIRECT",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=gross,
            travel_start_date=start,
            travel_end_date=end,
        )
        bookings.append(confirm_booking(booking["id"], scenario["supplier"]["id"]))
    set_clock(REMIT_CLOCK)
    for booking in bookings:
        record_receipt(
            booking["id"], scenario["supplier"]["id"], paid_cents, REMIT_DATE
        )
    return bookings, open_run(REMIT_PERIOD)


NORTHWIND = {
    "name": "Northwind Tours",
    "accreditation_scheme": "IATA",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 2_000_000,
    "remit_terms_days": 30,
}

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def _half_cent_pair():
    """Two identical bookings whose advisor share lands on a half cent."""
    scenario = _consortium_advisor_with_outside_supplier(NORTHWIND)
    bookings, run = _paid_bookings(
        scenario,
        [
            (1_000_150, "2026-06-01", "2026-06-05"),
            (1_000_150, "2026-06-06", "2026-06-10"),
        ],
        100_015,
    )
    scenario["bookings"] = bookings
    scenario["run"] = run
    return scenario


def test_each_booking_share_is_rounded_before_the_statement_sums_them():
    """PRD §3.8: "Rounding order is pinned and mandatory: each booking's
    `settled_share_cents` is its `received_commission_cents` multiplied by its own
    percentage, **rounded half up to whole cents per booking**, and the statement's
    `advisor_share_cents` is the plain integer sum of those already-rounded figures."

    Design: Difficulty/combinatorial_formula/statement_rollup_mode_b_round_per_booking_then_sum
    """
    scenario = _half_cent_pair()

    validate_success(
        api_client.calculate_settlement_run(scenario["run"]["id"], controller("ctrl-1"))
    )

    for booking in scenario["bookings"]:
        settled = read_booking(booking["id"])
        assert settled["expected_commission_cents"] == 100_015
        assert settled["received_commission_cents"] == 100_015
        assert settled["settled_share_cents"] == 70_011
        assert settled["settled_tier_level"] == 1


def test_statement_totals_sum_the_rounded_shares_rather_than_rounding_once():
    """PRD §2.6: "The two approaches disagree whenever two or more bookings each round
    upward from a half cent: two bookings of 100,015 cents each at a seventy-percent
    advisor share produce 70,011 plus 70,011, that is 140,022 cents, whereas rounding
    the combined 200,030 cents once would produce 140,021 cents."

    Design: Difficulty/combinatorial_formula/statement_rollup_mode_b_round_per_booking_then_sum
    """
    scenario = _half_cent_pair()

    run = validate_success(
        api_client.calculate_settlement_run(scenario["run"]["id"], controller("ctrl-1"))
    )

    assert run["statement_count"] == 1
    assert run["gross_commission_cents"] == 200_030
    assert run["advisor_share_total_cents"] == 140_022
    assert run["advisor_share_total_cents"] != 140_021
    assert run["platform_fee_total_cents"] == 7_001
    assert run["marketing_fund_total_cents"] == 2_660
    assert run["net_payout_total_cents"] == 130_361

    statement = statements_for_run(run["id"])[0]
    assert statement["booking_count"] == 2
    assert statement["advisor_share_cents"] == 140_022


def _million_cent_share():
    """One booking whose gross share crosses the second platform-fee floor."""
    scenario = _consortium_advisor_with_outside_supplier(MERIDIAN)
    bookings, run = _paid_bookings(
        scenario, [(14_571_430, "2026-06-01", "2026-06-05")], 1_457_143
    )
    scenario["bookings"] = bookings
    scenario["run"] = run
    return scenario


def test_platform_fee_tier_is_keyed_on_the_pre_fee_gross_share():
    """PRD §3.8: "**Step two** selects the platform-fee tier, and it keys that
    selection on the **pre-fee** gross share, never on the eventual net payout; the
    ladder used is the `platform_fee_tiers` of the schedule reached through the
    advisor's agreement whose `status` is `ACTIVE` or `TERMINATED` and whose
    `effective_date` is the greatest, ties broken by `created_at` ascending."

    Design: Difficulty/combinatorial_formula/platform_fee_mode_c_pre_fee_tier_post_fee_marketing_base
    """
    scenario = _million_cent_share()

    run = validate_success(
        api_client.calculate_settlement_run(scenario["run"]["id"], controller("ctrl-1"))
    )

    settled = read_booking(scenario["bookings"][0]["id"])
    assert settled["expected_commission_cents"] == 1_457_143
    assert settled["settled_share_cents"] == 1_020_000
    assert run["advisor_share_total_cents"] == 1_020_000
    assert run["platform_fee_total_cents"] == 30_600
    assert run["platform_fee_total_cents"] != 51_000


def test_marketing_fund_accrues_on_the_post_fee_base():
    """PRD §3.8: "**Step four** accrues the consortium marketing fund, and it keys on
    the **post-fee** base rather than the gross share: when the advisor has no
    `consortium_id`, `marketing_fund_cents` is 0; otherwise it is the gross share less
    `platform_fee_cents`, multiplied by the consortium's `marketing_fund_accrual_pct`,
    rounded half up to whole cents independently of step three."

    Design: Difficulty/combinatorial_formula/platform_fee_mode_c_pre_fee_tier_post_fee_marketing_base
    """
    scenario = _million_cent_share()

    run = validate_success(
        api_client.calculate_settlement_run(scenario["run"]["id"], controller("ctrl-1"))
    )

    statement = statements_for_run(run["id"])[0]
    assert statement["advisor_share_cents"] == 1_020_000
    assert statement["platform_fee_cents"] == 30_600
    assert statement["marketing_fund_cents"] == 19_788
    assert statement["net_payout_cents"] == 969_612
    assert run["marketing_fund_total_cents"] == 19_788
    assert run["net_payout_total_cents"] == 969_612
