"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
import re

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

# ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.5).
_ISO8601_3DP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_iso8601_3dp(value: str, field: str = "timestamp"):
    """PRD §2.5: created_at is "an ISO 8601 timestamp in UTC with three
    fractional digits (e.g., `2025-05-24T10:30:00.123Z`)"."""
    assert isinstance(value, str) and _ISO8601_3DP_RE.match(value), (
        f"{field} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def assert_calendar_day(value: str, expected_day: str, field: str = "date"):
    """Date fields are "interpreted as UTC calendar days" (PRD §2.4); compare
    on the calendar-day prefix regardless of time serialization."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert value[:10] == expected_day, (
        f"{field} must fall on calendar day {expected_day}, got {value!r}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert_iso8601_3dp(data.get("created_at", ""), "created_at")
    assert_iso8601_3dp(data.get("updated_at", ""), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["credit_status"] in ("GOOD_STANDING", "CREDIT_HOLD")


def assert_aircraft(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert isinstance(data["model"], str) and data["model"]
    assert data["status"] in ("IN_SERVICE", "IN_REFURB", "RETURNED")


def assert_program(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "QUOTED", "BOOKED", "INDUCTED", "SURFACE_REVIEW", "IN_WORK",
        "IN_INSPECTION", "READY_FOR_DELIVERY", "DELIVERED", "CANCELLED",
    )
    for f in (
        "base_price_cents", "daily_penalty_rate_cents", "total_contract_value_cents",
        "discovery_cost_total_cents", "billed_total_cents", "penalty_final_cents",
        "projected_penalty_cents", "rework_cycles", "material_estimate_gallons",
        "material_estimate_cost_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["total_contract_value_cents"] >= 0
    assert data["rework_cycles"] >= 0


def assert_paint_scheme(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["drawing_ref"], str) and data["drawing_ref"]
    assert isinstance(data["painted_area_sqft"], int)
    assert isinstance(data["coat_count"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_surface_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "DECIDED", "SUPERSEDED")
    assert isinstance(data["revision"], int) and data["revision"] >= 1


def assert_discovery_item(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "ESTIMATED", "APPROVED", "COMPLETED", "REJECTED", "DEFERRED",
    )
    assert data["source"] in ("MANUAL", "INSPECTION_AUTO")


def assert_change_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "COUNTERED")
    assert data["kind"] in ("SCOPE", "WEIGHT_ACK")
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 1


def assert_hangar_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["daily_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_hangar_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "ACTIVE", "RELEASED", "CANCELLED")


def assert_paint_booth(data: dict):
    _assert_common(data)
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["cure_buffer_hours"], int)


def assert_booth_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")
    assert isinstance(data["scheduled_fee_cents"], int)


def assert_soft_good_lot(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "UNCERTIFIED", "IN_TEST", "CERTIFIED", "CERT_FAILED", "CERT_QUARANTINED",
    )
    assert isinstance(data["fail_count"], int) and data["fail_count"] >= 0


def assert_burn_test(data: dict):
    """Append-only record: id + created_at only (PRD §2.5); no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert_iso8601_3dp(data.get("created_at", ""), "created_at")
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a UUID"
    assert data["test_method"] in ("VERTICAL_12S", "VERTICAL_60S", "HORIZONTAL_25")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["test_sequence"], int) and data["test_sequence"] >= 1


def assert_weight_balance_record(data: dict):
    _assert_common(data)
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("PREPARED", "SIGNED_OFF", "SUPERSEDED")
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_quality_inspection(data: dict):
    _assert_common(data)
    assert data["inspection_type"] in ("PREP", "PAINT", "INTERIOR", "FINAL")
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED")


def assert_delay_event(data: dict):
    _assert_common(data)
    assert data["category"] in ("CUSTOMER_CAUSED", "CENTER_CAUSED", "FORCE_MAJEURE")
    assert data["status"] in ("REPORTED", "CONFIRMED", "DISPUTED")
    assert data["source"] in ("MANUAL", "CHANGE_ORDER")
    assert isinstance(data["event_seq"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["kind"] in ("DEPOSIT", "PROGRESS", "FINAL")
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOIDED")
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line.get("label"), str)
        assert isinstance(line.get("amount_cents"), int), (
            "every line is individually rounded half-up to integer cents (PRD §3.12)"
        )
    assert data["total_cents"] == sum(l["amount_cents"] for l in data["lines"]), (
        "total_cents must equal the sum of the rounded line amounts (PRD §3.12)"
    )
