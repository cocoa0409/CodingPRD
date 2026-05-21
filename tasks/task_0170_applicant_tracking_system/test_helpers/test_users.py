"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "Four of these roles are entity-backed, meaning `X-User-ID` must
    be the `id` of a persisted entity. When `X-User-Role` is
    `Recruiter`, `X-User-ID` is the `id` of the acting `Recruiter`,
    and ownership checks on any resource that references a `Recruiter`
    compare the resource's foreign-key field (such as a requisition's
    `recruiter_id`) to `X-User-ID`. The same pattern applies for the
    other three entity-backed roles: when `X-User-Role` is
    `HiringManager`, `X-User-ID` is the `id` of the acting
    `HiringManager` and is compared against a resource's
    `hiring_manager_id`; when `X-User-Role` is `Interviewer`,
    `X-User-ID` is the `id` of the acting `Interviewer` and is compared
    against an interview's `interviewer_id`; when `X-User-Role` is
    `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` and
    is compared against an application's `candidate_id`."

    "The remaining five roles — `Compensation`, `Executive`,
    `ComplianceOfficer`, `PayrollOperator`, and `PlatformAdmin` — are
    opaque operator identities not tied to any persisted entity."

Four roles are entity_backed (Recruiter, HiringManager, Interviewer,
Candidate). Every fixture or test that issues an ownership-gated call
MUST mint headers via the matching make_*_headers() builder with the
real entity id. Falling back to the shared placeholder would force the
implementation to drop the ownership check in order to pass and is a
test bug.

Five roles are opaque (Compensation, Executive, ComplianceOfficer,
PayrollOperator, PlatformAdmin). Shared deterministic ids are the
canonical form for these.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_SHARED_ID: str = "platform-admin-op-0001"

COMPENSATION_SHARED_ID: str = "compensation-op-0001"
COMPENSATION_SECONDARY_ID: str = "compensation-op-0002"

EXECUTIVE_SHARED_ID: str = "executive-op-0001"
EXECUTIVE_SECONDARY_ID: str = "executive-op-0002"

COMPLIANCE_OFFICER_SHARED_ID: str = "compliance-officer-op-0001"

PAYROLL_OPERATOR_SHARED_ID: str = "payroll-operator-op-0001"

