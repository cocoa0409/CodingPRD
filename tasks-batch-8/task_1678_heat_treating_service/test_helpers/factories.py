"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULT_RECIPE = {
    "alloy_code": "4140",
    "spec_code": "AMS2759",
    "soak_temp_f": 1650,
    "soak_tolerance_f": 10,
    "min_soak_minutes": 60,
    "quench_media": "OIL",
    "required_furnace_class": "CLASS_3",
    "max_retreats": 1,
    "fixture_distortion_allowance_in": 0.005,
    "hardness_min_hrc": 38,
    "hardness_max_hrc": 44,
}

DEFAULT_FURNACE = {
    "furnace_code": "F-1",
    "furnace_class": "CLASS_3",
    "max_load_weight_lb": 1000,
    "quench_media_supported": ["OIL"],
}

DEFAULT_WINDOW = ("2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z")


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "Test Customer Co"}
    defaults.update(overrides)
    return defaults


def create_recipe_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_RECIPE)
    defaults.update(overrides)
    return defaults


def create_furnace_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_FURNACE)
    defaults.update(overrides)
    return defaults


def create_pyrometry_payload(furnace_id, record_type="TUS",
                             performed_at="2026-08-01T00:00:00Z", result="PASS",
                             **overrides) -> dict:
    defaults = {
        "furnace_id": furnace_id,
        "record_type": record_type,
        "performed_at": performed_at,
        "result": result,
    }
    if record_type == "INSTRUMENT_CALIBRATION":
        # instrument_id is required on calibration records (PRD §3.3)
        defaults.setdefault("instrument_id", "TC-CAL-9")
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id, recipe_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "recipe_id": recipe_id,
        "part_quantity": 5,
        "received_weight_lb": 100,
        "declared_value_cents": 500000,
        "processing_charge_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_load_batch_payload(furnace_id, recipe_id, **overrides) -> dict:
    defaults = {
        "furnace_id": furnace_id,
        "recipe_id": recipe_id,
        "scheduled_start_at": DEFAULT_WINDOW[0],
        "scheduled_end_at": DEFAULT_WINDOW[1],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(work_order_id, expected_load_batch_version,
                              **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "expected_load_batch_version": expected_load_batch_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(work_order_id, hardness_readings=None,
                              measured_distortion_in=0.004, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "hardness_readings": hardness_readings if hardness_readings is not None else [40, 42, 41],
        "measured_distortion_in": measured_distortion_in,
    }
    defaults.update(overrides)
    return defaults


def create_thermocouple_payload(load_batch_id, channel="LOAD_TC_1",
                                recorded_at="2026-08-02T10:00:00Z", temp_f=1650,
                                **overrides) -> dict:
    defaults = {
        "load_batch_id": load_batch_id,
        "channel": channel,
        "recorded_at": recorded_at,
        "temp_f": temp_f,
    }
    defaults.update(overrides)
    return defaults


def create_audit_package_payload(furnace_id, load_batch_ids, **overrides) -> dict:
    defaults = {"furnace_id": furnace_id, "load_batch_ids": load_batch_ids}
    defaults.update(overrides)
    return defaults
