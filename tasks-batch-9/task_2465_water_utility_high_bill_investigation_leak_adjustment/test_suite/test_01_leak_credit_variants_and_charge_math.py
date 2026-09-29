"""Leak-credit variant selection, bench-accuracy grading and the charge formulas.

The suites in this module pin the money and the metering verdicts that a
high-bill dispute turns on: the dual-variant credit preview and the credit a
buried-leak determination actually produces, the two bench-accuracy composites a
meter's size selects between, the seasonal branch of the tiered water charge,
the instalment schedule of a payment plan, and the pinned order in which the
credit cap and the administrative-fee waiver are consulted.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    assertions,
    fixtures,
)

# ---------------------------------------------------------------------------
# The 41,000-gallon SUMMER bill on the standard tariff and its 4,000-gallon
# seasonal baseline, together with the two variant nets it produces.
# ---------------------------------------------------------------------------
TARGET_GALLONS = 41000
BASELINE_GALLONS = 4000
TARGET_TOTAL_CENTS = 44939
EXCESS_GALLONS = 37000
EXCESS_REPRICE_NET_CENTS = 26779
BASELINE_REBILL_NET_CENTS = 26963
VARIANT_DELTA_CENTS = 184
ISSUED_BALANCE_CENTS = 60569

# The three bench flow points both meters are graded on.
LOW_FLOW_PCT = 95.20
MID_FLOW_PCT = 103.40
HIGH_FLOW_PCT = 102.10


# ===========================================================================
# The dual-variant credit preview on one bill and one leak type
# ===========================================================================
def test_adjustment_preview_returns_both_variant_nets_and_their_delta(api):
    """PRD §3.6: "The preview runs the credit calculation twice on the same bill — once forced to `EXCESS_REPRICE` and once forced to `BASELINE_REBILL` — and returns `bill_id`, the echoed `assumed_leak_type`, a `recommended_variant` naming the variant the credit rule would actually select for that leak type, the `excess_gallons`, an `excess_reprice_net_cents`, a `baseline_rebill_net_cents`, and a `variant_delta_cents` equal to the baseline-rebill net minus the excess-reprice net."

    PRD §3.6: "`excess_gallons` is `consumption_gallons` minus `seasonal_baseline_gallons`, with any negative result treated as zero."

    Design: Difficulty/dual_variant_calc/dual_variant_leak_credit_excess_reprice_vs_baseline_rebill
    """
    ctx = fixtures.determined_case(
        api,
        leak_type="SERVICE_LINE",
        leak_determination="CUSTOMER_SIDE_LEAK",
        target_gallons=TARGET_GALLONS,
    )

    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(
        bill,
        consumption_gallons=TARGET_GALLONS,
        seasonal_baseline_gallons=BASELINE_GALLONS,
        total_charge_cents=TARGET_TOTAL_CENTS,
    )

    preview = validate_success(
        api.get_adjustment_preview(
            ctx["bill_id"], CSR_HEADERS, {"assumed_leak_type": "SERVICE_LINE"}
        )
    )
    assertions.assert_fields(
        preview,
        bill_id=ctx["bill_id"],
        assumed_leak_type="SERVICE_LINE",
        excess_gallons=EXCESS_GALLONS,
        excess_reprice_net_cents=EXCESS_REPRICE_NET_CENTS,
        baseline_rebill_net_cents=BASELINE_REBILL_NET_CENTS,
        variant_delta_cents=VARIANT_DELTA_CENTS,
        recommended_variant="BASELINE_REBILL",
    )
    assert (
        preview["variant_delta_cents"]
        == preview["baseline_rebill_net_cents"] - preview["excess_reprice_net_cents"]
    )


def test_service_line_credit_applies_the_baseline_rebill_variant(api):
    """PRD §3.6: "Buried leaks — `SERVICE_LINE` and `UNDERGROUND` — take `BASELINE_REBILL`, where the whole excess is forgiven and the bill is simply rewritten to the baseline: `water_credit_cents` is `water_charge_cents` minus the water charge that consumption of exactly `seasonal_baseline_gallons` in that same `season` would have produced, again with any negative result treated as zero."

    PRD §3.6: "When the `leak_type` is one of the four eligible classes and `excess_gallons` is greater than zero, `sewer_relief_gallons` is the smallest of three quantities: `excess_gallons`, the statutory relief basis of 8,000 gallons, and the remaining headroom, where headroom is `sewer_billable_gallons` minus `submeter_credit_gallons` with any negative result treated as zero."

    PRD §3.6: "`capped_credit_cents` is the lesser of `gross_credit_cents` and `cap_cents`, and `cap_applied` is true exactly when `capped_credit_cents` is less than `gross_credit_cents`."

    Design: Difficulty/dual_variant_calc/dual_variant_leak_credit_excess_reprice_vs_baseline_rebill
    """
    ctx = fixtures.determined_case(
        api,
        leak_type="SERVICE_LINE",
        leak_determination="CUSTOMER_SIDE_LEAK",
        target_gallons=TARGET_GALLONS,
    )

    adjustment = fixtures.draft_adjustment(
        api,
        ctx["investigation_id"],
        ctx["bill_id"],
        "SERVICE_LINE",
        ctx["investigation_version"],
        ctx["rep_headers"],
    )

    assertions.assert_credit_breakdown(
        adjustment,
        variant_applied="BASELINE_REBILL",
        excess_gallons=EXCESS_GALLONS,
        water_credit_cents=34849,
        sewer_relief_gallons=8000,
        sewer_credit_cents=4880,
        gross_credit_cents=39729,
        cap_cents=BASELINE_REBILL_NET_CENTS,
        capped_credit_cents=BASELINE_REBILL_NET_CENTS,
        cap_applied=True,
        admin_fee_charged_cents=0,
        net_credit_cents=BASELINE_REBILL_NET_CENTS,
    )
    assertions.assert_fields(
        fixtures.fetch_adjustment(api, adjustment["id"]),
        net_credit_cents=BASELINE_REBILL_NET_CENTS,
        variant_applied="BASELINE_REBILL",
    )


def test_preview_and_draft_move_no_money_on_the_account_ledger(api):
    """PRD §3.6: "The preview creates no `LeakAdjustment` row and writes no ledger entry, and it recomputes from scratch on every call, so a rebill landing between two previews changes the answer."

    PRD §3.6: "A successful draft opens in `DRAFT` with `created_by_user_id` set to the acting `X-User-ID`, `board_ordered` false, `supersedes_adjustment_id` null, and every credit field computed; it moves the investigation from `DETERMINED` to `ADJUSTMENT_PENDING` and increments the investigation's `version` by one."

    Design: Difficulty/dual_variant_calc/dual_variant_leak_credit_excess_reprice_vs_baseline_rebill
    """
    ctx = fixtures.determined_case(
        api,
        leak_type="SERVICE_LINE",
        leak_determination="CUSTOMER_SIDE_LEAK",
        target_gallons=TARGET_GALLONS,
    )

    validate_success(
        api.get_adjustment_preview(
            ctx["bill_id"], CSR_HEADERS, {"assumed_leak_type": "SERVICE_LINE"}
        )
    )
    adjustment = fixtures.draft_adjustment(
        api,
        ctx["investigation_id"],
        ctx["bill_id"],
        "SERVICE_LINE",
        ctx["investigation_version"],
        ctx["rep_headers"],
    )
    assert adjustment["status"] == "DRAFT"

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_no_entry_of_kind(entries, "LEAK_ADJUSTMENT_CREDIT")
    assertions.assert_no_entry_of_kind(entries, "LEAK_ADJUSTMENT_ADMIN_FEE")

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=ISSUED_BALANCE_CENTS)
    assertions.assert_balance_is_ledger_sum(account, entries)


# ===========================================================================
# Bench accuracy: one flow triple, two meter sizes, two verdicts
# ===========================================================================
def _bench_pair(api):
    """Two bench requests on one investigation: a 3.0 inch and a 1.0 inch master."""
    ctx = fixtures.investigation_case(api, target_gallons=TARGET_GALLONS)
    large_meter = fixtures.create_master_meter(
        api, ctx["account_id"], size_inches=3.0, initial_register_value=200000
    )
    fixtures.post_reading(api, large_meter["id"], "2026-07-31", 200000)

    large_request = fixtures.request_meter_test(
        api,
        ctx["investigation_id"],
        large_meter["id"],
        "BENCH",
        "UTILITY",
        TECHNICIAN_HEADERS,
    )
    small_request = fixtures.request_meter_test(
        api,
        ctx["investigation_id"],
        ctx["meter_id"],
        "BENCH",
        "UTILITY",
        TECHNICIAN_HEADERS,
    )
    assert large_request["status"] == "BENCH_TEST_PENDING"
    assert small_request["status"] == "BENCH_TEST_PENDING"

    fixtures.set_clock(api, "2026-08-05T12:00:00Z")
    large_result = fixtures.record_bench_result(
        api,
        large_request["id"],
        LOW_FLOW_PCT,
        MID_FLOW_PCT,
        HIGH_FLOW_PCT,
        tested_at="2026-08-05T09:00:00Z",
    )
    small_result = fixtures.record_bench_result(
        api,
        small_request["id"],
        LOW_FLOW_PCT,
        MID_FLOW_PCT,
        HIGH_FLOW_PCT,
        tested_at="2026-08-05T11:00:00Z",
    )
    ctx.update(
        {
            "large_meter_id": large_meter["id"],
            "large_request": large_result,
            "small_request": small_result,
        }
    )
    return ctx


def test_small_master_meter_is_graded_awwa_weighted_and_fails_fast(api):
    """PRD §3.4: "A meter of 2.0 inches or smaller is graded `AWWA_WEIGHTED`, where `accuracy_pct` is `low_flow_pct` multiplied by fifteen hundredths, plus `mid_flow_pct` multiplied by seventy hundredths, plus `high_flow_pct` multiplied by fifteen hundredths, rounded half up to two decimal places — a weighting that deliberately dominates the composite with mid-flow behaviour."

    PRD §3.4: "`bench_result` classifies the already-rounded `accuracy_pct` with two strict comparisons: it is `FAST` when `accuracy_pct` is strictly greater than 101.50, `SLOW` when `accuracy_pct` is strictly less than 98.50, and `PASS` when it lies at or between those two bounds."

    PRD §3.4: "In all cases the meter's `correction_factor` is one hundred divided by `accuracy_pct`, rounded half up to six decimal places."

    Design: Difficulty/dual_variant_calc/dual_variant_bench_accuracy_awwa_weighted_vs_simple_mean
    """
    ctx = _bench_pair(api)

    request = ctx["small_request"]
    assertions.assert_fields(
        request,
        accuracy_method="AWWA_WEIGHTED",
        bench_result="FAST",
        status="CLOSED_FAST",
    )
    assert request["accuracy_pct"] == pytest.approx(101.98, abs=1e-9)

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assert meter["accuracy_status"] == "FAILED_FAST"
    assert meter["correction_factor"] == pytest.approx(0.980584, abs=1e-9)


def test_large_master_meter_is_graded_simple_mean_and_passes(api):
    """PRD §3.4: "A meter larger than 2.0 inches is graded `SIMPLE_MEAN`, where `accuracy_pct` is the sum of the three percentages divided by three, rounded half up to two decimal places."

    PRD §3.4: "`bench_result` classifies the already-rounded `accuracy_pct` with two strict comparisons: it is `FAST` when `accuracy_pct` is strictly greater than 101.50, `SLOW` when `accuracy_pct` is strictly less than 98.50, and `PASS` when it lies at or between those two bounds."

    Design: Difficulty/dual_variant_calc/dual_variant_bench_accuracy_awwa_weighted_vs_simple_mean
    """
    ctx = _bench_pair(api)

    request = ctx["large_request"]
    assertions.assert_fields(
        request,
        accuracy_method="SIMPLE_MEAN",
        bench_result="PASS",
        status="CLOSED_PASS",
    )
    assert request["accuracy_pct"] == pytest.approx(100.23, abs=1e-9)

    meter = fixtures.fetch_meter(api, ctx["large_meter_id"])
    assert meter["accuracy_status"] == "VERIFIED_ACCURATE"
    assert meter["correction_factor"] == pytest.approx(0.997705, abs=1e-9)


def test_identical_flow_points_diverge_by_meter_size_with_no_deposit_refund(api):
    """PRD §3.4: "The same three flow points on differently sized meters can therefore yield different verdicts."

    PRD §3.4: "When `deposit_cents` is greater than zero, a `CREDIT` entry with `source_kind` `METER_TEST_DEPOSIT_REFUND` for the negative deposit amount is written and `deposit_refunded` becomes true."

    Design: Difficulty/dual_variant_calc/dual_variant_bench_accuracy_awwa_weighted_vs_simple_mean
    """
    ctx = _bench_pair(api)

    small = ctx["small_request"]
    large = ctx["large_request"]

    for request in (small, large):
        assertions.assert_fields(
            request,
            low_flow_pct=LOW_FLOW_PCT,
            mid_flow_pct=MID_FLOW_PCT,
            high_flow_pct=HIGH_FLOW_PCT,
            deposit_cents=0,
            deposit_refunded=False,
        )

    assert small["accuracy_pct"] != large["accuracy_pct"]
    assert small["accuracy_method"] != large["accuracy_method"]
    assert small["bench_result"] != large["bench_result"]

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT")
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT_REFUND")


# ===========================================================================
# The tiered water charge: nested clamping and the seasonal surcharge branch
# ===========================================================================
def _seasonal_pair(api):
    """Two 41,000-gallon bills on one tariff, one in SUMMER and one in WINTER."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    winter_period = fixtures.create_billing_period(
        api,
        period_code="2026-01",
        start_date="2026-01-01",
        end_date="2026-01-31",
        season="WINTER",
        rebilling_deadline_date="2026-12-31",
    )
    summer_period = fixtures.create_billing_period(
        api,
        period_code="2026-07",
        start_date="2026-07-01",
        end_date="2026-07-31",
        season="SUMMER",
        rebilling_deadline_date="2027-01-31",
    )

    summer_account = fixtures.create_account(
        api, schedule["id"], account_number="ACC-SUM", customer_name="Sunny Ortiz"
    )
    winter_account = fixtures.create_account(
        api, schedule["id"], account_number="ACC-WIN", customer_name="Wynn Talbot"
    )
    summer_meter = fixtures.create_master_meter(
        api, summer_account["id"], initial_register_value=100000
    )
    winter_meter = fixtures.create_master_meter(
        api, winter_account["id"], initial_register_value=500000
    )

    fixtures.post_reading(api, summer_meter["id"], "2026-06-30", 100000)
    fixtures.post_reading(api, summer_meter["id"], "2026-07-31", 141000)
    fixtures.post_reading(api, winter_meter["id"], "2025-12-31", 500000)
    fixtures.post_reading(api, winter_meter["id"], "2026-01-31", 541000)

    summer_bill = fixtures.generate_bill(
        api, summer_account["id"], summer_period["id"], summer_meter["id"]
    )
    winter_bill = fixtures.generate_bill(
        api, winter_account["id"], winter_period["id"], winter_meter["id"]
    )
    return {
        "summer_account_id": summer_account["id"],
        "winter_account_id": winter_account["id"],
        "summer_bill": summer_bill,
        "winter_bill": winter_bill,
    }


