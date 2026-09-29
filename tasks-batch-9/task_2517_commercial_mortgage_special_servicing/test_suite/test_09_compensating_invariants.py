"""Compensating operations that restore a conserved ledger exactly, while
deliberately leaving one downstream judgement uncompensated.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ADVANCE_A_INTEREST_AUG,
    ADVANCE_B_INTEREST_AUG,
    ADVANCE_C_INTEREST_AUG,
    ARA_ONE_CENT_AMOUNT,
    ARA_ONE_CENT_CREDIT,
    ARA_UPDATE_PERCENTAGE,
    CONTROL_NOTIONAL_ONE_CENT_BELOW,
    FEE_STATED_PRINCIPAL_BASIS,
    GROSS_APPRAISED_BASIS,
    PI_OBLIGATION_NO_ARA,
    PI_OBLIGATION_WITH_ARA_ONE_CENT,
)
from test_helpers.test_users import ASSET_MANAGER, COMMITTEE_OFFICER, MASTER_SERVICER


# ==========================================================================
# The advance principal ledger, held in two places at once
# ==========================================================================
def _three_advances_with_the_last_deemed_nonrecoverable(api):
    """440,000.00 of advance principal, of which 90,000.00 is written off."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-A1"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-A01", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=lambda client, loan_id: fx.record_transfer_event(
            client,
            loan_id,
            occurred_on="2026-07-01T00:00:00Z",
            evidence_note="two missed debt service payments",
        ),
    )
    advance_a = fx.record_advance(
        api,
        built["loan_id"],
        advance_type="TAX_INSURANCE_ADVANCE",
        amount_usd=200000,
        advanced_on="2026-02-01T00:00:00Z",
    )
    advance_b = fx.record_advance(
        api,
        built["loan_id"],
        advance_type="PROPERTY_PROTECTION_ADVANCE",
        amount_usd=150000,
        advanced_on="2026-04-01T00:00:00Z",
    )
    advance_c = fx.record_advance(
        api,
        built["loan_id"],
        advance_type="TAX_INSURANCE_ADVANCE",
        amount_usd=90000,
        advanced_on="2026-06-01T00:00:00Z",
    )
    built["advance_a_id"] = advance_a["id"]
    built["advance_b_id"] = advance_b["id"]
    built["advance_c_id"] = advance_c["id"]
    return built


def _deem_nonrecoverable(api, advance_id):
    return validate_success(
        api.set_advance_status(
            advance_id,
            f.status_payload(
                "DEEMED_NONRECOVERABLE",
                reversal_reason="appraised value will not support recovery of this advance",
            ),
            COMMITTEE_OFFICER,
        )
    )


def _reverse(api, advance_id, reversal_reason):
    return api.set_advance_status(
        advance_id,
        f.status_payload("REVERSED", reversal_reason=reversal_reason),
        MASTER_SERVICER,
    )


def test_the_three_advances_accrue_thirty_over_three_sixty_interest_to_the_clock(api):
    """Each advance reads back the day count its funding date implies.

    The PRD: "Otherwise, take the advance's unreimbursed principal — its
    `amount_usd` less its `reimbursed_principal_usd` — multiply by the trust's
    `advance_interest_rate_pct` divided by one hundred, multiply by the day count,
    divide by three hundred and sixty, and round half up to two decimal places."

    Design: Difficulty/compensating_invariant/advance_reversal_restores_advance_principal_ledger_but_not_the_nonrecoverable_flag
    """
    built = _three_advances_with_the_last_deemed_nonrecoverable(api)

    for advance_id, expected in (
        (built["advance_a_id"], ADVANCE_A_INTEREST_AUG),
        (built["advance_b_id"], ADVANCE_B_INTEREST_AUG),
        (built["advance_c_id"], ADVANCE_C_INTEREST_AUG),
    ):
        advance = validate_success(api.get_advance(advance_id, MASTER_SERVICER))
        a.assert_money(advance["accrued_interest_usd"], expected, "accrued_interest_usd")
        assert advance["interest_accrued_through"].startswith("2026-08-01")
        a.assert_status(advance, "OUTSTANDING")

    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan["advances_outstanding_usd"], 440000.00, "advances_outstanding_usd")
    trust = fx.read_trust(api, built["trust_id"], MASTER_SERVICER)
    a.assert_money(
        trust["total_advances_outstanding_usd"],
        440000.00,
        "total_advances_outstanding_usd",
    )


