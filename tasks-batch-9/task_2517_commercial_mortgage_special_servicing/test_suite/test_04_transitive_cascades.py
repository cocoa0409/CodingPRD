"""Transitive cascades: one write that walks four causal links, in both
directions — control terminating as a reduction becomes effective, and control
surviving as a real-estate-owned asset is sold through the waterfall.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ARA_ONE_CENT_AMOUNT,
    ARA_REO_AMOUNT,
    ARA_REO_PERCENTAGE,
    CONTROL_NOTIONAL_ONE_CENT_BELOW,
    CONTROL_THRESHOLD_SMALL_TRUST,
    PI_OBLIGATION_REO,
    PI_OBLIGATION_WITH_ARA_ONE_CENT,
    REO_REMIC_DEADLINE,
    TRUST_NOTIONAL_AFTER_REO_ARA,
    WATERFALL_EXPENSES,
    WATERFALL_GROSS,
    WATERFALL_LIQUIDATION_FEE,
    WATERFALL_REALIZED_LOSS,
    WATERFALL_CONTROLLING_NOTIONAL,
    ADVANCE_A_INTEREST_OCT,
    ADVANCE_B_INTEREST_OCT,
)
from test_helpers.test_users import (
    ASSET_MANAGER,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    TRUSTEE,
)


# ==========================================================================
# A reduction becoming effective terminates control at the boundary
# ==========================================================================
def _trust_loan_plan_awaiting_consent(api):
    """An 8,000,000.00 controlling class, a 19,500,000.00 loan carrying a
    PROVISIONAL 6,000,000.90 reduction, and a plan sitting in CONSULTATION."""
    built = fx.loan_in_special_servicing(
        api,
        loan_overrides={"loan_number": "L-T01"},
        trust_overrides={
            "deal_name": "CMBS 2026-T1",
            "original_controlling_class_balance_usd": 8000000,
        },
    )
    fx.accepted_appraisal(api, built["loan_id"], value_usd=14999999)
    reduction = fx.provisional_reduction(api, built["loan_id"])

    plan = fx.scored_plan(api, built["loan_id"])
    fx.recommend_plan(api, plan["plan_id"], plan["plan"]["recommended_alternative_id"])
    consultation = fx.issue_plan_consultation(api, built["trust_id"], plan["plan_id"])

    return {
        "trust_id": built["trust_id"],
        "loan_id": built["loan_id"],
        "reduction_id": reduction["id"],
        "reduction": reduction,
        "plan_id": plan["plan_id"],
        "consultation_id": consultation["id"],
        "consultation": consultation,
    }


def test_making_a_reduction_effective_rewrites_the_loan_and_the_trust(api):
    """Links one and two: the loan's obligation shrinks and the trust's total
    appraisal reduction and notional are recomputed from it.

    The PRD: "First, the loan's `ara_amount_usd` is set to the reduction's
    `ara_amount_usd` and the loan's `required_monthly_pi_advance_usd` is
    recomputed. Second — caused by the first — the trust's `total_ara_usd` is
    recomputed, which in turn recomputes `controlling_class_notional_usd`."

    Design: Difficulty/transitive_cascade/appraisal_reduction_effective_four_link_control_termination_cascade
    """
    scenario = _trust_loan_plan_awaiting_consent(api)
    loan_before = fx.read_loan(api, scenario["loan_id"])
    trust_before = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_money(loan_before["ara_amount_usd"], 0.00, "ara_amount_usd before")
    a.assert_money(trust_before["total_ara_usd"], 0.00, "total_ara_usd before")

    effective = validate_success(
        api.set_appraisal_reduction_status(
            scenario["reduction_id"], f.status_payload("EFFECTIVE"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(effective, "EFFECTIVE")
    a.assert_money(effective["ara_amount_usd"], ARA_ONE_CENT_AMOUNT, "ara_amount_usd")
    assert effective["advance_reduction_applies"] is True
    assert effective["effective_on"].startswith("2026-08-01")
    assert effective["made_effective_by_user_id"] == "cmte-001"

    loan_after = fx.read_loan(api, scenario["loan_id"])
    a.assert_money(loan_after["ara_amount_usd"], ARA_ONE_CENT_AMOUNT, "loan ara_amount_usd")
    a.assert_money(
        loan_after["required_monthly_pi_advance_usd"],
        PI_OBLIGATION_WITH_ARA_ONE_CENT,
        "required_monthly_pi_advance_usd",
    )

    trust_after = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_money(trust_after["total_ara_usd"], ARA_ONE_CENT_AMOUNT, "total_ara_usd")
    a.assert_money(
        trust_after["controlling_class_notional_usd"],
        CONTROL_NOTIONAL_ONE_CENT_BELOW,
        "controlling_class_notional_usd",
    )
    a.assert_version_advanced_by(loan_before, loan_after, 1, "loan")
    a.assert_version_advanced_by(trust_before, trust_after, 1, "trust")


def test_the_recomputed_notional_one_cent_short_terminates_control(api):
    """Link three: the control test re-runs off the new notional.

    The PRD: "Third — caused by the second — the control test re-runs and may
    move the trust's `control_status` from `CONTROLLING` to `CONSULTING_ONLY`."

    Design: Difficulty/transitive_cascade/appraisal_reduction_effective_four_link_control_termination_cascade
    """
    scenario = _trust_loan_plan_awaiting_consent(api)
    before = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_status(before, "CONTROLLING", "control_status")

    fx.make_reduction_effective(api, scenario["reduction_id"])

    after = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_status(after, "CONSULTING_ONLY", "control_status")
    assert after["controlling_class_notional_usd"] < CONTROL_THRESHOLD_SMALL_TRUST, (
        "the recomputed notional must fall strictly below the 25% threshold"
    )
    a.assert_controlling_class_identity(after)


def test_control_termination_waives_the_pending_consultation_and_frees_its_plan(api):
    """Link four: the downgrade reaches an entity nobody wrote to.

    The PRD: "Fourth — caused by the third — every consultation on that trust
    that is still `PENDING` with `rights_type` of `CONSENT_RIGHT` has its
    `rights_type` downgraded to `CONSULTATION_ONLY` and its status set to
    `WAIVED`, and every workout plan that was sitting in status `CONSULTATION` as
    the subject of one of those consultations advances to `CONSENT_SATISFIED`."

    Design: Difficulty/transitive_cascade/appraisal_reduction_effective_four_link_control_termination_cascade
    """
    scenario = _trust_loan_plan_awaiting_consent(api)
    a.assert_status(scenario["consultation"], "PENDING")
    a.assert_status(scenario["consultation"], "CONSENT_RIGHT", "rights_type")

    fx.make_reduction_effective(api, scenario["reduction_id"])

    consultation = validate_success(
        api.get_consultation(scenario["consultation_id"], ASSET_MANAGER)
    )
    a.assert_status(consultation, "WAIVED")
    a.assert_status(consultation, "CONSULTATION_ONLY", "rights_type")

    plan = validate_success(api.get_workout_plan(scenario["plan_id"], ASSET_MANAGER))
    a.assert_status(plan, "CONSENT_SATISFIED")
    a.assert_status(plan, "CONSULTATION_ONLY", "consent_requirement")


# ==========================================================================
# The real-estate-owned sale runs the waterfall and keeps control
# ==========================================================================
def _reo_asset_under_contract(api):
    """The pinned disposition scenario, with the clock left at 2026-10-01."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    trust = fx.create_trust(
        api,
        deal_name="CMBS 2026-R2",
        original_controlling_class_balance_usd=8000000,
        liquidation_fee_rate_pct=1.0,
        advance_interest_rate_pct=5.0,
    )
    loan = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-R02",
        original_balance_usd=11000000,
        current_principal_balance_usd=10000000,
        accrued_unpaid_interest_usd=250000,
        securitization_value_usd=14000000,
    )
    fx.record_transfer_event(api, loan["id"], occurred_on="2026-05-15T00:00:00Z")
    fx.transfer_to_special_servicing(api, loan["id"])

    advances = fx.two_advances(api, loan["id"])
    fx.accepted_appraisal(
        api,
        loan["id"],
        value_usd=8000000,
        as_of_date="2026-06-01T00:00:00Z",
        ordered_on="2026-06-01T00:00:00Z",
    )
    reduction = fx.provisional_reduction(api, loan["id"])
    effective = fx.make_reduction_effective(api, reduction["id"])

    plan = fx.executed_plan(
        api,
        trust["id"],
        loan["id"],
        alternative_builders=[fx.add_foreclosure_alternative],
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    reo = fx.reo_under_contract(
        api, loan["id"], plan["plan_id"], acquired_on="2026-09-01T00:00:00Z"
    )
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    return {
        "trust_id": trust["id"],
        "loan_id": loan["id"],
        "advance_a_id": advances["advance_a"]["id"],
        "advance_b_id": advances["advance_b"]["id"],
        "reduction_id": reduction["id"],
        "reduction": effective,
        "plan_id": plan["plan_id"],
        "reo_id": reo["id"],
        "reo": reo,
    }


def _sell_the_asset(api, reo_id):
    return validate_success(
        api.set_reo_asset_status(
            reo_id,
            f.liquidation_payload(
                WATERFALL_GROSS,
                WATERFALL_EXPENSES,
                "2026-10-01T00:00:00Z",
                to_status="SOLD",
            ),
            COMMITTEE_OFFICER,
        )
    )


def test_the_sale_conjures_a_system_liquidation_fee_on_a_loan_nobody_wrote_to(api):
    """Link one: the fee accrual is created by the waterfall, not by a client.

    The PRD: "A `LIQUIDATION_FEE` fee accrual is created on the loan in status
    `ACCRUED` with `basis_amount_usd` equal to `gross_proceeds_usd`, `rate_pct`
    equal to the trust's `liquidation_fee_rate_pct`, `amount_usd` equal to the
    computed fee, and `accrued_by_user_id` recorded as the literal string
    `system`."

    Design: Difficulty/transitive_cascade/reo_sale_four_link_waterfall_and_control_restoration_cascade
    """
    scenario = _reo_asset_under_contract(api)
    a.assert_money(
        scenario["reduction"]["ara_amount_usd"], ARA_REO_AMOUNT, "ara_amount_usd"
    )
    a.assert_ara_percentage(scenario["reduction"]["ara_percentage"], ARA_REO_PERCENTAGE)
    assert scenario["reo"]["remic_disposition_deadline"].startswith(
        REO_REMIC_DEADLINE[:10]
    )
    assert not fx.fees_for_loan(api, scenario["loan_id"], "LIQUIDATION_FEE"), (
        "no liquidation fee may exist before the sale closes"
    )

    sold = _sell_the_asset(api, scenario["reo_id"])
    a.assert_status(sold, "SOLD")
    a.assert_money(sold["gross_sale_proceeds_usd"], WATERFALL_GROSS, "gross_sale_proceeds_usd")
    a.assert_money(sold["liquidation_expenses_usd"], WATERFALL_EXPENSES, "liquidation_expenses_usd")

    fees = fx.fees_for_loan(api, scenario["loan_id"], "LIQUIDATION_FEE")
    assert len(fees) == 1, "the waterfall creates exactly one liquidation fee accrual"
    fee = fees[0]
    a.assert_status(fee, "ACCRUED")
    assert fee["accrued_by_user_id"] == "system"
    a.assert_money(fee["basis_amount_usd"], WATERFALL_GROSS, "basis_amount_usd")
    a.assert_money(fee["amount_usd"], WATERFALL_LIQUIDATION_FEE, "amount_usd")


def test_the_sale_reimburses_both_advances_oldest_first_with_their_interest(api):
    """Link two: the advance ledger is settled interest-before-principal.

    The PRD: "**Interest is always paid before principal within a single
    advance**: pay the lesser of the available proceeds and the interest due,
    deduct that from the available proceeds, then pay the lesser of what remains
    and the principal due and deduct that too, adding both payments to
    `reimbursed_interest_usd` and `reimbursed_principal_usd` respectively."

    Design: Difficulty/transitive_cascade/reo_sale_four_link_waterfall_and_control_restoration_cascade
    """
    scenario = _reo_asset_under_contract(api)

    _sell_the_asset(api, scenario["reo_id"])

    advance_a = validate_success(api.get_advance(scenario["advance_a_id"], MASTER_SERVICER))
    a.assert_status(advance_a, "REIMBURSED")
    a.assert_money(
        advance_a["reimbursed_interest_usd"], ADVANCE_A_INTEREST_OCT, "advance A interest"
    )
    a.assert_money(advance_a["reimbursed_principal_usd"], 200000.00, "advance A principal")

    advance_b = validate_success(api.get_advance(scenario["advance_b_id"], MASTER_SERVICER))
    a.assert_status(advance_b, "REIMBURSED")
    a.assert_money(
        advance_b["reimbursed_interest_usd"], ADVANCE_B_INTEREST_OCT, "advance B interest"
    )
    a.assert_money(advance_b["reimbursed_principal_usd"], 150000.00, "advance B principal")

    loan = fx.read_loan(api, scenario["loan_id"])
    a.assert_money(loan["advances_outstanding_usd"], 0.00, "advances_outstanding_usd")
    trust = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_money(
        trust["total_advances_outstanding_usd"], 0.00, "total_advances_outstanding_usd"
    )


def test_the_sale_pays_interest_then_principal_and_writes_the_realized_loss(api):
    """Link three: the residue of principal becomes the realized loss.

    The PRD: "The loan's `realized_loss_usd` is that sum added to whatever
    `current_principal_balance_usd` remains, rounded half up to two decimal
    places, and the trust's `realized_loss_usd` increases by the loan's figure."

    Design: Difficulty/transitive_cascade/reo_sale_four_link_waterfall_and_control_restoration_cascade
    """
    scenario = _reo_asset_under_contract(api)

    _sell_the_asset(api, scenario["reo_id"])

    loan = fx.read_loan(api, scenario["loan_id"])
    a.assert_money(loan["accrued_unpaid_interest_usd"], 0.00, "accrued_unpaid_interest_usd")
    a.assert_money(
        loan["current_principal_balance_usd"],
        WATERFALL_REALIZED_LOSS,
        "current_principal_balance_usd",
    )
    a.assert_money(loan["realized_loss_usd"], WATERFALL_REALIZED_LOSS, "loan realized_loss_usd")

    trust = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_money(
        trust["realized_loss_usd"], WATERFALL_REALIZED_LOSS, "trust realized_loss_usd"
    )
    a.assert_money(
        trust["excess_liquidation_proceeds_usd"], 0.00, "excess_liquidation_proceeds_usd"
    )


def test_the_loss_replaces_the_reversed_reduction_instead_of_stacking_on_it(api):
    """Link four: the reduction is reversed so the same loss is not counted twice.

    The PRD: "Once the waterfall has run, one further cascade completes the
    disposition: the loan's `servicing_status` becomes `LIQUIDATED`, any
    appraisal reduction on the loan that was `EFFECTIVE` moves to `REVERSED`, the
    trust's `total_ara_usd` and `loans_in_special_servicing_count` are
    recomputed, and the control test re-runs against the newly recorded realized
    loss — which, depending on the numbers, can restore `CONTROLLING` or confirm
    `CONSULTING_ONLY`."

    Design: Difficulty/transitive_cascade/reo_sale_four_link_waterfall_and_control_restoration_cascade
    """
    scenario = _reo_asset_under_contract(api)
    trust_before = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_money(trust_before["total_ara_usd"], ARA_REO_AMOUNT, "total_ara_usd before")
    a.assert_money(
        trust_before["controlling_class_notional_usd"],
        TRUST_NOTIONAL_AFTER_REO_ARA,
        "controlling_class_notional_usd before",
    )

    _sell_the_asset(api, scenario["reo_id"])

    loan = fx.read_loan(api, scenario["loan_id"])
    a.assert_status(loan, "LIQUIDATED", "servicing_status")
    a.assert_money(loan["ara_amount_usd"], 0.00, "loan ara_amount_usd")
    a.assert_money(
        loan["required_monthly_pi_advance_usd"], 65000.00, "required_monthly_pi_advance_usd"
    )

    reduction = validate_success(
        api.get_appraisal_reduction(scenario["reduction_id"], COMMITTEE_OFFICER)
    )
    a.assert_status(reduction, "REVERSED")
    assert reduction["advance_reduction_applies"] is False

    trust_after = fx.read_trust(api, scenario["trust_id"], TRUSTEE)
    a.assert_money(trust_after["total_ara_usd"], 0.00, "total_ara_usd after")
    a.assert_money(
        trust_after["controlling_class_notional_usd"],
        WATERFALL_CONTROLLING_NOTIONAL,
        "controlling_class_notional_usd after",
    )
    a.assert_status(trust_after, "CONTROLLING", "control_status")
    assert trust_after["loans_in_special_servicing_count"] == 0
    a.assert_controlling_class_identity(trust_after)


def test_the_reimbursement_order_is_observable_in_the_advance_listing(api):
    """The waterfall's oldest-first order is the collection's declared order.

    The PRD: "advances are returned by `advanced_on` ascending with `created_at`
    ascending as the tie-break, which is exactly the order in which the
    liquidation waterfall reimburses them"

    Design: Difficulty/transitive_cascade/reo_sale_four_link_waterfall_and_control_restoration_cascade
    """
    scenario = _reo_asset_under_contract(api)

    rows, _ = validate_paginated(
        api.list_advances(MASTER_SERVICER, {"loan_id": scenario["loan_id"]})
    )
    assert a.ids_of(rows) == [scenario["advance_a_id"], scenario["advance_b_id"]]
    a.assert_ordered_by(rows, "advanced_on")

    _sell_the_asset(api, scenario["reo_id"])

    settled, _ = validate_paginated(
        api.list_advances(
            MASTER_SERVICER, {"loan_id": scenario["loan_id"], "status": "REIMBURSED"}
        )
    )
    assert a.ids_of(settled) == [scenario["advance_a_id"], scenario["advance_b_id"]]
