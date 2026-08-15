"""Pre-built role headers for every role in the PRD (§2.1).

`VDCManager`, `BIMCoordinator`, `LeadEngineer`, and `FacilitiesManager` are opaque
roles: their `X-User-ID` is not tied to any persisted entity, so shared constants
are canonical.

`TradeModelAuthor` and `FabricationLead` are entity-backed: `X-User-ID` must equal
the acting TradePartner's `id`. The shared constants for these two roles are only
a fallback for tests that never pass an ownership check; ownership-gated calls
MUST use `make_trade_model_author_headers(partner_id)` /
`make_fabrication_lead_headers(partner_id)` with the real partner id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "vdc_manager_headers": build_user_headers("vdc-mgr-1", "VDCManager"),
    "bim_coordinator_headers": build_user_headers("coord-1", "BIMCoordinator"),
    "lead_engineer_headers": build_user_headers("eng-1", "LeadEngineer"),
    "facilities_manager_headers": build_user_headers("fm-1", "FacilitiesManager"),
    # Entity-backed roles — shared constants are fallbacks for non-ownership
    # tests only (e.g., 400/404 probes); never use for ownership-gated calls.
    "trade_model_author_headers": build_user_headers("test-author-1", "TradeModelAuthor"),
    "fabrication_lead_headers": build_user_headers("test-fablead-1", "FabricationLead"),
}


def make_vdc_manager_headers(user_id: str) -> dict:
    """Opaque role: any operator identifier is acceptable."""
    return build_user_headers(user_id, "VDCManager")


def make_bim_coordinator_headers(user_id: str) -> dict:
    """Opaque role. Use distinct ids (coord-1 vs coord-2) for the verify SoD."""
    return build_user_headers(user_id, "BIMCoordinator")


def make_lead_engineer_headers(user_id: str) -> dict:
    """Opaque role. Must differ from a pinned model's submitted_by_user_id."""
    return build_user_headers(user_id, "LeadEngineer")


def make_facilities_manager_headers(user_id: str) -> dict:
    """Opaque role: any operator identifier is acceptable."""
    return build_user_headers(user_id, "FacilitiesManager")


def make_trade_model_author_headers(user_id: str) -> dict:
    """Entity-backed role: user_id MUST be the acting TradePartner's id."""
    return build_user_headers(user_id, "TradeModelAuthor")


def make_fabrication_lead_headers(user_id: str) -> dict:
    """Entity-backed role: user_id MUST be the requesting TradePartner's id."""
    return build_user_headers(user_id, "FabricationLead")
