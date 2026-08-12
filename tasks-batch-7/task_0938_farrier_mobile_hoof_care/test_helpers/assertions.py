"""Entity assertions, derivation helpers and domain invariant checkers."""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASIS_POINT_DENOMINATOR,
    DAYS_PER_WEEK,
    HORSE_HANDLING_MINUTES,
    SEDATION_EXTRA_MINUTES,
    SEDATION_HANDLING_MULTIPLIER_BP,
    SERVICE_MINUTES,
    SERVICE_UNITS,
    SHOES_PER_PAIR,
    TRAVEL_MINUTES_BY_ZONE,
)

# ---------------------------------------------------------------------------
# Timestamps: always compared as instants, never as rendered strings.
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str) and value, f"expected a timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, message: str = "") -> None:
    """Compare two timestamps semantically (same instant), never by string equality."""
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, (
        f"{message or 'timestamp mismatch'}: expected instant {want.isoformat()} "
        f"(from {expected!r}), got {got.isoformat()} (from {actual!r})"
    )


def parse_iso_date(value: str) -> date:
    assert isinstance(value, str) and value, f"expected an ISO date string, got {value!r}"
    return date.fromisoformat(value.strip())


def assert_same_date(actual: str, expected: str, message: str = "") -> None:
    """Compare two ISO calendar dates by value rather than by rendering."""
    assert parse_iso_date(actual) == parse_iso_date(expected), (
        f"{message or 'date mismatch'}: expected {expected}, got {actual}"
    )


def plus_days(iso_day: str, days: int) -> str:
    """Elapsed-duration day arithmetic: D plus N days."""
    return (parse_iso_date(iso_day) + timedelta(days=days)).isoformat()


def plus_weeks(iso_day: str, weeks: int) -> str:
    """`N weeks after D` is D plus N times 7 calendar days (PRD 2.4)."""
    return (parse_iso_date(iso_day) + timedelta(days=weeks * DAYS_PER_WEEK)).isoformat()


def lead_days(scheduled_date: str, clock_date: str) -> int:
    """Whole-calendar-day difference of the later minus the earlier."""
    return (parse_iso_date(scheduled_date) - parse_iso_date(clock_date)).days


WEEKDAY_TOKENS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def weekday_token(iso_day: str) -> str:
    """MON at index 0 through SUN at index 6 (PRD 2.4)."""
    return WEEKDAY_TOKENS[parse_iso_date(iso_day).weekday()]


# ---------------------------------------------------------------------------
# Arithmetic helpers mirroring the PRD's stated formulas.
# ---------------------------------------------------------------------------


def round_half_up(numerator: int, denominator: int) -> int:
    """The largest integer not greater than the value plus one half (PRD 2.5)."""
    return math.floor(numerator / denominator + 0.5)


def apply_basis_points(base: int, rate_bp: int) -> int:
    """base * rate / 10000, rounded half up."""
    return round_half_up(base * rate_bp, BASIS_POINT_DENOMINATOR)


def pairs_required(shoe_line_count: int) -> int:
    """Shoe count divided by 2, rounded up (PRD 2.5 / 3.5)."""
    return math.ceil(shoe_line_count / SHOES_PER_PAIR)


def expected_service_units(service_types) -> int:
    return sum(SERVICE_UNITS[t] for t in service_types)


def expected_service_minutes(service_types, requires_sedation: bool) -> int:
    """Per-limb chair time plus handling (PRD 3.5)."""
    chair = sum(SERVICE_MINUTES[t] for t in service_types)
    if requires_sedation:
        handling = apply_basis_points(
            HORSE_HANDLING_MINUTES, SEDATION_HANDLING_MULTIPLIER_BP
        )
        return chair + handling + SEDATION_EXTRA_MINUTES
    return chair + HORSE_HANDLING_MINUTES


def travel_minutes_for_zone(zone: str) -> int:
    return TRAVEL_MINUTES_BY_ZONE[zone]


# ---------------------------------------------------------------------------
# Common-field assertions.
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    """id + created_at + updated_at + version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID string, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity_name: str = "resource") -> None:
    """Only id and created_at; neither updated_at nor version may be emitted."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, f"{entity_name} must not emit updated_at"
    assert "version" not in data, f"{entity_name} must not emit version"


