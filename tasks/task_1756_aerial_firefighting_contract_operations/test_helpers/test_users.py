"""Pre-built role headers for every role in the PRD.

Only Pilot is entity-backed (X-User-ID is the acting CrewMember's id); every
other role is an opaque operator identifier. Ownership-gated Pilot calls MUST
use make_pilot_headers() with the real CrewMember id — the shared constant is
a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "carrier_ops_headers": build_user_headers("ops_1", "CarrierOps"),
    "agency_dispatcher_headers": build_user_headers("ad_1", "AgencyDispatcher"),
    "carrier_finance_headers": build_user_headers("cf_1", "CarrierFinance"),
    "agency_finance_headers": build_user_headers("af_1", "AgencyFinance"),
    "carding_inspector_headers": build_user_headers("ci_1", "CardingInspector"),
    "system_admin_headers": build_user_headers("sys_1", "SystemAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "pilot_headers": build_user_headers("test-pilot-1", "Pilot"),
}


def make_carrier_ops_headers(user_id: str = "ops_1") -> dict:
    return build_user_headers(user_id, "CarrierOps")


def make_agency_dispatcher_headers(user_id: str = "ad_1") -> dict:
    return build_user_headers(user_id, "AgencyDispatcher")


def make_carrier_finance_headers(user_id: str = "cf_1") -> dict:
    return build_user_headers(user_id, "CarrierFinance")


def make_agency_finance_headers(user_id: str = "af_1") -> dict:
    return build_user_headers(user_id, "AgencyFinance")


def make_carding_inspector_headers(user_id: str = "ci_1") -> dict:
    return build_user_headers(user_id, "CardingInspector")


def make_system_admin_headers(user_id: str = "sys_1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_pilot_headers(crew_member_id: str) -> dict:
    """For Pilot (entity_backed:CrewMember). Pass the acting CrewMember.id
    whenever the call is ownership-gated (flight-log/launch/arrive/drop)."""
    return build_user_headers(crew_member_id, "Pilot")
