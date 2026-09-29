"""Pre-built role headers for every role in the PRD.

Both `X-User-ID` and `X-User-Role` must be present on every request. For a
`CarrierLiaison` the `X-User-ID` is the acting carrier's own `id`, so calls made
by that role must use the per-instance builder with a real carrier id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the six roles whose identity is opaque, and a
# fallback for CarrierLiaison only on calls that never exercise carrier scoping.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "benefits_analyst_headers": build_user_headers("analyst-1", "BenefitsAnalyst"),
    "risk_officer_headers": build_user_headers("risk-1", "RiskOfficer"),
    "treasury_controller_headers": build_user_headers("treasury-1", "TreasuryController"),
    "claims_administrator_headers": build_user_headers("claims-1", "ClaimsAdministrator"),
    "board_secretary_headers": build_user_headers("board-1", "BoardSecretary"),
    # CarrierLiaison: shared constant is a non-ownership fallback only.
    "carrier_liaison_headers": build_user_headers("carrier-liaison-1", "CarrierLiaison"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_benefits_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BenefitsAnalyst")


def make_risk_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RiskOfficer")


def make_treasury_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TreasuryController")


def make_claims_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdministrator")


def make_board_secretary_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardSecretary")


def make_carrier_liaison_headers(carrier_id: str) -> dict:
    """For CarrierLiaison, whose `X-User-ID` is the acting carrier's own `id`.

    Pass the real carrier id whenever the call is scoped to that carrier's own
    records; anything else is a carrier scope violation.
    """
    return build_user_headers(carrier_id, "CarrierLiaison")
