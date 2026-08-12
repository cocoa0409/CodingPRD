"""Entity assertions, instant comparison and decimal comparison helpers.

Every timestamp assertion in this suite goes through `assert_same_instant`,
which parses both sides and compares the resulting instants. The PRD states
that "Timestamp comparisons are semantic comparisons of instants, never string
comparisons", so a renderer that emits `...T00:00:00Z` where the test wrote
`...T00:00:00.000Z` must still pass.

Every money / liters / pH / ABV assertion goes through a tolerance helper
rather than `==`, with a tolerance tighter than the last decimal the PRD
carries (2 places), so a value that is off by one cent or one hundredth of a
liter still fails.
"""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ABV_TOLERANCE, MONEY_TOLERANCE, VOLUME_TOLERANCE


# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------
def parse_instant(value, label: str = "timestamp") -> datetime:
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        assert isinstance(value, str) and value.strip(), (
            f"{label} must be a non-empty ISO 8601 string, got {value!r}"
        )
        text = value.strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:  # pragma: no cover - defensive
            raise AssertionError(f"{label} is not a parseable ISO 8601 instant: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label: str = "timestamp") -> None:
    """Assert two ISO 8601 values denote the same instant (never a string compare)."""
    actual_dt = parse_instant(actual, f"{label} (actual)")
    expected_dt = parse_instant(expected, f"{label} (expected)")
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_dt.isoformat()} "
        f"(from {expected!r}), got {actual_dt.isoformat()} (from {actual!r})"
    )


def assert_utc_date(actual, expected_date: str, label: str = "date") -> None:
    """Assert a normalised date value falls on the expected UTC calendar day at 00:00:00."""
    assert_same_instant(actual, f"{expected_date}T00:00:00.000Z", label)


