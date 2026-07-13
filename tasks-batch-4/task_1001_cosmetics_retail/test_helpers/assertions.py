"""Entity assertions and domain invariant checkers (PRD §2.5, §2.7)."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Common resource properties (PRD §2.5) ────────────

def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """id (bare UUID, no type prefix), created_at, updated_at and version >= 1."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an int starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity: str = "resource") -> None:
    """A points-ledger entry carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity} must have no updated_at field"
    assert "version" not in data, f"{entity} must have no version field"


# ─── Per-entity assertions ────────────────────────────

def assert_store(data: dict) -> None:
    assert_common_fields(data, "Store")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str)
    assert data["status"] in ("ACTIVE", "PAUSED")
    assert isinstance(data["bopis_slot_capacity"], int)
    assert data["bopis_slot_capacity"] >= 1, "bopis_slot_capacity must be at least 1"


def assert_product(data: dict) -> None:
    assert_common_fields(data, "Product")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["brand"], str)
    assert data["category"] in ("SKINCARE", "MAKEUP", "FRAGRANCE", "HAIR")
    assert data["hygiene_class"] in ("SEALED", "TESTER_APPLIED", "DIRECT_CONTACT")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0


def assert_variant(data: dict) -> None:
    assert_common_fields(data, "Variant")
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["shade_name"], str)
    assert isinstance(data["shade_code"], str)
    assert data["finish"] in ("MATTE", "DEWY", "SATIN")
    assert data["undertone"] in ("WARM", "COOL", "NEUTRAL")
    assert 1 <= data["depth_index"] <= 12, "depth_index sits on a 1..12 scale"
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["is_limited_launch"], bool)
    assert data["launch_status"] in (
        "NOT_LIMITED",
        "SCHEDULED",
        "TIER_ROUGE_ONLY",
        "TIER_VIB_PLUS",
        "PUBLIC",
        "CLOSED",
    )
    assert data["per_customer_cap"] >= 1


def assert_inventory_lot(data: dict) -> None:
    assert_common_fields(data, "InventoryLot")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["variant_id"])
    for field in (
        "units_received",
        "on_hand_units",
        "reserved_units",
        "tester_units",
        "sold_units",
        "destroyed_units",
        "launch_reserved_units",
    ):
        assert isinstance(data[field], int), f"InventoryLot.{field} must be an integer"
        assert data[field] >= 0, f"InventoryLot.{field} must never go negative"
    assert_lot_units_conserved(data)


def assert_customer(data: dict) -> None:
    assert_common_fields(data, "Customer")
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["name"], str)
    assert data["tier"] in ("INSIDER", "VIB", "ROUGE")
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["qualifying_spend_cents"], int)
    assert isinstance(data["lifetime_spend_cents"], int)
    assert is_iso8601_timestamp(data["cycle_started_at"])
    assert isinstance(data["hygiene_strikes"], int) and data["hygiene_strikes"] >= 0
    assert data["return_privilege"] in ("ACTIVE", "SUSPENDED")


def assert_promotion(data: dict) -> None:
    assert_common_fields(data, "Promotion")
    assert isinstance(data["name"], str)
    assert data["promo_type"] in ("GWP", "SAMPLE", "BUNDLE")
    assert isinstance(data["threshold_cents"], int) and data["threshold_cents"] >= 0
    assert data["priority"] is not None
    assert data["status"] in ("ACTIVE", "ENDED")
    assert 0 <= data["bundle_discount_pct"] < 1


def assert_order(data: dict) -> None:
    assert_common_fields(data, "Order")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["store_id"])
    assert data["channel"] in ("BOPIS", "SHIP_FROM_STORE")
    assert data["fulfillment_status"] in (
        "DRAFT",
        "RESERVED",
        "READY_FOR_PICKUP",
        "PICKED_UP",
        "SHIPPED",
        "CANCELLED",
    )
    assert data["payment_status"] in (
        "UNPAID",
        "AUTHORIZED",
        "CAPTURED",
        "PARTIALLY_REFUNDED",
        "REFUNDED",
        "VOIDED",
    )
    assert data["pricing_variant"] in ("PROVISIONAL", "FINAL")
    for field in (
        "subtotal_cents",
        "tier_discount_cents",
        "discounted_subtotal_cents",
        "points_value_cents",
        "total_due_cents",
        "points_earned",
        "refunded_cents",
        "points_redeemed",
    ):
        assert isinstance(data[field], int), f"Order.{field} must be integer cents/points"
    assert isinstance(data["gwp_eligible"], bool)
    assert_order_money_consistent(data)


def assert_order_money_consistent(data: dict) -> None:
    """The pinned arithmetic of PRD §3.5 must hold on every order body."""
    assert (
        data["discounted_subtotal_cents"]
        == data["subtotal_cents"] - data["tier_discount_cents"]
    ), "discounted_subtotal_cents must equal subtotal_cents less tier_discount_cents"
    assert (
        data["total_due_cents"]
        == data["discounted_subtotal_cents"] - data["points_value_cents"]
    ), "total_due_cents must equal discounted_subtotal_cents less points_value_cents"


def assert_order_line(data: dict) -> None:
    assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["variant_id"])
    assert data["line_type"] in ("SALE", "GWP", "SAMPLE")
    assert data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert data["hygiene_class"] in ("SEALED", "TESTER_APPLIED", "DIRECT_CONTACT")
    assert data["returned_quantity"] >= 0
    assert data["line_gross_cents"] == data["unit_price_cents"] * data["quantity"], (
        "line_gross_cents must be unit_price_cents multiplied by quantity"
    )
    assert data["line_net_cents"] == data["line_gross_cents"] - data["line_discount_cents"], (
        "line_net_cents must be line_gross_cents less line_discount_cents"
    )
    if data["line_type"] == "SALE":
        assert data["promotion_id"] is None, "a sale line's promotion_id is null"
    else:
        assert data["unit_price_cents"] == 0, "gift and sample lines price at zero"


def assert_points_ledger_entry(data: dict) -> None:
    assert_append_only_fields(data, "PointsLedgerEntry")
    assert is_valid_uuid(data["customer_id"])
    assert data["entry_type"] in (
        "SEED",
        "EARN",
        "REDEEM",
        "REVERSAL",
        "CLAWBACK",
        "SERVICE_BONUS",
    )
    assert isinstance(data["delta_points"], int)
    assert isinstance(data["balance_after"], int)
    if data["entry_type"] in ("REDEEM", "CLAWBACK"):
        assert data["delta_points"] <= 0, f"{data['entry_type']} entries are negative"
    if data["entry_type"] in ("SEED", "EARN", "REVERSAL", "SERVICE_BONUS"):
        assert data["delta_points"] >= 0, f"{data['entry_type']} entries are positive"
    if data["entry_type"] == "SEED":
        assert data["order_id"] is None, "a SEED entry has no order behind it"


def assert_artist(data: dict) -> None:
    assert_common_fields(data, "Artist")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["skills"], list)
    for skill in data["skills"]:
        assert skill in ("BROW", "MAKEOVER")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_service_booking(data: dict) -> None:
    assert_common_fields(data, "ServiceBooking")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["artist_id"])
    assert data["service_type"] in ("BROW", "MAKEOVER")
    assert data["status"] in (
        "CONFIRMED",
        "RESCHEDULE_PENDING",
        "COMPLETED",
        "NO_SHOW",
        "CANCELLED",
    )
    expected_duration = 30 if data["service_type"] == "BROW" else 60
    assert data["duration_minutes"] == expected_duration, (
        "a BROW runs 30 minutes and a MAKEOVER runs 60"
    )
    assert data["reschedule_count"] >= 0
    assert data["bonus_points_awarded"] >= 0


def assert_return_request(data: dict) -> None:
    assert_common_fields(data, "ReturnRequest")
    assert is_valid_uuid(data["order_line_id"])
    assert data["quantity"] >= 1
    assert data["reason"] in (
        "WRONG_SHADE",
        "DAMAGED",
        "CHANGED_MIND",
        "ALLERGIC_REACTION",
    )
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")
    if data.get("deny_reason") is not None:
        assert data["deny_reason"] in (
            "HYGIENE_VIOLATION",
            "NOT_AS_DESCRIBED",
            "OUT_OF_POLICY",
        )
    if data.get("disposition") is not None:
        assert data["disposition"] in ("RESTOCK", "DESTROY")


# ─── Conserved-quantity invariants (PRD §2.7) ─────────

def assert_lot_units_conserved(lot: dict) -> None:
    """units_received always equals on_hand + reserved + tester + sold + destroyed."""
    total = (
        lot["on_hand_units"]
        + lot["reserved_units"]
        + lot["tester_units"]
        + lot["sold_units"]
        + lot["destroyed_units"]
    )
    assert total == lot["units_received"], (
        f"units are not conserved: units_received={lot['units_received']} but "
        f"on_hand={lot['on_hand_units']} + reserved={lot['reserved_units']} + "
        f"tester={lot['tester_units']} + sold={lot['sold_units']} + "
        f"destroyed={lot['destroyed_units']} = {total}"
    )


def assert_points_ledger_conserved(customer: dict, entries: list) -> None:
    """points_balance always equals the sum of delta_points over the customer's entries."""
    ledger_sum = sum(e["delta_points"] for e in entries)
    assert customer["points_balance"] == ledger_sum, (
        f"points are not conserved: points_balance={customer['points_balance']} but "
        f"the ledger sums to {ledger_sum}"
    )


def assert_ledger_entry_sequence(entries: list, expected: list) -> None:
    """Assert (entry_type, delta_points) pairs in the order the ledger returns them
    (oldest first, PRD §3.4)."""
    actual = [(e["entry_type"], e["delta_points"]) for e in entries]
    assert actual == expected, f"Expected ledger {expected}, got {actual}"


def assert_lot_counters(lot: dict, **expected) -> None:
    """Assert named lot counters and re-check unit conservation."""
    for field, value in expected.items():
        assert lot[field] == value, (
            f"Expected InventoryLot.{field} == {value}, got {lot[field]}"
        )
    assert_lot_units_conserved(lot)
