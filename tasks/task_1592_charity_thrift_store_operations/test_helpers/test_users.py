"""Pre-built role headers for the eight PRD roles.

Cashier, Driver and Volunteer are entity-backed by Worker (PRD 2.1): for any
ownership-gated call the X-User-ID must be the acting worker's real id, so
use the per-instance builders below. The shared constants are safe only for
opaque roles or for tests that never exercise an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical form.
    "store_manager_headers": build_user_headers("mgr-default-1", "StoreManager"),
    "intake_attendant_headers": build_user_headers("intake-default-1", "IntakeAttendant"),
    "pricer_headers": build_user_headers("pricer-default-1", "Pricer"),
    "volunteer_coordinator_headers": build_user_headers("coord-default-1", "VolunteerCoordinator"),
    "finance_clerk_headers": build_user_headers("fin-default-1", "FinanceClerk"),
    # Entity-backed roles: fallback ONLY for tests that do not touch ownership.
    "cashier_headers": build_user_headers("cashier-nonworker-1", "Cashier"),
    "driver_headers": build_user_headers("driver-nonworker-1", "Driver"),
    "volunteer_headers": build_user_headers("volunteer-nonworker-1", "Volunteer"),
}


def make_store_manager_headers(user_id):
    return build_user_headers(user_id, "StoreManager")


def make_intake_attendant_headers(user_id):
    return build_user_headers(user_id, "IntakeAttendant")


def make_pricer_headers(user_id):
    return build_user_headers(user_id, "Pricer")


def make_volunteer_coordinator_headers(user_id):
    return build_user_headers(user_id, "VolunteerCoordinator")


def make_finance_clerk_headers(user_id):
    return build_user_headers(user_id, "FinanceClerk")


def make_cashier_headers(worker_id):
    """Cashier is entity-backed: pass the acting Worker.id."""
    return build_user_headers(worker_id, "Cashier")


def make_driver_headers(worker_id):
    """Driver is entity-backed: pass the acting Worker.id."""
    return build_user_headers(worker_id, "Driver")


def make_volunteer_headers(worker_id):
    """Volunteer is entity-backed: pass the acting Worker.id."""
    return build_user_headers(worker_id, "Volunteer")