def test_a_nonrecoverable_determination_leaves_both_ledgers_and_no_loss(api):
    """The written-off principal leaves both ledgers without becoming a loss.

    The PRD: "The unreimbursed principal leaves both the loan's
    `advances_outstanding_usd` and the trust's `total_advances_outstanding_usd`, but
    it is emphatically **not** returned to the borrower's obligation — the trust has
    simply absorbed it."

    Design: Difficulty/compensating_invariant/advance_reversal_restores_advance_principal_ledger_but_not_the_nonrecoverable_flag
    """
    built = _three_advances_with_the_last_deemed_nonrecoverable(api)
    deemed = _deem_nonrecoverable(api, built["advance_c_id"])
    a.assert_status(deemed, "DEEMED_NONRECOVERABLE")
    assert deemed["nonrecoverable_determined_on"].startswith("2026-08-01")

    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan["advances_outstanding_usd"], 350000.00, "advances_outstanding_usd")
    a.assert_money(loan["realized_loss_usd"], 0.00, "realized_loss_usd")
    trust = fx.read_trust(api, built["trust_id"], MASTER_SERVICER)
    a.assert_money(
        trust["total_advances_outstanding_usd"],
        350000.00,
        "total_advances_outstanding_usd",
    )


def test_the_compensation_is_unavailable_once_the_advance_is_terminal(api):
    """A nonrecoverable advance can no longer be reversed at all.

    The PRD: "An advance's status may be `OUTSTANDING`, `PARTIALLY_REIMBURSED`,
    `REIMBURSED`, `DEEMED_NONRECOVERABLE` or `REVERSED`, the last three being
    terminal."

    Design: Difficulty/compensating_invariant/advance_reversal_restores_advance_principal_ledger_but_not_the_nonrecoverable_flag
    """
    built = _three_advances_with_the_last_deemed_nonrecoverable(api)
    _deem_nonrecoverable(api, built["advance_c_id"])

    response = _reverse(
        api, built["advance_c_id"], "attempt to undo a nonrecoverable determination"
    )
    validate_error(response, e.ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_advance(built["advance_c_id"], MASTER_SERVICER))
    a.assert_status(unchanged, "DEEMED_NONRECOVERABLE")


def test_reversing_every_advance_restores_both_ledgers_to_zero(api):
    """The conserved quantity lands back on its pre-advance reading exactly.

    The PRD: "On reversal, `accrued_interest_usd` is zeroed, and the loan's
    `advances_outstanding_usd` and the trust's `total_advances_outstanding_usd`
    return to exactly the values they held before the advance existed."

    Design: Difficulty/compensating_invariant/advance_reversal_restores_advance_principal_ledger_but_not_the_nonrecoverable_flag
    """
    built = _three_advances_with_the_last_deemed_nonrecoverable(api)
    _deem_nonrecoverable(api, built["advance_c_id"])

    reversed_a = validate_success(
        _reverse(
            api,
            built["advance_a_id"],
            "advance was funded from the wrong servicing account",
        )
    )
    a.assert_status(reversed_a, "REVERSED")
    a.assert_money(reversed_a["accrued_interest_usd"], 0.00, "accrued_interest_usd")
    a.assert_money(reversed_a["reimbursed_principal_usd"], 0.00, "reimbursed_principal_usd")
    a.assert_money(reversed_a["reimbursed_interest_usd"], 0.00, "reimbursed_interest_usd")

    midway = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(midway["advances_outstanding_usd"], 150000.00, "advances_outstanding_usd")

    reversed_b = validate_success(
        _reverse(api, built["advance_b_id"], "duplicate property protection disbursement")
    )
    a.assert_status(reversed_b, "REVERSED")
    a.assert_money(reversed_b["accrued_interest_usd"], 0.00, "accrued_interest_usd")

    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan["advances_outstanding_usd"], 0.00, "advances_outstanding_usd")
    a.assert_money(loan["realized_loss_usd"], 0.00, "realized_loss_usd")
    trust = fx.read_trust(api, built["trust_id"], MASTER_SERVICER)
    a.assert_money(
        trust["total_advances_outstanding_usd"], 0.00, "total_advances_outstanding_usd"
    )


