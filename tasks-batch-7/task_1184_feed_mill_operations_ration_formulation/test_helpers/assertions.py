"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    CustomerStatus, EmployeeCapability, HazardClass, IngredientStatus,
    ContractStatus, BinStatus, FormulaStatus, OrderStatus, ProductionLineStatus,
    LineContamination, BatchStatus, WeighmentSource, WeighmentStatus,
    FlushRecordStatus, SampleType, SampleResult, CargoClassCapability,
    TripStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert data.get("medicated_permit_ref") is None or isinstance(data["medicated_permit_ref"], str)
    assert isinstance(data["credit_used_cents"], int) and data["credit_used_cents"] >= 0
    assert data["status"] in {s.value for s in CustomerStatus}


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["capability"] in {c.value for c in EmployeeCapability}


def assert_ingredient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["hazard_class"] in {h.value for h in HazardClass}
    assert isinstance(data["is_flush_material"], bool)
    for field in ("crude_protein_pct", "crude_fiber_pct", "metabolizable_energy_kcal_kg"):
        assert data[field] >= 0, f"{field} must be >= 0"
    assert data["status"] in {s.value for s in IngredientStatus}


def assert_price_tick(data: dict):
    """PriceTick is append-only (PRD §2.4): id + created_at only, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PriceTick must not carry updated_at"
    assert "version" not in data, "PriceTick must not carry version"
    assert isinstance(data["price_cents_per_ton"], int) and data["price_cents_per_ton"] > 0
    assert isinstance(data["ingredient_id"], str) and data["ingredient_id"]
    assert isinstance(data["effective_from"], str) and data["effective_from"]


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in ContractStatus}
    assert isinstance(data["fixed_price_cents_per_ton"], int) and data["fixed_price_cents_per_ton"] > 0
    assert data["total_tons"] > 0
    assert abs(data["remaining_tons"] - (data["total_tons"] - data["consumed_tons"])) < 1e-6, (
        "remaining_tons must equal total_tons - consumed_tons (PRD §3.2)"
    )


def assert_bin(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["capacity_tons"] > 0
    assert data.get("ingredient_id") is None or isinstance(data["ingredient_id"], str)
    assert data["status"] in {s.value for s in BinStatus}
    # PRD §3.3: EMPTY exactly when on_hand_tons is zero, READY otherwise (BLOCKED only by cascade).
    if data["status"] == BinStatus.EMPTY.value:
        assert data["on_hand_tons"] == 0, "EMPTY bin must read on_hand_tons == 0"
    if data["status"] == BinStatus.READY.value:
        assert data["on_hand_tons"] > 0, "READY bin must read on_hand_tons > 0"


def assert_formula(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in {s.value for s in FormulaStatus}
    assert isinstance(data["lines"], list)
    assert isinstance(data["meets_constraints"], bool)
    for line in data["lines"]:
        assert isinstance(line["ingredient_id"], str) and line["ingredient_id"]
        assert line["inclusion_pct"] > 0


def assert_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in OrderStatus}
    assert data["tons"] > 0
    assert isinstance(data["is_medicated"], bool)
    assert isinstance(data["quote_stale"], bool)
    assert isinstance(data["blocked"], bool)
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["quoted_formula_version"], int)
    assert isinstance(data["quoted_cost_basis_cents"], int)


def assert_production_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in {s.value for s in ProductionLineStatus}
    assert data["contamination"] in {c.value for c in LineContamination}


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in BatchStatus}
    assert data["target_tons"] > 0
    assert isinstance(data["is_medicated"], bool)
    assert isinstance(data["order_id"], str) and isinstance(data["line_id"], str)


def assert_weighment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in WeighmentStatus}
    assert data["actual_tons"] > 0
    assert data["source"] in {s.value for s in WeighmentSource}
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["line_cost_cents"], int)
    if data["source"] == WeighmentSource.CONTRACT.value:
        assert isinstance(data["contract_id"], str) and data["contract_id"], (
            "CONTRACT weighment must carry contract_id"
        )
    else:
        assert data.get("contract_id") is None, "SPOT weighment must carry contract_id null"


def assert_flush_record(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in FlushRecordStatus}
    assert data["quantity_tons"] >= 0.5, "quantity_tons must be >= 0.5 (PRD §3.7)"
    assert isinstance(data["recorded_by_employee_id"], str) and data["recorded_by_employee_id"]


def assert_quality_sample(data: dict):
    _assert_common_fields(data)
    assert data["sample_type"] in {s.value for s in SampleType}
    assert data["result"] in {r.value for r in SampleResult}
    assert isinstance(data["batch_id"], str) and data["batch_id"]


def assert_truck(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plate_no"], str) and data["plate_no"]
    assert data["cargo_class_capability"] in {c.value for c in CargoClassCapability}
    assert isinstance(data["compartments"], list) and 1 <= len(data["compartments"]) <= 8
    assert data["status"] in {"AVAILABLE", "RETIRED"}


def assert_delivery_trip(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in TripStatus}
    assert isinstance(data["compartment_allocations"], list) and data["compartment_allocations"]
    expected_total = sum(a["tons"] for a in data["compartment_allocations"])
    assert abs(data["total_tons"] - expected_total) < 1e-6, (
        "total_tons must equal the sum of compartment allocation tons (PRD §3.9)"
    )
