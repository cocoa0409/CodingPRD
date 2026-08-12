"""Entity assertions and domain invariant checkers.

Each ``assert_*`` function validates the shape of one entity response against
the fields the PRD promises.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert isinstance(data, dict), "entity payload must be a JSON object"
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_variety(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["variety_code"], str) and data["variety_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["substrate_recipe"] in ("PHASE_II_COMPOST", "STRAW_SAWDUST")
    assert isinstance(data["target_bioefficiency_pct"], (int, float))
    assert isinstance(data["shelf_life_days"], int)
    assert isinstance(data["spawn_run_days"], int)
    assert isinstance(data["casing_days"], int)
    assert isinstance(data["max_flushes"], int) and data["max_flushes"] >= 1
    assert isinstance(data["flush_yield_distribution"], list)
    assert len(data["flush_yield_distribution"]) == data["max_flushes"]
    assert isinstance(data["active_committed_kg"], (int, float))
    assert isinstance(data["planned_production_kg"], (int, float))


def assert_buyer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["lifetime_shortfall_penalty_cents"], int)


def assert_buyer_commitment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("buyer_id", ""))
    assert isinstance(data["reference"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "CANCELLED")
    assert isinstance(data["total_committed_kg"], (int, float))
    assert isinstance(data["total_delivered_kg"], (int, float))
    assert isinstance(data["total_shortfall_penalty_cents"], int)


def assert_commitment_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("commitment_id", ""))
    assert is_valid_uuid(data.get("variety_id", ""))
    assert isinstance(data["committed_kg"], (int, float)) and data["committed_kg"] > 0
    assert isinstance(data["week_start"], str)
    assert isinstance(data["week_end"], str)
    assert data["min_grade"] in ("A", "B")
    assert isinstance(data["delivered_kg"], (int, float))
    assert isinstance(data["allocated_kg"], (int, float))
    assert data["status"] in ("DRAFT", "ACTIVE", "SETTLED", "CANCELLED")
    assert data["settlement_outcome"] in (None, "FULFILLED", "SHORTFALL")
    assert isinstance(data["shortfall_kg"], (int, float))
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["supply_at_risk"], bool)


def assert_substrate_batch(data: dict):
    _assert_common_fields(data)
    assert data["recipe"] in ("PHASE_II_COMPOST", "STRAW_SAWDUST")
    assert isinstance(data["tonnage"], (int, float)) and data["tonnage"] > 0
    assert data.get("variety_id") is None or is_valid_uuid(data["variety_id"])
    assert data.get("spawn_kg") is None or isinstance(data["spawn_kg"], (int, float))
    assert isinstance(data["remaining_tonnage"], (int, float))
    assert data["status"] in ("MIXED", "PASTEURIZING", "CONDITIONED", "SPAWNED", "EXHAUSTED", "RETIRED")
    assert isinstance(data["spent_revenue_cents"], int)
    assert isinstance(data["disposal_cost_cents"], int)


def assert_tunnel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tunnel_code"], str) and data["tunnel_code"]
    assert isinstance(data["capacity_tonnes"], (int, float)) and data["capacity_tonnes"] > 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_pasteurization_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    assert is_valid_uuid(data.get("tunnel_id", ""))
    assert isinstance(data["planned_start"], str)
    assert isinstance(data["planned_end"], str)
    assert data.get("actual_start") is None or isinstance(data["actual_start"], str)
    assert data.get("hours_at_target_temp") is None or isinstance(data["hours_at_target_temp"], (int, float))
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "FAILED", "ABORTED")


def assert_growing_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert isinstance(data["capacity_tonnes"], (int, float)) and data["capacity_tonnes"] > 0
    assert data["occupancy_status"] in ("IDLE", "OCCUPIED", "TURNAROUND")
    assert data["health_status"] in ("CLEAR", "WATCH", "QUARANTINED")


def assert_room_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("room_id", ""))
    assert is_valid_uuid(data.get("batch_id", ""))
    assert is_valid_uuid(data.get("variety_id", ""))
    assert isinstance(data["allocated_tonnage"], (int, float)) and data["allocated_tonnage"] > 0
    assert isinstance(data["planned_start"], str)
    assert isinstance(data["planned_end"], str)
    assert data.get("placed_at") is None or isinstance(data["placed_at"], str)
    assert data.get("phase_entered_at") is None or isinstance(data["phase_entered_at"], str)
    assert data["status"] in (
        "SCHEDULED", "SPAWN_RUN", "CASING", "FRUITING", "TURNAROUND",
        "CLOSED", "CANCELLED", "ABORTED",
    )
    assert isinstance(data["flush_count"], int)
    assert isinstance(data["harvested_kg"], (int, float))
    assert isinstance(data["scheduled_projection_kg"], (int, float))
    assert isinstance(data["actualized_projection_kg"], (int, float))


def assert_flush(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("room_cycle_id", ""))
    assert isinstance(data["flush_number"], int) and data["flush_number"] >= 1
    assert isinstance(data["recorded_at"], str)
    assert isinstance(data["total_kg"], (int, float)) and data["total_kg"] > 0
    assert data.get("grade_a_kg") is None or isinstance(data["grade_a_kg"], (int, float))
    assert data.get("grade_b_kg") is None or isinstance(data["grade_b_kg"], (int, float))
    assert data.get("cull_kg") is None or isinstance(data["cull_kg"], (int, float))
    assert data.get("graded_at") is None or isinstance(data["graded_at"], str)
    assert data["status"] in ("RECORDED", "GRADED", "SETTLED")


def assert_piece(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("flush_id", ""))
    assert is_valid_uuid(data.get("worker_id", ""))
    assert isinstance(data["logged_by_user_id"], str) and data["logged_by_user_id"]
    assert isinstance(data["kg_picked"], (int, float)) and data["kg_picked"] > 0
    assert isinstance(data["rate_cents_per_kg"], int) and data["rate_cents_per_kg"] > 0
    assert isinstance(data["provisional_pay_cents"], int)
    assert data.get("final_pay_cents") is None or isinstance(data["final_pay_cents"], int)
    assert data["status"] in ("LOGGED", "APPROVED", "DISPUTED", "PAID")


def assert_worker(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert isinstance(data["piece_rate_cents_per_kg"], int) and data["piece_rate_cents_per_kg"] > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["accrued_unpaid_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)


def assert_contamination_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("room_id", ""))
    assert data.get("room_cycle_id") is None or is_valid_uuid(data["room_cycle_id"])
    assert data["pathogen"] in ("TRICHODERMA", "COBWEB", "BACTERIAL_BLOTCH", "VIRUS")
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    assert isinstance(data["affected_zone_pct"], (int, float))
    assert data["status"] in ("REPORTED", "CONFIRMED", "REMEDIATING", "CLEARED", "DISMISSED")


def assert_packaged_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("flush_id", ""))
    assert is_valid_uuid(data.get("variety_id", ""))
    assert data["grade"] in ("A", "B")
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["kg_per_unit"], (int, float)) and data["kg_per_unit"] > 0
    assert isinstance(data["lot_kg"], (int, float))
    assert isinstance(data["packed_at"], str)
    assert isinstance(data["expires_at"], str)
    assert data.get("allocated_line_id") is None or is_valid_uuid(data["allocated_line_id"])
    assert data["status"] in ("IN_STOCK", "ALLOCATED", "SHIPPED", "EXPIRED")


def assert_spent_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("room_cycle_id", ""))
    assert is_valid_uuid(data.get("batch_id", ""))
    assert isinstance(data["tonnage"], (int, float))
    assert isinstance(data["disposal_only"], bool)
    assert data.get("reserved_buyer_id") is None or is_valid_uuid(data["reserved_buyer_id"])
    assert data.get("sale_price_cents") is None or isinstance(data["sale_price_cents"], int)
    assert data.get("disposal_cost_cents") is None or isinstance(data["disposal_cost_cents"], int)
    assert data["status"] in ("AVAILABLE", "RESERVED", "SOLD", "DISPOSED")
