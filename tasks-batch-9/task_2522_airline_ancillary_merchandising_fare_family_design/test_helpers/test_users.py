"""Role identities and their auth headers.

Five of the six roles are opaque staff identities, so a fixed user id per role is
enough.  ChannelPartner is different: its ``X-User-ID`` must be the identifier of
the DistributionChannel the partner sells for, which only exists once a channel
has been created.  That is why ChannelPartner has a builder rather than a
constant header dict.
"""

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Role names exactly as the API expects them in X-User-Role
# ---------------------------------------------------------------------------
ROLE_MERCHANDISING_ANALYST = "MerchandisingAnalyst"
ROLE_PRICING_APPROVER = "PricingApprover"
ROLE_DISTRIBUTION_MANAGER = "DistributionManager"
ROLE_OPERATIONS_CONTROLLER = "OperationsController"
ROLE_REVENUE_ACCOUNTANT = "RevenueAccountant"
ROLE_CHANNEL_PARTNER = "ChannelPartner"

ALL_ROLES = (
    ROLE_MERCHANDISING_ANALYST,
    ROLE_PRICING_APPROVER,
    ROLE_DISTRIBUTION_MANAGER,
    ROLE_OPERATIONS_CONTROLLER,
    ROLE_REVENUE_ACCOUNTANT,
    ROLE_CHANNEL_PARTNER,
)

# ---------------------------------------------------------------------------
# Opaque staff identities
# ---------------------------------------------------------------------------
MERCHANDISING_ANALYST_USER_ID = "ma-001"
SECOND_MERCHANDISING_ANALYST_USER_ID = "ma-002"
PRICING_APPROVER_USER_ID = "pa-001"
SECOND_PRICING_APPROVER_USER_ID = "pa-002"
DISTRIBUTION_MANAGER_USER_ID = "dm-001"
OPERATIONS_CONTROLLER_USER_ID = "oc-001"
REVENUE_ACCOUNTANT_USER_ID = "ra-001"

MERCHANDISING_ANALYST = build_user_headers(
    MERCHANDISING_ANALYST_USER_ID, ROLE_MERCHANDISING_ANALYST
)
SECOND_MERCHANDISING_ANALYST = build_user_headers(
    SECOND_MERCHANDISING_ANALYST_USER_ID, ROLE_MERCHANDISING_ANALYST
)
PRICING_APPROVER = build_user_headers(
    PRICING_APPROVER_USER_ID, ROLE_PRICING_APPROVER
)
SECOND_PRICING_APPROVER = build_user_headers(
    SECOND_PRICING_APPROVER_USER_ID, ROLE_PRICING_APPROVER
)
DISTRIBUTION_MANAGER = build_user_headers(
    DISTRIBUTION_MANAGER_USER_ID, ROLE_DISTRIBUTION_MANAGER
)
OPERATIONS_CONTROLLER = build_user_headers(
    OPERATIONS_CONTROLLER_USER_ID, ROLE_OPERATIONS_CONTROLLER
)
REVENUE_ACCOUNTANT = build_user_headers(
    REVENUE_ACCOUNTANT_USER_ID, ROLE_REVENUE_ACCOUNTANT
)


def make_channel_partner_headers(distribution_channel_id):
    """Headers for the partner that sells for ``distribution_channel_id``.

    The identifier is the DistributionChannel row's own id, which is what makes
    channel scoping meaningful: a partner may only reach its own bookings.
    """
    return build_user_headers(str(distribution_channel_id), ROLE_CHANNEL_PARTNER)


def make_headers(role, user_id):
    """Headers for an arbitrary role/identity pair."""
    return build_user_headers(str(user_id), role)


# Role headers keyed by role name, for the roles whose identity is opaque.
OPAQUE_ROLE_HEADERS = {
    ROLE_MERCHANDISING_ANALYST: MERCHANDISING_ANALYST,
    ROLE_PRICING_APPROVER: PRICING_APPROVER,
    ROLE_DISTRIBUTION_MANAGER: DISTRIBUTION_MANAGER,
    ROLE_OPERATIONS_CONTROLLER: OPERATIONS_CONTROLLER,
    ROLE_REVENUE_ACCOUNTANT: REVENUE_ACCOUNTANT,
}

OPAQUE_ROLE_USER_IDS = {
    ROLE_MERCHANDISING_ANALYST: MERCHANDISING_ANALYST_USER_ID,
    ROLE_PRICING_APPROVER: PRICING_APPROVER_USER_ID,
    ROLE_DISTRIBUTION_MANAGER: DISTRIBUTION_MANAGER_USER_ID,
    ROLE_OPERATIONS_CONTROLLER: OPERATIONS_CONTROLLER_USER_ID,
    ROLE_REVENUE_ACCOUNTANT: REVENUE_ACCOUNTANT_USER_ID,
}
