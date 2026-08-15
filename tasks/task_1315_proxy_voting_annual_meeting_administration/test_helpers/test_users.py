"""Pre-built role headers for every role in the PRD (§2.1).

Shareholder is entity-backed: its X-User-ID must be the ShareholderAccount id
whenever the call is ownership-gated (own votes, own questions, own account).
Use make_shareholder_headers(account_id) in those cases; the shared constant is
only for tests that never exercise ownership (e.g. role-denial on create).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "proxy_admin_headers": build_user_headers("proxy-admin-1", "ProxyAdministrator"),
    "transfer_agent_headers": build_user_headers("transfer-agent-1", "TransferAgent"),
    "broker_headers": build_user_headers("broker-1", "Broker"),
    "inspector_headers": build_user_headers("insp-1", "InspectorOfElection"),
    # Second inspector identity: certification signing requires the signer to
    # differ from the draft creator (segregation of duties, PRD §3.8).
    "inspector_2_headers": build_user_headers("insp-2", "InspectorOfElection"),
    # entity_backed fallback — ONLY for tests that never touch ownership-gated
    # resources (e.g. Shareholder attempting POST /proxy/meetings).
    "shareholder_headers": build_user_headers("test-shareholder-1", "Shareholder"),
}


def make_shareholder_headers(account_id: str) -> dict:
    """Shareholder is entity-backed (PRD §2.1): pass the ShareholderAccount id
    as X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Shareholder")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector identity is opaque; distinct user ids drive the certification
    creator/signer segregation-of-duties check (PRD §3.8)."""
    return build_user_headers(user_id, "InspectorOfElection")


def make_proxy_admin_headers(user_id: str = "proxy-admin-1") -> dict:
    return build_user_headers(user_id, "ProxyAdministrator")


def make_transfer_agent_headers(user_id: str = "transfer-agent-1") -> dict:
    return build_user_headers(user_id, "TransferAgent")


def make_broker_headers(user_id: str = "broker-1") -> dict:
    return build_user_headers(user_id, "Broker")
