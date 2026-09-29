"""The declared arithmetic: the business-day deadline walk, the aggregation that
counts only effective reductions, the constants that bound a result at both ends,
the clock-driven advance accrual, the discounting and ranking of alternatives,
and the two fee bases.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ASSET_MANAGER,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    TRUSTEE,
)


# ==========================================================================
# The consultation response deadline is a business-day walk
# ==========================================================================
def test_the_consultation_deadline_walks_ten_business_days_over_a_holiday(api):
    """From a Friday issue date the walk skips three weekends and one pinned
    holiday to land on 2026-12-07 at the last millisecond of the day.

    The PRD: "The issue date itself is never counted, whether or not it happens
    to be a business day. The count then advances one calendar day at a time; a
    day is counted only if it is neither a Saturday nor a Sunday and is not one of
    the three pinned holidays `2026-09-07`, `2026-11-26` and `2026-12-25`. When
    the required number of business days has been counted, the deadline is that
    final date at `23:59:59.999Z`."

    Design: Corner/calculations/consultation_deadline_counts_ten_business_days_skipping_the_pinned_holiday
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-N1"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-N01", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    trust = fx.read_trust(api, built["trust_id"], TRUSTEE)
    assert trust["consultation_response_business_days"] == 10, (
        "the count is the declared default and is never supplied by the client"
    )

    plan = fx.create_plan(api, built["loan_id"])
    alternative = fx.add_modification_alternative(
        api,
        plan["id"],
        projected_cash_flows=[
            {"period_index": 1, "amount_usd": 900000},
            {"period_index": 2, "amount_usd": 9100000},
        ],
        upfront_cost_usd=120000,
    )
    fx.score_plan(api, plan["id"])
    fx.recommend_plan(api, plan["id"], alternative["id"])

    fx.set_clock(api, "2026-11-20T00:00:00Z")
    consultation = fx.issue_plan_consultation(api, built["trust_id"], plan["id"])

    assert consultation["issued_at"].startswith("2026-11-20T00:00:00"), (
        "issued_at is stamped with the current logical clock"
    )
    a.assert_millisecond_timestamp(consultation["deadline_at"], "deadline_at")
    assert consultation["deadline_at"].startswith("2026-12-07T23:59:59.999"), (
        "ten counted business days are Nov 23, 24, 25, 27, 30 and Dec 1, 2, 3, 4, 7"
    )
    a.assert_status(consultation, "PENDING")
    a.assert_status(consultation, "CONSENT_RIGHT", "rights_type")

    subject = validate_success(api.get_workout_plan(plan["id"], ASSET_MANAGER))
    a.assert_status(subject, "CONSULTATION")
    loan = fx.read_loan(api, built["loan_id"])
    a.assert_status(loan, "IN_WORKOUT", "servicing_status")


# ==========================================================================
# The trust ledger aggregates only the reductions the committee blessed
# ==========================================================================
def _trust_with_two_reduced_loans(api):
    """One trust, two special-serviced loans, one accepted appraisal each."""
    trust = fx.create_trust(api, deal_name="CMBS 2026-N2")
    loan_a = fx.create_mid_size_loan(
        api, trust["id"], loan_number="L-N02-A", maturity_date="2029-06-01T00:00:00Z"
    )
    loan_b = fx.create_loan(
        api,
        trust["id"],
        loan_number="L-N02-B",
        original_balance_usd=6000000,
        current_principal_balance_usd=5000000,
        note_rate_pct=5.5,
        monthly_debt_service_usd=31000,
        maturity_date="2030-01-01T00:00:00Z",
        securitization_value_usd=7000000,
    )

    fx.record_bankruptcy_event(api, loan_a["id"])
    fx.transfer_to_special_servicing(api, loan_a["id"])
    fx.record_transfer_event(
        api,
        loan_b["id"],
        event_code="RECEIVERSHIP",
        occurred_on="2026-07-05T00:00:00Z",
        evidence_note="receiver appointed over the property",
        days_delinquent_at_event=None,
    )
    fx.transfer_to_special_servicing(api, loan_b["id"])

    fx.accepted_appraisal(api, loan_a["id"], value_usd=6000000)
    fx.accepted_appraisal(api, loan_b["id"], value_usd=3000000)
    return trust["id"], loan_a["id"], loan_b["id"]


