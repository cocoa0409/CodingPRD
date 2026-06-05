"""Proofs of claim: filing guards (creditor match, stay), the allow ledger sync
cascade through to the waterfall, allow idempotency, and not-found.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    register_debtor, register_creditor, register_trustee, open_case,
    submit_means_test, add_income_and_expense_schedules, add_debt, petition,
    setup_filed_case, setup_case_at_meeting_held, file_claim, allow_claim,
    schedule_meeting, hold_meeting, create_plan, file_plan, confirm_plan,
    record_payment, current_case_version,
    make_creditor_headers, make_trustee_headers, NON_EXISTENT_UUID,
)


def test_claim_filing_on_terminated_stay_rejected(api):
    """PRD §2.9: "Attempting either of these while the posture is TERMINATED is
    rejected with ERR_STAY_TERMINATED (HTTP 409)." PRD §3.6: "Filing a claim is a
    creditor collection action and is therefore blocked when the stay is
    TERMINATED, as described in §2.9."

    Design: Corner/validations/claim_filing_on_terminated_stay_rejected
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    creditor = register_creditor(name="Cr stay")
    trustee = register_trustee(name="T-stay")
    debt = add_debt(debtor, case, creditor, "UNSECURED", 70000)
    validate_success(api.dismiss_case(case["id"], make_trustee_headers(trustee["id"])), 200)

    res = api.create_claim({
        "case_id": case["id"], "debt_id": debt["id"],
        "filed_by_creditor_id": creditor["id"], "claimed_amount_cents": 70000,
    }, make_creditor_headers(creditor["id"]))
    validate_error(res, "ERR_STAY_TERMINATED")


def test_claim_allow_idempotency_second_allow_returns_invalid_state(api):
    """PRD §3.6: "Allowing a claim advances it from FILED to ALLOWED". The allow
    transition is defined only from FILED, so a second allow on an ALLOWED claim
    has no valid source state and is rejected with ERR_INVALID_STATE (HTTP 409).
    PRD §2.7: "the resource's state checked against the requested transition
    (ERR_INVALID_STATE, HTTP 409)."

    Design: Corner/state_machines/claim_allow_idempotency_second_allow_returns_invalid_state
    """
    debtor, trustee, case = setup_case_at_meeting_held(
        filed_chapter="CHAPTER_13", room_code="R-idem",
        scheduled_start="2026-09-02T09:00:00Z", scheduled_end="2026-09-02T10:00:00Z")
    creditor = register_creditor(name="Cr idem")
    # debt + claim must exist before the meeting in the design; here the case is at
    # MEETING_HELD with the stay ACTIVE-derived posture still permitting claim filing.
    debt = add_debt(debtor, case, creditor, "UNSECURED", 50000)
    claim = file_claim(creditor, case, debt, 50000)
    allow_claim(trustee, claim)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.allow_claim(claim["id"], t_headers)
    validate_error(res, "ERR_INVALID_STATE")
    claim_after = validate_success(api.get_claim(claim["id"], t_headers), 200)
    assert claim_after["allowed_amount_cents"] == 50000


def test_claim_allow_cascades_to_debt_and_distribution(api):
    """PRD §3.6: "Allowing a claim advances it from FILED to ALLOWED, sets the
    claim's allowed_amount_cents to its claimed_amount_cents, and synchronizes
    that allowed amount onto the linked debt by writing it into the debt's
    allowed_amount_cents". PRD §3.8: "It distributes the plan's current
    paid_to_date_cents across the case's debts in strict priority order".

    Design: Difficulty/transitive_cascade/claim_allow_cascade_to_debt_ledger_then_distribution_depth3
    """
    debtor = register_debtor(full_name="Casc Debtor")
    creditor = register_creditor(name="Cr CA")
    trustee = register_trustee(name="T-CA")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 150000)
    case = petition(debtor, case)
    claim = file_claim(creditor, case, p_debt, 200000)

    plan = create_plan(debtor, case, monthly_payment_cents=200000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-CA",
                               scheduled_start="2026-07-03T09:00:00Z",
                               scheduled_end="2026-07-03T10:00:00Z")
    hold_meeting(trustee, meeting)
    plan = confirm_plan(trustee, plan)
    record_payment(trustee, plan, 200000)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.allow_claim(claim["id"], t_headers)
    allowed = validate_success(res, 200)
    assert allowed["status"] == "ALLOWED"
    assert allowed["allowed_amount_cents"] == 200000

    debt_after = validate_success(api.get_debt(p_debt["id"], t_headers), 200)
    assert debt_after["allowed_amount_cents"] == 200000

    dist = validate_success(api.get_distribution(plan["id"], t_headers), 200)
    assert dist["distribution"][p_debt["id"]] == 200000
    assert dist["surplus_cents"] == 0


def test_claim_allowance_changes_the_waterfall_distribution(api):
    """PRD §3.6: "synchronizes that allowed amount onto the linked debt by writing
    it into the debt's allowed_amount_cents ... the debt's allowed amount is what
    later feeds the Chapter 13 distribution." Allowing a claim larger than the
    scheduled amount changes which debts the fund reaches.

    Design: Difficulty/transitive_cascade/claim_allow_cascade_to_debt_ledger_then_distribution_depth3
    """
    debtor = register_debtor(full_name="Casc2 Debtor")
    creditor = register_creditor(name="Cr CA2")
    trustee = register_trustee(name="T-CA2")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 150000)
    case = petition(debtor, case)
    claim = file_claim(creditor, case, p_debt, 200000)
    plan = create_plan(debtor, case, monthly_payment_cents=200000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-CA2",
                               scheduled_start="2026-07-08T09:00:00Z",
                               scheduled_end="2026-07-08T10:00:00Z")
    hold_meeting(trustee, meeting)
    plan = confirm_plan(trustee, plan)
    record_payment(trustee, plan, 200000)

    t_headers = make_trustee_headers(trustee["id"])
    # Before allowance the debt's allowed amount is the scheduled 150000, so the
    # 200000 fund pays 150000 and leaves 50000 surplus.
    before = validate_success(api.get_distribution(plan["id"], t_headers), 200)
    assert before["distribution"][p_debt["id"]] == 150000
    assert before["surplus_cents"] == 50000

    # Allowing the 200000 claim raises the debt's allowed amount; the fund now
    # pays the full 200000 and surplus drops to 0.
    validate_success(api.allow_claim(claim["id"], t_headers), 200)
    after = validate_success(api.get_distribution(plan["id"], t_headers), 200)
    assert after["distribution"][p_debt["id"]] == 200000
    assert after["surplus_cents"] == 0


def test_claim_not_found_returns_404(api):
    """PRD §2.6: "For any route that names a resource in its path, the system
    confirms that resource exists ... the first identifier that does not resolve
    produces ERR_NOT_FOUND (HTTP 404)".

    Design: Corner/errors/claim_not_found_returns_404
    """
    trustee = register_trustee(name="T-nf")
    res = api.allow_claim(NON_EXISTENT_UUID, make_trustee_headers(trustee["id"]))
    validate_error(res, "ERR_NOT_FOUND")
