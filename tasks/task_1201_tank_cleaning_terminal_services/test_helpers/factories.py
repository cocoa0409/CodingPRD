"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "TERMINAL_NAME": "Terminal T1",
    "WASTEWATER_DAILY_CAPACITY_LITERS": 100000,
    "PRODUCT_CODE": "GAS89",
    "PRODUCT_FAMILY": "GASOLINE",
    "PRODUCT_VISCOSITY": "LOW",
    "PRODUCT_GROUP": "GAS",
    "PRODUCT_FLASH_POINT_C": -40,
    "TANK_NUMBER": "T-101",
    "TANK_CAPACITY_M3": 5000,
    "CONTRACTOR_NAME": "CleanCo",
    "HEEL_SOUNDING_LITERS": 2000,
    "BASE_SERVICE_FEE_CENTS": 500000,
    "WASTE_CODE": "K051",
    "HAZARD_CLASS": "NON_HAZARDOUS",
    "LAB_FLASH_POINT_C": 70,
    "LAB_TPH_MG_L": 120,
    "MAX_ENTRANTS": 4,
    "INSPECTOR_NAME": "InspA",
    "CERTIFICATION_LEVEL": "API653",
    "FINDING_DESCRIPTION": "coating blister",
    "REPAIR_DESCRIPTION": "weld patch plate",
    "BATCH_VOLUME_LITERS": 5000,
    "LAB_PH": 7.0,
    "LAB_TPH": 5.0,
    # Canonical window: clock starts 2026-05-01; window opens the next day.
    "WINDOW_START": "2026-05-02T00:00:00Z",
    "WINDOW_END": "2026-05-10T00:00:00Z",
    "WINDOW_ACTIVE_AT": "2026-05-02T06:00:00Z",
}


def create_terminal_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TERMINAL_NAME"],
        "wastewater_daily_capacity_liters": DEFAULTS["WASTEWATER_DAILY_CAPACITY_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["PRODUCT_CODE"],
        "family": DEFAULTS["PRODUCT_FAMILY"],
        "viscosity_class": DEFAULTS["PRODUCT_VISCOSITY"],
        "compatibility_group": DEFAULTS["PRODUCT_GROUP"],
        "flash_point_c": DEFAULTS["PRODUCT_FLASH_POINT_C"],
    }
    defaults.update(overrides)
    return defaults


def create_tank_payload(terminal_id, current_product_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "tank_number": DEFAULTS["TANK_NUMBER"],
        "capacity_m3": DEFAULTS["TANK_CAPACITY_M3"],
        "current_product_id": current_product_id,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {"company_name": DEFAULTS["CONTRACTOR_NAME"]}
    defaults.update(overrides)
    return defaults


def create_safety_event_payload(contractor_id, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "kind": "VIOLATION",
        "severity_weight": 1,
        "occurred_at": "2026-04-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cleaning_job_payload(terminal_id, tank_id, contractor_id,
                                from_product_id, to_product_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "tank_id": tank_id,
        "contractor_id": contractor_id,
        "from_product_id": from_product_id,
        "to_product_id": to_product_id,
        "heel_volume_liters_sounding": DEFAULTS["HEEL_SOUNDING_LITERS"],
        "base_service_fee_cents": DEFAULTS["BASE_SERVICE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def patch_cleaning_job_payload(expected_job_version, **overrides) -> dict:
    defaults = {"expected_job_version": expected_job_version}
    defaults.update(overrides)
    return defaults


def create_service_window_payload(tank_id, expected_tank_version, **overrides) -> dict:
    defaults = {
        "tank_id": tank_id,
        "planned_start": DEFAULTS["WINDOW_START"],
        "planned_end": DEFAULTS["WINDOW_END"],
        "expected_tank_version": expected_tank_version,
    }
    defaults.update(overrides)
    return defaults


def create_waste_profile_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "waste_code": DEFAULTS["WASTE_CODE"],
        "hazard_class": DEFAULTS["HAZARD_CLASS"],
        "lab_flash_point_c": DEFAULTS["LAB_FLASH_POINT_C"],
        "lab_tph_mg_l": DEFAULTS["LAB_TPH_MG_L"],
    }
    defaults.update(overrides)
    return defaults


def create_waste_shipment_payload(job_id, profile_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "profile_id": profile_id,
        "lines": [{"material": "SLUDGE", "kg": 2542, "rate_cents_per_kg": 2.0}],
    }
    defaults.update(overrides)
    return defaults


def create_gas_free_certificate_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "lel_pct": 5.0,
        "o2_pct": 20.9,
        "h2s_ppm": 2.0,
        "benzene_ppm": 0.2,
    }
    defaults.update(overrides)
    return defaults


def create_entry_permit_payload(job_id, cert_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "cert_id": cert_id,
        "max_entrants": DEFAULTS["MAX_ENTRANTS"],
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["INSPECTOR_NAME"],
        "certification_level": DEFAULTS["CERTIFICATION_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(job_id, inspector_id, expected_inspector_version,
                              **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "inspector_id": inspector_id,
        "scheduled_start": "2026-05-03T00:00:00Z",
        "scheduled_end": "2026-05-03T08:00:00Z",
        "expected_inspector_version": expected_inspector_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_finding_payload(inspection_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "severity": "MINOR",
        "description": DEFAULTS["FINDING_DESCRIPTION"],
        "requires_repair": False,
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(finding_id, **overrides) -> dict:
    defaults = {
        "finding_id": finding_id,
        "description": DEFAULTS["REPAIR_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_wastewater_batch_payload(terminal_id, job_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "job_id": job_id,
        "volume_liters": DEFAULTS["BATCH_VOLUME_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def submit_lab_payload(**overrides) -> dict:
    defaults = {
        "ph": DEFAULTS["LAB_PH"],
        "tph_mg_l": DEFAULTS["LAB_TPH"],
    }
    defaults.update(overrides)
    return defaults