def assert_fields_present(data: dict, field_names, entity_name: str = "resource"):
    for field in field_names:
        assert field in data, f"{entity_name} must serialize the field {field!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions.
# ---------------------------------------------------------------------------


def assert_barn(data: dict) -> None:
    assert_common_fields(data, "Barn")
    assert_fields_present(
        data,
        [
            "name",
            "zone",
            "served_weekdays",
            "access_open_minute",
            "access_close_minute",
            "blackout_dates",
        ],
        "Barn",
    )
    assert data["zone"] in ("A", "B", "C")
    assert isinstance(data["served_weekdays"], list) and data["served_weekdays"]
    assert isinstance(data["blackout_dates"], list)
    assert isinstance(data["access_open_minute"], int)
    assert isinstance(data["access_close_minute"], int)
    assert data["access_open_minute"] < data["access_close_minute"]


def assert_client(data: dict) -> None:
    assert_common_fields(data, "Client")
    assert_fields_present(
        data,
        [
            "display_name",
            "home_barn_id",
            "billing_standing",
            "deposit_balance_cents",
            "credit_balance_cents",
            "completed_visit_count",
            "no_show_count_rolling",
            "tax_exempt",
        ],
        "Client",
    )
    assert data["billing_standing"] in ("ACTIVE", "PREPAY_REQUIRED", "SUSPENDED")
    assert isinstance(data["tax_exempt"], bool)


def assert_horse(data: dict) -> None:
    assert_common_fields(data, "Horse")
    assert_fields_present(
        data,
        [
            "client_id",
            "barn_id",
            "name",
            "routine_cycle_weeks",
            "requires_sedation",
            "shoe_size_code",
            "lifecycle_status",
            "hold_status",
            "active_prescription_id",
            "next_due_on",
            "last_completed_on",
        ],
        "Horse",
    )
    assert data["lifecycle_status"] in ("ACTIVE", "RETIRED")
    assert data["hold_status"] in ("CLEAR", "HOLD")


def assert_limb_state(data: dict) -> None:
    assert_common_fields(data, "LimbState")
    assert_fields_present(
        data,
        [
            "horse_id",
            "limb",
            "shoeing_state",
            "current_sku_code",
            "last_serviced_on",
            "consecutive_reset_count",
        ],
        "LimbState",
    )
    assert data["limb"] in ("LF", "RF", "LH", "RH")
    assert data["shoeing_state"] in ("BAREFOOT", "SHOD", "SHOD_WITH_PAD", "GLUED")


def assert_farrier(data: dict) -> None:
    assert_common_fields(data, "Farrier")
    assert_fields_present(
        data, ["display_name", "certification_level", "cert_expires_on", "status"],
        "Farrier",
    )
    assert data["status"] in ("ACTIVE", "INACTIVE", "DECERTIFIED")
    assert data["certification_level"] in (
        "APPRENTICE",
        "JOURNEYMAN",
        "CERTIFIED_THERAPEUTIC",
    )


def assert_shoe_sku(data: dict) -> None:
    assert_common_fields(data, "ShoeSku")
    assert_fields_present(
        data, ["sku_code", "size_code", "material", "price_cents_per_pair"], "ShoeSku"
    )
    assert data["material"] in ("STEEL", "ALUMINUM", "COMPOSITE")
    assert data["price_cents_per_pair"] >= 0


def assert_inventory_bucket(data: dict) -> None:
    assert_common_fields(data, "InventoryBucket")
    assert_fields_present(
        data,
        [
            "location_kind",
            "farrier_id",
            "sku_id",
            "on_hand_pairs",
            "available_pairs",
            "reserved_pairs",
            "replenishment_flag",
        ],
        "InventoryBucket",
    )
    assert data["location_kind"] in ("SHOP", "VAN")
    assert isinstance(data["replenishment_flag"], bool)
    assert_bucket_balance(data)


def assert_stock_transfer(data: dict) -> None:
    assert_common_fields(data, "StockTransfer")
    assert_fields_present(
        data,
        ["sku_id", "from_bucket_id", "to_bucket_id", "quantity_pairs", "status"],
        "StockTransfer",
    )
    assert data["status"] in (
        "REQUESTED",
        "IN_TRANSIT",
        "RECEIVED",
        "CANCELLED",
        "ABORTED",
    )


