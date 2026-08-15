"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SITE_NAME": "Acme Refining",
    "SCHEDULE": {
        "vacuum_per_gallon_cents": 250,
        "hydroblast_per_foot_cents": 1800,
        "labor_rate_cents_per_hour": 14500,
        "equipment_rate_cents_per_hour": 22000,
        "standby_rate_cents_per_hour": 12000,
        "overtime_multiplier": 1.5,
        "minimum_invoice_cents": 75000,
    },
    "UNIT": {
        "unit_code": "VAC-01",
        "unit_type": "VAC_TRUCK",
        "max_pressure_psi": 3000,
        "tank_capacity_gal": 5000,
    },
    "OPERATOR": {
        "full_name": "Ann A",
        "employee_ref": "E-201",
        "hazwoper_expires_on": "2027-01-01",
        "hydroblast_certified": False,
    },
    "WINDOW_START": "2026-08-01T06:00:00Z",
    "WINDOW_END": "2026-08-01T14:00:00Z",
    "PERMIT_FROM": "2026-07-31T00:00:00Z",
    "PERMIT_UNTIL": "2026-08-05T18:00:00Z",
    "FACILITY": {
        "name": "Gulf Coast TSDF",
        "epa_id": "TXD0001",
        "total_capacity_tons": 1000,
    },
    "PROFILE": {
        "waste_code": "D008",
        "hazard_class": "HAZ",
        "density_lbs_per_gal": 8.0,
        "disposal_rate_per_ton_cents": 35000,
        "variance_basis": "WEIGHT",
    },
}


def create_site_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["SITE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(site_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "label": "S1"}
    defaults.update(DEFAULTS["SCHEDULE"])
    defaults.update(overrides)
    return defaults


def create_job_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "job_type": "VACUUM",
        "pricing_mode": "UNIT_RATE",
        "description": "Test job",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    defaults = dict(DEFAULTS["UNIT"])
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    defaults = dict(DEFAULTS["OPERATOR"])
    defaults.update(overrides)
    return defaults


def create_equipment_assignment_payload(job_id, unit_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "resource_kind": "EQUIPMENT",
        "equipment_unit_id": unit_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_operator_assignment_payload(job_id, operator_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "resource_kind": "OPERATOR",
        "operator_id": operator_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_jha_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "confined_space": False,
        "hazards": ["SLIP_TRIP"],
    }
    defaults.update(overrides)
    return defaults


def create_pressure_plan_jha_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "confined_space": False,
        "hazards": ["HIGH_PRESSURE_WATER"],
        "max_operating_pressure_psi": 5000,
        "planned_water_flow_gpm": 20.0,
        "water_source": "SITE_NONPOTABLE",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "permit_type": "HOT_WORK",
        "space_id": "B-201",
        "valid_from": DEFAULTS["PERMIT_FROM"],
        "valid_until": DEFAULTS["PERMIT_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_disposal_facility_payload(**overrides) -> dict:
    defaults = dict(DEFAULTS["FACILITY"])
    defaults.update(overrides)
    return defaults


def create_waste_profile_payload(site_id, facility_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "facility_id": facility_id}
    defaults.update(DEFAULTS["PROFILE"])
    defaults.update(overrides)
    return defaults


def create_manifest_payload(job_id, waste_profile_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "waste_profile_id": waste_profile_id,
        "estimated_gallons": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_containment_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "water_used_gallons": 500,
        "water_captured_gallons": 500,
    }
    defaults.update(overrides)
    return defaults


def create_downtime_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id, "cause": "CUSTOMER_DELAY"}
    defaults.update(overrides)
    return defaults


def create_incident_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "severity": "NEAR_MISS",
        "title": "Dropped hose",
        "description": "No injury",
    }
    defaults.update(overrides)
    return defaults
