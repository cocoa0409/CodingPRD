"""Pre-built role headers for every role the PRD recognises.

`Guest` is the only entity-backed identity: when `X-User-Role` is `Guest`,
`X-User-ID` must be the `id` of the acting `Guest` row, and ownership checks
compare a resource's `guest_id` to it.  Any ownership-gated call therefore has
to use `make_guest_headers(guest["id"])`; the shared `guest_headers` constant is
only safe for calls that never touch ownership (401/403/400/404 probes).

The other six roles carry opaque identities.  Their identifier still matters
where the PRD keys a gate on `X-User-ID` — the auditor who may not approve, and
the claim opener who may not adjudicate — so per-instance builders exist for
them too.
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque user identifiers.
MANAGER_USER_ID = "u_mgr_1"
DESK_USER_ID = "u_desk_1"
VETTING_OFFICER_USER_ID = "u_vet_a"
AUDITOR_USER_ID = "u_aud_1"
SECOND_AUDITOR_USER_ID = "u_aud_2"
PORT_AGENT_USER_ID = "u_agent_1"
RISK_OFFICER_USER_ID = "u_risk_1"
SECOND_RISK_OFFICER_USER_ID = "u_risk_2"
FINANCE_USER_ID = "u_fin_1"


TEST_USERS = {
    # Guest is entity_backed: this shared constant is a fallback for tests that
    # do not exercise row-level ownership.
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    # Opaque roles: the shared constant is the canonical form.
    "desk_headers": build_user_headers(DESK_USER_ID, "ShoreExcursionDesk"),
    "manager_headers": build_user_headers(MANAGER_USER_ID, "ExcursionManager"),
    "vetting_officer_headers": build_user_headers(
        VETTING_OFFICER_USER_ID, "OperatorVettingOfficer"
    ),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "OperatorVettingOfficer"),
    "second_auditor_headers": build_user_headers(
        SECOND_AUDITOR_USER_ID, "OperatorVettingOfficer"
    ),
    "port_agent_headers": build_user_headers(PORT_AGENT_USER_ID, "PortAgent"),
    "risk_officer_headers": build_user_headers(RISK_OFFICER_USER_ID, "RiskOfficer"),
    "second_risk_officer_headers": build_user_headers(
        SECOND_RISK_OFFICER_USER_ID, "RiskOfficer"
    ),
    "finance_headers": build_user_headers(FINANCE_USER_ID, "FinanceController"),
}

# Role name -> shared header dict, for role-matrix parametrisation.
HEADERS_BY_ROLE = {
    "Guest": TEST_USERS["guest_headers"],
    "ShoreExcursionDesk": TEST_USERS["desk_headers"],
    "ExcursionManager": TEST_USERS["manager_headers"],
    "OperatorVettingOfficer": TEST_USERS["vetting_officer_headers"],
    "PortAgent": TEST_USERS["port_agent_headers"],
    "RiskOfficer": TEST_USERS["risk_officer_headers"],
    "FinanceController": TEST_USERS["finance_headers"],
}


def make_guest_headers(guest_id: str) -> dict:
    """For the Guest role (entity-backed). Pass the real Guest.id as user_id
    whenever the call is ownership-gated: reading one booking, reading one
    refund-ledger entry, or cancelling a booking."""
    return build_user_headers(guest_id, "Guest")


def make_desk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShoreExcursionDesk")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ExcursionManager")


def make_vetting_officer_headers(user_id: str) -> dict:
    """The recorded auditor of the newest audit may not approve that operator,
    so the officer's identifier is load-bearing here."""
    return build_user_headers(user_id, "OperatorVettingOfficer")


def make_port_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortAgent")


def make_risk_officer_headers(user_id: str) -> dict:
    """The officer who opened a claim may not adjudicate it, so the officer's
    identifier is load-bearing here."""
    return build_user_headers(user_id, "RiskOfficer")


def make_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceController")


def headers_without_user_id(role: str = "ShoreExcursionDesk") -> dict:
    """Headers that declare a role but carry no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = "ShoreExcursionDesk") -> dict:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
