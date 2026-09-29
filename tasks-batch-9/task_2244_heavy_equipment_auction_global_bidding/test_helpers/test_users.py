"""Pre-built role headers for every role in the PRD.

Every request carries `X-User-ID` (the acting user) and `X-User-Role` (the capacity
in which that user acts).

Two roles are backed by a stored entity: a `Consignor` acts as the consignor record
whose id equals the `X-User-ID`, and a `Bidder` acts as the bidder record whose id
equals the `X-User-ID`. For those two roles, ownership-gated calls MUST use the
per-instance builder with the real entity id — the shared constants below are only
safe for calls whose success does not depend on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable identities for the five opaque roles. `inspector_user_id`,
# `qa_signed_off_by_user_id` and `credit_approved_by_user_id` are recorded from
# these values and later compared, so separate-of-duties tests need more than one
# identity per opaque role.
ADMIN_USER_ID = "platform-admin-1"
INSPECTOR_USER_ID = "inspector-1"
SECOND_INSPECTOR_USER_ID = "inspector-2"
COMPLIANCE_USER_ID = "compliance-1"
OPERATOR_USER_ID = "auction-operator-1"
SETTLEMENT_USER_ID = "credit-officer-1"
SECOND_SETTLEMENT_USER_ID = "settlement-officer-2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "intake_inspector_headers": build_user_headers(INSPECTOR_USER_ID, "IntakeInspector"),
    "second_intake_inspector_headers": build_user_headers(
        SECOND_INSPECTOR_USER_ID, "IntakeInspector"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_USER_ID, "ComplianceOfficer"
    ),
    "auction_operator_headers": build_user_headers(OPERATOR_USER_ID, "AuctionOperator"),
    "settlement_officer_headers": build_user_headers(
        SETTLEMENT_USER_ID, "SettlementOfficer"
    ),
    "second_settlement_officer_headers": build_user_headers(
        SECOND_SETTLEMENT_USER_ID, "SettlementOfficer"
    ),
    # Entity-backed roles — fallback for non-ownership tests only.
    "consignor_headers": build_user_headers("test-consignor-1", "Consignor"),
    "bidder_headers": build_user_headers("test-bidder-1", "Bidder"),
}


def make_consignor_headers(user_id: str) -> dict:
    """Headers for a Consignor. Pass the real Consignor id whenever the call is
    ownership-gated (consignment creation, lot creation, submit, counteroffer, reject)."""
    return build_user_headers(user_id, "Consignor")


def make_bidder_headers(user_id: str) -> dict:
    """Headers for a Bidder. Pass the real Bidder id whenever the call is
    ownership-gated (registration, bidding, payment, load-out booking)."""
    return build_user_headers(user_id, "Bidder")


def make_intake_inspector_headers(user_id: str) -> dict:
    """Headers for an IntakeInspector under a specific identity, so that the
    inspector recorded on a condition report can be distinguished from the
    inspector who signs off refurbishment QA."""
    return build_user_headers(user_id, "IntakeInspector")


def make_settlement_officer_headers(user_id: str) -> dict:
    """Headers for a SettlementOfficer under a specific identity."""
    return build_user_headers(user_id, "SettlementOfficer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Headers for a ComplianceOfficer under a specific identity."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_auction_operator_headers(user_id: str) -> dict:
    """Headers for an AuctionOperator under a specific identity."""
    return build_user_headers(user_id, "AuctionOperator")


def make_platform_admin_headers(user_id: str) -> dict:
    """Headers for a PlatformAdmin under a specific identity."""
    return build_user_headers(user_id, "PlatformAdmin")


def headers_without_user_id(role: str) -> dict:
    """Headers that declare a role but omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
