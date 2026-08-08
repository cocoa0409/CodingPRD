"""Entity assertions, semantic timestamp comparison and domain invariants."""

from datetime import date, datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ─── Semantic instant / date comparison ─────────────────────────────────────
# The PRD fixes the timestamp *format* (ISO 8601 UTC with three fractional
# digits) but a faithful implementation may still render "…:00Z" or
# "…:00.000Z" for the same instant. Every timestamp comparison below therefore
# parses both sides into instants first; nothing compares rendered strings.


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value: str) -> date:
    """Parse a bare ISO calendar date (YYYY-MM-DD)."""
    assert isinstance(value, str) and value, f"Expected an ISO date, got {value!r}"
    return date.fromisoformat(value.strip()[:10])


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Assert two timestamps denote the same instant, ignoring how each side
    renders trailing zeros or the millisecond component."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected the instant {expected}, got {actual}"
    )


def assert_instant_at_or_after(actual: str, floor: str, label: str = "timestamp") -> None:
    assert parse_instant(actual) >= parse_instant(floor), (
        f"{label}: expected an instant at or after {floor}, got {actual}"
    )


def assert_instant_ordering(earlier: str, later: str, label: str = "ordering") -> None:
    """Assert `earlier` denotes an instant no later than `later`."""
    assert parse_instant(earlier) <= parse_instant(later), (
        f"{label}: expected {earlier} to be at or before {later}"
    )


def assert_same_date(actual: str, expected: str, label: str = "date") -> None:
    assert parse_date(actual) == parse_date(expected), (
        f"{label}: expected the date {expected}, got {actual}"
    )


# ─── Common shape helpers ───────────────────────────────────────────────────


