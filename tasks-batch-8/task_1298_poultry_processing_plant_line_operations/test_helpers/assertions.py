"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_event_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only event must not carry updated_at"
    assert "version" not in data, "append-only event must not carry version"


def assert_processing_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_code"], str) and len(data["line_code"]) > 0
    assert data["line_type"] in ["EVISCERATION", "DEBONING"]
    assert isinstance(data["rated_speed_bpm"], int) and data["rated_speed_bpm"] > 0


def assert_production_shift(data: dict):
    _assert_common(data)
    assert isinstance(data["shift_date"], str) and len(data["shift_date"]) > 0
    assert data["shift_code"] in ["DAY_A", "DAY_B", "NIGHT"]
    assert isinstance(data["shackle_capacity_birds"], int) and data["shackle_capacity_birds"] > 0
    assert data["status"] in ["SCHEDULED", "RUNNING", "SUSPENDED", "CLOSED"]
    assert data["suspend_reason"] in ["NONE", "MANUAL", "WATER_LIMIT_BREACH", "REGULATORY_HOLD"]
    for f in ["shacklers_present", "eviscerators_present", "deboners_present", "qa_techs_present", "birds_processed"]:
        assert isinstance(data[f], int) and data[f] >= 0
    for f in ["process_water_gallons", "chiller_water_gallons", "chilled_weight_lb", "labor_hours_remaining"]:
        assert isinstance(data[f], (int, float))
    assert isinstance(data["water_breach_active"], bool)
    assert isinstance(data["chiller_limit_breached"], bool)


def assert_sanitation_run(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "VERIFIED", "FAILED_RECHECK"]
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))


def assert_preop_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "PASSED", "FAILED", "CORRECTING"]
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0


def assert_line_speed_waiver(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "ACTIVE", "DENIED", "REVOKED", "EXPIRED", "SUPERSEDED"]
    assert is_valid_uuid(data.get("line_id", ""))
    assert isinstance(data["max_speed_bpm"], int) and data["max_speed_bpm"] > 0
    assert isinstance(data["denial_count"], int) and data["denial_count"] >= 0


def assert_flock_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "RECEIVED", "ON_LINE", "CHILLED", "SETTLED", "REOPENED"]
    assert isinstance(data["lot_code"], str) and len(data["lot_code"]) > 0
    assert isinstance(data["booked_head_count"], int) and data["booked_head_count"] > 0
    assert is_valid_uuid(data.get("receiving_shift_id", ""))
    assert isinstance(data["birds_hung_total"], int)
    assert isinstance(data["condemned_accounted"], int)
    assert isinstance(data["carcasses_to_chill"], int)


def assert_line_run(data: dict):
    _assert_common(data)
    assert data["status"] in ["QUEUED", "RUNNING", "PAUSED", "COMPLETED", "RECONCILED", "CANCELLED"]
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("flock_lot_id", ""))
    assert isinstance(data["planned_speed_bpm"], int) and data["planned_speed_bpm"] > 0
    assert isinstance(data["speed_clamped"], bool)
    assert isinstance(data["auto_paused"], bool)


def assert_condemnation_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "CERTIFIED", "DISPUTED"]
    assert data["condemnation_code"] in ["SEPTICEMIA", "AIR_SACCULITIS", "BRUISING", "CONTAMINATION", "MACHINE_DAMAGE"]
    assert isinstance(data["carcass_count"], int) and data["carcass_count"] > 0
    assert isinstance(data["effective_count"], int) and data["effective_count"] > 0
    assert is_valid_uuid(data.get("line_run_id", ""))


def assert_utility_meter_reading(data: dict):
    _assert_event_common(data)
    assert data["meter_type"] in ["PROCESS_WATER", "CHILLER_WATER"]
    assert isinstance(data["gallons"], (int, float)) and data["gallons"] > 0
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_iso8601_timestamp(data.get("recorded_at", ""))


def assert_product_order(data: dict):
    _assert_common(data)
    assert data["product_code"] in ["WINGS", "BREAST_FILLET", "THIGH_MEAT", "TENDERLOIN", "WHOLE_BIRD"]
    assert data["temperature_requirement"] in ["FRESH", "FROZEN", "FLEXIBLE"]
    assert isinstance(data["pounds_ordered"], (int, float)) and data["pounds_ordered"] > 0
    assert data["fulfillment_status"] in ["PENDING", "IN_PRODUCTION", "FULFILLED", "CANCELLED"]
    assert data["allocation_status"] in ["UNALLOCATED", "PARTIALLY_ALLOCATED", "ALLOCATED"]
    assert isinstance(data["filled_lb"], (int, float)) and data["filled_lb"] >= 0


def assert_deboning_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED"]
    for f in ["order_id", "flock_lot_id", "shift_id", "line_id"]:
        assert is_valid_uuid(data.get(f, ""))
    assert isinstance(data["crew_count"], int) and data["crew_count"] > 0
    assert isinstance(data["input_weight_lb"], (int, float)) and data["input_weight_lb"] > 0
    assert isinstance(data["estimated_labor_hours"], (int, float))


def assert_finished_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "TRACE_LOCKED", "SHIPPED", "RECALLED"]
    assert data["routing_status"] in ["UNROUTED", "FRESH", "FROZEN"]
    assert is_valid_uuid(data.get("deboning_batch_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["trace_code"], str) and "/" in data["trace_code"]


def assert_chill_chain_log(data: dict):
    _assert_event_common(data)
    assert data["location"] in ["CHILLER", "BLAST_FREEZER", "COLD_STORAGE", "DOCK"]
    assert isinstance(data["temperature_c"], (int, float))
    assert -40 <= data["temperature_c"] <= 20
    assert is_valid_uuid(data.get("finished_lot_id", ""))
    assert is_iso8601_timestamp(data.get("recorded_at", ""))


def assert_bird_accountability(lot: dict):
    """PRD §3.4 invariant: birds_hung_total == condemned_accounted + carcasses_to_chill."""
    assert lot["birds_hung_total"] == lot["condemned_accounted"] + lot["carcasses_to_chill"], (
        f"bird accountability broken: {lot['birds_hung_total']} != "
        f"{lot['condemned_accounted']} + {lot['carcasses_to_chill']}"
    )


def assert_labor_invariant(shift: dict):
    """PRD §3.6: remaining labor never exceeds the budget and never goes negative."""
    assert 0 <= shift["labor_hours_remaining"] <= shift["labor_hours_budget"], (
        f"labor_hours_remaining {shift['labor_hours_remaining']} outside "
        f"[0, {shift['labor_hours_budget']}]"
    )
