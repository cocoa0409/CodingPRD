"""Subawards, single audits/findings, and the heavily-gated award closeout.

Sources: Difficulty queue (cross_entity_state_dependency, boundary_precision on the
audit threshold) and Corner queue (state_machines subaward/audit, calculations closeout
balance + threshold, validations closeout preconditions, endpoints finding-resolve and
reverse-reachability).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_single_audit,
    TEST_USERS,
)
import test_helpers.fixtures as fx

PM = TEST_USERS["program_manager_headers"]
AO = TEST_USERS["agency_officer_headers"]
AU = TEST_USERS["auditor_headers"]


# ==========================================================================
# Cross-entity state dependency (Difficulty Rule 7)
# ==========================================================================
def test_subaward_approve_requires_award_active(api):
    """PRD §3.4: "Approving moves a PROPOSED subaward to APPROVED, and this is permitted
    only while the prime award is ACTIVE."
    PRD §3.4: "In both cases, if the parent award is not ACTIVE, the operation is rejected
    with ERR_AWARD_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/subaward_approve_requires_award_active
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A13", applicant_org_name="Org M",
        requested_amount_cents=20_000_000,
    )
    sub = fx.create_subaward(award["id"], subrecipient_name="Sub Org",
                             subaward_amount_cents=3_000_000, risk_tier="LOW")
    validate_success(api.suspend_award(award["id"], {"expected_award_version": award["version"]}, AO))
    resp = api.approve_subaward(sub["id"], PM)
    validate_error(resp, ApiErrorId.ERR_AWARD_NOT_ACTIVE.value, expected_status=409)
    assert validate_success(api.get_subaward(sub["id"], PM))["status"] == "PROPOSED"


def test_subaward_approve_succeeds_once_award_reinstated_active(api):
    """PRD §3.4: "Approving moves a PROPOSED subaward to APPROVED, and this is permitted
    only while the prime award is ACTIVE."
    PRD §3.2: "a SUSPENDED award may be reinstated back to ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/subaward_approve_requires_award_active
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A13b", applicant_org_name="Org M2",
        requested_amount_cents=20_000_000,
    )
    sub = fx.create_subaward(award["id"], subrecipient_name="Sub Org 2",
                             subaward_amount_cents=3_000_000, risk_tier="LOW")
    suspended = validate_success(
        api.suspend_award(award["id"], {"expected_award_version": award["version"]}, AO)
    )
    # Approve is blocked while SUSPENDED.
    blocked = api.approve_subaward(sub["id"], PM)
    validate_error(blocked, ApiErrorId.ERR_AWARD_NOT_ACTIVE.value, expected_status=409)
    # Reinstate to ACTIVE, then approve succeeds.
    reinstated = validate_success(
        api.reinstate_award(award["id"], {"expected_award_version": suspended["version"]}, AO)
    )
    assert reinstated["status"] == "ACTIVE"
    approved = validate_success(api.approve_subaward(sub["id"], PM))
    assert approved["status"] == "APPROVED"


def test_award_close_blocked_by_unresolved_single_audit(api):
    """PRD §3.2: "every Single Audit of the award whose audit was required must be in
    RESOLVED status, and no audit finding of severity MATERIAL_WEAKNESS may remain OPEN;
    a violation here is rejected with ERR_AUDIT_UNRESOLVED."

    Design: Difficulty/cross_entity_state_dependency/award_close_requires_single_audit_resolved
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A14", applicant_org_name="Org N",
        requested_amount_cents=100_000_000,
    )
    fx.create_submitted_required_audit_with_open_material_weakness(award["id"], fiscal_year=2026)
    pc = fx.initiate_closeout(award)
    resp = api.close_award(pc["id"], {"expected_award_version": pc["version"]}, AO)
    validate_error(resp, ApiErrorId.ERR_AUDIT_UNRESOLVED.value, expected_status=409)
    assert validate_success(api.get_award(award["id"], AO))["status"] == "PENDING_CLOSEOUT"


