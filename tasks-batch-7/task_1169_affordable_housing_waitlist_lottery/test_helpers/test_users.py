"""Pre-built role headers for every role in the PRD (§2.1).

Seven roles are opaque operator identities; their X-User-ID is a free-form
operator identifier recorded on audit fields. The Applicant role is
entity-backed: X-User-ID must be the acting Applicant record's id, so any
ownership-gated call MUST use make_applicant_headers(applicant_id) with the
real Applicant.id returned by registration — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# applicant ownership (bad-payload, not-found, and exclusive-role rejections).
TEST_USERS = {
    "housing_developer_headers": build_user_headers("dev-1", "HousingDeveloper"),
    "marketing_coordinator_headers": build_user_headers("mc-1", "MarketingCoordinator"),
    "application_clerk_headers": build_user_headers("clerk-1", "ApplicationClerk"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "lottery_administrator_headers": build_user_headers("lot-1", "LotteryAdministrator"),
    "funding_agency_auditor_headers": build_user_headers("aud-1", "FundingAgencyAuditor"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # Fallback only; ownership-gated Applicant calls need make_applicant_headers().
    "applicant_headers": build_user_headers("applicant-placeholder", "Applicant"),
}


def make_housing_developer_headers(user_id: str = "dev-1") -> dict:
    """HousingDeveloper (opaque). user_id is a free operator identifier."""
    return build_user_headers(user_id, "HousingDeveloper")


def make_marketing_coordinator_headers(user_id: str = "mc-1") -> dict:
    """MarketingCoordinator (opaque)."""
    return build_user_headers(user_id, "MarketingCoordinator")


def make_application_clerk_headers(user_id: str = "clerk-1") -> dict:
    """ApplicationClerk (opaque)."""
    return build_user_headers(user_id, "ApplicationClerk")


def make_compliance_officer_headers(user_id: str = "co-1") -> dict:
    """ComplianceOfficer (opaque). Recorded as certified_by on CERTIFY —
    keep distinct from any lottery operator id on the same campaign."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_lottery_administrator_headers(user_id: str = "lot-1") -> dict:
    """LotteryAdministrator (opaque). Recorded as sealed_by/executed_by/
    published_by — keep distinct from any certifying officer id."""
    return build_user_headers(user_id, "LotteryAdministrator")


def make_funding_agency_auditor_headers(user_id: str = "aud-1") -> dict:
    """FundingAgencyAuditor (opaque)."""
    return build_user_headers(user_id, "FundingAgencyAuditor")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """Anonymous (opaque; the only role that may register an applicant)."""
    return build_user_headers(user_id, "Anonymous")


def make_applicant_headers(applicant_id: str) -> dict:
    """Applicant (entity-backed). Pass the actual Applicant.id; the server
    compares the addressed resource's owning applicant reference against
    this X-User-ID for ownership checks (PRD §2.1)."""
    return build_user_headers(applicant_id, "Applicant")
