"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the server is restarted before each test, so nothing carries over).
Setup calls use get_success_data() so failures surface as clear setup errors.

Identity threading: project-scoped ProjectLead writes always use
make_project_lead_headers(project_id); applicant ownership calls use
make_applicant_headers(applicant_user_id) with the filer's id; opaque operator
roles take explicit ids wherever the PRD records actors (SoD chain, signers).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CO_USER, DONOR_USER, FO_USER, PASSING_SCORECARD, PO_USER, SA_USER, SA_USER_2,
)
from .factories import (
    classification_review_payload,
    close_period_payload,
    close_tranche_payload,
    compliance_decision_payload,
    create_application_payload,
    create_compliance_review_payload,
    create_disbursement_payload,
    create_donation_payload,
    create_exit_plan_payload,
    create_grant_tranche_payload,
    create_risk_incident_payload,
    create_staff_engagement_payload,
    decide_refund_payload,
    fund_adjustment_payload,
    issue_findings_payload,
    mission_score_payload,
    request_refund_payload,
    review_decision_payload,
    signoff_payload,
)
from .test_users import (
    make_applicant_headers,
    make_compliance_officer_headers,
    make_donor_headers,
    make_finance_officer_headers,
    make_program_officer_headers,
    make_project_lead_headers,
    make_sponsor_admin_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: logical clock + reads
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, admin_id: str = SA_USER) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, make_sponsor_admin_headers(admin_id))
    return get_success_data(resp)


def get_project(project_id: str, reader: str = SA_USER) -> dict:
    return get_success_data(api_client.get_project(project_id, make_sponsor_admin_headers(reader)))


def get_agreement(agreement_id: str, reader: str = SA_USER) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, make_sponsor_admin_headers(reader)))


def get_fund(fund_account_id: str, reader: str = FO_USER) -> dict:
    return get_success_data(api_client.get_fund_account(fund_account_id, make_finance_officer_headers(reader)))


def get_disbursement(disbursement_id: str, reader: str = SA_USER) -> dict:
    return get_success_data(api_client.get_disbursement(disbursement_id, make_sponsor_admin_headers(reader)))


def get_engagement(engagement_id: str, reader: str = CO_USER) -> dict:
    return get_success_data(api_client.get_staff_engagement(engagement_id, make_compliance_officer_headers(reader)))


# ---------------------------------------------------------------------------
# Tier 1: application lifecycle (PRD §3.1)
# ---------------------------------------------------------------------------
def create_application(applicant_id: str, **overrides) -> dict:
    """Create a DRAFT application owned by applicant_id."""
    resp = api_client.create_application(
        create_application_payload(**overrides), make_applicant_headers(applicant_id))
    return get_success_data(resp)


def submit_application(application_id: str, applicant_id: str) -> dict:
    resp = api_client.submit_application(application_id, make_applicant_headers(applicant_id))
    return get_success_data(resp)


def score_mission(application_id: str, action: str = "ADVANCE",
                  officer_id: str = PO_USER, **scorecard) -> dict:
    score = dict(PASSING_SCORECARD)
    score.update(scorecard)
    resp = api_client.score_mission(
        application_id, mission_score_payload(action=action, **score),
        make_program_officer_headers(officer_id))
    return get_success_data(resp)


def decide_application(application_id: str, decision: str, sponsorship_model: str = None,
                       officer_id: str = CO_USER, **extra) -> dict:
    payload = compliance_decision_payload(decision=decision, **extra)
    if sponsorship_model is not None:
        payload["sponsorship_model"] = sponsorship_model
    resp = api_client.decide_compliance(
        application_id, payload, make_compliance_officer_headers(officer_id))
    return get_success_data(resp)


