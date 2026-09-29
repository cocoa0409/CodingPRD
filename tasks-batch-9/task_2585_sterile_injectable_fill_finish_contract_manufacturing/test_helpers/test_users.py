"""Acting principals for the six roles of PRD 2.1.

For the five CMO-side roles `X-User-ID` is an opaque operator identifier that
the server records but never compares to an entity `id`, so a module-level
header dict per role is safe. Two rules of PRD 2.8 do compare recorded operator
identifiers to each other — the release signature against `reviewer_user_id` and
the CAPA decision against `opened_by_user_id` — which is why the QA reviewer and
the Qualified Person also carry explicit second and third identities.

A `ClientRepresentative` is different: its `X-User-ID` is the `id` of the acting
`ClientProject`, so its headers can only be built once a project exists.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLIENT_REPRESENTATIVE,
    ROLE_MICROBIOLOGY_ANALYST,
    ROLE_PRODUCTION_SUPERVISOR,
    ROLE_PROGRAM_MANAGER,
    ROLE_QA_REVIEWER,
    ROLE_QUALIFIED_PERSON,
)

# Primary operator identity per CMO-side role.
PM_USER_ID = "pm-001"
PS_USER_ID = "ps-001"
MICRO_USER_ID = "micro-001"
QA_USER_ID = "qa-001"
QP_USER_ID = "qp-001"

# Second and third QA identities, for the two segregation rules of PRD 2.8.
QA_SECOND_USER_ID = "qa-002"
QA_THIRD_USER_ID = "qa-003"
QP_SECOND_USER_ID = "qp-002"

PROGRAM_MANAGER: Dict[str, str] = build_user_headers(PM_USER_ID, ROLE_PROGRAM_MANAGER)
PRODUCTION_SUPERVISOR: Dict[str, str] = build_user_headers(
    PS_USER_ID, ROLE_PRODUCTION_SUPERVISOR
)
MICROBIOLOGY_ANALYST: Dict[str, str] = build_user_headers(
    MICRO_USER_ID, ROLE_MICROBIOLOGY_ANALYST
)
QA_REVIEWER: Dict[str, str] = build_user_headers(QA_USER_ID, ROLE_QA_REVIEWER)
QA_REVIEWER_SECOND: Dict[str, str] = build_user_headers(
    QA_SECOND_USER_ID, ROLE_QA_REVIEWER
)
QA_REVIEWER_THIRD: Dict[str, str] = build_user_headers(
    QA_THIRD_USER_ID, ROLE_QA_REVIEWER
)
QUALIFIED_PERSON: Dict[str, str] = build_user_headers(
    QP_USER_ID, ROLE_QUALIFIED_PERSON
)
QUALIFIED_PERSON_SECOND: Dict[str, str] = build_user_headers(
    QP_SECOND_USER_ID, ROLE_QUALIFIED_PERSON
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_manager_headers": PROGRAM_MANAGER,
    "production_supervisor_headers": PRODUCTION_SUPERVISOR,
    "microbiology_analyst_headers": MICROBIOLOGY_ANALYST,
    "qa_reviewer_headers": QA_REVIEWER,
    "qualified_person_headers": QUALIFIED_PERSON,
}

# Role name -> headers, for the sweeps that try every CMO-side role over one
# operation. A `ClientRepresentative` is absent by construction: its identity
# depends on a project row.
HEADERS_BY_CMO_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_MANAGER: PROGRAM_MANAGER,
    ROLE_PRODUCTION_SUPERVISOR: PRODUCTION_SUPERVISOR,
    ROLE_MICROBIOLOGY_ANALYST: MICROBIOLOGY_ANALYST,
    ROLE_QA_REVIEWER: QA_REVIEWER,
    ROLE_QUALIFIED_PERSON: QUALIFIED_PERSON,
}


def make_program_manager_headers(user_id: str) -> Dict[str, str]:
    """A `ProgramManager` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_PROGRAM_MANAGER)


def make_production_supervisor_headers(user_id: str) -> Dict[str, str]:
    """A `ProductionSupervisor` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_PRODUCTION_SUPERVISOR)


def make_microbiology_analyst_headers(user_id: str) -> Dict[str, str]:
    """A `MicrobiologyAnalyst` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_MICROBIOLOGY_ANALYST)


def make_qa_reviewer_headers(user_id: str) -> Dict[str, str]:
    """A `QaReviewer` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_QA_REVIEWER)


def make_qualified_person_headers(user_id: str) -> Dict[str, str]:
    """A `QualifiedPerson` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_QUALIFIED_PERSON)


def make_client_representative_headers(client_project_id: str) -> Dict[str, str]:
    """A `ClientRepresentative` whose `X-User-ID` is its own project's `id`."""
    return build_user_headers(client_project_id, ROLE_CLIENT_REPRESENTATIVE)


def role_headers(role: str, user_id: str = "op-001") -> Dict[str, str]:
    """Headers for an arbitrary role string, including undeclared ones."""
    return build_user_headers(user_id, role)


def headers_without_auth() -> Dict[str, str]:
    """A request carrying neither `X-User-ID` nor `X-User-Role`."""
    return {"Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """A request carrying `X-User-Role` but no `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """A request carrying `X-User-ID` but no `X-User-Role`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """A request whose `X-User-ID` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """A request whose `X-User-Role` is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}
