"""Payload factories — one per entity, client-supplied input fields only."""

# ─── Catalogue models used throughout the suite ────────────────────────────
# The infusion-pump model is network-connected (which adds 4 risk points and
# brings its units into the loaner cyber-eligibility rule); the patient-monitor,
# scale and ventilator models are not.

PUMP_MODEL = {
    "manufacturer": "Medtronic",
    "model_number": "IVS-9000",
    "device_family": "INFUSION_PUMP",
    "expected_life_years": 8,
    "replacement_cost_cents": 3_200_000,
    "is_network_connected": True,
}

MONITOR_MODEL = {
    "manufacturer": "GE",
    "model_number": "CAM-500",
    "device_family": "PATIENT_MONITOR",
    "expected_life_years": 10,
    "replacement_cost_cents": 1_500_000,
}

SCALE_MODEL = {
    "manufacturer": "Welch Allyn",
    "model_number": "SCL-100",
    "device_family": "SCALE",
    "expected_life_years": 10,
    "replacement_cost_cents": 300_000,
}

VENTILATOR_MODEL = {
    "manufacturer": "Philips",
    "model_number": "VNT-3",
    "device_family": "VENTILATOR",
    "expected_life_years": 2,
    "replacement_cost_cents": 500_000,
}

# ─── Canonical device profiles ─────────────────────────────────────────────
# PUMP_UNIT scores 9*2 + 4*3 + 3*1 + 4 (network) + 1 (age >= 5y) = 38 -> CRITICAL.
PUMP_UNIT = {
    "serial_number": "SN-1001",
    "acquisition_date": "2019-03-01",
    "acquisition_cost_cents": 3_000_000,
    "function_code": 9,
    "physical_risk_code": 4,
    "maintenance_requirement_code": 3,
    "condition_score": 3,
}

# MONITOR_UNIT scores 5*2 + 3*3 + 2*1 + 0 + 1 = 22 -> MEDIUM.
MONITOR_UNIT = {
    "serial_number": "SN-2001",
    "acquisition_date": "2019-03-01",
    "acquisition_cost_cents": 1_400_000,
    "function_code": 5,
    "physical_risk_code": 3,
    "maintenance_requirement_code": 2,
    "condition_score": 4,
}

# POOL_MONITOR_UNIT scores 5*2 + 3*3 + 2*1 + 0 + 0 = 21 -> MEDIUM, condition 2.
POOL_MONITOR_UNIT = {
    "serial_number": "SN-2002",
    "acquisition_date": "2023-01-10",
    "acquisition_cost_cents": 1_450_000,
    "function_code": 5,
    "physical_risk_code": 3,
    "maintenance_requirement_code": 2,
    "condition_score": 2,
    "is_loaner_pool": True,
}

# SCALE_UNIT scores 2*2 + 1*3 + 1*1 = 8 -> LOW.
SCALE_UNIT = {
    "serial_number": "SN-3001",
    "acquisition_date": "2023-01-10",
    "acquisition_cost_cents": 280_000,
    "function_code": 2,
    "physical_risk_code": 1,
    "maintenance_requirement_code": 1,
    "condition_score": 2,
}


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": "Riverbend Medical Center",
        "facility_code": "RMC-01",
        "pm_compliance_target_pct": 90.00,
    }
    payload.update(overrides)
    return payload


def create_department_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "name": "Telemetry Unit",
        "cost_center_code": "CC-5200",
        "downtime_budget_cents": 5_000_000,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> dict:
    payload = {
        "name": "BioServe Inc",
        "vendor_code": "BSV",
        "hourly_rate_cents": 18500,
        "travel_flat_cents": 24000,
        "security_attestation_on_file": True,
        "is_approved": True,
    }
    payload.update(overrides)
    return payload


def create_device_model_payload(base=None, **overrides) -> dict:
    payload = dict(base or MONITOR_MODEL)
    payload.update(overrides)
    return payload


def create_device_payload(facility_id: str, department_id: str, device_model_id: str,
                          base=None, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "department_id": department_id,
        "device_model_id": device_model_id,
    }
    payload.update(dict(base or MONITOR_UNIT))
    payload.update(overrides)
    return payload


def create_pm_task_payload(device_id: str, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-01T23:59:00Z",
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(device_id: str, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "reported_severity": "ROUTINE",
        "problem_summary": "Intermittent fault reported by clinical staff",
    }
    payload.update(overrides)
    return payload


def create_loaner_assignment_payload(work_order_id: str, expected_work_order_version: int,
                                     **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "source": "POOL",
        "start_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-08-08T00:00:00Z",
        "expected_work_order_version": expected_work_order_version,
    }
    payload.update(overrides)
    return payload


def create_recall_notice_payload(facility_id: str, device_model_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "device_model_id": device_model_id,
        "source_reference": "FDA-2026-1188",
        "hazard_class": "CLASS_II",
        "response_due_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_service_contract_payload(vendor_id: str, device_model_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "device_model_id": device_model_id,
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-12-31T00:00:00Z",
        "annual_premium_cents": 1_200_000,
        "deductible_cents": 25000,
        "covered_event_cap": 2,
    }
    payload.update(overrides)
    return payload


def create_security_finding_payload(device_id: str, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "severity": "MEDIUM",
        "advisory_reference": "CVE-2026-1234",
    }
    payload.update(overrides)
    return payload
