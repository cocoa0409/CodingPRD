"""Pre-built auth headers for every role the PRD declares.

Every request carries ``X-User-ID`` and ``X-User-Role``. For ``FleetManager``
the ``X-User-ID`` is the id of the acting fleet account, and for
``TireTechnician`` it is the id of the acting technician, so those two roles
must always be built per-instance with the real entity id. The remaining six
roles carry an opaque operator identifier, so a shared constant is the
canonical form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across setups. The segregation-of-duties
# checks compare one recorded operator identifier against another, so distinct
# literals matter.
INSPECTOR_ONE_ID = "inspector-1"
INSPECTOR_TWO_ID = "inspector-2"
DUAL_ROLE_OPERATOR_ID = "dual-1"
OFFICER_SIGNER_ID = "officer-signer"
OFFICER_CERTIFIER_ID = "officer-certifier"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "dealer_admin_headers": build_user_headers("dealer-admin-1", "DealerAdmin"),
    "casing_inspector_headers": build_user_headers(INSPECTOR_ONE_ID, "CasingInspector"),
    "plant_scheduler_headers": build_user_headers("scheduler-1", "PlantScheduler"),
    "compliance_officer_headers": build_user_headers(
        OFFICER_SIGNER_ID, "ComplianceOfficer"
    ),
    "billing_clerk_headers": build_user_headers("clerk-1", "BillingClerk"),
    "dispatch_coordinator_headers": build_user_headers(
        "dispatcher-1", "DispatchCoordinator"
    ),
    # Identity-bearing roles — these shared constants are a fallback for tests
    # that never exercise ownership (for example malformed-payload rejections).
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "tire_technician_headers": build_user_headers(
        "test-tire-technician-1", "TireTechnician"
    ),
}


# --- Per-instance builders ------------------------------------------------

def make_fleet_manager_headers(fleet_account_id: str) -> dict:
    """Headers for a FleetManager acting as the given fleet account.

    Ownership checks compare the resource's ``fleet_account_id`` to
    ``X-User-ID``, so this must be the real fleet account id.
    """
    return build_user_headers(fleet_account_id, "FleetManager")


def make_tire_technician_headers(technician_id: str) -> dict:
    """Headers for a TireTechnician acting as the given technician.

    Arrival and completion on a road service call require the acting
    technician to be the one named in the call's ``technician_id``, so this
    must be the real technician id.
    """
    return build_user_headers(technician_id, "TireTechnician")


def make_casing_inspector_headers(user_id: str) -> dict:
    """Headers for a CasingInspector with an explicit operator identifier.

    The identifier is retained as ``inspected_by_user_id`` on the graded
    casing and later consumed by the manifest segregation-of-duties check.
    """
    return build_user_headers(user_id, "CasingInspector")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Headers for a ComplianceOfficer with an explicit operator identifier.

    The identifier is retained as ``signed_by_user_id`` or
    ``certified_by_user_id`` on the manifest.
    """
    return build_user_headers(user_id, "ComplianceOfficer")


def make_dealer_admin_headers(user_id: str = "dealer-admin-1") -> dict:
    return build_user_headers(user_id, "DealerAdmin")


def make_plant_scheduler_headers(user_id: str = "scheduler-1") -> dict:
    return build_user_headers(user_id, "PlantScheduler")


def make_billing_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_dispatch_coordinator_headers(user_id: str = "dispatcher-1") -> dict:
    return build_user_headers(user_id, "DispatchCoordinator")


# Convenience aliases for the most frequently used opaque callers.
DEALER_ADMIN = TEST_USERS["dealer_admin_headers"]
CASING_INSPECTOR = TEST_USERS["casing_inspector_headers"]
PLANT_SCHEDULER = TEST_USERS["plant_scheduler_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]
DISPATCH_COORDINATOR = TEST_USERS["dispatch_coordinator_headers"]
