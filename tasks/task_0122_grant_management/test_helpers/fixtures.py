"""Composite setup helpers for the Grant Management API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server against an empty DB before each test).
Setup calls use get_success_data() so a broken precondition surfaces a clear
"Setup step failed" message rather than an opaque assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_finance_officer_headers,
    ANONYMOUS_HEADERS,
)
from . import factories as f

GW = TEST_USERS["grant_writer_headers"]
FO = TEST_USERS["finance_officer_headers"]
PM = TEST_USERS["program_manager_headers"]
AO = TEST_USERS["agency_officer_headers"]
AU = TEST_USERS["auditor_headers"]


# --------------------------------------------------------------------------
# Tier 1: State progression — applications
# --------------------------------------------------------------------------
def create_draft_application(**overrides) -> dict:
    """Create one DRAFT application. Returns the application entity."""
    payload = f.create_application_payload(**overrides)
    return get_success_data(api_client.create_application(payload, GW))


def create_submitted_application(**overrides) -> dict:
    """DRAFT -> SUBMITTED. Returns the submitted application."""
    app = create_draft_application(**overrides)
    return get_success_data(api_client.submit_application(app["id"], GW))


def create_under_review_application(**overrides) -> dict:
    """DRAFT -> SUBMITTED -> UNDER_REVIEW. Returns the application under review."""
    app = create_submitted_application(**overrides)
    return get_success_data(api_client.begin_review_application(app["id"], AO))


def create_active_award(**app_overrides) -> dict:
    """Full path application -> AWARDED, returning the freshly created ACTIVE Award
    (with its server-computed federal_ceiling_cents and version captured)."""
    app = create_under_review_application(**app_overrides)
    return get_success_data(api_client.award_application(app["id"], AO))


def get_award(award_id: str) -> dict:
    """Re-read an award to capture its current version after intervening mutations."""
    return get_success_data(api_client.get_award(award_id, AO))


# --------------------------------------------------------------------------
# Tier 1: State progression — awards (OCC-guarded lifecycle)
# --------------------------------------------------------------------------
def initiate_closeout(award: dict) -> dict:
    """ACTIVE -> PENDING_CLOSEOUT using the award's current version. Returns the award."""
    return get_success_data(
        api_client.initiate_closeout_award(
            award["id"], {"expected_award_version": award["version"]}, AO
        )
    )


def create_award_in_pending_closeout(**app_overrides) -> dict:
    """ACTIVE award -> PENDING_CLOSEOUT (no other obligations). Returns the award in PENDING_CLOSEOUT."""
    award = create_active_award(**app_overrides)
    return initiate_closeout(award)


# --------------------------------------------------------------------------
# Tier 2: Indirect-cost rates
# --------------------------------------------------------------------------
def set_indirect_cost_rate(award_id: str, expected_version: int, **rate_overrides) -> dict:
    """Create an indirect-cost rate against an award (OCC-guarded). Returns the rate."""
    payload = f.create_indirect_cost_rate_payload(award_id, expected_version, **rate_overrides)
    return get_success_data(api_client.create_indirect_cost_rate(payload, FO))


def create_active_award_with_rate(rate_overrides=None, **app_overrides):
    """ACTIVE award + one ACTIVE indirect-cost rate.
    Returns (award_after_rate, rate). award_after_rate is re-read so its version reflects
    the rate-create bump."""
    award = create_active_award(**app_overrides)
    rate = set_indirect_cost_rate(award["id"], award["version"], **(rate_overrides or {}))
    return get_award(award["id"]), rate


# --------------------------------------------------------------------------
# Tier 2: Restricted funds
# --------------------------------------------------------------------------
def create_restricted_fund(award_id: str, **overrides) -> dict:
    payload = f.create_restricted_fund_payload(award_id, **overrides)
    return get_success_data(api_client.create_restricted_fund(payload, FO))


def create_award_with_funds(fund_specs, **app_overrides):
    """ACTIVE award + a list of restricted funds.

    fund_specs is a list of dicts of restricted-fund overrides
    (e.g. {"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}).
    Returns (award, [funds...]).
    """
    award = create_active_award(**app_overrides)
    funds = [create_restricted_fund(award["id"], **spec) for spec in fund_specs]
    return award, funds


# --------------------------------------------------------------------------
# Tier 3: Drawdowns
# --------------------------------------------------------------------------
def create_drawdown(award_id, amount_cents, allocation_plan, initiator_user_id="officer-draw-1"):
    """Create a REQUESTED drawdown initiated by a named FinanceOfficer user id.

    The initiator id is recorded on initiated_by_user_id (PRD §2.1) and matters for
    the segregation-of-duties check at certify time.
    Returns the drawdown.
    """
    headers = make_finance_officer_headers(initiator_user_id)
    payload = f.create_drawdown_payload(award_id, amount_cents, allocation_plan)
    return get_success_data(api_client.create_drawdown(payload, headers))


