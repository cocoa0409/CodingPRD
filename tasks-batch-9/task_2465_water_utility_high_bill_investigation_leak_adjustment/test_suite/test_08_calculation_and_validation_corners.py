"""Charge arithmetic at its boundaries and the refusals that guard the money.

The suites here walk the priced edges of a water bill and the rules that stop a
wrong figure from settling: the sewer cap binding exactly on its own limit, the
seasonal-baseline sample set admitting only settled same-season reads, the
half-cent tie inside the summer tier-three line, the dual-variant credit
preview that prices without persisting, the instalment plan's default and
reinstatement ceilings, the per-period rebilling deadline on both sides of its
edge, the statutory appeal-filing window, the board's daily docket capacity,
the estimated read that suppresses an irrigation credit, and the two ways a
mis-paired identifier is refused.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLERK_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    assertions,
    fixtures,
    make_customer_headers,
)

# The standard tariff prices a 4,000-gallon SUMMER period at 5,210 cents and a
# 41,000-gallon SUMMER period at 44,939 cents.
SMALL_PERIOD_TOTAL_CENTS = 5210
LARGE_PERIOD_TOTAL_CENTS = 44939
LARGE_PERIOD_WATER_CENTS = 37619
BASELINED_BILL_BALANCE_CENTS = 60569


# ===========================================================================
# Shared estates
# ===========================================================================
def _baseline_filter_estate(api):
    """Six periods on one meter with mixed bill status and mixed season."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    periods = {}
    for code, start, end, season, deadline in (
        ("2025-06", "2025-06-01", "2025-06-30", "SUMMER", "2026-12-31"),
        ("2025-07", "2025-07-01", "2025-07-31", "SUMMER", "2026-12-31"),
        ("2025-08", "2025-08-01", "2025-08-31", "SUMMER", "2026-12-31"),
        ("2026-01", "2026-01-01", "2026-01-31", "WINTER", "2027-01-31"),
        ("2026-07", "2026-07-01", "2026-07-31", "SUMMER", "2027-01-31"),
        ("2026-08", "2026-08-01", "2026-08-31", "SUMMER", "2027-02-28"),
    ):
        periods[code] = fixtures.create_billing_period(
            api,
            period_code=code,
            start_date=start,
            end_date=end,
            season=season,
            rebilling_deadline_date=deadline,
        )
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=100000
    )
    for read_date, value in (
        ("2025-05-31", 100000),
        ("2025-06-30", 104000),
        ("2025-07-31", 108000),
        ("2025-08-31", 112000),
        ("2026-01-31", 132000),
        ("2026-07-31", 173000),
    ):
        fixtures.post_reading(api, meter["id"], read_date, value)

    bills = {}
    for code in ("2025-06", "2025-07"):
        bills[code] = fixtures.generate_and_issue_bill(
            api, account["id"], periods[code]["id"], meter["id"]
        )
    # Left in DRAFT on purpose: an unsettled bill is outside the sample pool.
    bills["2025-08"] = fixtures.generate_bill(
        api, account["id"], periods["2025-08"]["id"], meter["id"]
    )
    for code in ("2026-01", "2026-07"):
        bills[code] = fixtures.generate_and_issue_bill(
            api, account["id"], periods[code]["id"], meter["id"]
        )
    return {"periods": periods, "account": account, "meter": meter, "bills": bills}


def _six_installment_plan(api):
    """One 5,210-cent bill financed over six instalments and activated."""
    ctx = fixtures.metered_account(api)
    period_id = ctx["calendar"]["history_ids"][0]
    fixtures.post_reading(api, ctx["meter_id"], "2025-05-31", 100000)
    fixtures.post_reading(api, ctx["meter_id"], "2025-06-30", 104000)
    bill = fixtures.generate_and_issue_bill(
        api, ctx["account_id"], period_id, ctx["meter_id"]
    )
    assert bill["adjusted_total_cents"] == SMALL_PERIOD_TOTAL_CENTS
    arrangement = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        bill["id"],
        SMALL_PERIOD_TOTAL_CENTS,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=6,
        down_payment_cents=1042,
    )
    arrangement = validate_success(
        api.activate_payment_arrangement(arrangement["id"], CSR_HEADERS)
    )
    ctx.update(
        {
            "bill": bill,
            "bill_id": bill["id"],
            "arrangement": arrangement,
            "arrangement_id": arrangement["id"],
        }
    )
    return ctx


def _bill_pending_rebill_inside_the_window(api):
    """A 4,000-gallon bill restated to 3,000 gallons while the window is open."""
    ctx = fixtures.metered_account(api)
    period_id = ctx["calendar"]["history_ids"][0]
    fixtures.post_reading(api, ctx["meter_id"], "2025-05-31", 100000)
    period_end_read = fixtures.post_reading(api, ctx["meter_id"], "2025-06-30", 104000)
    bill = fixtures.generate_and_issue_bill(
        api, ctx["account_id"], period_id, ctx["meter_id"]
    )
    fixtures.post_corrected_reading(
        api, ctx["meter_id"], "2025-06-30", 103000, period_end_read["id"]
    )
    ctx.update({"bill": fixtures.fetch_bill(api, bill["id"]), "bill_id": bill["id"]})
    assert ctx["bill"]["billing_status"] == "REBILL_PENDING"
    return ctx


