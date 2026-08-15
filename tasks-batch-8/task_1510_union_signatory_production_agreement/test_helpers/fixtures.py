"""Composite setup helpers for the union-compliance API (PRD §3 workflows).

The server restarts before every test, so each helper builds its preconditions
from scratch using only PRD-declared endpoints. All setup calls go through
get_success_data() so failures surface as clear "Setup step failed" errors.

Common bundles returned by the composite helpers are plain dicts, e.g.:
    {"company": ..., "application": ..., "production": ..., "bond": ...,
     "assignments": {"W-CAM-1": ...}, "owner": <ProducerRep headers>}
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_BUDGET_CENTS, ULB_BOND_CENTS
from .factories import (
    create_audit_payload,
    create_contribution_report_payload,
    create_crew_assignment_payload,
    create_force_majeure_event_payload,
    create_grievance_payload,
    create_producer_company_payload,
    create_production_payload,
    create_signatory_application_payload,
    create_work_day_log_payload,
)
from .test_users import (
    TEST_USERS,
    make_producer_rep_headers,
)

# Standard ULB-minimum crew roster: (ref, department, classification, rate).
STANDARD_CREW = (
    ("W-CAM-1", "CAMERA", "CAMERA_OPERATOR", 100_000),
    ("W-GRIP-1", "GRIP_ELECTRIC", "GAFFER", 90_000),
    ("W-SND-1", "SOUND", "BOOM_OPERATOR", 80_000),
)

MEAL_600 = [{"start_minutes": 600, "end_minutes": 630}]


# ---------------------------------------------------------------------------
# Tier 1 — companies, applications, productions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the server logical clock (PRD §2.5), as PlatformAdmin."""
    return get_success_data(api_client.set_clock(
        {"to_iso8601": to_iso8601}, TEST_USERS["platform_admin_headers"],
    ))


def register_company(legal_name: str = "Test Films LLC", fein: str = "20-0000001") -> dict:
    """Register a ProducerCompany (PENDING, version 1). Registration is exempt
    from the ProducerRep ownership check (PRD §2.1)."""
    return get_success_data(api_client.create_producer_company(
        create_producer_company_payload(legal_name=legal_name, fein=fein),
        TEST_USERS["producer_rep_headers"],
    ))


def owner_headers(company: dict) -> dict:
    """ProducerRep headers threaded with the owning company's id."""
    return make_producer_rep_headers(company["id"])


def get_company(company: dict) -> dict:
    return get_success_data(api_client.get_producer_company(company["id"], owner_headers(company)))


def create_application(company: dict, scope: str = "THEATRICAL",
                       slate: int = DEFAULT_BUDGET_CENTS) -> dict:
    return get_success_data(api_client.create_signatory_application(
        create_signatory_application_payload(
            producer_company_id=company["id"],
            requested_agreement_scope=scope,
            estimated_slate_budget_cents=slate,
        ),
        owner_headers(company),
    ))


def submit_application(application: dict, company: dict) -> dict:
    return get_success_data(api_client.submit_application(
        application["id"], {}, owner_headers(company),
    ))


def approve_application(application: dict) -> dict:
    """UnionRep decides APPROVE (also flips a PENDING company to SIGNATORY)."""
    return get_success_data(api_client.decide_application(
        application["id"], {"decision": "APPROVE"}, TEST_USERS["union_rep_headers"],
    ))


def create_signatory_company(legal_name: str = "Test Films LLC", fein: str = "20-0000001",
                             scope: str = "THEATRICAL",
                             slate: int = DEFAULT_BUDGET_CENTS) -> tuple:
    """Company driven PENDING -> SIGNATORY via an approved application.
    Returns (company_refetched, application)."""
    company = register_company(legal_name, fein)
    application = create_application(company, scope, slate)
    submit_application(application, company)
    approve_application(application)
    return get_company(company), application


def create_production(company: dict, title: str = "Test Production",
                      tier: str = "ULTRA_LOW_BUDGET",
                      budget: int = DEFAULT_BUDGET_CENTS) -> dict:
    return get_success_data(api_client.create_production(
        create_production_payload(
            producer_company_id=company["id"], title=title,
            agreement_tier=tier, budget_cents=budget,
        ),
        owner_headers(company),
    ))


def get_production(production_id: str, company: dict) -> dict:
    return get_success_data(api_client.get_production(production_id, owner_headers(company)))


