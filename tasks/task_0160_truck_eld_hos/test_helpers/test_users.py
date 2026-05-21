"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the
    acting `Driver` entity; every operation a driver performs is scoped
    to themselves, and ownership checks on any resource that references
    a `Driver` (a `DutyEvent`, a `DailyLog`, a `Violation`, an
    `AdverseConditionsExemption`) compare the resource's `driver_id`
    foreign-key field to `X-User-ID`. When `X-User-Role` is
    `CarrierSafetyOfficer`, `X-User-ID` is an opaque operator identifier
    not tied to any persisted entity ... When `X-User-Role` is
    `FMCSAAuditor`, `X-User-ID` is likewise an opaque federal-auditor
    identifier with no entity backing. When `X-User-Role` is
    `PlatformAdmin`, `X-User-ID` is an opaque platform-operator
    identifier, again with no entity backing."

The only entity_backed role is `Driver`. Every Driver-initiated call
that exercises ownership — POST /drivers/{id}/bind,
POST /drivers/{id}/unbind, POST /drivers/{id}/duty-events,
POST /drivers/{id}/duty-events/{event_id}/edit,
POST /drivers/{id}/daily-logs/{log_id}/certify,
POST /violations/{violation_id}/acknowledge,
POST /drivers/{id}/adverse-conditions — MUST be made with headers
minted by `make_driver_headers(driver_id)` so that X-User-ID equals
the real Driver.id the request claims to act on. Falling back to the
shared placeholder DRIVER_PLACEHOLDER_ID would fail every Driver
ownership check deterministically and hide implementation bugs behind
universal 403s.

The other three roles (CarrierSafetyOfficer, FMCSAAuditor,
PlatformAdmin) are opaque per PRD §2.1: shared deterministic ids are
the canonical form. CarrierSafetyOfficer additionally has a
secondary-operator builder because PRD §3.8 names the race "two
safety officers" and one of the bind-cross-carrier scenarios requires
two distinct carrier scopes.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
OFFICER_SHARED_ID: str = "officer-op-0001"
OFFICER_SECONDARY_ID: str = "officer-op-0002"

AUDITOR_SHARED_ID: str = "auditor-op-0001"

ADMIN_SHARED_ID: str = "admin-op-0001"

# Driver is entity_backed — this placeholder resolves to no real
# Driver row. Appropriate for auth/role-forbidden/404 probes only;
# any test whose success depends on the driver owning the resource
# MUST use make_driver_headers(driver_id) with a real Driver.id.
DRIVER_PLACEHOLDER_ID: str = "driver-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed Driver — shared constant is a placeholder for
    # auth / role / 404 probes only.
    "driver_headers": build_user_headers(
        DRIVER_PLACEHOLDER_ID, "Driver",
    ),
    # opaque roles — shared constants are the canonical form.
    "officer_headers": build_user_headers(
        OFFICER_SHARED_ID, "CarrierSafetyOfficer",
    ),
    "officer_secondary_headers": build_user_headers(
        OFFICER_SECONDARY_ID, "CarrierSafetyOfficer",
    ),
    "auditor_headers": build_user_headers(
        AUDITOR_SHARED_ID, "FMCSAAuditor",
    ),
    "admin_headers": build_user_headers(
        ADMIN_SHARED_ID, "PlatformAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Driver role.
# PRD §2.1: "X-User-ID is the id of the acting Driver entity ... ownership
# checks on any resource that references a Driver ... compare the
# resource's driver_id foreign-key field to X-User-ID."
# ---------------------------------------------------------------------------
def make_driver_headers(driver_id: str) -> Dict[str, str]:
    """Headers for a Driver acting as `driver_id`.

    Required whenever the call resolves an ownership check against
    Driver.id — bind, unbind, duty-event append, duty-event edit,
    daily-log certify, violation acknowledge, adverse-conditions
    declare.
    """
    return build_user_headers(driver_id, "Driver")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles — used when a test needs two
# distinct operators (e.g., the report-to-fmcsa race in PRD §3.8).
# ---------------------------------------------------------------------------
def make_officer_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a CarrierSafetyOfficer with a specific opaque id.

    PRD §3.8 names a concurrency scenario where two officers race to
    report the same violation — tests use this builder to construct
    headers carrying distinct operator ids for that race.
    """
    return build_user_headers(operator_id, "CarrierSafetyOfficer")


def make_auditor_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "FMCSAAuditor")


def make_admin_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "PlatformAdmin")


__all__ = [
    "OFFICER_SHARED_ID", "OFFICER_SECONDARY_ID",
    "AUDITOR_SHARED_ID", "ADMIN_SHARED_ID",
    "DRIVER_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_driver_headers",
    "make_officer_headers",
    "make_auditor_headers",
    "make_admin_headers",
]
