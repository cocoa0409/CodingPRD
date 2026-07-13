"""Case closure compliance: the state precondition taking precedence over the
mandatory-cross-report constraint, and the exact 5,000,000-cent estimated
exposure boundary that makes a cross-report mandatory before closing."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

CASEWORKER = TEST_USERS["caseworker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _financial_case_under_investigation_with_freeze(balance, flagged):
    """Financial case UNDER_INVESTIGATION with one ACTIVE freeze (not disposed)."""
    ctx = fx.create_financial_case_with_account(total_balance_cents=balance)
    fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], flagged,
                            "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    return ctx


def _financial_case_ready_for_closure_with_freeze(balance, flagged):
    """Financial case driven to READY_FOR_CLOSURE with one ACTIVE freeze."""
    ctx = fx.create_financial_case_with_account(total_balance_cents=balance)
    fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], flagged,
                            "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    fx.add_comprehensive_assessment(ctx["client"]["id"], isolation_level=2, cognitive_impairment_level=1,
                                    financial_vulnerability_level=3, caregiver_dependency_level=0,
                                    prior_report_count=1)
    inv_id = ctx["investigation"]["id"]
    get_success_data(api_client.submit_findings(inv_id, {"finding_summary": "financial exploitation"}, CASEWORKER))
    get_success_data(api_client.dispose_investigation(inv_id, {"disposition": "SUBSTANTIATED"}, SUPERVISOR))
    return ctx


# ---------------- state precondition beats cross-report constraint ----------------

def test_close_non_ready_case_returns_invalid_state(api):
    """PRD §3.8: "The case must be in `READY_FOR_CLOSURE` — reached only after
    its investigation was disposed — and closing from any other status is
    rejected with `ERR_CASE_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/close_state_beats_cross_report_constraint
    """
    ctx = _financial_case_under_investigation_with_freeze(balance=5_000_000, flagged=5_000_000)
    resp = api.close_case(ctx["case_id"], {"closure_reason": "premature"}, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE.value)


def test_close_state_check_precedes_cross_report_check(api):
    """PRD §2.6: "State admissibility is seventh ... Only after all of these
    pass does the server evaluate the endpoint-specific business rules". The
    READY_FOR_CLOSURE state check therefore fires before the mandatory
    cross-report business rule, even when estimated exposure is at the threshold.

    Design: Difficulty/priority_pair_validation_conflict/close_state_beats_cross_report_constraint
    """
    ctx = _financial_case_under_investigation_with_freeze(balance=5_000_000, flagged=5_000_000)
    resp = api.close_case(ctx["case_id"], {"closure_reason": "premature"}, SUPERVISOR)
    error_id = resp.json()["data"]["error_id"]
    assert error_id != ApiErrorId.ERR_CROSS_REPORT_REQUIRED.value, (
        f"state check must precede the cross-report constraint; got {error_id}"
    )
    assert error_id == ApiErrorId.ERR_CASE_INVALID_STATE.value


# ---------------- mandatory cross-report at exactly 5,000,000 cents ----------------

def test_close_at_exposure_threshold_requires_cross_report(api):
    """PRD §3.8: "if the case's `estimated_exposure_cents` is 5,000,000 cents or
    more, then its `cross_report_agency` must already be set; closing such a case
    with no cross-report on file is rejected with `ERR_CROSS_REPORT_REQUIRED`
    (422)."

    Design: Difficulty/boundary_precision_check/exposure_cross_report_threshold_exactly_50000
    """
    ctx = _financial_case_ready_for_closure_with_freeze(balance=5_000_000, flagged=3_000_000)
    resp = api.close_case(ctx["case_id"], {"closure_reason": "attempt close"}, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_CROSS_REPORT_REQUIRED.value)


def test_estimated_exposure_at_threshold_uses_full_balance(api):
    """PRD §3.5: "The `estimated_exposure_cents` is the projected worst-case
    exposure: the sum of the full `total_balance_cents` of every account that
    currently holds an active freeze in the case." A single 5,000,000-cent
    frozen account puts estimated exposure at exactly the 5,000,000 threshold.

    Design: Difficulty/boundary_precision_check/exposure_cross_report_threshold_exactly_50000
    """
    ctx = _financial_case_ready_for_closure_with_freeze(balance=5_000_000, flagged=3_000_000)
    case = fx.get_case(ctx["case_id"])
    assert case["estimated_exposure_cents"] == 5_000_000, (
        f"full frozen balance drives estimated to exactly 5,000,000; got {case['estimated_exposure_cents']}"
    )
