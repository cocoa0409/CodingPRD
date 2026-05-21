"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
    acting `Employee`; ownership checks on any resource that references
    an `Employee` ... compare the resource's owning `employee_id` to
    `X-User-ID`. A mismatch surfaces as `ERR_NOT_OWNER`. When
    `X-User-Role` is `HRSpecialist`, `X-User-ID` is the `id` of the
    acting `HRSpecialist`; HR specialists may act on resources owned
    by any employee within the system but their identity must still
    resolve to a known specialist row. For both entity-backed roles,
    an `X-User-ID` that does not resolve to a row in the backing
    entity yields `ERR_UNKNOWN_IDENTITY`. When `X-User-Role` is
    `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier
    not tied to any persisted entity."

Role identities recap:
    - Employee:        entity_backed (concrete /employees POST seeds rows)
    - HRSpecialist:    entity_backed (PRD does not expose a POST endpoint;
                       implementation must seed at least one row that
                       resolves to HR_SPECIALIST_SHARED_ID, which every
                       fixture passes when acting as HR)
    - ComplianceOfficer: opaque (shared constant is canonical)

Fixtures that act as Employee call `make_employee_headers(employee_id)`
with the just-created Employee.id. Fixtures that act as HRSpecialist
use the shared `HR_SPECIALIST_SHARED_ID` so the implementation's
HR-specialist resolution can be satisfied by seeding a single row at
boot (or by being permissive of any non-empty id — both are
PRD-faithful since PRD does not name the seeding mechanism). The two
PER-INSTANCE builders are still provided so a test that intends to
trigger ERR_UNKNOWN_IDENTITY can pass an obviously non-resolving id.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids.
# ---------------------------------------------------------------------------
# ComplianceOfficer is OPAQUE per PRD §2.1 — shared constant is canonical.
COMPLIANCE_OFFICER_SHARED_ID: str = "compliance-op-0001"
COMPLIANCE_OFFICER_SECONDARY_ID: str = "compliance-op-0002"

# entity_backed HRSpecialist — single canonical id every fixture passes
# when acting as HR. The implementation must resolve this id to a known
# HRSpecialist row (e.g., by seeding at boot or by being permissive of
# any non-empty value, which is the PRD-permitted shape since no
# /hr-specialists POST endpoint exists).
HR_SPECIALIST_SHARED_ID: str = "hr-specialist-001"
HR_SPECIALIST_SECONDARY_ID: str = "hr-specialist-002"

# Entity-backed Employee placeholder — used ONLY by tests that need a
# value-shaped id for auth / 404 / ERR_UNKNOWN_IDENTITY probes; this id
# does NOT resolve to any real Employee.
EMPLOYEE_PLACEHOLDER_ID: str = "employee-placeholder-id-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed Employee — shared constant is a placeholder for
    # auth / role / 404 / ERR_UNKNOWN_IDENTITY probes only.
    "employee_headers": build_user_headers(
        EMPLOYEE_PLACEHOLDER_ID, "Employee",
    ),
    # entity_backed HRSpecialist — shared canonical id for fixture use.
    "hr_specialist_headers": build_user_headers(
        HR_SPECIALIST_SHARED_ID, "HRSpecialist",
    ),
    "hr_specialist_secondary_headers": build_user_headers(
        HR_SPECIALIST_SECONDARY_ID, "HRSpecialist",
    ),
    # opaque ComplianceOfficer — shared constant is the canonical form.
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_SHARED_ID, "ComplianceOfficer",
    ),
    "compliance_officer_secondary_headers": build_user_headers(
        COMPLIANCE_OFFICER_SECONDARY_ID, "ComplianceOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed roles when the
# call is ownership-gated.
# ---------------------------------------------------------------------------
def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """Headers for an Employee acting on resources they own.

    PRD §2.1: ownership checks compare the resource's `employee_id`
    to `X-User-ID`. Required whenever the call is Employee-acted and
    subject to ownership — POST /employees/{employee_id}/leave-cases,
    POST /leave-cases/{leave_case_id}/return when acting as Employee,
    every GET subject to Employee ownership, etc.
    """
    return build_user_headers(employee_id, "Employee")


def make_hr_specialist_headers(hr_specialist_id: str) -> Dict[str, str]:
    """Headers for an HRSpecialist with a specific id.

    PRD §2.1: HRSpecialist is entity_backed; the X-User-ID "must still
    resolve to a known specialist row". Fixtures generally pass
    HR_SPECIALIST_SHARED_ID. Tests that exercise ERR_UNKNOWN_IDENTITY
    pass an id not seeded by any fixture (e.g. a random UUID).
    """
    return build_user_headers(hr_specialist_id, "HRSpecialist")


def make_compliance_officer_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a ComplianceOfficer with a specific opaque id.

    PRD §2.1: ComplianceOfficer X-User-ID is an opaque operator
    identifier not tied to any persisted entity.
    """
    return build_user_headers(operator_id, "ComplianceOfficer")


__all__ = [
    "COMPLIANCE_OFFICER_SHARED_ID",
    "COMPLIANCE_OFFICER_SECONDARY_ID",
    "HR_SPECIALIST_SHARED_ID",
    "HR_SPECIALIST_SECONDARY_ID",
    "EMPLOYEE_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_employee_headers",
    "make_hr_specialist_headers",
    "make_compliance_officer_headers",
]
