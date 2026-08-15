"""Pre-built role headers for every role in the Ready Mix Dispatch PRD.

Shared constants are used for the opaque roles (Dispatcher, BatchOperator, Driver,
QCTech, PlantManager) and for Customer calls whose outcome does not depend on
ownership. For ownership-gated calls (a Customer reading/cancelling/paying their
own resources), build headers with make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Customer — fallback for non-ownership tests only
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles — canonical shared form
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "batch_operator_headers": build_user_headers("test-batchop-1", "BatchOperator"),
    "driver_headers": build_user_headers("drv-1", "Driver"),
    "driver2_headers": build_user_headers("drv-2", "Driver"),
    "qc_a_headers": build_user_headers("qc-a", "QCTech"),
    "qc_b_headers": build_user_headers("qc-b", "QCTech"),
    "qc_c_headers": build_user_headers("qc-c", "QCTech"),
    "plant_manager_headers": build_user_headers("test-pm-1", "PlantManager"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed: Customer). Pass the actual Customer.id whenever
    the call is ownership-gated (order read/cancel, invoice read/dispute/pay, and
    order placement, which stamps customer_id from X-User-ID)."""
    return build_user_headers(customer_id, "Customer")


def make_driver_headers(user_id: str) -> dict:
    """Driver with a specific opaque id (drivers stamp added_by_user_id)."""
    return build_user_headers(user_id, "Driver")


def make_qc_headers(user_id: str) -> dict:
    """QCTech with a specific opaque id (load-bearing for segregation of duties)."""
    return build_user_headers(user_id, "QCTech")
