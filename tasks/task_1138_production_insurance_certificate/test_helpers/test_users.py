"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles use opaque operator identifiers: `X-User-ID` is not tied to
any persisted entity, so shared constants are the canonical form. The single
place `X-User-ID` values are compared against each other is the
segregation-of-duties rule on claim settlement — tests for that rule build
matching-identifier headers explicitly via build_user_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "broker_headers": build_user_headers("broker-001", "BrokerAgent"),
    "production_manager_headers": build_user_headers("pm-001", "ProductionManager"),
    "underwriter_headers": build_user_headers("uw-001", "UnderwriterAgent"),
    "claims_adjuster_headers": build_user_headers("adj-001", "ClaimsAdjuster"),
    "clearance_counsel_headers": build_user_headers("cc-001", "ClearanceCounsel"),
    "surety_underwriter_headers": build_user_headers("su-001", "SuretyUnderwriter"),
    "external_auditor_headers": build_user_headers("aud-001", "ExternalAuditor"),
    "platform_operator_headers": build_user_headers("op-001", "PlatformOperator"),
}
