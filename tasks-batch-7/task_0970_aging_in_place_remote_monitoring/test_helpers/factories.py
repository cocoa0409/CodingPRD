"""Payload factories — one per entity, input fields only (PRD section 3)."""

DEFAULTS = {
    "SENIOR_FULL_NAME": "Test Senior",
    "SENIOR_DOB": "1940-01-01",
    "SENIOR_ADDRESS": "1 Test St",
    "PLAN_TIER": "PLUS",
    "PLAN_MONTHLY_FEE_CENTS": 6000,
    "PLAN_INCLUDED_MOTION_SENSORS": 2,
    "PLAN_EXTRA_SENSOR_FEE_CENTS": 199,
    "PLAN_MAX_CONTACTS": 5,
    "PLAN_CHECKIN_INTERVAL_HOURS": 48,
    "PLAN_MEDICATION_REMINDERS_ENABLED": True,
    "PLAN_WELLNESS_REPORT_ENABLED": True,
    "PLAN_WELLNESS_REPORT_CADENCE": "MONTHLY",
    "INSTALLER_FULL_NAME": "Test Installer",
    "INSTALLER_REGION": "R1",
    "CAREGIVER_FULL_NAME": "Test Caregiver",
    "CAREGIVER_PHONE": "555-0100",
    "CONTACT_PRIORITY_RANK": 1,
    "CONTACT_MIN_SEVERITY": "LOW",
    "CONTACT_RESPONSE_TIMEOUT_SECONDS": 3600,
    "ALERT_SEVERITY": "MEDIUM",
    "MEDICATION_NAME": "Aspirin",
    "MED_WINDOW_MINUTES": 60,
    "MED_CRITICALITY": "ROUTINE",
    "MED_START_DATE": "2026-05-01",
    "CHECKIN_KIND": "CALL",
    "REPORT_PERIOD_START": "2026-05-01T00:00:00Z",
    "REPORT_PERIOD_END": "2026-05-02T00:00:00Z",
    "REPORT_MODE": "FINAL",
    "APPT_WINDOW_START": "2026-05-01T09:00:00Z",
    "APPT_WINDOW_END": "2026-05-01T10:00:00Z",
}


def create_senior_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["SENIOR_FULL_NAME"],
        "date_of_birth": DEFAULTS["SENIOR_DOB"],
        "address": DEFAULTS["SENIOR_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": DEFAULTS["PLAN_TIER"],
        "monthly_fee_cents": DEFAULTS["PLAN_MONTHLY_FEE_CENTS"],
        "included_motion_sensors": DEFAULTS["PLAN_INCLUDED_MOTION_SENSORS"],
        "extra_sensor_fee_cents": DEFAULTS["PLAN_EXTRA_SENSOR_FEE_CENTS"],
        "max_contacts": DEFAULTS["PLAN_MAX_CONTACTS"],
        "checkin_interval_hours": DEFAULTS["PLAN_CHECKIN_INTERVAL_HOURS"],
        "medication_reminders_enabled": DEFAULTS[
            "PLAN_MEDICATION_REMINDERS_ENABLED"
        ],
        "wellness_report_enabled": DEFAULTS["PLAN_WELLNESS_REPORT_ENABLED"],
        "wellness_report_cadence": DEFAULTS["PLAN_WELLNESS_REPORT_CADENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(senior_id: str, plan_id: str, **overrides) -> dict:
    defaults = {"senior_id": senior_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def record_payment_payload(outcome: str = "SUCCEEDED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def change_plan_payload(plan_id: str, proration_mode: str = None, **overrides) -> dict:
    defaults = {"plan_id": plan_id}
    if proration_mode is not None:
        defaults["proration_mode"] = proration_mode
    defaults.update(overrides)
    return defaults


def create_sensor_kit_payload(senior_id: str, **overrides) -> dict:
    defaults = {"senior_id": senior_id}
    defaults.update(overrides)
    return defaults


def create_telemetry_payload(
    device_id: str, event_type: str, observed_at: str, **overrides
) -> dict:
    defaults = {
        "device_id": device_id,
        "event_type": event_type,
        "observed_at": observed_at,
    }
    defaults.update(overrides)
    return defaults


def create_installer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["INSTALLER_FULL_NAME"],
        "region": DEFAULTS["INSTALLER_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_install_appointment_payload(
    senior_id: str, kit_id: str, installer_id: str, **overrides
) -> dict:
    defaults = {
        "senior_id": senior_id,
        "kit_id": kit_id,
        "installer_id": installer_id,
        "window_start": DEFAULTS["APPT_WINDOW_START"],
        "window_end": DEFAULTS["APPT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def reschedule_appointment_payload(
    window_start: str, window_end: str, **overrides
) -> dict:
    defaults = {"window_start": window_start, "window_end": window_end}
    defaults.update(overrides)
    return defaults


def create_caregiver_payload(senior_id: str, **overrides) -> dict:
    defaults = {
        "senior_id": senior_id,
        "full_name": DEFAULTS["CAREGIVER_FULL_NAME"],
        "phone": DEFAULTS["CAREGIVER_PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_contact_tree_entry_payload(
    senior_id: str, caregiver_id: str, **overrides
) -> dict:
    defaults = {
        "senior_id": senior_id,
        "caregiver_id": caregiver_id,
        "priority_rank": DEFAULTS["CONTACT_PRIORITY_RANK"],
        "min_severity": DEFAULTS["CONTACT_MIN_SEVERITY"],
        "response_timeout_seconds": DEFAULTS["CONTACT_RESPONSE_TIMEOUT_SECONDS"],
    }
    defaults.update(overrides)
    return defaults


def create_alert_payload(senior_id: str, severity: str = None, **overrides) -> dict:
    defaults = {
        "senior_id": senior_id,
        "severity": severity or DEFAULTS["ALERT_SEVERITY"],
    }
    defaults.update(overrides)
    return defaults


def create_medication_schedule_payload(
    senior_id: str, expected_senior_version: int, **overrides
) -> dict:
    defaults = {
        "senior_id": senior_id,
        "medication_name": DEFAULTS["MEDICATION_NAME"],
        "times_of_day": ["20:00"],
        "window_minutes": DEFAULTS["MED_WINDOW_MINUTES"],
        "criticality": DEFAULTS["MED_CRITICALITY"],
        "start_date": DEFAULTS["MED_START_DATE"],
        "expected_senior_version": expected_senior_version,
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(senior_id: str, kind: str = None, **overrides) -> dict:
    defaults = {
        "senior_id": senior_id,
        "kind": kind or DEFAULTS["CHECKIN_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_wellness_report_payload(
    senior_id: str, period_start: str = None, period_end: str = None,
    mode: str = None, **overrides,
) -> dict:
    defaults = {
        "senior_id": senior_id,
        "period_start": period_start or DEFAULTS["REPORT_PERIOD_START"],
        "period_end": period_end or DEFAULTS["REPORT_PERIOD_END"],
        "mode": mode or DEFAULTS["REPORT_MODE"],
    }
    defaults.update(overrides)
    return defaults
