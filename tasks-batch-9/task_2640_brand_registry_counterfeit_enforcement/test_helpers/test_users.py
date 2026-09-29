"""Canonical request identities for every role in the role model.

Five of the six roles are opaque: their `X-User-ID` is never compared against
any stored row, so a fixed syntactically valid value suffices. The sixth,
`AuthorizedRepresentative`, is entity-backed — its `X-User-ID` must be the id
of an existing authorized-representative designation row, so callers build its
headers per designation with ``make_authorized_representative_headers``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AUTHORIZED_REPRESENTATIVE,
    ROLE_BRAND_ADMINISTRATOR,
    ROLE_CUSTOMS_COORDINATOR,
    ROLE_ENFORCEMENT_ANALYST,
    ROLE_LEGAL_COUNSEL,
    ROLE_MARKETPLACE_LIAISON,
)

BRAND_ADMINISTRATOR_USER_ID = "aaaaaaaa-0000-4000-8000-000000000001"
ENFORCEMENT_ANALYST_USER_ID = "aaaaaaaa-0000-4000-8000-000000000002"
MARKETPLACE_LIAISON_USER_ID = "aaaaaaaa-0000-4000-8000-000000000003"
CUSTOMS_COORDINATOR_USER_ID = "aaaaaaaa-0000-4000-8000-000000000004"
LEGAL_COUNSEL_USER_ID = "aaaaaaaa-0000-4000-8000-000000000005"

# A syntactically valid identifier that names no designation row at all.
UNKNOWN_REPRESENTATIVE_USER_ID = "11111111-1111-4111-8111-111111111111"


def make_authorized_representative_headers(representative_id: str) -> Dict[str, str]:
    """Headers acting as the designation row `representative_id`."""
    return build_user_headers(representative_id, ROLE_AUTHORIZED_REPRESENTATIVE)


TEST_USERS = {
    "brand_administrator_headers": build_user_headers(
        BRAND_ADMINISTRATOR_USER_ID, ROLE_BRAND_ADMINISTRATOR),
    "enforcement_analyst_headers": build_user_headers(
        ENFORCEMENT_ANALYST_USER_ID, ROLE_ENFORCEMENT_ANALYST),
    "marketplace_liaison_headers": build_user_headers(
        MARKETPLACE_LIAISON_USER_ID, ROLE_MARKETPLACE_LIAISON),
    "customs_coordinator_headers": build_user_headers(
        CUSTOMS_COORDINATOR_USER_ID, ROLE_CUSTOMS_COORDINATOR),
    "legal_counsel_headers": build_user_headers(
        LEGAL_COUNSEL_USER_ID, ROLE_LEGAL_COUNSEL),
    # Placeholder identity for the entity-backed role: only useful for
    # asserting the unknown-designation rejection. Ownership-gated calls must
    # use make_authorized_representative_headers(<designation id>) instead.
    "authorized_representative_headers": make_authorized_representative_headers(
        UNKNOWN_REPRESENTATIVE_USER_ID),
}

# Headers with no role at all, for the pre-everything authentication check.
UNAUTHENTICATED_HEADERS = {"Content-Type": "application/json"}
