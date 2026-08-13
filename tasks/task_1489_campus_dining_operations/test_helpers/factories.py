"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "HALL_NAME": "Test Hall",
    "SERVICE_MODEL": "BOARD",
    "DINING_CAPACITY": 800,
    "KITCHEN_CAPACITY": 500,
    "VENDOR_NAME": "CampusEats LLC",
    "BOARD_RATE_CENTS": 500,
    "RETAIL_BPS": 1000,
    "CATERING_BPS": 800,
    "MIN_GUARANTEE_CENTS": 0,
    "CONTRACT_START": "2026-08-01",
    "CONTRACT_END": "2026-12-01",
    "CYCLE_NAME": "Fall Cycle",
    "CYCLE_WEEKS": 4,
    "CYCLE_START": "2026-07-01",
    "CYCLE_END": "2026-10-01",
    "RECIPE_NAME": "Grain Bowl",
    "STATION": "GLOBAL",
    "POPULARITY_SHARE": 0.5,
    "UNIT_COST_CENTS": 500,
    "MEAL_PERIOD": "LUNCH",
    "FORECAST_VARIANT": "BASE",
    "STUDENT_REF": "STU-1",
    "DIETARY_REQUIREMENT": "VEGAN",
    "STAFF_REF": "STAFF-1",
    "LABOR_ROLE": "COOK",
    "SHIFT_START": 480,
    "SHIFT_END": 960,
    "HOURLY_RATE_CENTS": 2000,
    "WASTE_CATEGORY": "PRE_CONSUMER",
    "WASTE_DISPOSITION": "LANDFILL",
    "WEIGHT_KG": 1.0,
    "DEPT_NAME": "Engineering",
    "DEPT_CODE": "ENG",
    "SEMESTER_BUDGET_CENTS": 1000000,
    "TIME_SLOT": "LUNCH",
    "GUARANTEED_COVERS": 10,
    "PERIOD_MONTH": "2026-08",
}


def create_dining_hall_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["HALL_NAME"],
        "service_model": DEFAULTS["SERVICE_MODEL"],
        "dining_capacity": DEFAULTS["DINING_CAPACITY"],
        "catering_kitchen_capacity": DEFAULTS["KITCHEN_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_contract_payload(dining_hall_id, **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "board_rate_per_cover_cents": DEFAULTS["BOARD_RATE_CENTS"],
        "retail_commission_bps": DEFAULTS["RETAIL_BPS"],
        "catering_commission_bps": DEFAULTS["CATERING_BPS"],
        "minimum_monthly_guarantee_cents": DEFAULTS["MIN_GUARANTEE_CENTS"],
        "effective_start_date": DEFAULTS["CONTRACT_START"],
        "effective_end_date": DEFAULTS["CONTRACT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_cycle_payload(dining_hall_id, **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "name": DEFAULTS["CYCLE_NAME"],
        "cycle_length_weeks": DEFAULTS["CYCLE_WEEKS"],
        "start_date": DEFAULTS["CYCLE_START"],
        "end_date": DEFAULTS["CYCLE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_recipe_payload(dining_hall_id, **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "name": DEFAULTS["RECIPE_NAME"],
        "station": DEFAULTS["STATION"],
        "allergen_tags": [],
        "dietary_flags": [],
        "popularity_share": DEFAULTS["POPULARITY_SHARE"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "allergen_reviewed": True,
    }
    defaults.update(overrides)
    return defaults


def create_meal_period_payload(dining_hall_id, menu_cycle_id, service_date,
                               **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "menu_cycle_id": menu_cycle_id,
        "service_date": service_date,
        "meal_period": DEFAULTS["MEAL_PERIOD"],
    }
    defaults.update(overrides)
    return defaults


def swipe_event_entry(entry_type, amount_cents, count=None) -> dict:
    entry = {"entry_type": entry_type, "amount_cents": amount_cents}
    if count is not None:
        entry["count"] = count
    return entry


def create_forecast_payload(recipe_id, expected_meal_period_version, **overrides) -> dict:
    defaults = {
        "recipe_id": recipe_id,
        "variant": DEFAULTS["FORECAST_VARIANT"],
        "expected_meal_period_version": expected_meal_period_version,
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_payload(dining_hall_id, **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "student_ref": DEFAULTS["STUDENT_REF"],
        "allergen_exclusions": [],
        "dietary_requirement": DEFAULTS["DIETARY_REQUIREMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_labor_shift_payload(dining_hall_id, **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "role": DEFAULTS["LABOR_ROLE"],
        "shift_date": "2026-08-10",
        "start_minute": DEFAULTS["SHIFT_START"],
        "end_minute": DEFAULTS["SHIFT_END"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_waste_log_payload(**overrides) -> dict:
    defaults = {
        "category": DEFAULTS["WASTE_CATEGORY"],
        "disposition": DEFAULTS["WASTE_DISPOSITION"],
        "weight_kg": DEFAULTS["WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_report_payload(dining_hall_id, inspection_date, violations,
                                     **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "inspection_date": inspection_date,
        "violations": violations,
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_payload(**overrides) -> dict:
    defaults = {
        "violation_code": "FIX-1",
        "severity": "MINOR",
        "due_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DEPT_NAME"],
        "department_code": DEFAULTS["DEPT_CODE"],
        "semester_budget_cents": DEFAULTS["SEMESTER_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def menu_line(recipe_id, portions) -> dict:
    return {"recipe_id": recipe_id, "portions": portions}


def create_catering_order_payload(dining_hall_id, department_id, event_date,
                                  menu_lines, **overrides) -> dict:
    defaults = {
        "dining_hall_id": dining_hall_id,
        "department_id": department_id,
        "event_date": event_date,
        "time_slot": DEFAULTS["TIME_SLOT"],
        "guaranteed_covers": DEFAULTS["GUARANTEED_COVERS"],
        "menu_lines": menu_lines,
    }
    defaults.update(overrides)
    return defaults


def create_commission_statement_payload(**overrides) -> dict:
    defaults = {"period_month": DEFAULTS["PERIOD_MONTH"]}
    defaults.update(overrides)
    return defaults
