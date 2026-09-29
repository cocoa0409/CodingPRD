"""Acting principals and header builders.

PRD 2.1 splits the five roles into two families.  `QualityManager`,
`Supervisor` and `ComplianceAuditor` are opaque: "`X-User-ID` is an opaque
operator identifier not tied to any persisted entity", so a fixed constant is
correct for them.  `QualityEvaluator` and `Agent` are entity-backed: "When
`X-User-Role` is `QualityEvaluator`, `X-User-ID` is the `id` of the acting
`Evaluator`" and "When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the
acting `Agent`".  Those two must therefore always be built from a freshly
created row's id via `make_evaluator_headers` / `make_agent_headers`; the
`TEST_USERS` entries for them are placeholders used only to exercise the
not-the-owner and unauthenticated paths.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    "quality_manager": {
        "user_id": "qm-operator-001",
        "role": "QualityManager",
    },
    "supervisor": {
        "user_id": "sup-operator-001",
        "role": "Supervisor",
    },
    "compliance_auditor": {
        "user_id": "aud-operator-001",
        "role": "ComplianceAuditor",
    },
    # Entity-backed placeholders: only for ownership-violation and
    # authentication tests, never for a call that must succeed.
    "quality_evaluator": {
        "user_id": "00000000-0000-4000-8000-0000000000e1",
        "role": "QualityEvaluator",
    },
    "agent": {
        "user_id": "00000000-0000-4000-8000-0000000000a1",
        "role": "Agent",
    },
}


def make_quality_manager_headers(user_id: str = None) -> Dict[str, str]:
    """Headers for the opaque QualityManager operator."""
    return build_user_headers(
        user_id or TEST_USERS["quality_manager"]["user_id"], "QualityManager"
    )


def make_supervisor_headers(user_id: str = None) -> Dict[str, str]:
    """Headers for the opaque Supervisor operator."""
    return build_user_headers(
        user_id or TEST_USERS["supervisor"]["user_id"], "Supervisor"
    )


def make_compliance_auditor_headers(user_id: str = None) -> Dict[str, str]:
    """Headers for the opaque ComplianceAuditor operator."""
    return build_user_headers(
        user_id or TEST_USERS["compliance_auditor"]["user_id"], "ComplianceAuditor"
    )


def make_evaluator_headers(evaluator_id: str) -> Dict[str, str]:
    """Headers for an entity-backed QualityEvaluator.

    `evaluator_id` must be the `id` of a stored Evaluator row, because
    ownership checks compare the resource's evaluator reference to
    `X-User-ID`.
    """
    return build_user_headers(evaluator_id, "QualityEvaluator")


def make_agent_headers(agent_id: str) -> Dict[str, str]:
    """Headers for an entity-backed Agent.

    `agent_id` must be the `id` of a stored Agent row, because an agent may
    only act on a resource whose `agent_id` equals `X-User-ID`.
    """
    return build_user_headers(agent_id, "Agent")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, including undeclared role names."""
    return build_user_headers(user_id, role)


# Header sets keyed by role name, for parametrised authorisation sweeps over
# the opaque roles.
OPAQUE_ROLE_HEADERS = {
    "QualityManager": make_quality_manager_headers,
    "Supervisor": make_supervisor_headers,
    "ComplianceAuditor": make_compliance_auditor_headers,
}
