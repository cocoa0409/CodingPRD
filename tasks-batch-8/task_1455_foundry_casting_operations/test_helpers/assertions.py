"""Entity assertions and domain invariant checkers (PRD §2.5, §2.8)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ClaimStatus,
    ClaimType,
    CreditVariant,
    DefectType,
    Disposition,
    EquipmentKind,
    FoundryPosture,
    HeatStatus,
    InspectionStatus,
    MoldProcess,
    MoldStatus,
    PatternStatus,
    PourSlotStatus,
    QualityStatus,
    ReturnLotStatus,
    RoutingStatus,
    SandBatchStatus,
    ScrapCode,
    ScrapStatus,
    ShrinkClass,
    OrderStatus,
    Zone,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_foundry(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sand_available_kg"], (int, float))
    assert isinstance(data["alloy_available_kg"], (int, float))
    assert data["posture"] in [p.value for p in FoundryPosture]
    assert isinstance(data["ops_run_index"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["foundry_id"])
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["credit_limit_cents"], int)


def assert_pattern(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["foundry_id"])
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["alloy_shrink_class"] in [s.value for s in ShrinkClass]
    assert data["mold_process"] in [p.value for p in MoldProcess]
    assert isinstance(data["finish_dimensions_mm"], list)
    assert 1 <= len(data["finish_dimensions_mm"]) <= 5
    assert isinstance(data["machining_allowance_mm"], (int, float))
    assert isinstance(data["impressions"], int) and data["impressions"] >= 1
    assert isinstance(data["pattern_dimensions_mm"], list)
    assert len(data["pattern_dimensions_mm"]) == len(data["finish_dimensions_mm"])
    assert isinstance(data["qualification_attempts"], int)
    assert data["status"] in [s.value for s in PatternStatus]


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["foundry_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["pattern_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["machining_allowance_pct"], (int, float))
    assert isinstance(data["warranty_months"], int)
    assert isinstance(data["warranty_budget_cents"], int)
    assert isinstance(data["accepted_count"], int)
    assert isinstance(data["scrapped_count"], int)
    assert isinstance(data["pipeline_count"], int)
    assert isinstance(data["settled_total_cents"], int)
    assert data["status"] in [s.value for s in OrderStatus]


def assert_equipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["foundry_id"])
    assert data["kind"] in [k.value for k in EquipmentKind]
    assert isinstance(data["label"], str) and data["label"]


def assert_heat(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["foundry_id"])
    assert is_valid_uuid(data["furnace_id"])
    assert isinstance(data["alloy_grade"], str) and data["alloy_grade"]
    assert isinstance(data["chemistry_spec"], dict)
    assert isinstance(data["charge_total_kg"], (int, float))
    assert data["status"] in [s.value for s in HeatStatus]


def assert_pour_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["molding_line_id"])
    assert is_valid_uuid(data["heat_id"])
    assert isinstance(data["mold_ids"], list)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in [s.value for s in PourSlotStatus]


def assert_mold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pattern_id"])
    assert is_valid_uuid(data["sand_batch_id"])
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["sand_weight_kg"], (int, float))
    assert isinstance(data["metal_weight_kg"], (int, float))
    assert isinstance(data["cooling_hours"], int)
    assert data["status"] in [s.value for s in MoldStatus]


def assert_casting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["mold_id"])
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["cavity_index"], int) and data["cavity_index"] >= 1
    assert isinstance(data["casting_weight_kg"], (int, float))
    assert data["routing_status"] in [s.value for s in RoutingStatus]
    assert data["quality_status"] in [s.value for s in QualityStatus]


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["casting_id"])
    assert isinstance(data["porosity_grade"], int) and 1 <= data["porosity_grade"] <= 8
    assert data["defect_type"] in [d.value for d in DefectType]
    assert data["zone"] in [z.value for z in Zone]
    assert data["status"] in [s.value for s in InspectionStatus]
    if data["status"] == InspectionStatus.DISPOSITIONED.value:
        assert data["disposition"] in [d.value for d in Disposition]


def assert_scrap_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["casting_id"])
    assert is_valid_uuid(data["return_lot_id"])
    assert data["scrap_code"] in [c.value for c in ScrapCode]
    assert isinstance(data["provisional_weight_kg"], (int, float))
    assert data["status"] in [s.value for s in ScrapStatus]


def assert_return_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["foundry_id"])
    assert isinstance(data["alloy_grade"], str) and data["alloy_grade"]
    for field in ("collected_weight_kg", "scrap_credited_kg", "consumed_weight_kg",
                  "downgraded_weight_kg", "remaining_weight_kg"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["status"] in [s.value for s in ReturnLotStatus]


def assert_sand_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["foundry_id"])
    for field in ("virgin_weight_kg", "current_weight_kg", "committed_weight_kg",
                  "spent_weight_kg", "pending_reclaim_kg", "discarded_weight_kg"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert isinstance(data["max_loi_pct"], (int, float))
    assert data["status"] in [s.value for s in SandBatchStatus]


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["claim_type"] in [t.value for t in ClaimType]
    assert isinstance(data["claim_qty"], int)
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["appeal_used"], bool)
    assert data["status"] in [s.value for s in ClaimStatus]
    if data["status"] == ClaimStatus.SETTLED.value:
        assert data["credit_variant_applied"] in [v.value for v in CreditVariant]
        assert isinstance(data["settled_credit_cents"], int)


def assert_alloy_mass_invariant(lot: dict):
    """PRD §2.8 alloy-mass invariant: collected + scrap_credited ==
    consumed + remaining + downgraded (2 dp tolerance)."""
    lhs = lot["collected_weight_kg"] + lot["scrap_credited_kg"]
    rhs = (
        lot["consumed_weight_kg"]
        + lot["remaining_weight_kg"]
        + lot["downgraded_weight_kg"]
    )
    assert abs(lhs - rhs) < 0.005, (
        f"Alloy mass drift on lot {lot.get('id')}: "
        f"{lot['collected_weight_kg']} + {lot['scrap_credited_kg']} != "
        f"{lot['consumed_weight_kg']} + {lot['remaining_weight_kg']} + "
        f"{lot['downgraded_weight_kg']}"
    )


def assert_sand_mass_invariant(batch: dict):
    """PRD §2.8 sand-mass invariant: virgin == current + committed + spent +
    pending_reclaim + discarded (2 dp tolerance)."""
    rhs = (
        batch["current_weight_kg"]
        + batch["committed_weight_kg"]
        + batch["spent_weight_kg"]
        + batch["pending_reclaim_kg"]
        + batch["discarded_weight_kg"]
    )
    assert abs(batch["virgin_weight_kg"] - rhs) < 0.005, (
        f"Sand mass drift on batch {batch.get('id')}: "
        f"virgin {batch['virgin_weight_kg']} != {rhs}"
    )
