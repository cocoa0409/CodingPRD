"""Dual-variant arithmetic: the appraisal reduction credit basis, the special
servicing fee basis convention, and the net-present-value discounting basis.

Each of these three calculations has two declared variants that run on identical
input data and produce materially different stored figures.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ARA_FULL_NARRATIVE_AMOUNT,
    ARA_FULL_NARRATIVE_CREDIT,
    ARA_FULL_NARRATIVE_PERCENTAGE,
    ARA_UPDATE_AMOUNT,
    ARA_UPDATE_CREDIT,
    ARA_UPDATE_PERCENTAGE,
    DEFAULT_CLOCK,
    FEE_ARA_ADJUSTED_AMOUNT,
    FEE_ARA_ADJUSTED_BASIS,
    FEE_MONTHLY_RATE_PCT,
    FEE_STATED_PRINCIPAL_AMOUNT,
    FEE_STATED_PRINCIPAL_BASIS,
    NPV_FORECLOSURE_NPV_CONTRACTUAL,
    NPV_FORECLOSURE_NPV_DELAY_STRESSED,
    NPV_MOD_NPV_CONTRACTUAL,
    NPV_MOD_NPV_DELAY_STRESSED,
    NPV_MOD_PV_CONTRACTUAL,
    NPV_MOD_PV_DELAY_STRESSED,
    NPV_NOTE_NPV_CONTRACTUAL,
    NPV_NOTE_NPV_DELAY_STRESSED,
)
from test_helpers.test_users import ASSET_MANAGER


# ==========================================================================
# The appraisal reduction credit basis
# ==========================================================================
def _loan_with_deficiency_base_of_19_5m(api, trust_id, loan_number):
    """Board a 19,500,000.00 balance loan with no advances and transfer it."""
    loan = fx.create_loan(api, trust_id, loan_number=loan_number)
    fx.record_transfer_event(api, loan["id"])
    fx.transfer_to_special_servicing(api, loan["id"])
    return loan["id"]


def test_update_appraisal_takes_the_credit_against_the_raw_appraised_value(api):
    """An UPDATE appraisal drives GROSS_APPRAISED_BASIS.

    The PRD: "When the `appraisal_type` is `UPDATE` or `INTERNAL_VALUATION`, the
    `calculation_basis` is `GROSS_APPRAISED_BASIS`: ninety percent of the raw
    `value_usd`, rounded half up to two decimal places, becomes
    `appraisal_credit_usd`."

    Design: Difficulty/dual_variant_calc/ara_gross_appraised_versus_net_liquidation_credit_basis
    """
    trust = fx.create_trust(api, original_controlling_class_balance_usd=8000000)
    loan_id = _loan_with_deficiency_base_of_19_5m(api, trust["id"], "L-001")

    fx.accepted_appraisal(
        api, loan_id, value_usd=15000000, as_of_date=DEFAULT_CLOCK, appraisal_type="UPDATE"
    )

    rows, _ = validate_paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"loan_id": loan_id})
    )
    assert len(rows) == 1, "accepting one appraisal creates exactly one reduction"
    reduction = rows[0]
    a.assert_status(reduction, "GROSS_APPRAISED_BASIS", "calculation_basis")
    a.assert_money(reduction["deficiency_base_usd"], 19500000.00, "deficiency_base_usd")
    a.assert_money(reduction["appraisal_credit_usd"], ARA_UPDATE_CREDIT, "appraisal_credit_usd")
    a.assert_money(reduction["ara_amount_usd"], ARA_UPDATE_AMOUNT, "ara_amount_usd")
    a.assert_ara_percentage(reduction["ara_percentage"], ARA_UPDATE_PERCENTAGE)


def test_full_narrative_appraisal_nets_liquidation_expenses_before_the_credit(api):
    """A FULL_NARRATIVE appraisal drives NET_LIQUIDATION_BASIS.

    The PRD: "When the driving appraisal's `appraisal_type` is `FULL_NARRATIVE`,
    the `calculation_basis` is `NET_LIQUIDATION_BASIS`: the appraiser's
    `estimated_liquidation_expenses_usd` is subtracted from `value_usd` first,
    and ninety percent of that net figure, rounded half up to two decimal
    places, becomes `appraisal_credit_usd`."

    Design: Difficulty/dual_variant_calc/ara_gross_appraised_versus_net_liquidation_credit_basis
    """
    trust = fx.create_trust(api, original_controlling_class_balance_usd=8000000)
    loan_id = _loan_with_deficiency_base_of_19_5m(api, trust["id"], "L-002")

    fx.accepted_appraisal(
        api,
        loan_id,
        value_usd=15000000,
        as_of_date=DEFAULT_CLOCK,
        appraisal_type="FULL_NARRATIVE",
        received_extra={"estimated_liquidation_expenses_usd": 900000},
    )

    rows, _ = validate_paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"loan_id": loan_id})
    )
    reduction = rows[0]
    a.assert_status(reduction, "NET_LIQUIDATION_BASIS", "calculation_basis")
    a.assert_money(reduction["deficiency_base_usd"], 19500000.00, "deficiency_base_usd")
    a.assert_money(
        reduction["appraisal_credit_usd"], ARA_FULL_NARRATIVE_CREDIT, "appraisal_credit_usd"
    )
    a.assert_money(reduction["ara_amount_usd"], ARA_FULL_NARRATIVE_AMOUNT, "ara_amount_usd")
    a.assert_ara_percentage(reduction["ara_percentage"], ARA_FULL_NARRATIVE_PERCENTAGE)


def test_identical_appraised_values_diverge_by_ninety_percent_of_the_expenses(api):
    """The two credit bases diverge by exactly 90% of the liquidation expenses.

    The PRD: "The gross basis always yields the smaller reduction; the net basis
    shrinks the credit by ninety percent of the estimated liquidation expenses
    and grows the reduction by exactly the same amount, so two appraisals
    reporting an identical `value_usd` produce materially different reductions
    depending on their type."

    Design: Difficulty/dual_variant_calc/ara_gross_appraised_versus_net_liquidation_credit_basis
    """
    trust = fx.create_trust(api, original_controlling_class_balance_usd=8000000)
    loan_a = _loan_with_deficiency_base_of_19_5m(api, trust["id"], "L-001")
    loan_b = _loan_with_deficiency_base_of_19_5m(api, trust["id"], "L-002")

    fx.accepted_appraisal(api, loan_a, value_usd=15000000, appraisal_type="UPDATE")
    fx.accepted_appraisal(
        api,
        loan_b,
        value_usd=15000000,
        appraisal_type="FULL_NARRATIVE",
        received_extra={"estimated_liquidation_expenses_usd": 900000},
    )

    rows_a, _ = validate_paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"loan_id": loan_a})
    )
    rows_b, _ = validate_paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"loan_id": loan_b})
    )
    gross = rows_a[0]["ara_amount_usd"]
    net = rows_b[0]["ara_amount_usd"]
    a.assert_money(net - gross, 810000.00, "net basis minus gross basis reduction")
    assert net > gross, "the gross basis must yield the smaller reduction"


def test_provisional_reductions_leave_the_trust_total_and_control_untouched(api):
    """A PROVISIONAL reduction does not move the trust's total.

    The PRD: "Because the new reduction is only `PROVISIONAL`, the trust's
    `total_ara_usd` is **not** yet affected by it; that happens only when the
    committee makes it effective."

    Design: Difficulty/dual_variant_calc/ara_gross_appraised_versus_net_liquidation_credit_basis
    """
    trust = fx.create_trust(api, original_controlling_class_balance_usd=8000000)
    loan_a = _loan_with_deficiency_base_of_19_5m(api, trust["id"], "L-001")
    loan_b = _loan_with_deficiency_base_of_19_5m(api, trust["id"], "L-002")

    fx.accepted_appraisal(api, loan_a, value_usd=15000000, appraisal_type="UPDATE")
    fx.accepted_appraisal(
        api,
        loan_b,
        value_usd=15000000,
        appraisal_type="FULL_NARRATIVE",
        received_extra={"estimated_liquidation_expenses_usd": 900000},
    )

    rows, _ = validate_paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"loan_id": loan_a})
    )
    a.assert_status(rows[0], "PROVISIONAL")

    trust_now = validate_success(api.get_trust(trust["id"], ASSET_MANAGER))
    a.assert_money(trust_now["total_ara_usd"], 0.00, "total_ara_usd")
    a.assert_status(trust_now, "CONTROLLING", "control_status")


# ==========================================================================
# The special servicing fee basis convention
# ==========================================================================
def _loan_with_effective_reduction_of_6m_and_ninety_cents(api, trust_id, loan_number):
    """A 19,500,000.00 loan whose EFFECTIVE reduction is exactly 6,000,000.90."""
    loan = fx.create_loan(api, trust_id, loan_number=loan_number)
    fx.record_bankruptcy_event(api, loan["id"])
    fx.transfer_to_special_servicing(api, loan["id"])
    fx.effective_reduction(api, loan["id"], value_usd=14999999)
    return loan["id"]


def test_stated_principal_convention_accrues_on_the_full_balance(api):
    """STATED_PRINCIPAL ignores the appraisal reduction entirely.

    The PRD: "Under `STATED_PRINCIPAL` the `basis_amount_usd` is the loan's full
    `current_principal_balance_usd`, unaffected by any appraisal reduction, so
    the servicer keeps earning on the written-down portion of the asset."

    Design: Difficulty/dual_variant_calc/special_servicing_fee_stated_principal_versus_ara_adjusted_basis
    """
    trust = fx.create_trust(
        api,
        deal_name="CMBS 2026-S1",
        special_servicing_fee_annual_pct=0.25,
        fee_basis_convention="STATED_PRINCIPAL",
    )
    loan_id = _loan_with_effective_reduction_of_6m_and_ninety_cents(api, trust["id"], "L-S01")

    loan = validate_success(api.get_loan(loan_id, ASSET_MANAGER))
    a.assert_money(loan["ara_amount_usd"], 6000000.90, "ara_amount_usd")

    fee = validate_success(
        api.create_fee_accrual(f.special_servicing_fee_payload(loan_id), ASSET_MANAGER), 201
    )
    a.assert_money(fee["basis_amount_usd"], FEE_STATED_PRINCIPAL_BASIS, "basis_amount_usd")
    a.assert_money(fee["amount_usd"], FEE_STATED_PRINCIPAL_AMOUNT, "amount_usd")
    a.assert_rate_pct(fee["rate_pct"], FEE_MONTHLY_RATE_PCT)

    loan_after = validate_success(api.get_loan(loan_id, ASSET_MANAGER))
    a.assert_money(loan_after["fees_payable_usd"], FEE_STATED_PRINCIPAL_AMOUNT, "fees_payable_usd")


def test_ara_adjusted_convention_accrues_on_the_written_down_balance(api):
    """ARA_ADJUSTED subtracts the loan's reduction from the fee basis.

    The PRD: "Under `ARA_ADJUSTED` the `basis_amount_usd` is that balance less
    the loan's `ara_amount_usd`, rounded half up to two decimal places, so the
    fee shrinks as collateral value falls."

    Design: Difficulty/dual_variant_calc/special_servicing_fee_stated_principal_versus_ara_adjusted_basis
    """
    trust = fx.create_trust(
        api,
        deal_name="CMBS 2026-R1",
        special_servicing_fee_annual_pct=0.25,
        fee_basis_convention="ARA_ADJUSTED",
    )
    loan_id = _loan_with_effective_reduction_of_6m_and_ninety_cents(api, trust["id"], "L-R01")

    loan = validate_success(api.get_loan(loan_id, ASSET_MANAGER))
    a.assert_money(loan["ara_amount_usd"], 6000000.90, "ara_amount_usd")

    fee = validate_success(
        api.create_fee_accrual(f.special_servicing_fee_payload(loan_id), ASSET_MANAGER), 201
    )
    a.assert_money(fee["basis_amount_usd"], FEE_ARA_ADJUSTED_BASIS, "basis_amount_usd")
    a.assert_money(fee["amount_usd"], FEE_ARA_ADJUSTED_AMOUNT, "amount_usd")
    a.assert_rate_pct(fee["rate_pct"], FEE_MONTHLY_RATE_PCT)

    loan_after = validate_success(api.get_loan(loan_id, ASSET_MANAGER))
    a.assert_money(loan_after["fees_payable_usd"], FEE_ARA_ADJUSTED_AMOUNT, "fees_payable_usd")


def test_the_two_fee_conventions_diverge_on_identical_loans(api):
    """One trust-level field, and one field only, drives the divergence.

    The PRD: "The monthly **special servicing fee** is a dual-variant
    calculation whose behaviour the trust chooses through
    `fee_basis_convention`."

    Design: Difficulty/dual_variant_calc/special_servicing_fee_stated_principal_versus_ara_adjusted_basis
    """
    stated = fx.create_trust(
        api,
        deal_name="CMBS 2026-S1",
        special_servicing_fee_annual_pct=0.25,
        fee_basis_convention="STATED_PRINCIPAL",
    )
    adjusted = fx.create_trust(
        api,
        deal_name="CMBS 2026-R1",
        special_servicing_fee_annual_pct=0.25,
        fee_basis_convention="ARA_ADJUSTED",
    )
    loan_s = _loan_with_effective_reduction_of_6m_and_ninety_cents(api, stated["id"], "L-S01")
    loan_r = _loan_with_effective_reduction_of_6m_and_ninety_cents(api, adjusted["id"], "L-R01")

    fee_s = validate_success(
        api.create_fee_accrual(f.special_servicing_fee_payload(loan_s), ASSET_MANAGER), 201
    )
    fee_r = validate_success(
        api.create_fee_accrual(f.special_servicing_fee_payload(loan_r), ASSET_MANAGER), 201
    )
    a.assert_money(
        fee_s["amount_usd"] - fee_r["amount_usd"], 1250.00, "fee divergence between conventions"
    )


# ==========================================================================
# The net present value discounting basis
# ==========================================================================
_ALTERNATIVE_BUILDERS = [
    fx.add_modification_alternative,
    fx.add_note_sale_alternative,
    fx.add_foreclosure_alternative,
]


def _scored_plan_on_a_fresh_loan(api, npv_basis, loan_number):
    built_loan = fx.loan_in_special_servicing(
        api,
        loan_factory=fx.create_mid_size_loan,
        event_factory=lambda client, loan_id: fx.record_transfer_event(
            client,
            loan_id,
            event_code="IMMINENT_DEFAULT",
            occurred_on="2026-07-20T00:00:00Z",
            evidence_note="borrower certified imminent default",
            days_delinquent_at_event=None,
            imminent_default_certified=True,
        ),
        loan_overrides={"loan_number": loan_number},
    )
    return fx.scored_plan(
        api,
        built_loan["loan_id"],
        alternative_builders=_ALTERNATIVE_BUILDERS,
        npv_basis=npv_basis,
    )


def _alternatives_by_type(api, plan_id):
    rows, _ = validate_paginated(
        api.list_workout_alternatives(ASSET_MANAGER, {"workout_plan_id": plan_id})
    )
    return {row["alternative_type"]: row for row in rows}


def test_contractual_basis_discounts_each_period_at_its_own_index(api):
    """Under CONTRACTUAL the exponent is the period index itself.

    The PRD: "Under the `CONTRACTUAL` basis, the cash flow of period *n* is
    divided by that base raised to the power *n*; under the `DELAY_STRESSED`
    basis every recovery is assumed to slip one full annual period, so the cash
    flow of period *n* is divided by the base raised to the power *n* plus one."

    Design: Difficulty/dual_variant_calc/workout_npv_contractual_versus_delay_stressed_recommendation_flip
    """
    built = _scored_plan_on_a_fresh_loan(api, "CONTRACTUAL", "L-C01")
    by_type = _alternatives_by_type(api, built["plan_id"])

    a.assert_money(
        by_type["MODIFICATION"]["discounted_pv_usd"], NPV_MOD_PV_CONTRACTUAL, "discounted_pv_usd"
    )
    a.assert_money(by_type["MODIFICATION"]["npv_usd"], NPV_MOD_NPV_CONTRACTUAL, "MODIFICATION npv")
    a.assert_money(by_type["NOTE_SALE"]["npv_usd"], NPV_NOTE_NPV_CONTRACTUAL, "NOTE_SALE npv")
    a.assert_money(
        by_type["FORECLOSURE"]["npv_usd"], NPV_FORECLOSURE_NPV_CONTRACTUAL, "FORECLOSURE npv"
    )
    assert by_type["MODIFICATION"]["rank"] == 1
    assert by_type["NOTE_SALE"]["rank"] == 2
    assert by_type["FORECLOSURE"]["rank"] == 3
    assert built["plan"]["recommended_alternative_id"] == by_type["MODIFICATION"]["id"]


def test_delay_stressed_basis_slips_every_recovery_one_annual_period(api):
    """Under DELAY_STRESSED the exponent is the period index plus one.

    The PRD: "Because the stressed basis pushes every flow one period further
    out, it punishes back-loaded alternatives more than front-loaded ones and
    can genuinely reverse which alternative comes first."

    Design: Difficulty/dual_variant_calc/workout_npv_contractual_versus_delay_stressed_recommendation_flip
    """
    built = _scored_plan_on_a_fresh_loan(api, "DELAY_STRESSED", "L-D01")
    by_type = _alternatives_by_type(api, built["plan_id"])

    a.assert_money(
        by_type["MODIFICATION"]["discounted_pv_usd"],
        NPV_MOD_PV_DELAY_STRESSED,
        "discounted_pv_usd",
    )
    a.assert_money(
        by_type["MODIFICATION"]["npv_usd"], NPV_MOD_NPV_DELAY_STRESSED, "MODIFICATION npv"
    )
    a.assert_money(by_type["NOTE_SALE"]["npv_usd"], NPV_NOTE_NPV_DELAY_STRESSED, "NOTE_SALE npv")
    a.assert_money(
        by_type["FORECLOSURE"]["npv_usd"], NPV_FORECLOSURE_NPV_DELAY_STRESSED, "FORECLOSURE npv"
    )
    assert by_type["NOTE_SALE"]["rank"] == 1
    assert by_type["MODIFICATION"]["rank"] == 2
    assert by_type["FORECLOSURE"]["rank"] == 3
    assert built["plan"]["recommended_alternative_id"] == by_type["NOTE_SALE"]["id"]


def test_the_discounting_basis_flips_which_alternative_is_recommended(api):
    """The same cash flows recommend different alternatives under the two bases.

    The PRD: "the `npv_basis`, which selects the discounting variant and
    defaults to `CONTRACTUAL`, its only alternative being `DELAY_STRESSED`."

    Design: Difficulty/dual_variant_calc/workout_npv_contractual_versus_delay_stressed_recommendation_flip
    """
    contractual = _scored_plan_on_a_fresh_loan(api, "CONTRACTUAL", "L-C01")
    stressed = _scored_plan_on_a_fresh_loan(api, "DELAY_STRESSED", "L-D01")

    contractual_types = _alternatives_by_type(api, contractual["plan_id"])
    stressed_types = _alternatives_by_type(api, stressed["plan_id"])

    contractual_winner = next(
        t for t, row in contractual_types.items() if row["rank"] == 1
    )
    stressed_winner = next(t for t, row in stressed_types.items() if row["rank"] == 1)
    assert contractual_winner == "MODIFICATION"
    assert stressed_winner == "NOTE_SALE"
    assert contractual_winner != stressed_winner