def assert_common_fields(data: dict, entity: str) -> None:
    """Every resource except the report snapshot carries id, created_at,
    updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )
    assert_instant_at_or_after(data["updated_at"], data["created_at"], f"{entity}.updated_at")


def assert_no_type_prefix(identifier: str) -> None:
    """Identifiers carry no type prefix and no embedded meaning (PRD §2.4)."""
    assert is_valid_uuid(identifier), f"Identifier must be a bare UUID, got {identifier!r}"


# ─── Per-entity assertions ──────────────────────────────────────────────────


def assert_school(data: dict) -> None:
    assert_common_fields(data, "School")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["site_code"], str) and 1 <= len(data["site_code"]) <= 16
    assert isinstance(data["sponsor_hospital_name"], str)
    assert data["program_status"] in ("ACTIVE", "SUSPENDED")
    assert 1 <= data["telehealth_concurrent_capacity"] <= 4
    assert data["telehealth_booked_minutes_total"] >= 0
    assert data["suspended_count"] >= 0


def assert_clinician(data: dict) -> None:
    assert_common_fields(data, "Clinician")
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_number"], str)
    assert data["discipline"] in ("MEDICAL", "BEHAVIORAL", "DENTAL")


def assert_student(data: dict) -> None:
    assert_common_fields(data, "Student")
    assert isinstance(data["first_name"], str)
    assert isinstance(data["last_name"], str)
    parse_date(data["date_of_birth"])
    assert data["payer_route"] in ("MEDICAID", "PRIVATE_INSURANCE", "SELF_PAY")
    assert data["discount_tier"] in ("TIER_A", "TIER_B", "TIER_C", "TIER_D", "TIER_E")
    assert data["immunization_compliance_status"] in (
        "COMPLIANT",
        "PROVISIONAL",
        "NON_COMPLIANT",
    )
    assert data["immunization_exemption_type"] in ("NONE", "MEDICAL", "RELIGIOUS")
    assert data["household_income_annual_cents"] >= 0
    assert data["household_size"] >= 1
    assert float(data["fpl_percent"]) >= 0
    assert_student_dose_counter_identity(data)


def assert_student_dose_counter_identity(data: dict) -> None:
    """`total_dose_count` is every dose row for that student and equals the sum
    of the other three (PRD §3.7)."""
    total = data["valid_dose_count"] + data["invalid_dose_count"] + data["voided_dose_count"]
    assert data["total_dose_count"] == total, (
        "Student.total_dose_count must equal valid + invalid + voided, "
        f"got {data['total_dose_count']} vs {total}"
    )


def assert_fpl_precision(fpl_percent) -> None:
    """Percentages of the federal poverty level are carried to exactly 2
    decimal places (PRD §2.8)."""
    value = float(fpl_percent)
    assert round(value, 2) == value, f"fpl_percent must carry 2 decimal places, got {fpl_percent}"


def assert_guardian(data: dict) -> None:
    assert_common_fields(data, "Guardian")
    assert isinstance(data["full_name"], str)
    assert data["relationship"] in ("MOTHER", "FATHER", "LEGAL_GUARDIAN", "OTHER")
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["is_primary"], bool)
    assert isinstance(data["notification_opt_out"], bool)


def assert_enrollment(data: dict) -> None:
    assert_common_fields(data, "Enrollment")
    assert data["status"] in ("PENDING", "ACTIVE", "WITHDRAWN", "TRANSFERRED")
    assert data["school_year"] in ("2025-2026", "2026-2027")
    assert data["reinstated_count"] >= 0
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["school_id"])


def assert_consent(data: dict) -> None:
    assert_common_fields(data, "Consent")
    assert data["category"] in (
        "GENERAL_TREATMENT",
        "BEHAVIORAL_HEALTH",
        "CONFIDENTIAL_SERVICES",
        "DENTAL",
        "TELEHEALTH",
    )
    assert data["granted_by"] in ("GUARDIAN", "STUDENT_SELF")
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED")
    assert is_iso8601_timestamp(data["effective_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_visit(data: dict) -> None:
    assert_common_fields(data, "Visit")
    assert data["visit_type"] in ("ACUTE", "BEHAVIORAL", "DENTAL", "SPORTS_PHYSICAL")
    assert data["delivery_mode"] in ("IN_PERSON", "TELEHEALTH")
    assert data["clinical_status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )
    assert data["billing_status"] in (
        "NOT_APPLICABLE",
        "PENDING_CHARGES",
        "CHARGES_POSTED",
        "REVERSED",
    )
    assert isinstance(data["confidential"], bool)
    assert_visit_bucket_residual_zero(data)


def assert_visit_bucket_residual_zero(visit: dict) -> None:
    """The visit-level residual — the gross bucket minus the sum of the
    payer-billed, patient-responsibility, write-off and no-charge buckets —
    must be exactly 0 (PRD §2.10)."""
    residual = visit["gross_charge_total_cents"] - (
        visit["payer_billed_total_cents"]
        + visit["patient_responsibility_total_cents"]
        + visit["write_off_total_cents"]
        + visit["no_charge_total_cents"]
    )
    assert residual == 0, (
        "Visit charge-bucket residual must be exactly 0, got "
        f"{residual} (gross={visit['gross_charge_total_cents']}, "
        f"payer_billed={visit['payer_billed_total_cents']}, "
        f"patient={visit['patient_responsibility_total_cents']}, "
        f"write_off={visit['write_off_total_cents']}, "
        f"no_charge={visit['no_charge_total_cents']})"
    )


def assert_visit_buckets(
    visit: dict, gross, no_charge, patient_responsibility, write_off, payer_billed
) -> None:
    """Assert all five encounter buckets at once and re-check the residual."""
    assert visit["gross_charge_total_cents"] == gross, (
        f"gross_charge_total_cents expected {gross}, got {visit['gross_charge_total_cents']}"
    )
    assert visit["no_charge_total_cents"] == no_charge, (
        f"no_charge_total_cents expected {no_charge}, got {visit['no_charge_total_cents']}"
    )
    assert visit["patient_responsibility_total_cents"] == patient_responsibility, (
        "patient_responsibility_total_cents expected "
        f"{patient_responsibility}, got {visit['patient_responsibility_total_cents']}"
    )
    assert visit["write_off_total_cents"] == write_off, (
        f"write_off_total_cents expected {write_off}, got {visit['write_off_total_cents']}"
    )
    assert visit["payer_billed_total_cents"] == payer_billed, (
        f"payer_billed_total_cents expected {payer_billed}, got {visit['payer_billed_total_cents']}"
    )
    assert_visit_bucket_residual_zero(visit)


def assert_clearance(data: dict) -> None:
    assert_common_fields(data, "SportsPhysicalClearance")
    assert data["outcome"] in (
        "CLEARED",
        "CLEARED_WITH_RESTRICTIONS",
        "NOT_CLEARED",
        "DEFERRED",
    )
    assert data["status"] in (
        "ACTIVE",
        "PENDING_REEVALUATION",
        "VOIDED",
        "EXPIRED",
        "SUPERSEDED",
    )
    parse_date(data["determination_date"])
    assert data["reevaluation_count"] >= 0


def assert_dose(data: dict) -> None:
    assert_common_fields(data, "ImmunizationDose")
    assert data["series_code"] in ("HEPB", "MMR")
    assert data["status"] in ("VALID", "INVALID_TOO_EARLY", "VOIDED")
    parse_date(data["administered_date"])
    if data["series_code"] == "HEPB":
        assert 1 <= data["dose_number"] <= 3
    else:
        assert 1 <= data["dose_number"] <= 2


def assert_screening(data: dict) -> None:
    assert_common_fields(data, "Screening")
    assert data["instrument"] in ("VISION", "HEARING", "DENTAL", "BMI", "BEHAVIORAL")
    assert data["outcome"] in ("PASS", "REFER")
    assert data["band_label"] in ("NORMAL", "ABNORMAL")
    assert data["status"] in ("RECORDED", "CLOSED_PASS", "REFERRED")
    assert float(data["numeric_result"]) >= 0
    # band_label mirrors outcome: NORMAL on a pass, ABNORMAL on a refer.
    expected_band = "NORMAL" if data["outcome"] == "PASS" else "ABNORMAL"
    assert data["band_label"] == expected_band, (
        f"band_label must mirror outcome: {data['outcome']} -> {expected_band}"
    )


def assert_referral(data: dict) -> None:
    assert_common_fields(data, "Referral")
    assert data["specialty"] in (
        "OPHTHALMOLOGY",
        "AUDIOLOGY",
        "DENTISTRY",
        "BEHAVIORAL_HEALTH",
        "PRIMARY_CARE",
        "NUTRITION",
    )
    assert data["status"] in (
        "OPEN",
        "OUTREACH_IN_PROGRESS",
        "SCHEDULED",
        "REPORT_RECEIVED",
        "CLOSED",
        "LOST_TO_FOLLOW_UP",
    )
    assert 0 <= data["outreach_attempt_count"] <= 3


def assert_charge(data: dict) -> None:
    assert_common_fields(data, "BillableCharge")
    assert data["service_category"] in (
        "ACUTE_OFFICE_VISIT",
        "BEHAVIORAL_THERAPY",
        "DENTAL_PREVENTIVE",
        "SPORTS_PHYSICAL_EXAM",
        "IMMUNIZATION_ADMIN",
        "TELEHEALTH_ENCOUNTER",
    )
    assert data["status"] in (
        "PENDING",
        "CLAIM_SUBMITTED",
        "CLAIM_DENIED",
        "CLAIM_APPEALED",
        "PAID",
        "WRITTEN_OFF",
        "NO_CHARGE",
        "REVERSED",
    )
    assert data["payer_route"] in ("MEDICAID", "PRIVATE_INSURANCE", "SELF_PAY")
    assert data["discount_tier_snapshot"] in (
        "TIER_A",
        "TIER_B",
        "TIER_C",
        "TIER_D",
        "TIER_E",
    )
    for field in (
        "gross_amount_cents",
        "provisional_patient_responsibility_cents",
        "floor_adjustment_cents",
        "patient_responsibility_cents",
        "payer_paid_amount_cents",
        "patient_paid_amount_cents",
        "write_off_amount_cents",
    ):
        assert isinstance(data[field], int), (
            f"BillableCharge.{field} must be a whole number of cents, got {data[field]!r}"
        )
    assert 0 <= data["appeal_count"] <= 2


def assert_notification(data: dict) -> None:
    assert_common_fields(data, "ParentNotification")
    assert data["event_type"] in (
        "VISIT_COMPLETED",
        "CLEARANCE_DETERMINED",
        "CLEARANCE_VOIDED",
        "REFERRAL_CREATED",
        "IMMUNIZATION_NON_COMPLIANT",
    )
    assert data["status"] in (
        "QUEUED",
        "SENT",
        "FAILED",
        "ACKNOWLEDGED",
        "UNDELIVERABLE",
        "SUPPRESSED_CONFIDENTIAL",
        "SUPPRESSED_OPT_OUT",
    )
    assert 0 <= data["delivery_attempt_count"] <= 3


def assert_telehealth_session(data: dict) -> None:
    assert_common_fields(data, "TelehealthSession")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert 15 <= data["duration_minutes"] <= 60
    assert 0 <= data["reschedule_count"] <= 2
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_report(data: dict) -> None:
    """A report carries id and created_at only — it has neither updated_at nor
    version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "AggregateReport.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "AggregateReport.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, "AggregateReport must not expose a version field"
    assert "updated_at" not in data, "AggregateReport must not expose an updated_at field"
    partition = (
        data["scheduled_visit_count"]
        + data["in_progress_visit_count"]
        + data["completed_visit_count"]
        + data["cancelled_visit_count"]
        + data["no_show_visit_count"]
    )
    assert data["total_visits"] == partition, (
        f"The five clinical-state counts must sum to total_visits exactly: "
        f"{partition} vs {data['total_visits']}"
    )


def assert_rate_precision(rate) -> None:
    """Closure rates are carried to exactly 4 decimal places (PRD §2.8)."""
    value = float(rate)
    assert round(value, 4) == value, f"Closure rate must carry 4 decimal places, got {rate}"


def assert_version_bumped_by(new_version: int, old_version: int, expected: int = 1) -> None:
    """Wherever the PRD says a version "increments", it means increments by
    exactly 1 (§2.4)."""
    assert new_version == old_version + expected, (
        f"Expected version to advance from {old_version} by exactly {expected}, "
        f"got {new_version}"
    )
