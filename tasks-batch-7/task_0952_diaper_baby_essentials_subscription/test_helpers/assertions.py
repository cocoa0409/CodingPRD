"""Entity assertions, timestamp helpers and domain invariant checkers."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import STAGE_BANDS, STAGE_ORDER


# ==========================================================================
# Timestamp handling — always semantic, never lexical
# ==========================================================================
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of how it renders fractions.

    ``2026-06-08T00:00:00Z``, ``2026-06-08T00:00:00.000Z`` and
    ``2026-06-08T00:00:00+00:00`` are the same instant; a string comparison
    would call them different.
    """
    assert isinstance(value, str) and value, f"expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two instants semantically after parsing both sides."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def instant_plus(base: str, *, days: int = 0, hours: int = 0, seconds: int = 0) -> str:
    """Return ``base`` shifted by the given offset, rendered with a Z suffix."""
    moment = parse_instant(base) + timedelta(days=days, hours=hours, seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def assert_instant_offset(actual: str, base: str, *, days: int = 0, hours: int = 0,
                          label: str = "instant") -> None:
    """Assert ``actual`` equals ``base`` plus the given offset."""
    assert_same_instant(actual, instant_plus(base, days=days, hours=hours), label)


# ==========================================================================
# Pure recomputations of PRD formulas (used only to build expectations)
# ==========================================================================
def round_half_up(value: float) -> int:
    """Round half away from zero to a whole unit, as the PRD pins."""
    from decimal import Decimal, ROUND_HALF_UP

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def stage_for_weight(weight_grams: int) -> str:
    for stage in STAGE_ORDER:
        low, high = STAGE_BANDS[stage]
        if low <= weight_grams < high:
            return stage
    raise AssertionError(f"weight {weight_grams} sits outside every declared band")


def stage_offset(from_stage: str, to_stage: str) -> int:
    return STAGE_ORDER.index(to_stage) - STAGE_ORDER.index(from_stage)


# ==========================================================================
# Common-field assertions
# ==========================================================================
def assert_full_quartet(data: dict, label: str = "resource") -> None:
    """A living resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_append_only_shape(data: dict, label: str = "record") -> None:
    """An append-only observation carries id and created_at and nothing else of the quartet."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert "version" not in data, f"{label} must not carry a version field"
    assert "updated_at" not in data, f"{label} must not carry an updated_at field"


# ==========================================================================
# Per-entity assertions
# ==========================================================================
def assert_account(data: dict) -> None:
    assert_full_quartet(data, "Account")
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert data["status"] in ("PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["payment_method_on_file"], bool)
    assert isinstance(data["referral_code"], str) and data["referral_code"]
    assert isinstance(data["loyalty_account_id"], str) and data["loyalty_account_id"]
    assert isinstance(data["available_credit_cents"], int)
    assert isinstance(data["next_charge_estimate_cents"], int)


def assert_child(data: dict) -> None:
    assert_full_quartet(data, "Child")
    assert data["stage"] in STAGE_ORDER
    assert isinstance(data["weight_grams"], int)
    assert isinstance(data["stage_pinned"], bool)
    assert isinstance(data["hypoallergenic_required"], bool)
    assert isinstance(data["archived"], bool)


def assert_plan(data: dict) -> None:
    assert_full_quartet(data, "Plan")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["default_pack_count"], int)


def assert_sku(data: dict) -> None:
    assert_full_quartet(data, "Sku")
    assert data["stage"] in STAGE_ORDER
    assert data["line"] in ("STANDARD", "HYPOALLERGENIC")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["pack_size_units"], int)
    assert isinstance(data["pack_price_cents"], int) and data["pack_price_cents"] >= 0
    assert isinstance(data["allergen_tags"], list)
    assert isinstance(data["stock_packs"], int) and data["stock_packs"] >= 0


