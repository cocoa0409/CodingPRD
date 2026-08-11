"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server before every test, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Uses
get_success_data() (lenient validator) internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_sponsor_payload, create_facility_payload, create_program_payload,
    create_project_payload, create_application_payload, create_amendment_payload,
    create_contractor_payload, create_contract_payload, create_dbe_report_payload,
    create_invoice_payload, create_drawdown_payload, create_audit_finding_payload,
    create_grant_asset_payload, create_phase_payload,
)
from .test_users import (
    TEST_USERS, make_contractor_headers,
    FAA_USER_ID, SPONSOR_USER_ID, COMPLIANCE_USER_ID, COMPLIANCE_USER_ID_2,
    FINANCE_USER_ID, AUDITOR_USER_ID,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _headers_for(role_headers, user_id=None):
    """Return role headers, rebound to a specific operator id when given.

    Segregation-of-duties compares X-User-ID values (PRD §2.10), so creators,
    preparers and certifiers must carry stable, distinct operator ids.
    """
    if user_id is None:
        return role_headers
    return {**role_headers, "X-User-ID": user_id}


# ---------------------------------------------------------------------------
# Tier 0: operational drivers (logical clock / fiscal checkpoint, PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server logical clock (FAAManager-only). Returns current_utc payload."""
    return get_success_data(api_client.set_clock(to_iso8601, FAA))


def run_checkpoint():
    """Run the fiscal checkpoint batch. Returns the counts payload."""
    return get_success_data(api_client.run_checkpoint(FAA))


# ---------------------------------------------------------------------------
# Tier 1: entity creation + state progression
# ---------------------------------------------------------------------------

def create_sponsor(tier="SMALL_HUB", npe_total=5_000_000, name="Sponsor A", loc_id=None):
    """FAAManager registers a sponsor. Returns the sponsor dict."""
    overrides = {"airport_size_tier": tier, "npe_entitlement_total": npe_total,
                 "sponsor_name": name}
    if loc_id is not None:
        overrides["loc_id"] = loc_id
    return get_success_data(api_client.create_sponsor(create_sponsor_payload(**overrides), FAA))


def create_facility(sponsor_id, name="Runway 09/27", facility_type="RUNWAY"):
    return get_success_data(api_client.create_facility(
        create_facility_payload(sponsor_id, facility_name=name, facility_type=facility_type),
        SPONSOR))


def create_draft_program(sponsor_id, fiscal_year=2027):
    """SponsorStaff opens a program (starts DRAFT). Returns the program dict."""
    return get_success_data(api_client.create_program(
        create_program_payload(sponsor_id, fiscal_year=fiscal_year), SPONSOR))


def add_project(program_id, **overrides):
    """Add a project to a DRAFT or AMENDMENT_DRAFT program. Returns the project dict."""
    return get_success_data(api_client.create_project(
        create_project_payload(program_id, **overrides), SPONSOR))


def submit_program(program_id):
    return get_success_data(api_client.submit_program(program_id, SPONSOR))


def accept_program(program_id):
    """FAAManager accepts a SUBMITTED program. Returns the program dict (new version)."""
    return get_success_data(api_client.accept_program(program_id, FAA))


def apply_selection(program_id, selection_budget, expected_program_version):
    """Run the selection sweep (OCC-guarded). Returns the program dict after the sweep."""
    return get_success_data(api_client.apply_selection(
        program_id,
        {"selection_budget": selection_budget,
         "expected_program_version": expected_program_version},
        SPONSOR))


def setup_accepted_program_with_selection(sponsor_tier="SMALL_HUB",
                                          npe_total=5_000_000,
                                          project_overrides=None,
                                          selection_budget=2_000_000,
                                          fiscal_year=2027):
    """Sponsor -> DRAFT program -> one project -> submit -> accept -> apply-selection.

    Returns dict(sponsor, program, project); `program` is the post-sweep record.
    """
    sponsor = create_sponsor(tier=sponsor_tier, npe_total=npe_total)
    program = create_draft_program(sponsor["id"], fiscal_year=fiscal_year)
    project = add_project(program["id"], **(project_overrides or {}))
    submit_program(program["id"])
    accepted = accept_program(program["id"])
    program = apply_selection(program["id"], selection_budget, accepted["version"])
    project = get_success_data(api_client.get_project(project["id"], SPONSOR))
    return {"sponsor": sponsor, "program": program, "project": project}


# ---------------------------------------------------------------------------
# Tier 2: grant application assembly (assurance checklist, PRD §3.3)
# ---------------------------------------------------------------------------

def create_application(sponsor_id, program_id, project_ids,
                       creator_user_id=SPONSOR_USER_ID):
    """SponsorStaff files a grant application (six assurances auto-created PENDING)."""
    return get_success_data(api_client.create_application(
        create_application_payload(sponsor_id, program_id, project_ids),
        _headers_for(SPONSOR, creator_user_id)))


def list_assurances(application_id):
    """Return the application's assurance checklist rows."""
    return get_success_data(api_client.list_assurances(application_id, SPONSOR))


def certify_all_assurances(application_id, certifier_user_id=COMPLIANCE_USER_ID):
    """ComplianceOfficer certifies every PENDING assurance of the application.

    The certifier id must differ from the application's creator id (PRD §2.10).
    """
    for row in list_assurances(application_id):
        get_success_data(api_client.certify_assurance(
            row["id"], _headers_for(COMPLIANCE, certifier_user_id)))
    return get_success_data(api_client.get_application(application_id, SPONSOR))


def submit_application(application_id):
    return get_success_data(api_client.submit_application(application_id, SPONSOR))


def offer_application(application_id, discretionary_amount=None):
    payload = {}
    if discretionary_amount is not None:
        payload["discretionary_amount"] = discretionary_amount
    return get_success_data(api_client.offer_application(application_id, FAA, payload))


def setup_certified_application(sponsor_tier="SMALL_HUB", npe_total=5_000_000,
                                project_overrides=None, selection_budget=2_000_000,
                                creator_user_id=SPONSOR_USER_ID,
                                certifier_user_id=COMPLIANCE_USER_ID):
    """ACCEPTED program with one SELECTED project + application with all six
    assurances certified (still DRAFT). Returns dict(sponsor, program, project,
    application, assurances)."""
    base = setup_accepted_program_with_selection(
        sponsor_tier=sponsor_tier, npe_total=npe_total,
        project_overrides=project_overrides, selection_budget=selection_budget)
    application = create_application(
        base["sponsor"]["id"], base["program"]["id"], [base["project"]["id"]],
        creator_user_id=creator_user_id)
    assurances = list_assurances(application["id"])
    application = certify_all_assurances(application["id"], certifier_user_id)
    return {**base, "application": application, "assurances": assurances}


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — the ACTIVE grant (PRD §3.3 -> §3.4)
# ---------------------------------------------------------------------------

def setup_active_grant(sponsor_tier="SMALL_HUB", npe_total=5_000_000,
                       project_overrides=None, selection_budget=2_000_000,
                       discretionary_amount=None,
                       creator_user_id=SPONSOR_USER_ID,
                       certifier_user_id=COMPLIANCE_USER_ID):
    """Full chain through accept-offer: sponsor -> program -> project -> selection ->
    certified application -> submit -> offer -> accept-offer -> Grant ACTIVE.

    Returns dict(sponsor, program, project, application, grant).
    """
    ctx = setup_certified_application(
        sponsor_tier=sponsor_tier, npe_total=npe_total,
        project_overrides=project_overrides, selection_budget=selection_budget,
        creator_user_id=creator_user_id, certifier_user_id=certifier_user_id)
    submit_application(ctx["application"]["id"])
    offer_application(ctx["application"]["id"], discretionary_amount)
    application = get_success_data(api_client.accept_offer(ctx["application"]["id"], SPONSOR))
    grant = get_success_data(api_client.get_grant(application["created_grant_id"], SPONSOR))
    return {**ctx, "application": application, "grant": grant}


# ---------------------------------------------------------------------------
# Tier 3b: contracts, invoices, DBE reports
# ---------------------------------------------------------------------------

def create_contractor(sponsor_id, name="BuildCo", dbe_certified=False):
    return get_success_data(api_client.create_contractor(
        create_contractor_payload(sponsor_id, contractor_name=name,
                                  dbe_certified=dbe_certified), SPONSOR))


def award_contract(grant_id, project_id, contractor_id, awarded_value=500_000,
                   dbe_goal_pct=12.50, retainage_pct=0.10):
    """Award a contract (starts AWARDED, dbe_posture UNEVALUATED)."""
    return get_success_data(api_client.create_contract(
        create_contract_payload(grant_id, project_id, contractor_id,
                                awarded_value=awarded_value, dbe_goal_pct=dbe_goal_pct,
                                retainage_pct=retainage_pct), SPONSOR))


def file_invoice(contract_id, contractor_id, invoice_number="INV-1", period="2026-05",
                 gross_amount=100_000):
    """Contractor files an invoice against its own contract (ownership-gated)."""
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(contract_id, invoice_number=invoice_number, period=period,
                               gross_amount=gross_amount),
        make_contractor_headers(contractor_id)))


