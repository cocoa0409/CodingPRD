"""Pre-built role headers for every role in the PRD.

Six of the seven roles carry an opaque identity, so a shared constant is the
canonical form for them. `PrinterRep` is entity-backed: its `X-User-ID` is the
`id` of the acting Printer row, so ownership-gated calls MUST use
`make_printer_rep_headers(printer["id"])`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. u_coord authors versions, so the four reviewer
# identities are deliberately distinct from it and from each other to satisfy
# segregation of duties.
COORDINATOR_USER_ID = "u_coord"
BRAND_REVIEWER_USER_ID = "u_brand"
LEGAL_REVIEWER_USER_ID = "u_legal"
REGULATORY_REVIEWER_USER_ID = "u_reg"
QUALITY_REVIEWER_USER_ID = "u_qa"
PLATFORM_ADMIN_USER_ID = "u_admin"

TEST_USERS = {
    "coordinator_headers": build_user_headers(
        COORDINATOR_USER_ID, "PackagingCoordinator"
    ),
    "brand_reviewer_headers": build_user_headers(
        BRAND_REVIEWER_USER_ID, "BrandReviewer"
    ),
    "legal_reviewer_headers": build_user_headers(
        LEGAL_REVIEWER_USER_ID, "LegalReviewer"
    ),
    "regulatory_reviewer_headers": build_user_headers(
        REGULATORY_REVIEWER_USER_ID, "RegulatoryReviewer"
    ),
    "quality_reviewer_headers": build_user_headers(
        QUALITY_REVIEWER_USER_ID, "QualityReviewer"
    ),
    # PrinterRep is entity_backed:Printer — this shared constant is only safe
    # for tests that do not exercise ownership (missing-header, 404, 400 cases).
    "printer_rep_headers": build_user_headers("u_printer_rep", "PrinterRep"),
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, "PlatformAdmin"
    ),
}

ROLE_HEADER_KEYS = {
    "PackagingCoordinator": "coordinator_headers",
    "BrandReviewer": "brand_reviewer_headers",
    "LegalReviewer": "legal_reviewer_headers",
    "RegulatoryReviewer": "regulatory_reviewer_headers",
    "QualityReviewer": "quality_reviewer_headers",
    "PrinterRep": "printer_rep_headers",
    "PlatformAdmin": "platform_admin_headers",
}

ALL_ROLES = [
    "PackagingCoordinator",
    "BrandReviewer",
    "LegalReviewer",
    "RegulatoryReviewer",
    "QualityReviewer",
    "PrinterRep",
    "PlatformAdmin",
]


def make_printer_rep_headers(printer_id: str) -> dict:
    """Headers for a PrinterRep acting as the Printer row whose id is given.

    `PrinterRep` is the one entity-backed role: ownership checks compare a
    resource's `printer_id` against the caller's `X-User-ID`, so this must be
    called with the real Printer id for any ownership-gated request.
    """
    return build_user_headers(printer_id, "PrinterRep")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary user/role pair — used by segregation-of-duties tests."""
    return build_user_headers(user_id, role)


def headers_for_discipline(discipline: str) -> dict:
    """The reviewer headers bound to a review task's discipline."""
    mapping = {
        "BRAND": "brand_reviewer_headers",
        "LEGAL": "legal_reviewer_headers",
        "REGULATORY": "regulatory_reviewer_headers",
        "QUALITY": "quality_reviewer_headers",
    }
    return TEST_USERS[mapping[discipline]]