def assert_is_timestamp(value, label: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 timestamp, got {value!r}"


# --------------------------------------------------------------------------
# Decimal quantities
# --------------------------------------------------------------------------
def assert_close(actual, expected, tolerance: float, label: str) -> None:
    assert actual is not None, f"{label} must be present, got None"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert abs(float(actual) - float(expected)) <= tolerance, (
        f"{label}: expected {expected} (tolerance {tolerance}), got {actual}"
    )


def assert_money(actual, expected, label: str = "amount") -> None:
    """Dollars carried to exactly 2 decimal places, rounded half up."""
    assert_close(actual, expected, MONEY_TOLERANCE, label)


def assert_liters(actual, expected, label: str = "liters") -> None:
    """Liters carried to exactly 2 decimal places, rounded half up."""
    assert_close(actual, expected, VOLUME_TOLERANCE, label)


def assert_abv(actual, expected, label: str = "abv_pct") -> None:
    """pH values and ABV percentages carried to exactly 2 decimal places."""
    assert_close(actual, expected, ABV_TOLERANCE, label)


def assert_two_decimals(actual, label: str = "value") -> None:
    """The value carries no more precision than 2 decimal places."""
    assert actual is not None, f"{label} must be present"
    assert abs(round(float(actual), 2) - float(actual)) < 1e-9, (
        f"{label} must be carried to 2 decimal places, got {actual}"
    )


# --------------------------------------------------------------------------
# Envelope-independent shape assertions
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, entity: str) -> None:
    """id / created_at / updated_at / version, carried by every family but QaReading."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert_is_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert_is_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_recipe(data: dict) -> None:
    assert_common_fields(data, "Recipe")
    assert isinstance(data["name"], str) and data["name"]
    assert data["style"] in (
        "KOMBUCHA",
        "JUN",
        "WATER_KEFIR",
        "HOP_TONIC",
        "BOTANICAL_SODA",
    )
    assert isinstance(data["recipe_version_number"], int)
    assert data["intended_abv_class"] in ("NON_ALCOHOLIC", "ALCOHOLIC")


def assert_label_approval(data: dict) -> None:
    assert_common_fields(data, "LabelApproval")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "STALE")
    assert data["abv_class"] in ("NON_ALCOHOLIC", "ALCOHOLIC")
    assert isinstance(data["required_elements"], list)
    assert isinstance(data["declared_elements"], list)


def assert_scoby_culture(data: dict) -> None:
    assert_common_fields(data, "ScobyCulture")
    assert data["state"] in ("ACTIVE", "REVERIFICATION_PENDING", "RETIRED", "CONTAMINATED")
    assert isinstance(data["generation_number"], int) and data["generation_number"] >= 1
    assert 0 <= data["vitality_score"] <= 100, (
        f"vitality_score must be clamped into 0..100, got {data['vitality_score']}"
    )


def assert_vessel(data: dict) -> None:
    assert_common_fields(data, "Vessel")
    assert data["state"] in ("DIRTY", "CIP_IN_PROGRESS", "SANITIZED", "OCCUPIED")


def assert_ingredient_lot(data: dict) -> None:
    assert_common_fields(data, "IngredientLot")
    assert data["status"] in (
        "AVAILABLE",
        "PARTIALLY_CONSUMED",
        "CONSUMED",
        "EXPIRED",
        "QUARANTINED",
    )
    assert_ingredient_quantity_conservation(data)


def assert_batch(data: dict) -> None:
    assert_common_fields(data, "Batch")
    assert data["ferment_stage"] in (
        "F1_ACTIVE",
        "F2_ACTIVE",
        "READY_TO_PACKAGE",
        "PACKAGED",
        "DUMPED",
    )
    assert data["qa_disposition"] in ("PENDING", "CONFORMING", "AT_RISK", "NONCONFORMING")
    assert_batch_volume_conservation(data)


def assert_qa_reading(data: dict) -> None:
    """A QA reading is append-only: id and created_at, but no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "QaReading.id must be a UUID string"
    assert_is_timestamp(data.get("created_at"), "QaReading.created_at")
    assert "updated_at" not in data, "QaReading must not carry an updated_at field"
    assert "version" not in data, "QaReading must not carry a version field"
    assert data["reading_type"] in ("F1", "F2", "PACKAGING")
    assert isinstance(data["flagged"], bool)
    assert isinstance(data["flag_reasons"], list)
    assert isinstance(data["day_index"], int)


def assert_packaging_run(data: dict) -> None:
    assert_common_fields(data, "PackagingRun")
    assert data["status"] in (
        "DRAFT",
        "SOURCED",
        "IN_PROGRESS",
        "COMPLETED",
        "ABORTED",
        "RECALL_FLAGGED",
    )
    assert data["format"] in ("KEG", "BOTTLE", "CAN")
    assert isinstance(data["source_draws"], list)
    assert data["source_batch_count"] == len(data["source_draws"]), (
        "source_batch_count must equal the number of entries in source_draws"
    )


def assert_finished_lot(data: dict) -> None:
    assert_common_fields(data, "FinishedLot")
    assert data["status"] in ("HELD", "RELEASED", "QUARANTINED", "RECALLED", "DEPLETED")
    assert data["abv_class"] in ("NON_ALCOHOLIC", "ALCOHOLIC")
    assert_finished_goods_unit_conservation(data)


def assert_keg(data: dict) -> None:
    assert_common_fields(data, "Keg")
    assert data["status"] in (
        "IN_STOCK",
        "FILLED",
        "ON_TAP",
        "EMPTY",
        "ON_DEPOSIT",
        "RETURNED",
        "SCRAPPED",
    )
    assert data["deposit_state"] in ("NONE", "CHARGED", "REFUNDED", "FORFEITED")


def assert_account(data: dict) -> None:
    assert_common_fields(data, "Account")
    assert data["status"] in ("ONBOARDING", "ACTIVE", "CREDIT_HOLD")
    assert data["channel"] in ("WHOLESALE_DISTRIBUTOR", "SELF_DISTRIBUTION")


