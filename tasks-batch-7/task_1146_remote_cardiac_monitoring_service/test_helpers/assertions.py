"""Entity assertions and domain invariant checkers (PRD §2.4 common fields, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_iso_prefix(value, expected_prefix: str, field: str = "timestamp"):
    """Domain datetimes are ISO 8601 UTC at minute granularity (PRD §2.7); the
    fractional-second rendering is serializer detail, so compare the prefix."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert value.startswith(expected_prefix), (
        f"{field} must start with {expected_prefix!r}, got {value!r}"
    )


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_patient(data: dict):
    _assert_common(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert data["insurance_plan"] in ["MEDICARE", "COMMERCIAL", "SELF_PAY"]
    assert isinstance(data["open_compliance_events"], int) and data["open_compliance_events"] >= 0


def assert_physician(data: dict):
    _assert_common(data, "Physician")
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10
    assert data["notification_preference"] in ["PHONE", "PORTAL"]


def assert_technician(data: dict):
    _assert_common(data, "Technician")
    assert data["certification_level"] in ["CCT", "CRAT", "RN"]
    assert isinstance(data["shift_capacity"], int) and data["shift_capacity"] > 0
    assert isinstance(data["open_alert_load"], int) and data["open_alert_load"] >= 0
    assert isinstance(data["alerts_acknowledged_total"], int) and data["alerts_acknowledged_total"] >= 0
    assert data["fatigue_status"] in ["NORMAL", "AT_RISK", "FATIGUED"]


def assert_device(data: dict):
    _assert_common(data, "Device")
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["model"] in ["HOLTER", "EVENT", "IMPLANTABLE"]
    assert data["status"] in [
        "IN_STOCK", "RESERVED", "DEPLOYED", "RETURN_IN_TRANSIT", "REFURBISHING", "LOST",
    ]


def assert_order(data: dict):
    _assert_common(data, "MonitoringOrder")
    assert data["monitor_type"] in ["HOLTER", "EVENT", "IMPLANTABLE"]
    assert isinstance(data["prescribed_days"], int) and 5 <= data["prescribed_days"] <= 45
    assert data["status"] in ["OPEN", "IN_SERVICE", "FULFILLED", "CANCELLED"]


def assert_enrollment(data: dict):
    _assert_common(data, "Enrollment")
    assert data["status"] in ["INITIATED", "EDUCATED", "ACTIVATION_FAILED", "ACTIVATED", "ABORTED"]
    assert isinstance(data["education_completed"], bool)
    assert isinstance(data["attempts_count"], int) and data["attempts_count"] >= 0


def assert_episode(data: dict):
    _assert_common(data, "MonitoringEpisode")
    assert data["clinical_status"] in ["MONITORING", "COMPLETED", "TERMINATED_EARLY"]
    assert data["compliance_status"] in ["COMPLIANT", "WATCH", "SUSPENDED"]
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0
    assert isinstance(data["transmission_count"], int) and data["transmission_count"] >= 0
    assert isinstance(data["unacknowledged_critical_count"], int) and data["unacknowledged_critical_count"] >= 0
    assert isinstance(data["total_billed_cents"], int) and data["total_billed_cents"] >= 0


def assert_suspension_interval(data: dict):
    _assert_common(data, "SuspensionInterval")
    assert is_iso8601_timestamp(data.get("started_at", ""))


def assert_transmission(data: dict):
    _assert_common(data, "Transmission")
    assert isinstance(data["seq_no"], int)
    assert isinstance(data["bytes_received"], int) and data["bytes_received"] > 0
    assert isinstance(data["signal_quality"], int) and 0 <= data["signal_quality"] <= 100
    assert data["status"] in ["PROCESSED", "FAILED"]


def assert_alert(data: dict):
    _assert_common(data, "ArrhythmiaAlert")
    assert data["severity"] in ["CRITICAL", "URGENT", "ROUTINE"]
    assert data["status"] in ["NEW", "ACKNOWLEDGED", "TRIAGED", "ESCALATED", "NOTIFIED", "CLOSED"]
    assert is_iso8601_timestamp(data.get("detected_at", ""))
    assert isinstance(data["notification_attempt_count"], int) and data["notification_attempt_count"] >= 0


def assert_notification_attempt(data: dict):
    _assert_common(data, "NotificationAttempt")
    assert data["channel"] in ["PHONE", "PORTAL", "ESCALATION"]
    assert data["status"] in ["PENDING", "ACKNOWLEDGED"]


def assert_report(data: dict):
    _assert_common(data, "DiagnosticReport")
    assert data["report_type"] in ["INTERIM", "FINAL"]
    assert data["status"] in ["DRAFT", "FINALIZED", "AMENDED"]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_billing_period(data: dict):
    _assert_common(data, "BillingPeriod")
    assert isinstance(data["period_index"], int) and data["period_index"] >= 0
    assert isinstance(data["window_days"], int) and data["window_days"] > 0
    assert isinstance(data["provisional_total_cents"], int)
    assert data["status"] in ["ACCRUING", "READY", "SUBMITTED", "ADJUSTMENT_PROPOSED", "ADJUSTED"]


def assert_return_shipment(data: dict):
    _assert_common(data, "ReturnShipment")
    assert data["status"] in ["LABEL_CREATED", "OVERDUE", "RECEIVED", "LOST"]


def assert_compliance_event(data: dict):
    _assert_common(data, "ComplianceEvent")
    assert data["event_type"] in ["TRANSMISSION_GAP", "RETURN_OVERDUE"]
    assert data["status"] in ["OPEN", "RESOLVED"]


def assert_recognized_total_invariant(period: dict):
    """PRD §3.8: recognized_total_cents == submitted_total_cents + approved_adjustment_cents."""
    if period.get("recognized_total_cents") is not None and period.get("submitted_total_cents") is not None:
        assert period["recognized_total_cents"] == (
            period["submitted_total_cents"] + period.get("approved_adjustment_cents", 0)
        ), (
            f"recognized {period['recognized_total_cents']} != submitted "
            f"{period['submitted_total_cents']} + approved {period.get('approved_adjustment_cents')}"
        )
