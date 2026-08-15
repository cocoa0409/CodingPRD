"""Pre-built role headers for every role in the PRD (§2.1).

Identity partition (PRD §2.1): GCProjectManager / GCInspector / OwnerRep carry an
opaque X-User-ID never compared to any entity id; SubcontractorRep is
entity-backed — its X-User-ID must equal the acting TradePackage's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "gc_pm_headers": build_user_headers("pm-1", "GCProjectManager"),
    "gc_inspector_headers": build_user_headers("insp-1", "GCInspector"),
    "owner_rep_headers": build_user_headers("owner-1", "OwnerRep"),
    # Fallback for non-ownership calls only (e.g. plain GETs). Ownership-gated
    # calls MUST use make_subcontractor_headers(<trade_package.id>).
    "subcontractor_headers": build_user_headers("test-subcontractor-1", "SubcontractorRep"),
}


def make_gc_pm_headers(user_id: str) -> dict:
    """GCProjectManager with a specific opaque user id (needed for sign-off duty tests)."""
    return build_user_headers(user_id, "GCProjectManager")


def make_gc_inspector_headers(user_id: str) -> dict:
    """GCInspector with a specific opaque user id (needed for sign-off duty tests)."""
    return build_user_headers(user_id, "GCInspector")


def make_owner_rep_headers(user_id: str) -> dict:
    """OwnerRep with a specific opaque user id."""
    return build_user_headers(user_id, "OwnerRep")


def make_subcontractor_headers(trade_package_id: str) -> dict:
    """SubcontractorRep is entity-backed: pass the actual TradePackage.id as user_id
    whenever the call is ownership-gated (mark-ready, document submit, waiver submit)."""
    return build_user_headers(trade_package_id, "SubcontractorRep")
