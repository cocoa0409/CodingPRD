"""Pre-built role headers for every role in the PRD.

SponsorSignatory is entity-backed: its X-User-ID must equal the owning
Sponsor's id, so any ownership-gated call must use
make_sponsor_signatory_headers(sponsor_id). The shared constant is only a
fallback for tests that never exercise ownership (e.g., forbidden-role
checks). The other four roles are opaque operator identifiers; their shared
constants are canonical, and per-instance builders exist so segregation-of-
duties tests can pin a specific X-User-ID per call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Sponsor — fallback for non-ownership tests only.
    "sponsor_signatory_headers": build_user_headers("test-signatory-1", "SponsorSignatory"),
    # opaque roles — shared constants are the canonical form.
    "badging_officer_headers": build_user_headers("off-1", "BadgingOfficer"),
    "security_manager_headers": build_user_headers("mgr-1", "SecurityManager"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    "access_control_headers": build_user_headers("acs-1", "AccessControlSystem"),
}


def make_sponsor_signatory_headers(user_id: str) -> dict:
    """For SponsorSignatory (entity-backed by Sponsor). Pass the actual
    Sponsor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "SponsorSignatory")


def make_badging_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BadgingOfficer")


def make_security_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SecurityManager")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_access_control_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccessControlSystem")