def test_the_restored_ledger_does_not_unblock_new_advances(api):
    """The credit judgement survives the reversal of every other advance.

    The PRD: "The second guard is blunter: if **any** advance on the loan has been
    deemed non-recoverable, no further advance of **any** type may be created, and
    the attempt is refused with `ERR_NONRECOVERABLE_ADVANCE_OUTSTANDING`."

    Design: Difficulty/compensating_invariant/advance_reversal_restores_advance_principal_ledger_but_not_the_nonrecoverable_flag
    """
    built = _three_advances_with_the_last_deemed_nonrecoverable(api)
    _deem_nonrecoverable(api, built["advance_c_id"])
    validate_success(
        _reverse(
            api,
            built["advance_a_id"],
            "advance was funded from the wrong servicing account",
        )
    )
    validate_success(
        _reverse(api, built["advance_b_id"], "duplicate property protection disbursement")
    )
    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan["advances_outstanding_usd"], 0.00, "advances_outstanding_usd")

    response = api.create_advance(
        f.advance_payload(
            built["loan_id"],
            advance_type="TAX_INSURANCE_ADVANCE",
            amount_usd=10000,
            advanced_on="2026-08-01T00:00:00Z",
        ),
        MASTER_SERVICER,
    )
    validate_error(response, e.ERR_NONRECOVERABLE_ADVANCE_OUTSTANDING, 409)


# ==========================================================================
# The controlling class notional identity, and the consent it cannot restore
# ==========================================================================
def _control_terminated_by_an_effective_reduction(api):
    """An 8,000,000.00 controlling class driven one cent below its threshold."""
    trust = fx.create_small_controlling_class_trust(api, deal_name="CMBS 2026-C1")
    loan = fx.create_loan(
        api,
        trust["id"],
        loan_number="L-C01",
        note_rate_pct=6.5,
        maturity_date="2028-06-01T00:00:00Z",
    )
    fx.record_transfer_event(
        api,
        loan["id"],
        occurred_on="2026-07-01T00:00:00Z",
        evidence_note="two missed debt service payments",
    )
    fx.transfer_to_special_servicing(api, loan["id"])
    fx.accepted_appraisal(api, loan["id"], value_usd=14999999)
    reduction = fx.provisional_reduction(api, loan["id"])

    built = fx.scored_plan(
        api, loan["id"], alternative_builders=[fx.add_modification_alternative]
    )
    fx.recommend_plan(
        api, built["plan_id"], built["plan"]["recommended_alternative_id"]
    )
    consultation = fx.issue_plan_consultation(api, trust["id"], built["plan_id"])

    return {
        "trust_id": trust["id"],
        "loan_id": loan["id"],
        "reduction": reduction,
        "reduction_id": reduction["id"],
        "plan_id": built["plan_id"],
        "consultation_id": consultation["id"],
        "consultation": consultation,
    }


def test_the_provisional_reduction_carries_the_one_cent_arithmetic(api):
    """A 14,999,999 valuation gives a 6,000,000.90 reduction.

    The PRD: "When the `appraisal_type` is `UPDATE` or `INTERNAL_VALUATION`, the
    `calculation_basis` is `GROSS_APPRAISED_BASIS`: ninety percent of the raw
    `value_usd`, rounded half up to two decimal places, becomes
    `appraisal_credit_usd`."

    Design: Difficulty/compensating_invariant/ara_reversal_restores_controlling_class_notional_but_not_the_waived_consultation
    """
    scenario = _control_terminated_by_an_effective_reduction(api)
    reduction = scenario["reduction"]

    a.assert_status(reduction, GROSS_APPRAISED_BASIS, "calculation_basis")
    a.assert_money(
        reduction["deficiency_base_usd"], FEE_STATED_PRINCIPAL_BASIS, "deficiency_base_usd"
    )
    a.assert_money(
        reduction["appraisal_credit_usd"], ARA_ONE_CENT_CREDIT, "appraisal_credit_usd"
    )
    a.assert_money(reduction["ara_amount_usd"], ARA_ONE_CENT_AMOUNT, "ara_amount_usd")
    a.assert_ara_percentage(reduction["ara_percentage"], ARA_UPDATE_PERCENTAGE)

    trust = fx.read_trust(api, scenario["trust_id"], COMMITTEE_OFFICER)
    a.assert_money(trust["total_ara_usd"], 0.00, "total_ara_usd")
    a.assert_status(trust, "CONTROLLING", "control_status")


