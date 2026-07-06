"""Void cascade, payment-reversal cascade, and conserved-quantity invariants (depth).

Translates the transitive_cascade and compensating_invariant difficulty instances.
"""
import pytest
from test_helpers import (
    get_success_data,
    setup_hearing_scheduled, setup_cited_citation, setup_paid_citation,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]


def test_reversal_cascade_depaids_citation_and_deaccrues_vendor(api):
    """PRD §3.7: "If the citation had reached `PAID`, reversal is a compensation
    cascade: the citation is reverted to the owed state it held before payment — to
    `ADJUDICATED_UPHELD` if it had a ruling, otherwise to `CITED` — and the vendor
    share that was accrued for this citation is de-accrued by exactly the same amount
    that was previously added, with the contract's `accrued_vendor_share_cents`
    floored at zero."

    Design: Difficulty/transitive_cascade/reversal_cascades_citation_and_vendor_share
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    cit = ctx["citation"]
    payment = ctx["payment"]
    vc = ctx["vendor_contract"]
    get_success_data(api.reverse_payment(payment["id"], PA))
    updated_cit = get_success_data(api.get_citation(cit["id"], PA))
    updated_vc = get_success_data(api.get_vendor_contract(vc["id"], PA))
    assert updated_cit["status"] == "CITED"
    assert updated_cit["amount_paid_cents"] == 0
    assert updated_vc["accrued_vendor_share_cents"] == 0


def test_reversal_recomputes_amount_paid_downward(api):
    """PRD §3.7: "Reversal requires the payment to be `CLEARED` and transitions it
    `CLEARED → REVERSED`. It recomputes the citation's `amount_paid_cents`
    downward."

    Design: Difficulty/transitive_cascade/reversal_cascades_citation_and_vendor_share
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    cit = ctx["citation"]
    payment = ctx["payment"]
    assert cit["amount_paid_cents"] == 12500
    get_success_data(api.reverse_payment(payment["id"], PA))
    updated_cit = get_success_data(api.get_citation(cit["id"], PA))
    assert updated_cit["amount_paid_cents"] == 0


def test_void_conserves_zero_owed(api):
    """PRD §3.8: "A successful void transitions the citation to `VOID`, which is
    terminal, and sets its `adjudicated_amount_cents` to zero so that nothing is
    owed."

    Design: Difficulty/compensating_invariant/void_conserves_zero_owed_and_no_collection
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    assert cit["adjudicated_amount_cents"] == 12500
    voided = get_success_data(api.void_citation(cit["id"], PA))
    assert voided["status"] == "VOID"
    assert voided["adjudicated_amount_cents"] == 0


def test_void_leaves_nothing_collectable(api):
    """PRD §3.6: "A citation that has been dismissed on adjudication or voided has an
    `adjudicated_amount_cents` of zero and therefore owes zero."

    Design: Difficulty/compensating_invariant/void_conserves_zero_owed_and_no_collection
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    get_success_data(api.void_citation(cit["id"], PA))
    # A void citation owes zero — a payment against it is refused (PRD §3.7).
    from test_helpers import create_payment_payload, validate_error
    res = api.create_payment(cit["id"], create_payment_payload(5000, "CARD"), PA)
    validate_error(res, "ERR_NOTHING_OWED")


def test_reversal_conserves_vendor_accrued_share(api):
    """PRD §3.7: "the vendor share that was accrued for this citation is de-accrued
    by exactly the same amount that was previously added, with the contract's
    `accrued_vendor_share_cents` floored at zero."

    Design: Difficulty/compensating_invariant/reversal_conserves_vendor_accrued_share
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    payment = ctx["payment"]
    vc = ctx["vendor_contract"]
    accrued_before = get_success_data(api.get_vendor_contract(vc["id"], PA))
    assert accrued_before["accrued_vendor_share_cents"] == 3000
    get_success_data(api.reverse_payment(payment["id"], PA))
    accrued_after = get_success_data(api.get_vendor_contract(vc["id"], PA))
    assert accrued_after["accrued_vendor_share_cents"] == 0


def test_vendor_accrual_forward_then_reverse_no_drift(api):
    """PRD §3.7: "On reaching `PAID`, the applied share is added to the contract's
    `accrued_vendor_share_cents`, which is surfaced for audit and never goes below
    zero."

    Design: Difficulty/compensating_invariant/reversal_conserves_vendor_accrued_share
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    payment = ctx["payment"]
    vc = ctx["vendor_contract"]
    reversed_pay = get_success_data(api.reverse_payment(payment["id"], PA))
    assert reversed_pay["status"] == "REVERSED"
    final_vc = get_success_data(api.get_vendor_contract(vc["id"], PA))
    assert final_vc["accrued_vendor_share_cents"] == 0