def _four_appeals_awaiting_a_docket(api):
    """Seven settled 4,000-gallon bills and four appeals filed on the same day."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period_specs = (
        ("2025-04", "2025-04-01", "2025-04-30"),
        ("2025-05", "2025-05-01", "2025-05-31"),
        ("2025-06", "2025-06-01", "2025-06-30"),
        ("2025-07", "2025-07-01", "2025-07-31"),
        ("2025-08", "2025-08-01", "2025-08-31"),
        ("2025-09", "2025-09-01", "2025-09-30"),
        ("2025-10", "2025-10-01", "2025-10-31"),
    )
    periods = [
        fixtures.create_billing_period(
            api,
            period_code=code,
            start_date=start,
            end_date=end,
            season="SUMMER",
            rebilling_deadline_date="2026-12-31",
        )
        for code, start, end in period_specs
    ]
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=100000
    )
    fixtures.post_reading(api, meter["id"], "2025-03-31", 100000)
    register = 100000
    for _code, _start, end in period_specs:
        register += 4000
        fixtures.post_reading(api, meter["id"], end, register)

    bills = [
        fixtures.generate_and_issue_bill(api, account["id"], period["id"], meter["id"])
        for period in periods
    ]
    appeals = []
    for bill in bills[3:]:
        assert bill["seasonal_baseline_gallons"] == 4000
        investigation = fixtures.open_investigation(api, bill["id"], CSR_HEADERS)
        validate_success(
            api.close_investigation_no_adjustment(
                investigation["id"], CSR_HEADERS, {"note": "no evidence supplied"}
            )
        )
        appeals.append(fixtures.file_appeal(api, investigation["id"], CSR_HEADERS))
    return {"account": account, "bills": bills, "appeals": appeals}


def _two_accounts_with_their_own_master_meters(api, read_meter_a=True):
    """Two accounts, each with a fully read POTABLE_MASTER meter of its own."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(
        api,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
        rebilling_deadline_date="2026-12-31",
    )
    account_a = fixtures.create_account(api, schedule["id"])
    account_b = fixtures.create_account(api, schedule["id"])
    meter_a = fixtures.create_master_meter(
        api, account_a["id"], initial_register_value=100000
    )
    meter_b = fixtures.create_master_meter(
        api, account_b["id"], initial_register_value=200000
    )
    if read_meter_a:
        fixtures.post_reading(api, meter_a["id"], "2025-05-31", 100000)
        fixtures.post_reading(api, meter_a["id"], "2025-06-30", 104000)
    fixtures.post_reading(api, meter_b["id"], "2025-05-31", 200000)
    fixtures.post_reading(api, meter_b["id"], "2025-06-30", 204000)
    return {
        "period": period,
        "account_a": account_a,
        "account_b": account_b,
        "meter_a": meter_a,
        "meter_b": meter_b,
    }


# ===========================================================================
# The sewer cap binding exactly on its own limit
# ===========================================================================
def test_sewer_cap_bills_the_full_twelve_thousand_gallons_at_the_limit(api):
    """PRD §3.2: "Step one caps: the capped volume is the lesser of `consumption_gallons` and `sewer_cap_gallons`."

    PRD §3.2: "`sewer_charge_cents` is `sewer_billable_gallons` multiplied by `sewer_rate_cents_per_kgal`, divided by one thousand, rounded half up once on that final product."

    PRD §3.2: "Line three depends on the period's `season`: in `WINTER` it is the third-tier volume multiplied by `tier3_rate_cents_per_kgal`, divided by one thousand, rounded half up; in `SUMMER` the surcharge is folded in *before* the rounding, so line three is the third-tier volume multiplied by `tier3_rate_cents_per_kgal`, multiplied by ten thousand plus `summer_surcharge_bp`, divided by one thousand and then by ten thousand, and only then rounded half up."

    PRD §3.2: "`total_charge_cents` is `water_charge_cents` plus `sewer_charge_cents`, and at generation time `adjusted_total_cents` equals `total_charge_cents` because no credit has been posted."

    Design: Corner/calculations/corner_calc_correct_result_sewer_cap_binds_exactly_at_twelve_thousand_gallons
    """
    ctx = fixtures.metered_account(api)
    period_id = ctx["calendar"]["history_ids"][0]
    fixtures.post_reading(api, ctx["meter_id"], "2025-05-31", 100000)
    fixtures.post_reading(api, ctx["meter_id"], "2025-06-30", 112000)

    bill = fixtures.generate_bill(api, ctx["account_id"], period_id, ctx["meter_id"])

    assertions.assert_fields(
        bill,
        consumption_gallons=12000,
        submeter_credit_gallons=0,
        sewer_billable_gallons=12000,
    )
    assertions.assert_bill_charges(
        bill,
        consumption_gallons=12000,
        water_charge_cents=7937,
        sewer_charge_cents=7320,
        total_charge_cents=15257,
        adjusted_total_cents=15257,
    )


def test_generating_a_bill_leaves_it_in_draft_with_no_ledger_movement(api):
    """PRD §3.2: "A newly generated bill sits in `DRAFT` with `rebill_of_bill_id` null and writes nothing to the ledger."

    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Corner/calculations/corner_calc_correct_result_sewer_cap_binds_exactly_at_twelve_thousand_gallons
    """
    ctx = fixtures.metered_account(api)
    period_id = ctx["calendar"]["history_ids"][0]
    fixtures.post_reading(api, ctx["meter_id"], "2025-05-31", 100000)
    fixtures.post_reading(api, ctx["meter_id"], "2025-06-30", 112000)

    bill = fixtures.generate_bill(api, ctx["account_id"], period_id, ctx["meter_id"])

    assertions.assert_fields(bill, billing_status="DRAFT")
    assertions.assert_null_fields(bill, "rebill_of_bill_id")
    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assert entries == []
    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=0, credit_status="CURRENT", service_status="ACTIVE"
    )
    assertions.assert_balance_is_ledger_sum(account, entries)


