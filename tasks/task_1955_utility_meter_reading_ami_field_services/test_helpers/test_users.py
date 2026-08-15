"""Pre-built role headers for every role in the PRD (section 2.1).

FieldTechnician is entity-backed: when a call is ownership-gated (route
start/complete, stop field operations, work-order start/complete), callers
MUST use make_field_technician_headers(entity_id) with the real technician
entity id. The shared constant is a fallback for non-ownership tests only.

Opaque roles (MeterOpsAdmin, Dispatcher, BillingLiaison, Investigator) may
use the shared constants freely; the make_* builders exist for tests that
need distinct user ids (e.g. segregation-of-duties on investigation close).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: fallback for non-ownership tests only
    "field_technician_headers": build_user_headers("test-tech-shared", "FieldTechnician"),
    # opaque roles: shared constants are canonical
    "meter_ops_admin_headers": build_user_headers("test-admin-1", "MeterOpsAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_liaison_headers": build_user_headers("test-billing-1", "BillingLiaison"),
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
}


def make_field_technician_headers(user_id: str) -> dict:
    """FieldTechnician is entity-backed: pass the real FieldTechnician.id
    whenever the call is ownership-gated (route/work-order start & complete,
    stop reads, mark-no-read, skip-hazard, hazard report stamping)."""
    return build_user_headers(user_id, "FieldTechnician")


def make_meter_ops_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MeterOpsAdmin")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_billing_liaison_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingLiaison")


def make_investigator_headers(user_id: str) -> dict:
    """Investigator is opaque, but investigation close compares X-User-ID
    against opened_by_user_id (segregation of duties) — pass distinct ids."""
    return build_user_headers(user_id, "Investigator")
