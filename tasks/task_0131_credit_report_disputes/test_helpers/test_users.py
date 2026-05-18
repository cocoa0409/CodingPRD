"""Pre-built role headers for every role defined in PRD §2.1.

PRD §2.1 identity rules — quoted verbatim:

  "When X-User-Role is Consumer, X-User-ID is the id of the acting
   Consumer; any resource scoped to a consumer (the consumer's
   disputes, credit reports, regulatory complaints, freezes, and
   locks) compares its consumer_id to X-User-ID for ownership, and a
   mismatch surfaces as ERR_FORBIDDEN_FOR_ROLE."

  "When X-User-Role is Furnisher, X-User-ID is the id of the acting
   Furnisher; tradeline rows and hard inquiries the furnisher owns or
   initiates are compared by furnisher_id (or
   requesting_furnisher_id) to X-User-ID."

  "When X-User-Role is BureauOperator, CFPBOperator, or PlatformAdmin,
   X-User-ID is an opaque operator identifier not tied to any
   persisted entity; the server may record it for audit purposes but
   does not compare it to any entity's id."

IDENTITY THREADING contract for this test_helpers package:

- Consumer is ENTITY-BACKED. The shared CONSUMER_FALLBACK_ID is a
  string ("fallback-consumer-1") that never equals any real
  Consumer.id minted by POST /consumers, so it is only safe for tests
  that do NOT exercise ownership (missing-header, role-mismatch,
  404-on-non-existent, cross-consumer ERR_FORBIDDEN_FOR_ROLE). Every
  Consumer-acting call whose success depends on owning the targeted
  resource MUST mint headers via make_consumer_headers(consumer["id"])
  using the real Consumer.id returned by create_consumer().

- Furnisher is ENTITY-BACKED. Same rule applies: the shared
  FURNISHER_FALLBACK_ID never equals any real Furnisher.id, so
  ownership-gated Furnisher calls (POST .../tradeline_items with
  furnisher_id=X-User-ID, POST .../hard_inquiries with
  requesting_furnisher_id=X-User-ID) MUST use
  make_furnisher_headers(furnisher["id"]).

- BureauOperator / CFPBOperator / PlatformAdmin are OPAQUE.
  Shared TEST_USERS constants are canonical for every operator call.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
BUREAU_OPERATOR_ID = "bureau-op-001"
BUREAU_OPERATOR_ID_ALT = "bureau-op-002"

CFPB_OPERATOR_ID = "cfpb-op-001"
CFPB_OPERATOR_ID_ALT = "cfpb-op-002"

PLATFORM_ADMIN_ID = "platform-admin-001"

# Entity-backed fallbacks — DO NOT use for ownership-gated calls.
CONSUMER_FALLBACK_ID = "fallback-consumer-1"
FURNISHER_FALLBACK_ID = "fallback-furnisher-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque BureauOperator — shared constant is canonical.
    "bureau_operator_headers": build_user_headers(
        BUREAU_OPERATOR_ID, "BureauOperator",
    ),
    "bureau_operator_headers_alt": build_user_headers(
        BUREAU_OPERATOR_ID_ALT, "BureauOperator",
    ),
    # Opaque CFPBOperator — shared constant is canonical.
    "cfpb_operator_headers": build_user_headers(
        CFPB_OPERATOR_ID, "CFPBOperator",
    ),
    "cfpb_operator_headers_alt": build_user_headers(
        CFPB_OPERATOR_ID_ALT, "CFPBOperator",
    ),
    # Opaque PlatformAdmin — shared constant is canonical.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    # Entity-backed Consumer fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch /
    # 404-on-non-existent / cross-consumer-forbidden paths.
    "consumer_fallback_headers": build_user_headers(
        CONSUMER_FALLBACK_ID, "Consumer",
    ),
    # Entity-backed Furnisher fallback — same restriction.
    "furnisher_fallback_headers": build_user_headers(
        FURNISHER_FALLBACK_ID, "Furnisher",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Consumer / Furnisher.
# ---------------------------------------------------------------------------
def make_consumer_headers(consumer_id: str) -> Dict[str, str]:
    """For Consumer (entity-backed per PRD §2.1). Pass the actual
    Consumer.id of the acting consumer.

    PRD §2.1: "When X-User-Role is Consumer, X-User-ID is the id of
    the acting Consumer; any resource scoped to a consumer ... compares
    its consumer_id to X-User-ID for ownership, and a mismatch
    surfaces as ERR_FORBIDDEN_FOR_ROLE."

    Every Consumer-driven call whose success depends on owning the
    targeted resource MUST use this builder, never the shared
    CONSUMER_FALLBACK_ID.
    """
    return build_user_headers(consumer_id, "Consumer")


def make_furnisher_headers(furnisher_id: str) -> Dict[str, str]:
    """For Furnisher (entity-backed per PRD §2.1). Pass the actual
    Furnisher.id of the acting furnisher.

    PRD §2.1: "When X-User-Role is Furnisher, X-User-ID is the id of
    the acting Furnisher; tradeline rows and hard inquiries the
    furnisher owns or initiates are compared by furnisher_id (or
    requesting_furnisher_id) to X-User-ID."
    """
    return build_user_headers(furnisher_id, "Furnisher")


def make_bureau_operator_headers(op_id: str) -> Dict[str, str]:
    """For BureauOperator (opaque per PRD §2.1). Any non-empty
    operator id is fine; this builder exists so tests that want a
    distinct id (e.g., for audit token discrimination) can supply
    one without relying on a single shared constant."""
    return build_user_headers(op_id, "BureauOperator")


def make_cfpb_operator_headers(op_id: str) -> Dict[str, str]:
    """For CFPBOperator (opaque per PRD §2.1)."""
    return build_user_headers(op_id, "CFPBOperator")


def make_platform_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque per PRD §2.1)."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "BUREAU_OPERATOR_ID",
    "BUREAU_OPERATOR_ID_ALT",
    "CFPB_OPERATOR_ID",
    "CFPB_OPERATOR_ID_ALT",
    "PLATFORM_ADMIN_ID",
    "CONSUMER_FALLBACK_ID",
    "FURNISHER_FALLBACK_ID",
    "TEST_USERS",
    "make_consumer_headers",
    "make_furnisher_headers",
    "make_bureau_operator_headers",
    "make_cfpb_operator_headers",
    "make_platform_admin_headers",
]
