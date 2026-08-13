"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Fields every primary resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_alloy_spec(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grade_code"], str) and data["grade_code"]
    assert isinstance(data["forge_temp_min_f"], int)
    assert isinstance(data["forge_temp_max_f"], int)
    assert data["forge_temp_max_f"] > data["forge_temp_min_f"]
    assert isinstance(data["reheat_limit"], int)
    assert isinstance(data["strokes_per_part"], int)
    assert isinstance(data["grain_flow_min_rating"], int)
    assert isinstance(data["macro_etch_required"], bool)


def assert_mill_heat(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["heat_number"], str) and data["heat_number"]
    assert data["status"] in [
        "RECEIVED", "CERT_VERIFIED", "QUARANTINED", "REJECTED", "DEPLETED",
    ]
    assert isinstance(data["received_weight_lbs"], (int, float))
    assert isinstance(data["remaining_weight_lbs"], (int, float))


def assert_billet(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["CUT", "CHARGED", "DISCHARGED", "CONSUMED", "SCRAPPED"]
    assert isinstance(data["cut_seq"], int) and data["cut_seq"] >= 1
    assert isinstance(data["cut_weight_lbs"], (int, float))


def assert_furnace(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["UP", "DOWN"]
    assert isinstance(data["capacity_lbs"], (int, float))


def assert_furnace_charge(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["LOADING", "SOAKING", "READY", "DISCHARGED", "ABORTED"]
    assert isinstance(data["charge_weight_lbs"], (int, float))
    assert isinstance(data["target_temp_f"], int)
    assert isinstance(data["soak_minutes"], int)


def assert_die_set(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["AVAILABLE", "INSTALLED", "WORN", "RESINKING", "RETIRED"]
    assert isinstance(data["cumulative_hits"], int)
    assert isinstance(data["resink_count"], int)


def assert_work_center(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["UP", "DOWN"]
    assert data["type"] in ["PRESS", "HAMMER"]
    assert isinstance(data["rated_tonnage"], int)


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "RELEASED", "IN_PROGRESS", "PRODUCED", "CERTIFIED", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["required_tonnage"], int) and data["required_tonnage"] >= 1
    for counter in ("forged_qty", "trimmed_qty", "shipped_qty", "scrapped_qty"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["planned_billet_weight_lbs"], (int, float))
    assert isinstance(data["consumed_billet_weight_lbs"], (int, float))


def assert_forge_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "FORGED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["planned_qty"], int)
    assert isinstance(data["parts_good_total"], int)
    assert isinstance(data["parts_scrapped_total"], int)


def assert_forge_heat(data: dict):
    """A recorded forge heat is an immutable event carrying only id + created_at
    among the common fields; both updated_at and version are absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "forge heat must not carry updated_at"
    assert "version" not in data, "forge heat must not carry version"
    assert isinstance(data["parts_good"], int)
    assert isinstance(data["parts_scrapped"], int)
    assert isinstance(data["hits_added"], int)


def assert_trim_ticket(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "ACCEPTED", "FLAGGED", "VOIDED"]
    assert isinstance(data["flash_scrap_lbs"], (int, float))
    assert isinstance(data["flash_yield_pct"], (int, float))


def assert_part_serial(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["FORGED", "TRIMMED", "INSPECTED", "SHIPPED", "SCRAPPED"]
    assert isinstance(data["serial_seq"], int) and data["serial_seq"] >= 1


def assert_quality_cert(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING", "SUBMITTED", "CERTIFIED", "REJECTED"]


def assert_surcharge_index(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["surcharge_cents_per_ton"], int)
    assert isinstance(data["energy_pct"], (int, float))


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PROVISIONAL", "FINAL", "PAID", "VOID"]
    assert isinstance(data["billable_tons"], (int, float))
    for field in (
        "tier_rate_cents_per_ton",
        "base_amount_cents",
        "alloy_surcharge_cents",
        "energy_surcharge_cents",
        "scrap_credit_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_heat_weight_invariant(heat: dict, billets: list):
    """Mass conservation: received == remaining + sum(cut weights over all billets
    ever cut from the heat, any status)."""
    total_cut = sum(b["cut_weight_lbs"] for b in billets)
    assert heat["received_weight_lbs"] == heat["remaining_weight_lbs"] + total_cut, (
        f"heat weight drift: received {heat['received_weight_lbs']} != "
        f"remaining {heat['remaining_weight_lbs']} + cut {total_cut}"
    )