def get_production_bond(production: dict, company: dict) -> dict:
    """The production's single auto-created bond (PRD §3.2)."""
    bonds = get_success_data(api_client.list_production_bonds(
        production["id"], owner_headers(company),
    ))
    assert isinstance(bonds, list) and len(bonds) == 1, (
        f"Setup failed: expected exactly 1 bond, got {bonds}"
    )
    return bonds[0]


def post_bond(bond: dict, company: dict, amount: int = ULB_BOND_CENTS) -> dict:
    return get_success_data(api_client.post_bond(
        bond["id"], {"amount_cents": amount}, owner_headers(company),
    ))


def create_staffing_production(legal_name: str = "Test Films LLC", fein: str = "20-0000001",
                               title: str = "Test Production",
                               tier: str = "ULTRA_LOW_BUDGET",
                               budget: int = DEFAULT_BUDGET_CENTS,
                               bond_amount: int = ULB_BOND_CENTS,
                               scope: str = "THEATRICAL") -> dict:
    """SIGNATORY company + production with bond POSTED (production STAFFING)."""
    company, application = create_signatory_company(legal_name, fein, scope=scope)
    production = create_production(company, title, tier, budget)
    bond = get_production_bond(production, company)
    bond = post_bond(bond, company, bond_amount)
    production = get_production(production["id"], company)
    return {"company": company, "application": application,
            "production": production, "bond": bond, "owner": owner_headers(company)}


# ---------------------------------------------------------------------------
# Tier 2 — crew and production start
# ---------------------------------------------------------------------------

def hire_crew(production: dict, company: dict, ref: str, department: str,
              classification: str, rate: int) -> dict:
    return get_success_data(api_client.create_crew_assignment(
        create_crew_assignment_payload(
            production_id=production["id"], crew_member_ref=ref,
            department=department, classification=classification,
            daily_rate_cents=rate,
        ),
        owner_headers(company),
    ))


def transition_assignment(assignment: dict, company: dict, to_state: str) -> dict:
    return get_success_data(api_client.transition_crew_assignment(
        assignment["id"], {"to_state": to_state}, owner_headers(company),
    ))


def start_production(production: dict, company: dict) -> dict:
    return get_success_data(api_client.start_production(production["id"], owner_headers(company)))


def create_in_production(legal_name: str = "Test Films LLC", fein: str = "20-0000001",
                         title: str = "Test Production",
                         crew=STANDARD_CREW, activate: tuple = (),
                         scope: str = "THEATRICAL") -> dict:
    """SIGNATORY company + ULB production driven to IN_PRODUCTION.

    `crew` is a tuple of (ref, department, classification, rate); every listed
    member is hired while STAFFING. `activate` names refs to flip HIRED->ACTIVE
    after start. Returns a bundle with assignments keyed by crew_member_ref.
    """
    bundle = create_staffing_production(legal_name, fein, title, scope=scope)
    company, owner = bundle["company"], bundle["owner"]
    assignments = {}
    for ref, department, classification, rate in crew:
        assignments[ref] = hire_crew(bundle["production"], company,
                                     ref, department, classification, rate)
    bundle["production"] = start_production(bundle["production"], company)
    for ref in activate:
        assignments[ref] = transition_assignment(assignments[ref], company, "ACTIVE")
    bundle["assignments"] = assignments
    return bundle


# ---------------------------------------------------------------------------
# Tier 3 — work day logs
# ---------------------------------------------------------------------------

def record_log(assignment: dict, company: dict, work_date: str = "2026-08-10",
               call: int = 480, wrap: int = 960, meals=None) -> dict:
    if meals is None:
        meals = MEAL_600
    return get_success_data(api_client.create_work_day_log(
        create_work_day_log_payload(
            crew_assignment_id=assignment["id"], work_date=work_date,
            call_time_minutes=call, wrap_time_minutes=wrap, meal_breaks=meals,
        ),
        owner_headers(company),
    ))


def submit_log(log: dict, company: dict) -> dict:
    return get_success_data(api_client.submit_work_day_log(log["id"], owner_headers(company)))


def void_log(log: dict, company: dict) -> dict:
    return get_success_data(api_client.void_work_day_log(log["id"], owner_headers(company)))


# ---------------------------------------------------------------------------
# Tier 3 — grievances
# ---------------------------------------------------------------------------