# ===========================================================================
# Which bills the seasonal baseline is allowed to average
# ===========================================================================
def test_baseline_excludes_draft_and_cross_season_bills_and_blocks_the_dispute(api):
    """PRD §3.2: "The candidate pool is every other bill on the same `account_id` and the same `meter_id` whose period has the same `season` as the target's period, whose period's `end_date` is earlier than the target period's `start_date`, whose `billing_status` is `ISSUED`, `ADJUSTED` or `UPHELD_AS_BILLED`, whose `anomaly_flag` is false, and whose `estimated_flag` is false."

    PRD §3.2: "If fewer than three candidates exist, `seasonal_baseline_gallons` is null and `baseline_sample_count` records how many were found; otherwise `baseline_sample_count` is 3 and `seasonal_baseline_gallons` is the sum of the sample's `consumption_gallons` divided by three, rounded half up to a whole gallon."

    PRD §3.2: "When `seasonal_baseline_gallons` is null or zero, `anomaly_ratio` is null and `anomaly_flag` is false."

    PRD §3.3: "And the bill must have a computed baseline — an investigation cannot proceed against a bill whose `seasonal_baseline_gallons` is null, because there would be nothing to compare consumption against and nothing to reprice a credit from, so the request is refused with `ERR_INSUFFICIENT_BASELINE_HISTORY`."

    Design: Corner/calculations/corner_calc_input_set_filtering_baseline_admits_only_settled_same_season_bills
    """
    estate = _baseline_filter_estate(api)
    target = fixtures.fetch_bill(api, estate["bills"]["2026-07"]["id"])

    assertions.assert_fields(
        target,
        consumption_gallons=41000,
        baseline_sample_count=2,
        seasonal_baseline_gallons=None,
        anomaly_ratio=None,
        anomaly_flag=False,
    )

    validate_error(
        api.create_investigation(
            {"bill_id": target["id"], "reported_cause": "bill ten times normal"},
            CSR_HEADERS,
        ),
        "ERR_INSUFFICIENT_BASELINE_HISTORY",
    )

    rows, meta = validate_paginated(
        api.list_investigations(CSR_HEADERS, {"bill_id": target["id"]})
    )
    assert rows == []
    assertions.assert_pagination_meta(meta, total_count=0)
    assertions.assert_fields(
        fixtures.fetch_bill(api, target["id"]), billing_status="ISSUED"
    )


def test_baseline_averages_the_three_most_recent_settled_same_season_bills(api):
    """PRD §3.2: "A bill's `seasonal_baseline_gallons` is the mean consumption of the three most recent same-season historical bills for the same meter."

    PRD §3.2: "Candidates are ordered by their period's `end_date` descending with `created_at` descending as the tie-break, and the first three form the sample."

    PRD §3.2: "Otherwise `anomaly_ratio` is `consumption_gallons` divided by `seasonal_baseline_gallons`, rounded half up to three decimal places, and `anomaly_flag` is true when that rounded ratio is greater than or equal to 2.000."

    Design: Corner/calculations/corner_calc_input_set_filtering_baseline_admits_only_settled_same_season_bills
    """
    estate = _baseline_filter_estate(api)
    fixtures.issue_bill(api, estate["bills"]["2025-08"]["id"])

    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    fixtures.post_reading(api, estate["meter"]["id"], "2026-08-31", 177000)
    later = fixtures.generate_bill(
        api,
        estate["account"]["id"],
        estate["periods"]["2026-08"]["id"],
        estate["meter"]["id"],
    )

    # The survivors are 2026-07 (41000), 2025-08 (4000) and 2025-07 (4000);
    # the older 2025-06 bill and the WINTER 2026-01 bill are both out.
    assertions.assert_fields(
        later,
        consumption_gallons=4000,
        baseline_sample_count=3,
        seasonal_baseline_gallons=16333,
        anomaly_flag=False,
    )
    assert abs(float(later["anomaly_ratio"]) - 0.245) < 1e-9


# ===========================================================================
# The instalment schedule and the two plan ceilings
# ===========================================================================
def test_installment_schedule_floors_and_one_late_payment_leaves_the_plan_active(api):
    """PRD §3.8: "`installment_cents` is the financed amount divided by `installment_count`, taking the floor — the largest whole number of cents not exceeding the quotient — and it applies to every instalment from the first through the second-to-last."

    PRD §3.8: "The remainder is the financed amount minus `installment_cents` multiplied by `installment_count`, and `final_installment_cents` is `installment_cents` plus that entire remainder."

    PRD §3.8: "When `missed_payment_count` reaches two the plan moves from `ACTIVE` to `DEFAULTED` and `credit_status` becomes `ARRANGEMENT_DEFAULTED`, which re-enables shutoff scheduling."

    Design: Corner/calculations/corner_calc_constants_applied_default_and_reinstatement_limits_come_from_the_constants
    """
    ctx = _six_installment_plan(api)

    assertions.assert_fields(
        ctx["arrangement"],
        status="ACTIVE",
        installment_count=6,
        down_payment_cents=1042,
        installment_cents=694,
        final_installment_cents=698,
        paid_installment_count=0,
        missed_payment_count=0,
        reinstatement_count=0,
    )
    assert 1042 + 5 * 694 + 698 == SMALL_PERIOD_TOTAL_CENTS

    after_one = fixtures.record_installment(api, ctx["arrangement_id"], 694, on_time=False)
    assertions.assert_fields(
        after_one, status="ACTIVE", paid_installment_count=1, missed_payment_count=1
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        balance_cents=SMALL_PERIOD_TOTAL_CENTS - 1042 - 694,
        credit_status="IN_ARRANGEMENT",
    )

    after_two = fixtures.record_installment(api, ctx["arrangement_id"], 694, on_time=False)
    assertions.assert_fields(
        after_two, status="DEFAULTED", paid_installment_count=2, missed_payment_count=2
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        balance_cents=SMALL_PERIOD_TOTAL_CENTS - 1042 - 2 * 694,
        credit_status="ARRANGEMENT_DEFAULTED",
    )