def assert_subscription(data: dict) -> None:
    assert_full_quartet(data, "Subscription")
    assert data["lifecycle_state"] in ("DRAFT", "ACTIVE", "PAUSED", "CANCELLED")
    assert data["billing_state"] in ("CURRENT", "PAST_DUE", "DELINQUENT")
    assert isinstance(data["cadence_interval_days"], int)
    assert 14 <= data["cadence_interval_days"] <= 56, (
        "cadence_interval_days must stay inside the 14..56 band"
    )
    assert isinstance(data["free_shipping_eligible"], bool)


def assert_cycle(data: dict) -> None:
    assert_full_quartet(data, "Cycle")
    assert data["status"] in (
        "PLANNED", "ALLOCATED", "CUTOFF_LOCKED", "DISPATCHED",
        "DELIVERED", "SKIPPED", "RETURNED", "CANCELLED",
    )
    assert data["payment_status"] in (
        "UNCHARGED", "CHARGED", "FULLY_COVERED", "PARTIALLY_REFUNDED", "REFUNDED",
    )
    for field in (
        "subtotal_cents", "shipping_cents", "gift_credit_applied_cents",
        "referral_credit_applied_cents", "loyalty_redemption_applied_cents",
        "loyalty_points_redeemed", "promo_discount_cents", "total_due_cents",
        "charged_cash_cents", "retained_cash_cents", "points_earned",
    ):
        assert isinstance(data[field], int), f"Cycle.{field} must be an integer number of cents/points"
    assert data["total_due_cents"] >= 0, "total_due_cents is floored at 0"


def assert_cycle_line(data: dict) -> None:
    assert_full_quartet(data, "CycleLine")
    assert data["status"] in (
        "ALLOCATED", "SUBSTITUTION_PENDING", "SUBSTITUTED", "SHORT_FILLED",
    )
    assert isinstance(data["quantity_packs"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["substitution_attempts"], int)
    assert isinstance(data["short_filled_units"], int)


def assert_registry(data: dict) -> None:
    assert_full_quartet(data, "Registry")
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "ARCHIVED")
    assert isinstance(data["reopen_count"], int)
    assert isinstance(data["inflight_gift_count"], int)


def assert_registry_item(data: dict) -> None:
    assert_full_quartet(data, "RegistryItem")
    assert data["status"] in ("REQUESTED", "PARTIALLY_FULFILLED", "FULFILLED")
    assert isinstance(data["requested_quantity"], int)
    assert isinstance(data["fulfilled_quantity"], int)
    assert data["fulfilled_quantity"] <= data["requested_quantity"], (
        "fulfilled_quantity never exceeds requested_quantity"
    )


def assert_gift_order(data: dict) -> None:
    assert_full_quartet(data, "GiftOrder")
    assert data["status"] in (
        "PENDING_PAYMENT", "PAID", "CLAIMED_CREDIT", "CLAIMED_ITEM",
        "FULFILLED", "REFUNDED",
    )
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["paid_cents"], int)


def assert_credit(data: dict) -> None:
    assert_full_quartet(data, "Credit")
    assert data["credit_type"] in ("GIFT", "REFERRAL", "GOODWILL", "SHORT_FILL")
    assert data["status"] in (
        "AVAILABLE", "PARTIALLY_CONSUMED", "CONSUMED", "EXPIRED", "REVOKED",
    )
    assert isinstance(data["refundable"], bool)
    assert_credit_conserved(data)


def assert_shipment(data: dict) -> None:
    assert_full_quartet(data, "Shipment")
    assert data["status"] in (
        "CREATED", "PICKED", "IN_TRANSIT", "EXCEPTION", "DELIVERED", "RETURNED",
    )
    assert data["service_level"] in ("STANDARD", "EXPEDITED")
    assert isinstance(data["exception_count"], int)


def assert_loyalty_account(data: dict) -> None:
    assert_full_quartet(data, "LoyaltyAccount")
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["trailing_earned_points"], int)


def assert_referral(data: dict) -> None:
    assert_full_quartet(data, "Referral")
    assert data["status"] in ("PENDING", "VESTED", "CLAWED_BACK", "EXPIRED")
    assert isinstance(data["credit_cents"], int)