def file_grievance(production: dict, category: str = "PAY",
                   incident_date: str = "2026-07-20",
                   description: str = "Test grievance",
                   union_user: str = "ur_1",
                   crew_assignment_id=None) -> dict:
    payload = create_grievance_payload(
        production_id=production["id"], category=category,
        incident_date=incident_date, description=description,
    )
    if crew_assignment_id is not None:
        payload["crew_assignment_id"] = crew_assignment_id
    return get_success_data(api_client.create_grievance(
        payload, {"X-User-ID": union_user, "X-User-Role": "UnionRep",
                  "Content-Type": "application/json"},
    ))


def accept_intake(grievance: dict, union_user: str = "ur_1") -> dict:
    return get_success_data(api_client.accept_grievance_intake(
        grievance["id"],
        {"X-User-ID": union_user, "X-User-Role": "UnionRep",
         "Content-Type": "application/json"},
    ))


def propose_settlement(grievance: dict, amount: int, version: int,
                       union_user: str = "ur_2") -> dict:
    return get_success_data(api_client.propose_settlement(
        grievance["id"],
        {"proposal_amount_cents": amount, "expected_grievance_version": version},
        {"X-User-ID": union_user, "X-User-Role": "UnionRep",
         "Content-Type": "application/json"},
    ))


def respond_settlement(grievance: dict, company: dict, decision: str) -> dict:
    return get_success_data(api_client.respond_settlement(
        grievance["id"], {"decision": decision}, owner_headers(company),
    ))


def escalate_grievance(grievance: dict, union_user: str = "ur_1") -> dict:
    return get_success_data(api_client.escalate_grievance(
        grievance["id"],
        {"X-User-ID": union_user, "X-User-Role": "UnionRep",
         "Content-Type": "application/json"},
    ))


def decide_grievance(grievance: dict, award: int, notes: str = None) -> dict:
    payload = {"award_cents": award}
    if notes is not None:
        payload["decision_notes"] = notes
    return get_success_data(api_client.decide_grievance(
        grievance["id"], payload, TEST_USERS["arbitrator_headers"],
    ))


def pay_grievance(grievance: dict, company: dict, amount: int) -> dict:
    return get_success_data(api_client.pay_grievance(
        grievance["id"], {"amount_cents": amount}, owner_headers(company),
    ))


def refund_grievance(grievance: dict, company: dict, amount: int) -> dict:
    return get_success_data(api_client.refund_grievance(
        grievance["id"], {"amount_cents": amount}, owner_headers(company),
    ))


def create_resolved_grievance(bundle: dict, amount: int = 70_000,
                              incident_date: str = "2026-07-20") -> dict:
    """Grievance driven FILED -> INVESTIGATING -> PROPOSED_SETTLEMENT -> RESOLVED
    (intake by ur_1, proposal by ur_2, ACCEPT by the producer)."""
    company = bundle["company"]
    grievance = file_grievance(bundle["production"], incident_date=incident_date,
                               union_user="ur_1")
    grievance = accept_intake(grievance, "ur_1")
    grievance = propose_settlement(grievance, amount, grievance["version"], "ur_2")
    grievance = respond_settlement(grievance, company, "ACCEPT")
    assert grievance["status"] == "RESOLVED", (
        f"Setup failed: expected RESOLVED, got {grievance['status']}"
    )
    return grievance


# ---------------------------------------------------------------------------
# Tier 3/4 — contribution reports and audits
# ---------------------------------------------------------------------------

def create_report(production: dict, company: dict, period: int, log_ids: list) -> dict:
    return get_success_data(api_client.create_contribution_report(
        create_contribution_report_payload(
            production_id=production["id"], period_index=period,
            work_day_log_ids=log_ids,
        ),
        owner_headers(company),
    ))


def submit_report(report: dict, company: dict) -> dict:
    return get_success_data(api_client.submit_contribution_report(
        report["id"], owner_headers(company),
    ))


def review_report(report: dict, decision: str, trustee_user: str = "ft_1",
                  reason: str = None) -> dict:
    payload = {"decision": decision}
    if reason is not None:
        payload["rejection_reason"] = reason
    return get_success_data(api_client.review_contribution_report(
        report["id"], payload,
        {"X-User-ID": trustee_user, "X-User-Role": "FundTrustee",
         "Content-Type": "application/json"},
    ))


def create_accepted_report(production: dict, company: dict, period: int,
                           log_ids: list, trustee_user: str = "ft_9") -> dict:
    report = create_report(production, company, period, log_ids)
    report = submit_report(report, company)
    return review_report(report, "ACCEPT", trustee_user)


