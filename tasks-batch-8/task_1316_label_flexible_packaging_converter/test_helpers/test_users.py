"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque: PRD §2.1 states X-User-ID "is an opaque operator
identifier not tied to any persisted entity" and "no ownership check is
derived from it". Shared constants are therefore the canonical form; the
per-instance builders exist for convenience and symmetry only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "prepress_operator_headers": build_user_headers("test-prepress-1",
                                                    "PrepressOperator"),
    "press_operator_headers": build_user_headers("test-press-1",
                                                 "PressOperator"),
    "quality_manager_headers": build_user_headers("test-quality-1",
                                                  "QualityManager"),
}


def make_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Estimator")


def make_prepress_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrepressOperator")


def make_press_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PressOperator")


def make_quality_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityManager")