def assert_refund(data: dict) -> None:
    assert_full_quartet(data, "Refund")
    assert data["reason"] in ("CANCEL", "RETURN", "GIFT_REFUND", "GOODWILL")
    assert data["status"] in ("REQUESTED", "APPROVED", "SETTLED", "DENIED")
    for field in (
        "requested_cents", "refunded_cash_cents", "restock_fee_cents",
        "points_clawed_back", "credits_restored_cents",
    ):
        assert isinstance(data[field], int), f"Refund.{field} must be an integer"


def assert_allergen_flag(data: dict) -> None:
    assert_append_only_shape(data, "AllergenFlag")
    assert data["allergen_tag"] in (
        "FRAGRANCE", "LATEX", "LOTION", "DYE", "CHLORINE", "ALOE",
    )
    assert data["severity"] in ("MILD", "SEVERE")


def assert_resize_event(data: dict) -> None:
    assert_append_only_shape(data, "ResizeEvent")
    assert data["origin"] in ("AUTO", "MANUAL")
    assert data["status"] in ("PROPOSED", "APPLIED_CURRENT", "APPLIED_NEXT", "REJECTED")


def assert_skip_record(data: dict) -> None:
    assert_append_only_shape(data, "SkipRecord")
    assert data["status"] in ("APPLIED", "REVOKED")


def assert_points_ledger_entry(data: dict) -> None:
    assert_append_only_shape(data, "PointsLedgerEntry")
    assert data["entry_type"] in ("EARN", "REDEEM", "EXPIRE", "CLAWBACK")
    assert isinstance(data["delta_points"], int)


def assert_substitution_event(data: dict) -> None:
    assert_append_only_shape(data, "SubstitutionEvent")
    assert data["outcome"] in ("SUBSTITUTED", "SHORT_FILLED")
    assert data["reason"] in ("OUT_OF_STOCK", "ALLERGEN_RESCREEN")
    assert isinstance(data["ladder_rung"], int)


def assert_pause_record(data: dict) -> None:
    assert_full_quartet(data, "PauseRecord")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "ENDED", "CANCELLED")
    assert isinstance(data["consumed_days"], int)


# ==========================================================================
# Conservation invariants (PRD section 2.9)
# ==========================================================================
def assert_credit_conserved(credit: dict) -> None:
    """issued_cents == consumed_cents + remaining_cents + forfeited_cents."""
    total = credit["consumed_cents"] + credit["remaining_cents"] + credit["forfeited_cents"]
    assert credit["issued_cents"] == total, (
        f"Credit money not conserved: issued {credit['issued_cents']} != "
        f"consumed {credit['consumed_cents']} + remaining {credit['remaining_cents']} "
        f"+ forfeited {credit['forfeited_cents']}"
    )


def assert_points_ledger_conserved(wallet: dict, entries: list) -> None:
    """points_balance == sum(delta_points) over that wallet's ledger entries."""
    total = sum(entry["delta_points"] for entry in entries)
    assert wallet["points_balance"] == total, (
        f"Points ledger not conserved: balance {wallet['points_balance']} != "
        f"sum of deltas {total}"
    )


def assert_registry_units_conserved(item: dict, gift_orders: list) -> None:
    """fulfilled_quantity == sum(quantity) over the item's live gift orders."""
    live = ("PAID", "CLAIMED_CREDIT", "CLAIMED_ITEM", "FULFILLED")
    total = sum(g["quantity"] for g in gift_orders if g["status"] in live)
    assert item["fulfilled_quantity"] == total, (
        f"Registry units not conserved: fulfilled_quantity "
        f"{item['fulfilled_quantity']} != summed live gift quantity {total}"
    )
    assert item["fulfilled_quantity"] <= item["requested_quantity"]


def assert_cycle_cash_conserved(cycle: dict, settled_refunds: list) -> None:
    """charged_cash_cents == retained_cash_cents + sum(refunded_cash_cents)."""
    refunded = sum(r["refunded_cash_cents"] for r in settled_refunds)
    assert cycle["charged_cash_cents"] == cycle["retained_cash_cents"] + refunded, (
        f"Cycle cash not conserved: charged {cycle['charged_cash_cents']} != "
        f"retained {cycle['retained_cash_cents']} + refunded {refunded}"
    )
