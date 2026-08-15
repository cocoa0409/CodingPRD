"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """PRD §2.5: every primary resource carries id (UUID), created_at, updated_at,
    and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive integer"
    )


def assert_facility(data: dict):
    assert_common_fields(data, "ContractedFacility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["supported_modalities"], list)
    assert isinstance(data["pad_amps_available"], int)
    assert isinstance(data["pad_voltage"], int)


def assert_unit(data: dict):
    assert_common_fields(data, "MobileImagingUnit")
    assert data["modality"] in ("MRI", "CT", "PET")
    assert data["status"] in ("ACTIVE_SERVICE", "MAINTENANCE", "OUT_OF_SERVICE")


def assert_contract(data: dict):
    assert_common_fields(data, "ServiceContract")
    assert data["billing_model"] in ("PER_DAY", "PER_SCAN")
    assert isinstance(data["day_rate_cents"], int)
    assert isinstance(data["monthly_scan_cap"], int)


def assert_route_plan(data: dict):
    assert_common_fields(data, "RoutePlan")
    assert data["status"] in ("DRAFT", "PUBLISHED", "LOCKED", "CLOSED", "SUPERSEDED")
    assert isinstance(data["site_day_count"], int)
    assert isinstance(data["total_travel_stipend_cents"], int)


def assert_site_day(data: dict):
    assert_common_fields(data, "SiteDayAssignment")
    assert data["status"] in (
        "SCHEDULED", "EN_ROUTE", "SETTING_UP", "READY", "IN_SERVICE",
        "COMPLETED", "CANCELLED", "INTERRUPTED", "RESCHEDULED",
    )


def assert_appointment(data: dict):
    assert_common_fields(data, "PatientAppointment")
    assert data["exam_type"] in ("CT_HEAD", "CT_CHEST", "MRI_BRAIN", "PET_ONCO")
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "CHECKED_IN", "SCANNING",
        "COMPLETED", "CANCELLED", "NO_SHOW",
    )


def assert_technologist(data: dict):
    assert_common_fields(data, "Technologist")
    assert isinstance(data["modality_certs"], list)
    assert isinstance(data["max_daily_drive_minutes"], int)


def assert_staffing_assignment(data: dict):
    assert_common_fields(data, "StaffingAssignment")
    assert data["status"] in ("ASSIGNED", "RELEASED")


def assert_transport_leg(data: dict):
    assert_common_fields(data, "TransportLeg")
    assert data["status"] in ("PLANNED", "DISPATCHED", "ARRIVED", "FAILED", "CANCELLED")
    assert isinstance(data["stipend_cents"], int)


def assert_setup_checklist(data: dict):
    assert_common_fields(data, "SetupChecklist")
    assert data["status"] in ("IN_PROGRESS", "ALL_PASSED", "HAS_FAILURES")


def assert_breakdown(data: dict):
    assert_common_fields(data, "BreakdownEvent")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in ("REPORTED", "RESOLVED")


def assert_dose_record(data: dict):
    """PRD §2.5: RadiationDoseRecord is immutable — id + created_at only; both
    updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "RadiationDoseRecord.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "RadiationDoseRecord.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "RadiationDoseRecord must not carry updated_at"
    assert "version" not in data, "RadiationDoseRecord must not carry version"
    assert isinstance(data["drl_exceeded"], bool)


def assert_accreditation(data: dict):
    assert_common_fields(data, "AccreditationRecord")
    assert data["accrediting_body"] in ("ACR", "IAC", "TJC")
    assert data["status"] in ("ACTIVE", "EXPIRING_SOON", "EXPIRED", "SUSPENDED")


def assert_billing_statement(data: dict):
    assert_common_fields(data, "BillingStatement")
    assert data["billing_model_snapshot"] in ("PER_DAY", "PER_SCAN")
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "DISPUTED", "INVOICED", "PAID")
    assert isinstance(data["completed_scan_count"], int)
    assert isinstance(data["no_show_count"], int)
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["net_due_cents"], int)


def assert_image_study(data: dict):
    assert_common_fields(data, "ImageStudy")
    assert data["status"] in (
        "QUEUED", "TRANSMITTING", "DELIVERED", "TRANSFER_FAILED", "ACKNOWLEDGED",
    )
    assert isinstance(data["transfer_attempts"], int)
