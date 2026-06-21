"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  - `EstatePlanner` identity is opaque.
  - `Executor` identity is entity_backed:Executor — X-User-ID must equal the
    acting Executor row's `id`. Use `make_executor_headers(executor_id)`.
  - `Judge` identity is opaque.
  - `Beneficiary` identity is entity_backed:BeneficiaryDesignation — X-User-ID
    must equal the acting BeneficiaryDesignation row's `id`. Use
    `make_beneficiary_headers(designation_id)`.
  - `Registrar` identity is opaque.
  - `Creditor` identity is opaque.
  - `PlatformAdmin` identity is opaque.

Shared constants under `TEST_USERS` are safe for opaque roles and for tests
not exercising ownership. For ownership-gated calls on Executor / Beneficiary,
use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and non-ownership tests.
TEST_USERS = {
    "planner_headers": build_user_headers("test-planner-1", "EstatePlanner"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "creditor_headers": build_user_headers("test-creditor-1", "Creditor"),
    "platform_admin_headers": build_user_headers(
        "test-platform-admin-1", "PlatformAdmin",
    ),
    # Shared fallback for non-ownership tests; for ownership-gated calls use
    # the per-instance builders.
    "executor_headers": build_user_headers("test-executor-fallback", "Executor"),
    "beneficiary_headers": build_user_headers(
        "test-beneficiary-fallback", "Beneficiary",
    ),
}


# Per-instance builders ─────────────────────────────────────────────────────

def make_planner_headers(opaque_id: str = "test-planner-1") -> dict:
    """For EstatePlanner role (identity: opaque)."""
    return build_user_headers(opaque_id, "EstatePlanner")


def make_judge_headers(opaque_id: str = "test-judge-1") -> dict:
    """For Judge role (identity: opaque)."""
    return build_user_headers(opaque_id, "Judge")


def make_registrar_headers(opaque_id: str = "test-registrar-1") -> dict:
    """For Registrar role (identity: opaque)."""
    return build_user_headers(opaque_id, "Registrar")


def make_creditor_headers(opaque_id: str = "test-creditor-1") -> dict:
    """For Creditor role (identity: opaque)."""
    return build_user_headers(opaque_id, "Creditor")


def make_platform_admin_headers(opaque_id: str = "test-platform-admin-1") -> dict:
    """For PlatformAdmin role (identity: opaque)."""
    return build_user_headers(opaque_id, "PlatformAdmin")


def make_executor_headers(executor_id: str) -> dict:
    """For Executor role (entity_backed:Executor). Pass the actual Executor.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(executor_id, "Executor")


def make_beneficiary_headers(designation_id: str) -> dict:
    """For Beneficiary role (entity_backed:BeneficiaryDesignation). Pass the
    actual BeneficiaryDesignation.id as user_id whenever the call is
    ownership-gated."""
    return build_user_headers(designation_id, "Beneficiary")
