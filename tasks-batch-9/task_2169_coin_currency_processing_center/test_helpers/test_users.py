"""Pre-built role headers for every role in the PRD.

Five roles carry an opaque operator identity; `CustomerAccountHolder` is
entity-backed, so its `X-User-ID` must be the acting CustomerAccount's `id`.
Tests that exercise ownership MUST use `make_customer_account_holder_headers()`
with the real account id — never the shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# ─── Opaque operator identifiers used across the suite ────────────────────

MANAGER_1 = "u-mgr-1"
MANAGER_2 = "u-mgr-2"
TELLER_1 = "u-tel-1"
TELLER_2 = "u-tel-2"
CARRIER_1 = "u-car-1"
COMPLIANCE_1 = "u-cmp-1"
FED_AGENT_1 = "u-frb-1"


# Shared constants — safe for opaque roles and for tests that never exercise
# CustomerAccount ownership.
TEST_USERS = {
    "manager_headers": build_user_headers(MANAGER_1, "VaultManager"),
    "second_manager_headers": build_user_headers(MANAGER_2, "VaultManager"),
    "teller_headers": build_user_headers(TELLER_1, "VaultTeller"),
    "second_teller_headers": build_user_headers(TELLER_2, "VaultTeller"),
    "carrier_headers": build_user_headers(CARRIER_1, "ArmoredCarrier"),
    "compliance_headers": build_user_headers(COMPLIANCE_1, "ComplianceOfficer"),
    "fed_agent_headers": build_user_headers(FED_AGENT_1, "FederalReserveAgent"),
    # Fallback only: never use for an ownership-gated call.
    "customer_headers": build_user_headers("test-customer-1", "CustomerAccountHolder"),
}


# ─── Per-instance builders ────────────────────────────────────────────────

def make_manager_headers(user_id: str) -> dict:
    """VaultManager (opaque identity). Pass a distinct operator id when a
    dual-control or segregation-of-duties rule compares operator identifiers."""
    return build_user_headers(user_id, "VaultManager")


def make_teller_headers(user_id: str) -> dict:
    """VaultTeller (opaque identity). Pass a distinct operator id when dual
    control compares the acting user against a recorded operator."""
    return build_user_headers(user_id, "VaultTeller")


def make_carrier_headers(user_id: str) -> dict:
    """ArmoredCarrier (opaque identity)."""
    return build_user_headers(user_id, "ArmoredCarrier")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer (opaque identity)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_fed_agent_headers(user_id: str) -> dict:
    """FederalReserveAgent (opaque identity)."""
    return build_user_headers(user_id, "FederalReserveAgent")


def make_customer_account_holder_headers(customer_account_id: str) -> dict:
    """CustomerAccountHolder — the identity IS the CustomerAccount row.

    Pass the actual CustomerAccount `id` returned by
    POST /cash-vault/customer-accounts. Any other value fails every
    ownership check with ERR_ACCOUNT_OWNERSHIP.
    """
    return build_user_headers(customer_account_id, "CustomerAccountHolder")


def headers_without_user_id(role: str = "VaultManager") -> dict:
    """Headers carrying X-User-Role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "u-nite-1", role: str = "NightAuditor") -> dict:
    """Headers naming a role outside the six the system recognises."""
    return build_user_headers(user_id, role)


__all__ = [
    "TEST_USERS",
    "MANAGER_1",
    "MANAGER_2",
    "TELLER_1",
    "TELLER_2",
    "CARRIER_1",
    "COMPLIANCE_1",
    "FED_AGENT_1",
    "make_manager_headers",
    "make_teller_headers",
    "make_carrier_headers",
    "make_compliance_headers",
    "make_fed_agent_headers",
    "make_customer_account_holder_headers",
    "headers_without_user_id",
    "headers_with_unknown_role",
]