def test_only_the_effective_reduction_enters_the_trust_ara_ledger(api):
    """Both reductions are computed in full; one of them contributes nothing.

    The PRD: "Because the new reduction is only `PROVISIONAL`, the trust's
    `total_ara_usd` is **not** yet affected by it; that happens only when the
    committee makes it effective."

    Design: Corner/calculations/trust_total_ara_counts_only_effective_reductions
    """
    trust_id, loan_a_id, loan_b_id = _trust_with_two_reduced_loans(api)

    reduction_a = fx.provisional_reduction(api, loan_a_id)
    reduction_b = fx.provisional_reduction(api, loan_b_id)
    a.assert_money(reduction_a["ara_amount_usd"], 4600000.00, "loan A ara_amount_usd")
    a.assert_ara_percentage(reduction_a["ara_percentage"], 46.0000, "loan A ara_percentage")
    a.assert_money(reduction_b["ara_amount_usd"], 2300000.00, "loan B ara_amount_usd")
    a.assert_ara_percentage(reduction_b["ara_percentage"], 46.0000, "loan B ara_percentage")

    before = fx.read_trust(api, trust_id, TRUSTEE)
    a.assert_money(before["total_ara_usd"], 0.00, "total_ara_usd before the blessing")

    fx.make_reduction_effective(api, reduction_a["id"])

    after = fx.read_trust(api, trust_id, TRUSTEE)
    a.assert_money(after["total_ara_usd"], 4600000.00, "total_ara_usd")
    a.assert_money(
        after["controlling_class_notional_usd"], 35400000.00, "controlling_class_notional_usd"
    )
    a.assert_status(after, "CONTROLLING", "control_status")
    a.assert_version_advanced_by(before, after, 1, "trust")


def test_the_unblessed_reduction_is_filtered_out_but_still_readable(api):
    """The excluded row exists: it is merely absent from the aggregate.

    The PRD: "Its `ara_amount_usd` mirrors the single `EFFECTIVE` appraisal
    reduction on the loan and is `0` when there is none."

    Design: Corner/calculations/trust_total_ara_counts_only_effective_reductions
    """
    _, loan_a_id, loan_b_id = _trust_with_two_reduced_loans(api)
    reduction_a = fx.provisional_reduction(api, loan_a_id)
    reduction_b = fx.provisional_reduction(api, loan_b_id)
    fx.make_reduction_effective(api, reduction_a["id"])

    provisional, _ = validate_paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"status": "PROVISIONAL"})
    )
    a.assert_contains_id(provisional, reduction_b["id"])
    a.assert_excludes_id(provisional, reduction_a["id"])

    loan_b = fx.read_loan(api, loan_b_id)
    a.assert_money(loan_b["ara_amount_usd"], 0.00, "loan B ara_amount_usd")
    a.assert_money(
        loan_b["required_monthly_pi_advance_usd"], 31000.00, "loan B advance obligation"
    )
    loan_a = fx.read_loan(api, loan_a_id)
    a.assert_money(loan_a["ara_amount_usd"], 4600000.00, "loan A ara_amount_usd")


# ==========================================================================
# Declared constants bound a result at both ends
# ==========================================================================
def _reduction_for_appraisal(api, appraisal_id):
    rows, _ = validate_paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"appraisal_id": appraisal_id})
    )
    assert len(rows) == 1, "acceptance creates exactly one reduction per appraisal"
    return rows[0]


