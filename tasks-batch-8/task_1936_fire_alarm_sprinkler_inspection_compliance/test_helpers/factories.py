"""Payload factories — one per creatable resource, input fields only."""


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Fire Protection Co",
        "state_license_no": "C-0001",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Technician",
        "nicet_level": "II",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "license_class": "ALARM",
        "issued_on": "2026-01-01",
        "expires_on": "2027-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(contractor_id, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "address_line": "1 Test Way",
        "occupancy_class": "BUSINESS",
        "jurisdiction_code": "LACO",
    }
    defaults.update(overrides)
    return defaults


def create_system_payload(**overrides) -> dict:
    defaults = {
        "system_category": "FIRE_ALARM",
        "install_date": "2026-01-01",
        "certification_cycle_anchor": "2000-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {
        "device_type": "SMOKE_DETECTOR",
        "serial_no": "SN-1",
    }
    defaults.update(overrides)
    return defaults


def replace_device_payload(replaced_by_device_id, **overrides) -> dict:
    defaults = {"replaced_by_device_id": replaced_by_device_id}
    defaults.update(overrides)
    return defaults


def create_plan_payload(plan_year, expected_property_version, **overrides) -> dict:
    defaults = {
        "plan_year": plan_year,
        "expected_property_version": expected_property_version,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(system_id, lead_technician_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "lead_technician_id": lead_technician_id,
        "scheduled_start": "2026-08-05T09:00:00Z",
        "scheduled_end": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_deficiency_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "classification": "NONCRITICAL",
    }
    defaults.update(overrides)
    return defaults


def create_impairment_payload(**overrides) -> dict:
    defaults = {
        "impairment_kind": "PLANNED",
        "planned_start": "2026-08-10T08:00:00Z",
        "planned_end": "2026-08-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_revision_payload(revision_of_id, **overrides) -> dict:
    defaults = {"revision_of_id": revision_of_id}
    defaults.update(overrides)
    return defaults


def create_backflow_test_payload(device_id, tester_technician_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "tester_technician_id": tester_technician_id,
        "tested_at": "2026-08-01T10:00:00Z",
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_pump_test_payload(tester_technician_id, **overrides) -> dict:
    defaults = {
        "test_kind": "CHURN",
        "tester_technician_id": tester_technician_id,
        "tested_at": "2026-08-01T10:00:00Z",
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_false_alarm_payload(**overrides) -> dict:
    defaults = {
        "alarm_occurred_at": "2026-08-02T01:00:00Z",
        "cause_code": "NEGLIGENCE",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_valuation_cents, expected_system_version,
                          **overrides) -> dict:
    defaults = {
        "project_valuation_cents": project_valuation_cents,
        "expected_system_version": expected_system_version,
    }
    defaults.update(overrides)
    return defaults


def cite_unpermitted_payload(unpermitted_work_detected=True, **overrides) -> dict:
    defaults = {"unpermitted_work_detected": unpermitted_work_detected}
    defaults.update(overrides)
    return defaults
