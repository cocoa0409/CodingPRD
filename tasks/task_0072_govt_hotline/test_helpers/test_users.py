"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformAdmin, HotlineOperator, Dispatcher, Supervisor, and SurveyAgent
  carry OPAQUE X-User-IDs. The server does not compare these to any
  persisted entity. Shared constants are safe for these roles.

  "When X-User-Role is PlatformAdmin, HotlineOperator, Dispatcher,
  Supervisor, or SurveyAgent, X-User-ID is an opaque operator identifier
  not tied to any persisted entity."

- DepartmentHandler is ENTITY-BACKED:
  "When X-User-Role is DepartmentHandler, X-User-ID is the id of the
  acting Handler; ownership checks on any resource that references a
  Handler (notably whether the caller is the LEAD assignment's
  handler_id when resuming or resolving) compare the resource's
  foreign-key field to X-User-ID."

  Every ownership-gated DepartmentHandler call MUST use
  make_department_handler_headers(handler['id']) — passing a shared
  fallback constant guarantees the ownership check fails for any real
  handler id, cascading 'Setup failed' into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding DepartmentHandler fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),
    "hotline_operator_headers": build_user_headers(
        "hotline-operator-001", "HotlineOperator",
    ),
    "hotline_operator_headers_alt": build_user_headers(
        "hotline-operator-002", "HotlineOperator",
    ),
    "dispatcher_headers": build_user_headers(
        "dispatcher-001", "Dispatcher",
    ),
    "dispatcher_headers_alt": build_user_headers(
        "dispatcher-002", "Dispatcher",
    ),
    "supervisor_headers": build_user_headers(
        "supervisor-001", "Supervisor",
    ),
    "survey_agent_headers": build_user_headers(
        "survey-agent-001", "SurveyAgent",
    ),
    # DepartmentHandler fallback — use ONLY for tests that do NOT exercise
    # ownership (missing-auth, wrong-role, missing-resource). Per PRD §2.1
    # the real X-User-ID must equal Handler.id for any ownership-gated
    # call; the per-instance builder below is the correct path in fixtures.
    "department_handler_headers": build_user_headers(
        "handler-fallback", "DepartmentHandler",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for the entity_backed DepartmentHandler.
# ---------------------------------------------------------------------------
def make_department_handler_headers(handler_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is DepartmentHandler, X-User-ID is the
    id of the acting Handler.' Pass the actual Handler.id returned by
    POST /handlers whenever the call is ownership-gated (notably pause,
    resume, resolve, accept, opinion, escalate)."""
    return build_user_headers(handler_id, "DepartmentHandler")


def make_platform_admin_headers(
    user_id: str = "platform-admin-001",
) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is opaque."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_hotline_operator_headers(
    user_id: str = "hotline-operator-001",
) -> Dict[str, str]:
    """PRD §2.1: HotlineOperator X-User-ID is opaque."""
    return build_user_headers(user_id, "HotlineOperator")


def make_dispatcher_headers(
    user_id: str = "dispatcher-001",
) -> Dict[str, str]:
    """PRD §2.1: Dispatcher X-User-ID is opaque."""
    return build_user_headers(user_id, "Dispatcher")


def make_supervisor_headers(
    user_id: str = "supervisor-001",
) -> Dict[str, str]:
    """PRD §2.1: Supervisor X-User-ID is opaque."""
    return build_user_headers(user_id, "Supervisor")


def make_survey_agent_headers(
    user_id: str = "survey-agent-001",
) -> Dict[str, str]:
    """PRD §2.1: SurveyAgent X-User-ID is opaque."""
    return build_user_headers(user_id, "SurveyAgent")


__all__ = [
    "TEST_USERS",
    "make_department_handler_headers",
    "make_platform_admin_headers",
    "make_hotline_operator_headers",
    "make_dispatcher_headers",
    "make_supervisor_headers",
    "make_survey_agent_headers",
]