def test_the_credit_percentage_the_zero_floor_and_the_fee_floor_all_bite(api):
    """A one-million-dollar loan makes three declared constants visible at once.

    The PRD: "the `calculation_basis` is `GROSS_APPRAISED_BASIS`: ninety percent
    of the raw `value_usd`, rounded half up to two decimal places, becomes
    `appraisal_credit_usd`."

    Design: Corner/calculations/declared_constants_bound_the_result_at_both_ends
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-N3")
    assert trust["special_servicing_fee_annual_pct"] == 0.25, (
        "the annual fee percentage is the declared default"
    )
    loan = fx.create_loan(
        api,
        trust["id"],
        loan_number="L-N03",
        original_balance_usd=1200000,
        current_principal_balance_usd=1000000,
        note_rate_pct=6.5,
        monthly_debt_service_usd=7000,
        maturity_date="2029-06-01T00:00:00Z",
        securitization_value_usd=1500000,
    )
    fx.record_bankruptcy_event(api, loan["id"])
    fx.transfer_to_special_servicing(api, loan["id"])

    first = fx.order_appraisal(api, loan["id"], valuation_valid_months=3)
    fx.receive_appraisal(api, first["id"], 1111111, "2026-08-01T00:00:00Z")
    second = fx.order_appraisal(
        api, loan["id"], valuation_valid_months=3, appraiser_firm="Beta Valuation"
    )
    fx.receive_appraisal(api, second["id"], 1200000, "2026-11-01T00:00:00Z")

    fx.accept_appraisal(api, first["id"])
    fx.accept_appraisal(api, second["id"])

    reduction_one = _reduction_for_appraisal(api, first["id"])
    a.assert_money(reduction_one["deficiency_base_usd"], 1000000.00, "deficiency_base_usd")
    a.assert_money(reduction_one["appraisal_credit_usd"], 999999.90, "appraisal_credit_usd")
    a.assert_money(reduction_one["ara_amount_usd"], 0.10, "ara_amount_usd")

    reduction_two = _reduction_for_appraisal(api, second["id"])
    a.assert_money(reduction_two["appraisal_credit_usd"], 1080000.00, "appraisal_credit_usd")
    a.assert_money(reduction_two["ara_amount_usd"], 0.00, "floored ara_amount_usd")
    for reduction in (reduction_one, reduction_two):
        assert reduction["ara_amount_usd"] >= 0, "the reduction is floored at zero"
        assert reduction["ara_percentage"] >= 0, "the percentage is never negative"

    superseded = validate_success(api.get_appraisal(first["id"], ASSET_MANAGER))
    a.assert_status(superseded, "SUPERSEDED")
    a.assert_money(
        _reduction_for_appraisal(api, first["id"])["ara_amount_usd"],
        0.10,
        "the frozen reduction of the superseded appraisal",
    )

    fee = fx.accrue_special_servicing_fee(
        api,
        loan["id"],
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
    )
    a.assert_money(fee["basis_amount_usd"], 1000000.00, "basis_amount_usd")
    a.assert_rate_pct(fee["rate_pct"], 0.020833)
    a.assert_money(fee["amount_usd"], 500.00, "amount_usd raised to the monthly floor")
    a.assert_status(fee, "ACCRUED")
    assert fee["fee_type"] == "SPECIAL_SERVICING_FEE"
    assert fee["accrued_by_user_id"] == "amgr-001"


# ==========================================================================
# Advance interest is a function of advanced_on and the clock alone
# ==========================================================================
def _three_advances_in_reverse_chronological_order(api):
    """Created April, then February 15, then February 1."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    trust = fx.create_trust(api, deal_name="CMBS 2026-N4")
    a.assert_rate_pct(trust["advance_interest_rate_pct"], 5.0, "advance_interest_rate_pct")
    loan = fx.create_mid_size_loan(
        api, trust["id"], loan_number="L-N04", maturity_date="2029-06-01T00:00:00Z"
    )

    april = fx.record_advance(
        api,
        loan["id"],
        advance_type="PROPERTY_PROTECTION_ADVANCE",
        amount_usd=150000,
        advanced_on="2026-04-01T00:00:00Z",
    )
    february_fifteenth = fx.record_advance(
        api,
        loan["id"],
        advance_type="PROPERTY_PROTECTION_ADVANCE",
        amount_usd=200000,
        advanced_on="2026-02-15T00:00:00Z",
    )
    february_first = fx.record_advance(
        api,
        loan["id"],
        advance_type="PROPERTY_PROTECTION_ADVANCE",
        amount_usd=200000,
        advanced_on="2026-02-01T00:00:00Z",
    )
    return loan["id"], april, february_fifteenth, february_first


