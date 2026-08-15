"""Pre-built role headers for every role named in PRD 2.1.

`Applicant`, `StaffReviewer` and `DecisionAuthority` are entity-backed roles:
their `X-User-ID` must equal the id of the acting registry row whenever the
call is ownership- or authorship-gated (submit/withdraw/payments for an
Applicant, verify/waive for a StaffReviewer, decisions for a
DecisionAuthority).  Use the per-instance builders below for those calls.
`PlatformAdmin` is opaque — the server never compares it to any entity id —
so the shared constant is its canonical form.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identity — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    # Entity-backed identities — fallbacks for non-ownership tests only
    # (e.g. 400-on-bad-payload or 404 probes where the id is never compared).
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "staff_reviewer_headers": build_user_headers("test-reviewer-1", "StaffReviewer"),
    "decision_authority_headers": build_user_headers(
        "test-authority-1", "DecisionAuthority"
    ),
}


def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """For Applicant (entity-backed).  Pass the acting Applicant row's id
    whenever the call is ownership-gated."""
    return build_user_headers(applicant_id, "Applicant")


def make_staff_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """For StaffReviewer (entity-backed).  Pass the acting StaffReviewer row's
    id whenever the call is authorship-gated (verify/waive own comments)."""
    return build_user_headers(reviewer_id, "StaffReviewer")


def make_decision_authority_headers(authority_id: str) -> Dict[str, str]:
    """For DecisionAuthority (entity-backed).  Pass the acting
    DecisionAuthority row's id whenever the call references the authority."""
    return build_user_headers(authority_id, "DecisionAuthority")


def make_platform_admin_headers(user_id: str = "admin-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")
