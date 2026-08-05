"""Pre-built role headers for every role in the PRD.

Four of the five roles carry an OPAQUE identity (FleetManager, DepotOperator,
MaintenanceTech, FinanceManager): X-User-ID is an operator identifier not tied
to any persisted entity, so a shared constant is correct for them. The Driver
role is ENTITY-BACKED: X-User-ID must be the id of a real Driver record, so any
ownership-gated call by a driver MUST use make_driver_headers(driver_id).

FinanceManager identity is opaque but the segregation-of-duties rule compares
the approver's X-User-ID to the payer's, so finance tests build explicit
per-user headers via make_finance_headers(user_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "fleet_manager_headers": build_user_headers("fm-1", "FleetManager"),
    "depot_operator_headers": build_user_headers("op-1", "DepotOperator"),
    "maintenance_tech_headers": build_user_headers("mt-1", "MaintenanceTech"),
    "finance_manager_headers": build_user_headers("fin-1", "FinanceManager"),
    # entity-backed Driver fallback — for non-ownership negative tests only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def fm_headers() -> dict:
    """FleetManager (opaque)."""
    return TEST_USERS["fleet_manager_headers"]


def op_headers() -> dict:
    """DepotOperator (opaque)."""
    return TEST_USERS["depot_operator_headers"]


def mt_headers() -> dict:
    """MaintenanceTech (opaque)."""
    return TEST_USERS["maintenance_tech_headers"]


def make_finance_headers(user_id: str) -> dict:
    """FinanceManager (opaque identity, but SoD compares the specific user id)."""
    return build_user_headers(user_id, "FinanceManager")


def finance_headers() -> dict:
    """Default FinanceManager credential (user 'fin-1')."""
    return TEST_USERS["finance_manager_headers"]


def make_driver_headers(driver_id: str) -> dict:
    """Driver (entity_backed:Driver). Pass the acting Driver.id as X-User-ID."""
    return build_user_headers(driver_id, "Driver")