def test_the_same_rows_report_three_different_figures_at_three_clocks(api):
    """The row created last has the oldest advanced_on and the largest interest.

    The PRD: "The day count is then three hundred and sixty times the difference
    in years, plus thirty times the difference in months, plus the difference
    between the two clamped day-of-month values."

    Design: Corner/calculations/advance_interest_refreshes_on_read_and_ignores_creation_order
    """
    loan_id, april, february_fifteenth, february_first = (
        _three_advances_in_reverse_chronological_order(api)
    )

    at_june = validate_success(api.get_advance(february_first["id"], MASTER_SERVICER))
    a.assert_money(at_june["accrued_interest_usd"], 3333.33, "February 1 interest at June 1")
    assert at_june["interest_accrued_through"].startswith("2026-06-01T00:00:00"), (
        "interest_accrued_through is stamped with the clock it was measured to"
    )
    april_at_june = validate_success(api.get_advance(april["id"], MASTER_SERVICER))
    a.assert_money(april_at_june["accrued_interest_usd"], 1250.00, "April interest at June 1")

    fx.set_clock(api, "2026-08-31T00:00:00Z")
    clamped = validate_success(api.get_advance(february_fifteenth["id"], MASTER_SERVICER))
    a.assert_money(
        clamped["accrued_interest_usd"], 5416.67, "February 15 interest at August 31"
    )

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    rows, _ = validate_paginated(api.list_advances(MASTER_SERVICER, {"loan_id": loan_id}))
    a.assert_money(
        a.find_by_id(rows, february_first["id"])["accrued_interest_usd"],
        6666.67,
        "February 1 interest at October 1",
    )
    a.assert_money(
        a.find_by_id(rows, february_fifteenth["id"])["accrued_interest_usd"],
        6277.78,
        "February 15 interest at October 1",
    )
    a.assert_money(
        a.find_by_id(rows, april["id"])["accrued_interest_usd"],
        3750.00,
        "April interest at October 1",
    )

    loan = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_money(loan["advances_outstanding_usd"], 550000.00, "advances_outstanding_usd")


def test_the_advance_log_is_ordered_by_the_advance_date_not_by_creation(api):
    """The oldest advanced_on leads the list although it was written last.

    The PRD: "advances are returned by `advanced_on` ascending with `created_at`
    ascending as the tie-break, which is exactly the order in which the
    liquidation waterfall reimburses them"

    Design: Corner/calculations/advance_interest_refreshes_on_read_and_ignores_creation_order
    """
    loan_id, april, february_fifteenth, february_first = (
        _three_advances_in_reverse_chronological_order(api)
    )
    fx.set_clock(api, "2026-10-01T00:00:00Z")

    rows, meta = validate_paginated(api.list_advances(MASTER_SERVICER, {"loan_id": loan_id}))
    assert meta["total_count"] == 3
    assert a.ids_of(rows) == [
        february_first["id"],
        february_fifteenth["id"],
        april["id"],
    ], "the log reads oldest advance first"
    a.assert_money(rows[0]["accrued_interest_usd"], 6666.67, "leading row interest")


