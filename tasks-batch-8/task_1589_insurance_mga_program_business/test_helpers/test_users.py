"""Pre-built role headers for every role in the PRD.

Entity-backed roles (CarrierUnderwriter -> Carrier, TPAAdjuster -> TPA) must be
built per instance via the make_* helpers below whenever the call is
ownership-gated: the X-User-ID must equal the actual entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "mga_underwriter_headers": build_user_headers("test-mga-uw-1", "MGAUnderwriter"),
    "mga_finance_headers": build_user_headers("test-mga-fin-1", "MGAFinance"),
    "carrier_auditor_headers": build_user_headers("test-carrier-aud-1", "CarrierAuditor"),
    # Entity-backed roles: fallback constants ONLY for non-ownership tests.
    "carrier_underwriter_headers": build_user_headers("test-carrier-uw-1", "CarrierUnderwriter"),
    "tpa_adjuster_headers": build_user_headers("test-tpa-adj-1", "TPAAdjuster"),
}


def make_carrier_underwriter_headers(carrier_id: str) -> dict:
    """CarrierUnderwriter is entity_backed by Carrier: pass the real Carrier.id
    whenever the call is ownership-gated (program lifecycle, filings approval,
    capacity, appointments, bordereau disposition, claim decide/close)."""
    return build_user_headers(carrier_id, "CarrierUnderwriter")


def make_tpa_adjuster_headers(tpa_id: str) -> dict:
    """TPAAdjuster is entity_backed by TPA: pass the real TPA.id whenever the
    call is ownership-gated (claim start-review/set-reserve/refer/approve/deny/
    pay/resume-review)."""
    return build_user_headers(tpa_id, "TPAAdjuster")
