"""Pre-built role headers for the Public Library API (PRD §2.1).

PRD §2.1 distinguishes two identity flavors:

- `Reader` is *entity-backed*: when X-User-Role is Reader, X-User-ID MUST equal
  the id of the acting Reader row. Ownership checks on Card, Loan, Reservation,
  Fine, ILLRequest, and AcquisitionSuggestion compare the resource's reader_id
  (or, for cards, the resource's id itself joined to its reader_id) to
  X-User-ID. A Reader acting on someone else's resource is rejected with
  ERR_FORBIDDEN.

- `Librarian`, `FineOfficer`, `ILLCoordinator`, and `Admin` are *opaque*:
  X-User-ID is an opaque operator identifier that is not tied to any persisted
  entity; the server may record it (e.g., as the actor on an audit log entry)
  but does not compare it to any entity's id.

For the entity-backed Reader role this module exposes a per-instance builder
(`make_reader_headers(reader_id)`). Fixtures MUST call that builder with the
actual Reader.id whenever the downstream call is ownership-gated; the shared
constant in TEST_USERS is appropriate only for tests that never reach an
ownership check (RBAC probes, missing-header probes, NOT_FOUND probes,
malformed-payload probes).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ─────────────────────────────────────────────────────────────
# Shared constants — canonical form for opaque roles, fallback-only for Reader.
# ─────────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: X-User-ID never compared to any entity id.
    "librarian_headers": build_user_headers("test-librarian-1", "Librarian"),
    "librarian_headers_alt": build_user_headers("test-librarian-2", "Librarian"),
    "fine_officer_headers": build_user_headers("test-fine-officer-1", "FineOfficer"),
    "ill_coordinator_headers": build_user_headers(
        "test-ill-coordinator-1", "ILLCoordinator"
    ),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    # Reader fallback — valid only for tests that do NOT exercise ownership.
    "reader_headers_fallback": build_user_headers("test-reader-fallback", "Reader"),
}


# ─────────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED whenever the call is ownership-gated.
# ─────────────────────────────────────────────────────────────


def make_reader_headers(reader_id: str) -> Dict[str, str]:
    """Build Reader headers where X-User-ID equals the acting Reader.id.

    Per PRD §2.1, ownership checks on Card, Loan, Reservation, Fine, ILLRequest,
    and AcquisitionSuggestion compare the resource's reader_id to X-User-ID, so
    fixtures must pass the same Reader.id they used to create the resource.
    A shared constant would always fail every ownership check, masking the
    implementation's behavior.
    """
    return build_user_headers(reader_id, "Reader")


def make_librarian_headers(user_id: str = "test-librarian-1") -> Dict[str, str]:
    """Librarian is opaque (PRD §2.1) — X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "Librarian")


def make_fine_officer_headers(
    user_id: str = "test-fine-officer-1",
) -> Dict[str, str]:
    """FineOfficer is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "FineOfficer")


def make_ill_coordinator_headers(
    user_id: str = "test-ill-coordinator-1",
) -> Dict[str, str]:
    """ILLCoordinator is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "ILLCoordinator")


def make_admin_headers(user_id: str = "test-admin-1") -> Dict[str, str]:
    """Admin is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "Admin")
