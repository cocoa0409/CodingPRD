"""Pre-built role headers for the five PRD roles (§2.1).

All five roles have identity: opaque (PRD §2.1 — "X-User-ID is an opaque operator
identifier that is not the `id` of any persisted entity"). Ownership is enforced
by comparing X-User-ID against a resource's owner_user_id / proposer_user_id /
created_by — so the builders below take an explicit user_id, and the shared
constants pick stable test identifiers that the fixture layer threads through.
"""
from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Stable user IDs used by the test suite.
# When a test creates an entity whose owner_user_id / proposer_user_id /
# created_by must match the caller, it threads these IDs through factories
# and headers together (e.g., a Risk created with owner_user_id="user_owner_1"
# is later transitioned via make_risk_owner_headers("user_owner_1")).
# ---------------------------------------------------------------------------

USER_RISK_OWNER = "user_owner_1"
USER_RISK_OWNER_2 = "user_owner_2"
USER_RISK_MANAGER = "user_rm_1"
USER_RISK_MANAGER_2 = "user_rm_2"
USER_CONTROL_OWNER = "user_co_1"
USER_BOARD_REPORTER = "user_br_1"
USER_INTERNAL_AUDITOR = "user_aud_1"
# A person acting with both duties in sequence (SoD tests)
USER_DUAL = "user_dual"


# Shared constants — safe for opaque roles and non-ownership-gated reads.
# For ownership-gated calls, build headers with the user_id matching the
# entity's recorded owner_user_id / proposer_user_id / created_by.
TEST_USERS = {
    "risk_owner_headers": build_user_headers(USER_RISK_OWNER, "RiskOwner"),
    "risk_owner_2_headers": build_user_headers(USER_RISK_OWNER_2, "RiskOwner"),
    "risk_manager_headers": build_user_headers(USER_RISK_MANAGER, "RiskManager"),
    "risk_manager_2_headers": build_user_headers(USER_RISK_MANAGER_2, "RiskManager"),
    "control_owner_headers": build_user_headers(USER_CONTROL_OWNER, "ControlOwner"),
    "board_reporter_headers": build_user_headers(USER_BOARD_REPORTER, "BoardReporter"),
    "internal_auditor_headers": build_user_headers(USER_INTERNAL_AUDITOR, "InternalAuditor"),
    "dual_headers_owner": build_user_headers(USER_DUAL, "RiskOwner"),
    "dual_headers_manager": build_user_headers(USER_DUAL, "RiskManager"),
}


# Per-instance builders — pass the user_id recorded on the entity under test.
def make_risk_owner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RiskOwner")


def make_risk_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RiskManager")


def make_control_owner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ControlOwner")


def make_board_reporter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardReporter")


def make_internal_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InternalAuditor")