# ==========================================================================
# Net present value is produced by the scoring transition, not at creation
# ==========================================================================
def _plan_with_two_priced_routes(api):
    """A DRAFT plan at 8.0% carrying a MODIFICATION and a NOTE_SALE."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-N5"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-N05", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    plan = fx.create_plan(
        api, built["loan_id"], discount_rate_pct=8.0, npv_basis="CONTRACTUAL"
    )
    modification = fx.add_modification_alternative(
        api,
        plan["id"],
        projected_cash_flows=[
            {"period_index": 1, "amount_usd": 1000000},
            {"period_index": 2, "amount_usd": 1000000},
            {"period_index": 3, "amount_usd": 8000000},
        ],
        upfront_cost_usd=100000,
    )
    note_sale = fx.add_note_sale_alternative(
        api,
        plan["id"],
        projected_cash_flows=[{"period_index": 1, "amount_usd": 8500000}],
        upfront_cost_usd=90000,
    )
    return plan, modification, note_sale


def test_an_alternative_carries_no_valuation_until_the_plan_is_scored(api):
    """Every pricing field is null while the alternative is merely PROPOSED.

    The PRD: "A new alternative starts in status `PROPOSED` with
    `discounted_pv_usd`, `npv_usd` and `rank` all null"

    Design: Corner/calculations/npv_is_projected_at_scoring_time_not_at_alternative_creation
    """
    _, modification, note_sale = _plan_with_two_priced_routes(api)

    for alternative in (modification, note_sale):
        a.assert_status(alternative, "PROPOSED")
        a.assert_fields_null(alternative, "discounted_pv_usd", "npv_usd", "rank")


def test_one_scoring_transition_prices_every_alternative_in_the_pool(api):
    """The contractual basis divides period one by the base exactly once.

    The PRD: "Under the `CONTRACTUAL` basis, the cash flow of period *n* is
    divided by that base raised to the power *n*; under the `DELAY_STRESSED` basis
    every recovery is assumed to slip one full annual period, so the cash flow of
    period *n* is divided by the base raised to the power *n* plus one."

    Design: Corner/calculations/npv_is_projected_at_scoring_time_not_at_alternative_creation
    """
    plan, modification, note_sale = _plan_with_two_priced_routes(api)

    scored = fx.score_plan(api, plan["id"])
    a.assert_status(scored, "SCORED")
    assert scored["recommended_alternative_id"] == modification["id"]
    a.assert_version_advanced_by(plan, scored, 1, "workout plan")

    priced_modification = validate_success(
        api.get_workout_alternative(modification["id"], ASSET_MANAGER)
    )
    a.assert_money(
        priced_modification["discounted_pv_usd"], 8133922.68, "discounted_pv_usd"
    )
    a.assert_money(priced_modification["npv_usd"], 8033922.68, "npv_usd")
    assert priced_modification["rank"] == 1
    a.assert_status(priced_modification, "SCORED")
    a.assert_version_advanced_by(modification, priced_modification, 1, "alternative")

    priced_note_sale = validate_success(
        api.get_workout_alternative(note_sale["id"], ASSET_MANAGER)
    )
    a.assert_money(priced_note_sale["discounted_pv_usd"], 7870370.37, "discounted_pv_usd")
    a.assert_money(priced_note_sale["npv_usd"], 7780370.37, "npv_usd")
    assert priced_note_sale["rank"] == 2
    a.assert_version_advanced_by(note_sale, priced_note_sale, 1, "alternative")


# ==========================================================================
# Ranking, and the two declared tie-breaks beneath it
# ==========================================================================
def _alternative(api, plan_id, alternative_type, cash_flows, upfront_cost_usd):
    return validate_success(
        api.create_workout_alternative(
            {
                "workout_plan_id": plan_id,
                "alternative_type": alternative_type,
                "projected_cash_flows": cash_flows,
                "upfront_cost_usd": upfront_cost_usd,
            },
            ASSET_MANAGER,
        ),
        201,
    )


def _plan_with_a_three_way_tie(api):
    """Three alternatives priced identically, plus a cheaper foreclosure."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-N6"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-N06", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    plan = fx.create_plan(
        api, built["loan_id"], discount_rate_pct=9.5, npv_basis="CONTRACTUAL"
    )
    tied_flows = [
        {"period_index": 1, "amount_usd": 5000000},
        {"period_index": 2, "amount_usd": 5000000},
    ]
    first_deed = _alternative(api, plan["id"], "DEED_IN_LIEU", tied_flows, 200000)
    note_sale = _alternative(api, plan["id"], "NOTE_SALE", tied_flows, 200000)
    second_deed = _alternative(api, plan["id"], "DEED_IN_LIEU", tied_flows, 200000)
    foreclosure = _alternative(
        api,
        plan["id"],
        "FORECLOSURE",
        [
            {"period_index": 1, "amount_usd": 4000000},
            {"period_index": 2, "amount_usd": 5000000},
        ],
        200000,
    )
    return plan, first_deed, note_sale, second_deed, foreclosure


def test_the_type_ordinal_then_created_at_settles_an_exact_npv_tie(api):
    """Three alternatives tie to the cent, so both declared tie-breaks decide.

    The PRD: "ties are broken by the ordinal of the `alternative_type`, ascending,
    where `MODIFICATION` is 1, `DEED_IN_LIEU` is 2, `NOTE_SALE` is 3 and
    `FORECLOSURE` is 4 — an ordering that encodes the pooling and servicing
    agreement's preference for keeping the loan alive; and only when both the net
    present value and the type are equal does `created_at` ascending decide."

    Design: Corner/calculations/ranking_breaks_exact_npv_ties_by_type_ordinal_then_created_at
    """
    plan, first_deed, note_sale, second_deed, foreclosure = _plan_with_a_three_way_tie(api)

    scored = fx.score_plan(api, plan["id"])
    assert scored["recommended_alternative_id"] == first_deed["id"]

    rows, _ = validate_paginated(
        api.list_workout_alternatives(ASSET_MANAGER, {"workout_plan_id": plan["id"]})
    )
    by_id = {row["id"]: row for row in rows}
    for label, alternative in (
        ("first DEED_IN_LIEU", first_deed),
        ("NOTE_SALE", note_sale),
        ("second DEED_IN_LIEU", second_deed),
    ):
        a.assert_money(
            by_id[alternative["id"]]["discounted_pv_usd"],
            8736264.89,
            f"{label} discounted_pv_usd",
        )
        a.assert_money(by_id[alternative["id"]]["npv_usd"], 8536264.89, f"{label} npv_usd")
    a.assert_money(
        by_id[foreclosure["id"]]["discounted_pv_usd"], 7823022.88, "FORECLOSURE pv"
    )
    a.assert_money(by_id[foreclosure["id"]]["npv_usd"], 7623022.88, "FORECLOSURE npv")

    assert by_id[first_deed["id"]]["rank"] == 1
    assert by_id[second_deed["id"]]["rank"] == 2
    assert by_id[note_sale["id"]]["rank"] == 3
    assert by_id[foreclosure["id"]]["rank"] == 4
    for row in rows:
        a.assert_status(row, "SCORED")