def test_making_it_effective_terminates_control_and_waives_the_consultation(api):
    """The four-link cascade lands the notional one cent below the threshold.

    The PRD: "Fourth — caused by the third — every consultation on that trust that
    is still `PENDING` with `rights_type` of `CONSENT_RIGHT` has its `rights_type`
    downgraded to `CONSULTATION_ONLY` and its status set to `WAIVED`, and every
    workout plan that was sitting in status `CONSULTATION` as the subject of one of
    those consultations advances to `CONSENT_SATISFIED`."

    Design: Difficulty/compensating_invariant/ara_reversal_restores_controlling_class_notional_but_not_the_waived_consultation
    """
    scenario = _control_terminated_by_an_effective_reduction(api)
    a.assert_status(scenario["consultation"], "CONSENT_RIGHT", "rights_type")

    effective = fx.make_reduction_effective(api, scenario["reduction_id"])
    a.assert_status(effective, "EFFECTIVE")
    assert effective["advance_reduction_applies"] is True

    loan = fx.read_loan(api, scenario["loan_id"], COMMITTEE_OFFICER)
    a.assert_money(loan["ara_amount_usd"], ARA_ONE_CENT_AMOUNT, "ara_amount_usd")
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        PI_OBLIGATION_WITH_ARA_ONE_CENT,
        "required_monthly_pi_advance_usd",
    )
    trust = fx.read_trust(api, scenario["trust_id"], COMMITTEE_OFFICER)
    a.assert_money(trust["total_ara_usd"], ARA_ONE_CENT_AMOUNT, "total_ara_usd")
    a.assert_money(
        trust["controlling_class_notional_usd"],
        CONTROL_NOTIONAL_ONE_CENT_BELOW,
        "controlling_class_notional_usd",
    )
    a.assert_status(trust, "CONSULTING_ONLY", "control_status")

    consultation = validate_success(
        api.get_consultation(scenario["consultation_id"], COMMITTEE_OFFICER)
    )
    a.assert_status(consultation, "WAIVED")
    a.assert_status(consultation, "CONSULTATION_ONLY", "rights_type")
    plan = validate_success(api.get_workout_plan(scenario["plan_id"], ASSET_MANAGER))
    a.assert_status(plan, "CONSENT_SATISFIED")


def test_reversal_walks_the_whole_cascade_backwards(api):
    """Every figure returns to its pre-effective reading and the identity holds.

    The PRD: "The trust's `total_ara_usd` returns to exactly the value it held
    before this reduction became effective, and `controlling_class_notional_usd` and
    `control_status` are recomputed from that restored total — so a trust that had
    dropped to `CONSULTING_ONLY` can return to `CONTROLLING`."

    Design: Difficulty/compensating_invariant/ara_reversal_restores_controlling_class_notional_but_not_the_waived_consultation
    """
    scenario = _control_terminated_by_an_effective_reduction(api)
    fx.make_reduction_effective(api, scenario["reduction_id"])

    reversed_reduction = validate_success(
        api.set_appraisal_reduction_status(
            scenario["reduction_id"],
            f.status_payload(
                "REVERSED",
                reversal_reason="appraiser withdrew the report after a scope-of-work error",
            ),
            COMMITTEE_OFFICER,
        )
    )
    a.assert_status(reversed_reduction, "REVERSED")
    assert reversed_reduction["advance_reduction_applies"] is False

    loan = fx.read_loan(api, scenario["loan_id"], COMMITTEE_OFFICER)
    a.assert_money(loan["ara_amount_usd"], 0.00, "ara_amount_usd")
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        PI_OBLIGATION_NO_ARA,
        "required_monthly_pi_advance_usd",
    )
    trust = fx.read_trust(api, scenario["trust_id"], COMMITTEE_OFFICER)
    a.assert_money(trust["total_ara_usd"], 0.00, "total_ara_usd")
    a.assert_money(
        trust["controlling_class_notional_usd"], 8000000.00, "controlling_class_notional_usd"
    )
    a.assert_status(trust, "CONTROLLING", "control_status")
    a.assert_controlling_class_identity(trust)


