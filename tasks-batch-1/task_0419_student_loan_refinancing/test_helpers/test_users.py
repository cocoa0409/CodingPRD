"""Pre-built role headers for every role in the PRD (Section 2.1).

Borrower and Cosigner are entity-backed: their X-User-ID must equal the acting
entity's own id whenever the call is ownership-gated. Use the make_*_headers
builders with the real entity id for those cases. The four operator roles
(Underwriter, DisbursementOfficer, ServicingAgent, PlatformAdmin) are opaque,
so a shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# borrower/cosigner ownership (e.g., 400-on-bad-payload, 404-on-missing-resource,
# 403-forbidden-role).
TEST_USERS = {
    # entity-backed: shared constant is a non-ownership fallback only.
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "cosigner_headers": build_user_headers("test-cosigner-1", "Cosigner"),
    # opaque operator roles: shared constant is canonical.
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "disbursement_officer_headers": build_user_headers("test-do-1", "DisbursementOfficer"),
    "servicing_agent_headers": build_user_headers("test-sa-1", "ServicingAgent"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# Per-instance builders — required for entity-backed roles.
def make_borrower_headers(user_id: str) -> dict:
    """For Borrower (entity_backed:Borrower). Pass the actual Borrower.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Borrower")


def make_cosigner_headers(user_id: str) -> dict:
    """For Cosigner (entity_backed:Cosigner). Pass the actual Cosigner.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Cosigner")


# Opaque-role builders (useful when a test needs a specific operator id, e.g.
# the segregation-of-duties pairing where the officer id must equal the
# approving underwriter id).
def make_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_disbursement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DisbursementOfficer")


def make_servicing_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServicingAgent")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
