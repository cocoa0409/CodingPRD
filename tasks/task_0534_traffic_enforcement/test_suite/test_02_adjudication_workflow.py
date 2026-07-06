"""Citation branching, adjudication outcomes, and payment reversal cycles (depth).

Translates the non_linear_state_machine difficulty instances and related corner
consistency instances.
"""
import pytest
from test_helpers import (
    get_success_data,
    setup_hearing_scheduled, setup_paid_citation,
    rule_hearing, set_clock, initiate_payment, settle_to_cleared,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]


def test_hearing_dismissed_zeroes_amount_and_upholds_contest(api):
    """PRD §3.5: "**`DISMISSED`**: the citation is thrown out. The citation
    transitions `HEARING_SCHEDULED → ADJUDICATED_DISMISSED`, which is terminal, the
    hearing's `outcome` becomes `DISMISSED`, and the contest moves `SCHEDULED →
    UPHELD` (the contest is upheld because the citation is dismissed)."
    PRD §3.5: "As compensation, the citation's `adjudicated_amount_cents` is set to
    zero and its `escalation_stage` is set to `NONE`, so the owner owes nothing."

    Design: Difficulty/non_linear_state_machine/citation_branching_contest_hearing_outcomes
    """
    ctx = setup_hearing_scheduled(ground="SIGNAL_MALFUNCTION")
    cit = ctx["citation"]
    hearing = ctx["hearing"]
    contest = ctx["contest"]
    set_clock("2026-05-15T11:00:00Z")
    rule_hearing(hearing["id"], "DISMISSED", hearing["version"], adjudicator_ref="adj-9")
    updated = get_success_data(api.get_citation(cit["id"], PA))
    updated_contest = get_success_data(api.get_contest(contest["id"], PA))
    assert updated["status"] == "ADJUDICATED_DISMISSED"
    assert updated["adjudicated_amount_cents"] == 0
    assert updated_contest["status"] == "UPHELD"


def test_hearing_reduced_branch_recomputes_amount(api):
    """PRD §3.5: "On a valid reduction the citation transitions `HEARING_SCHEDULED →
    ADJUDICATED_UPHELD` (the owner remains liable, but at the reduced amount), the
    hearing's `outcome` becomes `REDUCED`, and the contest moves `SCHEDULED →
    DISMISSED`. The citation's `adjudicated_amount_cents` is recomputed as the
    adjudicator's `reduced_amount_cents` plus the program's `admin_fee_cents`."

    Design: Difficulty/non_linear_state_machine/citation_branching_contest_hearing_outcomes
    """
    ctx = setup_hearing_scheduled()
    cit = ctx["citation"]
    hearing = ctx["hearing"]
    set_clock("2026-05-15T11:00:00Z")
    rule_hearing(hearing["id"], "REDUCED", hearing["version"],
                 adjudicator_ref="adj-9", reduced_amount_cents=4000)
    updated = get_success_data(api.get_citation(cit["id"], PA))
    assert updated["status"] == "ADJUDICATED_UPHELD"
    assert updated["adjudicated_amount_cents"] == 6500


def test_hearing_upheld_leaves_full_amount(api):
    """PRD §3.5: "**`UPHELD`**: the citation is liable at the full statutory amount.
    The citation transitions `HEARING_SCHEDULED → ADJUDICATED_UPHELD`, its
    `adjudicated_amount_cents` is set to its `assessed_amount_cents` (the fine stands
    unchanged, surcharge included), the hearing's `outcome` becomes `UPHELD`, and the
    contest moves `SCHEDULED → DISMISSED`."

    Design: Corner/consistency_model/adjudicated_uphold_amount_stands_immediate
    """
    ctx = setup_hearing_scheduled()
    cit = ctx["citation"]
    hearing = ctx["hearing"]
    contest = ctx["contest"]
    set_clock("2026-05-15T11:00:00Z")
    rule_hearing(hearing["id"], "UPHELD", hearing["version"], adjudicator_ref="adj-9")
    updated = get_success_data(api.get_citation(cit["id"], PA))
    updated_contest = get_success_data(api.get_contest(contest["id"], PA))
    assert updated["status"] == "ADJUDICATED_UPHELD"
    assert updated["adjudicated_amount_cents"] == 12500
    assert updated_contest["status"] == "DISMISSED"


def test_payment_reversal_reverts_paid_citation_to_cited(api):
    """PRD §3.7: "If the citation had reached `PAID`, reversal is a compensation
    cascade: the citation is reverted to the owed state it held before payment — to
    `ADJUDICATED_UPHELD` if it had a ruling, otherwise to `CITED` — and the vendor
    share that was accrued for this citation is de-accrued by exactly the same amount
    that was previously added, with the contract's `accrued_vendor_share_cents`
    floored at zero."

    Design: Difficulty/non_linear_state_machine/payment_reversal_cycle_repaids_citation
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    cit = ctx["citation"]
    payment = ctx["payment"]
    vc = ctx["vendor_contract"]
    reversed_pay = get_success_data(api.reverse_payment(payment["id"], PA))
    updated = get_success_data(api.get_citation(cit["id"], PA))
    updated_vc = get_success_data(api.get_vendor_contract(vc["id"], PA))
    assert reversed_pay["status"] == "REVERSED"
    assert updated["status"] == "CITED"
    assert updated["amount_paid_cents"] == 0
    assert updated_vc["accrued_vendor_share_cents"] == 0


def test_payment_reversal_repayable_after_reversion(api):
    """PRD §3.7: "This clearing-to-`PAID` transition is defined from `CITED`, from
    `ADJUDICATED_UPHELD`, and from `DELINQUENT`; reaching `PAID` from any of those
    states recomputes `amount_paid_cents` and accrues the vendor revenue share
    described next."

    Design: Difficulty/non_linear_state_machine/payment_reversal_cycle_repaids_citation
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    cit = ctx["citation"]
    payment = ctx["payment"]
    # Reverse back to CITED, then a fresh payment can drive it to PAID again.
    get_success_data(api.reverse_payment(payment["id"], PA))
    reverted = get_success_data(api.get_citation(cit["id"], PA))
    assert reverted["status"] == "CITED"
    new_payment = initiate_payment(cit["id"], 12500)
    settle_to_cleared(new_payment["id"])
    repaid = get_success_data(api.get_citation(cit["id"], PA))
    assert repaid["status"] == "PAID"
    assert repaid["amount_paid_cents"] == 12500
