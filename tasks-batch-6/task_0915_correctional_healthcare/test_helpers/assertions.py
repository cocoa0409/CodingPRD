"""Entity assertions, instant comparison and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

import pytest

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Instant comparison ───────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z, optional fractional
    seconds of any width, and an explicit +00:00 offset. Returns a tz-aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:  # pragma: no cover - surfaced as a test failure
        raise AssertionError(f"Not a parseable ISO 8601 instant: {value!r} ({exc})")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Compare two timestamps SEMANTICALLY, never by string equality.

    `2026-03-01T00:00:00.000Z` and `2026-03-01T00:00:00Z` denote the same instant and
    must compare equal; only the instants they name are asserted here.
    """
    assert actual is not None, f"{label} is null, expected {expected}"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected} ({want}), got {actual} ({got})"


def assert_instant_is_null(actual: Optional[str], label: str = "timestamp") -> None:
    assert actual is None, f"{label}: expected null, got {actual!r}"


# ─── Common envelope field assertions ─────────────────

def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """Every persisted resource carries a server-minted UUID `id` with no type prefix and
    an ISO 8601 UTC `created_at` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID string with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict, entity: str = "resource") -> None:
    """Resources outside the two immutable audit records also carry updated_at + version."""
    assert_common_fields(data, entity)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_audit_record_fields(data: dict, entity: str = "audit record") -> None:
    """ChronicCareVisit and LedgerEntry carry only id and created_at — no updated_at
    field and no version field at all (PRD §2.4)."""
    assert_common_fields(data, entity)
    assert "updated_at" not in data, f"{entity} must have no updated_at field"
    assert "version" not in data, f"{entity} must have no version field"


# ─── Per-entity assertions ────────────────────────────

def assert_inmate(data: dict) -> None:
    assert_versioned_fields(data, "Inmate")
    assert isinstance(data["booking_number"], str) and data["booking_number"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["facility_code"], str)
    assert data["custody_level"] in ("MINIMUM", "MEDIUM", "MAXIMUM")
    assert data["admission_type"] in ("NEW_BOOKING", "INTER_FACILITY_TRANSFER")
    assert data["custody_status"] in ("IN_CUSTODY", "RELEASED", "DECEASED")
    assert data["records_state"] in ("OPEN", "FROZEN")
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["indigent_flag"], bool)
    assert isinstance(data["open_sick_call_count"], int)
    assert isinstance(data["no_show_count"], int)


def assert_intake_screening(data: dict) -> None:
    assert_versioned_fields(data, "IntakeScreening")
    assert data["screening_type"] in ("RECEIVING", "FULL_ASSESSMENT")
    assert data["status"] in ("PENDING", "COMPLETED", "OVERDUE", "REFUSED")
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601 UTC"
    assert isinstance(data["inmate_id"], str)


def assert_chronic_enrollment(data: dict) -> None:
    assert_versioned_fields(data, "ChronicCareEnrollment")
    assert data["condition_code"] in (
        "DIABETES", "HYPERTENSION", "ASTHMA", "SEIZURE_DISORDER", "HIV",
    )
    assert data["severity"] in ("MILD", "MODERATE", "SEVERE")
    assert data["tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["periodicity_days"], int)
    assert data["status"] in ("ACTIVE", "LAPSED", "RESOLVED")
    assert isinstance(data["missed_visit_count"], int)
    assert isinstance(data["escalated"], bool)


def assert_chronic_visit(data: dict) -> None:
    assert_audit_record_fields(data, "ChronicCareVisit")
    assert data["outcome"] in ("COMPLETED", "MISSED", "REFUSED")
    assert isinstance(data["enrollment_id"], str)
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"
    assert isinstance(data["recorded_by_user_id"], str)


def assert_sick_call_request(data: dict) -> None:
    assert_versioned_fields(data, "SickCallRequest")
    assert data["status"] in (
        "SUBMITTED", "TRIAGED", "SCHEDULED", "SEEN", "CLOSED", "CANCELLED",
    )
    assert data["acuity"] in (None, "EMERGENT", "URGENT", "ROUTINE")
    assert isinstance(data["retriage_count"], int)
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["complaint_text"], str)


def assert_medication_order(data: dict) -> None:
    assert_versioned_fields(data, "MedicationOrder")
    assert data["drug_class"] in (
        "PSYCHOTROPIC", "CONTROLLED", "CHRONIC_MAINTENANCE", "ACUTE_SHORT_COURSE",
    )
    assert data["route_mode"] in ("DOT", "KOP")
    assert isinstance(data["doses_per_day"], int)
    assert 1 <= data["doses_per_day"] <= 4
    assert data["status"] in ("ACTIVE", "HELD", "DISCONTINUED", "COMPLETED")
    assert isinstance(data["consecutive_missed_count"], int)
    assert isinstance(data["consecutive_refused_count"], int)
    assert isinstance(data["escalated_to_prescriber"], bool)
    assert isinstance(data["forced_dot"], bool)
    assert_adherence_precision(data["adherence_pct"])


def assert_medication_administration(data: dict) -> None:
    assert_versioned_fields(data, "MedicationAdministration")
    assert data["outcome"] in (
        "SCHEDULED", "ADMINISTERED", "REFUSED", "MISSED", "VOIDED",
    )
    assert data["timing_class"] in (None, "ON_TIME", "LATE", "MISSED_WINDOW")
    assert isinstance(data["order_id"], str)


def assert_specialty_referral(data: dict) -> None:
    assert_versioned_fields(data, "SpecialtyReferral")
    assert data["specialty"] in (
        "CARDIOLOGY", "ONCOLOGY", "ORTHOPEDICS", "OPHTHALMOLOGY", "DIALYSIS",
    )
    assert data["urgency"] in ("EMERGENT", "ROUTINE")
    assert data["status"] in (
        "REQUESTED", "PENDING_UR", "AUTHORIZED", "DENIED", "SCHEDULED",
        "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["no_show_count"], int)


def assert_utilization_review(data: dict) -> None:
    assert_versioned_fields(data, "UtilizationReview")
    assert data["status"] in (
        "OPEN", "APPROVED", "DENIED", "DEFERRED", "PEER_REVIEW", "OVERTURNED", "UPHELD",
    )
    assert data["decision"] in (None, "APPROVE", "DENY", "DEFER")
    assert isinstance(data["defer_count"], int)
    assert isinstance(data["turnaround_breached"], bool)
    assert isinstance(data["retrospective"], bool)


def assert_transport_order(data: dict) -> None:
    assert_versioned_fields(data, "TransportOrder")
    assert data["status"] in (
        "DRAFT", "ESCORT_ASSIGNED", "DISPATCHED", "COMPLETED", "NO_SHOW", "CANCELLED",
    )
    assert data["required_escort_level"] in ("ESCORT_1", "ESCORT_2", "ESCORT_2_ARMED")
    assert data["assigned_escort_level"] in (
        None, "ESCORT_1", "ESCORT_2", "ESCORT_2_ARMED",
    )
    assert isinstance(data["lead_minutes"], int)


def assert_copay_charge(data: dict) -> None:
    assert_versioned_fields(data, "CopayCharge")
    assert data["charge_variant"] in ("EXEMPT", "FUNDED", "INDIGENT")
    assert data["status"] in ("POSTED", "WAIVED", "REVERSED", "DEBT_LIEN")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["scheduled_amount_cents"], int)
    assert isinstance(data["indigency_snapshot"], bool)


def assert_ledger_entry(data: dict) -> None:
    assert_audit_record_fields(data, "LedgerEntry")
    assert data["entry_type"] in ("DEPOSIT", "CHARGE", "LIEN", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)


def assert_grievance(data: dict) -> None:
    assert_versioned_fields(data, "Grievance")
    assert data["stage"] in ("INFORMAL", "FORMAL", "APPEAL")
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "DECIDED", "REMANDED", "CLOSED", "WITHDRAWN",
    )
    assert data["outcome"] in (None, "GRANTED", "DENIED", "WITHDRAWN")
    assert isinstance(data["remand_count"], int)
    assert isinstance(data["response_breached"], bool)


def assert_release_plan(data: dict) -> None:
    assert_versioned_fields(data, "ReleasePlan")
    assert data["release_type"] in ("SCHEDULED", "UNEXPECTED")
    assert data["status"] in ("DRAFT", "FINALIZED", "EXECUTED", "VOIDED")
    assert isinstance(data["bridge_supply_total_days"], int)
    assert isinstance(data["bridge_supply_lines"], list)
    assert isinstance(data["reentry_referral_required"], bool)
    assert isinstance(data["records_packet_ready"], bool)


def assert_mortality_review(data: dict) -> None:
    assert_versioned_fields(data, "MortalityReview")
    assert data["manner"] in (
        "NATURAL", "ACCIDENT", "SUICIDE", "HOMICIDE", "UNDETERMINED",
    )
    assert data["status"] in ("OPEN", "CORRECTIVE_ACTIONS_ISSUED", "CLOSED")
    assert isinstance(data["corrective_action_count"], int)
    assert isinstance(data["corrective_actions"], list)
    assert isinstance(data["closed_late"], bool)


# ─── Domain invariant checkers ────────────────────────

def assert_adherence_precision(value) -> None:
    """Adherence percentages are numbers carried to exactly 2 decimal places (PRD §2.8)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"adherence_pct must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"adherence_pct {value} carries more than 2 decimal places"
    )
    assert 0 <= float(value) <= 100, f"adherence_pct out of range: {value}"