def test_summer_surcharge_loads_only_the_third_tier_line_of_the_water_charge(api):
    """PRD §3.2: "Line three depends on the period's `season`: in `WINTER` it is the third-tier volume multiplied by `tier3_rate_cents_per_kgal`, divided by one thousand, rounded half up; in `SUMMER` the surcharge is folded in *before* the rounding, so line three is the third-tier volume multiplied by `tier3_rate_cents_per_kgal`, multiplied by ten thousand plus `summer_surcharge_bp`, divided by one thousand and then by ten thousand, and only then rounded half up."

    PRD §3.2: "`water_charge_cents` is `base_charge_cents` plus the three rounded lines."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_tiered_water_charge_nested_clamp_seasonal_branch
    """
    ctx = _seasonal_pair(api)

    summer = ctx["summer_bill"]
    winter = ctx["winter_bill"]

    assertions.assert_bill_charges(
        summer, consumption_gallons=41000, water_charge_cents=37619
    )
    assertions.assert_bill_charges(
        winter, consumption_gallons=41000, water_charge_cents=33480
    )
    assert summer["water_charge_cents"] - winter["water_charge_cents"] == 4139


def test_seasonal_water_branch_leaves_the_sewer_charge_identical(api):
    """PRD §3.2: "Rounding each line independently before the sum is mandatory; producing one unrounded grand total and rounding that instead yields a different answer, and the surcharge never touches lines one or two."

    PRD §3.2: "`sewer_charge_cents` is `sewer_billable_gallons` multiplied by `sewer_rate_cents_per_kgal`, divided by one thousand, rounded half up once on that final product."

    PRD §3.2: "`total_charge_cents` is `water_charge_cents` plus `sewer_charge_cents`, and at generation time `adjusted_total_cents` equals `total_charge_cents` because no credit has been posted."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_tiered_water_charge_nested_clamp_seasonal_branch
    """
    ctx = _seasonal_pair(api)

    assertions.assert_bill_charges(
        ctx["summer_bill"],
        sewer_charge_cents=7320,
        total_charge_cents=44939,
        adjusted_total_cents=44939,
    )
    assertions.assert_bill_charges(
        ctx["winter_bill"],
        sewer_charge_cents=7320,
        total_charge_cents=40800,
        adjusted_total_cents=40800,
    )
    assert (
        ctx["summer_bill"]["sewer_charge_cents"]
        == ctx["winter_bill"]["sewer_charge_cents"]
    )