def test_the_alternative_listing_reads_back_in_rank_order_every_time(api):
    """The ordering is deterministic and never falls back to the identifier.

    The PRD: "An alternative's `id` is never used as a tie-break."

    Design: Corner/calculations/ranking_breaks_exact_npv_ties_by_type_ordinal_then_created_at
    """
    plan, first_deed, note_sale, second_deed, foreclosure = _plan_with_a_three_way_tie(api)
    fx.score_plan(api, plan["id"])

    expected = [first_deed["id"], second_deed["id"], note_sale["id"], foreclosure["id"]]
    for _ in range(2):
        rows, _ = validate_paginated(
            api.list_workout_alternatives(ASSET_MANAGER, {"workout_plan_id": plan["id"]})
        )
        assert a.ids_of(rows) == expected, "alternatives read back by rank ascending"
        assert [row["rank"] for row in rows] == [1, 2, 3, 4]


# ==========================================================================
# The fee basis variant is selected by server-side state
# ==========================================================================
def test_the_fee_basis_follows_the_reduction_and_not_the_caller(api):
    """Two identical monthly accruals diverge because the committee acted between
    them.

    The PRD: "Under `ARA_ADJUSTED` the `basis_amount_usd` is that balance less the
    loan's `ara_amount_usd`, rounded half up to two decimal places, so the fee
    shrinks as collateral value falls."

    Design: Corner/calculations/fee_basis_variant_is_selected_by_ara_effectiveness_not_by_the_caller
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={
            "deal_name": "CMBS 2026-N7",
            "fee_basis_convention": "ARA_ADJUSTED",
        },
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-N07", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id = built["loan_id"]
    trust = fx.read_trust(api, built["trust_id"], TRUSTEE)
    assert trust["fee_basis_convention"] == "ARA_ADJUSTED"

    fx.accepted_appraisal(api, loan_id, value_usd=6000000)
    reduction = fx.provisional_reduction(api, loan_id)
    a.assert_money(reduction["ara_amount_usd"], 4600000.00, "ara_amount_usd")
    a.assert_money(
        fx.read_loan(api, loan_id)["ara_amount_usd"],
        0.00,
        "the loan mirrors no reduction while this one is only provisional",
    )

    july = fx.accrue_special_servicing_fee(
        api,
        loan_id,
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
    )
    a.assert_money(july["basis_amount_usd"], 10000000.00, "July basis_amount_usd")
    a.assert_rate_pct(july["rate_pct"], 0.020833)
    a.assert_money(july["amount_usd"], 2083.33, "July amount_usd")

    fx.make_reduction_effective(api, reduction["id"])

    august = fx.accrue_special_servicing_fee(
        api,
        loan_id,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
    )
    a.assert_money(august["basis_amount_usd"], 5400000.00, "August basis_amount_usd")
    a.assert_rate_pct(august["rate_pct"], 0.020833)
    a.assert_money(august["amount_usd"], 1125.00, "August amount_usd")

    loan = fx.read_loan(api, loan_id)
    a.assert_money(loan["ara_amount_usd"], 4600000.00, "ara_amount_usd")
    a.assert_money(loan["fees_payable_usd"], 3208.33, "fees_payable_usd")


# ==========================================================================
# A newer valuation retires the incumbent reduction before its replacement lands
# ==========================================================================
def _effective_reduction_and_a_received_successor(api):
    """Reduction one is EFFECTIVE at 4,600,000.00; appraisal two is RECEIVED."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-N8"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-N08", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id = built["loan_id"]

    first = fx.order_appraisal(api, loan_id, valuation_valid_months=3)
    fx.receive_appraisal(api, first["id"], 6000000, "2026-08-01T00:00:00Z")
    fx.accept_appraisal(api, first["id"])
    reduction_one = fx.provisional_reduction(api, loan_id)
    fx.make_reduction_effective(api, reduction_one["id"])

    second = fx.order_appraisal(
        api, loan_id, appraiser_firm="Beta Valuation", valuation_valid_months=12
    )
    fx.receive_appraisal(api, second["id"], 7000000, "2026-11-01T00:00:00Z")
    return built["trust_id"], loan_id, first, second, reduction_one


