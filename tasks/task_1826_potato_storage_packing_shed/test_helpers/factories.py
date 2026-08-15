"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "GROWER_NAME": "Test Grower",
    "GROWER_CODE": "G-TEST",
    "SHED_NAME": "Test Shed",
    "BIN_CODE": "B-1",
    "BIN_CAPACITY_CWT": 2000.00,
    "VARIETY": "RUSSET_BURBANK",
    "HARVEST_DATE": "2026-07-20",
    "LOT_WEIGHT_CWT": 500.00,
    "BUYER_NAME": "Test Buyer",
    "COMMITTED_CWT": 300.00,
    "PRICE_CENTS_PER_CWT": 2000,
    "GRADE_MIN_US1_PCT": 50.0,
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-12-01T00:00:00Z",
    "PRIORITY_RANK": 1,
    "PACK_UNIT_WEIGHT_LBS": 50,
    "REQUESTED_PACKED_CWT": 75.00,
    "SEASON_LABEL": "2026-storage",
}


def create_grower_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GROWER_NAME"],
        "grower_code": DEFAULTS["GROWER_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_shed_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["SHED_NAME"]}
    defaults.update(overrides)
    return defaults


def create_bin_payload(**overrides) -> dict:
    defaults = {
        "bin_code": DEFAULTS["BIN_CODE"],
        "capacity_cwt": DEFAULTS["BIN_CAPACITY_CWT"],
    }
    defaults.update(overrides)
    return defaults


def create_field_lot_payload(**overrides) -> dict:
    defaults = {
        "variety": DEFAULTS["VARIETY"],
        "harvest_date": DEFAULTS["HARVEST_DATE"],
        "original_weight_cwt": DEFAULTS["LOT_WEIGHT_CWT"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(expected_field_lot_version, **overrides) -> dict:
    defaults = {
        "assessment_date": "2026-08-02",
        "us1_pct": 70.0,
        "us2_pct": 20.0,
        "cull_pct": 10.0,
        "cumulative_shrink_cwt": 0.00,
        "expected_field_lot_version": expected_field_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "buyer_name": DEFAULTS["BUYER_NAME"],
        "variety": DEFAULTS["VARIETY"],
        "committed_volume_cwt": DEFAULTS["COMMITTED_CWT"],
        "price_cents_per_cwt": DEFAULTS["PRICE_CENTS_PER_CWT"],
        "grade_min_us1_pct": DEFAULTS["GRADE_MIN_US1_PCT"],
        "delivery_window_start": DEFAULTS["WINDOW_START"],
        "delivery_window_end": DEFAULTS["WINDOW_END"],
        "priority_rank": DEFAULTS["PRIORITY_RANK"],
    }
    defaults.update(overrides)
    return defaults


def create_pack_order_payload(shed_id, **overrides) -> dict:
    defaults = {
        "order_type": "CONTRACT",
        "shed_id": shed_id,
        "variety": DEFAULTS["VARIETY"],
        "pack_unit_weight_lbs": DEFAULTS["PACK_UNIT_WEIGHT_LBS"],
        "grade_min_us1_pct": DEFAULTS["GRADE_MIN_US1_PCT"],
        "requested_packed_cwt": DEFAULTS["REQUESTED_PACKED_CWT"],
        "allocation_policy": "LOT_ASSESSMENT",
    }
    defaults.update(overrides)
    return defaults


def create_pack_run_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-08-10T08:00:00Z",
        "scheduled_end": "2026-08-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_wash_check_payload(**overrides) -> dict:
    """Default payload is a clean PASS: 2.0 NTU / 100 ppm / 50 F."""
    defaults = {
        "measured_at": "2026-08-02T06:00:00Z",
        "turbidity_ntu": 2.0,
        "chlorine_ppm": 100,
        "water_temp_f": 50,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {"field_work_date": "2026-08-05"}
    defaults.update(overrides)
    return defaults


def create_settlement_payload(expected_grower_version, **overrides) -> dict:
    defaults = {
        "season_label": DEFAULTS["SEASON_LABEL"],
        "expected_grower_version": expected_grower_version,
    }
    defaults.update(overrides)
    return defaults


def make_draw(field_lot_id, raw_drawn_cwt, packed_cwt, us1_cwt, us2_cwt, cull_cwt,
              cull_channel="WASTE") -> dict:
    """One per-lot draw record for a completing pack-run close (PRD §3.5)."""
    return {
        "field_lot_id": field_lot_id,
        "raw_drawn_cwt": raw_drawn_cwt,
        "packed_cwt": packed_cwt,
        "us1_cwt": us1_cwt,
        "us2_cwt": us2_cwt,
        "cull_cwt": cull_cwt,
        "cull_channel": cull_channel,
    }
