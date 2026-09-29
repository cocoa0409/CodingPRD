"""Acting identities and header builders for every role in the PRD.

Every request carries both ``X-User-ID`` and ``X-User-Role``. The seven
platform-side roles use opaque user identifiers. ``CarrierRepresentative`` is
entity-backed: its ``X-User-ID`` must be the ``Carrier.id`` it speaks for, so it
has no fixed constant and must be built per carrier with
``make_carrier_representative_headers``.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- Role names ---------------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_INTERCONNECTION_MANAGER = "InterconnectionManager"
ROLE_NETWORK_PLANNER = "NetworkPlanner"
ROLE_ACCESS_BILLING_ANALYST = "AccessBillingAnalyst"
ROLE_DISPUTE_RESOLUTION_OFFICER = "DisputeResolutionOfficer"
ROLE_REGULATORY_AFFAIRS_SPECIALIST = "RegulatoryAffairsSpecialist"
ROLE_REVENUE_ASSURANCE_CONTROLLER = "RevenueAssuranceController"
ROLE_CARRIER_REPRESENTATIVE = "CarrierRepresentative"

# --- Opaque acting identities -------------------------------------------------
USER_PLATFORM_ADMIN = "u-admin-01"
USER_INTERCONNECTION_MANAGER = "u-icmanager-02"
USER_NETWORK_PLANNER = "u-netplan-03"
USER_ACCESS_BILLING_ANALYST = "u-billing-01"
USER_ACCESS_BILLING_ANALYST_ALT = "u-billing-02"
USER_DISPUTE_RESOLUTION_OFFICER = "u-dispute-07"
USER_REGULATORY_AFFAIRS_SPECIALIST = "u-regaffairs-05"
USER_REVENUE_ASSURANCE_CONTROLLER = "u-revassure-04"

TEST_USERS = {
    ROLE_PLATFORM_ADMIN: USER_PLATFORM_ADMIN,
    ROLE_INTERCONNECTION_MANAGER: USER_INTERCONNECTION_MANAGER,
    ROLE_NETWORK_PLANNER: USER_NETWORK_PLANNER,
    ROLE_ACCESS_BILLING_ANALYST: USER_ACCESS_BILLING_ANALYST,
    ROLE_DISPUTE_RESOLUTION_OFFICER: USER_DISPUTE_RESOLUTION_OFFICER,
    ROLE_REGULATORY_AFFAIRS_SPECIALIST: USER_REGULATORY_AFFAIRS_SPECIALIST,
    ROLE_REVENUE_ASSURANCE_CONTROLLER: USER_REVENUE_ASSURANCE_CONTROLLER,
}


def platform_admin_headers():
    """Headers for the PlatformAdmin role."""
    return build_user_headers(USER_PLATFORM_ADMIN, ROLE_PLATFORM_ADMIN)


def interconnection_manager_headers():
    """Headers for the InterconnectionManager role (the CLEC side of a negotiation)."""
    return build_user_headers(USER_INTERCONNECTION_MANAGER, ROLE_INTERCONNECTION_MANAGER)


def network_planner_headers():
    """Headers for the NetworkPlanner role."""
    return build_user_headers(USER_NETWORK_PLANNER, ROLE_NETWORK_PLANNER)


def access_billing_analyst_headers(user_id=USER_ACCESS_BILLING_ANALYST):
    """Headers for the AccessBillingAnalyst role; the acting id is the invoice issuer."""
    return build_user_headers(user_id, ROLE_ACCESS_BILLING_ANALYST)


def dispute_resolution_officer_headers(user_id=USER_DISPUTE_RESOLUTION_OFFICER):
    """Headers for the DisputeResolutionOfficer role."""
    return build_user_headers(user_id, ROLE_DISPUTE_RESOLUTION_OFFICER)


def regulatory_affairs_specialist_headers():
    """Headers for the RegulatoryAffairsSpecialist role."""
    return build_user_headers(
        USER_REGULATORY_AFFAIRS_SPECIALIST, ROLE_REGULATORY_AFFAIRS_SPECIALIST
    )


def revenue_assurance_controller_headers(user_id=USER_REVENUE_ASSURANCE_CONTROLLER):
    """Headers for the RevenueAssuranceController role."""
    return build_user_headers(user_id, ROLE_REVENUE_ASSURANCE_CONTROLLER)


def make_carrier_representative_headers(carrier_id):
    """Headers for the CarrierRepresentative speaking for ``carrier_id``.

    The role is entity-backed, so the acting user id IS the carrier id; any other
    value is a different carrier and is refused as a carrier scope violation.
    """
    return build_user_headers(carrier_id, ROLE_CARRIER_REPRESENTATIVE)


def headers_without_role(user_id=USER_PLATFORM_ADMIN):
    """A request that supplies only ``X-User-ID``."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user(role=ROLE_PLATFORM_ADMIN):
    """A request that supplies only ``X-User-Role``."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
