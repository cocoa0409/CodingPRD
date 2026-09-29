"""Header builders for the seven roles.

Four of the roles (`FirmManagingPartner`, `EngagementPartner`,
`QualityControlDirector`, `EngagementQualityReviewer`) are backed by a Partner
record and one (`PeerReviewer`) by a PeerReviewer record: for those roles the
``X-User-ID`` must be the id of the backing record, so tests must always build
their headers from the created entity via the ``make_*_headers`` helpers.
``SystemAdmin`` and ``PeerReviewCommittee`` are not entity-backed and may use
the fixed identifiers below.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque identities for the two roles that are not backed by a stored entity.
SYSTEM_ADMIN_ID = "11111111-1111-1111-1111-111111111111"
PEER_REVIEW_COMMITTEE_ID = "22222222-2222-2222-2222-222222222222"

# Placeholder identifiers for entity-backed roles.  These are only valid for
# calls that do not resolve the caller to a stored record; anything ownership
# or firm scoped must use the make_* builders with a real entity id.
UNKNOWN_PARTNER_ID = "33333333-3333-3333-3333-333333333333"
UNKNOWN_REVIEWER_ID = "44444444-4444-4444-4444-444444444444"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_admin": build_user_headers(SYSTEM_ADMIN_ID, UserRole.SYSTEM_ADMIN.value),
    "peer_review_committee": build_user_headers(
        PEER_REVIEW_COMMITTEE_ID, UserRole.PEER_REVIEW_COMMITTEE.value
    ),
    "firm_managing_partner": build_user_headers(
        UNKNOWN_PARTNER_ID, UserRole.FIRM_MANAGING_PARTNER.value
    ),
    "engagement_partner": build_user_headers(
        UNKNOWN_PARTNER_ID, UserRole.ENGAGEMENT_PARTNER.value
    ),
    "quality_control_director": build_user_headers(
        UNKNOWN_PARTNER_ID, UserRole.QUALITY_CONTROL_DIRECTOR.value
    ),
    "engagement_quality_reviewer": build_user_headers(
        UNKNOWN_PARTNER_ID, UserRole.ENGAGEMENT_QUALITY_REVIEWER.value
    ),
    "peer_reviewer": build_user_headers(
        UNKNOWN_REVIEWER_ID, UserRole.PEER_REVIEWER.value
    ),
}

ADMIN = TEST_USERS["system_admin"]
COMMITTEE = TEST_USERS["peer_review_committee"]


def make_system_admin_headers() -> Dict[str, str]:
    return build_user_headers(SYSTEM_ADMIN_ID, UserRole.SYSTEM_ADMIN.value)


def make_committee_headers() -> Dict[str, str]:
    return build_user_headers(
        PEER_REVIEW_COMMITTEE_ID, UserRole.PEER_REVIEW_COMMITTEE.value
    )


def make_managing_partner_headers(partner_id: str) -> Dict[str, str]:
    return build_user_headers(partner_id, UserRole.FIRM_MANAGING_PARTNER.value)


def make_engagement_partner_headers(partner_id: str) -> Dict[str, str]:
    return build_user_headers(partner_id, UserRole.ENGAGEMENT_PARTNER.value)


def make_qc_director_headers(partner_id: str) -> Dict[str, str]:
    return build_user_headers(partner_id, UserRole.QUALITY_CONTROL_DIRECTOR.value)


def make_eq_reviewer_headers(partner_id: str) -> Dict[str, str]:
    return build_user_headers(partner_id, UserRole.ENGAGEMENT_QUALITY_REVIEWER.value)


def make_peer_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    return build_user_headers(reviewer_id, UserRole.PEER_REVIEWER.value)


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
