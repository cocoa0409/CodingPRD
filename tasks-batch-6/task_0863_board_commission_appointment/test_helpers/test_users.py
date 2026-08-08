"""Pre-built role headers for every role in the PRD (§2.1).

Five roles are opaque operator identifiers (BoardClerk, AppointingAuthority,
ConfirmingMember, EthicsOfficer, PublicAuditor): X-User-ID is not tied to a
persisted entity, but is recorded (e.g. nominated_by_user_id) and compared for
segregation-of-duties. Use the make_*_headers(user_id) builders to pin a
specific operator id where SoD matters.

Applicant is entity-backed: X-User-ID must equal the acting Applicant.id for
ownership checks — always use make_applicant_headers(applicant_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for tests that do NOT exercise ownership/SoD gating.
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "BoardClerk"),
    "authority_headers": build_user_headers("auth-1", "AppointingAuthority"),
    "confirming_headers": build_user_headers("cm-1", "ConfirmingMember"),
    "ethics_headers": build_user_headers("ethics-1", "EthicsOfficer"),
    "auditor_headers": build_user_headers("audit-1", "PublicAuditor"),
    # entity-backed fallback (non-ownership tests only)
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}

# Unauthenticated caller: no valid header pair (PRD §2.1 -> ERR_UNAUTHENTICATED).
ANON_HEADERS: dict = {}


# ---- opaque-role builders (pin a specific operator id, e.g. for SoD) ----
def make_clerk_headers(user_id="clerk-1") -> dict:
    return build_user_headers(user_id, "BoardClerk")


def make_authority_headers(user_id="auth-1") -> dict:
    """AppointingAuthority id is recorded as nominated_by_user_id (SoD basis)."""
    return build_user_headers(user_id, "AppointingAuthority")


def make_confirming_headers(user_id="cm-1") -> dict:
    """ConfirmingMember id is compared against nominated_by_user_id (SoD)."""
    return build_user_headers(user_id, "ConfirmingMember")


def make_ethics_headers(user_id="ethics-1") -> dict:
    return build_user_headers(user_id, "EthicsOfficer")


def make_auditor_headers(user_id="audit-1") -> dict:
    return build_user_headers(user_id, "PublicAuditor")


# ---- entity-backed builder (MUST pass the real Applicant.id) ----
def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (entity_backed:Applicant). Pass the actual Applicant.id so
    ownership checks (own application resubmit, own disclosure file) pass."""
    return build_user_headers(user_id, "Applicant")
