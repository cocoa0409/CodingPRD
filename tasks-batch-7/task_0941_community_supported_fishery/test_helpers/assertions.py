"""Entity assertions, money/pound helpers and conservation-invariant checkers."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Timestamps ───────────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants semantically, never as strings.

    The two sides may legitimately differ in how many fractional-second digits they
    render; what the PRD pins is the instant, so both sides are parsed and compared
    as aware datetimes.
    """
    assert actual is not None, f"{label} is missing"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_utc_millis_format(value: str, label: str = "timestamp") -> None:
    """All timestamps are ISO 8601 UTC instants with a trailing Z."""
    assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 UTC instant, got {value!r}"


# ─── Numbers ──────────────────────────────────────────────────────────────────

def assert_pounds(actual, expected, label: str = "pounds") -> None:
    """Pounds are decimals carried to exactly two places."""
    assert actual is not None, f"{label} is missing"
    assert float(actual) == pytest.approx(float(expected), abs=1e-9), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual, expected, label: str = "cents") -> None:
    """Money fields hold a whole number of cents."""
    assert actual is not None, f"{label} is missing"
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a whole number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ─── Common resource shape ────────────────────────────────────────────────────

def assert_common_fields(data: dict, label: str = "resource") -> None:
    """Every resource carries a UUID id, a created_at, an updated_at and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID with no type prefix"
    assert_utc_millis_format(data.get("created_at", ""), f"{label}.created_at")
    assert_utc_millis_format(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_append_only_fields(data: dict, label: str = "record") -> None:
    """An append-only observation carries id and created_at and neither updated_at nor version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID with no type prefix"
    assert_utc_millis_format(data.get("created_at", ""), f"{label}.created_at")
    assert "version" not in data, f"{label} must not carry a version field"
    assert "updated_at" not in data, f"{label} must not carry an updated_at field"


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_season(data: dict) -> None:
    assert_common_fields(data, "Season")
    assert data["status"] in (
        "PLANNING",
        "OPEN",
        "LANDINGS_CLOSED",
        "TRUE_UP",
        "CLOSED",
    ), f"unexpected season status {data['status']}"
    assert isinstance(data["total_weeks"], int)
    assert isinstance(data["shortfall_flag_count"], int)
    assert isinstance(data["offered_species"], list) and data["offered_species"]


def assert_share_plan(data: dict) -> None:
    assert_common_fields(data, "SharePlan")
    assert data["share_size"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["delivery_frequency"] in ("WEEKLY", "BIWEEKLY")
    assert data["species_tier"] in ("WHITEFISH", "PREMIUM_FINFISH", "SHELLFISH")
    assert isinstance(data["price_per_delivery_cents"], int)
    assert isinstance(data["weight_units"], int)
    assert isinstance(data["scheduled_delivery_count"], int)


def assert_pickup_window(data: dict) -> None:
    assert_common_fields(data, "PickupWindow")
    assert data["status"] in ("SCHEDULED", "OPEN", "GRACE", "CLOSED", "RECONCILED")
    assert_slot_partition(data)


def assert_member(data: dict) -> None:
    assert_common_fields(data, "Member")
    assert data["standing"] in ("GOOD", "WARNED", "RESTRICTED")
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["allergy_exclusions"], list)
    assert isinstance(data["dislikes"], list)
    assert isinstance(data["never_substitute"], bool)


def assert_subscription(data: dict) -> None:
    assert_common_fields(data, "Subscription")
    assert data["lifecycle_status"] in (
        "PENDING",
        "WAITLISTED",
        "ACTIVE",
        "PAUSED",
        "PAST_DUE",
        "TRANSFERRED",
        "CANCELLED",
        "COMPLETED",
    )
    assert data["billing_status"] in (
        "UNBILLED",
        "CURRENT",
        "DUNNING",
        "PREPAID_SETTLED",
        "REFUND_PENDING",
        "SETTLED",
    )
    assert data["true_up_status"] in ("NOT_DUE", "SHORTFALL_FLAGGED", "REFUNDED", "CREDITED")
    assert data["fulfillment_mode"] in ("HUB_PICKUP", "HOME_DELIVERY")
    assert data["payment_basis"] in ("PREPAID_FULL_SEASON", "INSTALLMENT")


def assert_vessel(data: dict) -> None:
    assert_common_fields(data, "Vessel")
    assert data["compliance_status"] in ("COMPLIANT", "PROBATION", "SUSPENDED")
    assert isinstance(data["violation_count"], int)
    assert isinstance(data["gear_types"], list) and data["gear_types"]


