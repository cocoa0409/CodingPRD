"""Pre-built role headers for every role in the PRD.

All six roles are opaque: X-User-ID is an operator identifier that is never
compared to any entity's id (PRD §2.1). Distinct user ids still matter for
segregation-of-duties (PRD §2.11): the X-User-ID resolving an audit must
differ from the X-User-ID that submitted the filing under audit. Use the
make_*_headers builders to control the operator id in those tests.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for every test whose outcome does not depend on a
# specific operator identity (all roles here are opaque).
TEST_USERS = {
    "plan_administrator_headers": build_user_headers(
        "test-admin-1", "PlanAdministrator"),
    "claims_examiner_headers": build_user_headers(
        "test-examiner-1", "ClaimsExaminer"),
    "stop_loss_analyst_headers": build_user_headers(
        "test-analyst-1", "StopLossAnalyst"),
    "carrier_reviewer_headers": build_user_headers(
        "test-reviewer-1", "CarrierReviewer"),
    "plan_accountant_headers": build_user_headers(
        "test-accountant-1", "PlanAccountant"),
    "carrier_auditor_headers": build_user_headers(
        "test-auditor-1", "CarrierAuditor"),
}


# Per-instance builders — used when the operator id itself is load-bearing
# (segregation-of-duties comparisons on filing submission vs audit resolve).

def make_plan_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanAdministrator")


def make_claims_examiner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsExaminer")


def make_stop_loss_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StopLossAnalyst")


def make_carrier_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CarrierReviewer")


def make_plan_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanAccountant")


def make_carrier_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CarrierAuditor")


# Headers with no X-User-Role / X-User-ID at all -> ERR_UNAUTHENTICATED.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
