"""Pre-built role headers for the eight roles the PRD recognizes.

`PlatformAdmin`, `Trustee`, `TitleOfficer`, `ComplianceOfficer`, `AuctionOps` and
`Anonymous` carry opaque identity, so a shared constant is the canonical form for
them. Two distinct `AuctionOps` identities are provided because the
segregation-of-duties rule compares the operator who closed a lot against the
operator who executes that lot's contract.

`Seller` and `Bidder` are entity-backed: `X-User-ID` is the `id` of the acting
`Seller` or `Bidder` row. Any ownership-gated call MUST use the per-instance
builders below with the real entity id — the shared constants would be refused
with `ERR_NOT_RESOURCE_OWNER`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPS_CLOSER, OPS_CONTRACT
from .types import UserRole

PLATFORM_ADMIN_USER = "platform-admin-1"
TRUSTEE_USER = "trustee-1"
TITLE_OFFICER_USER = "title-officer-1"
COMPLIANCE_OFFICER_USER = "compliance-officer-1"
AUCTION_OPS_USER = "ops-general-0"
ANONYMOUS_USER = "anonymous-visitor-1"

TEST_USERS = {
    # Opaque identities — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER, UserRole.PLATFORM_ADMIN.value
    ),
    "trustee_headers": build_user_headers(TRUSTEE_USER, UserRole.TRUSTEE.value),
    "title_officer_headers": build_user_headers(
        TITLE_OFFICER_USER, UserRole.TITLE_OFFICER.value
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER, UserRole.COMPLIANCE_OFFICER.value
    ),
    "auction_ops_headers": build_user_headers(AUCTION_OPS_USER, UserRole.AUCTION_OPS.value),
    "auction_ops_closer_headers": build_user_headers(OPS_CLOSER, UserRole.AUCTION_OPS.value),
    "auction_ops_contract_headers": build_user_headers(
        OPS_CONTRACT, UserRole.AUCTION_OPS.value
    ),
    "anonymous_headers": build_user_headers(ANONYMOUS_USER, UserRole.ANONYMOUS.value),
    # Entity-backed roles: these shared constants are only safe on calls that do
    # not perform an ownership comparison (role-rejection probes, 404 probes,
    # public catalogue reads).
    "seller_headers": build_user_headers("unbound-seller-1", UserRole.SELLER.value),
    "bidder_headers": build_user_headers("unbound-bidder-1", UserRole.BIDDER.value),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """For `PlatformAdmin` (opaque identity)."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_trustee_headers(user_id: str) -> dict:
    """For `Trustee` (opaque identity)."""
    return build_user_headers(user_id, UserRole.TRUSTEE.value)


def make_title_officer_headers(user_id: str) -> dict:
    """For `TitleOfficer` (opaque identity)."""
    return build_user_headers(user_id, UserRole.TITLE_OFFICER.value)


def make_compliance_officer_headers(user_id: str) -> dict:
    """For `ComplianceOfficer` (opaque identity)."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_auction_ops_headers(user_id: str) -> dict:
    """For `AuctionOps`. The identity is opaque, but it is recorded in
    `closed_by_user_id` and `executed_by_user_id`, so tests that exercise the
    four-eyes rule must pass distinct ids."""
    return build_user_headers(user_id, UserRole.AUCTION_OPS.value)


def make_anonymous_headers(user_id: str = ANONYMOUS_USER) -> dict:
    """For `Anonymous` (opaque identity)."""
    return build_user_headers(user_id, UserRole.ANONYMOUS.value)


def make_seller_headers(seller_id: str) -> dict:
    """For `Seller`. Pass the seller row's `id`: ownership checks compare
    `X-User-ID` against the `seller_id` of the listing being acted on and against
    the `seller_id` supplied on asset intake."""
    return build_user_headers(seller_id, UserRole.SELLER.value)


def make_bidder_headers(bidder_id: str) -> dict:
    """For `Bidder`. Pass the bidder row's `id`: funding, bidding, responding to
    an offer and reading an eligibility assessment all compare `X-User-ID`
    against that id."""
    return build_user_headers(bidder_id, UserRole.BIDDER.value)