def test_generated_bill_without_baseline_history_stays_draft_and_unbilled(api):
    """PRD §3.2: "If fewer than three candidates exist, `seasonal_baseline_gallons` is null and `baseline_sample_count` records how many were found; otherwise `baseline_sample_count` is 3 and `seasonal_baseline_gallons` is the sum of the sample's `consumption_gallons` divided by three, rounded half up to a whole gallon."

    PRD §3.2: "When `seasonal_baseline_gallons` is null or zero, `anomaly_ratio` is null and `anomaly_flag` is false."

    PRD §3.2: "A newly generated bill sits in `DRAFT` with `rebill_of_bill_id` null and writes nothing to the ledger."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_tiered_water_charge_nested_clamp_seasonal_branch
    """
    ctx = _seasonal_pair(api)

    for bill in (ctx["summer_bill"], ctx["winter_bill"]):
        assertions.assert_null_fields(
            bill, "seasonal_baseline_gallons", "anomaly_ratio", "rebill_of_bill_id"
        )
        assertions.assert_fields(bill, anomaly_flag=False, billing_status="DRAFT")

    for account_id in (ctx["summer_account_id"], ctx["winter_account_id"]):
        entries = assertions.ledger_entries(api, account_id, SUPERVISOR_HEADERS)
        assert entries == []
        assertions.assert_account_state(
            fixtures.fetch_account(api, account_id), balance_cents=0
        )


