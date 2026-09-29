"""
Domain assertions for the Warewashing API.

These build on the framework's generic structural assertions and add the
entity-shaped checks the PRD pins: the common-field contract of §2.5, the
half-open window arithmetic of §2.12, the round-half-up rule of §2.6 and the
conserved ledgers of §2.10.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ─── Instant equality ──────────────────────────────────────────────────


def _canonical_instant(value: Any) -> str:
    """
    Reduce an ISO 8601 UTC instant to a precision-independent canonical form.

    The PRD pins a fractional-digit count for exactly two fields: it calls
    `api_request_timestamp` (§2.2) and `created_at` (§2.5) "an ISO 8601 UTC
    string with three fractional digits", and it pins `response_deadline_at`
    (§3.5) to "whole seconds". Every other instant it declares is only "an
    ISO 8601 UTC timestamp" — §2.5 on `updated_at`, and §2.4 on the instants
    the logical clock supplies (`installed_at`, `retrieved_at`,
    `dose_effective_at`, `last_calibrated_at`, the verification instant) — so
    the trailing `.000` is a serialisation choice the PRD leaves open rather
    than a rule a test may pin. Comparing through this function keeps the
    assertion on *which instant* the field holds, which the PRD does fix.
    """
    assert isinstance(value, str), f"instant is not a string: {value!r}"
    assert is_iso8601_timestamp(value), f"instant is not ISO 8601 UTC: {value!r}"
    text = value.strip()
    for suffix in ("Z", "z", "+00:00", "-00:00"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return f"{text}Z"


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """
    Assert two ISO 8601 UTC instants denote the same moment, independently of
    how many fractional digits the serialiser emitted (see
    `_canonical_instant`).
    """
    assert _canonical_instant(actual) == _canonical_instant(expected), (
        f"{field} expected {expected}, got {actual}"
    )


# ─── §2.5 Identity and common fields ───────────────────────────────────


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """
    Assert the §2.5 mutable-resource contract: a UUID `id` with no type prefix,
    an ISO 8601 `created_at`, an ISO 8601 `updated_at` and an integer `version`.
    """
    assert is_valid_uuid(entity.get("id")), f"id is not a bare UUID: {entity.get('id')}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"created_at is not ISO 8601: {entity.get('created_at')}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"updated_at is not ISO 8601: {entity.get('updated_at')}"
    )
    assert isinstance(entity.get("version"), int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1 on creation"


def assert_immutable_evidence_fields(entity: Dict[str, Any]) -> None:
    """
    Assert the §2.5 exception: a TelemetryReading or CalibrationRecord carries
    only `id` and `created_at` — both `updated_at` and `version` are absent.
    """
    assert is_valid_uuid(entity.get("id")), f"id is not a bare UUID: {entity.get('id')}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"created_at is not ISO 8601: {entity.get('created_at')}"
    )
    assert "updated_at" not in entity, (
        "updated_at must be absent from immutable evidence rows"
    )
    assert "version" not in entity, (
        "version must be absent from immutable evidence rows"
    )


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    """Assert an exact version value."""
    assert entity.get("version") == expected, (
        f"expected version {expected}, got {entity.get('version')}"
    )


# ─── §2.6 Rounding ─────────────────────────────────────────────────────


def round_half_up(value, digits: int = 0):
    """
    Round half up, the only rounding method in this API (§2.6): a value exactly
    at the midpoint rounds away from zero.
    """
    quant = Decimal(1).scaleb(-digits)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if digits == 0 else float(result)


def assert_cents(value: Any, expected: int) -> None:
    """Assert a monetary field is an integer number of whole cents (§2.6)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"monetary values are integer cents, got {value!r}"
    )
    assert value == expected, f"expected {expected} cents, got {value}"


def assert_pct(value: Any, expected: float) -> None:
    """Assert a percentage carried to two decimal places (§2.6)."""
    assert value is not None, "percentage must not be null here"
    assert value == pytest.approx(expected, abs=0.005), (
        f"expected {expected}, got {value}"
    )


def assert_two_dp(value: Any) -> None:
    """Assert a decimal is carried to at most two decimal places."""
    assert value == pytest.approx(round(float(value), 2), abs=1e-9), (
        f"{value} carries more than two decimal places"
    )


def assert_four_dp(value: Any) -> None:
    """Assert a decimal is carried to at most four decimal places."""
    assert value == pytest.approx(round(float(value), 4), abs=1e-9), (
        f"{value} carries more than four decimal places"
    )


# ─── Entity shape assertions ───────────────────────────────────────────


def assert_customer(customer: Dict[str, Any]) -> None:
    """Assert the §3.1 customer shape."""
    assert_common_fields(customer)
    assert isinstance(customer["name"], str)
    assert customer["billing_status"] in ("CURRENT", "CREDIT_HOLD")
    assert isinstance(customer["equipment_on_placement_value_cents"], int)
    assert isinstance(customer["active_agreement_count"], int)


