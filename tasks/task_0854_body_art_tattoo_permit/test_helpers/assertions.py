"""Entity assertions, instant comparison and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Instant handling ──────────────────────────────────────────────────
# The PRD requires ISO 8601 UTC instants; comparisons below are made on the
# parsed instant so that a rendering with or without fractional digits is
# treated identically.


def parse_instant(value: str) -> datetime:
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, field: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    assert actual is not None, f"{field} must not be null (expected {expected})"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_iso_utc(value: str, field: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), f"{field} must be an ISO 8601 UTC instant, got {value!r}"


def assert_common_fields(data: dict, entity: str) -> None:
    """id / created_at / updated_at / version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a dashed UUID, got {data.get('id')!r}"
    assert_iso_utc(data.get("created_at", ""), f"{entity}.created_at")
    assert_iso_utc(data.get("updated_at", ""), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


# ─── Entity assertions ─────────────────────────────────────────────────


def assert_establishment(data: dict) -> None:
    assert_common_fields(data, "Establishment")
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["street_address"], str) and data["street_address"].strip()
    assert len(data["county_code"]) == 3 and data["county_code"].isupper()
    assert data["establishment_type"] in (
        "TATTOO",
        "PIERCING",
        "PERMANENT_COSMETICS",
        "COMBINED",
    )
    assert data["permit_status"] in (
        "PENDING_PLAN_REVIEW",
        "PENDING_INSPECTION",
        "ACTIVE",
        "SUSPENDED",
        "EXPIRED",
        "REVOKED",
    )
    assert data["operating_posture"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert data["sterilization_compliance_status"] in (
        "COMPLIANT",
        "DEFICIENT",
        "NONCOMPLIANT",
    )
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    for counter in (
        "open_violation_count",
        "open_critical_violation_count",
        "active_artist_count",
        "fees_paid_cents",
        "fees_refunded_cents",
        "plan_review_cycles_used",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Establishment.{counter} must be a non-negative integer, got {data.get(counter)!r}"
        )
    assert data["open_critical_violation_count"] <= data["open_violation_count"]


def assert_artist(data: dict) -> None:
    assert_common_fields(data, "Artist")
    assert is_valid_uuid(data["establishment_id"])
    assert isinstance(data["legal_name"], str) and data["legal_name"].strip()
    assert data["permit_status"] in (
        "PENDING",
        "ACTIVE",
        "PROBATION",
        "SUSPENDED",
        "INACTIVE",
        "REVOKED",
    )
    assert isinstance(data["bbp_recert_required"], bool)
    assert isinstance(data["confirmed_infection_count"], int)
    assert isinstance(data["suspension_count"], int)


def assert_plan_review(data: dict) -> None:
    assert_common_fields(data, "PlanReview")
    assert is_valid_uuid(data["establishment_id"])
    assert data["status"] in ("SUBMITTED", "CORRECTIONS_REQUIRED", "APPROVED", "DENIED")
    assert isinstance(data["floor_plan_reference"], str)
    assert float(data["sterilization_area_sqft"]) > 0
    assert isinstance(data["procedure_station_count"], int) and data["procedure_station_count"] >= 1
    assert isinstance(data["has_handwash_sink"], bool)
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 1


def assert_inspection(data: dict) -> None:
    assert_common_fields(data, "Inspection")
    assert is_valid_uuid(data["establishment_id"])
    assert data["inspection_type"] in ("PREOPENING", "ROUTINE", "COMPLAINT", "REINSPECTION")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELLED")
    assert_iso_utc(data["scheduled_start_at"], "Inspection.scheduled_start_at")
    assert_iso_utc(data["scheduled_end_at"], "Inspection.scheduled_end_at")
    assert parse_instant(data["scheduled_end_at"]) > parse_instant(data["scheduled_start_at"])
    assert isinstance(data["open_violation_count_at_start"], int)
    if data["score"] is not None:
        assert isinstance(data["score"], int) and 0 <= data["score"] <= 100


def assert_violation(data: dict) -> None:
    assert_common_fields(data, "Violation")
    assert is_valid_uuid(data["inspection_id"])
    assert data["severity"] in ("CRITICAL", "NONCRITICAL")
    assert data["status"] in ("ISSUED", "CORRECTION_SUBMITTED", "VERIFIED", "ESCALATED")
    assert_iso_utc(data["issued_at"], "Violation.issued_at")
    assert_iso_utc(data["abatement_due_at"], "Violation.abatement_due_at")
    assert isinstance(data["deduction_points"], int)
    assert float(data["repeat_multiplier_applied"]) in (1.0, 1.5)


def assert_sterilization_record(data: dict) -> None:
    """Immutable record: id and created_at only, no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "SterilizationRecord.id must be a dashed UUID"
    assert_iso_utc(data.get("created_at", ""), "SterilizationRecord.created_at")
    assert "updated_at" not in data, "SterilizationRecord must not expose updated_at"
    assert "version" not in data, "SterilizationRecord must not expose version"
    assert is_valid_uuid(data["establishment_id"])
    assert data["spore_test_result"] in ("PASS", "FAIL", "PENDING")
    assert isinstance(data["device_serial"], str) and data["device_serial"].strip()


def assert_minor_consent(data: dict) -> None:
    assert_common_fields(data, "MinorConsent")
    assert is_valid_uuid(data["establishment_id"])
    assert 0 <= data["minor_age_at_signing"] <= 17
    assert data["guardian_id_document_type"] in (
        "DRIVERS_LICENSE",
        "PASSPORT",
        "STATE_ID",
        "MILITARY_ID",
    )
    assert data["authorized_procedure_type"] in ("TATTOO", "PIERCING", "PERMANENT_COSMETICS")
    assert data["verification_status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert_iso_utc(data["expires_at"], "MinorConsent.expires_at")


def assert_procedure_log(data: dict) -> None:
    assert_common_fields(data, "ProcedureLog")
    assert is_valid_uuid(data["establishment_id"])
    assert is_valid_uuid(data["artist_id"])
    assert 0 <= data["client_age"] <= 120
    assert data["procedure_type"] in ("TATTOO", "PIERCING", "PERMANENT_COSMETICS")
    assert data["audit_status"] in ("RECORDED", "FLAGGED", "CLEARED")
    assert isinstance(data["aftercare_provided"], bool)
    assert parse_instant(data["ended_at"]) > parse_instant(data["started_at"])


def assert_complaint(data: dict) -> None:
    assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data["establishment_id"])
    assert data["category"] in (
        "SANITATION",
        "UNLICENSED_ARTIST",
        "MINOR_PROCEDURE",
        "INJURY",
        "OTHER",
    )
    assert data["status"] in (
        "RECEIVED",
        "TRIAGED",
        "INVESTIGATING",
        "SUBSTANTIATED",
        "UNSUBSTANTIATED",
    )
    assert isinstance(data["triage_overdue"], bool)
    assert isinstance(data["reopen_count"], int)
    assert_iso_utc(data["received_at"], "Complaint.received_at")
    assert_iso_utc(data["triage_due_at"], "Complaint.triage_due_at")


def assert_infection_report(data: dict) -> None:
    assert_common_fields(data, "InfectionReport")
    assert is_valid_uuid(data["establishment_id"])
    assert data["infection_type"] in (
        "BACTERIAL",
        "VIRAL_HEPATITIS",
        "MRSA",
        "MYCOBACTERIAL",
        "OTHER",
    )
    assert data["investigation_status"] in ("RECEIVED", "SCREENING", "CONFIRMED", "RULED_OUT")
    assert data["notification_status"] in ("PENDING", "CDC_NOTIFIED", "NOT_REQUIRED", "CLOSED")
    assert isinstance(data["notification_late"], bool)
    assert isinstance(data["reopen_count"], int)
    assert_iso_utc(data["notification_due_at"], "InfectionReport.notification_due_at")


def assert_enforcement_action(data: dict) -> None:
    assert_common_fields(data, "EnforcementAction")
    assert data["subject_type"] in ("ESTABLISHMENT", "ARTIST")
    assert data["action_type"] in ("SUSPENSION", "REVOCATION")
    assert data["reason_code"] in (
        "IMMINENT_HEALTH_HAZARD",
        "RISK_THRESHOLD",
        "CONFIRMED_INFECTION",
        "UNLICENSED_PRACTICE",
        "FEE_DELINQUENCY",
    )
    assert data["status"] in ("ACTIVE", "LIFTED")
    assert isinstance(data["auto_generated"], bool)
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert_iso_utc(data["issued_at"], "EnforcementAction.issued_at")
    if data["subject_type"] == "ESTABLISHMENT":
        assert is_valid_uuid(data["establishment_id"] or "")
        assert data["artist_id"] is None, "An establishment action carries artist_id null"
    else:
        assert is_valid_uuid(data["artist_id"] or "")
        assert data["establishment_id"] is None, "An artist action carries establishment_id null"


def assert_renewal_application(data: dict) -> None:
    assert_common_fields(data, "RenewalApplication")
    assert is_valid_uuid(data["establishment_id"])
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "DEFICIENT",
        "APPROVED",
        "DENIED",
        "SUPERSEDED",
    )
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0
    assert isinstance(data["fee_refunded_cents"], int) and data["fee_refunded_cents"] >= 0
    assert isinstance(data["fee_balance_due_cents"], int) and data["fee_balance_due_cents"] >= 0
    assert isinstance(data["late_fee_applied"], bool)
    assert isinstance(data["cycle_count"], int)


# ─── Domain invariants ─────────────────────────────────────────────────


def assert_posture_matches_inputs(establishment: dict) -> None:
    """The posture must follow from permit_status, risk_score and the critical counter."""
    posture = establishment["operating_posture"]
    if establishment["permit_status"] != "ACTIVE":
        assert posture == "CLOSED", (
            f"A permit in {establishment['permit_status']} must be CLOSED, got {posture}"
        )
    elif (
        establishment["risk_score"] >= 60
        or establishment["open_critical_violation_count"] > 0
    ):
        assert posture == "RESTRICTED", f"Expected RESTRICTED, got {posture}"
    else:
        assert posture == "OPEN", f"Expected OPEN, got {posture}"


def assert_net_departmental_fees(establishment: dict, expected_net_cents: int) -> None:
    """fees_paid_cents - fees_refunded_cents is the establishment's net money position."""
    net = establishment["fees_paid_cents"] - establishment["fees_refunded_cents"]
    assert net == expected_net_cents, (
        f"Net departmental fees expected {expected_net_cents}, got {net} "
        f"(paid={establishment['fees_paid_cents']}, refunded={establishment['fees_refunded_cents']})"
    )


def assert_reinstatement_breakdown(
    action: dict,
    expected_days: int,
    expected_base: int,
    expected_admin: int,
    expected_total: int,
) -> None:
    assert action["suspension_days"] == expected_days, (
        f"suspension_days expected {expected_days}, got {action['suspension_days']}"
    )
    assert action["reinstatement_base_cents"] == expected_base
    assert action["reinstatement_admin_fee_cents"] == expected_admin
    assert action["reinstatement_total_cents"] == expected_total
    assert (
        action["reinstatement_base_cents"] + action["reinstatement_admin_fee_cents"]
        == action["reinstatement_total_cents"]
    ), "reinstatement_total_cents must be base plus admin fee"


def find_row(rows: list, row_id: str) -> Optional[dict]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
