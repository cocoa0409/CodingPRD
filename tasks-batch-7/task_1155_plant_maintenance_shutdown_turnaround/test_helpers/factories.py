"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TA_NAME": "TA-2026-CRU2",
    "PLANT_UNIT": "CRU-2",
    "PLANNED_START": "2026-06-10T00:00:00Z",
    "PLANNED_END": "2026-07-10T00:00:00Z",
    "AUTHORIZED_BUDGET_CENTS": 900_000_000,
    "CONTINGENCY_BUDGET_CENTS": 1_000_000,
    "WORK_ITEM_TITLE": "Anchor",
    "SYSTEM_AREA": "CRU-2-A",
    "WORK_TYPE": "CORRECTIVE",
    "RISK_CLASS": "A",
    "ESTIMATED_HOURS": 10,
    "ESTIMATED_COST_CENTS": 10_000,
    "CONTRACTOR_NAME": "Delta Mechanical",
    "CRAFT": "PIPEFITTING",
    "HEADCOUNT_CAP": 5,
    "WORKER_NAME": "Rae Wolder",
    "TRADE": "WELDER",
    "SHIFT_DATE": "2026-06-15",
    "SHIFT_TYPE": "DAY",
    "SHIFT_STARTS": "2026-06-15T08:00:00Z",
    "SHIFT_ENDS": "2026-06-15T16:00:00Z",
    "PLANNED_HEADCOUNT": 3,
    "PLANNED_HOURS": 8,
    "EQUIPMENT_TAG": "EXCH-E201",
    "ISOLATION_MODE": "EXCLUSIVE",
    "ISOLATED_FROM": "2026-06-10T00:00:00Z",
    "ISOLATED_UNTIL": "2026-06-25T00:00:00Z",
    "PERMIT_TYPE": "COLD_WORK",
    "HAZARD_CLASS": "LOW",
    "VALID_FROM": "2026-06-12T00:00:00Z",
    "VALID_UNTIL": "2026-06-20T00:00:00Z",
    "DISCOVERY_DESCRIPTION": "Corrosion found on open",
    "QUOTED_COST_CENTS": 90_000,
    "QUOTED_HOURS": 20,
    "AREA_NAME": "North Laydown",
    "CAPACITY_SQM": 500,
    "MATERIAL_DESCRIPTION": "Blind stock",
    "AREA_SQM": 40,
    "WINDOW_FROM": "2026-06-10T00:00:00Z",
    "WINDOW_UNTIL": "2026-06-20T00:00:00Z",
    "REPORT_DATE": "2026-06-15",
    "PUNCH_DESCRIPTION": "Weep-hole plug weeping",
    "PUNCH_CATEGORY": "A",
}


def create_turnaround_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TA_NAME"],
        "plant_unit": DEFAULTS["PLANT_UNIT"],
        "planned_start": DEFAULTS["PLANNED_START"],
        "planned_end": DEFAULTS["PLANNED_END"],
        "authorized_budget_cents": DEFAULTS["AUTHORIZED_BUDGET_CENTS"],
        "contingency_budget_cents": DEFAULTS["CONTINGENCY_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_work_item_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["WORK_ITEM_TITLE"],
        "system_area": DEFAULTS["SYSTEM_AREA"],
        "work_type": DEFAULTS["WORK_TYPE"],
        "risk_class": DEFAULTS["RISK_CLASS"],
        "estimated_hours": DEFAULTS["ESTIMATED_HOURS"],
        "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
        "requires_permit": False,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CONTRACTOR_NAME"],
        "craft": DEFAULTS["CRAFT"],
        "headcount_cap": DEFAULTS["HEADCOUNT_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["WORKER_NAME"],
        "trade": DEFAULTS["TRADE"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_date": DEFAULTS["SHIFT_DATE"],
        "shift_type": DEFAULTS["SHIFT_TYPE"],
        "starts_at": DEFAULTS["SHIFT_STARTS"],
        "ends_at": DEFAULTS["SHIFT_ENDS"],
        "planned_headcount": DEFAULTS["PLANNED_HEADCOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {
        "planned_hours": DEFAULTS["PLANNED_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_isolation_payload(**overrides) -> dict:
    defaults = {
        "equipment_tag": DEFAULTS["EQUIPMENT_TAG"],
        "isolation_mode": DEFAULTS["ISOLATION_MODE"],
        "isolated_from": DEFAULTS["ISOLATED_FROM"],
        "isolated_until": DEFAULTS["ISOLATED_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_type": DEFAULTS["PERMIT_TYPE"],
        "hazard_class": DEFAULTS["HAZARD_CLASS"],
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
        "required_isolation_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_discovery_payload(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["DISCOVERY_DESCRIPTION"],
        "quoted_cost_cents": DEFAULTS["QUOTED_COST_CENTS"],
        "quoted_hours": DEFAULTS["QUOTED_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_laydown_area_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AREA_NAME"],
        "capacity_sqm": DEFAULTS["CAPACITY_SQM"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    defaults = {
        "material_description": DEFAULTS["MATERIAL_DESCRIPTION"],
        "area_sqm": DEFAULTS["AREA_SQM"],
        "window_from": DEFAULTS["WINDOW_FROM"],
        "window_until": DEFAULTS["WINDOW_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_report_line(worker_id, shift_id, hours, hazard_flag=False) -> dict:
    return {
        "worker_id": worker_id,
        "shift_id": shift_id,
        "hours": hours,
        "hazard_flag": hazard_flag,
    }


def create_daily_report_payload(**overrides) -> dict:
    defaults = {
        "report_date": DEFAULTS["REPORT_DATE"],
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(**overrides) -> dict:
    defaults = {
        "category": DEFAULTS["PUNCH_CATEGORY"],
        "description": DEFAULTS["PUNCH_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults
