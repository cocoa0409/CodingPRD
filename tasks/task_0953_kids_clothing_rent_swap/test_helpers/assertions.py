"""Entity assertions, semantic instant comparison and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    GRADE_ORDINALS,
    SIZE_LADDER,
    SIZE_LADDER_ORDINALS,
)

# ---------------------------------------------------------------------------
# Semantic instant comparison
# ---------------------------------------------------------------------------
#
# PRD 2.4: "An instant supplied by a client in a request body is compared
# semantically, as an instant, not as a string; the response, however, always
# renders the platform's own canonical three-fractional-digit form."
#
# A faithful implementation may therefore echo "2026-05-01T00:00:00.000Z" where
# the test wrote "2026-05-01T00:00:00Z".  Never compare instants as strings.


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant, tolerating `Z`, `+00:00`, and any number of
    fractional digits.  Returns a timezone-aware UTC datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Compare two ISO-8601 renderings as instants, not as strings."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    a, e = parse_instant(actual), parse_instant(expected)
    assert a == e, f"{label}: expected instant {expected!r} ({e.isoformat()}), got {actual!r} ({a.isoformat()})"


def assert_instant_before(earlier: str, later: str, label: str = "instant ordering"):
    assert parse_instant(earlier) < parse_instant(later), (
        f"{label}: expected {earlier!r} to be strictly earlier than {later!r}"
    )


def assert_is_instant(value: str, label: str = "instant"):
    """Assert the value is a renderable ISO-8601 instant."""
    assert isinstance(value, str) and value, f"{label} must be a non-empty ISO-8601 string"
    parse_instant(value)


# ---------------------------------------------------------------------------
# Common shape
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, label: str = "entity"):
    """PRD 2.4: every persisted resource carries a bare UUID `id`, a `created_at`
    instant, an `updated_at` instant and an integer `version` starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID: {data.get('id')!r}"
    assert "-" in str(data.get("id", "")), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer at least 1, got {data.get('version')!r}"
    )


def assert_bare_uuid(value: str, label: str = "id"):
    assert is_valid_uuid(value or ""), f"{label} must be a bare UUID with no type prefix: {value!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_plan(data: dict):
    assert_common_fields(data, "Plan")
    assert data["tier"] in ("STARTER", "CORE", "PLUS", "CAPSULE_PLUS")
    assert isinstance(data["slots_per_box"], int) and 1 <= data["slots_per_box"] <= 8
    assert isinstance(data["swaps_per_cycle"], int) and 0 <= data["swaps_per_cycle"] <= 6
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_member(data: dict):
    assert_common_fields(data, "Member")
    assert data["status"] in ("PENDING", "ACTIVE", "PAUSED", "DELINQUENT", "CANCELLED")
    assert data["child_size_code"] in SIZE_LADDER
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0
    assert data["outstanding_balance_cents"] >= 0
    assert_is_instant(data["size_effective_at"], "Member.size_effective_at")


def assert_cycle(data: dict):
    assert_common_fields(data, "Cycle")
    assert data["status"] in (
        "SCHEDULED", "OPEN", "SWAP_CLOSED", "RETURN_DUE",
        "GRACE", "HELD", "CLOSED", "DELINQUENT_CLOSED",
    )
    assert isinstance(data["cycle_index"], int) and 1 <= data["cycle_index"] <= 240
    for field in ("start_at", "swap_by_at", "return_due_at", "grace_ends_at"):
        assert_is_instant(data[field], f"Cycle.{field}")


def assert_garment_style(data: dict):
    assert_common_fields(data, "GarmentStyle")
    assert data["brand_tier"] in ("PREMIUM", "STANDARD", "VALUE")
    assert data["season"] in ("SS", "AW", "ALL_SEASON")
    assert data["demand_band"] in ("HIGH", "MEDIUM", "LOW")
    assert data["size_code"] in SIZE_LADDER
    assert isinstance(data["retail_price_cents"], int) and data["retail_price_cents"] >= 100
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["units_ever_acquired"], int) and data["units_ever_acquired"] >= 0


def assert_garment_unit(data: dict):
    assert_common_fields(data, "GarmentUnit")
    assert data["state"] in (
        "IN_STOCK", "RESERVED", "OUT", "INBOUND",
        "PROCESSING", "LOST_IN_TRANSIT", "RETIRED", "SOLD",
    )
    assert data["acquisition_source"] in ("PURCHASED", "TRADE_IN_ABSORBED")
    assert data["current_grade"] in GRADE_ORDINALS
    assert isinstance(data["cycles_completed"], int) and data["cycles_completed"] >= 0
    assert isinstance(data["cumulative_cleaning_cost_cents"], int)
    assert isinstance(data["retirement_eligible"], bool)


def assert_box(data: dict):
    assert_common_fields(data, "Box")
    assert data["status"] in (
        "DRAFT", "PACKED", "SHIPPED", "DELIVERED", "RETURN_STARTED", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["slots_free"], int)
    assert 0 <= data["slots_free"] <= data["slot_capacity"], (
        f"Box.slots_free {data['slots_free']} outside 0..{data['slot_capacity']}"
    )


def assert_box_item(data: dict):
    assert_common_fields(data, "BoxItem")
    assert data["fulfillment_status"] in (
        "ALLOCATED", "SHIPPED", "WITH_MEMBER", "RETURNING", "RECEIVED", "CANCELLED", "LOST",
    )
    assert data["settlement_status"] in (
        "OPEN", "SETTLED", "WAIVED", "BOUGHT_OUT", "LOST_CHARGED",
    )
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 0
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert isinstance(data["damage_fee_cents"], int) and data["damage_fee_cents"] >= 0


def assert_swap_request(data: dict):
    assert_common_fields(data, "SwapRequest")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "FULFILLED", "REJECTED", "CANCELLED",
    )
    assert isinstance(data["return_box_item_ids"], list)
    assert isinstance(data["requested_style_ids"], list)


def assert_shipping_label(data: dict):
    assert_common_fields(data, "ShippingLabel")
    assert data["direction"] in ("OUTBOUND", "RETURN", "TRADE_IN_INBOUND", "REJECT_RETURN")
    assert data["status"] in ("ISSUED", "IN_TRANSIT", "DELIVERED", "LOST", "VOIDED", "EXPIRED")
    assert isinstance(data["reissue_count"], int) and 0 <= data["reissue_count"] <= 2
    assert_is_instant(data["issued_at"], "ShippingLabel.issued_at")
    assert_is_instant(data["expires_at"], "ShippingLabel.expires_at")


def assert_shipment(data: dict):
    assert_common_fields(data, "Shipment")
    assert data["direction"] in ("OUTBOUND", "RETURN", "TRADE_IN_INBOUND", "REJECT_RETURN")
    assert data["status"] in (
        "CREATED", "IN_TRANSIT", "DELIVERED", "LOST", "RETURNED_TO_SENDER",
    )
    assert isinstance(data["ever_scanned"], bool)


def assert_condition_assessment(data: dict):
    assert_common_fields(data, "ConditionAssessment")
    assert data["pipeline"] in ("RENTAL", "TRADE_IN")
    assert data["status"] in ("DRAFT", "SUBMITTED", "DISPUTED", "CONFIRMED", "VOIDED")
    assert isinstance(data["regrade_count"], int) and 0 <= data["regrade_count"] <= 2
    if data.get("grade") is not None:
        assert data["grade"] in GRADE_ORDINALS


def assert_processing_job(data: dict):
    assert_common_fields(data, "ProcessingJob")
    assert data["route"] in ("STANDARD_LAUNDER", "STAIN_TREATMENT", "REPAIR", "RETIRE")
    assert data["status"] in ("QUEUED", "IN_PROGRESS", "FAILED", "PASSED", "SCRAPPED")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0


def assert_trade_in_submission(data: dict):
    assert_common_fields(data, "TradeInSubmission")
    assert data["status"] in (
        "DRAFT", "LABEL_ISSUED", "IN_TRANSIT", "RECEIVED", "GRADING", "CREDITED", "CLOSED",
    )
    assert isinstance(data["declared_item_count"], int)
    assert 3 <= data["declared_item_count"] <= 12
    assert isinstance(data["credited_total_cents"], int) and data["credited_total_cents"] >= 0
    assert isinstance(data["uncapped_total_cents"], int) and data["uncapped_total_cents"] >= 0


def assert_trade_in_item(data: dict):
    assert_common_fields(data, "TradeInItem")
    assert data["grading_status"] in ("PENDING", "GRADED", "REJECTED", "CREDITED")
    assert data["disposition_status"] in (
        "NONE", "AWAITING_ELECTION", "ABSORBED", "RETURN_TO_MEMBER", "DONATE", "RECYCLE",
    )
    assert data["declared_brand_tier"] in ("PREMIUM", "STANDARD", "VALUE")
    assert data["declared_size_code"] in SIZE_LADDER
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert isinstance(data["granted_credit_cents"], int) and data["granted_credit_cents"] >= 0


def assert_buy_out_order(data: dict):
    assert_common_fields(data, "BuyOutOrder")
    assert data["status"] in ("QUOTED", "ACCEPTED", "PAID", "COMPLETED", "EXPIRED", "CANCELLED")
    assert data["quote_variant"] in ("CYCLES_WORN", "MONTHS_HELD")
    assert isinstance(data["quoted_price_cents"], int) and data["quoted_price_cents"] >= 0
    assert isinstance(data["late_surcharge_cents"], int) and data["late_surcharge_cents"] >= 0
    assert isinstance(data["final_price_cents"], int)
    assert_is_instant(data["quoted_at"], "BuyOutOrder.quoted_at")
    assert_is_instant(data["quote_expires_at"], "BuyOutOrder.quote_expires_at")


def assert_capsule(data: dict):
    assert_common_fields(data, "Capsule")
    assert data["season"] in ("SS", "AW")
    assert data["status"] in ("DRAFT", "ANNOUNCED", "OPEN", "EMBARGO_LIFTED", "CLOSED")
    assert_is_instant(data["release_at"], "Capsule.release_at")
    assert_is_instant(data["close_at"], "Capsule.close_at")


