"""Entity assertions and the domain invariants that must always hold."""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MACHINING_STATES = [
    "SCHEDULED",
    "RUNNING",
    "INTERRUPTED",
    "MACHINING_COMPLETE",
    "CANCELLED",
]
QUALITY_STATES = ["PENDING_INSPECTION", "IN_SPC", "QUALITY_HOLD", "ACCEPTED", "REJECTED"]
ALLOY_CODES = ["303SS", "316SS", "C360", "6061AL", "12L14"]
GAUGE_TYPES = ["MICROMETER", "BORE_GAUGE", "OPTICAL_COMPARATOR", "CMM"]


def assert_identity_quartet(data: dict):
    """id, created_at, updated_at and version as the PRD describes them."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_three_fractional_digits(timestamp: str):
    assert isinstance(timestamp, str) and timestamp.endswith("Z"), (
        f"timestamp must be UTC and end with Z, got {timestamp!r}"
    )
    assert "." in timestamp, f"timestamp must carry fractional seconds, got {timestamp!r}"
    fraction = timestamp.split(".")[-1][:-1]
    assert len(fraction) == 3 and fraction.isdigit(), (
        f"timestamp must carry exactly three fractional digits, got {timestamp!r}"
    )


def assert_operator(data: dict):
    assert_identity_quartet(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["badge_code"], str) and data["badge_code"]
    assert isinstance(data["certifications"], list)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_machine(data: dict):
    assert_identity_quartet(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["max_bar_diameter_mm"] > 0
    assert data["status"] in ["AVAILABLE", "RUNNING", "DOWN"]
    assert isinstance(data["chip_accrual_by_alloy"], dict)
    assert data["coolant_makeup_liters"] >= 0
    assert isinstance(data["lifetime_reclamation_credit_cents"], int)


def assert_part(data: dict):
    assert_identity_quartet(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["alloy_code"] in ALLOY_CODES
    assert data["bar_diameter_mm"] > 0
    assert data["cut_off_length_mm"] > 0
    assert data["cycle_time_sec"] > 0
    assert data["setup_hours"] >= 0
    assert data["material_cost_cents_per_meter"] >= 0
    assert data["finished_mass_g"] > 0
    assert isinstance(data["observed_accepted_qty"], int)


def assert_characteristic(data: dict):
    assert_identity_quartet(data)
    assert isinstance(data["char_code"], str) and data["char_code"]
    assert data["usl"] > data["lsl"]
    assert data["cpk_min"] > 0
    assert data["subgroup_size"] in [3, 5]
    assert data["sample_freq_pieces"] >= 1
    assert data["required_gauge_type"] in GAUGE_TYPES


def assert_gauge(data: dict):
    assert_identity_quartet(data)
    assert isinstance(data["gauge_code"], str) and data["gauge_code"]
    assert data["gauge_type"] in GAUGE_TYPES
    assert data["grr_pct"] >= 0
    assert data["status"] in ["IN_SERVICE", "CALIBRATION_DUE", "GRR_FAILED", "RETIRED"]
    assert isinstance(data["calibration_count"], int) and data["calibration_count"] >= 0


def assert_bar_stock_lot(data: dict):
    assert_identity_quartet(data)
    assert isinstance(data["heat_number"], str) and data["heat_number"]
    assert data["alloy_code"] in ALLOY_CODES
    assert data["bar_length_mm"] > 0
    assert data["bars_received"] >= 1
    assert data["feeder_slots"] >= 1
    assert data["status"] in ["RECEIVED", "CERTIFIED", "QUARANTINED", "DEPLETED"]
    assert_bar_length_ledger(data)


def assert_bar_length_ledger(lot: dict):
    """available + reserved + consumed must equal the immutable total."""
    total = lot["total_length_mm"]
    parts = lot["available_length_mm"] + lot["reserved_length_mm"] + lot["consumed_length_mm"]
    assert parts == pytest.approx(total, abs=1e-6), (
        f"bar length ledger drifted: {lot['available_length_mm']} + "
        f"{lot['reserved_length_mm']} + {lot['consumed_length_mm']} != {total}"
    )
    assert lot["available_length_mm"] >= 0
    assert lot["reserved_length_mm"] >= 0
    assert lot["consumed_length_mm"] >= 0


def assert_quote(data: dict):
    assert_identity_quartet(data)
    assert data["lot_qty"] >= 1
    assert data["status"] in ["DRAFT", "PRICED", "ACCEPTED", "CONSUMED", "EXPIRED"]


def assert_blanket_po(data: dict):
    assert_identity_quartet(data)
    assert data["total_committed_qty"] >= 1
    assert data["status"] in ["ACTIVE", "SUSPENDED", "EXHAUSTED", "EXPIRED"]
    assert_po_quantity_ledger(data)


def assert_po_quantity_ledger(po: dict):
    """remaining + open_released + fulfilled must equal the committed total."""
    total = po["total_committed_qty"]
    parts = po["remaining_qty"] + po["open_released_qty"] + po["fulfilled_qty"]
    assert parts == total, (
        f"committed quantity ledger drifted: {po['remaining_qty']} + "
        f"{po['open_released_qty']} + {po['fulfilled_qty']} != {total}"
    )
    assert po["remaining_qty"] >= 0
    assert po["open_released_qty"] >= 0
    assert po["fulfilled_qty"] >= 0


def assert_kanban_release(data: dict):
    assert_identity_quartet(data)
    assert data["qty"] >= 1
    assert data["status"] in ["RELEASED", "IN_PRODUCTION", "FULFILLED", "SHORT_CLOSED"]
    assert isinstance(data["fulfilled_qty"], int)


def assert_work_order(data: dict):
    assert_identity_quartet(data)
    assert data["qty_ordered"] >= 1
    assert data["machining_status"] in MACHINING_STATES
    assert data["quality_status"] in QUALITY_STATES
    assert data["bars_reserved"] >= 1
    assert data["reserved_length_mm"] > 0
    assert data["qty_good"] + data["qty_scrap"] <= data["qty_ordered"]


def assert_tool_assignment(data: dict):
    assert_identity_quartet(data)
    assert data["station"] >= 1
    assert data["expected_life_pieces"] >= 1
    assert data["drift_limit_um"] > 0
    assert data["status"] in ["IN_SERVICE", "OFFSET_HOLD", "LIFE_EXPIRED", "RETIRED"]
    assert isinstance(data["pieces_since_index"], int)
    assert isinstance(data["offset_log_count"], int)


def assert_spc_sample(data: dict):
    """A subgroup is an immutable observation: id and created_at, nothing more."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "a measured subgroup must not carry updated_at"
    assert "version" not in data, "a measured subgroup must not carry version"
    assert data["piece_index"] >= 1
    assert isinstance(data["measurements"], list) and data["measurements"]
    assert data["disposition"] in ["ACCEPT", "MARGINAL", "REJECT"]
    assert isinstance(data["out_of_spec_count"], int)


def assert_routing_step(data: dict):
    assert_identity_quartet(data)
    assert data["sequence"] >= 1
    assert data["operation"] in [
        "DEBURR",
        "WASH",
        "HEAT_TREAT",
        "PLATING",
        "INSPECTION_100PCT",
    ]
    assert data["status"] in ["PENDING", "IN_PROGRESS", "COMPLETE", "BLOCKED"]


def assert_whole_cents(value):
    assert isinstance(value, int), f"monetary values are whole cents, got {value!r}"


def assert_decimals(value, places: int):
    assert round(float(value), places) == pytest.approx(float(value), abs=1e-9), (
        f"{value} carries more than {places} decimal places"
    )
