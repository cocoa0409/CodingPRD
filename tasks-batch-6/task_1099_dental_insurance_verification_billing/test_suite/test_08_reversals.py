"""Compensating reversals conserve the benefit pool and the patient dues ledger.

Difficulty: compensating_invariant (x2).
"""
from test_helpers import (
    get_success_data, make_biller_headers, make_manager_headers, make_patient_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as fac


# --------------------------------------------------------------------------
# compensating_invariant / insurance_reversal_conserves_benefits_pool
# --------------------------------------------------------------------------
def test_insurance_reversal_restores_benefits_pool(api):
    """PRD §2.10 / §3.7: "Reversing an insurance payment restores the coverage's
    `benefits_used_cents` and `deductible_met_cents` to their pre-posting values."

    Design: Difficulty/compensating_invariant/insurance_reversal_conserves_benefits_pool
    """
    sc, _claim, payment = fx.adjudicated_crown_claim(api)
    fx.get_success_data(api.reverse_payment(payment["id"], make_manager_headers("mgr_bob")))
    coverage = get_success_data(api.get_coverage(sc["coverage"]["id"], make_biller_headers()))
    assert coverage["benefits_used_cents"] == 0, \
        f"expected 0, got {coverage['benefits_used_cents']}"
    assert coverage["deductible_met_cents"] == 0, \
        f"expected 0, got {coverage['deductible_met_cents']}"


def test_insurance_reversal_rolls_back_claim_and_patient(api):
    """PRD §3.7: "reverts the claim's `paid_insurance_cents` and
    `final_patient_portion_cents`, returns the claim to `SUBMITTED`, and restores
    the patient's `balance_cents`."

    Design: Difficulty/compensating_invariant/insurance_reversal_conserves_benefits_pool
    """
    sc, claim, payment = fx.adjudicated_crown_claim(api)
    fx.get_success_data(api.reverse_payment(payment["id"], make_manager_headers("mgr_bob")))
    reverted = get_success_data(api.get_claim(claim["id"], make_biller_headers()))
    assert reverted["status"] == "SUBMITTED", f"expected SUBMITTED, got {reverted['status']}"
    assert reverted["paid_insurance_cents"] == 0, \
        f"expected 0, got {reverted['paid_insurance_cents']}"
    patient = get_success_data(api.get_patient(sc["patient"]["id"], make_biller_headers()))
    assert patient["balance_cents"] == 0, f"expected 0, got {patient['balance_cents']}"


# --------------------------------------------------------------------------
# compensating_invariant / patient_payment_reversal_conserves_patient_dues
# --------------------------------------------------------------------------
def _patient_payment_reversed_setup(api):
    """Adjudicated crown claim (patient portion 72500); patient pays 72500 (claim
    CLOSED); returns (pid, claim_id, patient_payment_id)."""
    sc, claim, _pay = fx.adjudicated_crown_claim(api)
    pid = sc["patient"]["id"]
    ppay = get_success_data(api.create_payment(
        fac.create_payment_payload(pid, "PATIENT", 72500, claim_id=claim["id"]),
        make_patient_headers(pid)))
    return pid, claim["id"], ppay["id"]


def test_patient_payment_reversal_restores_balance(api):
    """PRD §3.7: "Reversing a patient payment subtracts its `amount_cents` back
    out of the claim's `patient_paid_cents` and adds it back to the patient's
    `balance_cents`."

    Design: Difficulty/compensating_invariant/patient_payment_reversal_conserves_patient_dues
    """
    pid, _claim_id, ppay_id = _patient_payment_reversed_setup(api)
    fx.get_success_data(api.reverse_payment(ppay_id, make_manager_headers("mgr_bob")))
    patient = get_success_data(api.get_patient(pid, make_biller_headers()))
    assert patient["balance_cents"] == 72500, \
        f"expected 72500, got {patient['balance_cents']}"


def test_patient_payment_reversal_reopens_claim(api):
    """PRD §3.7: "if the claim had been `CLOSED` by that payment it returns to its
    prior adjudicated state."

    Design: Difficulty/compensating_invariant/patient_payment_reversal_conserves_patient_dues
    """
    _pid, claim_id, ppay_id = _patient_payment_reversed_setup(api)
    fx.get_success_data(api.reverse_payment(ppay_id, make_manager_headers("mgr_bob")))
    claim = get_success_data(api.get_claim(claim_id, make_biller_headers()))
    assert claim["patient_paid_cents"] == 0, \
        f"expected 0, got {claim['patient_paid_cents']}"
    assert claim["status"] == "ADJUDICATED", f"expected ADJUDICATED, got {claim['status']}"
