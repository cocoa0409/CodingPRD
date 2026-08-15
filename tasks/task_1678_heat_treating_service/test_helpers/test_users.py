"""Pre-built role headers for every role in the PRD (§2.1).

Six roles use an opaque identity model — `X-User-ID` is never compared to any
entity's `id` — so shared constants are canonical. Two QualityEngineer
identities exist because the disposition segregation-of-duties rule compares
the decider's `X-User-ID` against the inspection test's `recorded_by_user_id`
(PRD §3.7).

The Customer role is entity-backed by CustomerAccount: any ownership-gated
call MUST use `make_customer_headers(customer["id"])` with the real account
id — the shared constant is only for probes where no owned resource exists.
"""
from prd_bench_local_runner.testing import build_user_headers

# Named user ids referenced by the segregation-of-duties rule (PRD §3.7).
USER_CUSTOMER_SERVICE_REP = "csr-1"
USER_SHOP_SCHEDULER = "sched-1"
USER_FURNACE_OPERATOR = "op-1"
USER_CALIBRATION_TECH = "cal-1"
USER_QUALITY_ENGINEER = "qe-1"
USER_QUALITY_ENGINEER_2 = "qe-2"
USER_NADCAP_AUDITOR = "aud-1"

TEST_USERS = {
    "customer_service_rep": build_user_headers(
        USER_CUSTOMER_SERVICE_REP, "CustomerServiceRep"
    ),
    "shop_scheduler": build_user_headers(USER_SHOP_SCHEDULER, "ShopScheduler"),
    "furnace_operator": build_user_headers(USER_FURNACE_OPERATOR, "FurnaceOperator"),
    "calibration_tech": build_user_headers(USER_CALIBRATION_TECH, "CalibrationTech"),
    "quality_engineer": build_user_headers(USER_QUALITY_ENGINEER, "QualityEngineer"),
    "quality_engineer_2": build_user_headers(
        USER_QUALITY_ENGINEER_2, "QualityEngineer"
    ),
    "nadcap_auditor": build_user_headers(USER_NADCAP_AUDITOR, "NadcapAuditor"),
    # Fallback for non-ownership probes only; ownership-gated calls must use
    # make_customer_headers() with the real CustomerAccount id.
    "customer": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed by CustomerAccount). Pass the actual
    CustomerAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_quality_engineer_headers(user_id: str) -> dict:
    """Ad-hoc QualityEngineer identity (e.g. a decider colliding with the
    inspection recorder for the segregation-of-duties check)."""
    return build_user_headers(user_id, "QualityEngineer")
