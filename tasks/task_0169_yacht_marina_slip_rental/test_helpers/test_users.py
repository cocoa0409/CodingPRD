"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "The `Boater` role is entity-backed: when `X-User-Role` is `Boater`,
    the value of `X-User-ID` is the `id` of the acting `Boater`, and
    ownership checks on any resource that references a boater compare
    the resource's `boater_id` foreign-key field to `X-User-ID`. A
    `Boater` may therefore act on their own boater record, their own
    vessels, reservations, waitlist entries, pump-out jobs, insurance
    policies, tow contracts, and slip transfer requests, but not on
    those of any other boater."

    "The `DockMaster` and `BillingClerk` roles are opaque: when
    `X-User-Role` is `DockMaster` or `BillingClerk`, the value of
    `X-User-ID` is an opaque operator identifier not tied to any
    persisted entity."

Boater is entity_backed. Every fixture or test that issues an
ownership-gated call (create vessel for a boater, create reservation on
behalf of a boater, cancel own reservation, schedule pump-out for own
reservation, create waitlist entry, create transfer request, accept /
decline / requeue transfer offer, buy insurance policy, cancel own
policy, buy tow contract, GETs restricted to own resources) MUST mint
headers via `make_boater_headers(boater_id)` with the actual
Boater.id. Falling back to the shared placeholder forces the
implementation to drop the ownership check in order to pass and is a
test bug.

DockMaster and BillingClerk are opaque. Shared deterministic ids are the
canonical form for these.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
DOCK_MASTER_SHARED_ID: str = "dock-master-op-0001"
DOCK_MASTER_SECONDARY_ID: str = "dock-master-op-0002"
BILLING_CLERK_SHARED_ID: str = "billing-clerk-op-0001"

# Entity-backed placeholder — never resolves to a real Boater. Used
# only for auth probes / wrong-role / 404 probes.
BOATER_PLACEHOLDER_ID: str = "boater-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed Boater — shared placeholder is for auth/role/404
    # probes only. Ownership-gated calls must use make_boater_headers().
    "boater_headers": build_user_headers(
        BOATER_PLACEHOLDER_ID, "Boater",
    ),
    # opaque DockMaster — shared constants are canonical.
    "dock_master_headers": build_user_headers(
        DOCK_MASTER_SHARED_ID, "DockMaster",
    ),
    "dock_master_secondary_headers": build_user_headers(
        DOCK_MASTER_SECONDARY_ID, "DockMaster",
    ),
    # opaque BillingClerk — shared constant is canonical.
    "billing_clerk_headers": build_user_headers(
        BILLING_CLERK_SHARED_ID, "BillingClerk",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Boater role.
# PRD §2.1: "X-User-ID is the `id` of the acting `Boater`".
# ---------------------------------------------------------------------------
def make_boater_headers(boater_id: str) -> Dict[str, str]:
    """Headers for a Boater acting on behalf of `boater_id`.

    Required whenever the call resolves an ownership check against the
    boater — POST /marinas/:m/boaters/:b/vessels, POST
    /marinas/:m/reservations (the request's boater_id must equal
    X-User-ID), POST /marinas/:m/reservations/:id/cancel (own
    reservation), POST /marinas/:m/waitlist, POST
    /marinas/:m/waitlist/:id/cancel, POST /marinas/:m/transfer-requests,
    POST /marinas/:m/transfer-requests/:id/accept, /decline, /requeue,
    POST /marinas/:m/pump-out-jobs (own reservation), POST
    /marinas/:m/pump-out-jobs/:id/cancel, POST
    /marinas/:m/boaters/:b/policies, POST
    /marinas/:m/policies/:id/cancel, POST
    /marinas/:m/boaters/:b/tow-contracts, GETs restricted to own
    resources.
    """
    return build_user_headers(boater_id, "Boater")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles. Useful for tests that need
# two distinct operators (e.g., concurrent approval).
# ---------------------------------------------------------------------------
def make_dock_master_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a DockMaster with a specific opaque operator id."""
    return build_user_headers(operator_id, "DockMaster")


def make_billing_clerk_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a BillingClerk with a specific opaque operator id."""
    return build_user_headers(operator_id, "BillingClerk")


__all__ = [
    "DOCK_MASTER_SHARED_ID",
    "DOCK_MASTER_SECONDARY_ID",
    "BILLING_CLERK_SHARED_ID",
    "BOATER_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_boater_headers",
    "make_dock_master_headers",
    "make_billing_clerk_headers",
]
