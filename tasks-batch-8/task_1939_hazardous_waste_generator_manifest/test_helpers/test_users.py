"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (EHSManager, WasteCoordinator, ComplianceAuditor) may use the shared
constants anywhere. Entity-backed roles (TransporterAgent, TSDFAgent) MUST be built
with the acting partner's id via the per-instance builders whenever the call is
ownership-gated (sign-transporter / receive / raise-discrepancy).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ehs_manager_headers": build_user_headers("mgr-1", "EHSManager"),
    "waste_coordinator_headers": build_user_headers("wc-1", "WasteCoordinator"),
    "compliance_auditor_headers": build_user_headers("aud-1", "ComplianceAuditor"),
    # Entity-backed roles: shared constants are only for non-ownership reads.
    "transporter_agent_headers": build_user_headers("test-transporter-1", "TransporterAgent"),
    "tsdf_agent_headers": build_user_headers("test-tsdf-1", "TSDFAgent"),
}


def make_ehs_manager_headers(user_id: str) -> dict:
    """EHSManager (opaque identity)."""
    return build_user_headers(user_id, "EHSManager")


def make_waste_coordinator_headers(user_id: str) -> dict:
    """WasteCoordinator (opaque identity)."""
    return build_user_headers(user_id, "WasteCoordinator")


def make_compliance_auditor_headers(user_id: str) -> dict:
    """ComplianceAuditor (opaque identity)."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_transporter_agent_headers(user_id: str) -> dict:
    """TransporterAgent (entity_backed:WastePartner). Pass the transporter partner's
    id whenever the call is ownership-gated (manifest sign-transporter)."""
    return build_user_headers(user_id, "TransporterAgent")


def make_tsdf_agent_headers(user_id: str) -> dict:
    """TSDFAgent (entity_backed:WastePartner). Pass the TSDF partner's id whenever
    the call is ownership-gated (manifest receive / raise-discrepancy)."""
    return build_user_headers(user_id, "TSDFAgent")


# Short aliases used throughout fixtures/tests
def ehs_headers(user_id: str = "mgr-1") -> dict:
    return make_ehs_manager_headers(user_id)


def wc_headers(user_id: str = "wc-1") -> dict:
    return make_waste_coordinator_headers(user_id)


def ca_headers(user_id: str = "aud-1") -> dict:
    return make_compliance_auditor_headers(user_id)
