"""Pre-built request headers for every role the PRD defines.

Two roles are identified by a domain entity rather than by an opaque operator
id: ChannelOperator's X-User-ID is a Channel id, and Guest's X-User-ID is a
Booking id. Any ownership-gated call for those roles MUST use the matching
``make_*_headers`` builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities reused across scenarios.
USER_PLATFORM_ADMIN = "u-admin-1"
USER_REVENUE_MANAGER = "u-rev-1"
USER_REVENUE_MANAGER_2 = "u-rev-2"
USER_COMPLIANCE_OFFICER = "u-comp-1"
USER_COMPLIANCE_OFFICER_2 = "u-comp-2"
USER_REGULATORY_LIAISON = "u-liaison-1"
USER_REGULATORY_LIAISON_2 = "u-liaison-2"
USER_GUEST_SERVICES_AGENT = "u-gsa-1"
USER_GUEST_SERVICES_AGENT_2 = "u-gsa-2"

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical identity.
    "platform_admin_headers": build_user_headers(USER_PLATFORM_ADMIN, "PlatformAdmin"),
    "revenue_manager_headers": build_user_headers(USER_REVENUE_MANAGER, "RevenueManager"),
    "revenue_manager_2_headers": build_user_headers(
        USER_REVENUE_MANAGER_2, "RevenueManager"
    ),
    "compliance_officer_headers": build_user_headers(
        USER_COMPLIANCE_OFFICER, "ComplianceOfficer"
    ),
    "compliance_officer_2_headers": build_user_headers(
        USER_COMPLIANCE_OFFICER_2, "ComplianceOfficer"
    ),
    "regulatory_liaison_headers": build_user_headers(
        USER_REGULATORY_LIAISON, "RegulatoryLiaison"
    ),
    "regulatory_liaison_2_headers": build_user_headers(
        USER_REGULATORY_LIAISON_2, "RegulatoryLiaison"
    ),
    "guest_services_agent_headers": build_user_headers(
        USER_GUEST_SERVICES_AGENT, "GuestServicesAgent"
    ),
    "guest_services_agent_2_headers": build_user_headers(
        USER_GUEST_SERVICES_AGENT_2, "GuestServicesAgent"
    ),
    # Entity-identified roles: these shared constants are only safe for calls
    # that are rejected before any ownership comparison can succeed.
    "channel_operator_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000c0", "ChannelOperator"
    ),
    "guest_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000b0", "Guest"
    ),
}


def make_platform_admin_headers(user_id: str = USER_PLATFORM_ADMIN) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_revenue_manager_headers(user_id: str = USER_REVENUE_MANAGER) -> dict:
    return build_user_headers(user_id, "RevenueManager")


def make_compliance_officer_headers(user_id: str = USER_COMPLIANCE_OFFICER) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_regulatory_liaison_headers(user_id: str = USER_REGULATORY_LIAISON) -> dict:
    return build_user_headers(user_id, "RegulatoryLiaison")


def make_guest_services_agent_headers(user_id: str = USER_GUEST_SERVICES_AGENT) -> dict:
    return build_user_headers(user_id, "GuestServicesAgent")


def make_channel_operator_headers(channel_id: str) -> dict:
    """ChannelOperator headers. Pass the Channel id that owns the resource."""
    return build_user_headers(channel_id, "ChannelOperator")


def make_guest_headers(booking_id: str) -> dict:
    """Guest headers. Pass the Booking id the guest is staying under."""
    return build_user_headers(booking_id, "Guest")


ALL_ROLE_NAMES = [
    "PlatformAdmin",
    "RevenueManager",
    "ComplianceOfficer",
    "RegulatoryLiaison",
    "ChannelOperator",
    "GuestServicesAgent",
    "Guest",
]
