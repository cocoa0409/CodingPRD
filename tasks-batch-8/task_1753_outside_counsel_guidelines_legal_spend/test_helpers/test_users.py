"""Pre-built role headers for every role in the PRD (§2.1).

LegalOpsReviewer is an opaque role: the server does not compare its X-User-ID
against any resource id, so a shared constant is canonical.

PanelFirmUser is entity-backed: its X-User-ID must equal the acting
PanelFirm.id for ownership-gated calls (acknowledge, engage, rate-card and
invoice writes, appeals, accruals, voids). Use make_panel_firm_headers with
the real firm id for those calls; the shared constant is only a fallback for
tests that never exercise ownership (e.g. 403 role-denial probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "legal_ops_headers": build_user_headers("test-legal-ops-1", "LegalOpsReviewer"),
    # Entity-backed role: fallback for non-ownership tests only.
    "panel_firm_headers": build_user_headers("test-panel-firm-1", "PanelFirmUser"),
}


def make_panel_firm_headers(user_id: str) -> dict:
    """For PanelFirmUser (entity-backed by PanelFirm). Pass the actual
    PanelFirm.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PanelFirmUser")