def assert_capsule_allocation(data: dict):
    assert_common_fields(data, "CapsuleAllocation")
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert isinstance(data["units_allocated"], int) and data["units_allocated"] >= 1


def assert_pause_request(data: dict):
    assert_common_fields(data, "PauseRequest")
    assert data["status"] in ("REQUESTED", "ACTIVE", "ENDED", "CANCELLED", "DENIED")
    assert isinstance(data["days_requested"], int) and 7 <= data["days_requested"] <= 30
    assert_is_instant(data["start_at"], "PauseRequest.start_at")
    assert_is_instant(data["end_at"], "PauseRequest.end_at")


def assert_lost_shipment_claim(data: dict):
    assert_common_fields(data, "LostShipmentClaim")
    assert data["status"] in (
        "OPENED", "INVESTIGATING", "AWAITING_MEMBER_INFO", "APPROVED", "DENIED", "SETTLED",
    )
    if data.get("variant") is not None:
        assert data["variant"] in ("SCANNED", "NEVER_SCANNED")
    assert_is_instant(data["filed_at"], "LostShipmentClaim.filed_at")
    assert_is_instant(data["deadline_at"], "LostShipmentClaim.deadline_at")


def assert_charge_entry(data: dict):
    assert_common_fields(data, "ChargeLedgerEntry")
    assert data["charge_type"] in (
        "PLAN_CHARGE", "PROTECTION_FEE", "LATE_FEE", "DAMAGE_FEE",
        "SHIPPING_FEE", "LOST_LIABILITY", "BUYOUT_PRICE", "SURCHARGE",
    )
    assert data["status"] in ("ASSESSED", "PARTIALLY_SETTLED", "SETTLED", "WAIVED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["net_due_cents"], int) and data["net_due_cents"] >= 0


def assert_credit_entry(data: dict):
    assert_common_fields(data, "CreditLedgerEntry")
    assert data["status"] in ("AVAILABLE", "PARTIALLY_APPLIED", "APPLIED", "EXPIRED", "REVOKED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert_is_instant(data["granted_at"], "CreditLedgerEntry.granted_at")
    assert_is_instant(data["expires_at"], "CreditLedgerEntry.expires_at")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_box_slot_conservation(box: dict, items: list):
    """PRD 2.10: for each Box, `slot_capacity` equals `slots_free` plus the
    number of its items whose `fulfillment_status` is one of ALLOCATED,
    SHIPPED, WITH_MEMBER or RETURNING, plus the number of its items whose
    `settlement_status` is BOUGHT_OUT."""
    holding = sum(
        1 for i in items
        if i["fulfillment_status"] in ("ALLOCATED", "SHIPPED", "WITH_MEMBER", "RETURNING")
    )
    bought_out = sum(1 for i in items if i["settlement_status"] == "BOUGHT_OUT")
    assert box["slot_capacity"] == box["slots_free"] + holding + bought_out, (
        f"Slot conservation broken: capacity {box['slot_capacity']} != free "
        f"{box['slots_free']} + holding {holding} + bought_out {bought_out}"
    )


def assert_unit_conservation(style: dict, units: list):
    """PRD 2.10: for each GarmentStyle, `units_ever_acquired` equals the total
    number of that style's units counted across all eight circulation states."""
    states = (
        "IN_STOCK", "RESERVED", "OUT", "INBOUND",
        "PROCESSING", "LOST_IN_TRANSIT", "RETIRED", "SOLD",
    )
    counted = sum(1 for u in units if u["state"] in states)
    assert style["units_ever_acquired"] == counted, (
        f"Unit conservation broken: units_ever_acquired {style['units_ever_acquired']} "
        f"!= {counted} units across the eight circulation states"
    )


def assert_credit_conservation(credit_entries: list, charge_entries: list):
    """PRD 2.10: the sum of `amount_cents` over every credit entry equals the
    sum of `remaining_cents` over AVAILABLE / PARTIALLY_APPLIED entries, plus
    the sum of `credit_applied_cents` over all charges, plus the sum of
    `remaining_cents` over EXPIRED / REVOKED entries."""
    granted = sum(c["amount_cents"] for c in credit_entries)
    live = sum(
        c["remaining_cents"] for c in credit_entries
        if c["status"] in ("AVAILABLE", "PARTIALLY_APPLIED")
    )
    applied = sum(c["credit_applied_cents"] for c in charge_entries)
    parked = sum(
        c["remaining_cents"] for c in credit_entries
        if c["status"] in ("EXPIRED", "REVOKED")
    )
    assert granted == live + applied + parked, (
        f"Credit conservation broken: granted {granted} != live {live} "
        f"+ applied {applied} + parked {parked}"
    )


def size_ordinal(size_code: str) -> int:
    return SIZE_LADDER_ORDINALS[size_code]


def grade_ordinal(grade: str) -> int:
    return GRADE_ORDINALS[grade]