def open_audit(production: dict, scope: list, trustee_user: str = "ft_1") -> dict:
    return get_success_data(api_client.create_audit(
        create_audit_payload(production_id=production["id"], scope_period_indices=scope),
        {"X-User-ID": trustee_user, "X-User-Role": "FundTrustee",
         "Content-Type": "application/json"},
    ))


def issue_findings(audit: dict, trustee_user: str = "ft_1") -> dict:
    return get_success_data(api_client.issue_audit_findings(
        audit["id"],
        {"X-User-ID": trustee_user, "X-User-Role": "FundTrustee",
         "Content-Type": "application/json"},
    ))


def pay_audit(audit: dict, company: dict, amount: int) -> dict:
    return get_success_data(api_client.pay_audit(
        audit["id"], {"amount_cents": amount}, owner_headers(company),
    ))


def close_audit(audit: dict, trustee_user: str = "ft_2") -> dict:
    return get_success_data(api_client.close_audit(
        audit["id"],
        {"X-User-ID": trustee_user, "X-User-Role": "FundTrustee",
         "Content-Type": "application/json"},
    ))


# ---------------------------------------------------------------------------
# Tier 3 — force majeure
# ---------------------------------------------------------------------------

def declare_force_majeure(production: dict, event_type: str = "STRIKE",
                          start: str = "2026-08-05", end=None,
                          union_user: str = "ur_1") -> dict:
    payload = create_force_majeure_event_payload(
        production_id=production["id"], event_type=event_type, start_date=start,
    )
    if end is not None:
        payload["end_date"] = end
    return get_success_data(api_client.create_force_majeure_event(
        payload,
        {"X-User-ID": union_user, "X-User-Role": "UnionRep",
         "Content-Type": "application/json"},
    ))


def lift_force_majeure(event: dict, union_user: str = "ur_1") -> dict:
    return get_success_data(api_client.lift_force_majeure_event(
        event["id"],
        {"X-User-ID": union_user, "X-User-Role": "UnionRep",
         "Content-Type": "application/json"},
    ))


# ---------------------------------------------------------------------------
# Tier 4/5 — budget revisions, wrapped/closed productions, accepted reports
# ---------------------------------------------------------------------------

def revise_budget(production: dict, company: dict, new_budget: int) -> dict:
    """OCC-guarded budget revision using the live production version."""
    current = get_production(production["id"], company)
    return get_success_data(api_client.create_budget_revision(
        production["id"],
        {"new_budget_cents": new_budget,
         "expected_production_version": current["version"]},
        owner_headers(company),
    ))


def setup_wrapped_production(**kwargs) -> dict:
    """IN_PRODUCTION production with every assignment WRAPPED, then WRAPPED."""
    bundle = create_in_production(**kwargs)
    company = bundle["company"]
    for ref, assignment in list(bundle["assignments"].items()):
        bundle["assignments"][ref] = transition_assignment(assignment, company, "WRAPPED")
    bundle["production"] = get_success_data(api_client.wrap_production(
        bundle["production"]["id"], bundle["owner"],
    ))
    return bundle


def setup_closed_production(**kwargs) -> dict:
    """Full lifecycle through CLOSED (no reports/grievances/audits — vacuously
    satisfied per PRD §3.8; bond remains POSTED)."""
    bundle = setup_wrapped_production(**kwargs)
    bundle["production"] = get_success_data(api_client.close_production(
        bundle["production"]["id"], bundle["owner"],
    ))
    return bundle


def setup_accepted_report(legal_name: str = "Report Films LLC", fein: str = "20-0000101",
                          period: int = 1, rate: int = 100_000,
                          work_date: str = "2026-08-10") -> dict:
    """ULB production IN_PRODUCTION with one ACTIVE CAMERA assignment (plus HIRED
    GRIP/SOUND for staffing), one SUBMITTED log, and an ACCEPTED report for
    `period` covering that log. Returns bundle with log/report attached."""
    bundle = create_in_production(
        legal_name=legal_name, fein=fein,
        crew=(("W-CAM-1", "CAMERA", "CAMERA_OPERATOR", rate),) + STANDARD_CREW[1:],
        activate=("W-CAM-1",),
    )
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]
    log = record_log(cam, company, work_date)
    log = submit_log(log, company)
    report = create_accepted_report(bundle["production"], company, period, [log["id"]])
    bundle["log"] = log
    bundle["report"] = report
    return bundle
