"""Per-entity shape assertions and domain invariant checkers."""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BILLABLE_CENTS_PER_UNIT,
    BILLABLE_UNIT_MINUTES,
    REMINDER_CADENCE_CODE_BY_TIER,
    TIER_ELEVATED_FLOOR,
    TIER_INTENSIVE_FLOOR,
)
from .types import (
    AuthStatus,
    BookingClass,
    ChairStatus,
    ChairType,
    DoseTier,
    LabResultStatus,
    LotStatus,
    NurseStatus,
    PlanStatus,
    PreparationStatus,
    ReadinessStatus,
    ReminderChannel,
    ReminderOutcome,
    ReminderTier,
    ScheduleStatus,
    SteeringStatus,
    TemplateStatus,
)


# ---------------------------------------------------------------------------
# Audit field helpers
# ---------------------------------------------------------------------------
def assert_versioned_audit_fields(row: Dict[str, Any]) -> None:
    """Assert the four audit fields carried by every versioned resource kind."""
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC instant, got {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC instant, got {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1 on creation"


def assert_immutable_audit_fields(row: Dict[str, Any]) -> None:
    """Assert the audit surface of the one resource kind that is never mutated."""
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC instant, got {row['created_at']!r}"
    )
    assert "updated_at" not in row, "a filed draw carries no updated_at"
    assert "version" not in row, "a filed draw carries no version"


# ---------------------------------------------------------------------------
# Entity shape assertions
# ---------------------------------------------------------------------------
def assert_infusion_center(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert isinstance(row["name"], str) and row["name"].strip()
    for field in (
        "open_minute",
        "close_minute",
        "turnover_buffer_minutes",
        "urgent_reserve_chair_count",
        "addon_cutoff_minute",
        "lab_validity_hours",
        "stagger_grid_minutes",
        "acuity_slot_minutes",
        "available_chair_count",
        "reserved_chair_count",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
    assert 0 <= row["open_minute"] < row["close_minute"] <= 1440
    assert row["open_minute"] <= row["addon_cutoff_minute"] <= row["close_minute"]
    assert row["reserved_chair_count"] <= row["available_chair_count"]


def assert_chair(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["center_id"])
    assert isinstance(row["label"], str) and 1 <= len(row["label"]) <= 16
    assert row["chair_type"] in (
        ChairType.STANDARD,
        ChairType.BARIATRIC,
        ChairType.ISOLATION,
    )
    assert row["status"] in (ChairStatus.AVAILABLE, ChairStatus.OUT_OF_SERVICE)
    assert isinstance(row["reserved_for_urgent"], bool)
    assert isinstance(row["committed_minutes"], int) and row["committed_minutes"] >= 0
    assert not (
        row["status"] == ChairStatus.OUT_OF_SERVICE and row["reserved_for_urgent"]
    ), "no chair may be simultaneously OUT_OF_SERVICE and reserved_for_urgent"


def assert_nurse(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["center_id"])
    assert isinstance(row["full_name"], str) and row["full_name"].strip()
    assert 1 <= row["acuity_capacity_points"] <= 20
    assert 0 <= row["shift_start_minute"] < row["shift_end_minute"] <= 1440
    assert row["status"] in (NurseStatus.ACTIVE, NurseStatus.INACTIVE)
    assert (
        isinstance(row["assigned_acuity_points"], int)
        and row["assigned_acuity_points"] >= 0
    )


def assert_drug(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert isinstance(row["name"], str) and row["name"].strip()
    assert isinstance(row["is_biosimilar"], bool)
    if not row["is_biosimilar"]:
        assert row.get("reference_drug_id") is None, (
            "reference_drug_id must be null whenever is_biosimilar is false"
        )
    assert 5 <= row["base_administration_minutes"] <= 480
    assert 5 <= row["min_administration_minutes"] <= 480
    assert 0 <= row["premedication_minutes"] <= 120
    assert 0 <= row["observation_minutes_first_dose"] <= 240
    assert 0 <= row["observation_minutes_subsequent"] <= 240
    assert 1 <= row["acuity_points"] <= 10
    assert 15 <= row["prep_stability_minutes"] <= 1440
    assert row["unit_cost_cents"] >= 0
    assert isinstance(row["requires_lab_gate"], bool)


def assert_drug_lot(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["drug_id"])
    assert isinstance(row["lot_number"], str) and 1 <= len(row["lot_number"]) <= 32
    for field in (
        "units_received",
        "units_committed",
        "units_administered",
        "units_wasted",
        "units_returned",
        "units_available",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
        assert row[field] >= 0, f"{field} must not be negative"
    assert row["status"] in (LotStatus.AVAILABLE, LotStatus.DEPLETED, LotStatus.EXPIRED)
    assert_lot_ledger_conserved(row)


def assert_patient(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert isinstance(row["mrn"], str) and 1 <= len(row["mrn"]) <= 32
    assert isinstance(row["full_name"], str) and row["full_name"].strip()
    assert 1 <= row["weight_kg"] <= 400
    assert row["completed_appointment_count"] >= 0
    assert row["no_show_strikes"] >= 0
    assert row["no_show_risk_score"] >= 0
    assert row["reminder_tier"] in (
        ReminderTier.STANDARD,
        ReminderTier.ELEVATED,
        ReminderTier.INTENSIVE,
    )
    assert row["waste_liability_cents"] >= 0
    assert row["steering_status"] in (
        SteeringStatus.SUITE,
        SteeringStatus.HOME_INFUSION_REVIEW,
    )
    assert_reminder_tier_matches_score(row["no_show_risk_score"], row["reminder_tier"])


def assert_treatment_plan(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["patient_id"])
    assert is_valid_uuid(row["drug_id"])
    assert 0 < row["dose_mg_per_kg"] <= 100
    assert 1 <= row["total_cycles"] <= 52
    assert isinstance(row["premed_waived"], bool)
    assert row["status"] in (
        PlanStatus.ACTIVE,
        PlanStatus.SUSPENDED,
        PlanStatus.COMPLETED,
        PlanStatus.SUPERSEDED,
    )
    assert row["completed_cycles"] >= 0
    assert isinstance(row["first_dose_completed"], bool)
    assert row["first_dose_completed"] == (row["completed_cycles"] >= 1), (
        "first_dose_completed is true exactly when completed_cycles is 1 or more"
    )


def assert_appointment_template(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["center_id"])
    assert is_valid_uuid(row["drug_id"])
    assert row["dose_tier"] in (DoseTier.LOW, DoseTier.MID, DoseTier.HIGH)
    for field in (
        "base_admin_minutes",
        "min_admin_minutes",
        "premed_minutes",
        "observation_minutes_first",
        "observation_minutes_subsequent",
        "acuity_points",
        "stagger_offset_minutes",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
    assert row["status"] in (TemplateStatus.ACTIVE, TemplateStatus.RETIRED)


def assert_appointment(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["center_id"])
    assert is_valid_uuid(row["patient_id"])
    assert is_valid_uuid(row["treatment_plan_id"])
    assert is_valid_uuid(row["template_id"])
    assert row["schedule_status"] in (
        ScheduleStatus.TENTATIVE,
        ScheduleStatus.CONFIRMED,
        ScheduleStatus.CHECKED_IN,
        ScheduleStatus.INFUSING,
        ScheduleStatus.OBSERVING,
        ScheduleStatus.COMPLETED,
        ScheduleStatus.CANCELLED,
        ScheduleStatus.NO_SHOW,
    )
    assert row["readiness_status"] in (
        ReadinessStatus.PENDING,
        ReadinessStatus.AUTH_CLEARED,
        ReadinessStatus.LAB_CLEARED,
        ReadinessStatus.FULLY_CLEARED,
        ReadinessStatus.BLOCKED,
    )
    assert row["booking_class"] in (
        BookingClass.ROUTINE,
        BookingClass.SAME_DAY_ADDON,
        BookingClass.URGENT,
    )
    for field in (
        "premed_minutes",
        "admin_minutes",
        "observation_minutes",
        "observation_extension_minutes",
        "chair_minutes",
        "acuity_points",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
        assert row[field] >= 0
    assert_window_arithmetic(row)


def assert_authorization_request(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["appointment_id"])
    assert is_valid_uuid(row["treatment_plan_id"])
    assert isinstance(row["payer_name"], str) and row["payer_name"].strip()
    assert row["status"] in (
        AuthStatus.DRAFT,
        AuthStatus.SUBMITTED,
        AuthStatus.APPROVED,
        AuthStatus.PENDED,
        AuthStatus.DENIED,
        AuthStatus.EXPIRED,
    )
    assert isinstance(row["submission_count"], int)
    assert 0 <= row["submission_count"] <= 3


def assert_drug_preparation(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["appointment_id"])
    assert is_valid_uuid(row["drug_lot_id"])
    assert 1 <= row["units_requested"] <= 100
    assert row["status"] in (
        PreparationStatus.REQUESTED,
        PreparationStatus.PREPARED,
        PreparationStatus.ADMINISTERED,
        PreparationStatus.WASTED,
        PreparationStatus.RETURNED,
    )


def assert_adverse_event(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["appointment_id"])
    assert is_valid_uuid(row["reported_by_nurse_id"])
    assert 1 <= row["grade"] <= 4
    assert row["action"] in ("SLOW_RATE", "HOLD", "ABORT")
    assert row["status"] in ("REPORTED", "UNDER_REVIEW", "CLOSED")
    assert isinstance(row["observation_extension_minutes"], int)


def assert_lab_result(row: Dict[str, Any]) -> None:
    assert_immutable_audit_fields(row)
    assert is_valid_uuid(row["patient_id"])
    assert isinstance(row["collected_at"], str) and row["collected_at"]
    assert row["status"] in (LabResultStatus.PENDING, LabResultStatus.RESULTED)
    if row["status"] == LabResultStatus.RESULTED:
        assert row.get("anc_value") is not None
        assert row.get("platelet_value") is not None


def assert_reminder_contact(row: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(row)
    assert is_valid_uuid(row["appointment_id"])
    assert is_valid_uuid(row["patient_id"])
    assert row["channel"] in (
        ReminderChannel.SMS,
        ReminderChannel.VOICE,
        ReminderChannel.PORTAL,
    )
    assert isinstance(row["sequence_number"], int) and row["sequence_number"] >= 1
    assert row["outcome"] in (
        ReminderOutcome.NO_RESPONSE,
        ReminderOutcome.CONFIRM_ATTENDANCE,
        ReminderOutcome.CANCEL_REQUEST,
    )


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and optional fraction."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str) -> None:
    """Compare two UTC instants by value, so a fractional-second suffix does not matter."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"expected the instant {expected}, got {actual}"
    )


def assert_lot_ledger_conserved(lot: Dict[str, Any]) -> None:
    """units_available is received less committed, administered and wasted."""
    expected = (
        lot["units_received"]
        - lot["units_committed"]
        - lot["units_administered"]
        - lot["units_wasted"]
    )
    assert lot["units_available"] == expected, (
        "units_available must equal units_received less units_committed, "
        f"units_administered and units_wasted; got {lot['units_available']} "
        f"against {expected} (units_returned is outside the balance)"
    )


def assert_window_arithmetic(appointment: Dict[str, Any]) -> None:
    """chair_minutes is premed plus admin plus observation, and end is start plus it."""
    assert (
        appointment["chair_minutes"]
        == appointment["premed_minutes"]
        + appointment["admin_minutes"]
        + appointment["observation_minutes"]
    ), "chair_minutes must be premed_minutes plus admin_minutes plus observation_minutes"
    if appointment.get("start_minute") is not None and appointment.get("end_minute") is not None:
        assert (
            appointment["end_minute"]
            == appointment["start_minute"] + appointment["chair_minutes"]
        ), "end_minute must be start_minute plus chair_minutes"


def assert_reminder_tier_matches_score(score: float, tier: str) -> None:
    """reminder_tier is read straight off the persisted risk score."""
    if score < TIER_ELEVATED_FLOOR:
        expected = ReminderTier.STANDARD
    elif score < TIER_INTENSIVE_FLOOR:
        expected = ReminderTier.ELEVATED
    else:
        expected = ReminderTier.INTENSIVE
    assert tier == expected, (
        f"a score of {score} implies reminder_tier {expected}, got {tier}"
    )


def assert_cadence_code_matches_tier(cadence_code: str, tier: str) -> None:
    assert cadence_code == REMINDER_CADENCE_CODE_BY_TIER[tier], (
        f"reminder tier {tier} implies cadence code "
        f"{REMINDER_CADENCE_CODE_BY_TIER[tier]}, got {cadence_code}"
    )


def assert_two_decimal_places(value: float, expected: float) -> None:
    """A percentage or score carries two decimal places, rounded half up."""
    assert value == pytest.approx(expected, abs=0.005), (
        f"expected {expected} to two decimal places, got {value}"
    )


def assert_billable_units(
    appointment: Dict[str, Any], expected_units: Optional[int] = None
) -> None:
    """Realised chair time divided by 15 and rounded up to a whole unit."""
    realised = appointment["actual_end_minute"] - appointment["actual_start_minute"]
    computed = math.ceil(realised / BILLABLE_UNIT_MINUTES)
    assert appointment["billable_chair_units"] == computed, (
        f"a {realised}-minute occupancy bills {computed} quarter-hour units, "
        f"got {appointment['billable_chair_units']}"
    )
    if expected_units is not None:
        assert appointment["billable_chair_units"] == expected_units


def assert_day_billing(summary: Dict[str, Any]) -> None:
    """day_billable_cents is day_billable_units multiplied by 9,000 cents."""
    assert (
        summary["day_billable_cents"]
        == summary["day_billable_units"] * BILLABLE_CENTS_PER_UNIT
    ), "day_billable_cents must be day_billable_units multiplied by 9,000 cents"


def assert_utilization_report(report: Dict[str, Any]) -> None:
    """The percentage is occupied over available, times 100, to two decimals."""
    assert isinstance(report["available_chair_minutes"], int)
    assert isinstance(report["occupied_chair_minutes"], int)
    assert isinstance(report["appointment_count"], int)
    assert isinstance(report["biosimilar_savings_cents"], int)
    if report["available_chair_minutes"] == 0:
        assert report["utilization_pct"] == pytest.approx(0.00, abs=0.005), (
            "a centre with no available chair minutes reports exactly 0.00"
        )
    else:
        expected = (
            report["occupied_chair_minutes"] / report["available_chair_minutes"] * 100
        )
        assert report["utilization_pct"] == pytest.approx(expected, abs=0.01)


def assert_committed_minutes(chair: Dict[str, Any], expected: int) -> None:
    assert chair["committed_minutes"] == expected, (
        f"chair {chair.get('label')} should hold {expected} committed minutes, "
        f"got {chair['committed_minutes']}"
    )


def assert_assigned_acuity(nurse: Dict[str, Any], expected: int) -> None:
    assert nurse["assigned_acuity_points"] == expected, (
        f"nurse should carry {expected} assigned acuity points, "
        f"got {nurse['assigned_acuity_points']}"
    )


def assert_bumped(appointment: Dict[str, Any]) -> None:
    """A bumped visit sits in TENTATIVE with both assignments cleared."""
    assert appointment["schedule_status"] == ScheduleStatus.TENTATIVE, (
        "a bumped visit's schedule_status becomes TENTATIVE"
    )
    assert appointment["chair_id"] is None, "a bumped visit's chair_id is cleared to null"
    assert appointment["nurse_id"] is None, "a bumped visit's nurse_id is cleared to null"


def assert_sweep_counters(
    report: Dict[str, Any],
    expired_lot_count: int,
    expired_authorization_count: int,
    wasted_preparation_count: int,
    no_show_count: int,
) -> None:
    assert report["expired_lot_count"] == expired_lot_count
    assert report["expired_authorization_count"] == expired_authorization_count
    assert report["wasted_preparation_count"] == wasted_preparation_count
    assert report["no_show_count"] == no_show_count


def assert_ordered_by(rows: List[Dict[str, Any]], *keys: str) -> None:
    """Assert the rows are non-decreasing under the given key sequence."""
    previous = None
    for row in rows:
        current = tuple(row[key] for key in keys)
        if previous is not None:
            assert previous <= current, (
                f"rows must be ordered by {keys}; {previous} preceded {current}"
            )
        previous = current
