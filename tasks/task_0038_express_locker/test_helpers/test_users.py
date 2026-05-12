"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- `Courier` is **entity-backed**: when X-User-Role is `Courier`, X-User-ID
  is the id of the acting Courier record, and ownership checks on any
  resource that references a courier (notably Parcel.courier_id) compare
  the resource's foreign key to X-User-ID directly.

  Concretely, that means /parcels (deposit start), /parcels/{id}/confirm-deposit,
  /parcels/{id}/correct-wrong-deposit, and /parcels/{id}/recall all run
  ownership comparisons against the actual Courier.id and MUST be called
  with `make_courier_headers(courier_id)` — not the shared fallback
  constant.

- `OperationsAdmin`, `Recipient`, `Any` are **opaque**: X-User-ID is not
  joined against any persisted entity. Their shared TEST_USERS constants
  are canonical.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Opaque roles are canonical here. The Courier fallback
# is for tests that do NOT exercise an ownership comparison (e.g.,
# header-missing tests or wrong-role tests where the call is rejected
# before the ownership branch ever runs).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # --- Opaque roles (canonical) -----------------------------------------
    "operations_admin_headers": build_user_headers(
        "ops-admin-001", "OperationsAdmin",
    ),
    "operations_admin_headers_alt": build_user_headers(
        "ops-admin-002", "OperationsAdmin",
    ),
    "recipient_headers": build_user_headers(
        "recipient-default", "Recipient",
    ),
    "any_headers": build_user_headers(
        "anyone-001", "Any",
    ),
    # --- Fallback for entity-backed Courier role --------------------------
    # Use ONLY when the test does not depend on ownership matching.
    "courier_headers": build_user_headers(
        "courier-fallback-id", "Courier",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder for the entity-backed Courier role (PRD §2.1).
# Use this whenever the call is ownership-gated on Parcel.courier_id.
# ---------------------------------------------------------------------------
def make_courier_headers(courier_id: str) -> Dict[str, str]:
    """Build Courier headers tied to a real Courier.id.

    PRD §2.1: 'when X-User-Role is Courier, the value of X-User-ID is the
    id of the acting Courier record, and ownership checks on any resource
    that references a courier (notably Parcel.courier_id) compare the
    resource's foreign key to X-User-ID directly.'

    Pass the actual `Courier.id` returned by POST /couriers — not a string
    constant. The PRD ownership comparison treats X-User-ID as the
    Courier.id.
    """
    return build_user_headers(courier_id, "Courier")


def make_operations_admin_headers(
    admin_id: str = "ops-admin-001",
) -> Dict[str, str]:
    """Build an OperationsAdmin (opaque) header dict."""
    return build_user_headers(admin_id, "OperationsAdmin")


def make_recipient_headers(
    user_id: str = "recipient-default",
) -> Dict[str, str]:
    """Build a Recipient (opaque) header dict.

    PRD §2.1: 'X-User-ID is opaque (it conceptually represents the
    phone-number-bearing recipient bound to a specific parcel and is
    recorded into events; it is not joined against any persisted recipient
    entity).' For tests that need the recipient identifier to differ from
    the parcel's recipient_phone (validation-priority instance #2 in
    SCAFFOLD_DIFFICULTY_DESIGN), pass a distinct user_id.
    """
    return build_user_headers(user_id, "Recipient")


def make_any_headers(
    user_id: str = "anyone-001",
) -> Dict[str, str]:
    """Build an Any (opaque, read-only) header dict (PRD §2.1)."""
    return build_user_headers(user_id, "Any")


__all__ = [
    "TEST_USERS",
    "make_courier_headers",
    "make_operations_admin_headers",
    "make_recipient_headers",
    "make_any_headers",
]
