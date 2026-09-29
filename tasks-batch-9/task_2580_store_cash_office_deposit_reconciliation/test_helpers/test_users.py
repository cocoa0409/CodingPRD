"""Pre-built role headers for every role in the PRD.

Every request must carry X-User-ID and X-User-Role. When X-User-Role is Cashier
the X-User-ID is the id of the acting Cashier record, so cashier calls MUST use
make_cashier_headers(cashier["id"]). For the other five roles X-User-ID is an
opaque operator identifier.
"""

from prd_bench_local_runner.testing import build_user_headers

#: Distinct operator identifiers, so that dual-control pairs can be satisfied.
CLERK_1 = "U-CLERK-1"
CLERK_2 = "U-CLERK-2"
CLERK_3 = "U-CLERK-3"
CLERK_4 = "U-CLERK-4"
MANAGER_1 = "U-MGR-1"
MANAGER_2 = "U-MGR-2"
CARRIER_1 = "U-CARRIER-7"
CARRIER_2 = "U-CARRIER-9"
TREASURY_1 = "U-TREAS-1"
LP_1 = "U-LP-1"

TEST_USERS = {
    # entity_backed role: this shared constant is a fallback for tests that do
    # not exercise cashier ownership (missing-record and bad-payload cases).
    "cashier_headers": build_user_headers("U-CASHIER-UNBOUND", "Cashier"),
    # opaque roles: the shared constant is the canonical form.
    "clerk_headers": build_user_headers(CLERK_1, "CashOfficeClerk"),
    "clerk_2_headers": build_user_headers(CLERK_2, "CashOfficeClerk"),
    "clerk_3_headers": build_user_headers(CLERK_3, "CashOfficeClerk"),
    "clerk_4_headers": build_user_headers(CLERK_4, "CashOfficeClerk"),
    "manager_headers": build_user_headers(MANAGER_1, "StoreManager"),
    "manager_2_headers": build_user_headers(MANAGER_2, "StoreManager"),
    "carrier_headers": build_user_headers(CARRIER_1, "ArmoredCarrier"),
    "carrier_2_headers": build_user_headers(CARRIER_2, "ArmoredCarrier"),
    "treasury_headers": build_user_headers(TREASURY_1, "TreasuryAnalyst"),
    "investigator_headers": build_user_headers(LP_1, "LossPreventionInvestigator"),
}


def make_cashier_headers(cashier_id: str) -> dict:
    """For Cashier, whose X-User-ID is the id of the acting Cashier record.

    Pass the real Cashier.id whenever the call is ownership-gated: recording a
    drop, closing one's own register, or acknowledging one's own coaching.
    """
    return build_user_headers(cashier_id, "Cashier")


def make_clerk_headers(user_id: str) -> dict:
    """For CashOfficeClerk, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "CashOfficeClerk")


def make_manager_headers(user_id: str) -> dict:
    """For StoreManager, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "StoreManager")


def make_carrier_headers(user_id: str) -> dict:
    """For ArmoredCarrier, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "ArmoredCarrier")


def make_treasury_headers(user_id: str) -> dict:
    """For TreasuryAnalyst, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "TreasuryAnalyst")


def make_investigator_headers(user_id: str) -> dict:
    """For LossPreventionInvestigator, an opaque operator identifier."""
    return build_user_headers(user_id, "LossPreventionInvestigator")


#: Every role name, for authorization sweeps.
ALL_ROLE_NAMES = [
    "Cashier",
    "CashOfficeClerk",
    "StoreManager",
    "ArmoredCarrier",
    "TreasuryAnalyst",
    "LossPreventionInvestigator",
]


def headers_for_role(role_name: str, user_id: str = "U-GENERIC-1") -> dict:
    """Build headers for any role name, for role-authorization sweeps."""
    return build_user_headers(user_id, role_name)