# ===========================================================================
# The instalment schedule: floor once, then push the remainder to the final
# ===========================================================================
def test_installment_schedule_pushes_the_whole_remainder_onto_the_final_instalment(api):
    """PRD §3.8: "`installment_cents` is the financed amount divided by `installment_count`, taking the floor — the largest whole number of cents not exceeding the quotient — and it applies to every instalment from the first through the second-to-last."

    PRD §3.8: "The remainder is the financed amount minus `installment_cents` multiplied by `installment_count`, and `final_installment_cents` is `installment_cents` plus that entire remainder."

    PRD §3.8: "`installment_cents` multiplied by one less than `installment_count`, plus `final_installment_cents`, therefore equals the financed amount exactly; rounding each instalment independently and summing would not reconcile."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_b_installment_floor_then_remainder_to_final
    """
    ctx = fixtures.baselined_bill(api, target_gallons=TARGET_GALLONS)
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_bill_charges(bill, adjusted_total_cents=TARGET_TOTAL_CENTS)

    arrangement = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        TARGET_TOTAL_CENTS,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=12,
        down_payment_cents=9000,
    )

    assertions.assert_fields(
        arrangement,
        total_amount_cents=TARGET_TOTAL_CENTS,
        down_payment_cents=9000,
        installment_count=12,
        installment_cents=2994,
        final_installment_cents=3005,
    )
    financed = TARGET_TOTAL_CENTS - 9000
    assert financed == 35939
    assert (
        arrangement["installment_cents"] * 11 + arrangement["final_installment_cents"]
        == financed
    )