def test_reversal_does_not_retract_the_valuation_it_was_computed_from(api):
    """The accepted appraisal and the loan's mirrored value survive the reversal.

    The PRD: "Its `last_appraised_value_usd` mirrors the `value_usd` of the single
    `ACCEPTED` appraisal on the loan and is null when there is none."

    Design: Difficulty/compensating_invariant/ara_reversal_restores_controlling_class_notional_but_not_the_waived_consultation
    """
    scenario = _control_terminated_by_an_effective_reduction(api)
    fx.make_reduction_effective(api, scenario["reduction_id"])
    validate_success(
        api.set_appraisal_reduction_status(
            scenario["reduction_id"],
            f.status_payload(
                "REVERSED",
                reversal_reason="appraiser withdrew the report after a scope-of-work error",
            ),
            COMMITTEE_OFFICER,
        )
    )

    loan = fx.read_loan(api, scenario["loan_id"], COMMITTEE_OFFICER)
    a.assert_money(loan["last_appraised_value_usd"], 14999999.00, "last_appraised_value_usd")

    appraisal = validate_success(
        api.get_appraisal(scenario["reduction"]["appraisal_id"], ASSET_MANAGER)
    )
    a.assert_status(appraisal, "ACCEPTED")


def test_the_waived_consent_is_never_given_back(api):
    """Restoration does not un-waive, so the plan is approvable on a deemed consent.

    The PRD: "What restoration does **not** do is undo the past: consultations
    already `WAIVED` are not returned to `PENDING`, and rights already downgraded are
    not upgraded."

    Design: Difficulty/compensating_invariant/ara_reversal_restores_controlling_class_notional_but_not_the_waived_consultation
    """
    scenario = _control_terminated_by_an_effective_reduction(api)
    fx.make_reduction_effective(api, scenario["reduction_id"])
    validate_success(
        api.set_appraisal_reduction_status(
            scenario["reduction_id"],
            f.status_payload(
                "REVERSED",
                reversal_reason="appraiser withdrew the report after a scope-of-work error",
            ),
            COMMITTEE_OFFICER,
        )
    )

    consultation = validate_success(
        api.get_consultation(scenario["consultation_id"], COMMITTEE_OFFICER)
    )
    a.assert_status(consultation, "WAIVED")
    a.assert_status(consultation, "CONSULTATION_ONLY", "rights_type")
    a.assert_fields_null(consultation, "responded_at", "responded_by_user_id")

    approved = validate_success(
        api.set_workout_plan_status(
            scenario["plan_id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(approved, "APPROVED")


def test_the_compensation_is_not_repeatable(api):
    """REVERSED is terminal, so a second reversal changes nothing.

    The PRD: "the fourth status, `RECALCULATED`, is reached only by the system, and
    both `RECALCULATED` and `REVERSED` are terminal."

    Design: Difficulty/compensating_invariant/ara_reversal_restores_controlling_class_notional_but_not_the_waived_consultation
    """
    scenario = _control_terminated_by_an_effective_reduction(api)
    fx.make_reduction_effective(api, scenario["reduction_id"])
    validate_success(
        api.set_appraisal_reduction_status(
            scenario["reduction_id"],
            f.status_payload(
                "REVERSED",
                reversal_reason="appraiser withdrew the report after a scope-of-work error",
            ),
            COMMITTEE_OFFICER,
        )
    )

    response = api.set_appraisal_reduction_status(
        scenario["reduction_id"],
        f.status_payload(
            "REVERSED", reversal_reason="second attempt at the same compensation"
        ),
        COMMITTEE_OFFICER,
    )
    validate_error(response, e.ERR_INVALID_STATE_TRANSITION, 409)

    trust = fx.read_trust(api, scenario["trust_id"], COMMITTEE_OFFICER)
    a.assert_money(
        trust["controlling_class_notional_usd"], 8000000.00, "controlling_class_notional_usd"
    )
    a.assert_status(trust, "CONTROLLING", "control_status")
    loan = fx.read_loan(api, scenario["loan_id"], COMMITTEE_OFFICER)
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        PI_OBLIGATION_NO_ARA,
        "required_monthly_pi_advance_usd",
    )