def assert_quota_ledger(data: dict) -> None:
    assert_common_fields(data, "QuotaLedger")
    assert data["status"] in ("OPEN", "WARNING", "EXHAUSTED", "SUSPENDED")
    assert_quota_ledger_invariant(data)


def assert_trip(data: dict) -> None:
    assert_common_fields(data, "Trip")
    assert data["status"] in ("PLANNED", "LANDED", "VERIFIED", "REJECTED")
    assert data["sustainability_band"] in ("GREEN", "YELLOW", "ORANGE", "RED")
    assert 0 <= data["sustainability_score"] <= 100


def assert_landing_lot(data: dict) -> None:
    assert_common_fields(data, "LandingLot")
    assert data["status"] in (
        "RECORDED",
        "ALLOCATED",
        "SPLIT",
        "DISPATCHED",
        "CLOSED",
        "RECALLED",
    )
    assert data["quality_status"] in ("CLEAR", "HOLD", "RELEASED", "DISCOUNTED", "DISCARDED")
    assert data["allocation_variant"] in ("NONE", "NORMAL_FILL", "SHORT_FILL")
    assert_landed_pounds_partition(data)


def assert_sub_lot(data: dict) -> None:
    assert_common_fields(data, "SubLot")
    assert data["status"] in ("IN_TRANSIT", "ARRIVED", "CONSUMED", "RETURNED", "DESTROYED")
    assert data["destination_type"] in ("HUB", "ROUTE")


def assert_share_delivery(data: dict) -> None:
    assert_common_fields(data, "ShareDelivery")
    assert data["fulfillment_status"] in (
        "SCHEDULED",
        "SKIPPED",
        "ALLOCATED",
        "PACKED",
        "IN_TRANSIT",
        "DELIVERED",
        "AT_HUB",
        "PICKED_UP",
        "NO_SHOW",
        "DONATED",
        "VOIDED",
    )
    assert data["fill_status"] in ("PENDING", "FULL_FILL", "UNDER_FILLED", "SUBSTITUTED", "VOID")
    assert data["billing_status"] in (
        "PENDING",
        "CHARGED",
        "PARTIALLY_CREDITED",
        "CREDITED",
        "REFUNDED",
        "FORFEITED",
    )


def assert_substitution_event(data: dict) -> None:
    assert_common_fields(data, "SubstitutionEvent")
    assert data["status"] in ("PROPOSED", "ACCEPTED", "REJECTED", "CREDIT_ISSUED")
    assert data["settlement_variant"] in ("EQUAL_OR_GREATER", "BELOW_VALUE")


def assert_cold_chain_event(data: dict) -> None:
    assert_append_only_fields(data, "ColdChainEvent")
    assert data["custody_leg"] in ("DOCK_TO_HUB", "HUB_HOLD", "HUB_TO_DOOR")
    assert data["breach_type"] in ("NONE", "SINGLE_EXCURSION", "CUMULATIVE", "BOTH")
    assert_utc_millis_format(data.get("recorded_at", ""), "ColdChainEvent.recorded_at")
    assert isinstance(data.get("recorded_by_user_id"), str) and data["recorded_by_user_id"]


def assert_skip_request(data: dict) -> None:
    assert_common_fields(data, "SkipRequest")
    assert data["status"] in ("REQUESTED", "CREDITED", "FORFEITED", "REVOKED")
    assert data["settlement_variant"] in ("CREDIT", "FORFEIT")


def assert_settlement_statement(data: dict) -> None:
    assert_common_fields(data, "SettlementStatement")
    assert data["status"] in ("DRAFT", "PROVISIONAL", "HELD", "FINAL", "PAID", "VOID")
    assert data["variant"] in ("PROVISIONAL", "FINAL")


def assert_share_transfer(data: dict) -> None:
    assert_common_fields(data, "ShareTransfer")
    assert data["status"] in ("REQUESTED", "ACCEPTED", "DECLINED", "EXPIRED")
    assert data["settlement_variant"] in ("PREPAID", "INSTALLMENT")


def assert_recall_notice(data: dict) -> None:
    assert_common_fields(data, "RecallNotice")
    assert data["status"] in ("INITIATED", "SCOPED", "REMEDIATED", "CLOSED")
    assert data["reason"] in ("PATHOGEN", "MISLABEL", "COLD_CHAIN", "REGULATORY")


# ─── Conservation invariants ──────────────────────────────────────────────────