def test_a_defaulted_plan_is_reinstated_once_and_the_second_attempt_is_refused(api):
    """PRD §3.8: "A defaulted plan may be reinstated once and only once by a supervisor."

    PRD §3.8: "Reinstatement is available only from `DEFAULTED` and is refused with `ERR_REINSTATEMENT_LIMIT` when `reinstatement_count` has already reached one."

    PRD §3.8: "It returns the plan to `ACTIVE`, increases `reinstatement_count` by one, resets `missed_payment_count` to zero, restores `credit_status` to `IN_ARRANGEMENT`, and then recomputes `service_status`."

    Design: Corner/calculations/corner_calc_constants_applied_default_and_reinstatement_limits_come_from_the_constants
    """
    ctx = _six_installment_plan(api)
    for _ in range(2):
        fixtures.record_installment(api, ctx["arrangement_id"], 694, on_time=False)

    reinstated = validate_success(
        api.reinstate_payment_arrangement(ctx["arrangement_id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_fields(
        reinstated, status="ACTIVE", reinstatement_count=1, missed_payment_count=0
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), credit_status="IN_ARRANGEMENT"
    )

    for _ in range(2):
        fixtures.record_installment(api, ctx["arrangement_id"], 694, on_time=False)
    # Four instalments are still short of the six the plan carries, so the
    # plan defaults again rather than completing.
    assertions.assert_fields(
        fixtures.fetch_arrangement(api, ctx["arrangement_id"]),
        status="DEFAULTED",
        paid_installment_count=4,
        missed_payment_count=2,
    )

    validate_error(
        api.reinstate_payment_arrangement(ctx["arrangement_id"], SUPERVISOR_HEADERS),
        "ERR_REINSTATEMENT_LIMIT",
    )

    assertions.assert_fields(
        fixtures.fetch_arrangement(api, ctx["arrangement_id"]),
        status="DEFAULTED",
        reinstatement_count=1,
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        balance_cents=SMALL_PERIOD_TOTAL_CENTS - 1042 - 4 * 694,
        credit_status="ARRANGEMENT_DEFAULTED",
    )


# ===========================================================================
# The half-cent tie inside the summer tier-three line
# ===========================================================================
def test_summer_tier_three_line_rounds_an_exact_half_cent_away_from_zero(api):
    """PRD §2.5: "Wherever a division or a rate multiplication produces a fraction, the result is rounded **half up** — a value exactly on the halfway mark rounds away from zero — and the rounding happens at the step in which the division appears, not at the end of the calculation."

    PRD §2.5: "In the tiered water charge, each tier line is rounded to whole cents independently and the rounded lines are then summed; rounding a single grand total instead produces a different answer."

    PRD §3.2: "Rounding each line independently before the sum is mandatory; producing one unrounded grand total and rounding that instead yields a different answer, and the surcharge never touches lines one or two."

    Design: Corner/calculations/corner_calc_precision_tier_three_surcharge_line_lands_on_an_exact_half_cent
    """
    ctx = fixtures.metered_account(api)
    tie_period_id = ctx["calendar"]["history_ids"][0]
    plain_period_id = ctx["calendar"]["history_ids"][1]
    fixtures.post_reading(api, ctx["meter_id"], "2025-05-31", 100000)
    fixtures.post_reading(api, ctx["meter_id"], "2025-06-30", 141000)
    fixtures.post_reading(api, ctx["meter_id"], "2025-07-31", 181204)

    tie = fixtures.generate_bill(api, ctx["account_id"], tie_period_id, ctx["meter_id"])
    plain = fixtures.generate_bill(
        api, ctx["account_id"], plain_period_id, ctx["meter_id"]
    )

    # 31000 * 890 * 11500 / 10000000 is exactly 31728.5 cents.
    assertions.assert_bill_charges(
        tie,
        consumption_gallons=41000,
        water_charge_cents=LARGE_PERIOD_WATER_CENTS,
        sewer_charge_cents=7320,
        total_charge_cents=LARGE_PERIOD_TOTAL_CENTS,
    )
    assert tie["water_charge_cents"] != 37618, "half-even or truncation would give 37618"
    assert tie["total_charge_cents"] != 44938

    # 30204 * 890 * 11500 / 10000000 is 30913.794, where every rule agrees.
    assertions.assert_bill_charges(
        plain,
        consumption_gallons=40204,
        water_charge_cents=36804,
        sewer_charge_cents=7320,
        total_charge_cents=44124,
    )


# ===========================================================================
# The read-only dual-variant credit preview
# ===========================================================================
def test_preview_prices_both_variants_for_each_assumed_leak_type(api):
    """PRD §3.6: "The preview runs the credit calculation twice on the same bill — once forced to `EXCESS_REPRICE` and once forced to `BASELINE_REBILL` — and returns `bill_id`, the echoed `assumed_leak_type`, a `recommended_variant` naming the variant the credit rule would actually select for that leak type, the `excess_gallons`, an `excess_reprice_net_cents`, a `baseline_rebill_net_cents`, and a `variant_delta_cents` equal to the baseline-rebill net minus the excess-reprice net."

    PRD §3.6: "Relief is granted only for leak types whose water did not reach the sewer, namely `SERVICE_LINE`, `UNDERGROUND`, `IRRIGATION` and `POOL`; `TOILET` is deliberately excluded because toilet water does discharge to the sewer."

    Design: Corner/calculations/corner_calc_forward_looking_preview_prices_both_variants_and_persists_nothing
    """
    ctx = fixtures.baselined_bill(api, target_gallons=41000)
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]),
        consumption_gallons=41000,
        seasonal_baseline_gallons=4000,
        total_charge_cents=LARGE_PERIOD_TOTAL_CENTS,
    )

    buried = validate_success(
        api.get_adjustment_preview(
            ctx["bill_id"], CSR_HEADERS, {"assumed_leak_type": "SERVICE_LINE"}
        )
    )
    assertions.assert_fields(
        buried,
        bill_id=ctx["bill_id"],
        assumed_leak_type="SERVICE_LINE",
        excess_gallons=37000,
        excess_reprice_net_cents=26779,
        baseline_rebill_net_cents=26963,
        variant_delta_cents=184,
        recommended_variant="BASELINE_REBILL",
    )

    fixture_leak = validate_success(
        api.get_adjustment_preview(
            ctx["bill_id"], SUPERVISOR_HEADERS, {"assumed_leak_type": "TOILET"}
        )
    )
    assertions.assert_fields(
        fixture_leak,
        bill_id=ctx["bill_id"],
        assumed_leak_type="TOILET",
        excess_gallons=37000,
        excess_reprice_net_cents=21899,
        baseline_rebill_net_cents=26963,
        variant_delta_cents=5064,
        recommended_variant="EXCESS_REPRICE",
    )
    assert (
        fixture_leak["excess_reprice_net_cents"] != buried["excess_reprice_net_cents"]
    ), "the same bill must reprice differently once sewer relief is withheld"


