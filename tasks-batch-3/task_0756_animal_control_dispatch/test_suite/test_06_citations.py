"""Citation issuance, repeat-offender fine escalation, and the case fine ledger."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS,
    investigating_case, issue_citation, pay_citation,
    create_citation_payload,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ==========================================================================
# Difficulty: dual_variant_calc / citation_fine_standard_vs_escalated
# ==========================================================================
def test_repeat_offender_fine_escalates_to_375(api):
    """PRD 3.7: "The base_fine is fixed by violation_code: 50 for unlicensed, 75
    for leash, 250 for dangerous, 300 for bite, and 500 for cruelty." PRD 3.7:
    "If there is at least one prior, the party is a repeat offender: the
    multiplier is 1 plus 0.5 times the number of priors, where the prior count is
    capped at 3 for this purpose — so one prior yields 1.5×, two priors 2.0×, and
    three or more priors 2.5×."

    Design: Difficulty/dual_variant_calc/citation_fine_standard_vs_escalated
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides={"complaint_type": "BITE"})
    first = issue_citation(api, ctx["case"]["id"], violation_code="DANGEROUS",
                           issued_to_name="Sam Owner", issued_to_ref="OWNER-9")
    assert first["fine_amount"] == pytest.approx(250.00, abs=0.01)
    pay_citation(api, first["id"])
    second = validate_success(api.create_citation(create_citation_payload(
        ctx["case"]["id"], violation_code="DANGEROUS", issued_to_name="Sam Owner",
        issued_to_ref="OWNER-9"), SUPERVISOR), expected_status=201)
    assert second["base_fine"] == pytest.approx(250.00, abs=0.01)
    assert second["fine_amount"] == pytest.approx(375.00, abs=0.01)


def test_first_offense_dangerous_fine_is_base_250(api):
    """PRD 3.7: "If there are no such priors, the multiplier is 1.0 and the
    fine_amount equals the base fine (the standard, first-offense case)." PRD
    3.7: "The base_fine is fixed by violation_code: 50 for unlicensed, 75 for
    leash, 250 for dangerous, 300 for bite, and 500 for cruelty."

    Design: Difficulty/dual_variant_calc/citation_fine_standard_vs_escalated
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides={"complaint_type": "BITE"})
    citation = issue_citation(api, ctx["case"]["id"], violation_code="DANGEROUS",
                              issued_to_name="Fresh Owner", issued_to_ref="OWNER-FRESH")
    assert citation["base_fine"] == pytest.approx(250.00, abs=0.01)
    assert citation["fine_amount"] == pytest.approx(250.00, abs=0.01)


# ==========================================================================
# Difficulty: compensating_invariant / case_outstanding_fines_conserved
# ==========================================================================
def test_outstanding_fines_conserved_across_issue_and_pay(api):
    """PRD 2.7: "A Case carries outstanding_fines_total, the sum of fine_amount
    across the case's citations still in ISSUED. It rises by the fine when a
    citation is issued and falls by the fine when that citation is paid or
    referred to court."

    Design: Difficulty/compensating_invariant/case_outstanding_fines_conserved
    """
    ctx = investigating_case(api, case_type="STRAY")
    citation = issue_citation(api, ctx["case"]["id"], violation_code="DANGEROUS",
                              issued_to_name="Owner Z", issued_to_ref="OWNER-3")
    after_issue = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR))
    assert after_issue["outstanding_fines_total"] == pytest.approx(250.00, abs=0.01)
    paid = pay_citation(api, citation["id"])
    assert paid["status"] == "PAID"
    after_pay = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR))
    assert after_pay["outstanding_fines_total"] == pytest.approx(0.00, abs=0.01)


def test_paying_citation_zeroes_case_ledger(api):
    """PRD 3.7: "Either exit lowers the case's outstanding_fines_total by that
    citation's fine_amount." PRD 3.7: "A Dispatcher or Supervisor records
    payment, moving the citation from ISSUED to PAID."

    Design: Difficulty/compensating_invariant/case_outstanding_fines_conserved
    """
    ctx = investigating_case(api, case_type="STRAY")
    citation = issue_citation(api, ctx["case"]["id"], violation_code="DANGEROUS",
                              issued_to_name="Owner Z", issued_to_ref="OWNER-3b")
    pay_citation(api, citation["id"])
    case_after = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR))
    assert case_after["outstanding_fines_total"] == pytest.approx(0.00, abs=0.01)


# ==========================================================================
# Corner: state_machines
# ==========================================================================
def test_paying_citation_twice_is_already_resolved(api):
    """PRD 3.7: "A citation leaves ISSUED two ways, and both require it to still
    be in ISSUED — a pay or refer attempt on an already-resolved citation is
    ERR_CITATION_ALREADY_RESOLVED."

    Design: Corner/state_machines/pay_citation_twice_returns_already_resolved
    """
    ctx = investigating_case(api, case_type="STRAY")
    citation = issue_citation(api, ctx["case"]["id"], violation_code="UNLICENSED",
                              issued_to_name="PC Owner", issued_to_ref="OWNER-PC")
    pay_citation(api, citation["id"])
    resp = api.pay_citation(citation["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CITATION_ALREADY_RESOLVED)


# ==========================================================================
# Corner: calculations
# ==========================================================================
def test_first_offense_leash_fine_is_75(api):
    """PRD 3.7: "The base_fine is fixed by violation_code: 50 for unlicensed, 75
    for leash, 250 for dangerous, 300 for bite, and 500 for cruelty." PRD 3.7:
    "If there are no such priors, the multiplier is 1.0 and the fine_amount
    equals the base fine (the standard, first-offense case)."

    Design: Corner/calculations/citation_fine_leash_first_offense_constant
    """
    ctx = investigating_case(api, case_type="STRAY")
    citation = issue_citation(api, ctx["case"]["id"], violation_code="LEASH",
                              issued_to_name="LF Owner", issued_to_ref="OWNER-LF")
    assert citation["fine_amount"] == pytest.approx(75.00, abs=0.01)
