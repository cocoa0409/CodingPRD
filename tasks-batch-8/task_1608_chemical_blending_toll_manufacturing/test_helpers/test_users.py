"""Pre-built role headers for every role in the PRD (§2.1).

All roles in this API use opaque operator identifiers: ``X-User-ID`` is never
compared to any entity's ``id`` (PRD §2.1), so shared per-role constants are
safe everywhere. The only place two ``X-User-ID`` values are compared to each
other is the cleaning-validation segregation-of-duties rule (PRD §3.5); for
those tests use ``make_operator_headers`` / ``make_validator_headers`` with an
explicit user id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "quality_manager_headers": build_user_headers("qm-user-1", "QualityManager"),
    "batch_scheduler_headers": build_user_headers("sched-user-1", "BatchScheduler"),
    "tank_operator_headers": build_user_headers("tankop-user-1", "TankOperator"),
    "qa_validator_headers": build_user_headers("qa-user-1", "QAValidator"),
    "sds_author_headers": build_user_headers("sds-user-1", "SDSAuthor"),
    "shipping_clerk_headers": build_user_headers("ship-user-1", "ShippingClerk"),
}


def make_quality_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityManager")


def make_batch_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BatchScheduler")


def make_operator_headers(user_id: str) -> dict:
    """TankOperator headers with an explicit user id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "TankOperator")


def make_validator_headers(user_id: str) -> dict:
    """QAValidator headers with an explicit user id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "QAValidator")


def make_sds_author_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SDSAuthor")


def make_shipping_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShippingClerk")