def test_preview_creates_no_adjustment_and_writes_no_ledger_entry(api):
    """PRD §3.6: "The preview creates no `LeakAdjustment` row and writes no ledger entry, and it recomputes from scratch on every call, so a rebill landing between two previews changes the answer."

    PRD §3.2: "Issuing moves the bill from `DRAFT` to `ISSUED` and is permitted while the period is `OPEN` or `CLOSED`."

    Design: Corner/calculations/corner_calc_forward_looking_preview_prices_both_variants_and_persists_nothing
    """
    ctx = fixtures.baselined_bill(api, target_gallons=41000)

    for leak_type, headers in (
        ("SERVICE_LINE", CSR_HEADERS),
        ("TOILET", SUPERVISOR_HEADERS),
    ):
        validate_success(
            api.get_adjustment_preview(
                ctx["bill_id"], headers, {"assumed_leak_type": leak_type}
            )
        )

    rows, meta = validate_paginated(
        api.list_leak_adjustments(CSR_HEADERS, {"bill_id": ctx["bill_id"]})
    )
    assert rows == []
    assertions.assert_pagination_meta(meta, total_count=0)

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"] * 4)
    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=BASELINED_BILL_BALANCE_CENTS
    )
    assertions.assert_balance_is_ledger_sum(account, entries)
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]),
        billing_status="ISSUED",
        total_charge_cents=LARGE_PERIOD_TOTAL_CENTS,
        adjusted_total_cents=LARGE_PERIOD_TOTAL_CENTS,
    )


# ===========================================================================
# The per-period rebilling deadline, on both sides of its edge
# ===========================================================================
def test_rebill_past_the_period_deadline_is_refused_and_moves_no_money(api):
    """PRD §3.5: "The operation is available only from `REBILL_PENDING`, is refused with `ERR_BILLING_PERIOD_LOCKED` when the period is `LOCKED`, and is refused with `ERR_REBILL_WINDOW_EXPIRED` when today's date on the logical clock is later than the period's `rebilling_deadline_date` — the deadline day itself is still inside the window."

    PRD §3.5: "Entering `REBILL_PENDING` recomputes `consumption_gallons`, `water_charge_cents`, `submeter_credit_gallons`, `sewer_billable_gallons`, `sewer_charge_cents` and `total_charge_cents` from the live reads, and increments the account's `open_rebill_count`, which is what drives the `SHUTOFF_SCHEDULED` to `SHUTOFF_HELD` protection."

    Design: Corner/validations/corner_validation_violation_to_error_rebill_after_the_period_deadline_is_refused
    """
    # The correction itself is posted while the window is still open; only the
    # rebill attempt happens after the deadline day.
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(
        api,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
        rebilling_deadline_date="2026-06-30",
    )
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=100000
    )
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    period_end_read = fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)
    bill = fixtures.generate_and_issue_bill(
        api, account["id"], period["id"], meter["id"]
    )
    fixtures.post_corrected_reading(
        api, meter["id"], "2025-06-30", 103000, period_end_read["id"]
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, bill["id"]), billing_status="REBILL_PENDING"
    )

    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    validate_error(
        api.rebill_bill(bill["id"], SUPERVISOR_HEADERS), "ERR_REBILL_WINDOW_EXPIRED"
    )

    pending = fixtures.fetch_bill(api, bill["id"])
    assertions.assert_fields(
        pending, billing_status="REBILL_PENDING", sewer_billable_gallons=3000
    )
    assertions.assert_bill_charges(
        pending,
        consumption_gallons=3000,
        water_charge_cents=2250,
        sewer_charge_cents=1830,
        total_charge_cents=4080,
    )

    entries = assertions.ledger_entries(api, account["id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"])
    assertions.assert_single_entry(
        entries, "BILL_CHARGE", amount_cents=SMALL_PERIOD_TOTAL_CENTS
    )
    assertions.assert_no_entry_of_kind(entries, "REBILL_REVERSAL")
    assertions.assert_no_entry_of_kind(entries, "REBILL_CHARGE")
    assertions.assert_account_state(
        fixtures.fetch_account(api, account["id"]),
        balance_cents=SMALL_PERIOD_TOTAL_CENTS,
        open_rebill_count=1,
    )

    bills, meta = validate_paginated(
        api.list_bills(SUPERVISOR_HEADERS, {"account_id": account["id"]})
    )
    assert len(bills) == 1
    assertions.assert_pagination_meta(meta, total_count=1)


