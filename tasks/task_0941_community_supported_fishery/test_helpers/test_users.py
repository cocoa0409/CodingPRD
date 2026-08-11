"""Pre-built role headers for every role named in the PRD.

Two of the five roles are entity backed: a `Member` caller sends the acting member's
own `id` as `X-User-ID`, and a `Vendor` caller sends the acting vessel's `id`. Use the
per-instance builders below for those two roles whenever the call is ownership gated.
The other three roles are opaque operator identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities. Two distinct quality officers exist so that a test can
# separate the operator who logged a cold-chain breach from the one who dispositions it.
ADMIN_USER_ID = "csf-admin-1"
HUB_OPERATOR_USER_ID = "hub-op-1"
HUB_OPERATOR_2_USER_ID = "hub-op-2"
QUALITY_OFFICER_USER_ID = "qo-1"
QUALITY_OFFICER_2_USER_ID = "qo-2"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "CsfAdmin"),
    "hub_operator_headers": build_user_headers(HUB_OPERATOR_USER_ID, "HubOperator"),
    "hub_operator_2_headers": build_user_headers(HUB_OPERATOR_2_USER_ID, "HubOperator"),
    "quality_officer_headers": build_user_headers(QUALITY_OFFICER_USER_ID, "QualityOfficer"),
    "quality_officer_2_headers": build_user_headers(QUALITY_OFFICER_2_USER_ID, "QualityOfficer"),
    # Fallback constants for the two entity-backed roles. Only safe for calls whose
    # outcome does not depend on the caller owning the addressed resource.
    "member_headers": build_user_headers("member-not-bound", "Member"),
    "vendor_headers": build_user_headers("vessel-not-bound", "Vendor"),
}


def make_member_headers(member_id: str) -> dict:
    """Headers for a Member acting on their own resources. Pass the member's own id."""
    return build_user_headers(member_id, "Member")


def make_vendor_headers(vessel_id: str) -> dict:
    """Headers for a Vendor acting on their own trips. Pass the vessel's own id."""
    return build_user_headers(vessel_id, "Vendor")


def make_hub_operator_headers(user_id: str = HUB_OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "HubOperator")


def make_quality_officer_headers(user_id: str = QUALITY_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "QualityOfficer")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "CsfAdmin")