def assert_shipment(data: dict) -> None:
    assert_common_fields(data, "Shipment")
    assert data["status"] in (
        "DRAFT",
        "CONFIRMED",
        "DELIVERED",
        "PAID",
        "CANCELLED",
        "RECALL_HOLD",
    )
    assert data["aging_bucket"] in ("CURRENT", "B1_1_30", "B2_31_60", "B3_61_PLUS")
    assert data["days_past_due"] >= 0, "days_past_due is floored at 0, never negative"


def assert_shipment_line(data: dict) -> None:
    assert_common_fields(data, "ShipmentLine")
    assert data["line_status"] in ("ACTIVE", "RECALLED", "CANCELLED")


def assert_subscription(data: dict) -> None:
    assert_common_fields(data, "Subscription")
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert isinstance(data["pause_windows"], list)


def assert_subscription_allocation(data: dict) -> None:
    assert_common_fields(data, "SubscriptionAllocation")
    assert data["status"] in ("ALLOCATED", "SHIPPED", "REVERSED")


def assert_taproom_fill(data: dict) -> None:
    assert_common_fields(data, "TaproomFill")
    assert data["fill_status"] in ("REQUESTED", "INSPECTED", "POURED")
    assert data["container_type"] in ("HOUSE_GROWLER", "CUSTOMER_GROWLER", "GLASS_POUR")


def assert_recall_notice(data: dict) -> None:
    assert_common_fields(data, "RecallNotice")
    assert data["status"] in ("PENDING", "ACKNOWLEDGED", "OVERDUE")
    assert data["trigger_source"] in (
        "INGREDIENT_LOT_QUARANTINE",
        "LOT_QUARANTINE",
        "LOT_RECALL",
    )


# --------------------------------------------------------------------------
# Conservation invariants (PRD section 2.11)
# --------------------------------------------------------------------------
def assert_finished_goods_unit_conservation(lot: dict) -> None:
    total = (
        lot["on_hand_units"]
        + lot["shipped_units"]
        + lot["poured_units"]
        + lot["destroyed_units"]
    )
    assert total == lot["units_produced"], (
        "units_produced must equal on_hand_units + shipped_units + poured_units + "
        f"destroyed_units; got {lot['units_produced']} vs {total}"
    )
    assert lot["reserved_units"] <= lot["on_hand_units"], (
        "reserved_units must at all times be at or below on_hand_units; got "
        f"{lot['reserved_units']} > {lot['on_hand_units']}"
    )


def assert_batch_volume_conservation(batch: dict) -> None:
    total = batch["remaining_liters"] + batch["drawn_liters"] + batch["loss_liters"]
    assert_liters(
        total,
        batch["pitched_liters"],
        "pitched_liters must equal remaining_liters + drawn_liters + loss_liters",
    )


def assert_keg_deposit_conservation(account: dict, charged_keg_count: int) -> None:
    assert_money(
        account["keg_deposit_balance"],
        45.00 * charged_keg_count,
        "keg_deposit_balance must equal 45.00 times the number of CHARGED kegs",
    )
    assert_money(
        45.00 * account["kegs_charged_lifetime"],
        account["keg_deposit_balance"]
        + account["deposit_refunded_total"]
        + account["deposit_forfeited_total"],
        "45.00 * kegs_charged_lifetime must equal balance + refunded + forfeited",
    )


def assert_ingredient_quantity_conservation(lot: dict) -> None:
    assert_liters(
        lot["quantity_available"] + lot["quantity_consumed"],
        lot["quantity_received"],
        "quantity_received must equal quantity_available plus quantity_consumed",
    )


def assert_qa_flag_conservation(batch: dict, readings: list) -> None:
    flagged = sum(1 for r in readings if r["flagged"])
    assert batch["flagged_reading_count"] == flagged, (
        "flagged_reading_count must equal the number of QA readings whose flagged is "
        f"true; got {batch['flagged_reading_count']} vs {flagged}"
    )


def find_by_id(rows: list, row_id: str, label: str = "row") -> Optional[dict]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"{label} with id {row_id} not present in the returned collection")
