"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

# PRD declares style_code / sku_code / roll_code / line_code / employee_no
# unique per entity table. A single test may build several entities through
# the defaults (e.g. two full setup chains in one test), so the defaults must
# be unique per call; explicit overrides always win.
_COUNTER = itertools.count(1)


def _uniq(base):
    return f"{base}-{next(_COUNTER)}"


DEFAULTS = {
    "STYLE_CODE": "ST-1",
    "BASE_SIZE": "M",
    "SIZE_RUN": ["M"],
    "BASE_MEASUREMENTS": [{"point": "chest", "base_value_in": 20.0}],
    "GRADE_RULES": [],
    "LABOR_COST_CENTS_PER_UNIT": 800,
    "FABRIC_COST_CENTS_PER_UNIT": 500,
    "OP_NAME": "join",
    "OP_MACHINE_TYPE": "MANUAL",
    "OP_SAM_SECONDS": 60,
    "OP_PIECE_RATE_CENTS": 10,
    "TRIM_SKU": "TI-1",
    "TRIM_ORIGIN": "US",
    "TRIM_UNIT_COST": 10,
    "ROLL_CODE": "R-1",
    "FABRIC_CODE": "DEN",
    "ROLL_COST_CENTS_PER_YARD": 200,
    "RECEIVED_YARDS": 41.3,
    "COLOR": "navy",
    "MARKER_LENGTH_YARDS": 40.0,
    "LINE_CODE": "L-1",
    "STATION_COUNT": 2,
    "SHIFT_MINUTES": 480,
    "EMPLOYEE_NO": "E-1",
    "FULL_NAME": "Ann Operator",
    "WORK_DATE": "2026-08-03",
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2026-08-31",
}


def create_style_payload(**overrides):
    defaults = {
        "style_code": _uniq(DEFAULTS["STYLE_CODE"]),
        "base_size": DEFAULTS["BASE_SIZE"],
        "size_run": list(DEFAULTS["SIZE_RUN"]),
        "declared_fabric_domestic": True,
        "target_content_claim": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_tech_pack_payload(**overrides):
    defaults = {
        "version_no": 1,
        "base_measurements": [dict(m) for m in DEFAULTS["BASE_MEASUREMENTS"]],
        "grade_rules": [dict(g) for g in DEFAULTS["GRADE_RULES"]],
        "labor_cost_cents_per_unit": DEFAULTS["LABOR_COST_CENTS_PER_UNIT"],
        "fabric_cost_cents_per_unit": DEFAULTS["FABRIC_COST_CENTS_PER_UNIT"],
    }
    defaults.update(overrides)
    return defaults


def create_operation_spec_payload(**overrides):
    defaults = {
        "sequence_no": 1,
        "name": DEFAULTS["OP_NAME"],
        "machine_type": DEFAULTS["OP_MACHINE_TYPE"],
        "sam_seconds": DEFAULTS["OP_SAM_SECONDS"],
        "piece_rate_cents": DEFAULTS["OP_PIECE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_trim_item_payload(**overrides):
    defaults = {
        "sku_code": _uniq(DEFAULTS["TRIM_SKU"]),
        "description": "trim item",
        "origin_country": DEFAULTS["TRIM_ORIGIN"],
        "unit_cost_cents": DEFAULTS["TRIM_UNIT_COST"],
    }
    defaults.update(overrides)
    return defaults


def create_trim_requirement_payload(**overrides):
    defaults = {
        "units_per_garment": 1,
        "wastage_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_fabric_roll_payload(**overrides):
    defaults = {
        "roll_code": _uniq(DEFAULTS["ROLL_CODE"]),
        "fabric_code": DEFAULTS["FABRIC_CODE"],
        "origin_country": DEFAULTS["TRIM_ORIGIN"],
        "cost_cents_per_yard": DEFAULTS["ROLL_COST_CENTS_PER_YARD"],
        "received_yards": DEFAULTS["RECEIVED_YARDS"],
    }
    defaults.update(overrides)
    return defaults


def create_production_order_payload(**overrides):
    defaults = {
        "color": DEFAULTS["COLOR"],
        "size_quantities": [{"size": DEFAULTS["BASE_SIZE"], "qty": 10}],
    }
    defaults.update(overrides)
    return defaults


def create_marker_payload(**overrides):
    defaults = {
        "marker_length_yards": DEFAULTS["MARKER_LENGTH_YARDS"],
        "planned_pieces": 10,
    }
    defaults.update(overrides)
    return defaults


def create_sewing_line_payload(**overrides):
    defaults = {
        "line_code": _uniq(DEFAULTS["LINE_CODE"]),
        "station_count": DEFAULTS["STATION_COUNT"],
        "shift_minutes": DEFAULTS["SHIFT_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_line_assignment_payload(**overrides):
    defaults = {
        "shift_date": DEFAULTS["WORK_DATE"],
        "start_minute": 480,
        "end_minute": 580,
        "assigned_pieces": 10,
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides):
    defaults = {
        "employee_no": _uniq(DEFAULTS["EMPLOYEE_NO"]),
        "full_name": DEFAULTS["FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_piece_work_entry_payload(**overrides):
    defaults = {
        "work_date": DEFAULTS["WORK_DATE"],
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_run_payload(**overrides):
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_quality_audit_payload(**overrides):
    defaults = {
        "inspection_level": "NORMAL",
        "aql_level": "AQL_2_5",
    }
    defaults.update(overrides)
    return defaults
