"""Pre-built role headers for every role in the PRD.

CardHolder is entity-backed by CardHolder and MerchantUser is entity-backed by
Merchant: for ownership-gated calls, X-User-ID must be the id of the persisted
entity, so those calls MUST use make_cardholder_headers(holder_id) /
make_merchantuser_headers(merchant_id). The shared constants are fallbacks for
tests that do not exercise ownership (400/404/wrong-role checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "card_office_admin_headers": build_user_headers("card-office-1", "CardOfficeAdmin"),
    "dining_manager_headers": build_user_headers("dining-mgr-1", "DiningServicesManager"),
    "bursar_headers": build_user_headers("bursar-1", "BursarOffice"),
    "fraud_analyst_headers": build_user_headers("fraud-1", "FraudAnalyst"),
    "security_officer_headers": build_user_headers("security-1", "SecurityOfficer"),
    "pos_headers": build_user_headers("pos-terminal-1", "PointOfSale"),
    "door_controller_headers": build_user_headers("door-ctrl-1", "DoorController"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "cardholder_headers": build_user_headers("test-holder-1", "CardHolder"),
    "merchant_user_headers": build_user_headers("test-merchant-1", "MerchantUser"),
}


def make_platform_admin_headers(user_id: str = "platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_card_office_admin_headers(user_id: str = "card-office-1") -> dict:
    return build_user_headers(user_id, "CardOfficeAdmin")


def make_dining_manager_headers(user_id: str = "dining-mgr-1") -> dict:
    return build_user_headers(user_id, "DiningServicesManager")


def make_bursar_headers(user_id: str = "bursar-1") -> dict:
    return build_user_headers(user_id, "BursarOffice")


def make_fraud_analyst_headers(user_id: str = "fraud-1") -> dict:
    return build_user_headers(user_id, "FraudAnalyst")


def make_security_officer_headers(user_id: str = "security-1") -> dict:
    return build_user_headers(user_id, "SecurityOfficer")


def make_pos_headers(user_id: str = "pos-terminal-1") -> dict:
    return build_user_headers(user_id, "PointOfSale")


def make_door_controller_headers(user_id: str = "door-ctrl-1") -> dict:
    return build_user_headers(user_id, "DoorController")


def make_cardholder_headers(holder_id: str) -> dict:
    """For CardHolder (entity_backed:CardHolder). Pass the real CardHolder.id
    whenever the call is ownership-gated."""
    return build_user_headers(holder_id, "CardHolder")


def make_merchantuser_headers(merchant_id: str) -> dict:
    """For MerchantUser (entity_backed:Merchant). Pass the real Merchant.id
    whenever the call is ownership-gated."""
    return build_user_headers(merchant_id, "MerchantUser")
