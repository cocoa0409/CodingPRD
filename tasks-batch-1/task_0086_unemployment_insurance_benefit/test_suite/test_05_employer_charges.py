"""Employer charges: protest/relieve compensation (reserve restored exactly,
no drift) and the entity-backed ownership gate on protest."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_two_employer_eligible_claim, get_charge_for_employer,
    create_employer, file_week, adjudicate_week, pay_week,
    make_employer_headers,
    assert_employer, assert_employer_charge,
    TEST_USERS,
)

ADJ = TEST_USERS["adjudicator_headers"]
BPO = TEST_USERS["benefit_payment_officer_headers"]


def _paid_two_employer_with_protested_x():
    """Two-employer claim D, week paid (X charged 6389), Emp X's charge PROTESTED
    by Emp X. Returns (scenario, charge_x_after_protest)."""
    scenario = make_two_employer_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    charge_x = get_charge_for_employer(scenario["employer_x"]["id"])
    protested = get_success_data(api_client.protest_employer_charge(
        charge_x["id"], {}, make_employer_headers(scenario["employer_x"]["id"])))
    scenario["charge_x"] = charge_x
    return scenario, protested


# ── Difficulty: compensating_invariant / charge_relieve_restores_employer_reserve_exactly ──

def test_relieve_restores_reserve_to_pre_charge_value(api):
    """PRD §3.9: "An Adjudicator then relieves a protested charge by supplying a
    relief_reason ... moving it PROTESTED → RELIEVED. Relief records the
    relief_reason, credits the employer's reserve_account_balance_cents back by the
    charge's charge_amount_cents — reversing the original posting debit so the
    reserve returns to exactly its pre-charge value".

    Design: Difficulty/compensating_invariant/charge_relieve_restores_employer_reserve_exactly
    """
    # Emp X charged 6389 (reserve 100000000 -> 99993611), charge PROTESTED, then
    # RELIEVED -> reserve credited back to exactly 100000000.
    scenario, protested = _paid_two_employer_with_protested_x()
    relieved = get_success_data(api_client.relieve_employer_charge(
        protested["id"], {"relief_reason": "MISCONDUCT_DISCHARGE"}, ADJ))
    assert_employer_charge(relieved)
    emp_x = get_success_data(api_client.get_employer(scenario["employer_x"]["id"], ADJ))
    assert relieved["status"] == "RELIEVED"
    assert emp_x["reserve_account_balance_cents"] == 100000000
    assert emp_x["charge_protest_count"] == 0


def test_protest_then_relieve_protest_count_returns_to_zero(api):
    """PRD §3.9: "Protesting increments that employer's charge_protest_count by one
    and increments the charge's version".
    PRD §3.9: "decrements the employer's charge_protest_count by one, and increments
    the charge's version".

    Design: Difficulty/compensating_invariant/charge_relieve_restores_employer_reserve_exactly
    """
    scenario, protested = _paid_two_employer_with_protested_x()
    assert protested["status"] == "PROTESTED"
    emp_x_protested = get_success_data(
        api_client.get_employer(scenario["employer_x"]["id"], ADJ))
    assert emp_x_protested["charge_protest_count"] == 1
    get_success_data(api_client.relieve_employer_charge(
        protested["id"], {"relief_reason": "QUIT_WITHOUT_CAUSE"}, ADJ))
    emp_x = get_success_data(api_client.get_employer(scenario["employer_x"]["id"], ADJ))
    assert emp_x["charge_protest_count"] == 0
    assert emp_x["reserve_account_balance_cents"] == 100000000


# ── Corner: rbac / employer_cannot_protest_others_charge ──

def test_employer_cannot_protest_charge_it_does_not_own(api):
    """PRD §2.1: "In particular, an employer may only protest an EmployerCharge
    whose employer_id equals its own X-User-ID."

    Design: Corner/rbac/employer_cannot_protest_others_charge
    """
    # A third employer Z (not on the claim's wage base, does not own X's charge)
    # attempts to protest X's charge.
    scenario = make_two_employer_eligible_claim()
    emp_z = create_employer(experience_rate=0.04)
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    charge_x = get_charge_for_employer(scenario["employer_x"]["id"])
    res = api.protest_employer_charge(
        charge_x["id"], {}, make_employer_headers(emp_z["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
