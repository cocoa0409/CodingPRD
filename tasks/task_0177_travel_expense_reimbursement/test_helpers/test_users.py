"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules (verbatim):

    "Five roles are recognized, spelled exactly as shown: `TRAVELER`,
    `MANAGER`, `FINANCE_REVIEWER`, `OOP_APPROVER`, and `ADMIN`. The
    first four are entity-backed: when `X-User-Role` is any of
    `TRAVELER`, `MANAGER`, `FINANCE_REVIEWER`, or `OOP_APPROVER`, the
    `X-User-ID` value is the `id` of the acting `Employee`, and any
    ownership check on a resource that references an `Employee` (for
    example, a `Trip` referencing `traveler_id`, an
    `OutOfPolicyApproval` referencing `requester_employee_id`, or a
    `Receipt` referencing `uploader_employee_id`) compares that
    foreign-key field to `X-User-ID`."

    "When `X-User-Role` is `ADMIN`, the `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity ..."

CONSEQUENCE: TRAVELER, MANAGER, FINANCE_REVIEWER, and OOP_APPROVER
are ALL entity_backed. Fixtures and tests that exercise ownership
MUST mint headers via the per-instance builder
`make_{role}_headers(employee_id)` with the real `Employee.id` of the
acting user. The shared-constant `TEST_USERS` entries are placeholders
for tests that probe auth / role / 404 paths WITHOUT exercising
ownership; they do NOT resolve to any real Employee unless tests
explicitly create one with the matching id (X-User-ID must be a
well-formed UUID per PRD §2.1, so we use uuid4() values).

PRD §2.1 X-User-ID shape: "`X-User-ID`, a UUID that identifies the
calling principal". All ids minted here are uuid4 strings.

ADMIN is opaque — the shared constant is the canonical form; any uuid
value works because ADMIN performs no ownership comparisons.
"""
from __future__ import annotations

import uuid
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic UUIDs for placeholder use (auth / role / 404 probes
# that do NOT exercise ownership). These uuids do NOT resolve to any real
# Employee row unless a test deliberately creates one with this id, which
# is impossible because /employees mints its own id. Therefore any
# ownership-gated call that uses these constants WILL fail; fixtures must
# use the per-instance builder with the real Employee.id.
# ---------------------------------------------------------------------------
TRAVELER_PLACEHOLDER_ID: str = str(uuid.UUID(int=0x1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A))
MANAGER_PLACEHOLDER_ID: str = str(uuid.UUID(int=0x2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B))
FINANCE_REVIEWER_PLACEHOLDER_ID: str = str(uuid.UUID(int=0x3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C))
OOP_APPROVER_PLACEHOLDER_ID: str = str(uuid.UUID(int=0x4D4D4D4D4D4D4D4D4D4D4D4D4D4D4D4D))
ADMIN_OPERATOR_ID: str = str(uuid.UUID(int=0x5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E))
ADMIN_OPERATOR_SECONDARY_ID: str = str(uuid.UUID(int=0x6F6F6F6F6F6F6F6F6F6F6F6F6F6F6F6F))


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Placeholder TRAVELER — for tests that probe auth without ownership.
    # (Fixtures MUST use make_traveler_headers(employee_id) instead.)
    "traveler_headers": build_user_headers(
        TRAVELER_PLACEHOLDER_ID, "TRAVELER",
    ),
    # Placeholder MANAGER — for tests that probe auth without ownership.
    "manager_headers": build_user_headers(
        MANAGER_PLACEHOLDER_ID, "MANAGER",
    ),
    # Placeholder FINANCE_REVIEWER — for tests that probe auth without
    # ownership.
    "finance_reviewer_headers": build_user_headers(
        FINANCE_REVIEWER_PLACEHOLDER_ID, "FINANCE_REVIEWER",
    ),
    # Placeholder OOP_APPROVER — for tests that probe auth without
    # ownership.
    "oop_approver_headers": build_user_headers(
        OOP_APPROVER_PLACEHOLDER_ID, "OOP_APPROVER",
    ),
    # ADMIN is opaque — the shared constant is the canonical form.
    "admin_headers": build_user_headers(ADMIN_OPERATOR_ID, "ADMIN"),
    "admin_secondary_headers": build_user_headers(
        ADMIN_OPERATOR_SECONDARY_ID, "ADMIN",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for every entity_backed role whenever
# the call is ownership-gated.
# ---------------------------------------------------------------------------
def make_traveler_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a TRAVELER acting as Employee `employee_id`.

    MANDATORY for: POST /trips (traveler_id must equal X-User-ID),
    POST /trips/{id}/submit, /cancel, /complete, PATCH /trips/{id},
    POST /virtual-cards, POST /virtual-cards/{id}/activate,
    POST /expense-reports, POST /expense-reports/{id}/submit,
    POST /expense-reports/{report_id}/lines, PATCH /expense-lines/{id},
    POST /expense-lines/{id}/attach-receipt, POST /receipts,
    POST /oop-approvals.

    Per PRD §2.1 the value will be compared to the traveler-side
    foreign-key fields of the target resource.
    """
    return build_user_headers(employee_id, "TRAVELER")


def make_manager_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a MANAGER acting as Employee `employee_id`.

    MANDATORY for: POST /trips/{id}/approve, /reject, /request-changes
    (manager must equal the traveler's manager_id), and
    POST /oop-approvals/{id}/l1-approve, /deny.
    """
    return build_user_headers(employee_id, "MANAGER")


def make_finance_reviewer_headers(employee_id: str) -> Dict[str, str]:
    """Headers for a FINANCE_REVIEWER acting as Employee `employee_id`.

    MANDATORY for: report claim / approve / reject / request-changes /
    disburse (segregation-of-duties checks compare reviewer to
    traveler_id), virtual-card issue / lock / unlock / close, OCR waive,
    and OOP L2 / deny.
    """
    return build_user_headers(employee_id, "FINANCE_REVIEWER")


def make_oop_approver_headers(employee_id: str) -> Dict[str, str]:
    """Headers for an OOP_APPROVER acting as Employee `employee_id`.

    MANDATORY for: POST /oop-approvals/{id}/final-approve, /deny.
    The duplicate-approver check (ERR_OOP_DUPLICATE_APPROVER) compares
    this value against l1_approver_id.
    """
    return build_user_headers(employee_id, "OOP_APPROVER")


def make_admin_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an ADMIN with a specific opaque operator id.

    ADMIN performs no ownership comparisons, so any UUID value works.
    """
    return build_user_headers(operator_id, "ADMIN")


def new_uuid() -> str:
    """Mint a fresh UUID4 — useful when tests need a unique id."""
    return str(uuid.uuid4())


__all__ = [
    "TRAVELER_PLACEHOLDER_ID",
    "MANAGER_PLACEHOLDER_ID",
    "FINANCE_REVIEWER_PLACEHOLDER_ID",
    "OOP_APPROVER_PLACEHOLDER_ID",
    "ADMIN_OPERATOR_ID",
    "ADMIN_OPERATOR_SECONDARY_ID",
    "TEST_USERS",
    "make_traveler_headers",
    "make_manager_headers",
    "make_finance_reviewer_headers",
    "make_oop_approver_headers",
    "make_admin_headers",
    "new_uuid",
]