def assert_landed_pounds_partition(lot: dict) -> None:
    """For every landing lot, gross equals net plus the over-quota discard."""
    assert float(lot["landed_pounds_gross"]) == pytest.approx(
        float(lot["landed_pounds_net"]) + float(lot["discarded_over_quota_pounds"]), abs=1e-6
    ), (
        "landed_pounds_gross must equal landed_pounds_net plus discarded_over_quota_pounds: "
        f"{lot['landed_pounds_gross']} vs {lot['landed_pounds_net']} + "
        f"{lot['discarded_over_quota_pounds']}"
    )


def assert_allocation_partition(lot: dict) -> None:
    """For every allocated lot, net equals allocated plus secondary plus donated."""
    assert float(lot["landed_pounds_net"]) == pytest.approx(
        float(lot["allocated_pounds_total"])
        + float(lot["surplus_secondary_pounds"])
        + float(lot["surplus_donated_pounds"]),
        abs=1e-6,
    ), (
        "landed_pounds_net must equal allocated_pounds_total plus surplus_secondary_pounds "
        "plus surplus_donated_pounds"
    )


def assert_quota_ledger_invariant(ledger: dict) -> None:
    """For every quota ledger, entitlement equals committed plus remaining."""
    assert float(ledger["entitlement_pounds"]) == pytest.approx(
        float(ledger["committed_pounds"]) + float(ledger["remaining_pounds"]), abs=1e-6
    ), "entitlement_pounds must equal committed_pounds plus remaining_pounds"


def assert_slot_partition(window: dict) -> None:
    """For every pickup window, total equals free plus reserved plus occupied plus forfeited."""
    assert window["cooler_slots_total"] == (
        window["slots_free"]
        + window["slots_reserved"]
        + window["slots_occupied"]
        + window["slots_forfeited"]
    ), (
        "cooler_slots_total must equal slots_free plus slots_reserved plus slots_occupied "
        f"plus slots_forfeited: {window}"
    )


def assert_vendor_money_invariant(statement: dict) -> None:
    """On a FINAL statement, gross equals deductions plus net payable plus forfeited plus offset."""
    assert statement["gross_cents"] == (
        statement["deductions_cents"]
        + statement["net_payable_cents"]
        + statement["holdback_forfeited_cents"]
        + statement["offset_cents"]
    ), (
        "gross_cents must equal deductions_cents plus net_payable_cents plus "
        f"holdback_forfeited_cents plus offset_cents: {statement}"
    )
    assert (
        statement["holdback_released_cents"] + statement["holdback_forfeited_cents"]
        == statement["holdback_cents"]
    ), "holdback_released_cents plus holdback_forfeited_cents must equal holdback_cents"


def assert_split_mass_invariant(lot: dict, sub_lots: list) -> None:
    """For every split lot, the sub-lot pounds sum to split_pounds_total and to the allocation."""
    total = sum(float(sl["pounds"]) for sl in sub_lots)
    assert total == pytest.approx(float(lot["split_pounds_total"]), abs=1e-6), (
        "the sub-lot pounds must sum to split_pounds_total"
    )
    assert float(lot["split_pounds_total"]) == pytest.approx(
        float(lot["allocated_pounds_total"]), abs=1e-6
    ), "split_pounds_total must equal allocated_pounds_total"


def assert_promised_count_partition(subscription: dict) -> None:
    """After the true-up sweep, the promised count partitions into its five buckets."""
    assert subscription["promised_delivery_count"] == (
        subscription["delivered_count"]
        + subscription["credited_count"]
        + subscription["member_fault_count"]
        + subscription["skip_credited_count"]
        + subscription["undelivered_count"]
    ), (
        "promised_delivery_count must equal delivered_count plus credited_count plus "
        "member_fault_count plus skip_credited_count plus undelivered_count"
    )


def assert_transfer_net_take(transfer: dict, transferor_price_per_delivery_cents: int) -> None:
    """On a transfer, the CSF's net cash take equals transfer_fee_cents exactly."""
    assumed_liability = 0
    if transfer["settlement_variant"] == "INSTALLMENT":
        assumed_liability = (
            transfer["remaining_delivery_count"] * transferor_price_per_delivery_cents
        )
    net_take = (
        transfer["transferee_charge_cents"]
        - transfer["transferor_refund_cents"]
        - assumed_liability
    )
    assert net_take == transfer["transfer_fee_cents"], (
        "transferee_charge_cents less transferor_refund_cents less the assumed liability must "
        f"equal transfer_fee_cents: got {net_take} against {transfer['transfer_fee_cents']}"
    )
