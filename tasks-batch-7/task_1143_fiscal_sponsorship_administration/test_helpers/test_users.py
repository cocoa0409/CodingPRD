"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): ProjectLead is entity-backed — X-User-ID is the
acting Project's id — so any project-scoped write MUST use
make_project_lead_headers(project_id). Applicant is opaque but ownership-bound
against the stored applicant_user_id, so submit/withdraw/countersign MUST use
make_applicant_headers(applicant_user_id) with the filer's id. The remaining
roles are opaque operator identifiers; the operator id still matters wherever
the PRD records actors (segregation of duties on the disbursement chain,
pairwise-distinct exit signers).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (bad-payload 400s, 404 probes, reads by authorized roles).
TEST_USERS = {
    "applicant_headers": build_user_headers("user_app_shared", "Applicant"),
    "program_officer_headers": build_user_headers("user_po_1", "ProgramOfficer"),
    "compliance_officer_headers": build_user_headers("user_co_1", "ComplianceOfficer"),
    "finance_officer_headers": build_user_headers("user_fo_1", "FinanceOfficer"),
    "sponsor_admin_headers": build_user_headers("user_sa_1", "SponsorAdmin"),
    "donor_headers": build_user_headers("user_donor_1", "Donor"),
    # Entity-backed fallback — ONLY for non-ownership calls (plain GETs).
    "project_lead_headers": build_user_headers("test-project-lead-1", "ProjectLead"),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_applicant_headers(user_id: str) -> dict:
    """Applicant: pass the application's applicant_user_id for submit/withdraw/countersign."""
    return build_user_headers(user_id, "Applicant")


def make_project_lead_headers(project_id: str) -> dict:
    """ProjectLead is entity-backed: pass the actual Project.id for every
    project-scoped write (disbursements, engagements, exit plans, incidents)."""
    return build_user_headers(project_id, "ProjectLead")


def make_program_officer_headers(user_id: str = "user_po_1") -> dict:
    return build_user_headers(user_id, "ProgramOfficer")


def make_compliance_officer_headers(user_id: str = "user_co_1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_finance_officer_headers(user_id: str = "user_fo_1") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_sponsor_admin_headers(user_id: str = "user_sa_1") -> dict:
    return build_user_headers(user_id, "SponsorAdmin")


def make_donor_headers(user_id: str = "user_donor_1") -> dict:
    return build_user_headers(user_id, "Donor")