def verify_invoice(invoice_id):
    return get_success_data(api_client.verify_invoice(invoice_id, SPONSOR))


def reject_invoice(invoice_id):
    return get_success_data(api_client.reject_invoice(invoice_id, SPONSOR))


def setup_grant_with_contract(awarded_value=500_000, dbe_goal_pct=12.50,
                              retainage_pct=0.10, contractor_name="BuildCo",
                              **grant_kwargs):
    """ACTIVE grant + registered contractor + awarded contract.

    Returns dict(sponsor, program, project, application, grant, contractor, contract).
    """
    ctx = setup_active_grant(**grant_kwargs)
    contractor = create_contractor(ctx["sponsor"]["id"], name=contractor_name)
    contract = award_contract(ctx["grant"]["id"], ctx["project"]["id"], contractor["id"],
                              awarded_value=awarded_value, dbe_goal_pct=dbe_goal_pct,
                              retainage_pct=retainage_pct)
    return {**ctx, "contractor": contractor, "contract": contract}


def setup_grant_with_verified_invoice(invoice_number="INV-1", gross_amount=100_000,
                                      period="2026-05", **contract_kwargs):
    """ACTIVE grant + contract + one VERIFIED invoice.

    Returns dict(..., invoice) on top of setup_grant_with_contract's keys.
    Accepts the same overrides as setup_grant_with_contract plus invoice fields.
    """
    ctx = setup_grant_with_contract(**contract_kwargs)
    invoice = file_invoice(ctx["contract"]["id"], ctx["contractor"]["id"],
                           invoice_number=invoice_number, period=period,
                           gross_amount=gross_amount)
    invoice = verify_invoice(invoice["id"])
    contract = get_success_data(api_client.get_contract(ctx["contract"]["id"], SPONSOR))
    return {**ctx, "invoice": invoice, "contract": contract}


