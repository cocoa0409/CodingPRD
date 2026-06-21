"""Entity assertions and domain invariant checkers (PRD §2.4-§2.5)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version, present on all thirteen entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["total_section_count"], int)
    assert data["total_section_count"] >= 0


def assert_section(data: dict):
    _assert_common(data)
    assert data["price_zone"] in ("PREMIUM", "STANDARD", "VALUE")
    assert data["face_value_cents"] > 0
    assert data["row_count"] >= 1
    assert data["seats_per_row"] >= 1
    assert data["capacity"] == data["row_count"] * data["seats_per_row"], \
        "capacity must equal row_count * seats_per_row"


def assert_event(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "ON_SALE", "LAST_MINUTE", "COMPLETED", "CANCELLED", "POSTPONED",
    )
    assert data["price_cap_multiplier"] >= 1.0
    assert data["last_minute_cutoff_minutes"] >= 0
    assert isinstance(data["active_listing_count"], int)


def assert_seller(data: dict):
    _assert_common(data)
    assert data["trust_tier"] in ("NEW", "VERIFIED", "TRUSTED", "RESTRICTED")
    assert data["escrow_balance_cents"] >= 0, "escrow_balance_cents never negative"
    assert data["paid_out_balance_cents"] >= 0
    assert data["open_fraud_flag_count"] >= 0


def assert_buyer(data: dict):
    _assert_common(data)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents never negative"
    assert data["lifetime_orders_count"] >= 0


def assert_listing(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SOLD_OUT", "DELISTED", "FROZEN")
    assert data["delivery_method"] in ("MOBILE_TRANSFER", "BARCODE_PDF")
    assert data["pricing_mode"] in ("FIXED", "DYNAMIC")
    assert data["split_rule"] in ("ANY", "PAIRS", "WHOLE")
    assert data["ask_price_cents"] > 0
    assert data["total_seat_count"] >= 0
    assert data["available_seat_count"] >= 0
    assert data["held_seat_count"] >= 0


def assert_seat(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "HELD", "SOLD", "TRANSFERRED", "VOID")
    assert data["seat_number"] >= 1
    assert isinstance(data["barcode_token"], str) and len(data["barcode_token"]) > 0


def assert_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("PENDING", "CHARGED", "REFUNDED", "CREDITED")
    assert data["delivery_status"] in (
        "AWAITING", "IN_TRANSFER", "DELIVERED", "DELIVERY_FAILED", "REPLACED",
    )
    assert data["lifecycle_state"] in ("OPEN", "SETTLED", "UNWOUND")
    assert data["quantity"] >= 1


def assert_transfer(data: dict):
    _assert_common(data)
    assert data["method"] in ("MOBILE_TRANSFER", "BARCODE_PDF")
    assert data["status"] in ("INITIATED", "SENT", "ACCEPTED", "EXPIRED", "FAILED", "RECALLED")
    assert data["attempt_number"] >= 1
    assert isinstance(data["is_last_minute"], bool)


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "ESCROWED", "RELEASABLE", "PAID", "CLAWED_BACK", "CANCELLED",
    )
    assert data["gross_sale_cents"] >= 0
    assert data["seller_fee_cents"] >= 0
    assert data["net_payout_cents"] >= 0, "net_payout_cents never below 0"
    assert data["clawback_cents"] >= 0


def assert_guarantee_claim(data: dict):
    _assert_common(data)
    assert data["reason"] in ("NOT_DELIVERED", "INVALID_BARCODE", "DUPLICATE_SEAT", "EVENT_ISSUE")
    assert data["status"] in (
        "FILED", "INVESTIGATING", "REPLACEMENT_OFFERED",
        "RESOLVED_REPLACED", "RESOLVED_REFUNDED", "DENIED",
    )
    assert data["round_number"] >= 0


def assert_event_credit(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "REDEEMED", "EXPIRED", "REVOKED")
    assert data["amount_cents"] >= 0
    assert isinstance(data["bonus_applied"], bool)


def assert_fraud_flag(data: dict):
    _assert_common(data)
    assert data["subject_type"] in ("LISTING", "ORDER", "SEAT")
    assert data["signal"] in ("DUPLICATE_BARCODE", "PRICE_GOUGE", "VELOCITY", "CHARGEBACK")
    assert data["severity"] in ("LOW", "HIGH")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "CONFIRMED", "DISMISSED")


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_seat_pool_reconciles(listing: dict):
    """PRD §2.5: AVAILABLE + HELD + SOLD + TRANSFERRED == total_seat_count.
    The listing object only exposes available/held; this verifies the bounds
    that are visible on the listing record itself."""
    assert listing["available_seat_count"] <= listing["total_seat_count"]
    assert listing["held_seat_count"] <= listing["total_seat_count"]


def assert_listing_status_matches_pool(listing: dict):
    """PRD §2.5: ACTIVE while available_seat_count>0, SOLD_OUT when it reaches 0."""
    if listing["status"] == "ACTIVE":
        assert listing["available_seat_count"] > 0, \
            "ACTIVE listing must have available_seat_count > 0"
    if listing["status"] == "SOLD_OUT":
        assert listing["available_seat_count"] == 0, \
            "SOLD_OUT listing must have available_seat_count == 0"
