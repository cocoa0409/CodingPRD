"""Pre-built role headers for every role in the PRD (PRD 2.1).

FirmAdmin and ComplianceOfficer carry opaque operator ids, so shared
constants are canonical for them. ClientUser, Appraiser and QCReviewer are
entity-backed: whenever a call is ownership-gated, build headers with the
actual entity id via the make_*_headers builders below — the shared
constants exist only for tests that never exercise ownership (schema-400s,
role denials on bogus ids, etc.).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "firm_admin_headers": build_user_headers("test-firm-admin-1", "FirmAdmin"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "client_user_headers": build_user_headers("test-client-user-1", "ClientUser"),
    "appraiser_headers": build_user_headers("test-appraiser-1", "Appraiser"),
    "qc_reviewer_headers": build_user_headers("test-qc-reviewer-1", "QCReviewer"),
}


def make_clientuser_headers(client_id: str) -> dict:
    """ClientUser identity is the Client id; pass the real client id whenever
    the call is ownership-gated (order create / cancel, revision create)."""
    return build_user_headers(client_id, "ClientUser")


def make_appraiser_headers(appraiser_id: str) -> dict:
    """Appraiser identity is the Appraiser id; pass the real id whenever the
    call checks the assignee / signer (start-analysis, comps, report writes)."""
    return build_user_headers(appraiser_id, "Appraiser")


def make_qc_reviewer_headers(appraiser_id: str) -> dict:
    """QCReviewer identity is an Appraiser id resolved at review time; pass the
    reviewing appraiser's real id so the reviewer record resolves."""
    return build_user_headers(appraiser_id, "QCReviewer")


def make_role_only_headers(role: str) -> dict:
    """Headers with X-User-Role but no X-User-ID (authentication probes)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
