"""Validation precedence: the generic state check pre-empts later business-rule
checks, and among business-referential vs business-temporal the referential check
fires first; plus the standalone prior-discharge bar.

PRD §2.7 and the §3 narratives govern these assertions.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    register_debtor, register_creditor, register_trustee, open_case,
    submit_means_test, add_income_and_expense_schedules, add_debt, petition,
    setup_filed_case, setup_case_at_meeting_held, file_claim,
    make_debtor_headers, make_creditor_headers, make_trustee_headers,
)


def test_state_check_pre_empts_means_test_abuse_on_second_petition(api):
    """PRD §2.7: "Only then is the resource's state checked against the requested
    transition (ERR_INVALID_STATE, HTTP 409). Domain-specific business rules ...
    the means-test and discharge bars ... are evaluated after the generic state
    check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_chapter7_petition
    """
    debtor = register_debtor(full_name="Pri5a Debtor", prior_discharge_within_8y=False)
    case = open_case(debtor, filed_chapter="CHAPTER_7")
    submit_means_test(debtor, case, cmi_monthly_cents=400000,
                      monthly_expenses_cents=300000, median_annual_income_cents=6000000)
    add_income_and_expense_schedules(debtor, case)
    d_headers = make_debtor_headers(debtor["id"])
    # First petition succeeds (PRESUMPTION_OK), advancing the case to FILED.
    validate_success(api.petition_case(case["id"], d_headers), 200)
    # Re-submit the means test so the result becomes PRESUMPTION_ABUSE.
    submit_means_test(debtor, case, cmi_monthly_cents=600000,
                      monthly_expenses_cents=300000, median_annual_income_cents=6000000)
    # Second petition: the case is no longer DRAFT (state) AND abuse presumption
    # holds; the state check wins with ERR_INVALID_STATE.
    res = api.petition_case(case["id"], d_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_state_check_fires_in_isolation_on_second_petition(api):
    """PRD §2.7: "Only then is the resource's state checked against the requested
    transition (ERR_INVALID_STATE, HTTP 409)." A second petition on a case already
    advanced past DRAFT (means_test_result still PRESUMPTION_OK, so the abuse bar
    is NOT in play) hits the state check alone.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_chapter7_petition
    """
    debtor = register_debtor(full_name="Pri5a-iso Debtor", prior_discharge_within_8y=False)
    case = open_case(debtor, filed_chapter="CHAPTER_7")
    submit_means_test(debtor, case, cmi_monthly_cents=400000,
                      monthly_expenses_cents=300000, median_annual_income_cents=6000000)
    add_income_and_expense_schedules(debtor, case)
    d_headers = make_debtor_headers(debtor["id"])
    validate_success(api.petition_case(case["id"], d_headers), 200)
    # Result stays PRESUMPTION_OK; only the state check can fire on the re-petition.
    res = api.petition_case(case["id"], d_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_claim_creditor_mismatch_fires_in_isolation_on_live_case(api):
    """PRD §3.6: "a creditor may only file against its own scheduled debts: the
    filed_by_creditor_id must equal the creditor_id recorded on the linked debt,
    and a mismatch is rejected with ERR_CLAIM_CREDITOR_MISMATCH (HTTP 409)." On a
    live FILED case (stay ACTIVE, so the stay guard cannot fire) the referential
    mismatch is the only violation.

    Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_temporal_on_claim_filing
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    creditor_a = register_creditor(name="Cr A-iso")
    creditor_b = register_creditor(name="Cr B-iso")
    debt = add_debt(debtor, case, creditor_a, "UNSECURED", 90000)
    # Stay is ACTIVE (case FILED), so only the creditor mismatch can fire.
    res = api.create_claim({
        "case_id": case["id"], "debt_id": debt["id"],
        "filed_by_creditor_id": creditor_b["id"], "claimed_amount_cents": 90000,
    }, make_creditor_headers(creditor_b["id"]))
    validate_error(res, "ERR_CLAIM_CREDITOR_MISMATCH")


def test_chapter7_discharge_blocked_by_prior_discharge_bar(api):
    """PRD §3.10: "the debtor's prior_discharge_within_8y be false — a prior
    discharge within eight years bars a new one and is rejected with
    ERR_PRIOR_DISCHARGE_BAR (HTTP 409)."

    Design: Corner/validations/chapter7_discharge_blocked_by_prior_discharge_bar
    """
    debtor, trustee, case = setup_case_at_meeting_held(
        filed_chapter="CHAPTER_7", prior_discharge_within_8y=True,
        room_code="R-bar", scheduled_start="2026-09-05T09:00:00Z",
        scheduled_end="2026-09-05T10:00:00Z")
    t_headers = make_trustee_headers(trustee["id"])
    res = api.discharge_case(case["id"], t_headers)
    validate_error(res, "ERR_PRIOR_DISCHARGE_BAR")
    after = validate_success(api.get_case(case["id"], make_debtor_headers(debtor["id"])), 200)
    assert after["status"] == "MEETING_HELD"