def test_proposing_a_plan_moves_no_money_and_leaves_the_account_past_due(api):
    """PRD §3.8: "A new plan opens in `PROPOSED` with `paid_installment_count`, `missed_payment_count` and `reinstatement_count` all zero, and any other arrangement on the same account sitting in `PROPOSED` or `ACTIVE` is moved to the terminal `CANCELLED`, which stops it counting toward the account's `credit_status` and therefore triggers a recompute."

    PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_b_installment_floor_then_remainder_to_final
    """
    ctx = fixtures.baselined_bill(api, target_gallons=TARGET_GALLONS)

    arrangement = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        TARGET_TOTAL_CENTS,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=12,
        down_payment_cents=9000,
    )
    assertions.assert_fields(
        arrangement,
        status="PROPOSED",
        paid_installment_count=0,
        missed_payment_count=0,
        reinstatement_count=0,
    )

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_no_entry_of_kind(entries, "ARRANGEMENT_DOWN_PAYMENT")
    assertions.assert_no_entry_of_kind(entries, "ARRANGEMENT_INSTALLMENT")

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=ISSUED_BALANCE_CENTS, credit_status="PAST_DUE"
    )
    assertions.assert_balance_is_ledger_sum(account, entries)
    assertions.assert_fields(
        fixtures.fetch_arrangement(api, arrangement["id"]), status="PROPOSED"
    )


