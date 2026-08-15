"""Pre-built role headers for every role in the PRD (section 2.1).

Identity semantics (PRD section 2.1): the Contributor role is entity-backed —
`X-User-ID` must be the acting Contributor's `id` and is compared against
resource foreign keys. DeskAdmin, Editor, FinanceUser and VerificationEditor
are opaque operator identifiers. Segregation-of-duties checks compare
`X-User-ID` pairwise, so distinct operator ids are provided per duty.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "desk_admin_headers": build_user_headers("admin-1", "DeskAdmin"),
    "editor_headers": build_user_headers("editor-1", "Editor"),
    "finance_headers": build_user_headers("fin-1", "FinanceUser"),
    "finance_2_headers": build_user_headers("fin-2", "FinanceUser"),
    "verification_editor_headers": build_user_headers("ve-1",
                                                      "VerificationEditor"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only. Ownership-gated calls MUST use make_contributor_headers(id).
    "contributor_headers": build_user_headers("test-contributor-1",
                                              "Contributor"),
}


def make_contributor_headers(user_id: str) -> dict:
    """For Contributor (entity_backed). Pass the actual Contributor.id as
    user_id whenever the call is ownership-gated (accept/start/submit,
    invoice creation, expense claims, tax documents)."""
    return build_user_headers(user_id, "Contributor")


def make_finance_headers(user_id: str) -> dict:
    """For FinanceUser (opaque). Pin a specific X-User-ID where
    segregation-of-duties pairs are exercised."""
    return build_user_headers(user_id, "FinanceUser")


def make_verification_editor_headers(user_id: str) -> dict:
    """For VerificationEditor (opaque). Pin a specific X-User-ID where the
    recorder/adjudicator separation is exercised."""
    return build_user_headers(user_id, "VerificationEditor")


def make_editor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Editor")


def make_desk_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DeskAdmin")
