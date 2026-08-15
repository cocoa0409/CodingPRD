"""Pre-built role headers for every role in the PRD (§2.1).

ComplianceOfficer / FilingCoordinator / FilingAgent / EquityPlanAdmin use opaque
X-User-ID values. ReportingInsider is entity-backed: X-User-ID must equal the
acting ReportingPerson's id, so ownership-gated flows MUST use
make_reporting_insider_headers(person_id) with the real person id.
"""
from prd_bench_local_runner.testing import build_user_headers
from .constants import TEST_DEFAULTS

TEST_USERS = {
    "compliance_officer_headers": build_user_headers(
        TEST_DEFAULTS["COMPLIANCE_OFFICER_ID"], "ComplianceOfficer"),
    "filing_coordinator_headers": build_user_headers(
        TEST_DEFAULTS["FILING_COORDINATOR_ID"], "FilingCoordinator"),
    "filing_agent_headers": build_user_headers(
        TEST_DEFAULTS["FILING_AGENT_ID"], "FilingAgent"),
    "equity_plan_admin_headers": build_user_headers(
        TEST_DEFAULTS["EQUITY_PLAN_ADMIN_ID"], "EquityPlanAdmin"),
    # Fallback only for non-ownership tests; the id never equals a real person id.
    "reporting_insider_headers": build_user_headers(
        "insider_1", "ReportingInsider"),
}


def make_compliance_officer_headers(user_id: str = TEST_DEFAULTS["COMPLIANCE_OFFICER_ID"]) -> dict:
    """ComplianceOfficer headers (opaque identity)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_filing_coordinator_headers(user_id: str = TEST_DEFAULTS["FILING_COORDINATOR_ID"]) -> dict:
    """FilingCoordinator headers (opaque identity; recorded as prepared_by_user_id
    on manually created filings)."""
    return build_user_headers(user_id, "FilingCoordinator")


def make_filing_agent_headers(user_id: str = TEST_DEFAULTS["FILING_AGENT_ID"]) -> dict:
    """FilingAgent headers (opaque identity; must match an ACTIVE authorization's
    agent_user_id for submit / record-edgar-result)."""
    return build_user_headers(user_id, "FilingAgent")


def make_equity_plan_admin_headers(user_id: str = TEST_DEFAULTS["EQUITY_PLAN_ADMIN_ID"]) -> dict:
    """EquityPlanAdmin headers (opaque identity; recorded as ingested_by_user_id
    on ingested transactions — drives the confirmer segregation-of-duties check)."""
    return build_user_headers(user_id, "EquityPlanAdmin")


def make_reporting_insider_headers(user_id: str) -> dict:
    """ReportingInsider headers (entity-backed identity). Pass the actual
    ReportingPerson.id as user_id whenever the call is ownership-gated
    (plan creation, SUBMIT_ADOPTION, insider TERMINATE)."""
    return build_user_headers(user_id, "ReportingInsider")