def test_rebill_inside_the_window_supersedes_the_bill_with_an_issued_replacement(api):
    """PRD §3.5: "The superseded bill moves from `REBILL_PENDING` to the terminal `REBILLED`."

    PRD §3.5: "A replacement bill is created carrying the superseded bill's `account_id`, `period_id`, `meter_id`, recomputed `consumption_gallons` and copied `read_type`, with `rebill_of_bill_id` naming the superseded bill; it is created in `DRAFT` and then immediately auto-advanced to `ISSUED` inside the same request."

    PRD §4: "Action endpoints return the resource they acted upon, with the single exception of the rebill action, which returns the newly created replacement bill rather than the superseded one."

    Design: Corner/validations/corner_validation_satisfaction_to_pass_rebill_inside_the_window_replaces_the_bill
    """
    ctx = _bill_pending_rebill_inside_the_window(api)

    replacement = validate_success(api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS))

    assert replacement["id"] != ctx["bill_id"]
    assertions.assert_fields(
        replacement,
        rebill_of_bill_id=ctx["bill_id"],
        billing_status="ISSUED",
        account_id=ctx["account_id"],
        meter_id=ctx["meter_id"],
    )
    assertions.assert_bill_charges(
        replacement, consumption_gallons=3000, total_charge_cents=4080
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="REBILLED"
    )

    bills, meta = validate_paginated(
        api.list_bills(SUPERVISOR_HEADERS, {"account_id": ctx["account_id"]})
    )
    assert len(bills) == 2
    assertions.assert_pagination_meta(meta, total_count=2)


def test_rebill_writes_a_reversal_then_a_replacement_charge_and_clears_the_hold(api):
    """PRD §3.5: "Two ledger entries land: a `REVERSAL` with `source_kind` `REBILL_REVERSAL` whose `amount_cents` is the negative of the sum of the superseded bill's `BILL_CHARGE` and `REBILL_CHARGE` entries, and then — from the replacement's auto-issue — a `CHARGE` with `source_kind` `REBILL_CHARGE` for the positive `total_charge_cents` of the replacement."

    PRD §3.5: "The account's `open_rebill_count` decreases by one, which may return `service_status` from `SHUTOFF_HELD` to `SHUTOFF_SCHEDULED` or, if collections have caught up, to `ACTIVE`; `balance_cents`, `credit_status` and `service_status` are recomputed in that order."

    Design: Corner/validations/corner_validation_satisfaction_to_pass_rebill_inside_the_window_replaces_the_bill
    """
    ctx = _bill_pending_rebill_inside_the_window(api)

    validate_success(api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS))

    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(
        entries, ["BILL_CHARGE", "REBILL_REVERSAL", "REBILL_CHARGE"]
    )
    assertions.assert_single_entry(
        entries,
        "BILL_CHARGE",
        entry_type="CHARGE",
        amount_cents=SMALL_PERIOD_TOTAL_CENTS,
    )
    assertions.assert_single_entry(
        entries,
        "REBILL_REVERSAL",
        entry_type="REVERSAL",
        amount_cents=-SMALL_PERIOD_TOTAL_CENTS,
    )
    assertions.assert_single_entry(
        entries, "REBILL_CHARGE", entry_type="CHARGE", amount_cents=4080
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=4080, credit_status="CURRENT", open_rebill_count=0
    )
    assertions.assert_balance_is_ledger_sum(account, entries)


# ===========================================================================
# The statutory appeal-filing window
# ===========================================================================
def test_appeal_filed_one_day_past_the_thirty_day_window_is_refused(api):
    """PRD §3.9: "The investigation must be in `DETERMINED`, `RESOLVED` or `CLOSED_NO_ADJUSTMENT`, and the filing must be timely: today's date on the logical clock must be no later than thirty calendar days after the reference instant, which is `determined_at` for a `DETERMINED` or `RESOLVED` investigation and the closure instant for one that is `CLOSED_NO_ADJUSTMENT`."

    PRD §2.4: "Wherever this document says "the current instant" or "today", it means the logical clock's value at the moment the request is processed."

    Design: Corner/validations/corner_validation_temporal_appeal_filing_window_is_thirty_inclusive_days
    """
    ctx = fixtures.upheld_bill_case(api, request_first_round=False)
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="CLOSED_NO_ADJUSTMENT",
    )

    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    validate_error(
        api.create_board_appeal(
            {
                "investigation_id": ctx["investigation_id"],
                "grounds": "asks the board to review the closure",
            },
            ctx["customer_headers"],
        ),
        "ERR_APPEAL_UNTIMELY",
    )

    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="CLOSED_NO_ADJUSTMENT",
        shutoff_hold_active=False,
    )
    rows, meta = validate_paginated(
        api.list_board_appeals(
            CLERK_HEADERS, {"investigation_id": ctx["investigation_id"]}
        )
    )
    assert rows == []
    assertions.assert_pagination_meta(meta, total_count=0)


def test_appeal_filed_on_the_thirtieth_day_is_accepted_and_re_arms_the_hold(api):
    """PRD §3.9: "A filed appeal opens in `FILED` with `filing_date` set from the logical clock and `filed_by_user_id` stamped with the acting `X-User-ID`, and `hearing_date`, `hearing_officer_user_id`, `decision` and `decision_note` all still null."

    PRD §3.9: "Filing moves the investigation to `APPEALED`, which sets `shutoff_hold_active` to true (or leaves it true) and increases the account's `open_investigation_hold_count` when the hold was not already outstanding — a pending appeal is itself a shutoff hold."

    Design: Corner/validations/corner_validation_temporal_appeal_filing_window_is_thirty_inclusive_days
    """
    ctx = fixtures.upheld_bill_case(api, request_first_round=False)

    fixtures.set_clock(api, "2026-08-31T00:00:00Z")
    appeal = validate_success(
        api.create_board_appeal(
            {
                "investigation_id": ctx["investigation_id"],
                "grounds": "asks the board to review the closure",
            },
            ctx["customer_headers"],
        ),
        201,
    )

    assertions.assert_fields(
        appeal,
        status="FILED",
        investigation_id=ctx["investigation_id"],
        filed_by_user_id=ctx["account_id"],
    )
    assert appeal["filing_date"].startswith("2026-08-31")
    assertions.assert_null_fields(
        appeal, "hearing_date", "hearing_officer_user_id", "decision", "decision_note"
    )

    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="APPEALED",
        shutoff_hold_active=True,
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        balance_cents=BASELINED_BILL_BALANCE_CENTS,
        open_investigation_hold_count=1,
    )


