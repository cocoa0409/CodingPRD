"""Pre-built role headers for every role in the PRD (§2.1).

Staff roles (ProgramAdmin, ConservationPlanner, PaymentOfficer,
QualityAssuranceOfficer) carry opaque user identifiers — the server records
them as audit stamps but never ties them to an entity id.

The Applicant role is entity-backed: `X-User-ID` must equal the Applicant
record's `id` on ownership-gated writes. Always build applicant headers with
`make_applicant_headers(applicant["id"])` after registering the applicant.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER,
    PLANNER_USER,
    PLANNER_USER_2,
    PAYMENT_OFFICER_USER,
    QA_USER,
    QA_USER_2,
)

# Shared constants — safe for staff roles and for tests that never exercise
# applicant ownership.
TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER, "ProgramAdmin"),
    "planner_headers": build_user_headers(PLANNER_USER, "ConservationPlanner"),
    "planner2_headers": build_user_headers(PLANNER_USER_2, "ConservationPlanner"),
    "po_headers": build_user_headers(PAYMENT_OFFICER_USER, "PaymentOfficer"),
    "qa_headers": build_user_headers(QA_USER, "QualityAssuranceOfficer"),
    "qa2_headers": build_user_headers(QA_USER_2, "QualityAssuranceOfficer"),
    # Fallback only for tests that do not exercise ownership-gated calls.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_admin_headers(user_id: str = ADMIN_USER) -> dict:
    """ProgramAdmin (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_planner_headers(user_id: str = PLANNER_USER) -> dict:
    """ConservationPlanner (opaque identity)."""
    return build_user_headers(user_id, "ConservationPlanner")


def make_payment_officer_headers(user_id: str = PAYMENT_OFFICER_USER) -> dict:
    """PaymentOfficer (opaque identity)."""
    return build_user_headers(user_id, "PaymentOfficer")


def make_qa_headers(user_id: str = QA_USER) -> dict:
    """QualityAssuranceOfficer (opaque identity)."""
    return build_user_headers(user_id, "QualityAssuranceOfficer")


def make_applicant_headers(user_id: str) -> dict:
    """Applicant (entity-backed): pass the actual Applicant record's id."""
    return build_user_headers(user_id, "Applicant")
