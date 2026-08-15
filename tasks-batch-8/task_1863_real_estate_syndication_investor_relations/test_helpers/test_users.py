"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles (SponsorOperator,
# ComplianceOfficer, TransferAgent), whose X-User-ID is never compared to a
# persisted entity id (PRD §2.1). Two distinct compliance desks are provided so
# segregation-of-duties flows can verify with one officer and approve with a
# different one (PRD §3.3).
TEST_USERS = {
    "sponsor_operator_headers": build_user_headers("test-sponsor-1", "SponsorOperator"),
    "compliance_officer_headers": build_user_headers("test-officer-1",
                                                     "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("test-officer-2",
                                                       "ComplianceOfficer"),
    "transfer_agent_headers": build_user_headers("test-agent-1", "TransferAgent"),
    # Investor is entity-backed: this shared constant is a fallback for tests
    # that do NOT exercise ownership. Any ownership-gated call MUST use
    # make_investor_headers(investor["id"]) instead.
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
}


def make_investor_headers(user_id: str) -> dict:
    """For the Investor role (entity-backed): pass the acting Investor's id as
    user_id whenever the call is ownership-gated (PRD §2.1: X-User-ID is the id
    of the acting Investor)."""
    return build_user_headers(user_id, "Investor")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer (opaque identity): pick a distinct user_id per
    officer when segregation of duties requires two different desks."""
    return build_user_headers(user_id, "ComplianceOfficer")
