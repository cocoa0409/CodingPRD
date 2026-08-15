"""Pre-built role headers for every role in the PRD (§2.1).

All roles are opaque-identity: ``X-User-ID`` is an operator identifier recorded on
resources for attribution and ownership checks. The shared constants below use the
stable operator ids used throughout the test suite, so ownership-gated calls work
whenever the model was registered with the matching owner headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used across the suite.
U_OWN_A = "u_own_a"
U_OWN_B = "u_own_b"
U_VAL = "u_val"
U_VAL_B = "u_val_b"
U_CRO = "u_cro"
U_REP = "u_rep"
U_ADMIN = "u_admin"

TEST_USERS = {
    "model_owner_a_headers": build_user_headers(U_OWN_A, "ModelOwner"),
    "model_owner_b_headers": build_user_headers(U_OWN_B, "ModelOwner"),
    "model_validator_headers": build_user_headers(U_VAL, "ModelValidator"),
    "model_validator_b_headers": build_user_headers(U_VAL_B, "ModelValidator"),
    "risk_officer_headers": build_user_headers(U_CRO, "ModelRiskOfficer"),
    "reporter_headers": build_user_headers(U_REP, "RegulatoryReporter"),
    "platform_admin_headers": build_user_headers(U_ADMIN, "PlatformAdmin"),
}


def make_owner_headers(user_id: str) -> dict:
    """ModelOwner headers for a specific operator id (ownership checks compare
    the caller's X-User-ID against the model's recorded owner_user_id)."""
    return build_user_headers(user_id, "ModelOwner")


def make_validator_headers(user_id: str) -> dict:
    """ModelValidator headers for a specific operator id (validation must be
    independent of the model's owner)."""
    return build_user_headers(user_id, "ModelValidator")


def make_risk_officer_headers(user_id: str) -> dict:
    """ModelRiskOfficer headers for a specific operator id (documentation
    decisions are barred when the decider is the package's submitter)."""
    return build_user_headers(user_id, "ModelRiskOfficer")


def make_reporter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryReporter")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
