"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity; the server
    records it for the segregation-of-duties check (see §2.4) but does
    not compare it to any entity's `id`."

    "When `X-User-Role` is `PayrollAgent`, `X-User-ID` is likewise an
    opaque operator identifier; the server records it as the poster of
    each `Contribution` row so that the segregation-of-duties check at
    purchase-batch time can detect overlap with the calling
    `PlanAdministrator`."

    "When `X-User-Role` is `Participant`, `X-User-ID` is the
    participant's own identifier; the `Participant` entity is
    materialized implicitly, meaning any value supplied via `X-User-ID`
    for this role is treated as an existing participant id. Ownership
    checks on any resource that references a participant — specifically
    the `participant_id` field on `Enrollment`, `Purchase`, `Form3922`,
    and `Disposition` — compare that foreign-key value to `X-User-ID`
    and reject mismatches with `ERR_NOT_OWNER`."

    "When `X-User-Role` is `TaxAuthority`, `X-User-ID` is an opaque
    auditor identifier not tied to any persisted entity ..."

Only ONE role is entity-backed in this PRD: Participant. Every fixture
that creates an Enrollment, posts a Disposition, etc., MUST use the
SAME `X-User-ID` (a stable per-participant id) when acting as that
participant — otherwise ownership checks reject the request. The helper
`make_participant_headers(participant_id)` is mandatory for that.

PlanAdministrator and PayrollAgent are opaque, but the segregation-of-
duties rule (PRD §2.4) requires that the `X-User-ID` posting a
contribution and the `X-User-ID` running the purchase batch on the
SAME period be DIFFERENT. Fixtures that exercise the full lifecycle
default to two distinct shared ids and offer the `make_*` builders so
tests can mint additional distinct operators.
"""
from __future__ import annotations

import uuid
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles. PlanAdministrator and
# PayrollAgent default ids are intentionally distinct so the segregation-
# of-duties check (PRD §2.4) is satisfied by the default lifecycle path.
# ---------------------------------------------------------------------------
PLAN_ADMIN_SHARED_ID: str = "plan-admin-op-0001"
PLAN_ADMIN_SECONDARY_ID: str = "plan-admin-op-0002"

PAYROLL_AGENT_SHARED_ID: str = "payroll-agent-op-0001"
PAYROLL_AGENT_SECONDARY_ID: str = "payroll-agent-op-0002"

TAX_AUTHORITY_SHARED_ID: str = "tax-authority-op-0001"

# Entity-backed placeholder — does NOT resolve to any real participant
# unless tests explicitly create an Enrollment using this id. Used only
# for auth / role / 404 probes that don't exercise ownership.
PARTICIPANT_PLACEHOLDER_ID: str = "participant-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque PlanAdministrator — shared constant is the canonical form.
    "plan_admin_headers": build_user_headers(
        PLAN_ADMIN_SHARED_ID, "PlanAdministrator",
    ),
    "plan_admin_secondary_headers": build_user_headers(
        PLAN_ADMIN_SECONDARY_ID, "PlanAdministrator",
    ),
    # opaque PayrollAgent — shared constant is the canonical form.
    "payroll_agent_headers": build_user_headers(
        PAYROLL_AGENT_SHARED_ID, "PayrollAgent",
    ),
    "payroll_agent_secondary_headers": build_user_headers(
        PAYROLL_AGENT_SECONDARY_ID, "PayrollAgent",
    ),
    # entity_backed Participant — placeholder for non-ownership probes.
    "participant_headers": build_user_headers(
        PARTICIPANT_PLACEHOLDER_ID, "Participant",
    ),
    # opaque TaxAuthority.
    "tax_authority_headers": build_user_headers(
        TAX_AUTHORITY_SHARED_ID, "TaxAuthority",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_participant_headers(participant_id: str) -> Dict[str, str]:
    """Headers for a Participant acting on behalf of `participant_id`.

    MANDATORY whenever the call resolves an ownership check against the
    participant — POST /offering-periods/{op}/enrollments,
    PATCH /enrollments/{id}, POST /enrollments/{id}/withdraw,
    POST /dispositions, PATCH /dispositions/{id},
    DELETE /dispositions/{id}, GET /participants/{me}/* views.

    Per PRD §2.1: "Ownership checks ... compare that foreign-key value
    to `X-User-ID` and reject mismatches with `ERR_NOT_OWNER`."
    """
    return build_user_headers(participant_id, "Participant")


def make_plan_admin_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a PlanAdministrator with a specific opaque operator id.

    Use a DIFFERENT id from any PayrollAgent that posted contributions
    on the same offering period — PRD §2.4 segregation-of-duties.
    """
    return build_user_headers(operator_id, "PlanAdministrator")


def make_payroll_agent_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a PayrollAgent with a specific opaque operator id.

    PRD §2.1: "the server records it as the poster of each `Contribution`
    row so that the segregation-of-duties check at purchase-batch time
    can detect overlap with the calling `PlanAdministrator`."
    """
    return build_user_headers(operator_id, "PayrollAgent")


def make_tax_authority_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a TaxAuthority auditor with a specific opaque id."""
    return build_user_headers(operator_id, "TaxAuthority")


def new_participant_id(prefix: str = "p") -> str:
    """Generate a unique participant id for a fresh fixture.

    PRD §2.1: "the `Participant` entity is materialized implicitly,
    meaning any value supplied via `X-User-ID` for this role is treated
    as an existing participant id." We therefore mint a fresh,
    deterministic-shape opaque string per scenario.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


__all__ = [
    "PLAN_ADMIN_SHARED_ID",
    "PLAN_ADMIN_SECONDARY_ID",
    "PAYROLL_AGENT_SHARED_ID",
    "PAYROLL_AGENT_SECONDARY_ID",
    "TAX_AUTHORITY_SHARED_ID",
    "PARTICIPANT_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_participant_headers",
    "make_plan_admin_headers",
    "make_payroll_agent_headers",
    "make_tax_authority_headers",
    "new_participant_id",
]
