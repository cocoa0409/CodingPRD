"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in [
        "DRAFT", "OPEN", "ORDERING_CLOSED", "SUPPLIER_ORDERED", "DELIVERED",
        "SORTED", "DISTRIBUTION_COMPLETE", "RECONCILED", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["default_profit_share_bps"], int)


def assert_group(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["provisional_proceeds_cents"], int)
    assert isinstance(data["proceeds_balance_cents"], int)


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]
    assert data["unit_price_cents"] > 0
    assert data["supplier_unit_cost_cents"] >= 0
    assert data["case_pack_size"] >= 1
    for bucket in ("delivered_units", "distributed_units", "restocked_units",
                   "written_off_units", "lost_units", "surplus_units"):
        assert isinstance(data[bucket], int), f"{bucket} must be an int"


def assert_product_unit_invariant(data: dict):
    """Conserved-units invariant: delivered == distributed + restocked +
    written_off + surplus + lost (PRD §3.8)."""
    total = (data["distributed_units"] + data["restocked_units"]
             + data["written_off_units"] + data["surplus_units"]
             + data["lost_units"])
    assert data["delivered_units"] == total, (
        f"unit invariant violated: delivered {data['delivered_units']} != "
        f"sum of buckets {total}")


def assert_prize(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["tier_type"] in ["UNITS_SOLD", "REVENUE_CENTS", "ORDERS_COUNT"]
    assert data["threshold_value"] > 0
    assert data["prize_cost_cents"] >= 0
    assert data["stock_quantity"] >= 0
    assert isinstance(data["remaining_quantity"], int)


def assert_seller(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["ENROLLED", "ACTIVE", "SUSPENDED", "WITHDRAWN"]
    assert isinstance(data["units_sold"], int)
    assert isinstance(data["revenue_cents"], int)
    assert isinstance(data["orders_count"], int)


def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["DRAFT", "SUBMITTED", "LOCKED", "CANCELLED",
                              "COMPLETED"]
    assert data["payment_status"] in ["UNPAID", "PARTIALLY_PAID", "PAID"]
    assert data["fulfillment_status"] in ["PENDING", "SORTED", "DISTRIBUTED",
                                          "PARTIALLY_RETURNED", "RETURNED"]
    assert isinstance(data["cleared_cents"], int)


def assert_order_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["returned_qty"], int)
    assert isinstance(data["claim_resolved_refund_qty"], int)
    assert isinstance(data["sort_shortage_qty"], int)


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["RECORDED", "CLEARED", "BOUNCED", "VOIDED",
                              "REFUNDED"]
    assert data["method"] in ["CASH", "CHECK", "CARD"]
    assert isinstance(data["refunded_amount_cents"], int)


def assert_supplier_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACKNOWLEDGED", "DELIVERED",
                              "CANCELLED"]
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["actual_cost_cents"], int)
    assert isinstance(data["total_ordered_units"], int)


def assert_supplier_order_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["requested_units"], int)
    assert isinstance(data["ordered_cases"], int)
    assert isinstance(data["ordered_units"], int)
    assert data["ordered_units"] == data["ordered_cases"] * data["case_pack_size"]


def assert_distribution_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert data["slot_capacity"] >= 1


def assert_sort_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["PENDING", "VERIFIED", "SHORT"]
    assert isinstance(data["expected_qty"], int)


def assert_pickup_appointment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED"]


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "APPEALED",
                              "RESOLVED_REPLACEMENT", "RESOLVED_REFUND"]
    assert data["claim_type"] in ["MISSING", "DAMAGED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_return_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED",
                              "RECEIVED_RESTOCKED", "RECEIVED_WRITTEN_OFF"]
    assert data["reason"] in ["UNSOLD", "DEFECTIVE", "WRONG_ITEM",
                              "FAMILY_CHANGED_MIND"]


def assert_prize_award(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["QUEUED", "AWARDED", "FULFILLED", "FORFEITED",
                              "EXPIRED"]


def assert_ledger_entry(data: dict):
    """Append-only ledger row: id + created_at from the common set; no
    updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "ledger entries are append-only: no version"
    assert "updated_at" not in data, (
        "ledger entries are append-only: no updated_at")
    assert data["entry_type"] in [
        "PROVISIONAL_CREDIT", "SALE_REVERSAL_DEBIT", "BOUNCE_FEE_DEBIT",
        "RETURN_DEBIT", "CLAIM_LOSS_DEBIT", "PRIZE_COST_DEBIT",
        "PRIZE_COST_REVERSAL", "FINAL_TRUE_UP_CREDIT", "FINAL_TRUE_UP_DEBIT",
        "MANUAL_ADJUSTMENT",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert isinstance(data["balance_after_cents"], int)


def assert_ledger_replay_consistency(entries: list):
    """Replay (created_at ASC, seq ASC): seq starts at 1, increments by 1, and
    each balance_after_cents equals the previous balance plus amount_cents."""
    balance = 0
    for index, entry in enumerate(entries, start=1):
        assert entry["seq"] == index, (
            f"seq must be per-group monotonic from 1: entry {index} has "
            f"seq {entry['seq']}")
        balance += entry["amount_cents"]
        assert entry["balance_after_cents"] == balance, (
            f"running balance mismatch at seq {entry['seq']}: "
            f"{entry['balance_after_cents']} != {balance}")
