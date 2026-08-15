"""Pre-built role headers for every role in the PRD (§2.1, §2.9).

Three roles are entity-backed: ``Customer`` (PolicyHolder.id), ``RepairShop``
(RepairShop.id) and ``RentalPartner`` (RentalPartner.id). For those, always use
the per-instance builders with the real entity id whenever the call is
ownership-gated. The remaining roles carry an opaque operator id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "rental_desk_agent_headers": build_user_headers("desk-agent-1", "RentalDeskAgent"),
    "claims_adjuster_headers": build_user_headers("adjuster-1", "ClaimsAdjuster"),
    "settlement_approver_headers": build_user_headers("settlement-1", "SettlementApprover"),
    "recovery_specialist_headers": build_user_headers("recovery-1", "RecoverySpecialist"),
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    # Entity-backed roles: fallback constants for non-ownership checks only
    # (e.g. role-denial probes, 404 probes). Never use these when the call is
    # ownership-gated — build per-instance headers with the real entity id.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "repair_shop_headers": build_user_headers("test-shop-1", "RepairShop"),
    "rental_partner_headers": build_user_headers("test-partner-1", "RentalPartner"),
}


def make_customer_headers(policyholder_id: str) -> dict:
    """Customer is entity-backed by PolicyHolder: pass the real holder id."""
    return build_user_headers(policyholder_id, "Customer")


def make_repair_shop_headers(shop_id: str) -> dict:
    """RepairShop is entity-backed by RepairShop: pass the real shop id."""
    return build_user_headers(shop_id, "RepairShop")


def make_rental_partner_headers(partner_id: str) -> dict:
    """RentalPartner is entity-backed by RentalPartner: pass the real partner id."""
    return build_user_headers(partner_id, "RentalPartner")