# ===========================================================================
# The board's daily docket capacity
# ===========================================================================
def test_hearing_docket_capacity_binds_per_date_and_not_globally(api):
    """PRD §3.9: "The board also sits only so many matters in a day: a date already holding three appeals in `SCHEDULED` status is full, and a further attempt is refused with `ERR_HEARING_DOCKET_FULL`."

    PRD §3.9: "The customer is entitled to notice, so `hearing_date` must be at or after the appeal's `filing_date` plus ten calendar days, else `ERR_HEARING_NOTICE_TOO_SHORT`."

    PRD §3.9: "Successful docketing records `hearing_date`, moves the appeal to `SCHEDULED`, and adds one to that date's docket count."

    Design: Corner/validations/corner_validation_aggregate_hearing_docket_capacity_counts_per_hearing_date
    """
    estate = _four_appeals_awaiting_a_docket(api)
    appeals = estate["appeals"]
    assert len(appeals) == 4
    for appeal in appeals:
        assertions.assert_fields(appeal, status="FILED")
        assert appeal["filing_date"].startswith("2026-08-01")

    for appeal in appeals[:3]:
        docketed = fixtures.schedule_hearing(api, appeal["id"], "2026-08-20")
        assertions.assert_fields(
            docketed, status="SCHEDULED", hearing_date="2026-08-20"
        )

    fourth = appeals[3]
    validate_error(
        api.schedule_hearing(
            fourth["id"], {"hearing_date": "2026-08-20"}, CLERK_HEADERS
        ),
        "ERR_HEARING_DOCKET_FULL",
    )
    refused = fixtures.fetch_appeal(api, fourth["id"])
    assertions.assert_fields(refused, status="FILED")
    assertions.assert_null_fields(refused, "hearing_date")

    moved = fixtures.schedule_hearing(api, fourth["id"], "2026-08-21")
    assertions.assert_fields(moved, status="SCHEDULED", hearing_date="2026-08-21")

    _rows, full_day = validate_paginated(
        api.list_board_appeals(CLERK_HEADERS, {"hearing_date": "2026-08-20"})
    )
    assertions.assert_pagination_meta(full_day, total_count=3)
    _rows, next_day = validate_paginated(
        api.list_board_appeals(CLERK_HEADERS, {"hearing_date": "2026-08-21"})
    )
    assertions.assert_pagination_meta(next_day, total_count=1)

    assertions.assert_account_state(
        fixtures.fetch_account(api, estate["account"]["id"]),
        balance_cents=7 * SMALL_PERIOD_TOTAL_CENTS,
        open_investigation_hold_count=4,
    )


# ===========================================================================
# The estimated read that suppresses an irrigation-submeter credit
# ===========================================================================
def test_an_estimated_master_read_suppresses_the_irrigation_submeter_credit(api):
    """PRD §3.2: "`estimated_flag` is set true exactly when the live period-end read for this bill has `read_type` of `ESTIMATED`; that single boolean later suppresses irrigation-submeter sewer relief, because an estimated master read cannot be reconciled against a submeter read."

    PRD §3.2: "If the bill's `estimated_flag` is true, or if every candidate submeter was ineligible, `submeter_credit_gallons` is zero; otherwise it is the lesser of the raw irrigation volume and `submeter_sewer_credit_cap_gallons`."

    PRD §3.2: "Step two subtracts: `sewer_billable_gallons` is the capped volume minus `submeter_credit_gallons`, with any negative result treated as zero."

    Design: Corner/validations/corner_validation_conditional_estimated_read_suppresses_the_irrigation_submeter_credit
    """
    ctx = fixtures.metered_account_with_submeter(api)
    actual_period_id = ctx["calendar"]["history_ids"][0]
    estimated_period_id = ctx["calendar"]["history_ids"][1]

    fixtures.post_reading(api, ctx["meter_id"], "2025-05-31", 100000)
    fixtures.post_reading(api, ctx["meter_id"], "2025-06-30", 141000)
    fixtures.post_reading(
        api, ctx["meter_id"], "2025-07-31", 182000, read_type="ESTIMATED"
    )
    # 9,000 gallons of irrigation volume inside each of the two periods.
    fixtures.post_reading(api, ctx["submeter_id"], "2025-05-31", 0)
    fixtures.post_reading(api, ctx["submeter_id"], "2025-06-30", 9000)
    fixtures.post_reading(api, ctx["submeter_id"], "2025-07-31", 18000)

    read_bill = fixtures.generate_bill(
        api, ctx["account_id"], actual_period_id, ctx["meter_id"]
    )
    estimated_bill = fixtures.generate_bill(
        api,
        ctx["account_id"],
        estimated_period_id,
        ctx["meter_id"],
        read_type="ESTIMATED",
    )

    assertions.assert_fields(
        read_bill,
        estimated_flag=False,
        consumption_gallons=41000,
        submeter_credit_gallons=8000,
        sewer_billable_gallons=4000,
    )
    assertions.assert_bill_charges(
        read_bill,
        water_charge_cents=LARGE_PERIOD_WATER_CENTS,
        sewer_charge_cents=2440,
        total_charge_cents=40059,
    )

    # PRD §3.2 pins only the suppression itself — "If the bill's
    # `estimated_flag` is true ... `submeter_credit_gallons` is zero". It does
    # not state what volume a bill derives when its live period-end read is
    # ESTIMATED (the derivation sentence names only the "live `ACTUAL` or
    # `CORRECTED` reads bounding the period"), so no consumption or charge
    # figure is asserted on the estimated bill.
    assertions.assert_fields(
        estimated_bill,
        estimated_flag=True,
        submeter_credit_gallons=0,
    )

    _rows, meta = validate_paginated(
        api.list_bills(SUPERVISOR_HEADERS, {"meter_id": ctx["submeter_id"]})
    )
    assertions.assert_pagination_meta(meta, total_count=0)