def test_award_close_succeeds_after_audit_resolved(api):
    """PRD §3.2: "every Single Audit of the award whose audit was required must be in
    RESOLVED status, and no audit finding of severity MATERIAL_WEAKNESS may remain OPEN."
    PRD §3.8: "A SUBMITTED audit may then be resolved, but only when every audit finding of
    that audit with severity MATERIAL_WEAKNESS is in RESOLVED status; resolution moves the
    audit to the terminal RESOLVED state."

    Design: Difficulty/cross_entity_state_dependency/award_close_requires_single_audit_resolved
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A14b", applicant_org_name="Org N2",
        requested_amount_cents=100_000_000,
    )
    audit, finding = fx.create_submitted_required_audit_with_open_material_weakness(
        award["id"], fiscal_year=2026,
    )
    pc = fx.initiate_closeout(award)
    # Blocked while the material weakness is OPEN and the audit unresolved.
    blocked = api.close_award(pc["id"], {"expected_award_version": pc["version"]}, AO)
    validate_error(blocked, ApiErrorId.ERR_AUDIT_UNRESOLVED.value, expected_status=409)
    # Resolve the finding, then the audit, then close succeeds.
    validate_success(api.resolve_finding(finding["id"], AU))
    validate_success(api.resolve_single_audit(audit["id"], AU))
    award_now = validate_success(api.get_award(award["id"], AO))
    closed = validate_success(api.close_award(award_now["id"], {"expected_award_version": award_now["version"]}, AO))
    assert closed["status"] == "CLOSED"


# ==========================================================================
# Boundary precision (Difficulty Rule 6): single-audit threshold inclusive at $750k
# ==========================================================================
def test_single_audit_threshold_inclusive_boundary(api):
    """PRD §3.8: "it is true exactly when federal_expenditures_cents is at least seven
    hundred fifty thousand dollars, and false otherwise. The boundary is inclusive —
    federal expenditures of 74,999,999 cents leave audit_required false, while 75,000,000
    cents make it true."

    Design: Difficulty/boundary_precision_check/single_audit_threshold_inclusive_at_750k
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A11", applicant_org_name="Org K",
        requested_amount_cents=90_000_000,
    )
    below = fx.create_single_audit(award["id"], fiscal_year=2026, federal_expenditures_cents=74_999_999)
    at = fx.create_single_audit(award["id"], fiscal_year=2027, federal_expenditures_cents=75_000_000)
    assert below["audit_required"] is False
    assert at["audit_required"] is True


def test_single_audit_threshold_one_cent_below_boundary(api):
    """PRD §3.8: "federal expenditures of 74,999,999 cents leave audit_required false,
    while 75,000,000 cents make it true."

    Design: Difficulty/boundary_precision_check/single_audit_threshold_inclusive_at_750k
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A11b", applicant_org_name="Org K2",
        requested_amount_cents=90_000_000,
    )
    below = fx.create_single_audit(award["id"], fiscal_year=2026, federal_expenditures_cents=74_999_999)
    assert_single_audit(below)
    assert below["audit_required"] is False


# ==========================================================================
# Corner: subaward lifecycle, audit branches, findings, closeout calc/preconditions
# ==========================================================================
def test_subaward_full_lifecycle_to_terminated(api):
    """PRD §3.4: "Approving moves a PROPOSED subaward to APPROVED... Activating moves an
    APPROVED subaward to ACTIVE... an ACTIVE subaward may be terminated... either path
    moves the subaward to the terminal TERMINATED state."

    Design: Corner/state_machines/subaward_full_lifecycle_proposed_approved_active_terminated
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C12", applicant_org_name="Corner Org 12",
        requested_amount_cents=30_000_000,
    )
    sub = fx.create_subaward(award["id"], subrecipient_name="Sub C12",
                             subaward_amount_cents=2_000_000, risk_tier="LOW")
    validate_success(api.approve_subaward(sub["id"], PM))
    validate_success(api.activate_subaward(sub["id"], PM))
    terminated = validate_success(api.terminate_subaward(sub["id"], PM))
    assert terminated["status"] == "TERMINATED"


