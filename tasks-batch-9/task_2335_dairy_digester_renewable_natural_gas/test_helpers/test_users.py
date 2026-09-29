"""Pre-built role headers for every role named in the PRD (§2.1).

The platform recognises exactly seven roles. Six of them are opaque — the
``X-User-ID`` is any stable operator identifier. ``DairyPartner`` is different:
its ``X-User-ID`` is the acting ``Dairy.id``, so ownership-gated calls MUST use
``make_dairy_partner_headers(dairy["id"])``.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Canonical user identifiers used across fixtures.
USER_ADMIN = "u-admin"
USER_OPERATOR = "u-ops"
USER_SCHEDULER = "u-sched"
USER_PROGRAM = "u-program"
USER_VERIFIER = "u-verifier"
USER_FINANCE_A = "u-fin-a"
USER_FINANCE_B = "u-fin-b"
USER_DUAL = "u-dual"

# Shared constants — safe for opaque roles and for calls that do not exercise
# dairy ownership.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(USER_ADMIN, "PlatformAdmin"),
    "project_operator_headers": build_user_headers(USER_OPERATOR, "ProjectOperator"),
    "pipeline_scheduler_headers": build_user_headers(USER_SCHEDULER, "PipelineScheduler"),
    "program_administrator_headers": build_user_headers(USER_PROGRAM, "ProgramAdministrator"),
    "credit_verifier_headers": build_user_headers(USER_VERIFIER, "CreditVerifier"),
    "finance_controller_headers": build_user_headers(USER_FINANCE_A, "FinanceController"),
    "finance_controller_b_headers": build_user_headers(USER_FINANCE_B, "FinanceController"),
    # DairyPartner is entity backed; this shared constant is only a fallback for
    # tests that never reach the ownership check.
    "dairy_partner_headers": build_user_headers("test-dairy-partner-1", "DairyPartner"),
}


def make_platform_admin_headers(user_id: str = USER_ADMIN) -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_project_operator_headers(user_id: str = USER_OPERATOR) -> Dict[str, str]:
    return build_user_headers(user_id, "ProjectOperator")


def make_pipeline_scheduler_headers(user_id: str = USER_SCHEDULER) -> Dict[str, str]:
    return build_user_headers(user_id, "PipelineScheduler")


def make_program_administrator_headers(user_id: str = USER_PROGRAM) -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramAdministrator")


def make_credit_verifier_headers(user_id: str = USER_VERIFIER) -> Dict[str, str]:
    return build_user_headers(user_id, "CreditVerifier")


def make_finance_controller_headers(user_id: str = USER_FINANCE_A) -> Dict[str, str]:
    return build_user_headers(user_id, "FinanceController")


def make_dairy_partner_headers(dairy_id: str) -> Dict[str, str]:
    """Headers for DairyPartner. ``dairy_id`` must be the acting ``Dairy.id``:
    the PRD reads ``X-User-ID`` as the dairy the caller speaks for."""
    return build_user_headers(dairy_id, "DairyPartner")


def headers_without_role(user_id: str = USER_ADMIN) -> Dict[str, str]:
    """A request that omits ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user(role: str = "PlatformAdmin") -> Dict[str, str]:
    """A request that omits ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unrecognised_role(
    user_id: str = USER_ADMIN, role: str = "LenderAgent"
) -> Dict[str, str]:
    """A request presenting a role string the platform does not recognise."""
    return build_user_headers(user_id, role)
