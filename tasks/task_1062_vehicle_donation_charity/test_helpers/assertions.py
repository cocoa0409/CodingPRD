"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')}"
    )


def assert_donor(data: dict):
    _assert_common(data, "Donor")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ["ACTIVE", "BLOCKED"], f"unexpected donor status {data['status']}"
    assert isinstance(data["donation_count"], int) and data["donation_count"] >= 0


def assert_charity(data: dict):
    _assert_common(data, "CharityAffiliate")
    assert isinstance(data["ein"], str) and data["ein"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"], f"unexpected charity status {data['status']}"
    assert isinstance(data["pledged_balance_cents"], int)
    assert isinstance(data["remitted_balance_cents"], int)
    assert 0 <= data["remittance_fee_pct"] <= 0.30, (
        f"remittance_fee_pct must sit within [0, 0.30], got {data['remittance_fee_pct']}"
    )


def assert_donation(data: dict):
    _assert_common(data, "Donation")
    assert data["status"] in [
        "PENDING_REVIEW", "ACCEPTED", "PICKUP_BLOCKED", "IN_CUSTODY",
        "SOLD", "UNSOLD", "CLOSED", "DECLINED", "CANCELLED",
    ], f"unexpected donation status {data['status']}"
    assert data["payout_status"] in ["PENDING", "ACCRUED", "REMITTED", "WITHHELD"], (
        f"unexpected payout_status {data['payout_status']}"
    )
    assert data["intake_channel"] in ["WEB", "PHONE", "PARTNER"]
    assert data["declared_condition"] in ["EXCELLENT", "GOOD", "FAIR", "POOR", "SALVAGE"]
    assert data["exception_type"] in [
        "NONE", "MATERIAL_IMPROVEMENT", "GIFT_TO_NEEDY", "SIGNIFICANT_USE",
    ]
    assert isinstance(data["pickup_attempts"], int) and data["pickup_attempts"] >= 0
    assert_donation_money_invariants(data)


def assert_donation_money_invariants(data: dict):
    """Money fields are whole cents and never negative."""
    for field in [
        "gross_proceeds_cents", "program_fee_cents",
        "tow_allowance_cents", "net_to_charity_cents",
    ]:
        value = data[field]
        assert isinstance(value, int), f"{field} must be whole cents (integer), got {value!r}"
        assert value >= 0, f"{field} must never be negative, got {value}"
    assert data["program_fee_cents"] <= data["gross_proceeds_cents"], (
        "the program fee is capped at the gross the sale brought in"
    )


def assert_vehicle(data: dict):
    _assert_common(data, "Vehicle")
    assert isinstance(data["vin"], str) and data["vin"]
    assert 1900 <= data["year"] <= 2100, f"model year out of range: {data['year']}"
    assert data["base_book_value_cents"] > 0
    assert isinstance(data["salvage_flag"], bool)
    assert isinstance(data["keys_present"], bool)
    assert isinstance(data["inspected"], bool)
    assert data["fmv_variant"] in ["BASE_CONDITION", "POST_INSPECTION"]
    assert isinstance(data["fmv_estimate_cents"], int) and data["fmv_estimate_cents"] >= 10_000, (
        "the estimate is floored at ten thousand cents"
    )
    if data["condition_grade"] is not None:
        assert data["condition_grade"] in ["EXCELLENT", "GOOD", "FAIR", "POOR", "SALVAGE"]


def assert_title_record(data: dict):
    _assert_common(data, "TitleRecord")
    assert data["state"] in ["DRAFT", "SUBMITTED", "CLEARED", "REJECTED", "ABANDONED"]
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0
    assert isinstance(data["title_number"], str) and data["title_number"]
    assert isinstance(data["owner_name"], str) and data["owner_name"]


def assert_tow_vendor(data: dict):
    _assert_common(data, "TowVendor")
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["hourly_rate_cents"] > 0
    assert data["daily_capacity_slots"] > 0
    assert isinstance(data["booked_slots_count"], int) and data["booked_slots_count"] >= 0


def assert_pickup_order(data: dict):
    _assert_common(data, "PickupOrder")
    assert data["status"] in ["SCHEDULED", "COMPLETED", "FAILED", "CANCELLED"]
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert isinstance(data["actual_tow_cost_cents"], int) and data["actual_tow_cost_cents"] >= 0


def assert_venue(data: dict):
    _assert_common(data, "SalesVenue")
    assert data["venue_type"] in ["AUCTION", "SALVAGE", "DIRECT_SALE"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_auction_lot(data: dict):
    _assert_common(data, "AuctionLot")
    assert data["status"] in ["LISTED", "SOLD", "NO_SALE", "VOIDED", "WITHDRAWN"]
    assert data["reserve_price_cents"] >= 0
    assert isinstance(data["relist_count"], int) and data["relist_count"] >= 0
    assert is_iso8601_timestamp(data.get("listed_at_utc", "")), (
        f"listed_at_utc must be an ISO 8601 UTC timestamp, got {data.get('listed_at_utc')}"
    )


def assert_tax_receipt(data: dict):
    _assert_common(data, "TaxReceipt")
    assert data["status"] in ["DRAFT", "ISSUED", "VOIDED"]
    assert data["form_type"] in [
        "FORM_1098C_BOX_4A", "FORM_1098C_BOX_4B", "ACKNOWLEDGMENT_ONLY",
    ]
    assert data["valuation_variant"] in ["GROSS_PROCEEDS", "FMV_FULL", "FMV_SAFE_HARBOR"]
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 0
    assert isinstance(data["reissue_count"], int) and data["reissue_count"] >= 0


def assert_remittance_batch(data: dict):
    _assert_common(data, "RemittanceBatch")
    assert data["status"] in ["OPEN", "CLOSED", "PAID", "DISPUTED"]
    for field in ["donation_count", "gross_cents", "fee_cents", "net_cents"]:
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert data["net_cents"] == data["gross_cents"] - data["fee_cents"] or data["status"] == "OPEN", (
        "a frozen batch's net_cents is its gross less the final fee"
    )


def assert_follow_up_task(data: dict):
    _assert_common(data, "FollowUpTask")
    assert data["task_type"] in [
        "RECEIPT_DELIVERY", "PICKUP_ESCALATION", "TITLE_STALE", "REMITTANCE_PENDING",
    ]
    assert data["status"] in ["OPEN", "ESCALATED", "DONE"]
    assert is_iso8601_timestamp(data.get("due_utc", "")), (
        f"due_utc must be an ISO 8601 UTC timestamp, got {data.get('due_utc')}"
    )
    assert isinstance(data["assigned_role"], str) and data["assigned_role"]


def assert_ledger_entry(data: dict):
    """A ledger line carries id and created_at only -- no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "ledger entry id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ledger entry created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "a ledger line is never edited, so it carries no updated_at"
    assert "version" not in data, "a ledger line is never edited, so it carries no version"
    assert data["entry_type"] in [
        "PROCEEDS_CREDIT", "PROGRAM_FEE_DEBIT", "TOW_COST_DEBIT", "ADMIN_FEE_DEBIT",
        "REVERSAL", "REMITTANCE_SETTLEMENT", "CHARITY_FEE_DEBIT",
    ]
    assert data["direction"] in ["CREDIT", "DEBIT"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0, (
        "amount_cents is always an unsigned magnitude of at least zero"
    )


def signed_total(entries) -> int:
    """Signed sum: +amount_cents on CREDIT, -amount_cents on DEBIT."""
    total = 0
    for entry in entries:
        total += entry["amount_cents"] if entry["direction"] == "CREDIT" else -entry["amount_cents"]
    return total


def ledger_types(entries):
    return [entry["entry_type"] for entry in entries]
