"""Pre-built role headers for every role in the PRD.

Six roles are opaque: X-User-ID is an operator identifier never compared to an
entity id. WELDER is entity-backed: X-User-ID must equal the acting Welder
record's id, so ownership-gated weld calls MUST use make_welder_headers with
the real welder id. Builders for the opaque roles exist so segregation-of-
duties tests can pin a specific X-User-ID per call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "fabricator_admin_headers": build_user_headers("admin-1", "FABRICATOR_ADMIN"),
    "detailer_headers": build_user_headers("det-1", "DETAILER"),
    "eor_headers": build_user_headers("eor-1", "EOR"),
    "foreman_headers": build_user_headers("foreman-1", "FOREMAN"),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only; ownership-gated calls must use make_welder_headers(id).
    "welder_headers": build_user_headers("welder-1", "WELDER"),
    "qc_inspector_headers": build_user_headers("qc-1", "QC_INSPECTOR"),
    "gc_pm_headers": build_user_headers("gcpm-1", "GC_PM"),
}


def make_fabricator_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FABRICATOR_ADMIN")


def make_detailer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DETAILER")


def make_eor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EOR")


def make_foreman_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FOREMAN")


def make_welder_headers(user_id: str) -> dict:
    """For WELDER (entity-backed): pass the actual Welder.id as user_id
    whenever the call is ownership-gated (POST /welds, weld repair)."""
    return build_user_headers(user_id, "WELDER")


def make_qc_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QC_INSPECTOR")


def make_gc_pm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GC_PM")