def assert_adherence_equals(actual, expected) -> None:
    assert float(actual) == pytest.approx(float(expected), abs=0.005), (
        f"Expected adherence_pct {expected}, got {actual}"
    )


def assert_money_invariant(entries: list, inmate: dict) -> None:
    """PRD §2.9 money invariant: the sum of amount_cents across an inmate's ledger
    entries equals account_balance_cents, and the last entry's balance_after_cents
    equals it too."""
    total = sum(e["amount_cents"] for e in entries)
    assert total == inmate["account_balance_cents"], (
        f"Sum of ledger amount_cents {total} != account_balance_cents "
        f"{inmate['account_balance_cents']}"
    )
    if entries:
        assert entries[-1]["balance_after_cents"] == inmate["account_balance_cents"], (
            "balance_after_cents on the chronologically last entry must equal "
            "account_balance_cents"
        )


def assert_dose_partition(administrations: list, expected_total: int) -> None:
    """PRD §2.9 dose-count invariant: the five outcome buckets partition the order's
    administration rows exactly."""
    buckets = {"SCHEDULED": 0, "ADMINISTERED": 0, "REFUSED": 0, "MISSED": 0, "VOIDED": 0}
    for row in administrations:
        assert row["outcome"] in buckets, f"Unexpected outcome {row['outcome']!r}"
        buckets[row["outcome"]] += 1
    assert sum(buckets.values()) == expected_total, (
        f"Five outcome buckets sum to {sum(buckets.values())}, expected {expected_total}"
    )
    assert len(administrations) == expected_total, (
        f"Expected {expected_total} administration rows, got {len(administrations)}"
    )
    return buckets


def bucket_counts(administrations: list) -> dict:
    buckets = {"SCHEDULED": 0, "ADMINISTERED": 0, "REFUSED": 0, "MISSED": 0, "VOIDED": 0}
    for row in administrations:
        buckets[row["outcome"]] += 1
    return buckets
