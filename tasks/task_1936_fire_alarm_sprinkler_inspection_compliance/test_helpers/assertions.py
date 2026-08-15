"""Entity assertions and date helpers.

Field names follow the PRD exactly. Every resource carries the four common
system-managed fields from the PRD's resource-identity section.
"""
from datetime import date, datetime, timedelta

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_license_no"], str) and data["state_license_no"]
    assert isinstance(data["compliance_score"], int)
    assert data["compliance_score"] >= 0, "compliance_score never falls below 0"
    assert data["posture"] in ("GOOD_STANDING", "PROBATION", "SUSPENDED")
    assert data["status"] in ("ACTIVE", "DEACTIVATED")


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contractor_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["nicet_level"] in ("I", "II", "III", "IV")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_license_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["technician_id"], str)
    assert data["license_class"] in ("ALARM", "SPRINKLER", "BACKFLOW", "PUMP")
    assert isinstance(data["issued_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contractor_id"], str)
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert data["occupancy_class"] in (
        "ASSEMBLY", "BUSINESS", "EDUCATIONAL", "MERCANTILE", "RESIDENTIAL", "STORAGE",
    )
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_system(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert data["system_category"] in ("FIRE_ALARM", "SPRINKLER", "BACKFLOW", "FIRE_PUMP")
    assert isinstance(data["install_date"], str)
    assert data["impairment_status"] in ("NORMAL", "IMPAIRED", "OUT_OF_SERVICE")
    assert isinstance(data["certification_cycle_anchor"], str)
    assert data["status"] in ("IN_SERVICE", "DECOMMISSIONED")


def assert_device(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["system_id"], str)
    assert data["device_type"] in (
        "SMOKE_DETECTOR", "PULL_STATION", "NOTIFICATION_APPLIANCE", "SPRINKLER_HEAD",
        "GAUGE_VALVE", "FIRE_PUMP_CONTROLLER", "BACKFLOW_ASSEMBLY", "SUPERVISORY_SWITCH",
    )
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    assert data["frequency_code"] in ("MONTHLY", "QUARTERLY", "ANNUAL")
    assert isinstance(data["next_due_date"], str)
    assert data.get("replaced_by_device_id") is None or isinstance(
        data["replaced_by_device_id"], str)
    assert data["status"] in ("IN_SERVICE", "REPLACED", "REMOVED")


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["total_events_required"], int)
    assert data["total_events_required"] >= 0
    assert isinstance(data["events_completed"], int)
    assert data["events_completed"] >= 0
    assert data["plan_posture"] in (
        "DRAFT", "SCHEDULED", "IN_PROGRESS", "FULFILLED", "LAPSED",
    )
    assert isinstance(data["provisional_fee_cents"], int)


def assert_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["system_id"], str)
    assert isinstance(data["lead_technician_id"], str)
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_ACCESS",
    )
    if data["status"] == "COMPLETED":
        assert isinstance(data["completed_at"], str)
        assert isinstance(data["report_due_date"], str)


def assert_deficiency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["device_id"], str)
    assert data["classification"] in ("CRITICAL", "NONCRITICAL")
    assert data.get("correction_deadline") is None or isinstance(
        data["correction_deadline"], str)
    assert isinstance(data["extension_used"], bool)
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert data.get("corrected_at") is None or isinstance(data["corrected_at"], str)
    assert data["status"] in ("OPEN", "CORRECTED", "VERIFIED", "WAIVED")


def assert_impairment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["system_id"], str)
    assert data["impairment_kind"] in ("PLANNED", "UNPLANNED")
    assert isinstance(data["planned_start"], str)
    assert isinstance(data["planned_end"], str)
    assert isinstance(data["notification_deadline"], str)
    assert isinstance(data["notification_late"], bool)
    assert isinstance(data["discovered_at"], str)
    assert data["status"] in ("OPEN", "NOTIFIED", "RESTORED", "CLOSED")


def assert_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["event_id"], str)
    assert data.get("portal_submission_id") is None or isinstance(
        data["portal_submission_id"], str)
    assert data.get("submitted_at") is None or isinstance(data["submitted_at"], str)
    assert isinstance(data["is_late"], bool)
    assert data.get("revision_of_id") is None or isinstance(data["revision_of_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_backflow_test(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["system_id"], str)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["tester_technician_id"], str)
    assert isinstance(data["tested_at"], str)
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["unpaid_balance_cents"], int)
    assert data["unpaid_balance_cents"] >= 0
    assert data["status"] in ("RECORDED", "INVOICED", "PAID", "FAILED_OPEN")


def assert_pump_test(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["system_id"], str)
    assert data["test_kind"] in ("CHURN", "ANNUAL_FLOW")
    assert isinstance(data["tester_technician_id"], str)
    assert isinstance(data["tested_at"], str)
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] in ("RECORDED", "ATTESTED", "FAILED_OPEN")


def assert_false_alarm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["alarm_occurred_at"], str)
    assert data["cause_code"] in (
        "NEGLIGENCE", "EQUIPMENT_FAULT", "UNKNOWN", "MALICIOUS", "WEATHER",
    )
    assert isinstance(data["chargeable"], bool)
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["waived"], bool)
    assert data["status"] in ("OPEN", "ASSESSED", "WAIVED", "PAID")


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["system_id"], str)
    assert isinstance(data["project_valuation_cents"], int)
    assert data["project_valuation_cents"] >= 0
    assert isinstance(data["permit_fee_cents"], int) and data["permit_fee_cents"] >= 0
    assert data.get("work_commenced_at") is None or isinstance(
        data["work_commenced_at"], str)
    assert data["status"] in (
        "APPLIED", "ISSUED", "WORK_COMMENCED", "FINED", "CLOSED", "EXPIRED",
    )


# ---------------------------------------------------------------------------
# Date/datetime helpers (date-only fields carry no time component per the PRD;
# parsing tolerates an optional time suffix so assertions stay format-agnostic)
# ---------------------------------------------------------------------------

def parse_date(value: str) -> date:
    """Parse an ISO date (or datetime) field down to its calendar date."""
    return date.fromisoformat(str(value)[:10])


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, accepting a trailing 'Z'."""
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def days_between(earlier: date, later: date) -> int:
    return (later - earlier).days


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def iso_date(d: date) -> str:
    return d.isoformat()


def iso_utc(d: date, hour: int = 0) -> str:
    return f"{d.isoformat()}T{hour:02d}:00:00Z"