def file_dbe_report(contract_id, contractor_id, reporting_period, dbe_paid_amount,
                    total_paid_amount):
    """Contractor files a DBE report against its own contract (ownership-gated)."""
    return get_success_data(api_client.create_dbe_report(
        create_dbe_report_payload(contract_id, reporting_period, dbe_paid_amount,
                                  total_paid_amount),
        make_contractor_headers(contractor_id)))


def adjudicate_dbe_report(report_id, adjudicator_user_id=COMPLIANCE_USER_ID):
    return get_success_data(api_client.adjudicate_dbe_report(
        report_id, _headers_for(COMPLIANCE, adjudicator_user_id)))


# ---------------------------------------------------------------------------
# Tier 3c: reimbursement drawdown lifecycle (PRD §3.7)
# ---------------------------------------------------------------------------

def create_drawdown(grant_id, invoice_ids, preparer_user_id=FINANCE_USER_ID):
    """FinanceOfficer prepares a drawdown over VERIFIED invoices (starts DRAFT)."""
    return get_success_data(api_client.create_drawdown(
        create_drawdown_payload(grant_id, invoice_ids),
        _headers_for(FINANCE, preparer_user_id)))


def certify_drawdown(request_id, certifier_user_id=COMPLIANCE_USER_ID_2):
    """ComplianceOfficer certifies a DRAFT drawdown (certifier != preparer)."""
    return get_success_data(api_client.certify_drawdown(
        request_id, _headers_for(COMPLIANCE, certifier_user_id)))