def disburse_drawdown(drawdown_id, initiator_user_id="officer-draw-1"):
    """REQUESTED -> DISBURSED. Returns the disbursed drawdown."""
    headers = make_finance_officer_headers(initiator_user_id)
    return get_success_data(api_client.disburse_drawdown(drawdown_id, headers))


def create_disbursed_drawdown(award_id, amount_cents, allocation_plan, initiator_user_id="officer-draw-1"):
    """Create + disburse a drawdown by the same initiator. Returns the disbursed drawdown."""
    dd = create_drawdown(award_id, amount_cents, allocation_plan, initiator_user_id)
    return disburse_drawdown(dd["id"], initiator_user_id)


def single_line_plan(fund_id, amount_cents):
    return [{"restricted_fund_id": fund_id, "amount_cents": amount_cents}]


# --------------------------------------------------------------------------
# Tier 4: Financial reports
# --------------------------------------------------------------------------
def create_financial_report(award_id, **overrides) -> dict:
    payload = f.create_financial_report_payload(award_id, **overrides)
    return get_success_data(api_client.create_financial_report(payload, FO))


def certify_financial_report(report_id, certifier_user_id="officer-cert-1") -> dict:
    """DRAFT -> SUBMITTED by a named FinanceOfficer (recorded as certified_by_user_id)."""
    headers = make_finance_officer_headers(certifier_user_id)
    return get_success_data(api_client.certify_financial_report(report_id, headers))


def accept_financial_report(report_id) -> dict:
    """SUBMITTED -> ACCEPTED (runs approval totals, indirect cost, reimbursement, ledger sync)."""
    return get_success_data(api_client.accept_financial_report(report_id, AO))


def create_accepted_interim_report(award_id, direct_cost_lines, period_label,
                                   certifier_user_id="officer-cert-1") -> dict:
    """Create an INTERIM report, certify, and accept. Returns the ACCEPTED report."""
    report = create_financial_report(
        award_id, period_label=period_label, report_basis="INTERIM",
        direct_cost_lines=direct_cost_lines,
    )
    certify_financial_report(report["id"], certifier_user_id)
    return accept_financial_report(report["id"])


# --------------------------------------------------------------------------
# Tier 4: Subawards
# --------------------------------------------------------------------------
def create_subaward(award_id, **overrides) -> dict:
    payload = f.create_subaward_payload(award_id, **overrides)
    return get_success_data(api_client.create_subaward(payload, PM))


def create_active_subaward(award_id, **overrides) -> dict:
    """PROPOSED -> APPROVED -> ACTIVE. Returns the active subaward."""
    sub = create_subaward(award_id, **overrides)
    get_success_data(api_client.approve_subaward(sub["id"], PM))
    return get_success_data(api_client.activate_subaward(sub["id"], PM))


# --------------------------------------------------------------------------
# Tier 5: Single audits and findings
# --------------------------------------------------------------------------
def create_single_audit(award_id, **overrides) -> dict:
    payload = f.create_single_audit_payload(award_id, **overrides)
    return get_success_data(api_client.create_single_audit(payload, AU))


def create_finding(single_audit_id, **overrides) -> dict:
    payload = f.create_finding_payload(**overrides)
    return get_success_data(api_client.create_finding(single_audit_id, payload, AU))


def create_submitted_required_audit_with_open_material_weakness(award_id, **overrides):
    """A required (above-threshold) SingleAudit SUBMITTED with one OPEN MATERIAL_WEAKNESS finding.

    Returns (single_audit, finding).
    """
    audit = create_single_audit(award_id, federal_expenditures_cents=80_000_000, **overrides)
    finding = create_finding(audit["id"], severity="MATERIAL_WEAKNESS", questioned_cost_cents=500_000)
    get_success_data(api_client.submit_single_audit(audit["id"], AU))
    return audit, finding


# Re-export commonly used header dicts so test files can import them from fixtures.
__all__ = [
    "GW", "FO", "PM", "AO", "AU", "ANONYMOUS_HEADERS",
    "create_draft_application", "create_submitted_application",
    "create_under_review_application", "create_active_award", "get_award",
    "initiate_closeout", "create_award_in_pending_closeout",
    "set_indirect_cost_rate", "create_active_award_with_rate",
    "create_restricted_fund", "create_award_with_funds",
    "create_drawdown", "disburse_drawdown", "create_disbursed_drawdown", "single_line_plan",
    "create_financial_report", "certify_financial_report", "accept_financial_report",
    "create_accepted_interim_report",
    "create_subaward", "create_active_subaward",
    "create_single_audit", "create_finding",
    "create_submitted_required_audit_with_open_material_weakness",
]