# ===========================================================================
# The credit cap is consulted before the administrative-fee waiver
# ===========================================================================
def test_capped_credit_below_the_waiver_threshold_still_attracts_the_admin_fee(api):
    """PRD §3.6: "When `capped_credit_cents` is greater than or equal to the rate schedule's `admin_fee_waiver_threshold_cents`, `admin_fee_charged_cents` is zero."

    PRD §3.6: "Steps four and five are order-sensitive: because the waiver is decided on the capped figure rather than the gross figure, a gross credit that sat above the waiver threshold but is pushed below it by the cap still attracts the fee."

    PRD §3.6: "Otherwise `admin_fee_charged_cents` is the lesser of `admin_fee_cents` and `capped_credit_cents`, so the fee can never exceed the credit it is deducted from."

    PRD §3.6: "Every division in these six steps is rounded half up at the step in which it appears, and every quantity is a whole number of cents or gallons."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_c_credit_cap_applied_before_admin_fee_waiver
    """
    ctx = fixtures.determined_case(
        api,
        leak_type="SERVICE_LINE",
        leak_determination="CUSTOMER_SIDE_LEAK",
        target_gallons=12000,
    )

    adjustment = fixtures.draft_adjustment(
        api,
        ctx["investigation_id"],
        ctx["bill_id"],
        "SERVICE_LINE",
        ctx["investigation_version"],
        ctx["rep_headers"],
    )

    assertions.assert_credit_breakdown(
        adjustment,
        gross_credit_cents=10047,
        capped_credit_cents=9154,
        admin_fee_charged_cents=1500,
        net_credit_cents=7654,
    )
    assert adjustment["gross_credit_cents"] > 10000
    assert adjustment["capped_credit_cents"] < 10000


def test_proportional_cap_binds_at_sixty_percent_of_the_bill(api):
    """PRD §3.6: "`cap_cents` is the tighter of a proportional cap and an absolute cap: the proportional cap is `total_charge_cents` multiplied by six thousand basis points and divided by ten thousand — that is, sixty percent of the bill — rounded half up to whole cents, and the absolute cap is 50,000 cents (five hundred dollars); `cap_cents` is the lesser of the two."

    PRD §3.6: "`capped_credit_cents` is the lesser of `gross_credit_cents` and `cap_cents`, and `cap_applied` is true exactly when `capped_credit_cents` is less than `gross_credit_cents`."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_c_credit_cap_applied_before_admin_fee_waiver
    """
    ctx = fixtures.determined_case(
        api,
        leak_type="SERVICE_LINE",
        leak_determination="CUSTOMER_SIDE_LEAK",
        target_gallons=12000,
    )

    adjustment = fixtures.draft_adjustment(
        api,
        ctx["investigation_id"],
        ctx["bill_id"],
        "SERVICE_LINE",
        ctx["investigation_version"],
        ctx["rep_headers"],
    )

    assertions.assert_credit_breakdown(
        adjustment,
        variant_applied="BASELINE_REBILL",
        excess_gallons=8000,
        water_credit_cents=5167,
        sewer_relief_gallons=8000,
        sewer_credit_cents=4880,
        cap_cents=9154,
        cap_applied=True,
    )
    assert (
        adjustment["water_credit_cents"] + adjustment["sewer_credit_cents"]
        == adjustment["gross_credit_cents"]
    )


def test_twelve_thousand_gallon_summer_bill_is_flagged_at_three_times_its_baseline(api):
    """PRD §3.2: "Otherwise `anomaly_ratio` is `consumption_gallons` divided by `seasonal_baseline_gallons`, rounded half up to three decimal places, and `anomaly_flag` is true when that rounded ratio is greater than or equal to 2.000."

    PRD §3.2: "Step one caps: the capped volume is the lesser of `consumption_gallons` and `sewer_cap_gallons`."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_c_credit_cap_applied_before_admin_fee_waiver
    """
    ctx = fixtures.determined_case(
        api,
        leak_type="SERVICE_LINE",
        leak_determination="CUSTOMER_SIDE_LEAK",
        target_gallons=12000,
    )

    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_bill_charges(
        bill,
        consumption_gallons=12000,
        water_charge_cents=7937,
        sewer_charge_cents=7320,
        total_charge_cents=15257,
    )
    assertions.assert_fields(
        bill,
        seasonal_baseline_gallons=BASELINE_GALLONS,
        anomaly_flag=True,
    )
    assert bill["anomaly_ratio"] == pytest.approx(3.0, abs=1e-9)