def test_progress_report_return_resubmit_cycle(api):
    """PRD §3.7: "Returning a SUBMITTED report for rework moves it to RETURNED. From
    RETURNED, the GrantWriter may resubmit, moving the report back to SUBMITTED, so the
    return-and-resubmit cycle may repeat."
    PRD §3.7: "Accepting a SUBMITTED report moves it to the terminal ACCEPTED state."

    Design: Corner/state_machines/progress_report_return_resubmit_cycle_back_to_submitted
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C16", applicant_org_name="Corner Org 16",
        requested_amount_cents=30_000_000,
    )
    GW = TEST_USERS["grant_writer_headers"]
    pr = validate_success(api.create_progress_report({
        "award_id": award["id"], "period_label": "FY2026-Q1",
        "milestones_met": 3, "milestones_planned": 5,
    }, GW), expected_status=201)
    validate_success(api.return_progress_report(pr["id"], PM))
    validate_success(api.resubmit_progress_report(pr["id"], GW))
    accepted = validate_success(api.accept_progress_report(pr["id"], PM))
    assert accepted["status"] == "ACCEPTED"


def test_below_threshold_audit_resolves_directly_from_open(api):
    """PRD §3.8: "An audit that was not required follows the shorter path: when
    audit_required is false, the Auditor resolves it directly from OPEN to RESOLVED with
    no submission step."

    Design: Corner/state_machines/below_threshold_single_audit_resolves_directly_from_open
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C17", applicant_org_name="Corner Org 17",
        requested_amount_cents=30_000_000,
    )
    audit = fx.create_single_audit(award["id"], fiscal_year=2026, federal_expenditures_cents=10_000_000)
    assert audit["audit_required"] is False
    resolved = validate_success(api.resolve_single_audit(audit["id"], AU))
    assert resolved["status"] == "RESOLVED"


def test_submit_below_threshold_audit_returns_invalid_state(api):
    """PRD §3.8: "submission of an audit that is not OPEN, or of an audit whose
    audit_required is false, is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/submit_below_threshold_single_audit_returns_invalid_state
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C18", applicant_org_name="Corner Org 18",
        requested_amount_cents=30_000_000,
    )
    audit = fx.create_single_audit(award["id"], fiscal_year=2026, federal_expenditures_cents=10_000_000)
    resp = api.submit_single_audit(audit["id"], AU)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert validate_success(api.get_single_audit(audit["id"], AU))["status"] == "OPEN"


def test_audit_resolve_blocked_by_open_material_weakness(api):
    """PRD §3.8: "A SUBMITTED audit may then be resolved, but only when every audit
    finding of that audit with severity MATERIAL_WEAKNESS is in RESOLVED status."
    PRD §3.8: "A resolve attempt against an audit in a state from which resolution is not
    defined yields ERR_INVALID_STATE."

    Design: Corner/state_machines/single_audit_resolve_blocked_by_open_material_weakness_finding
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C19", applicant_org_name="Corner Org 19",
        requested_amount_cents=100_000_000,
    )
    audit, _finding = fx.create_submitted_required_audit_with_open_material_weakness(
        award["id"], fiscal_year=2026,
    )
    resp = api.resolve_single_audit(audit["id"], AU)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert validate_success(api.get_single_audit(audit["id"], AU))["status"] == "SUBMITTED"


