"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1 identity rules:

- Applicant is OPAQUE. PRD §2.1: "When X-User-Role is Applicant,
  X-User-ID is an opaque consumer identifier not tied to any persisted
  entity. The server records it on every Application the caller creates
  (as applicant_id), and ownership checks on Application-scoped writes
  compare the resource's applicant_id to X-User-ID."

  Although the role identity is opaque, the X-User-ID DOES double as
  Application.applicant_id for ownership checks. Therefore tests whose
  success depends on the Applicant owning a particular Application MUST
  use the SAME X-User-ID across the create-application call and any
  later ownership-gated call. The per-instance builder
  make_applicant_headers(applicant_id) supports this — pass the same
  string both when creating the application and when issuing the later
  call.

- MarketplaceAdmin is OPAQUE. PRD §2.1: "When X-User-Role is
  MarketplaceAdmin, X-User-ID is an opaque operator identifier not tied
  to any persisted entity. The server may record it for audit purposes
  but does not compare it to any entity's id." Shared admin_headers
  constant is canonical.

- Insurer is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Insurer,
  X-User-ID is the id of the acting Insurer row; ownership checks on
  plan-management operations compare the target Plan.insurer_id to
  X-User-ID." Every Insurer call whose success depends on owning the
  target Plan MUST mint headers via make_insurer_headers(insurer["id"])
  — never via the shared INSURER_FALLBACK_ID constant.

- CustomerService is OPAQUE. PRD §2.1: "When X-User-Role is
  CustomerService, X-User-ID is an opaque support-operator identifier
  not tied to any persisted entity. The server may record it ... but
  does not compare it to any entity's id." Shared customer_service
  headers constant is canonical.

The shared *_FALLBACK_ID constants are ONLY safe for tests that DO NOT
exercise ownership (auth/role-rejection paths, NotFound on unrelated
paths). Ownership-gated calls MUST use the per-instance builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
APPLICANT_FALLBACK_ID = "applicant-001"
APPLICANT_FALLBACK_ID_ALT = "applicant-002"
MARKETPLACE_ADMIN_ID = "admin-001"
MARKETPLACE_ADMIN_ID_ALT = "admin-002"
CUSTOMER_SERVICE_ID = "cs-001"

# Entity-backed Insurer fallback — DO NOT use for ownership-gated calls.
INSURER_FALLBACK_ID = "fallback-insurer-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Applicant fallback — safe ONLY for tests that do not require
    # ownership of a specific Application. For Applicant-acting tests
    # that need to own an Application, use make_applicant_headers(id)
    # with the same id that was passed to /applications create.
    "applicant_fallback_headers": build_user_headers(
        APPLICANT_FALLBACK_ID, "Applicant",
    ),
    "applicant_fallback_headers_alt": build_user_headers(
        APPLICANT_FALLBACK_ID_ALT, "Applicant",
    ),
    # Opaque MarketplaceAdmin — shared constant is canonical.
    "admin_headers": build_user_headers(
        MARKETPLACE_ADMIN_ID, "MarketplaceAdmin",
    ),
    "admin_headers_alt": build_user_headers(
        MARKETPLACE_ADMIN_ID_ALT, "MarketplaceAdmin",
    ),
    # Opaque CustomerService — shared constant is canonical.
    "customer_service_headers": build_user_headers(
        CUSTOMER_SERVICE_ID, "CustomerService",
    ),
    # Entity-backed Insurer fallback — DO NOT use for ownership-gated
    # Plan calls. Safe only for auth/role-rejection / NotFound paths and
    # for plain GET /plans / GET /insurers list reads.
    "insurer_fallback_headers": build_user_headers(
        INSURER_FALLBACK_ID, "Insurer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for Insurer (entity-backed) and for
# any Applicant-acting call that exercises Application ownership.
# ---------------------------------------------------------------------------
def make_insurer_headers(insurer_id: str) -> Dict[str, str]:
    """For Insurer (entity_backed:Insurer). Pass the actual Insurer.id of
    the acting insurer.

    PRD §2.1: "When X-User-Role is Insurer, X-User-ID is the id of the
    acting Insurer row; ownership checks on plan-management operations
    compare the target Plan.insurer_id to X-User-ID."

    Every Insurer-driven Plan write — POST /plans, PATCH /plans/{id},
    POST /plans/{id}/variants — whose success depends on the calling
    Insurer owning the target Plan MUST use this builder, not the
    shared INSURER_FALLBACK_ID constant.
    """
    return build_user_headers(insurer_id, "Insurer")


def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """For Applicant (opaque, but X-User-ID is recorded as
    Application.applicant_id).

    PRD §2.1: "The server records it on every Application the caller
    creates (as applicant_id), and ownership checks on
    Application-scoped writes compare the resource's applicant_id to
    X-User-ID. A mismatch is rejected with ERR_NOT_APPLICATION_OWNER."

    Every Applicant-acting write under /applications/{id}/* that
    targets a specific Application MUST be issued with this builder
    using the SAME applicant_id that was used to create the
    Application — otherwise the server will reject the call with
    ERR_NOT_APPLICATION_OWNER even though the role is correct.
    """
    return build_user_headers(applicant_id, "Applicant")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For MarketplaceAdmin (opaque). Any non-empty operator id works;
    this builder exists so tests that need distinct admin ids (audit
    discrimination in concurrency races) can supply one.
    """
    return build_user_headers(admin_id, "MarketplaceAdmin")


def make_customer_service_headers(cs_id: str) -> Dict[str, str]:
    """For CustomerService (opaque). Any non-empty operator id works."""
    return build_user_headers(cs_id, "CustomerService")


__all__ = [
    "APPLICANT_FALLBACK_ID",
    "APPLICANT_FALLBACK_ID_ALT",
    "MARKETPLACE_ADMIN_ID",
    "MARKETPLACE_ADMIN_ID_ALT",
    "CUSTOMER_SERVICE_ID",
    "INSURER_FALLBACK_ID",
    "TEST_USERS",
    "make_insurer_headers",
    "make_applicant_headers",
    "make_admin_headers",
    "make_customer_service_headers",
]
