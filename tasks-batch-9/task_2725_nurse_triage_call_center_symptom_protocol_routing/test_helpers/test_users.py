"""Auth headers per role (PRD §2.1).

PRD §2.1 makes identity binding role-dependent, so the nurse and liaison roles
cannot use a fixed placeholder identifier on any ownership-gated call:

- "When `X-User-Role` is `TriageNurse`, `X-User-ID` is the `id` of the acting
  `Nurse`"
- "When `X-User-Role` is `ChargeNurse`, `X-User-ID` is likewise the `id` of the
  acting `Nurse`"
- "When `X-User-Role` is `PracticeLiaison`, `X-User-ID` is the `id` of the
  acting `Practice`"

The three builder functions below are therefore the only correct way to act as
those roles once real rows exist. `PlatformAdmin`, `IntakeAgent` and
`ComplianceAuditor` carry "an opaque operator identifier not tied to any
persisted entity", so the constants in TEST_USERS are always valid for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CHARGE_NURSE,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_INTAKE_AGENT,
    ROLE_PLATFORM_ADMIN,
    ROLE_PRACTICE_LIAISON,
    ROLE_TRIAGE_NURSE,
)

# Opaque operator identifiers (PRD §2.1).
PLATFORM_ADMIN_USER_ID = "11111111-1111-4111-8111-111111111111"
INTAKE_AGENT_USER_ID = "22222222-2222-4222-8222-222222222222"
COMPLIANCE_AUDITOR_USER_ID = "33333333-3333-4333-8333-333333333333"

# Placeholder entity-backed identifiers, valid only where no ownership,
# licensure or scope comparison is performed (for example a role-rejection
# test that never reaches the ownership gate).
UNBOUND_NURSE_USER_ID = "44444444-4444-4444-8444-444444444444"
UNBOUND_PRACTICE_USER_ID = "55555555-5555-4555-8555-555555555555"

PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
INTAKE_AGENT = build_user_headers(INTAKE_AGENT_USER_ID, ROLE_INTAKE_AGENT)
COMPLIANCE_AUDITOR = build_user_headers(
    COMPLIANCE_AUDITOR_USER_ID, ROLE_COMPLIANCE_AUDITOR
)
UNBOUND_TRIAGE_NURSE = build_user_headers(UNBOUND_NURSE_USER_ID, ROLE_TRIAGE_NURSE)
UNBOUND_CHARGE_NURSE = build_user_headers(UNBOUND_NURSE_USER_ID, ROLE_CHARGE_NURSE)
UNBOUND_PRACTICE_LIAISON = build_user_headers(
    UNBOUND_PRACTICE_USER_ID, ROLE_PRACTICE_LIAISON
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
    ROLE_INTAKE_AGENT: INTAKE_AGENT,
    ROLE_COMPLIANCE_AUDITOR: COMPLIANCE_AUDITOR,
    ROLE_TRIAGE_NURSE: UNBOUND_TRIAGE_NURSE,
    ROLE_CHARGE_NURSE: UNBOUND_CHARGE_NURSE,
    ROLE_PRACTICE_LIAISON: UNBOUND_PRACTICE_LIAISON,
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID):
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_intake_agent_headers(user_id: str = INTAKE_AGENT_USER_ID):
    return build_user_headers(user_id, ROLE_INTAKE_AGENT)


def make_compliance_auditor_headers(user_id: str = COMPLIANCE_AUDITOR_USER_ID):
    """The auditor's opaque id is recorded as `auditor_user_id` (PRD §2.1)."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_AUDITOR)


def make_triage_nurse_headers(nurse_id: str):
    """`X-User-ID` must be the acting `Nurse.id` (PRD §2.1)."""
    return build_user_headers(nurse_id, ROLE_TRIAGE_NURSE)


def make_charge_nurse_headers(nurse_id: str):
    """`X-User-ID` must be the acting `Nurse.id` (PRD §2.1)."""
    return build_user_headers(nurse_id, ROLE_CHARGE_NURSE)


def make_practice_liaison_headers(practice_id: str):
    """`X-User-ID` must be the acting `Practice.id` (PRD §2.1)."""
    return build_user_headers(practice_id, ROLE_PRACTICE_LIAISON)


def headers_for_role(role: str, entity_id: str = None) -> Dict[str, str]:
    """Headers for an arbitrary role, binding an entity id where required."""
    if role in (ROLE_TRIAGE_NURSE, ROLE_CHARGE_NURSE, ROLE_PRACTICE_LIAISON):
        if entity_id is None:
            return TEST_USERS[role]
        return build_user_headers(entity_id, role)
    if entity_id is None:
        return TEST_USERS[role]
    return build_user_headers(entity_id, role)
