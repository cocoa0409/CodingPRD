"""Pre-built role headers for every role in the PRD.

Every request must carry X-User-ID and X-User-Role.  When X-User-Role is
StationOperator, X-User-ID is the id of the acting Station — so ownership-gated
calls must use ``make_station_operator_headers(station["id"])`` rather than the
shared constant below.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Shared constants ─────────────────────────────────────────────────────
# Safe for the seven roles whose identity is opaque, and for StationOperator
# only in tests that never reach an ownership check (missing-header,
# role-denial and not-found scenarios).

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers("PA-1", "PlatformAdmin"),
    "platform_admin_2_headers": build_user_headers("PA-2", "PlatformAdmin"),
    # entity_backed:Station — shared constant is a fallback for non-ownership tests only.
    "station_operator_headers": build_user_headers("SO-1", "StationOperator"),
    "production_engineer_headers": build_user_headers("PE-1", "ProductionEngineer"),
    "quality_analyst_headers": build_user_headers("QA-1", "QualityAnalyst"),
    "quality_analyst_2_headers": build_user_headers("QA-2", "QualityAnalyst"),
    "safety_officer_headers": build_user_headers("SO-1", "SafetyOfficer"),
    "safety_officer_2_headers": build_user_headers("SO-2", "SafetyOfficer"),
    "compliance_admin_headers": build_user_headers("CA-1", "ComplianceAdmin"),
    "compliance_admin_2_headers": build_user_headers("CA-2", "ComplianceAdmin"),
    "logistics_dispatcher_headers": build_user_headers("LD-1", "LogisticsDispatcher"),
    "program_auditor_headers": build_user_headers("PGA-1", "ProgramAuditor"),
    "program_auditor_2_headers": build_user_headers("PGA-2", "ProgramAuditor"),
}


# ─── Per-instance builders ────────────────────────────────────────────────


def make_station_operator_headers(station_id: str) -> Dict[str, str]:
    """Headers for the StationOperator bound to ``station_id``.

    The acting person is identified by the station's own id, which is what the
    station-ownership check compares against.
    """
    return build_user_headers(station_id, "StationOperator")


def make_platform_admin_headers(user_id: str = "PA-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_production_engineer_headers(user_id: str = "PE-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ProductionEngineer")


def make_quality_analyst_headers(user_id: str = "QA-1") -> Dict[str, str]:
    return build_user_headers(user_id, "QualityAnalyst")


def make_safety_officer_headers(user_id: str = "SO-1") -> Dict[str, str]:
    return build_user_headers(user_id, "SafetyOfficer")


def make_compliance_admin_headers(user_id: str = "CA-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceAdmin")


def make_logistics_dispatcher_headers(user_id: str = "LD-1") -> Dict[str, str]:
    return build_user_headers(user_id, "LogisticsDispatcher")


def make_program_auditor_headers(user_id: str = "PGA-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramAuditor")