def assert_shoe_reservation(data: dict) -> None:
    assert_common_fields(data, "ShoeReservation")
    assert_fields_present(
        data, ["appointment_id", "sku_id", "bucket_id", "pairs", "status"],
        "ShoeReservation",
    )
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")


def assert_rate_card(data: dict) -> None:
    assert_common_fields(data, "RateCard")
    assert_fields_present(
        data,
        [
            "label",
            "effective_from",
            "supersedes_rate_card_id",
            "price_trim_cents",
            "price_reset_cents",
            "price_new_shoes_cents",
            "price_corrective_cents",
            "price_glue_on_cents",
            "pad_price_cents",
            "trip_fee_zone_a_cents",
            "trip_fee_zone_b_cents",
            "trip_fee_zone_c_cents",
            "status",
        ],
        "RateCard",
    )
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_route(data: dict) -> None:
    assert_common_fields(data, "Route")
    assert_fields_present(
        data,
        [
            "farrier_id",
            "route_date",
            "status",
            "committed_units",
            "committed_minutes",
            "stop_count",
        ],
        "Route",
    )
    assert data["status"] in (
        "DRAFT",
        "PLANNED",
        "DISPATCHED",
        "CLOSED",
        "CANCELLED",
    )
    assert data["committed_units"] >= 0
    assert data["committed_minutes"] >= 0
    assert data["stop_count"] >= 0


def assert_route_stop(data: dict) -> None:
    assert_common_fields(data, "RouteStop")
    assert_fields_present(
        data,
        [
            "route_id",
            "barn_id",
            "sequence_index",
            "planned_start_minute",
            "status",
            "travel_minutes",
            "service_minutes",
            "end_minute",
            "trip_fee_cents",
            "billable_horse_count",
        ],
        "RouteStop",
    )
    assert data["status"] in ("PENDING", "ARRIVED", "COMPLETED", "VOIDED")
    assert data["end_minute"] == data["planned_start_minute"] + data["service_minutes"], (
        "RouteStop.end_minute must be planned_start_minute plus service_minutes"
    )


def assert_appointment(data: dict) -> None:
    assert_common_fields(data, "Appointment")
    assert_fields_present(
        data,
        [
            "horse_id",
            "route_stop_id",
            "origin_appointment_id",
            "rate_card_id",
            "scheduled_date",
            "visit_kind",
            "warranty_reason",
            "cycle_source",
            "status",
            "billing_status",
            "vet_present",
            "service_units",
            "service_minutes",
            "estimated_total_cents",
            "cancellation_fee_cents",
            "trip_fee_share_cents",
            "completed_on",
        ],
        "Appointment",
    )
    assert data["status"] in (
        "UNROUTED",
        "SCHEDULED",
        "CONFIRMED",
        "IN_PROGRESS",
        "COMPLETED",
        "BLOCKED",
        "CANCELLED_ADVANCE",
        "CANCELLED_LATE",
        "CANCELLED_ONSITE",
        "NO_SHOW",
    )
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "SETTLED", "VOIDED")
    assert data["visit_kind"] in ("ROUTINE", "WARRANTY_REVISIT")


def assert_service_line(data: dict) -> None:
    assert_common_fields(data, "ServiceLine")
    assert_fields_present(
        data,
        [
            "appointment_id",
            "limb_state_id",
            "prescription_id",
            "sku_id",
            "limb",
            "service_type",
            "with_pad",
            "status",
            "labor_cents",
        ],
        "ServiceLine",
    )
    assert data["status"] in ("PLANNED", "PERFORMED", "OMITTED", "REMOVED")
    assert data["service_type"] in (
        "TRIM",
        "RESET",
        "NEW_SHOES",
        "CORRECTIVE",
        "GLUE_ON",
    )


def assert_lameness_case(data: dict) -> None:
    assert_common_fields(data, "LamenessCase")
    assert_fields_present(
        data, ["horse_id", "reported_on", "severity", "status", "hold_applied"],
        "LamenessCase",
    )
    assert data["status"] in ("OPEN", "PRESCRIBED", "RESOLVED")
    assert isinstance(data["hold_applied"], bool)


def assert_prescription(data: dict) -> None:
    assert_common_fields(data, "VetPrescription")
    assert_fields_present(
        data,
        [
            "lameness_case_id",
            "horse_id",
            "issued_on",
            "expires_on",
            "limb_scope",
            "prescribed_cycle_weeks",
            "status",
        ],
        "VetPrescription",
    )
    assert data["status"] in (
        "DRAFT",
        "ACTIVE",
        "EXPIRED",
        "REVOKED",
        "SUPERSEDED",
    )


