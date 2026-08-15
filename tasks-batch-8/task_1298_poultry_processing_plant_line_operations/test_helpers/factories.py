"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "LINE_CODE": "EV-1",
    "RATED_SPEED_BPM": 200,
    "SHIFT_DATE": "2026-08-01",
    "SHIFT_CODE": "DAY_A",
    "SHACKLE_CAPACITY_BIRDS": 20000,
    "LABOR_HOURS_BUDGET": 100.0,
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-08-01T02:00:00Z",
    "LOT_CODE": "FL-100",
    "GROWER_NAME": "GrowerA",
    "BOOKED_HEAD_COUNT": 10000,
    "EXPECTED_AVG_LIVE_WEIGHT_LB": 5.0,
    "HEAD_COUNT_RECEIVED": 10000,
    "DOA_COUNT": 50,
    "TOTAL_LIVE_WEIGHT_LB": 50000.0,
    "PLANNED_SPEED_BPM": 175,
    "CARCASS_COUNT": 100,
    "GALLONS": 100.0,
    "POUNDS_ORDERED": 500.0,
    "DUE_AT": "2026-08-03T00:00:00Z",
    "CREW_COUNT": 12,
    "INPUT_WEIGHT_LB": 1000.0,
    "WAIVER_MAX_SPEED_BPM": 195,
}


def create_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": DEFAULTS["LINE_CODE"],
        "line_type": "EVISCERATION",
        "rated_speed_bpm": DEFAULTS["RATED_SPEED_BPM"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_date": DEFAULTS["SHIFT_DATE"],
        "shift_code": DEFAULTS["SHIFT_CODE"],
        "shackle_capacity_birds": DEFAULTS["SHACKLE_CAPACITY_BIRDS"],
        "labor_hours_budget": DEFAULTS["LABOR_HOURS_BUDGET"],
    }
    defaults.update(overrides)
    return defaults


def staffing_payload(expected_shift_version, **overrides) -> dict:
    defaults = {
        "shacklers_present": 10,
        "eviscerators_present": 20,
        "deboners_present": 12,
        "qa_techs_present": 2,
        "expected_shift_version": expected_shift_version,
    }
    defaults.update(overrides)
    return defaults


def create_sanitation_run_payload(shift_id, line_id, **overrides) -> dict:
    defaults = {
        "shift_id": shift_id,
        "line_id": line_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_preop_inspection_payload(shift_id, line_id, **overrides) -> dict:
    defaults = {"shift_id": shift_id, "line_id": line_id}
    defaults.update(overrides)
    return defaults


def create_waiver_payload(expected_line_version, **overrides) -> dict:
    defaults = {
        "max_speed_bpm": DEFAULTS["WAIVER_MAX_SPEED_BPM"],
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-08-02T00:00:00Z",
        "expected_line_version": expected_line_version,
    }
    defaults.update(overrides)
    return defaults


def create_flock_lot_payload(receiving_shift_id, **overrides) -> dict:
    defaults = {
        "lot_code": DEFAULTS["LOT_CODE"],
        "grower_name": DEFAULTS["GROWER_NAME"],
        "booked_head_count": DEFAULTS["BOOKED_HEAD_COUNT"],
        "expected_avg_live_weight_lb": DEFAULTS["EXPECTED_AVG_LIVE_WEIGHT_LB"],
        "receiving_shift_id": receiving_shift_id,
    }
    defaults.update(overrides)
    return defaults


def receive_flock_lot_payload(**overrides) -> dict:
    defaults = {
        "head_count_received": DEFAULTS["HEAD_COUNT_RECEIVED"],
        "doa_count": DEFAULTS["DOA_COUNT"],
        "total_live_weight_lb": DEFAULTS["TOTAL_LIVE_WEIGHT_LB"],
    }
    defaults.update(overrides)
    return defaults


def create_line_run_payload(shift_id, line_id, flock_lot_id, **overrides) -> dict:
    defaults = {
        "shift_id": shift_id,
        "line_id": line_id,
        "flock_lot_id": flock_lot_id,
        "planned_speed_bpm": DEFAULTS["PLANNED_SPEED_BPM"],
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(**overrides) -> dict:
    defaults = {"to_status": "COMPLETED", "birds_hung": 9950, "carcass_weight_lb": 36000.0}
    defaults.update(overrides)
    return defaults


def create_condemnation_record_payload(line_run_id, **overrides) -> dict:
    defaults = {
        "line_run_id": line_run_id,
        "condemnation_code": "SEPTICEMIA",
        "carcass_count": DEFAULTS["CARCASS_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_utility_reading_payload(shift_id, **overrides) -> dict:
    defaults = {
        "shift_id": shift_id,
        "meter_type": "PROCESS_WATER",
        "gallons": DEFAULTS["GALLONS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "customer_name": "CustX",
        "product_code": "WINGS",
        "pounds_ordered": DEFAULTS["POUNDS_ORDERED"],
        "temperature_requirement": "FROZEN",
        "due_at": DEFAULTS["DUE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_deboning_batch_payload(order_id, flock_lot_id, shift_id, line_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "flock_lot_id": flock_lot_id,
        "shift_id": shift_id,
        "line_id": line_id,
        "crew_count": DEFAULTS["CREW_COUNT"],
        "input_weight_lb": DEFAULTS["INPUT_WEIGHT_LB"],
    }
    defaults.update(overrides)
    return defaults


def complete_batch_payload(**overrides) -> dict:
    defaults = {
        "to_status": "COMPLETED",
        "actual_output_weight_lb": 980.0,
        "actual_labor_hours": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_chill_chain_log_payload(finished_lot_id, **overrides) -> dict:
    defaults = {
        "finished_lot_id": finished_lot_id,
        "location": "CHILLER",
        "temperature_c": 3.5,
    }
    defaults.update(overrides)
    return defaults