# ===========================================================================
# A meter that must belong to the account being billed
# ===========================================================================
def test_billing_a_meter_from_another_account_is_refused_as_a_mismatch(api):
    """PRD §3.2: "The meter must belong to the named account, else `ERR_BILL_METER_ACCOUNT_MISMATCH`."

    PRD §3.2: "The meter's `meter_type` must be `POTABLE_MASTER`, else `ERR_METER_NOT_BILLABLE`."

    Design: Corner/validations/corner_validation_cross_entity_bill_meter_must_belong_to_the_billed_account
    """
    estate = _two_accounts_with_their_own_master_meters(api)

    validate_error(
        api.create_bill(
            {
                "account_id": estate["account_a"]["id"],
                "period_id": estate["period"]["id"],
                "meter_id": estate["meter_b"]["id"],
                "read_type": "ACTUAL",
            },
            SUPERVISOR_HEADERS,
        ),
        "ERR_BILL_METER_ACCOUNT_MISMATCH",
    )

    for account_key in ("account_a", "account_b"):
        _rows, meta = validate_paginated(
            api.list_bills(
                SUPERVISOR_HEADERS, {"account_id": estate[account_key]["id"]}
            )
        )
        assertions.assert_pagination_meta(meta, total_count=0)


def test_each_meter_bills_cleanly_against_its_own_account(api):
    """PRD §3.2: "The caller never supplies consumption or money: `consumption_gallons` is derived from the live `ACTUAL` or `CORRECTED` reads bounding the period and can never be negative."

    PRD §3.2: "The meter must belong to the named account, else `ERR_BILL_METER_ACCOUNT_MISMATCH`."

    Design: Corner/validations/corner_validation_cross_entity_bill_meter_must_belong_to_the_billed_account
    """
    estate = _two_accounts_with_their_own_master_meters(api)

    bill_a = validate_success(
        api.create_bill(
            {
                "account_id": estate["account_a"]["id"],
                "period_id": estate["period"]["id"],
                "meter_id": estate["meter_a"]["id"],
                "read_type": "ACTUAL",
            },
            SUPERVISOR_HEADERS,
        ),
        201,
    )
    bill_b = validate_success(
        api.create_bill(
            {
                "account_id": estate["account_b"]["id"],
                "period_id": estate["period"]["id"],
                "meter_id": estate["meter_b"]["id"],
                "read_type": "ACTUAL",
            },
            SUPERVISOR_HEADERS,
        ),
        201,
    )

    for bill in (bill_a, bill_b):
        assertions.assert_bill_charges(
            bill,
            consumption_gallons=4000,
            total_charge_cents=SMALL_PERIOD_TOTAL_CENTS,
        )
        assertions.assert_fields(bill, billing_status="DRAFT")

    for account_key in ("account_a", "account_b"):
        assertions.assert_account_state(
            fixtures.fetch_account(api, estate[account_key]["id"]), balance_cents=0
        )


# ===========================================================================
# Existence is resolved before a customer's ownership scope
# ===========================================================================
def test_path_identifier_resolves_before_the_customer_ownership_scope(api):
    """PRD §2.7: "It sits after existence deliberately: a customer probing an unknown identifier gets a 404, not a 403, because the identifier space is not a secret even though row contents are."

    PRD §2.8: "Because scoping is evaluated after existence but before state, a customer aiming a legitimate-looking action at someone else's row receives `ERR_ACCOUNT_OWNERSHIP_MISMATCH` rather than a state error."

    Design: Corner/validations/corner_validation_cascading_existence_is_resolved_before_customer_ownership
    """
    estate = _two_accounts_with_their_own_master_meters(api, read_meter_a=False)
    foreign_bill = fixtures.generate_bill(
        api,
        estate["account_b"]["id"],
        estate["period"]["id"],
        estate["meter_b"]["id"],
    )
    customer_headers = make_customer_headers(estate["account_a"]["id"])

    validate_error(
        api.get_bill(NON_EXISTENT_UUID, customer_headers), "ERR_BILL_NOT_FOUND"
    )
    validate_error(
        api.get_bill(foreign_bill["id"], customer_headers),
        "ERR_ACCOUNT_OWNERSHIP_MISMATCH",
    )


def test_body_reference_resolves_before_the_customer_ownership_scope(api):
    """PRD §2.7: "Every identifier supplied in a payload must resolve, checked in the order the fields appear in that operation's input list, reporting the matching not-found code above (404)."

    PRD §2.8: "A bill belongs to the customer when its account identifier equals `X-User-ID`; an investigation, meter test request, repair proof, leak adjustment, arrangement or appeal belongs to the customer when the account reached through its chain of references does."

    Design: Corner/validations/corner_validation_cascading_existence_is_resolved_before_customer_ownership
    """
    estate = _two_accounts_with_their_own_master_meters(api, read_meter_a=False)
    foreign_bill = fixtures.generate_bill(
        api,
        estate["account_b"]["id"],
        estate["period"]["id"],
        estate["meter_b"]["id"],
    )
    customer_headers = make_customer_headers(estate["account_a"]["id"])

    validate_error(
        api.create_investigation(
            {
                "bill_id": NON_EXISTENT_UUID,
                "reported_cause": "probing an id that does not exist",
            },
            customer_headers,
        ),
        "ERR_BILL_NOT_FOUND",
    )
    validate_error(
        api.create_investigation(
            {
                "bill_id": foreign_bill["id"],
                "reported_cause": "probing a neighbour's bill",
            },
            customer_headers,
        ),
        "ERR_ACCOUNT_OWNERSHIP_MISMATCH",
    )

    rows, meta = validate_paginated(
        api.list_investigations(CSR_HEADERS, {"bill_id": foreign_bill["id"]})
    )
    assert rows == []
    assertions.assert_pagination_meta(meta, total_count=0)