def test_the_ledger_moves_twice_and_never_holds_two_reductions_at_once(api):
    """The retired reduction leaves the ledger before its replacement enters it.

    The PRD: "if an appraisal reduction pointing at that now-superseded appraisal
    was `EFFECTIVE`, it is moved to `RECALCULATED`, its `advance_reduction_applies`
    is set false, the trust's `total_ara_usd` is recomputed and the control test
    re-runs."

    Design: Corner/calculations/newer_accepted_appraisal_reconciles_the_effective_reduction_to_recalculated
    """
    trust_id, loan_id, first, second, reduction_one = (
        _effective_reduction_and_a_received_successor(api)
    )

    before_trust = fx.read_trust(api, trust_id, TRUSTEE)
    a.assert_money(before_trust["total_ara_usd"], 4600000.00, "total_ara_usd before")
    a.assert_money(
        before_trust["controlling_class_notional_usd"], 35400000.00, "notional before"
    )
    a.assert_money(
        fx.read_loan(api, loan_id)["required_monthly_pi_advance_usd"],
        35100.00,
        "the prorated advance obligation while the reduction is effective",
    )

    fx.accept_appraisal(api, second["id"])

    superseded = validate_success(api.get_appraisal(first["id"], ASSET_MANAGER))
    a.assert_status(superseded, "SUPERSEDED")
    retired = validate_success(
        api.get_appraisal_reduction(reduction_one["id"], ASSET_MANAGER)
    )
    a.assert_status(retired, "RECALCULATED")
    assert retired["advance_reduction_applies"] is False

    mid_trust = fx.read_trust(api, trust_id, TRUSTEE)
    a.assert_money(mid_trust["total_ara_usd"], 0.00, "total_ara_usd between the two")
    a.assert_money(
        mid_trust["controlling_class_notional_usd"], 40000000.00, "notional between the two"
    )
    mid_loan = fx.read_loan(api, loan_id)
    a.assert_money(mid_loan["ara_amount_usd"], 0.00, "ara_amount_usd between the two")
    a.assert_money(
        mid_loan["required_monthly_pi_advance_usd"],
        65000.00,
        "the unreduced advance obligation between the two",
    )

    reduction_two = fx.provisional_reduction(api, loan_id)
    a.assert_money(reduction_two["deficiency_base_usd"], 10000000.00, "deficiency_base_usd")
    a.assert_money(reduction_two["appraisal_credit_usd"], 6300000.00, "appraisal_credit_usd")
    a.assert_money(reduction_two["ara_amount_usd"], 3700000.00, "replacement ara_amount_usd")

    fx.make_reduction_effective(api, reduction_two["id"])

    after_trust = fx.read_trust(api, trust_id, TRUSTEE)
    a.assert_money(after_trust["total_ara_usd"], 3700000.00, "total_ara_usd after")
    a.assert_money(
        after_trust["controlling_class_notional_usd"], 36300000.00, "notional after"
    )
    a.assert_status(after_trust, "CONTROLLING", "control_status")
    after_loan = fx.read_loan(api, loan_id)
    a.assert_money(after_loan["ara_amount_usd"], 3700000.00, "ara_amount_usd after")
    a.assert_money(
        after_loan["required_monthly_pi_advance_usd"],
        40950.00,
        "the advance obligation prorated on the replacement reduction",
    )

    response = api.set_appraisal_reduction_status(
        reduction_one["id"], f.status_payload("EFFECTIVE"), COMMITTEE_OFFICER
    )
    validate_error(response, e.ERR_INVALID_STATE_TRANSITION, 409)
    a.assert_status(
        validate_success(api.get_appraisal_reduction(reduction_one["id"], ASSET_MANAGER)),
        "RECALCULATED",
    )
