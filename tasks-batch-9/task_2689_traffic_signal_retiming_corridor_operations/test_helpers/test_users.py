"""Pre-built role headers for every role named in PRD §2.1."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  The five opaque roles carry an operator identifier that is
# never compared to any row's id, so these constants are the canonical form for
# them.  PublicRequester is entity-backed: the shared constant is only safe for
# tests that do not exercise ownership (e.g. 404 / 422 paths).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "SignalOpsAdmin"),
    "timing_engineer_headers": build_user_headers("timing-eng-1", "TimingEngineer"),
    "certifying_engineer_headers": build_user_headers("cert-eng-1", "CertifyingEngineer"),
    "field_technician_headers": build_user_headers("tech-1", "FieldTechnician"),
    "citizen_liaison_headers": build_user_headers("liaison-1", "CitizenLiaison"),
    "public_requester_headers": build_user_headers("requester-not-a-row", "PublicRequester"),
}


def make_admin_headers(user_id: str) -> dict:
    """SignalOpsAdmin acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "SignalOpsAdmin")


def make_timing_engineer_headers(user_id: str) -> dict:
    """TimingEngineer acting under a specific opaque operator identifier.

    Use this when the identifier matters — it is recorded as a timing plan's
    authored_by_user_id and a priority configuration's proposed_by_user_id and is
    the comparand for the segregation-of-duties rule.
    """
    return build_user_headers(user_id, "TimingEngineer")


def make_certifying_engineer_headers(user_id: str) -> dict:
    """CertifyingEngineer acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "CertifyingEngineer")


def make_field_technician_headers(user_id: str) -> dict:
    """FieldTechnician acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "FieldTechnician")


def make_citizen_liaison_headers(user_id: str) -> dict:
    """CitizenLiaison acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "CitizenLiaison")


def make_public_requester_headers(requester_id: str) -> dict:
    """PublicRequester: X-User-ID is the id of the acting Requester row.

    Ownership-gated calls MUST use this builder with the real requester id.
    """
    return build_user_headers(requester_id, "PublicRequester")


# Distinct operator identifiers used by segregation-of-duties tests.
AUTHOR_ENGINEER_ID = "timing-eng-author"
REVIEWER_ENGINEER_ID = "cert-eng-reviewer"
