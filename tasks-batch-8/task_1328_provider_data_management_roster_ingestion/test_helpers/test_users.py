"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use opaque X-User-ID values that the server never compares to
any entity id, so shared constants are the canonical form. Per-user builders
exist for segregation-of-duties scenarios (§2.8), where the SAME or a
DIFFERENT opaque user id must be chosen deliberately.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    CONTACT_USER_1,
    DIST_USER_1,
    INTAKE_USER_1,
    INTAKE_USER_2,
    STEWARD_USER_1,
)

TEST_USERS = {
    "data_steward_headers": build_user_headers(STEWARD_USER_1, "DataSteward"),
    "intake_operator_headers": build_user_headers(INTAKE_USER_1, "IntakeOperator"),
    "intake_operator_2_headers": build_user_headers(INTAKE_USER_2, "IntakeOperator"),
    "distribution_operator_headers": build_user_headers(DIST_USER_1, "DistributionOperator"),
    "provider_contact_headers": build_user_headers(CONTACT_USER_1, "ProviderContact"),
}


def make_data_steward_headers(user_id: str) -> dict:
    """DataSteward headers with a caller-chosen opaque user id."""
    return build_user_headers(user_id, "DataSteward")


def make_intake_operator_headers(user_id: str) -> dict:
    """IntakeOperator headers with a caller-chosen opaque user id (SoD tests)."""
    return build_user_headers(user_id, "IntakeOperator")


def make_distribution_operator_headers(user_id: str) -> dict:
    """DistributionOperator headers with a caller-chosen opaque user id."""
    return build_user_headers(user_id, "DistributionOperator")


def make_provider_contact_headers(user_id: str) -> dict:
    """ProviderContact headers with a caller-chosen opaque user id."""
    return build_user_headers(user_id, "ProviderContact")


def make_headers_without_role(user_id: str = "anon") -> dict:
    """Headers that omit X-User-Role entirely (PRD §2.1 unauthenticated path)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
