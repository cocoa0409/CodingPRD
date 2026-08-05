"""Entity assertions, semantic timestamp comparison and conservation checkers."""

import re
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Instants — always compared semantically, never by raw string equality.
# --------------------------------------------------------------------------- #
def parse_instant(value, label: str = "timestamp") -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime.

    Accepts any number of fractional-second digits and either the trailing 'Z'
    or an explicit offset, so two renderings of the same instant compare equal.
    """
    assert isinstance(value, str) and value.strip(), (
        f"{label} must be a non-empty ISO 8601 string, got {value!r}"
    )
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:  # pragma: no cover - surfaced as an assertion
        raise AssertionError(f"{label} is not a parseable instant: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label: str = "timestamp") -> None:
    """Assert two ISO 8601 renderings denote the same instant."""
    got = parse_instant(actual, f"{label} (actual)")
    want = parse_instant(expected, f"{label} (expected)")
    assert got == want, (
        f"{label}: expected instant {want.isoformat()} (from {expected!r}), "
        f"got {got.isoformat()} (from {actual!r})"
    )


def assert_instant_plus_days(actual, anchor, days: int, label: str = "timestamp") -> None:
    """Assert `actual` is exactly `days` calendar days after `anchor`."""
    want = parse_instant(anchor, f"{label} anchor") + timedelta(days=days)
    got = parse_instant(actual, f"{label} (actual)")
    assert got == want, (
        f"{label}: expected {anchor!r} + {days}d = {want.isoformat()}, "
        f"got {got.isoformat()}"
    )


def assert_calendar_date(actual, expected: str, label: str = "date") -> None:
    """Assert a date-only field equals the expected YYYY-MM-DD calendar date."""
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert _DATE_RE.match(actual), (
        f"{label} must be a plain calendar date with no time component, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_is_iso_instant(value, label: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


# --------------------------------------------------------------------------- #
# Common structural assertions
# --------------------------------------------------------------------------- #
def assert_common_fields(data: dict, entity: str) -> None:
    """Every resource but LabResult carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert_is_iso_instant(data.get("created_at"), f"{entity}.created_at")
    assert_is_iso_instant(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity: str) -> None:
    """Immutable observations carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert_is_iso_instant(data.get("created_at"), f"{entity}.created_at")
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #
def assert_practitioner(data: dict) -> None:
    assert_common_fields(data, "Practitioner")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["credential"] in {
        "ND",
        "HEALTH_COACH",
        "DISPENSARY_TECH",
        "CLINICAL_DIRECTOR",
    }
    assert isinstance(data["licensed_state_codes"], list)
    assert isinstance(data["is_active"], bool)


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["state_code"], str)
    assert data["clinical_status"] in {"INTAKE", "ESTABLISHED", "INACTIVE"}
    assert data["scope_review_status"] in {
        "NONE",
        "UNDER_REVIEW",
        "CLEARED",
        "RESTRICTED",
    }
    assert data["clinical_write_gate"] in {
        "OPEN",
        "FROZEN_SCOPE_REVIEW",
        "FROZEN_RED_FLAG",
    }
    assert isinstance(data["red_flag_referral_open"], bool)
    assert isinstance(data["telehealth_consent"], bool)
    for field in (
        "intake_booking_score",
        "intake_protocol_score",
        "cash_charged_total_cents",
        "cash_refunded_total_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"Patient.{field} must be a non-negative integer, got {data[field]!r}"
        )


def assert_intake_section(data: dict) -> None:
    assert_common_fields(data, "IntakeSection")
    assert data["status"] in {"SUBMITTED", "ATTESTED", "EXPIRED"}
    assert data["section_type"] in {
        "CHIEF_COMPLAINT_TIMELINE",
        "SYSTEMS_REVIEW",
        "DIET_LIFESTYLE",
        "MEDICATIONS_SUPPLEMENTS",
        "FAMILY_HISTORY",
    }
    assert isinstance(data["weight"], int)
    assert_is_iso_instant(data.get("submitted_at"), "IntakeSection.submitted_at")


def assert_membership(data: dict) -> None:
    assert_common_fields(data, "Membership")
    assert data["tier"] in {"FOUNDATION", "CORE", "PREMIER"}
    assert data["status"] in {"ACTIVE", "PAUSED", "EXPIRED"}
    assert_calendar_date(
        data["cycle_start_date"], data["cycle_start_date"], "Membership.cycle_start_date"
    )
    assert_calendar_date(
        data["cycle_end_date"], data["cycle_end_date"], "Membership.cycle_end_date"
    )
    assert_membership_visit_conservation(data)
    assert_membership_lab_credit_conservation(data)


def assert_lab_order(data: dict) -> None:
    assert_common_fields(data, "LabOrder")
    assert data["panel_code"] in {
        "SERUM_METABOLIC",
        "DUTCH_HORMONE",
        "SALIVA_CORTISOL",
        "STOOL_GI_MAP",
    }
    assert data["specimen_type"] in {"SERUM", "DRIED_URINE", "SALIVA", "STOOL"}
    assert data["status"] in {
        "ORDERED",
        "WASHOUT_HOLD",
        "COLLECTED",
        "RESULTED",
        "CRITICAL_ESCALATED",
        "INTERPRETED",
        "CANCELLED",
    }
    assert data["funding_source"] in {"MEMBERSHIP_CREDIT", "CASH"}
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["lab_credit_cost"], int)
    assert isinstance(data["has_critical_result"], bool)


def assert_lab_result(data: dict) -> None:
    assert_append_only_fields(data, "LabResult")
    assert data["standard_band"] in {"LOW", "IN_RANGE", "HIGH"}
    assert data["optimal_band"] in {"BELOW_OPTIMAL", "OPTIMAL", "ABOVE_OPTIMAL"}
    assert isinstance(data["is_critical"], bool)
    assert isinstance(data["analyte_code"], str) and data["analyte_code"]


def assert_protocol(data: dict) -> None:
    assert_common_fields(data, "Protocol")
    assert data["status"] in {
        "DRAFT",
        "ISSUED",
        "ACTIVE",
        "COMPLETED",
        "SUPERSEDED",
        "DISCONTINUED",
    }
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["advancement_blocked"], bool)
    assert isinstance(data["interaction_flags"], list)
    assert isinstance(data["symptom_score_baseline"], int)


def assert_protocol_item(data: dict) -> None:
    assert_common_fields(data, "ProtocolItem")
    assert data["status"] in {"ACTIVE", "HELD", "DISCONTINUED", "COMPLETED"}
    assert isinstance(data["titration_step_no"], int)
    assert isinstance(data["titration_locked"], bool)
    assert data["last_decision"] in {None, "ADVANCE", "HOLD", "REDUCE", "DISCONTINUE"}


def assert_dispensary_product(data: dict) -> None:
    assert_common_fields(data, "DispensaryProduct")
    assert data["supplement_class"] in {
        "HORMONE_SUPPORT",
        "ADAPTOGEN",
        "PROBIOTIC",
        "BOTANICAL",
        "VITAMIN_MINERAL",
        "ENZYME",
    }
    assert data["interaction_severity"] in {"NONE", "MODERATE", "SEVERE"}
    assert isinstance(data["stock_on_hand"], int) and data["stock_on_hand"] >= 0


def assert_product_lot(data: dict) -> None:
    assert_common_fields(data, "ProductLot")
    assert isinstance(data["quantity_initial"], int)
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["is_quarantined"], bool)
    assert isinstance(data["is_expired"], bool)


def assert_dispense(data: dict) -> None:
    assert_common_fields(data, "Dispense")
    assert data["status"] in {"DISPENSED", "REVERSED"}
    assert data["pricing_variant"] in {"RETAIL", "MEMBER", "PRACTITIONER_COST"}
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert data["total_price_cents"] == data["unit_price_cents"] * data["quantity"], (
        "Dispense.total_price_cents must be unit_price_cents multiplied by quantity"
    )


def assert_encounter(data: dict) -> None:
    assert_common_fields(data, "Encounter")
    assert data["modality"] in {"IN_PERSON", "TELEHEALTH", "EVISIT"}
    assert data["scheduling_status"] in {
        "SCHEDULED",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    }
    assert data["billing_status"] in {
        "CASH_PENDING",
        "ENTITLEMENT_RESERVED",
        "ENTITLEMENT_CONSUMED",
        "CASH_CHARGED",
        "SUPERBILLED",
        "REFUNDED",
        "FORFEITED",
    }
    assert isinstance(data["cash_charged_cents"], int)
    assert isinstance(data["entitlement_consumed"], bool)


def assert_message_thread(data: dict) -> None:
    assert_common_fields(data, "MessageThread")
    assert data["status"] in {"OPEN", "ANSWERED", "CONVERTED_TO_EVISIT", "CLOSED"}
    assert isinstance(data["patient_message_count"], int)
    assert isinstance(data["clinician_message_count"], int)
    assert isinstance(data["clinical_minutes_total"], int)
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["evisit_conversion_eligible"], bool)


def assert_superbill(data: dict) -> None:
    assert_common_fields(data, "Superbill")
    assert data["status"] in {
        "DRAFT",
        "ISSUED",
        "VOIDED",
        "DENIED",
        "APPEALED",
        "CLOSED",
    }
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    for field in (
        "billable_total_cents",
        "non_billable_membership_cents",
        "excluded_supplement_cents",
    ):
        assert isinstance(data[field], int), f"Superbill.{field} must be an integer"


def assert_referral(data: dict) -> None:
    assert_common_fields(data, "Referral")
    assert data["referral_type"] in {"ROUTINE", "RED_FLAG_AUTO"}
    assert data["status"] in {
        "SENT",
        "ACKNOWLEDGED",
        "REPORT_RECEIVED",
        "CLOSED",
        "DECLINED",
        "ABANDONED",
    }
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert_calendar_date(
        data["due_by_date"], data["due_by_date"], "Referral.due_by_date"
    )


# --------------------------------------------------------------------------- #
# Conservation invariants
# --------------------------------------------------------------------------- #
def assert_membership_visit_conservation(membership: dict) -> None:
    granted = membership["visits_granted"]
    total = (
        membership["visits_consumed"]
        + membership["visits_remaining"]
        + membership["visits_forfeited"]
    )
    assert granted == total, (
        "visits_granted must equal visits_consumed + visits_remaining + "
        f"visits_forfeited: {granted} != {membership['visits_consumed']} + "
        f"{membership['visits_remaining']} + {membership['visits_forfeited']}"
    )


def assert_membership_lab_credit_conservation(membership: dict) -> None:
    granted = membership["lab_credits_granted"]
    total = (
        membership["lab_credits_consumed"]
        + membership["lab_credits_remaining"]
        + membership["lab_credits_forfeited"]
    )
    assert granted == total, (
        "lab_credits_granted must equal lab_credits_consumed + "
        f"lab_credits_remaining + lab_credits_forfeited: {granted} != {total}"
    )


def assert_lot_conservation(lot: dict, dispensed_quantities) -> None:
    """quantity_initial == quantity_on_hand + every still-DISPENSED quantity."""
    outstanding = sum(dispensed_quantities)
    assert lot["quantity_initial"] == lot["quantity_on_hand"] + outstanding, (
        "quantity_initial must equal quantity_on_hand plus the total quantity "
        f"across every DISPENSED dispense drawn from the lot: "
        f"{lot['quantity_initial']} != {lot['quantity_on_hand']} + {outstanding}"
    )


def assert_cash_ledger_monotonic(before: dict, after: dict) -> None:
    """Both lifetime cash counters only ever grow."""
    assert after["cash_charged_total_cents"] >= before["cash_charged_total_cents"], (
        "cash_charged_total_cents must never decrease"
    )
    assert after["cash_refunded_total_cents"] >= before["cash_refunded_total_cents"], (
        "cash_refunded_total_cents must never decrease"
    )
