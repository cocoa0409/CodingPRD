"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "FACILITY_NAME": "Hospital A",
    "FACILITY_ADDRESS": "1 A St",
    "PAD_AMPS": 150,
    "PAD_VOLTAGE": 480,
    "PAD_LEVEL_DEG": 2.0,
    "UNIT_CODE": "MIU-01",
    "MODALITY": "CT",
    "POWER_REQUIRED_AMPS": 100,
    "VOLTAGE_REQUIRED": 480,
    "SETUP_MINUTES": 60,
    "TEARDOWN_MINUTES": 45,
    "HOME_BASE": "Depot",
    # Contract defaults shared by both billing models (PRD §3.1).
    "DAY_RATE_CENTS": 500000,
    "SCAN_RATE_CENTS": 40000,
    "INCLUDED_SCAN_QUOTA": 10,
    "OVERAGE_SCAN_RATE_CENTS": 45000,
    "GUARANTEED_MINIMUM_CENTS": 200000,
    "NO_SHOW_FEE_CENTS": 10000,
    "CANCEL_NOTICE_HOURS": 48,
    "CANCEL_LATE_PCT": 0.5,
    "MONTHLY_SCAN_CAP": 100,
    "INTERRUPTION_FLOOR_CENTS": 100000,
    "TECH_NAME": "Tina Tech",
    "MAX_DAILY_DRIVE_MINUTES": 240,
    "DRIVE_MINUTES": 50,
    "STAFF_DRIVE_MINUTES": 30,
    "LEG_DISTANCE_MILES": 40,
    "MEASURED_AMPS": 140,
    "MEASURED_UPLINK_MBPS": 100,
    "EXAM_TYPE": "CT_HEAD",
    "APPT_START": "09:00",
    "APPT_DURATION_MINUTES": 30,
    "ESTIMATED_DOSE_MSV": 1.0,
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "address": DEFAULTS["FACILITY_ADDRESS"],
        "supported_modalities": [DEFAULTS["MODALITY"]],
        "pad_amps_available": DEFAULTS["PAD_AMPS"],
        "pad_voltage": DEFAULTS["PAD_VOLTAGE"],
        "pad_level_tolerance_deg": DEFAULTS["PAD_LEVEL_DEG"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": DEFAULTS["UNIT_CODE"],
        "modality": DEFAULTS["MODALITY"],
        "power_required_amps": DEFAULTS["POWER_REQUIRED_AMPS"],
        "voltage_required": DEFAULTS["VOLTAGE_REQUIRED"],
        "setup_minutes": DEFAULTS["SETUP_MINUTES"],
        "teardown_minutes": DEFAULTS["TEARDOWN_MINUTES"],
        "home_base_name": DEFAULTS["HOME_BASE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(facility_id, billing_model="PER_DAY", **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "billing_model": billing_model,
        "day_rate_cents": DEFAULTS["DAY_RATE_CENTS"],
        "scan_rate_cents": DEFAULTS["SCAN_RATE_CENTS"],
        "included_scan_quota": DEFAULTS["INCLUDED_SCAN_QUOTA"],
        "overage_scan_rate_cents": DEFAULTS["OVERAGE_SCAN_RATE_CENTS"],
        "guaranteed_minimum_cents": DEFAULTS["GUARANTEED_MINIMUM_CENTS"],
        "no_show_fee_cents": DEFAULTS["NO_SHOW_FEE_CENTS"],
        "cancel_notice_hours": DEFAULTS["CANCEL_NOTICE_HOURS"],
        "cancel_late_pct": DEFAULTS["CANCEL_LATE_PCT"],
        "monthly_scan_cap": DEFAULTS["MONTHLY_SCAN_CAP"],
        "interruption_floor_cents": DEFAULTS["INTERRUPTION_FLOOR_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_route_plan_payload(unit_id, week_start_date, expected_unit_version, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "week_start_date": week_start_date,
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def create_site_day_payload(route_plan_id, facility_id, contract_id, service_date, **overrides) -> dict:
    defaults = {
        "route_plan_id": route_plan_id,
        "facility_id": facility_id,
        "contract_id": contract_id,
        "service_date": service_date,
        "arrival_time": "07:00",
        "first_patient_time": "08:30",
        "last_patient_time": "16:00",
        "departure_time": "17:00",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(site_day_id, patient_ref, **overrides) -> dict:
    defaults = {
        "site_day_id": site_day_id,
        "patient_ref": patient_ref,
        "exam_type": DEFAULTS["EXAM_TYPE"],
        "scheduled_start": DEFAULTS["APPT_START"],
        "duration_minutes": DEFAULTS["APPT_DURATION_MINUTES"],
        "estimated_dose_msv": DEFAULTS["ESTIMATED_DOSE_MSV"],
    }
    defaults.update(overrides)
    return defaults


def create_technologist_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["TECH_NAME"],
        "modality_certs": [DEFAULTS["MODALITY"]],
        "home_base_name": DEFAULTS["HOME_BASE"],
        "max_daily_drive_minutes": DEFAULTS["MAX_DAILY_DRIVE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_staffing_assignment_payload(site_day_id, technologist_id, **overrides) -> dict:
    defaults = {
        "site_day_id": site_day_id,
        "technologist_id": technologist_id,
        "estimated_drive_minutes": DEFAULTS["STAFF_DRIVE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_transport_leg_payload(site_day_id, **overrides) -> dict:
    defaults = {
        "site_day_id": site_day_id,
        "origin_name": DEFAULTS["HOME_BASE"],
        "destination_name": DEFAULTS["FACILITY_NAME"],
        "distance_miles": DEFAULTS["LEG_DISTANCE_MILES"],
        "drive_minutes": DEFAULTS["DRIVE_MINUTES"],
        "overnight": False,
    }
    defaults.update(overrides)
    return defaults


def create_setup_checklist_payload(site_day_id, **overrides) -> dict:
    defaults = {
        "site_day_id": site_day_id,
        "power_verify_passed": True,
        "measured_amps": DEFAULTS["MEASURED_AMPS"],
        "pad_level_passed": True,
        "chiller_passed": True,
        "rf_shield_passed": True,
        "network_link_passed": True,
        "measured_uplink_mbps": DEFAULTS["MEASURED_UPLINK_MBPS"],
    }
    defaults.update(overrides)
    return defaults


def create_breakdown_payload(unit_id, severity, description, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "severity": severity,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_dose_record_payload(appointment_id, technologist_id, dose_msv, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "technologist_id": technologist_id,
        "dose_msv": dose_msv,
    }
    defaults.update(overrides)
    return defaults


def create_accreditation_payload(unit_id, modality="CT", **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "accrediting_body": "ACR",
        "modality": modality,
        "issued_on": "2026-01-01",
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_image_study_payload(appointment_id, study_uid, size_mb, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "study_uid": study_uid,
        "size_mb": size_mb,
    }
    defaults.update(overrides)
    return defaults