def test_single_audit_above_boundary_one_dollar_over(api):
    """PRD §3.8: "it is true exactly when federal_expenditures_cents is at least seven
    hundred fifty thousand dollars, and false otherwise."

    Design: Corner/calculations/single_audit_threshold_above_boundary_at_one_dollar_over
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C23", applicant_org_name="Corner Org 23",
        requested_amount_cents=100_000_000,
    )
    audit = fx.create_single_audit(award["id"], fiscal_year=2026, federal_expenditures_cents=75_000_100)
    assert audit["audit_required"] is True


def test_closeout_unobligated_balance_equals_ceiling_minus_drawn(api):
    """PRD §3.2: "the close response surfaces closeout_unobligated_cents, computed as the
    award's federal_ceiling_cents minus its current federal_drawn_cents — the federal cash
    authorized but never drawn."

    Design: Corner/calculations/closeout_unobligated_balance_equals_ceiling_minus_drawn
    """
    # ceiling = 30000000 * 0.80 = 24000000; drawn 5000000 -> unobligated 19000000.
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-C21", applicant_org_name="Corner Org 21",
        requested_amount_cents=30_000_000,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 5_000_000, fx.single_line_plan(fund["id"], 5_000_000),
        initiator_user_id="officer-draw-C21",
    )
    award_now = validate_success(api.get_award(award["id"], AO))
    pc = fx.initiate_closeout(award_now)
    closed = validate_success(api.close_award(pc["id"], {"expected_award_version": pc["version"]}, AO))
    assert closed["status"] == "CLOSED"
    assert closed["closeout_unobligated_cents"] == 19_000_000


def test_closeout_blocked_by_active_subaward(api):
    """PRD §3.2: "no subaward of the award may be in ACTIVE status — every subaward must
    be in PROPOSED, APPROVED, or TERMINATED; a violation here is rejected with
    ERR_CLOSEOUT_PRECONDITIONS."

    Design: Corner/validations/closeout_blocked_by_active_subaward_returns_closeout_preconditions
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C31", applicant_org_name="Corner Org 31",
        requested_amount_cents=30_000_000,
    )
    fx.create_active_subaward(award["id"], subrecipient_name="Sub C31",
                              subaward_amount_cents=1_000_000, risk_tier="LOW")
    award_now = validate_success(api.get_award(award["id"], AO))
    pc = fx.initiate_closeout(award_now)
    resp = api.close_award(pc["id"], {"expected_award_version": pc["version"]}, AO)
    validate_error(resp, ApiErrorId.ERR_CLOSEOUT_PRECONDITIONS.value, expected_status=409)
    assert validate_success(api.get_award(award["id"], AO))["status"] == "PENDING_CLOSEOUT"


def test_finding_resolve_sets_status_resolved(api):
    """PRD §3.8: "the Auditor resolves an OPEN finding to move it to RESOLVED."

    Design: Corner/endpoints/audit_finding_resolve_action_sets_status_resolved
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C32", applicant_org_name="Corner Org 32",
        requested_amount_cents=100_000_000,
    )
    audit = fx.create_single_audit(award["id"], fiscal_year=2026, federal_expenditures_cents=80_000_000)
    finding = fx.create_finding(audit["id"], severity="MATERIAL_WEAKNESS", questioned_cost_cents=100_000)
    resolved = validate_success(api.resolve_finding(finding["id"], AU))
    assert resolved["status"] == "RESOLVED"


def test_list_findings_by_single_audit_reverse_reachability(api):
    """PRD §3.8: "Findings of an audit may be listed."
    PRD §2.8: "the findings of a single audit. Path parameters are validated left to right."

    Design: Corner/endpoints/audit_findings_reverse_reachability_list_by_single_audit
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C34", applicant_org_name="Corner Org 34",
        requested_amount_cents=100_000_000,
    )
    audit = fx.create_single_audit(award["id"], fiscal_year=2026, federal_expenditures_cents=80_000_000)
    fx.create_finding(audit["id"], severity="DEFICIENCY", questioned_cost_cents=10_000)
    fx.create_finding(audit["id"], severity="SIGNIFICANT_DEFICIENCY", questioned_cost_cents=20_000)
    findings = api.list_findings(audit["id"], AU).json()["data"]
    assert len(findings) == 2
    assert all(f["single_audit_id"] == audit["id"] for f in findings)


def test_duplicate_restricted_fund_priority_order_returns_duplicate(api):
    """PRD §3.5: "Within a single award, both priority_order and category must be distinct
    across funds; a duplicate of either is rejected with ERR_DUPLICATE."

    Design: Corner/validations/duplicate_restricted_fund_priority_order_returns_duplicate
    """
    from test_helpers import TEST_USERS as TU
    FO = TU["finance_officer_headers"]
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C28", applicant_org_name="Corner Org 28",
        requested_amount_cents=50_000_000,
    )
    fx.create_restricted_fund(award["id"], category="PERSONNEL", budgeted_cents=5_000_000, priority_order=1)
    resp = api.create_restricted_fund({
        "award_id": award["id"], "category": "TRAVEL", "budgeted_cents": 3_000_000, "priority_order": 1,
    }, FO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value, expected_status=409)
