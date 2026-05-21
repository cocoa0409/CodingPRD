"""Pre-built role headers for every role declared in PRD §2.1.

PRD §2.1 identity rules (paraphrased):
  - Customer: entity-backed. X-User-ID is the id of the acting Customer;
    ownership checks compare Parcel.customer_id (and Address.customer_id)
    to X-User-ID. A Customer reading or filing an appointment for a
    parcel they do not own is rejected with ERR_FORBIDDEN.
  - Driver: entity-backed. X-User-ID is the id of the acting Driver;
    ownership checks compare Route.driver_id and DeliveryAttempt.driver_id
    to X-User-ID. Drivers may only act on their own records / routes.
  - Dispatcher / SortingHubOperator / ComplianceOfficer: opaque
    operator identifiers not tied to any persisted entity; the server
    may record them for audit but does not compare them to any entity id.

Two things are emitted per role:

  (1) A shared-constant entry in TEST_USERS — safe for opaque roles
      (Dispatcher, SortingHubOperator, ComplianceOfficer) and for the
      tests that don't exercise ownership (auth probes, role-forbidden
      probes, 404 probes).
  (2) A per-instance builder make_<role>_headers(user_id) — MANDATORY
      for the entity-backed roles Customer and Driver. Fixtures that
      create a Customer or Driver and then act AS that entity MUST mint
      headers via make_customer_headers(customer["id"]) /
      make_driver_headers(driver["id"]). Falling back to the shared
      constant for an ownership-gated call (e.g., a Customer reading
      their own parcel, or a Driver recording an attempt on their own
      route) would force every ownership check to reject every request.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — opaque roles + non-ownership tests
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Entity-backed roles: shared constants are a fallback for tests
    # that don't exercise ownership (auth probes, 404 probes, etc.).
    "customer_headers": build_user_headers(
        "customer-shared-0001", "Customer",
    ),
    "driver_headers": build_user_headers(
        "driver-shared-0001", "Driver",
    ),
    # Opaque roles: the shared constant IS the canonical form.
    "dispatcher_headers": build_user_headers(
        "dispatcher-op-0001", "Dispatcher",
    ),
    "sorting_hub_operator_headers": build_user_headers(
        "hub-op-0001", "SortingHubOperator",
    ),
    "compliance_officer_headers": build_user_headers(
        "compliance-op-0001", "ComplianceOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed roles.
# ---------------------------------------------------------------------------
def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for a specific Customer (PRD §2.1 entity_backed:Customer).

    Use whenever the downstream call is ownership-gated on
    Parcel.customer_id (e.g., GET /parcels/{id} as Customer, POST
    /appointments as Customer, GET /customers/{id} as the owner,
    PATCH /customers/{id} as the owner, POST /customers/{id}/addresses).
    """
    return build_user_headers(customer_id, "Customer")


def make_driver_headers(driver_id: str) -> Dict[str, str]:
    """Headers for a specific Driver (PRD §2.1 entity_backed:Driver).

    Use whenever the downstream call is ownership-gated on
    Route.driver_id or DeliveryAttempt.driver_id — that is, on
    POST /drivers/{id}/check-in, POST /drivers/{id}/check-out,
    POST /parcels/{id}/attempts (driver of the stop's route),
    POST /routes/{id}/close (driver of the route), and
    GET /parcels/{id} / GET /routes/{id} when called as Driver.
    """
    return build_user_headers(driver_id, "Driver")


def make_dispatcher_headers(opaque_id: str = "dispatcher-op-0001") -> Dict[str, str]:
    """Headers for a Dispatcher (PRD §2.1 opaque). Identity is not
    compared to any entity; the optional argument exists only so a
    test can audit-distinguish two dispatchers."""
    return build_user_headers(opaque_id, "Dispatcher")


def make_sorting_hub_operator_headers(
    opaque_id: str = "hub-op-0001",
) -> Dict[str, str]:
    """Headers for a SortingHubOperator (PRD §2.1 opaque)."""
    return build_user_headers(opaque_id, "SortingHubOperator")


def make_compliance_officer_headers(
    opaque_id: str = "compliance-op-0001",
) -> Dict[str, str]:
    """Headers for a ComplianceOfficer (PRD §2.1 opaque)."""
    return build_user_headers(opaque_id, "ComplianceOfficer")


__all__ = [
    "TEST_USERS",
    "make_customer_headers",
    "make_driver_headers",
    "make_dispatcher_headers",
    "make_sorting_hub_operator_headers",
    "make_compliance_officer_headers",
]
