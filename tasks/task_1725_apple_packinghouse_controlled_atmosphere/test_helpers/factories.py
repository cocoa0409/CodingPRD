"""Payload factories — one per endpoint body, input fields only."""
from .constants import TEST_DEFAULTS


def create_grower_payload(name="Grower One", grower_code="G1", **overrides):
    payload = {"name": name, "grower_code": grower_code}
    payload.update(overrides)
    return payload


def create_block_payload(orchard_name=TEST_DEFAULTS["ORCHARD_NAME"],
                         block_code=TEST_DEFAULTS["BLOCK_CODE"],
                         variety=TEST_DEFAULTS["VARIETY"],
                         storage_life_days=TEST_DEFAULTS["STORAGE_LIFE_DAYS"],
                         **overrides):
    payload = {
        "orchard_name": orchard_name,
        "block_code": block_code,
        "variety": variety,
        "storage_life_days": storage_life_days,
    }
    payload.update(overrides)
    return payload


def create_lot_payload(grower_id, block_id, received_bin_count=5,
                       received_weight_lbs=4000, avg_color_pct=80, **overrides):
    payload = {
        "grower_id": grower_id,
        "block_id": block_id,
        "received_bin_count": received_bin_count,
        "received_weight_lbs": received_weight_lbs,
        "avg_color_pct": avg_color_pct,
    }
    payload.update(overrides)
    return payload


def presize_payload(size_small_lbs=500, size_medium_lbs=2000,
                    size_large_lbs=1000, presize_cull_lbs=500, **overrides):
    payload = {
        "size_small_lbs": size_small_lbs,
        "size_medium_lbs": size_medium_lbs,
        "size_large_lbs": size_large_lbs,
        "presize_cull_lbs": presize_cull_lbs,
    }
    payload.update(overrides)
    return payload


def create_ca_room_payload(room_code=TEST_DEFAULTS["ROOM_CODE"],
                           bin_capacity=TEST_DEFAULTS["BIN_CAPACITY"],
                           o2_setpoint_pct=TEST_DEFAULTS["O2_SETPOINT_PCT"],
                           **overrides):
    payload = {
        "room_code": room_code,
        "bin_capacity": bin_capacity,
        "o2_setpoint_pct": o2_setpoint_pct,
    }
    payload.update(overrides)
    return payload


def schedule_update_payload(expected_ca_room_version=None, planned_open_date=None,
                            o2_setpoint_pct=None, **overrides):
    payload = {}
    if expected_ca_room_version is not None:
        payload["expected_ca_room_version"] = expected_ca_room_version
    if planned_open_date is not None:
        payload["planned_open_date"] = planned_open_date
    if o2_setpoint_pct is not None:
        payload["o2_setpoint_pct"] = o2_setpoint_pct
    payload.update(overrides)
    return payload


def seal_payload(planned_open_date=TEST_DEFAULTS["PLANNED_OPEN_DATE"], **overrides):
    payload = {"planned_open_date": planned_open_date}
    payload.update(overrides)
    return payload


def atmosphere_reading_payload(o2_pct=TEST_DEFAULTS["O2_SETPOINT_PCT"], **overrides):
    payload = {"o2_pct": o2_pct}
    payload.update(overrides)
    return payload


def create_inspection_payload(scald_pct=4.0, bitter_pit_pct=3.0, decay_pct=4.9,
                              **overrides):
    payload = {
        "scald_pct": scald_pct,
        "bitter_pit_pct": bitter_pit_pct,
        "decay_pct": decay_pct,
    }
    payload.update(overrides)
    return payload


def create_allocation_payload(lot_id, bins=5, **overrides):
    payload = {"lot_id": lot_id, "bins": bins}
    payload.update(overrides)
    return payload


def create_spec_payload(customer_name=TEST_DEFAULTS["CUSTOMER_NAME"],
                        label_code=TEST_DEFAULTS["LABEL_CODE"],
                        grade_min=TEST_DEFAULTS["GRADE_MIN"],
                        color_min_pct=TEST_DEFAULTS["COLOR_MIN_PCT"],
                        size_class=TEST_DEFAULTS["SIZE_CLASS"],
                        pack_style=TEST_DEFAULTS["PACK_STYLE"], **overrides):
    payload = {
        "customer_name": customer_name,
        "label_code": label_code,
        "grade_min": grade_min,
        "color_min_pct": color_min_pct,
        "size_class": size_class,
        "pack_style": pack_style,
    }
    payload.update(overrides)
    return payload


def create_packing_run_payload(lot_id, spec_id, pool_id,
                               line_code=TEST_DEFAULTS["LINE_CODE"],
                               scheduled_start=TEST_DEFAULTS["RUN_START"],
                               scheduled_end=TEST_DEFAULTS["RUN_END"],
                               input_weight_lbs=500, **overrides):
    payload = {
        "lot_id": lot_id,
        "spec_id": spec_id,
        "pool_id": pool_id,
        "line_code": line_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "input_weight_lbs": input_weight_lbs,
    }
    payload.update(overrides)
    return payload


def complete_run_payload(cartons_produced=20, packed_weight_lbs=3400,
                         cull_weight_lbs=400, juice_weight_lbs=200, **overrides):
    payload = {
        "cartons_produced": cartons_produced,
        "packed_weight_lbs": packed_weight_lbs,
        "cull_weight_lbs": cull_weight_lbs,
        "juice_weight_lbs": juice_weight_lbs,
    }
    payload.update(overrides)
    return payload


def create_pool_payload(variety=TEST_DEFAULTS["VARIETY"],
                        grade_class=TEST_DEFAULTS["GRADE_CLASS"],
                        season=TEST_DEFAULTS["SEASON"], **overrides):
    payload = {
        "variety": variety,
        "grade_class": grade_class,
        "season": season,
    }
    payload.update(overrides)
    return payload


def record_sale_payload(cartons_sold=10, gross_revenue_cents=30000,
                        deduction_cents=0, **overrides):
    payload = {
        "cartons_sold": cartons_sold,
        "gross_revenue_cents": gross_revenue_cents,
        "deduction_cents": deduction_cents,
    }
    payload.update(overrides)
    return payload


def close_pool_payload(expected_pool_version, **overrides):
    payload = {"expected_pool_version": expected_pool_version}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides):
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
