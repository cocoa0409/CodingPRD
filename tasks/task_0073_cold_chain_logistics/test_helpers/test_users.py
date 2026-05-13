"""Pre-built role headers for every role in the PRD.

PRD §2.1: 'For every recognised business role, X-User-ID is an opaque
operator identifier and is not tied to any persisted entity row. The
server may record it as a foreign-key-like value on certain resources
— for example, a TransportTask records shipper_id, carrier_id and
consignee_id whose values are expected to match the X-User-ID of the
corresponding party — but it does not compare X-User-ID to an id field
on a Shipper, Carrier or Consignee row, because no such row exists.'

Consequences for headers:

1. Shared-constant TEST_USERS entries are valid for:
   - opaque-identity calls that do not exercise resource ownership
     (e.g. POST /vehicles by a CARRIER, POST /drivers by a CARRIER,
      GET-by-id where the caller's role itself authorizes the read,
      400-on-bad-payload, 404-on-missing-resource, wrong-role 403).

2. Per-instance builders MUST be used whenever the call is gated by
   the task's stored shipper_id / carrier_id / consignee_id (e.g.
   the CARRIER closing a task — they must be the carrier that created
   it — or by segregation-of-duties on /responsibility-decisions/
   {id}/finalize. The opaque X-User-ID used to create the task is
   what later calls must echo, NOT the shared constant.

   Fixtures pass the same opaque id consistently. Falling back to
   a shared constant for an ownership-gated call would force the
   implementation to drop the ownership check in order to pass.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Shipper — opaque, but ownership-gated reads/writes need the SAME
    # opaque id that was stored as TransportTask.shipper_id.
    "shipper_headers": build_user_headers("shipper-001", "SHIPPER"),
    "shipper_headers_alt": build_user_headers("shipper-002", "SHIPPER"),

    # Carrier — same caveat: many carrier operations are gated on
    # X-User-ID == TransportTask.carrier_id.
    "carrier_headers": build_user_headers("carrier-001", "CARRIER"),
    "carrier_headers_alt": build_user_headers("carrier-002", "CARRIER"),

    # Driver — opaque, gated by TransportTask.driver_id matching.
    "driver_headers": build_user_headers("driver-001", "DRIVER"),
    "driver_headers_alt": build_user_headers("driver-002", "DRIVER"),

    # Consignee — opaque.
    "consignee_headers": build_user_headers("consignee-001", "CONSIGNEE"),
    "consignee_headers_alt": build_user_headers("consignee-002", "CONSIGNEE"),

    # Dispatcher — opaque, no ownership comparison.
    "dispatcher_headers": build_user_headers("dispatcher-001", "DISPATCHER"),
    "dispatcher_headers_alt": build_user_headers("dispatcher-002", "DISPATCHER"),

    # Compliance officer — opaque, SoD-gated on /decisions/{id}/finalize.
    "compliance_headers": build_user_headers(
        "compliance-001", "COMPLIANCE_OFFICER",
    ),
    "compliance_headers_alt": build_user_headers(
        "compliance-002", "COMPLIANCE_OFFICER",
    ),

    # Insurance adjuster — opaque.
    "insurance_headers": build_user_headers(
        "insurance-001", "INSURANCE_ADJUSTER",
    ),

    # System — opaque, used for clock fixture and IoT ingest path.
    "system_headers": build_user_headers("system", "SYSTEM"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED whenever the call is gated on
# X-User-ID == TransportTask.shipper_id / carrier_id / consignee_id /
# driver_id, or on the SoD rule in PRD §3.10. The fixture layer threads
# these IDs so the test body never has to.
# ---------------------------------------------------------------------------
def make_shipper_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: 'a TransportTask records shipper_id ... whose values
    are expected to match the X-User-ID of the corresponding party.'

    Use this builder whenever the call is ownership-gated by the
    task's stored shipper_id (e.g. the shipper accept/dispute path)."""
    return build_user_headers(user_id, "SHIPPER")


def make_carrier_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1 + §3.8: carrier-id is compared to X-User-ID for
    ownership-gated calls (notably POST /transport-tasks/{id}/close
    and POST /insurance-claims)."""
    return build_user_headers(user_id, "CARRIER")


def make_driver_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: 'a TransportTask records ... whose values are
    expected to match the X-User-ID of the corresponding party.'

    Use this when departures, arrivals or handovers are issued by
    the driver assigned to the task — the X-User-ID must equal the
    task's driver_id."""
    return build_user_headers(user_id, "DRIVER")


def make_consignee_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: consignee ownership is by stored consignee_id."""
    return build_user_headers(user_id, "CONSIGNEE")


def make_dispatcher_headers(
    user_id: str = "dispatcher-001",
) -> Dict[str, str]:
    """PRD §2.1: DISPATCHER X-User-ID is opaque."""
    return build_user_headers(user_id, "DISPATCHER")


def make_compliance_headers(
    user_id: str = "compliance-001",
) -> Dict[str, str]:
    """PRD §3.10: 'the finalizing actor's X-User-ID must not equal any
    of the task's shipper_id, carrier_id, or consignee_id.' Choose a
    distinct opaque id for the finalizer when calling
    /responsibility-decisions/{id}/finalize."""
    return build_user_headers(user_id, "COMPLIANCE_OFFICER")


def make_insurance_headers(
    user_id: str = "insurance-001",
) -> Dict[str, str]:
    """PRD §2.1: INSURANCE_ADJUSTER X-User-ID is opaque."""
    return build_user_headers(user_id, "INSURANCE_ADJUSTER")


def make_system_headers(user_id: str = "system") -> Dict[str, str]:
    """PRD §2.1: SYSTEM principal for test fixtures and IoT ingest."""
    return build_user_headers(user_id, "SYSTEM")


__all__ = [
    "TEST_USERS",
    "make_shipper_headers",
    "make_carrier_headers",
    "make_driver_headers",
    "make_consignee_headers",
    "make_dispatcher_headers",
    "make_compliance_headers",
    "make_insurance_headers",
    "make_system_headers",
]
