"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule (verbatim):

    "ShipperUser — an end-user acting as a specific shipper. When
    X-User-Role is ShipperUser, X-User-ID is the id of the acting
    Shipper; ownership checks on any resource that references a Shipper
    (a QuoteRequest, a Load, an Invoice, a DisputeClaim) compare the
    resource's shipper_id to X-User-ID."

    "CarrierUser — an end-user acting as a specific carrier. When
    X-User-Role is CarrierUser, X-User-ID is the id of the acting
    Carrier; ownership checks on any resource that references a Carrier
    (notably Load.carrier_id) compare the foreign key to X-User-ID."

Consequence — entity_backed roles (ShipperUser, CarrierUser) MUST mint
headers with the actual entity id whenever the call is ownership-gated:

    - ShipperUser ownership-gated calls (every PRD-listed exclusive
      shipper operation): POST /quote-requests, /accept, /reject,
      /dispute-claims, /accept-counter, /reject-counter, /withdraw,
      load /cancel. Helper: make_shipper_headers(shipper_id).

    - CarrierUser ownership-gated calls: /carrier-accept, /depart,
      /deliver, /accessorial-charges. Helper:
      make_carrier_headers(carrier_id).

Falling back to a shared placeholder id would fail every ownership
check deterministically, masking ownership-enforcement bugs behind
universal 403 responses.

The opaque roles (PlatformAdmin, BrokerOps, CarrierOps) have shared
deterministic ids — they are not compared against any persisted entity
id.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_SHARED_ID: str = "platform-admin-0001"
BROKER_OPS_SHARED_ID: str = "broker-ops-0001"
BROKER_OPS_SECONDARY_ID: str = "broker-ops-0002"
CARRIER_OPS_SHARED_ID: str = "carrier-ops-0001"
CARRIER_OPS_SECONDARY_ID: str = "carrier-ops-0002"

# Entity-backed placeholders — resolve to no real entity. Appropriate
# for auth/role-forbidden/404 probes only. Any test whose success
# depends on the caller owning the subject resource MUST use
# make_shipper_headers / make_carrier_headers with the real id.
SHIPPER_USER_PLACEHOLDER_ID: str = "shipper-user-placeholder-0001"
CARRIER_USER_PLACEHOLDER_ID: str = "carrier-user-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_SHARED_ID, "PlatformAdmin",
    ),
    "broker_ops_headers": build_user_headers(
        BROKER_OPS_SHARED_ID, "BrokerOps",
    ),
    "broker_ops_secondary_headers": build_user_headers(
        BROKER_OPS_SECONDARY_ID, "BrokerOps",
    ),
    "carrier_ops_headers": build_user_headers(
        CARRIER_OPS_SHARED_ID, "CarrierOps",
    ),
    "carrier_ops_secondary_headers": build_user_headers(
        CARRIER_OPS_SECONDARY_ID, "CarrierOps",
    ),
    # entity_backed — placeholders for non-ownership probes only.
    "shipper_user_headers": build_user_headers(
        SHIPPER_USER_PLACEHOLDER_ID, "ShipperUser",
    ),
    "carrier_user_headers": build_user_headers(
        CARRIER_USER_PLACEHOLDER_ID, "CarrierUser",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed roles.
# ---------------------------------------------------------------------------
def make_shipper_headers(shipper_id: str) -> Dict[str, str]:
    """Headers for a ShipperUser acting on behalf of `shipper_id`.

    Required for every ownership-gated shipper-scoped call (PRD §2.1):
    POST /quote-requests, /accept, /reject, /dispute-claims,
    /accept-counter, /reject-counter, /withdraw, /loads/{id}/cancel.
    """
    return build_user_headers(shipper_id, "ShipperUser")


def make_carrier_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for a CarrierUser acting on behalf of `carrier_id`.

    Required for every ownership-gated carrier-scoped call (PRD §2.1):
    /carrier-accept, /depart, /deliver, /accessorial-charges.
    """
    return build_user_headers(carrier_id, "CarrierUser")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles — useful for segregation
# scenarios where two distinct operators must be observable.
# ---------------------------------------------------------------------------
def make_platform_admin_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "PlatformAdmin")


def make_broker_ops_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "BrokerOps")


def make_carrier_ops_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "CarrierOps")


__all__ = [
    "PLATFORM_ADMIN_SHARED_ID",
    "BROKER_OPS_SHARED_ID",
    "BROKER_OPS_SECONDARY_ID",
    "CARRIER_OPS_SHARED_ID",
    "CARRIER_OPS_SECONDARY_ID",
    "SHIPPER_USER_PLACEHOLDER_ID",
    "CARRIER_USER_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_shipper_headers",
    "make_carrier_headers",
    "make_platform_admin_headers",
    "make_broker_ops_headers",
    "make_carrier_ops_headers",
]
