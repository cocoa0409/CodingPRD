"""Pre-built role headers for every role in the PRD.

The Applicant role is entity-backed: its ``X-User-ID`` is the acting
Applicant's ``id`` and ownership checks compare it to the resource's
``applicant_id``. Ownership-gated calls MUST therefore use
``make_applicant_headers(applicant["id"])`` rather than the shared constant.
The other five roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "applicant_headers": build_user_headers("applicant-shared", "Applicant"),
    # opaque roles: shared constant is the canonical form.
    "row_reviewer_headers": build_user_headers("rowrev-1", "ROWReviewer"),
    "aesthetic_reviewer_headers": build_user_headers("aesrev-1", "AestheticReviewer"),
    "approver_headers": build_user_headers("approver-1", "Approver"),
    "inspector_headers": build_user_headers("insp-1", "Inspector"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_applicant_headers(user_id: str) -> dict:
    """Headers for the Applicant (entity_backed:Applicant). Pass the acting
    Applicant's ``id`` whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Applicant")


def make_row_reviewer_headers(user_id: str = "rowrev-1") -> dict:
    return build_user_headers(user_id, "ROWReviewer")


def make_aesthetic_reviewer_headers(user_id: str = "aesrev-1") -> dict:
    return build_user_headers(user_id, "AestheticReviewer")


def make_approver_headers(user_id: str = "approver-1") -> dict:
    return build_user_headers(user_id, "Approver")


def make_inspector_headers(user_id: str = "insp-1") -> dict:
    return build_user_headers(user_id, "Inspector")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