def submit_drawdown(request_id, submitter_user_id=FINANCE_USER_ID):
    return get_success_data(api_client.submit_drawdown(
        request_id, _headers_for(FINANCE, submitter_user_id)))


def approve_drawdown(request_id):
    return get_success_data(api_client.approve_drawdown(request_id, FAA))


def create_certified_drawdown(grant_id, invoice_ids):
    return certify_drawdown(create_drawdown(grant_id, invoice_ids)["id"])


def create_submitted_drawdown(grant_id, invoice_ids):
    """Drawdown walked DRAFT -> CERTIFIED -> SUBMITTED. Returns the drawdown dict."""
    return submit_drawdown(create_certified_drawdown(grant_id, invoice_ids)["id"])


def create_approved_drawdown(grant_id, invoice_ids):
    """Drawdown walked all the way to APPROVED (funds moved, invoices PAID)."""
    return approve_drawdown(create_submitted_drawdown(grant_id, invoice_ids)["id"])


# ---------------------------------------------------------------------------
# Tier 4: assets, findings, phases
# ---------------------------------------------------------------------------

def register_asset(grant_id, **overrides):
    return get_success_data(api_client.create_grant_asset(
        create_grant_asset_payload(grant_id, **overrides), SPONSOR))


def request_disposal(asset_id):
    return get_success_data(api_client.request_disposal(asset_id, SPONSOR))


def record_finding(grant_id, **overrides):
    """Auditor records a finding against a grant in UNDER_AUDIT."""
    return get_success_data(api_client.create_audit_finding(
        create_audit_finding_payload(grant_id, **overrides), AUDITOR))


def create_phase(grant_id, project_id, facility_id, contractor_id, **overrides):
    return get_success_data(api_client.create_phase(
        create_phase_payload(grant_id, project_id, facility_id, contractor_id,
                             **overrides), SPONSOR))


def setup_phase_scenario(**grant_kwargs):
    """ACTIVE grant + one facility + one contractor (for construction-phase tests).

    Returns dict(sponsor, program, project, application, grant, facility, contractor).
    """
    ctx = setup_active_grant(**grant_kwargs)
    facility = create_facility(ctx["sponsor"]["id"])
    contractor = create_contractor(ctx["sponsor"]["id"])
    return {**ctx, "facility": facility, "contractor": contractor}


# ---------------------------------------------------------------------------
# Tier 5: finalization / terminal state (closeout audit, PRD §3.9)
# ---------------------------------------------------------------------------

def request_closeout(grant_id):
    return get_success_data(api_client.request_closeout(grant_id, SPONSOR))


def begin_audit(grant_id):
    return get_success_data(api_client.begin_audit(grant_id, AUDITOR))


def approve_closeout(grant_id):
    return get_success_data(api_client.approve_closeout(grant_id, FAA))


def setup_grant_under_audit(**grant_kwargs):
    """ACTIVE grant -> CLOSEOUT_REQUESTED -> UNDER_AUDIT (no drawdowns/phases).

    Returns setup_active_grant's keys with the grant in UNDER_AUDIT.
    """
    ctx = setup_active_grant(**grant_kwargs)
    request_closeout(ctx["grant"]["id"])
    grant = begin_audit(ctx["grant"]["id"])
    return {**ctx, "grant": grant}


def setup_closed_grant(**grant_kwargs):
    """Full lifecycle through CLOSED: ... -> UNDER_AUDIT -> approve-closeout.

    Returns setup_active_grant's keys with the grant in terminal CLOSED.
    """
    ctx = setup_grant_under_audit(**grant_kwargs)
    grant = approve_closeout(ctx["grant"]["id"])
    return {**ctx, "grant": grant}


# ---------------------------------------------------------------------------
# Convenience: create a grant amendment against a fresh grant version (PRD §3.4, §2.7)
# ---------------------------------------------------------------------------

def create_amendment(grant_id, added_scope_cost, reason, expected_grant_version):
    return get_success_data(api_client.create_amendment(
        grant_id,
        create_amendment_payload(added_scope_cost, reason, expected_grant_version),
        SPONSOR))


def current_grant_version(grant_id):
    return get_success_data(api_client.get_grant(grant_id, SPONSOR))["version"]
