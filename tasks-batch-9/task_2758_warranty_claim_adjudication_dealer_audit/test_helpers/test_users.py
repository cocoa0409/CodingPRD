"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATORS

# Shared constants. Safe for the six manufacturer-side roles, whose X-User-ID is
# an opaque operator identifier that is never compared to an entity id.
TEST_USERS = {
    "warranty_admin_headers": build_user_headers(
        OPERATORS["WARRANTY_ADMIN"], "WarrantyAdmin"
    ),
    "claim_adjudicator_headers": build_user_headers(
        OPERATORS["ADJUDICATOR"], "ClaimAdjudicator"
    ),
    "claim_adjudicator_alt_headers": build_user_headers(
        OPERATORS["ADJUDICATOR_ALT"], "ClaimAdjudicator"
    ),
    "adjudication_manager_headers": build_user_headers(
        OPERATORS["MANAGER"], "AdjudicationManager"
    ),
    "field_auditor_headers": build_user_headers(
        OPERATORS["AUDITOR_LEAD"], "FieldAuditor"
    ),
    "audit_manager_headers": build_user_headers(
        OPERATORS["AUDIT_MANAGER"], "AuditManager"
    ),
    "appeal_reviewer_headers": build_user_headers(
        OPERATORS["APPEAL_REVIEWER"], "AppealReviewer"
    ),
    # DealerWarrantyAdmin is dealer-backed: this shared constant is a fallback for
    # tests that do not depend on the caller owning the subject dealership.
    "dealer_warranty_admin_headers": build_user_headers(
        "test-dealer-admin-1", "DealerWarrantyAdmin"
    ),
}


def make_dealer_warranty_admin_headers(dealer_id: str) -> dict:
    """Headers for a DealerWarrantyAdmin acting for one dealership.

    PRD §2.1: when X-User-Role is DealerWarrantyAdmin, X-User-ID is the id of the
    acting dealership's Dealer row, so every dealer-scoped call must pass the real
    Dealer id here.
    """
    return build_user_headers(dealer_id, "DealerWarrantyAdmin")


def make_operator_headers(user_id: str, role: str) -> dict:
    """Headers for a manufacturer-side operator with an explicit X-User-ID."""
    return build_user_headers(user_id, role)