def countersign(agreement_id: str, applicant_id: str) -> dict:
    resp = api_client.countersign_agreement(agreement_id, make_applicant_headers(applicant_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: approval cascade bundles (PRD §3.1 → §3.2)
# ---------------------------------------------------------------------------
def create_approved_bundle(applicant_id: str, model: str = "COMPREHENSIVE", **app_overrides) -> dict:
    """Application approved; Project PROPOSED, agreement PENDING_COUNTERSIGN, fund PENDING."""
    app = create_application(applicant_id, requested_model=model, **app_overrides)
    submit_application(app["id"], applicant_id)
    score_mission(app["id"], action="ADVANCE")
    decided = decide_application(app["id"], "APPROVE", sponsorship_model=model)
    return {
        "application": decided,
        "applicant_id": applicant_id,
        "project_id": decided["project_id"],
        "agreement_id": decided["agreement_id"],
        "fund_account_id": decided["fund_account_id"],
        "model": model,
    }


def create_active_bundle(applicant_id: str, model: str = "COMPREHENSIVE", **app_overrides) -> dict:
    """Approved + countersigned: project ACTIVE, agreement ACTIVE, fund ACTIVE."""
    bundle = create_approved_bundle(applicant_id, model=model, **app_overrides)
    countersign(bundle["agreement_id"], applicant_id)
    return bundle


# ---------------------------------------------------------------------------
# Tier 2: donations (PRD §3.3)
# ---------------------------------------------------------------------------
def pledge_donation(project_id: str, amount_cents: int, donor_id: str = DONOR_USER, **overrides) -> dict:
    resp = api_client.create_donation(
        project_id, create_donation_payload(amount_cents=amount_cents, **overrides),
        make_donor_headers(donor_id))
    return get_success_data(resp)


def receive_donation(donation_id: str, finance_id: str = FO_USER) -> dict:
    return get_success_data(api_client.receive_donation(donation_id, make_finance_officer_headers(finance_id)))


def issue_receipt(donation_id: str, finance_id: str = FO_USER) -> dict:
    return get_success_data(api_client.issue_receipt(donation_id, make_finance_officer_headers(finance_id)))


def create_received_donation(project_id: str, amount_cents: int, donor_id: str = DONOR_USER,
                             finance_id: str = FO_USER, **overrides) -> dict:
    """Pledge + receive. Returns the RECEIVED donation (fee_cents assessed)."""
    donation = pledge_donation(project_id, amount_cents, donor_id=donor_id, **overrides)
    return receive_donation(donation["id"], finance_id=finance_id)


def create_receipted_donation(project_id: str, amount_cents: int, donor_id: str = DONOR_USER,
                              finance_id: str = FO_USER, **overrides) -> dict:
    """Pledge + receive + issue tax receipt. Returns the RECEIPTED donation."""
    donation = create_received_donation(project_id, amount_cents, donor_id=donor_id,
                                        finance_id=finance_id, **overrides)
    return issue_receipt(donation["id"], finance_id=finance_id)


# ---------------------------------------------------------------------------
# Tier 3: disbursement pipeline (PRD §3.4)
# ---------------------------------------------------------------------------
def create_disbursement_draft(project_id: str, amount_cents: int, **overrides) -> dict:
    resp = api_client.create_disbursement(
        project_id, create_disbursement_payload(amount_cents=amount_cents, **overrides),
        make_project_lead_headers(project_id))
    return get_success_data(resp)


def submit_disbursement(disbursement_id: str, project_id: str) -> dict:
    return get_success_data(api_client.submit_disbursement(
        disbursement_id, make_project_lead_headers(project_id)))


def create_submitted_disbursement(project_id: str, amount_cents: int, **overrides) -> dict:
    draft = create_disbursement_draft(project_id, amount_cents, **overrides)
    return submit_disbursement(draft["id"], project_id)


def compliance_approve_disbursement(disbursement_id: str, officer_id: str = CO_USER) -> dict:
    return get_success_data(api_client.compliance_review_disbursement(
        disbursement_id, review_decision_payload(decision="APPROVE"),
        make_compliance_officer_headers(officer_id)))


def sponsor_approve_disbursement(disbursement_id: str, admin_id: str = SA_USER) -> dict:
    return get_success_data(api_client.sponsor_approve_disbursement(
        disbursement_id, review_decision_payload(decision="APPROVE"),
        make_sponsor_admin_headers(admin_id)))


def pay_disbursement(disbursement_id: str, finance_id: str = FO_USER) -> dict:
    return get_success_data(api_client.pay_disbursement(
        disbursement_id, make_finance_officer_headers(finance_id)))


def create_approved_disbursement(project_id: str, amount_cents: int,
                                 officer_id: str = CO_USER, **overrides) -> dict:
    """Draft -> submit -> compliance APPROVE (APPROVED_FOR_PAYMENT when not high-value)."""
    submitted = create_submitted_disbursement(project_id, amount_cents, **overrides)
    return compliance_approve_disbursement(submitted["id"], officer_id=officer_id)


def create_paid_disbursement(project_id: str, amount_cents: int, officer_id: str = CO_USER,
                             finance_id: str = FO_USER, **overrides) -> dict:
    """Draft -> submit -> compliance APPROVE -> pay. Amount must be below the high-value line."""
    approved = create_approved_disbursement(project_id, amount_cents, officer_id=officer_id, **overrides)
    return pay_disbursement(approved["id"], finance_id=finance_id)


def pay_staff(project_id: str, engagement_id: str, amount_cents: int, spend_date: str,
              officer_id: str = CO_USER, finance_id: str = FO_USER,
              payee_name: str = "Test Worker", purpose: str = "staff milestone") -> dict:
    """Full pipeline to PAID for a STAFF payee linked to an ACTIVE engagement."""
    return create_paid_disbursement(
        project_id, amount_cents, officer_id=officer_id, finance_id=finance_id,
        payee_type="STAFF", payee_name=payee_name, spend_date=spend_date,
        staff_engagement_id=engagement_id, purpose=purpose)


# ---------------------------------------------------------------------------
# Tier 3: staff engagements (PRD §3.5)
# ---------------------------------------------------------------------------
def propose_engagement(project_id: str, worker_email: str, **overrides) -> dict:
    resp = api_client.create_staff_engagement(
        project_id, create_staff_engagement_payload(worker_email=worker_email, **overrides),
        make_project_lead_headers(project_id))
    return get_success_data(resp)


def vet_engagement(engagement_id: str, approved_type: str = "CONTRACTOR",
                   officer_id: str = CO_USER, rationale: str = "vetted") -> dict:
    return get_success_data(api_client.classification_review_engagement(
        engagement_id, classification_review_payload(approved_type=approved_type, rationale=rationale),
        make_compliance_officer_headers(officer_id)))


def activate_engagement(engagement_id: str, project_id: str) -> dict:
    return get_success_data(api_client.activate_engagement(
        engagement_id, make_project_lead_headers(project_id)))


def create_vetted_engagement(project_id: str, worker_email: str,
                             engagement_type: str = "CONTRACTOR", **overrides) -> dict:
    proposed = propose_engagement(project_id, worker_email, engagement_type=engagement_type, **overrides)
    return vet_engagement(proposed["id"], approved_type=engagement_type)


def create_active_engagement(project_id: str, worker_email: str,
                             engagement_type: str = "CONTRACTOR", **overrides) -> dict:
    vetted = create_vetted_engagement(project_id, worker_email,
                                      engagement_type=engagement_type, **overrides)
    return activate_engagement(vetted["id"], project_id)


# ---------------------------------------------------------------------------
# Tier 3: compliance reviews and risk incidents (PRD §3.6)
# ---------------------------------------------------------------------------
def open_review(project_id: str, review_type: str = "TRIGGERED", officer_id: str = CO_USER,
                **overrides) -> dict:
    resp = api_client.create_compliance_review(
        project_id, create_compliance_review_payload(review_type=review_type, **overrides),
        make_compliance_officer_headers(officer_id))
    return get_success_data(resp)


def issue_findings(review_id: str, findings_count: int, severity_max: str = "MEDIUM",
                   officer_id: str = CO_USER) -> dict:
    return get_success_data(api_client.issue_findings(
        review_id, issue_findings_payload(findings_count=findings_count, severity_max=severity_max),
        make_compliance_officer_headers(officer_id)))


def create_findings_review(project_id: str, findings_count: int, severity_max: str = "MEDIUM",
                           officer_id: str = CO_USER, **overrides) -> dict:
    review = open_review(project_id, officer_id=officer_id, **overrides)
    return issue_findings(review["id"], findings_count, severity_max, officer_id=officer_id)


def report_incident(project_id: str, severity: str = "LOW", category: str = "LIABILITY",
                    reporter: str = "compliance", description: str = "test incident") -> dict:
    headers = (make_compliance_officer_headers(CO_USER) if reporter == "compliance"
               else make_project_lead_headers(project_id))
    resp = api_client.create_risk_incident(
        project_id, create_risk_incident_payload(
            category=category, severity=severity, description=description), headers)
    return get_success_data(resp)


def suspend_project(project_id: str, reason: str = "audit hold", admin_id: str = SA_USER) -> dict:
    return get_success_data(api_client.suspend_project(
        project_id, {"reason": reason}, make_sponsor_admin_headers(admin_id)))


def reinstate_project(project_id: str, admin_id: str = SA_USER) -> dict:
    return get_success_data(api_client.reinstate_project(
        project_id, make_sponsor_admin_headers(admin_id)))


# ---------------------------------------------------------------------------
# Tier 5: exit plans (PRD §3.8)
# ---------------------------------------------------------------------------
def propose_exit_plan(project_id: str, proposer: str = "lead", **overrides) -> dict:
    headers = (make_project_lead_headers(project_id) if proposer == "lead"
               else make_sponsor_admin_headers(SA_USER))
    resp = api_client.create_exit_plan(
        project_id, create_exit_plan_payload(**overrides), headers)
    return get_success_data(resp)


def begin_due_diligence(exit_plan_id: str, admin_id: str = SA_USER) -> dict:
    return get_success_data(api_client.begin_due_diligence(
        exit_plan_id, make_sponsor_admin_headers(admin_id)))


def sign_exit_plan(exit_plan_id: str, project_id: str, party: str, signer_id: str) -> dict:
    """party PROJECT_LEAD signs with the Project id; SPONSOR_BOARD/SUCCESSOR_REP sign as SponsorAdmin."""
    headers = (make_project_lead_headers(project_id) if party == "PROJECT_LEAD"
               else make_sponsor_admin_headers(signer_id))
    return get_success_data(api_client.signoff_exit_plan(
        exit_plan_id, signoff_payload(party=party), headers))


def create_due_diligence_exit_plan(project_id: str, admin_id: str = SA_USER, **overrides) -> dict:
    plan = propose_exit_plan(project_id, **overrides)
    return begin_due_diligence(plan["id"], admin_id=admin_id)


def create_approved_exit_plan(project_id: str, board_signer: str = SA_USER,
                              successor_signer: str = SA_USER_2, **overrides) -> dict:
    """Exit plan carried to APPROVED via three pairwise-distinct party signoffs."""
    plan = create_due_diligence_exit_plan(project_id, **overrides)
    sign_exit_plan(plan["id"], project_id, "SPONSOR_BOARD", board_signer)
    sign_exit_plan(plan["id"], project_id, "SUCCESSOR_REP", successor_signer)
    return sign_exit_plan(plan["id"], project_id, "PROJECT_LEAD", project_id)


# ---------------------------------------------------------------------------
# Tier 2: grant tranches (PRD §3.2)
# ---------------------------------------------------------------------------
def create_tranche(agreement_id: str, amount_cents: int = 100000,
                   period_start: str = "2026-01-01", period_end: str = "2026-03-31",
                   purpose: str = "restricted grant purpose", admin_id: str = SA_USER) -> dict:
    resp = api_client.create_grant_tranche(
        agreement_id, create_grant_tranche_payload(
            amount_cents=amount_cents, period_start=period_start,
            period_end=period_end, purpose=purpose),
        make_sponsor_admin_headers(admin_id))
    return get_success_data(resp)


def close_tranche(tranche_id: str, report_note: str = "final report", admin_id: str = SA_USER) -> dict:
    return get_success_data(api_client.close_grant_tranche(
        tranche_id, close_tranche_payload(report_note=report_note),
        make_sponsor_admin_headers(admin_id)))


# ---------------------------------------------------------------------------
# Tier 2: fund administration (PRD §3.7)
# ---------------------------------------------------------------------------
def post_adjustment(fund_account_id: str, expected_version: int, amount_cents: int,
                    memo: str = "adjustment", finance_id: str = FO_USER) -> dict:
    return get_success_data(api_client.post_fund_adjustment(
        fund_account_id,
        fund_adjustment_payload(expected_version, amount_cents, memo=memo),
        make_finance_officer_headers(finance_id)))


def close_period(fund_account_id: str, period_start: str, period_end: str,
                 finance_id: str = FO_USER) -> dict:
    return get_success_data(api_client.close_period(
        fund_account_id, close_period_payload(period_start=period_start, period_end=period_end),
        make_finance_officer_headers(finance_id)))


def request_refund(donation_id: str, amount_cents: int, requester: str = "donor",
                   reason: str = "refund request") -> dict:
    headers = (make_donor_headers(DONOR_USER) if requester == "donor"
               else make_finance_officer_headers(FO_USER))
    return get_success_data(api_client.request_refund(
        donation_id, request_refund_payload(amount_cents=amount_cents, reason=reason), headers))


def decide_refund(donation_id: str, decision: str = "APPROVE", admin_id: str = SA_USER) -> dict:
    return get_success_data(api_client.decide_refund(
        donation_id, decide_refund_payload(decision=decision),
        make_sponsor_admin_headers(admin_id)))
