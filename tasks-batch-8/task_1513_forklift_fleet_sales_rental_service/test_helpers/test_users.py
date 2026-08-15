"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, unauthenticated).
TEST_USERS = {
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "rental_coordinator_headers": build_user_headers("test-rental-coord-1", "RentalCoordinator"),
    "service_dispatcher_headers": build_user_headers("test-dispatcher-1", "ServiceDispatcher"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "training_registrar_headers": build_user_headers("test-registrar-1", "TrainingRegistrar"),
    "lease_manager_headers": build_user_headers("test-lease-manager-1", "LeaseManager"),
}


def make_technician_headers(technician_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    as technician_id whenever the call is ownership-gated (service-call resolve)."""
    return build_user_headers(technician_id, "Technician")


def make_fleet_manager_headers(user_id: str = "test-fleet-manager-1") -> dict:
    return build_user_headers(user_id, "FleetManager")


def make_sales_rep_headers(user_id: str = "test-sales-rep-1") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_rental_coordinator_headers(user_id: str = "test-rental-coord-1") -> dict:
    return build_user_headers(user_id, "RentalCoordinator")


def make_service_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "ServiceDispatcher")


def make_training_registrar_headers(user_id: str = "test-registrar-1") -> dict:
    return build_user_headers(user_id, "TrainingRegistrar")


def make_lease_manager_headers(user_id: str = "test-lease-manager-1") -> dict:
    return build_user_headers(user_id, "LeaseManager")