def assert_invoice(data: dict) -> None:
    assert_common_fields(data, "Invoice")
    assert_fields_present(
        data,
        [
            "appointment_id",
            "client_id",
            "rate_card_id",
            "status",
            "issued_on",
            "labor_subtotal_cents",
            "product_subtotal_cents",
            "multi_horse_discount_cents",
            "loyalty_discount_cents",
            "loyalty_discount_labor_cents",
            "loyalty_discount_product_cents",
            "labor_net_cents",
            "trip_fee_share_cents",
            "fee_cents",
            "taxable_product_base_cents",
            "tax_cents",
            "total_cents",
            "paid_cents",
            "balance_cents",
        ],
        "Invoice",
    )
    assert data["status"] in (
        "DRAFT",
        "ISSUED",
        "PARTIALLY_PAID",
        "PAID",
        "VOID",
    )
    assert_invoice_invariants(data)


def assert_invoice_line(data: dict) -> None:
    assert_append_only_fields(data, "InvoiceLine")
    assert_fields_present(
        data,
        [
            "invoice_id",
            "line_kind",
            "description",
            "limb",
            "service_type",
            "sku_code",
            "quantity",
            "unit_amount_cents",
            "amount_cents",
            "taxable",
        ],
        "InvoiceLine",
    )
    assert isinstance(data["taxable"], bool)


def assert_reminder(data: dict) -> None:
    assert_common_fields(data, "Reminder")
    assert_fields_present(
        data, ["appointment_id", "offset_days", "due_on", "status", "sent_on"],
        "Reminder",
    )
    assert data["status"] in ("PENDING", "SENT", "FAILED", "ACKNOWLEDGED")


# ---------------------------------------------------------------------------
# Conservation invariants (PRD 2.9).
# ---------------------------------------------------------------------------


def assert_bucket_balance(bucket: dict) -> None:
    """on_hand_pairs equals available_pairs plus reserved_pairs."""
    assert bucket["on_hand_pairs"] == bucket["available_pairs"] + bucket["reserved_pairs"], (
        "bucket balance broken: on_hand_pairs "
        f"{bucket['on_hand_pairs']} != available_pairs {bucket['available_pairs']} "
        f"+ reserved_pairs {bucket['reserved_pairs']}"
    )


def assert_loyalty_split(invoice: dict) -> None:
    """loyalty_discount_labor_cents + loyalty_discount_product_cents == loyalty_discount_cents."""
    assert (
        invoice["loyalty_discount_labor_cents"]
        + invoice["loyalty_discount_product_cents"]
        == invoice["loyalty_discount_cents"]
    ), (
        "loyalty split broken: "
        f"{invoice['loyalty_discount_labor_cents']} + "
        f"{invoice['loyalty_discount_product_cents']} != "
        f"{invoice['loyalty_discount_cents']}"
    )


def assert_invoice_total(invoice: dict) -> None:
    """total_cents and balance_cents follow from the component figures."""
    expected_total = (
        invoice["labor_net_cents"]
        + invoice["taxable_product_base_cents"]
        + invoice["trip_fee_share_cents"]
        + invoice["fee_cents"]
        + invoice["tax_cents"]
    )
    assert invoice["total_cents"] == expected_total, (
        f"invoice total broken: expected {expected_total}, got {invoice['total_cents']}"
    )
    assert invoice["balance_cents"] == invoice["total_cents"] - invoice["paid_cents"], (
        "invoice balance broken: balance_cents must be total_cents minus paid_cents"
    )


def assert_invoice_invariants(invoice: dict) -> None:
    assert_loyalty_split(invoice)
    assert_invoice_total(invoice)


def assert_trip_fee_split(stop: dict, invoices) -> None:
    """The billable invoices' shares sum to the stop's trip_fee_cents exactly."""
    total_share = sum(inv["trip_fee_share_cents"] for inv in invoices)
    assert total_share == stop["trip_fee_cents"], (
        f"trip-fee split broken: shares sum to {total_share} but the stop's "
        f"trip_fee_cents is {stop['trip_fee_cents']}"
    )


def find_by(rows, **criteria) -> Optional[dict]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    return None
