"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "When `X-User-Role` is `FleetManager`, `TaxAdmin`, `ClaimAdjuster`,
    or `VendorOps`, the `X-User-ID` value is treated as an opaque
    operator identifier — it is not tied to any persisted entity, and
    the server may record it on audit metadata but does not compare it
    to any entity's `id` for ownership purposes. When `X-User-Role` is
    `Lessee`, by contrast, `X-User-ID` is the `id` of the acting
    `Lessee` row; ownership checks on any resource that ultimately
    references a `Lessee` (a lease agreement, a fuel card under that
    lease, a settlement on that lease) compare the resource's
    foreign-key chain back to `X-User-ID`. Specifically, a `Lessee`
    caller invoking the dispute operation on an `OverageSettlement`
    must have an `X-User-ID` that matches the `lessee_id` of the
    parent `LeaseAgreement`; mismatch yields `ERR_FORBIDDEN`."

Only the `Lessee` role is entity_backed. Every fixture or test that
issues an ownership-gated call (POST /overage-settlements/{id}/dispute)
MUST mint headers via `make_lessee_headers(lessee_id)` with the actual
Lessee.id. Falling back to the shared placeholder would force the
implementation to drop the ownership check in order to pass and is a
test bug.

The other four roles (FleetManager, TaxAdmin, ClaimAdjuster, VendorOps)
are opaque — shared deterministic ids are the canonical form for
these.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
FLEET_MANAGER_SHARED_ID: str = "fleet-manager-op-0001"
FLEET_MANAGER_SECONDARY_ID: str = "fleet-manager-op-0002"

TAX_ADMIN_SHARED_ID: str = "tax-admin-op-0001"

CLAIM_ADJUSTER_SHARED_ID: str = "claim-adjuster-op-0001"

VENDOR_OPS_SHARED_ID: str = "vendor-ops-op-0001"

# Entity-backed placeholder — never resolves to a real Lessee row.
# Used only for auth probes / wrong-role / 404 probes that don't
# exercise ownership.
LESSEE_PLACEHOLDER_ID: str = "lessee-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque FleetManager — shared constants are the canonical form.
    "fleet_manager_headers": build_user_headers(
        FLEET_MANAGER_SHARED_ID, "FleetManager",
    ),
    "fleet_manager_secondary_headers": build_user_headers(
        FLEET_MANAGER_SECONDARY_ID, "FleetManager",
    ),
    # opaque TaxAdmin — shared constant is canonical.
    "tax_admin_headers": build_user_headers(
        TAX_ADMIN_SHARED_ID, "TaxAdmin",
    ),
    # opaque ClaimAdjuster — shared constant is canonical.
    "claim_adjuster_headers": build_user_headers(
        CLAIM_ADJUSTER_SHARED_ID, "ClaimAdjuster",
    ),
    # opaque VendorOps — shared constant is canonical.
    "vendor_ops_headers": build_user_headers(
        VENDOR_OPS_SHARED_ID, "VendorOps",
    ),
    # entity_backed Lessee — shared constant is a PLACEHOLDER for
    # auth/role/404 probes only. Ownership-gated calls (dispute) MUST
    # use make_lessee_headers(lessee_id).
    "lessee_headers": build_user_headers(
        LESSEE_PLACEHOLDER_ID, "Lessee",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Lessee role.
# PRD §2.1: "X-User-ID is the `id` of the acting `Lessee` row".
# ---------------------------------------------------------------------------
def make_lessee_headers(lessee_id: str) -> Dict[str, str]:
    """Headers for a Lessee acting on behalf of `lessee_id`.

    Required whenever the call resolves an ownership check against the
    lessee — POST /overage-settlements/{id}/dispute is the sole
    Lessee-exclusive write per PRD §2.1 + §3.6 (the dispute operation),
    and reads restricted to the lessee's own resources.
    """
    return build_user_headers(lessee_id, "Lessee")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles — useful for tests that
# need two distinct operators of the same role.
# ---------------------------------------------------------------------------
def make_fleet_manager_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a FleetManager with a specific opaque operator id."""
    return build_user_headers(operator_id, "FleetManager")


def make_tax_admin_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a TaxAdmin with a specific opaque operator id."""
    return build_user_headers(operator_id, "TaxAdmin")


def make_claim_adjuster_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a ClaimAdjuster with a specific opaque operator id."""
    return build_user_headers(operator_id, "ClaimAdjuster")


def make_vendor_ops_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a VendorOps with a specific opaque operator id."""
    return build_user_headers(operator_id, "VendorOps")


__all__ = [
    "FLEET_MANAGER_SHARED_ID",
    "FLEET_MANAGER_SECONDARY_ID",
    "TAX_ADMIN_SHARED_ID",
    "CLAIM_ADJUSTER_SHARED_ID",
    "VENDOR_OPS_SHARED_ID",
    "LESSEE_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_lessee_headers",
    "make_fleet_manager_headers",
    "make_tax_admin_headers",
    "make_claim_adjuster_headers",
    "make_vendor_ops_headers",
]
