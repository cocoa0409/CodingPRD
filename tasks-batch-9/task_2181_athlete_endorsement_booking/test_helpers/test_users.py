"""Pre-built caller headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. The PRD says these are never compared to any
# entity id, so a shared constant is the canonical form for them.
TALENT_AGENT_ID = "ta-desk-1"
SCREENING_OFFICER_ID = "co-screen-1"
SECOND_SCREENING_OFFICER_ID = "co-screen-2"
REVIEWING_OFFICER_ID = "co-review-9"
ENFORCEMENT_OFFICER_ID = "co-enforce-1"
FINANCE_MANAGER_ID = "fm-1"

TEST_USERS = {
    "talent_agent_headers": build_user_headers(TALENT_AGENT_ID, "TalentAgent"),
    "compliance_officer_headers": build_user_headers(SCREENING_OFFICER_ID, "ComplianceOfficer"),
    "reviewing_officer_headers": build_user_headers(REVIEWING_OFFICER_ID, "ComplianceOfficer"),
    "enforcement_officer_headers": build_user_headers(ENFORCEMENT_OFFICER_ID, "ComplianceOfficer"),
    "finance_manager_headers": build_user_headers(FINANCE_MANAGER_ID, "FinanceManager"),
    # Entity-backed roles: these shared constants are only safe for calls that
    # never run an ownership comparison (bad payloads, unknown ids, role checks).
    "brand_rep_headers": build_user_headers("test-brand-rep-1", "BrandRep"),
    "athlete_headers": build_user_headers("test-athlete-1", "Athlete"),
    # A request that carries no caller identity at all.
    "no_auth_headers": {"Content-Type": "application/json"},
}


def make_talent_agent_headers(user_id: str = TALENT_AGENT_ID) -> dict:
    """TalentAgent is an opaque operator identity."""
    return build_user_headers(user_id, "TalentAgent")


def make_compliance_officer_headers(user_id: str = SCREENING_OFFICER_ID) -> dict:
    """ComplianceOfficer is an opaque operator identity, but the id is recorded
    on the opportunity it screens and on the disclosure it rules."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_finance_manager_headers(user_id: str = FINANCE_MANAGER_ID) -> dict:
    """FinanceManager is an opaque operator identity."""
    return build_user_headers(user_id, "FinanceManager")


def make_brand_rep_headers(brand_id: str) -> dict:
    """BrandRep acts as the Brand it registered: pass the actual Brand id
    whenever the call is ownership-gated."""
    return build_user_headers(brand_id, "BrandRep")


def make_athlete_headers(athlete_id: str) -> dict:
    """Athlete acts as the Athlete the agent rostered: pass the actual Athlete
    id whenever the call is ownership-gated."""
    return build_user_headers(athlete_id, "Athlete")
