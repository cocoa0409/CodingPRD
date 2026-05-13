"""Pre-built role headers for the IP Management API (PRD §2.1).

PRD §2.1 distinguishes two identity flavors:

- `Admin`, `IPManager`, `FinanceManager`, `Counsel` are *opaque*: X-User-ID is
  an opaque operator identifier and is never compared to any entity id. The
  shared constants below are the canonical form for these roles.

- `InternalAgent` and `ExternalAgent` are *entity-backed*: X-User-ID MUST equal
  the id of the acting `Agent` row. Ownership checks on
  ApplicationOfficeAction compare `assigned_agent_id` to X-User-ID — calling
  /office-actions/{id}/respond with a mismatched X-User-ID is rejected with
  ERR_FORBIDDEN (PRD §2.1, §3.2).

For the two entity-backed roles this module exposes per-instance builders:
`make_internal_agent_headers(agent_id)` and `make_external_agent_headers(agent_id)`.
Fixtures MUST call those builders with the actual Agent.id when the downstream
call is ownership-gated; the shared constants below are appropriate only for
tests that never reach an ownership check (header-missing probes, RBAC probes,
unknown-id probes).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ─────────────────────────────────────────────────────────────
# Shared constants — canonical for opaque roles, fallback-only for agents.
# ─────────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles per PRD §2.1.
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "admin_headers_alt": build_user_headers("test-admin-2", "Admin"),
    "ip_manager_headers": build_user_headers("test-ip-manager-1", "IPManager"),
    "ip_manager_headers_alt": build_user_headers("test-ip-manager-2", "IPManager"),
    "finance_manager_headers": build_user_headers(
        "test-finance-manager-1", "FinanceManager"
    ),
    "counsel_headers": build_user_headers("test-counsel-1", "Counsel"),
    # Entity-backed fallback — only valid for tests that do NOT hit an
    # ownership-gated endpoint (e.g., 401/403 probes, NOT_FOUND probes).
    "internal_agent_fallback": build_user_headers(
        "test-internal-agent-fallback", "InternalAgent"
    ),
    "external_agent_fallback": build_user_headers(
        "test-external-agent-fallback", "ExternalAgent"
    ),
}


# ─────────────────────────────────────────────────────────────
# Per-instance builders — required for every entity-backed call.
# ─────────────────────────────────────────────────────────────


def make_admin_headers(user_id: str = "test-admin-1") -> Dict[str, str]:
    """Admin is opaque (PRD §2.1) — X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "Admin")


def make_ip_manager_headers(user_id: str = "test-ip-manager-1") -> Dict[str, str]:
    """IPManager is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "IPManager")


def make_finance_manager_headers(
    user_id: str = "test-finance-manager-1",
) -> Dict[str, str]:
    """FinanceManager is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "FinanceManager")


def make_counsel_headers(user_id: str = "test-counsel-1") -> Dict[str, str]:
    """Counsel is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "Counsel")


def make_internal_agent_headers(agent_id: str) -> Dict[str, str]:
    """Build InternalAgent headers where X-User-ID equals the acting Agent.id.

    Per PRD §2.1: "For `InternalAgent` and `ExternalAgent`, `X-User-ID` is the
    `id` of the acting `Agent`; ownership checks on any resource that
    references an `Agent` compare the resource's `assigned_agent_id` to
    `X-User-ID`." Fixtures must pass the same Agent.id used to create the
    resource being acted upon (notably for /office-actions/{id}/respond).
    """
    return build_user_headers(agent_id, "InternalAgent")


def make_external_agent_headers(agent_id: str) -> Dict[str, str]:
    """Build ExternalAgent headers where X-User-ID equals the acting Agent.id
    (PRD §2.1)."""
    return build_user_headers(agent_id, "ExternalAgent")
