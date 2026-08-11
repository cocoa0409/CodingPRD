"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_fair(data: dict):
    _assert_audit_fields(data, "Fair")
    assert isinstance(data["name"], str) and data["name"]
    assert data["posture"] in [
        "SETUP", "ENTRIES_OPEN", "ENTRIES_LOCKED", "WEIGH_IN",
        "SHOWING", "AUCTION", "SETTLEMENT", "CLOSED",
    ]
    assert isinstance(data["premium_budget_cents"], int)
    assert isinstance(data["available_premium_pool_cents"], int)
    assert isinstance(data["yardage_fee_cents"], int)
    assert isinstance(data["premium_cap_cents"], int)


def assert_exhibitor(data: dict):
    _assert_audit_fields(data, "Exhibitor")
    assert data["organization"] in ["FFA", "FOUR_H", "INDEPENDENT"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_animal_entry(data: dict):
    _assert_audit_fields(data, "AnimalEntry")
    assert data["species"] in [
        "MARKET_STEER", "MARKET_SWINE", "MARKET_LAMB", "MARKET_GOAT",
    ]
    assert isinstance(data["tag_number"], str) and data["tag_number"]
    assert data["status"] in [
        "ENTERED", "VERIFIED", "WEIGHED", "CLASSIFIED", "SHOWN",
        "SOLD", "NOT_SOLD", "DISQUALIFIED", "CLEARED", "REJECTED",
    ]
    assert isinstance(data["state_fair_qualified"], bool)


def assert_weigh_ticket(data: dict):
    _assert_audit_fields(data, "WeighTicket")
    assert data["weight_lbs"] > 0
    assert data["status"] in ["ACTIVE", "VOIDED"]


def assert_show_class(data: dict):
    _assert_audit_fields(data, "ShowClass")
    assert data["weight_max_lbs"] > data["weight_min_lbs"]
    assert data["capacity"] > 0
    assert isinstance(data["placed_count"], int) and data["placed_count"] >= 0
    assert data["status"] in ["OPEN", "FINALIZED"]


def assert_judge(data: dict):
    _assert_audit_fields(data, "Judge")
    assert isinstance(data["qualified_species"], list)
    assert len(data["qualified_species"]) > 0


def assert_ring_slot(data: dict):
    _assert_audit_fields(data, "RingSlot")
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED"]
    assert isinstance(data["ring_name"], str) and data["ring_name"]


def assert_placing(data: dict):
    _assert_audit_fields(data, "Placing")
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert data["award"] in ["NONE", "GRAND_CHAMPION", "RESERVE_CHAMPION"]
    assert data["status"] in ["RECORDED", "VOIDED"]


def assert_premium_award(data: dict):
    _assert_audit_fields(data, "PremiumAward")
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["status"] in ["ACCRUED", "APPROVED", "PAID", "FORFEITED"]


def assert_buyer(data: dict):
    _assert_audit_fields(data, "Buyer")
    assert isinstance(data["bidder_number"], str) and data["bidder_number"]
    assert isinstance(data["credit_limit_cents"], int)


def assert_auction_lot(data: dict):
    _assert_audit_fields(data, "AuctionLot")
    assert isinstance(data["lot_number"], int) and data["lot_number"] >= 1
    assert data["status"] in ["QUEUED", "OPEN", "SOLD", "PASSED", "NO_SALE"]
    assert isinstance(data["reoffer_count"], int) and data["reoffer_count"] >= 0


def assert_add_on_pledge(data: dict):
    _assert_audit_fields(data, "AddOnPledge")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["PLEDGED", "INVOICED", "PAID", "VOIDED"]


def assert_invoice(data: dict):
    _assert_audit_fields(data, "Invoice")
    assert data["status"] in ["DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID"]
    for field in (
        "hammer_subtotal_cents", "addon_subtotal_cents", "buyer_premium_cents",
        "total_due_cents", "amount_paid_cents", "balance_cents", "line_count",
    ):
        assert isinstance(data[field], int), f"Invoice.{field} must be int cents"


def assert_disposition_order(data: dict):
    _assert_audit_fields(data, "DispositionOrder")
    assert data["disposition_type"] in ["HARVEST", "RETURN"]
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED", "COMPLETED"]
    assert isinstance(data["created_by_user_id"], str)


def assert_health_inspection(data: dict):
    # Immutable record: carries only id and created_at (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "HealthInspection.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "HealthInspection.created_at must be ISO 8601"
    assert "updated_at" not in data, "HealthInspection must not carry updated_at"
    assert "version" not in data, "HealthInspection must not carry version"
    assert data["result"] in ["PASS", "FAIL", "QUARANTINE"]


def assert_affidavit(data: dict):
    _assert_audit_fields(data, "Affidavit")
    assert data["status"] in ["SIGNED", "REVOKED"]
    assert is_iso8601_timestamp(data.get("signed_at", "")), \
        "Affidavit.signed_at must be ISO 8601"


def assert_premium_pool_invariant(fair: dict, awards: list):
    """Purse conservation (PRD §3.5): pool == budget - sum(provisional of
    awards in ACCRUED/APPROVED/PAID); FORFEITED excluded."""
    outstanding = sum(
        a["provisional_amount_cents"]
        for a in awards
        if a["status"] in ("ACCRUED", "APPROVED", "PAID")
    )
    assert fair["available_premium_pool_cents"] == (
        fair["premium_budget_cents"] - outstanding
    ), (
        f"pool {fair['available_premium_pool_cents']} != budget "
        f"{fair['premium_budget_cents']} - outstanding {outstanding}"
    )


def assert_invoice_totals(invoice: dict):
    """Invoice arithmetic (PRD §3.7): total due and balance identities."""
    assert invoice["total_due_cents"] == (
        invoice["hammer_subtotal_cents"]
        + invoice["addon_subtotal_cents"]
        + invoice["buyer_premium_cents"]
    )
    assert invoice["balance_cents"] == (
        invoice["total_due_cents"] - invoice["amount_paid_cents"]
    )