# Entity-backed placeholders — never resolve to a real entity. Used
# only for auth probes / wrong-role / 404 probes.
RECRUITER_PLACEHOLDER_ID: str = "recruiter-placeholder-0001"
HIRING_MANAGER_PLACEHOLDER_ID: str = "hiring-manager-placeholder-0001"
INTERVIEWER_PLACEHOLDER_ID: str = "interviewer-placeholder-0001"
CANDIDATE_PLACEHOLDER_ID: str = "candidate-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ---- entity_backed roles (placeholders for non-ownership probes) ----
    "recruiter_headers": build_user_headers(
        RECRUITER_PLACEHOLDER_ID, "Recruiter",
    ),
    "hiring_manager_headers": build_user_headers(
        HIRING_MANAGER_PLACEHOLDER_ID, "HiringManager",
    ),
    "interviewer_headers": build_user_headers(
        INTERVIEWER_PLACEHOLDER_ID, "Interviewer",
    ),
    "candidate_headers": build_user_headers(
        CANDIDATE_PLACEHOLDER_ID, "Candidate",
    ),
    # ---- opaque roles (shared constants are canonical) ----
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_SHARED_ID, "PlatformAdmin",
    ),
    "compensation_headers": build_user_headers(
        COMPENSATION_SHARED_ID, "Compensation",
    ),
    "compensation_secondary_headers": build_user_headers(
        COMPENSATION_SECONDARY_ID, "Compensation",
    ),
    "executive_headers": build_user_headers(
        EXECUTIVE_SHARED_ID, "Executive",
    ),
    "executive_secondary_headers": build_user_headers(
        EXECUTIVE_SECONDARY_ID, "Executive",
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_SHARED_ID, "ComplianceOfficer",
    ),
    "payroll_operator_headers": build_user_headers(
        PAYROLL_OPERATOR_SHARED_ID, "PayrollOperator",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed roles.
# PRD §2.1: "X-User-ID is the `id` of the acting `Recruiter` ...
# `HiringManager` ... `Interviewer` ... `Candidate`".
# ---------------------------------------------------------------------------
def make_recruiter_headers(recruiter_id: str) -> Dict[str, str]:
    """Headers for a Recruiter acting on behalf of `recruiter_id`.

    Required whenever the call resolves an ownership check against the
    recruiter — e.g., POST /requisitions/{id}/submit (must match the
    requisition's recruiter_id), POST /requisitions/{id}/hold|resume|
    cancel, POST /applications/{id}/advance|reject, POST
    /applications/{id}/interviews, POST /applications/{id}/offers,
    PATCH /offers/{id}, POST /offers/{id}/submit|extend|rescind."""
    return build_user_headers(recruiter_id, "Recruiter")


def make_hiring_manager_headers(hiring_manager_id: str) -> Dict[str, str]:
    """Headers for a HiringManager acting on behalf of `hiring_manager_id`.

    Required for /requisitions/{id}/approve (must match the
    requisition's hiring_manager_id) and for /offers/{id}/approve when
    that step's approver_role is HIRING_MANAGER (id matches
    required_approver_id)."""
    return build_user_headers(hiring_manager_id, "HiringManager")


def make_interviewer_headers(interviewer_id: str) -> Dict[str, str]:
    """Headers for an Interviewer acting on behalf of `interviewer_id`.

    Required for POST /interviews/{id}/feedback (must equal the
    Interview's interviewer_id per PRD §3.4)."""
    return build_user_headers(interviewer_id, "Interviewer")


def make_candidate_headers(candidate_id: str) -> Dict[str, str]:
    """Headers for a Candidate acting on behalf of `candidate_id`.

    Required whenever the call resolves an ownership check against the
    candidate — POST /applications/{id}/withdraw, POST
    /offers/{id}/accept|decline (acting candidate must match parent
    application's candidate_id), POST /candidates/{id}/eeo-record on
    own candidate id."""
    return build_user_headers(candidate_id, "Candidate")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles. Useful when a test needs two
# distinct operators (concurrent approval scenarios).
# ---------------------------------------------------------------------------
def make_compensation_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a Compensation operator with a specific opaque id.

    PRD §2.1: "For each of them, `X-User-ID` is an opaque identifier";
    PRD §3.5: "for `COMPENSATION` and `EXECUTIVE` steps, the id is an
    opaque operator identity ... the supplied id is matched against
    `required_approver_id`."  Tests must mint this builder with the
    same id they used as required_approver_id on the corresponding
    approval step.
    """
    return build_user_headers(operator_id, "Compensation")


def make_executive_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an Executive operator with a specific opaque id.

    PRD §3.5: same matching rule as Compensation — id must equal the
    relevant OfferApprovalStep.required_approver_id."""
    return build_user_headers(operator_id, "Executive")


def make_compliance_officer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "ComplianceOfficer")


def make_payroll_operator_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "PayrollOperator")


def make_platform_admin_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "PlatformAdmin")


__all__ = [
    "PLATFORM_ADMIN_SHARED_ID",
    "COMPENSATION_SHARED_ID",
    "COMPENSATION_SECONDARY_ID",
    "EXECUTIVE_SHARED_ID",
    "EXECUTIVE_SECONDARY_ID",
    "COMPLIANCE_OFFICER_SHARED_ID",
    "PAYROLL_OPERATOR_SHARED_ID",
    "RECRUITER_PLACEHOLDER_ID",
    "HIRING_MANAGER_PLACEHOLDER_ID",
    "INTERVIEWER_PLACEHOLDER_ID",
    "CANDIDATE_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_recruiter_headers",
    "make_hiring_manager_headers",
    "make_interviewer_headers",
    "make_candidate_headers",
    "make_compensation_headers",
    "make_executive_headers",
    "make_compliance_officer_headers",
    "make_payroll_operator_headers",
    "make_platform_admin_headers",
]
