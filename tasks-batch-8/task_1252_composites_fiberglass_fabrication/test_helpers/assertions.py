"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_emission_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["permit_code"], str) and data["permit_code"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["styrene_quota_kg"] > 0
    assert isinstance(data["styrene_used_kg"], (int, float))
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "CLOSED")


def assert_mold(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["mold_code"], str) and data["mold_code"]
    assert data["tooling_phase"] in ("PROTOTYPE", "TRANSITION", "PRODUCTION")
    assert data["maintenance_interval_cycles"] >= 1
    assert data["cycles_since_maintenance"] >= 0
    assert data["prototype_parts_required"] >= 0
    assert data["prototype_parts_validated"] >= 0
    assert data["status"] in (
        "ACTIVE",
        "MAINTENANCE_DUE",
        "IN_MAINTENANCE",
        "RETIRED",
    )


def assert_ply_book(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["revision"], str) and data["revision"]
    assert data["part_area_m2"] > 0
    assert isinstance(data["plies"], list) and len(data["plies"]) >= 1
    for ply in data["plies"]:
        assert isinstance(ply["seq"], int)
        assert isinstance(ply["material_code"], str)
        assert ply["areal_weight_g_m2"] > 0
    assert data["resin_system"] in ("POLYESTER", "VINYL_ESTER", "EPOXY")
    assert 0 < data["target_fiber_volume_pct"] < 1
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED")


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_no"], str) and data["work_order_no"]
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert is_valid_uuid(data["mold_id"])
    assert is_valid_uuid(data["ply_book_id"])
    assert isinstance(data["pinned_ply_book_version"], int)
    assert data["quantity"] >= 1
    assert data["target_part_weight_g"] > 0
    assert data["repair_count"] >= 0
    assert data["status"] in (
        "RELEASED",
        "LAYUP_IN_PROGRESS",
        "AWAITING_CURE",
        "CURE_SCHEDULED",
        "IN_CURE",
        "CURED",
        "IN_INSPECTION",
        "REPAIR",
        "ACCEPTED",
        "SCRAPPED",
    )


def assert_resin_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["batch_code"], str) and data["batch_code"]
    assert data["resin_system"] in ("POLYESTER", "VINYL_ESTER", "EPOXY")
    assert data["resin_mass_g"] > 0
    assert data["catalyst_mass_g"] > 0
    assert is_iso8601_timestamp(data["mixed_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in (
        "MIXED",
        "PARTIALLY_CONSUMED",
        "EXHAUSTED",
        "EXPIRED",
        "QUENCHED",
        "REJECTED",
    )


def assert_layup_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["resin_batch_id"])
    assert data["resin_used_g"] > 0
    assert isinstance(data["styrene_emitted_kg"], (int, float))
    assert is_iso8601_timestamp(data["session_at"])
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_cure_equipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["equipment_code"], str) and data["equipment_code"]
    assert data["kind"] in ("OVEN", "AUTOCLAVE")
    assert data["max_parts_per_cycle"] >= 1
    assert data["turnaround_minutes"] >= 0
    assert data["max_temperature_c"] > 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_cure_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["equipment_id"])
    assert data["ramp_rate_c_per_min"] > 0
    assert data["soak_temp_c"] > 0
    assert data["soak_minutes"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["uses_mold"], bool)
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED")


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["method"] in ("ULTRASONIC", "TAP_TEST", "VISUAL")
    assert data["void_content_pct"] >= 0
    assert data["delamination_area_cm2"] >= 0
    assert data["result"] in ("PASS", "REPAIR_REQUIRED", "FAIL")
    assert is_iso8601_timestamp(data["inspected_at"])


def assert_repair(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["source_inspection_id"])
    assert data["repair_seq"] >= 1
    assert data["status"] in ("OPEN", "CLOSED", "SUPERSEDED")


def assert_resin_mass_invariant(batch: dict):
    """PRD §3.4: total == consumed + remaining + quenched at all times."""
    total = batch["total_mass_g"]
    consumed = batch["consumed_mass_g"]
    remaining = batch["remaining_mass_g"]
    quenched = batch["quenched_mass_g"]
    assert abs(total - (consumed + remaining + quenched)) < 1e-6, (
        f"resin mass not conserved: total {total} != "
        f"consumed {consumed} + remaining {remaining} + quenched {quenched}"
    )