def assert_site(site: Dict[str, Any]) -> None:
    """Assert the §3.1 site shape."""
    assert_common_fields(site)
    assert site["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert site["priority_tier"] in ("STANDARD", "PREMIUM")
    assert site["service_posture"] in ("NORMAL", "ELEVATED", "CRITICAL")
    assert isinstance(site["open_ticket_count"], int)


def assert_agreement(agreement: Dict[str, Any]) -> None:
    """Assert the §3.2 agreement shape."""
    assert_common_fields(agreement)
    assert agreement["status"] in (
        "DRAFT",
        "ACTIVE",
        "RENEWAL_PENDING",
        "EXPIRED",
        "TERMINATED",
        "VOID",
    )
    assert isinstance(agreement["renewal_count"], int)
    assert isinstance(agreement["placement_count"], int)
    assert isinstance(agreement["covered_product_ids"], list)


def assert_placement(placement: Dict[str, Any]) -> None:
    """Assert the §3.3 placement shape, including both independent axes."""
    assert_common_fields(placement)
    assert placement["placement_status"] in (
        "PENDING_INSTALL",
        "INSTALLED",
        "RETRIEVAL_SCHEDULED",
        "RETRIEVED",
        "CANCELLED",
    )
    assert placement["operational_status"] in ("UP", "DEGRADED", "DOWN", "OFFLINE")
    assert isinstance(placement["last_cycle_count"], int)
    assert isinstance(placement["cycles_since_calibration"], int)
    assert isinstance(placement["open_alert_count"], int)


def assert_axes(
    placement: Dict[str, Any],
    placement_status: Optional[str] = None,
    operational_status: Optional[str] = None,
) -> None:
    """Assert one or both of a placement's two independent status axes (§3.3)."""
    if placement_status is not None:
        assert placement["placement_status"] == placement_status, (
            f"placement_status expected {placement_status}, "
            f"got {placement['placement_status']}"
        )
    if operational_status is not None:
        assert placement["operational_status"] == operational_status, (
            f"operational_status expected {operational_status}, "
            f"got {placement['operational_status']}"
        )


def assert_dispenser(dispenser: Dict[str, Any]) -> None:
    """Assert the §3.4 dispenser shape."""
    assert_common_fields(dispenser)
    assert dispenser["dispenser_status"] in ("ACTIVE", "LOCKED_OUT", "REMOVED")
    if dispenser["lockout_reason"] is not None:
        assert dispenser["lockout_reason"] in (
            "EFFICACY_FAILURE",
            "AGREEMENT_ENDED",
            "INVESTIGATION_HOLD",
        )


def assert_lockout(
    dispenser: Dict[str, Any], status: str, reason: Optional[str]
) -> None:
    """Assert a dispenser's lifecycle state together with its lockout reason."""
    assert dispenser["dispenser_status"] == status, (
        f"dispenser_status expected {status}, got {dispenser['dispenser_status']}"
    )
    assert dispenser["lockout_reason"] == reason, (
        f"lockout_reason expected {reason}, got {dispenser['lockout_reason']}"
    )


def assert_telemetry_reading(reading: Dict[str, Any]) -> None:
    """Assert the §2.5 immutable-evidence shape of a telemetry reading."""
    assert_immutable_evidence_fields(reading)
    assert isinstance(reading["cycle_delta"], int)
    assert reading["source"] in ("DEVICE", "MANUAL_AUDIT")
    assert isinstance(reading["triggered_alert_types"], list)


def assert_alert(alert: Dict[str, Any]) -> None:
    """Assert the §3.4 alert shape."""
    assert_common_fields(alert)
    assert alert["severity"] in ("WARNING", "CRITICAL")
    assert alert["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED")


def assert_ticket(ticket: Dict[str, Any]) -> None:
    """Assert the §3.5 ticket shape."""
    assert_common_fields(ticket)
    assert ticket["origin"] in ("CUSTOMER_REPORT", "TELEMETRY_AUTO")
    assert ticket["status"] in (
        "QUEUED",
        "DISPATCHED",
        "ON_SITE",
        "PENDING_VERIFICATION",
        "CLOSED",
        "CANCELLED",
    )
    assert isinstance(ticket["priority_score"], int)
    assert 0 <= ticket["priority_score"] <= 1000
    assert isinstance(ticket["sla_breached"], bool)
    assert isinstance(ticket["escalation_level"], int)
    assert isinstance(ticket["requires_sanitation_cert"], bool)


def assert_visit(visit: Dict[str, Any]) -> None:
    """Assert the §3.6 visit shape."""
    assert_common_fields(visit)
    assert visit["visit_status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "SUBMITTED",
        "VERIFIED",
        "REJECTED",
        "CANCELLED",
    )
    assert isinstance(visit["calibration_record_count"], int)
    assert isinstance(visit["repair_confirmed"], bool)


def assert_calibration_record(record: Dict[str, Any]) -> None:
    """Assert the §2.5 immutable-evidence shape of a calibration record."""
    assert_immutable_evidence_fields(record)
    assert record["calibration_verdict"] in ("PASS", "ADJUSTED", "FAIL")
    assert record["efficacy_result"] in ("PASS", "FAIL", "NOT_APPLICABLE")
    assert isinstance(record["applied"], bool)


def assert_delivery(delivery: Dict[str, Any]) -> None:
    """Assert the §3.7 delivery shape."""
    assert_common_fields(delivery)
    assert delivery["status"] in ("DELIVERED", "VOIDED")
    assert isinstance(delivery["quantity_ml"], int)
    assert isinstance(delivery["amount_cents"], int)


def assert_review(review: Dict[str, Any]) -> None:
    """Assert the §3.7 variance review shape."""
    assert_common_fields(review)
    assert review["status"] in ("DRAFT", "PUBLISHED", "ESCALATED", "CLOSED")
    assert review["basis"] in ("NAMEPLATE", "AS_CALIBRATED")
    assert review["classification"] in (
        "INSUFFICIENT_DATA",
        "THEFT_SUSPECT",
        "DILUTION_SUSPECT",
        "OVERUSE",
        "UNDERUSE",
        "WITHIN_TOLERANCE",
    )


def assert_case(case: Dict[str, Any]) -> None:
    """Assert the §3.8 investigation case shape."""
    assert_common_fields(case)
    assert case["case_status"] in (
        "EVIDENCE_GATHERING",
        "PENDING_REVIEW",
        "SUBSTANTIATED",
        "UNSUBSTANTIATED",
    )
    assert case["remediation"] in (
        "NONE",
        "TRAINING",
        "DISPENSER_REPLACEMENT",
        "CHARGEBACK",
    )
    assert isinstance(case["chargeback_cents"], int)
    assert isinstance(case["evidence_item_count"], int)
    assert isinstance(case["return_count"], int)


# ─── §2.10 Conserved ledgers ───────────────────────────────────────────


def assert_equipment_ledger(customer: Dict[str, Any], expected_cents: int) -> None:
    """
    Assert the conserved equipment ledger of §2.10:
    `Customer.equipment_on_placement_value_cents` equals the summed
    `equipment_value_cents` of that customer's placements in
    {PENDING_INSTALL, INSTALLED, RETRIEVAL_SCHEDULED}.
    """
    assert_cents(customer["equipment_on_placement_value_cents"], expected_cents)


def assert_workload(technician: Dict[str, Any], expected: int) -> None:
    """
    Assert the conserved workload counter of §2.10:
    `Technician.open_ticket_count` equals the number of that technician's
    tickets in {DISPATCHED, ON_SITE, PENDING_VERIFICATION}.
    """
    assert technician["open_ticket_count"] == expected, (
        f"open_ticket_count expected {expected}, "
        f"got {technician['open_ticket_count']}"
    )


# ─── §2.12 Windows and §2.4 clock ──────────────────────────────────────


def assert_in_half_open_window(instant: str, start: str, end: str) -> None:
    """Assert an instant belongs to the half-open window [start, end) of §2.12."""
    assert start <= instant < end, (
        f"{instant} is not inside the half-open window [{start}, {end})"
    )


def assert_sweep_counters(
    data: Dict[str, Any],
    agreements_moved_to_renewal_pending: Optional[int] = None,
    agreements_expired: Optional[int] = None,
    tickets_escalated: Optional[int] = None,
    current_utc: Optional[str] = None,
) -> None:
    """Assert the four values the §2.4 clock advance reports."""
    for key in (
        "agreements_moved_to_renewal_pending",
        "agreements_expired",
        "tickets_escalated",
        "current_utc",
    ):
        assert key in data, f"clock response is missing {key}"
    if agreements_moved_to_renewal_pending is not None:
        assert (
            data["agreements_moved_to_renewal_pending"]
            == agreements_moved_to_renewal_pending
        )
    if agreements_expired is not None:
        assert data["agreements_expired"] == agreements_expired
    if tickets_escalated is not None:
        assert data["tickets_escalated"] == tickets_escalated
    if current_utc is not None:
        assert data["current_utc"] == current_utc


# ─── §2.3 Pagination envelope ──────────────────────────────────────────


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """Assert the four §2.3 pagination fields carried inside meta."""
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more


def assert_sorted_by_created_at(rows: list) -> None:
    """Assert the §2.3 default ordering: created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"
