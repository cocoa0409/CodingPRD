"""Pre-built role headers for every role recognised by the PRD (§2.1).

`FilingAgent` and `CertifyingOfficer` are entity-backed: their `X-User-ID` must be
the `id` of a persisted `LicenseeUser`, so ownership-gated calls MUST use the
per-instance builders below with the real user id. `ComplianceOfficer` is opaque —
its identifier is never resolved against any record, so the shared constant is the
canonical form for the regulator.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Safe for the opaque regulator role, and for tests whose success
# does not depend on the caller resolving to a real LicenseeUser (for example a 401
# probe). Never use the entity-backed entries for ownership-gated calls.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "filing_agent_headers": build_user_headers("test-filing-agent-1", "FilingAgent"),
    "certifying_officer_headers": build_user_headers(
        "test-certifying-officer-1", "CertifyingOfficer"
    ),
    "compliance_officer_headers": build_user_headers(
        "regulator-001", "ComplianceOfficer"
    ),
}


def make_filing_agent_headers(user_id: str) -> Dict[str, str]:
    """Headers for a FilingAgent. Pass the acting LicenseeUser's `id`."""
    return build_user_headers(user_id, "FilingAgent")


def make_certifying_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a CertifyingOfficer. Pass the acting LicenseeUser's `id`."""
    return build_user_headers(user_id, "CertifyingOfficer")


def make_compliance_officer_headers(user_id: str = "regulator-001") -> Dict[str, str]:
    """Headers for the opaque ComplianceOfficer role."""
    return build_user_headers(user_id, "ComplianceOfficer")


def compliance_officer_headers() -> Dict[str, str]:
    """Convenience accessor for the regulator headers."""
    return TEST_USERS["compliance_officer_headers"]
