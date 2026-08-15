"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (FapAdmin, AuditAnalyst, FinanceController, TreasuryApprover,
System) use shared constants: X-User-ID is an opaque operator identifier.

Entity-backed roles require per-instance builders: CarrierRep's X-User-ID is
the acting Carrier's id, and ClientViewer's is the acting ClientAccount's id.
Ownership-gated calls MUST use make_carrier_rep_headers(carrier["id"]) or
make_client_viewer_headers(client["id"]) — never the shared constants.

Segregation-of-duties tests need the same operator id under different roles,
so per-instance builders exist for the opaque finance/treasury roles too.
"""
from prd_bench_local_runner.testing import build_user_headers

FIN_OPERATOR_1 = "op-fin-1"
FIN_OPERATOR_2 = "op-fin-2"
TREASURY_OPERATOR_1 = "op-treasury-1"
ANALYST_OPERATOR_1 = "op-analyst-1"
ADMIN_OPERATOR_1 = "op-admin-1"
SYSTEM_OPERATOR_1 = "system-1"

TEST_USERS = {
    "fap_admin_headers": build_user_headers(ADMIN_OPERATOR_1, "FapAdmin"),
    "audit_analyst_headers": build_user_headers(ANALYST_OPERATOR_1, "AuditAnalyst"),
    "finance_controller_headers": build_user_headers(FIN_OPERATOR_1, "FinanceController"),
    "finance_controller_2_headers": build_user_headers(FIN_OPERATOR_2, "FinanceController"),
    "treasury_approver_headers": build_user_headers(TREASURY_OPERATOR_1, "TreasuryApprover"),
    "system_headers": build_user_headers(SYSTEM_OPERATOR_1, "System"),
}

# A request carrying neither auth header (PRD §2.1 identity-header stage).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_fap_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FapAdmin")


def make_audit_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AuditAnalyst")


def make_finance_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_treasury_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TreasuryApprover")


def make_carrier_rep_headers(carrier_id: str) -> dict:
    """CarrierRep is entity-backed: X-User-ID must be the acting Carrier's id
    whenever the call is carrier-scoped (PRD §2.1)."""
    return build_user_headers(carrier_id, "CarrierRep")


def make_client_viewer_headers(client_id: str) -> dict:
    """ClientViewer is entity-backed: X-User-ID must be the acting
    ClientAccount's id whenever the read is client-scoped (PRD §2.1)."""
    return build_user_headers(client_id, "ClientViewer")
