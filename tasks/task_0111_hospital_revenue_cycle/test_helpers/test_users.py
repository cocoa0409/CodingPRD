"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules — ALL ROLES ARE OPAQUE:

- PRD §2.1: "When X-User-Role is RegistrationClerk, X-User-ID is an
  opaque operator identifier not tied to any persisted entity; the
  server may record it for audit (for example, in fields a transition
  writes) but does not compare it to any entity's id."

- PRD §2.1: "When X-User-Role is ChargeCaptureClerk, X-User-ID is
  likewise an opaque operator identifier with no entity backing."

- PRD §2.1: "When X-User-Role is Coder, X-User-ID is again opaque; in
  particular, the coder_id written on a CodingRecord is supplied in the
  request body and need not match X-User-ID."

- PRD §2.1: "When X-User-Role is Biller, X-User-ID is opaque."

- PRD §2.1: "When X-User-Role is TestHarness, X-User-ID is opaque and
  the role exists solely to drive the clock-advance capability in tests."

Because every role is opaque, the shared constants in TEST_USERS are
canonical for every call — ownership is NOT exercised against
X-User-ID in this domain. The per-instance builders below exist for
race-condition tests that need two distinct operator audit tokens, not
because ownership is gated on the id.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
REGISTRATION_CLERK_ID = "clerk-reg-001"
REGISTRATION_CLERK_ID_ALT = "clerk-reg-002"
CHARGE_CAPTURE_CLERK_ID = "clerk-chg-001"
CHARGE_CAPTURE_CLERK_ID_ALT = "clerk-chg-002"
CODER_ID = "coder-001"
CODER_ID_ALT = "coder-002"
BILLER_ID = "biller-001"
BILLER_ID_ALT = "biller-002"
TEST_HARNESS_ID = "harness-001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # RegistrationClerk — opaque
    "registration_clerk_headers": build_user_headers(
        REGISTRATION_CLERK_ID, "RegistrationClerk",
    ),
    "registration_clerk_headers_alt": build_user_headers(
        REGISTRATION_CLERK_ID_ALT, "RegistrationClerk",
    ),
    # ChargeCaptureClerk — opaque
    "charge_capture_clerk_headers": build_user_headers(
        CHARGE_CAPTURE_CLERK_ID, "ChargeCaptureClerk",
    ),
    "charge_capture_clerk_headers_alt": build_user_headers(
        CHARGE_CAPTURE_CLERK_ID_ALT, "ChargeCaptureClerk",
    ),
    # Coder — opaque
    "coder_headers": build_user_headers(CODER_ID, "Coder"),
    "coder_headers_alt": build_user_headers(CODER_ID_ALT, "Coder"),
    # Biller — opaque
    "biller_headers": build_user_headers(BILLER_ID, "Biller"),
    "biller_headers_alt": build_user_headers(BILLER_ID_ALT, "Biller"),
    # TestHarness — opaque, test-only
    "test_harness_headers": build_user_headers(
        TEST_HARNESS_ID, "TestHarness",
    ),
}


def make_registration_clerk_headers(user_id: str) -> Dict[str, str]:
    """Build a RegistrationClerk header set with a custom operator id.
    Useful for race tests that need distinct audit tokens. PRD §2.1:
    the id is opaque audit data; no entity ownership check is performed
    against it."""
    return build_user_headers(user_id, "RegistrationClerk")


def make_charge_capture_clerk_headers(user_id: str) -> Dict[str, str]:
    """Build a ChargeCaptureClerk header set with a custom operator id.
    PRD §2.1: id is opaque."""
    return build_user_headers(user_id, "ChargeCaptureClerk")


def make_coder_headers(user_id: str) -> Dict[str, str]:
    """Build a Coder header set with a custom operator id. PRD §2.1:
    id is opaque; coder_id is supplied in the CodingRecord body and is
    independent of X-User-ID."""
    return build_user_headers(user_id, "Coder")


def make_biller_headers(user_id: str) -> Dict[str, str]:
    """Build a Biller header set with a custom operator id. PRD §2.1:
    id is opaque."""
    return build_user_headers(user_id, "Biller")


__all__ = [
    "REGISTRATION_CLERK_ID",
    "REGISTRATION_CLERK_ID_ALT",
    "CHARGE_CAPTURE_CLERK_ID",
    "CHARGE_CAPTURE_CLERK_ID_ALT",
    "CODER_ID",
    "CODER_ID_ALT",
    "BILLER_ID",
    "BILLER_ID_ALT",
    "TEST_HARNESS_ID",
    "TEST_USERS",
    "make_registration_clerk_headers",
    "make_charge_capture_clerk_headers",
    "make_coder_headers",
    "make_biller_headers",
]
