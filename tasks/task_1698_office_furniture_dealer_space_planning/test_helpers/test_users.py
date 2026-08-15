"""Pre-built role headers for every role in the PRD.

All eleven roles are opaque: X-User-ID is an operator identifier not tied to
any persisted entity. The server records it only where the business process
requires attribution (PricingContract.created_by_user_id /
activated_by_user_id; LiquidationLot.appraised_by_user_id /
issued_by_user_id), and those recorded values are what the
segregation-of-duties checks compare against. The per-user builder functions
exist so tests can pin those attribution ids explicitly.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical user ids used across fixtures; contract creator and activator
# (and lot appraiser vs credit issuer) must differ to satisfy segregation
# of duties.
USER_ACCOUNT_EXECUTIVE = "ae-1"
USER_CONTRACTS_OFFICER = "co-1"
USER_CONTRACTS_OFFICER_2 = "co-2"
USER_DEALER_ADMIN = "da-1"
USER_DESIGNER = "des-1"
USER_CLIENT_APPROVER = "ca-1"
USER_PROJECT_MANAGER = "pm-1"
USER_WAREHOUSE_LEAD = "wl-1"
USER_CLAIMS_COORDINATOR = "cc-1"
USER_MANUFACTURER_REP = "mr-1"
USER_LIQUIDATION_APPRAISER = "la-1"
USER_FINANCE_MANAGER = "fm-1"

TEST_USERS = {
    "dealer_admin_headers": build_user_headers(USER_DEALER_ADMIN, "DealerAdmin"),
    "account_executive_headers": build_user_headers(USER_ACCOUNT_EXECUTIVE, "AccountExecutive"),
    "contracts_officer_headers": build_user_headers(USER_CONTRACTS_OFFICER, "ContractsOfficer"),
    "designer_headers": build_user_headers(USER_DESIGNER, "Designer"),
    "client_approver_headers": build_user_headers(USER_CLIENT_APPROVER, "ClientApprover"),
    "project_manager_headers": build_user_headers(USER_PROJECT_MANAGER, "ProjectManager"),
    "warehouse_lead_headers": build_user_headers(USER_WAREHOUSE_LEAD, "WarehouseLead"),
    "claims_coordinator_headers": build_user_headers(USER_CLAIMS_COORDINATOR, "ClaimsCoordinator"),
    "manufacturer_rep_headers": build_user_headers(USER_MANUFACTURER_REP, "ManufacturerRep"),
    "liquidation_appraiser_headers": build_user_headers(USER_LIQUIDATION_APPRAISER, "LiquidationAppraiser"),
    "finance_manager_headers": build_user_headers(USER_FINANCE_MANAGER, "FinanceManager"),
}

# Headers carrying no user context at all (for the header-presence rule).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_dealer_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DealerAdmin")


def make_account_executive_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccountExecutive")


def make_contracts_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractsOfficer")


def make_designer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Designer")


def make_client_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClientApprover")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_warehouse_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseLead")


def make_claims_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsCoordinator")


def make_manufacturer_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ManufacturerRep")


def make_liquidation_appraiser_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LiquidationAppraiser")


def make_finance_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceManager")
