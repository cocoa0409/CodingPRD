"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Shared shape helpers
# --------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """Most resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_immutable_child_fields(data: dict):
    """Immutable rows carry only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "an immutable row must not expose updated_at"
    assert "version" not in data, "an immutable row must not expose version"


def assert_bare_uuid(value: str):
    assert is_valid_uuid(value), f"expected a bare UUID with no type prefix, got {value!r}"
    assert ":" not in value and "_" not in value, (
        f"expected a bare UUID with no type prefix, got {value!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["customer_type"] in ["DISTRIBUTOR", "FLEET", "PRIVATE_LABEL", "INDUSTRIAL"]
    assert data["contract_tier"] in ["TIER_A", "TIER_B", "TIER_C"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["takeback_agreement_status"] in ["NONE", "ACTIVE", "SUSPENDED"]
    assert isinstance(data["takeback_credit_balance_cents"], int)


def assert_component_lot(data: dict):
    assert_common_fields(data)
    assert data["component_type"] in ["BASE_OIL", "VI_IMPROVER", "ADDITIVE_PACKAGE", "DYE"]
    assert isinstance(data["component_code"], str) and len(data["component_code"]) > 0
    assert data["additive_family"] in [
        "NONE", "ZDDP_PCMO", "LOW_SAPS", "HDEO_API_CK4", "GEAR_EP", "FOOD_GRADE_H1",
    ]
    assert data["received_kg"] > 0
    assert data["available_kg"] >= 0
    assert isinstance(data["unit_cost_cents_per_kg"], int) and data["unit_cost_cents_per_kg"] > 0
    assert data["status"] in ["AVAILABLE", "QUARANTINED", "DEPLETED"]
    assert isinstance(data["coa_viscosity_verified"], bool)


def assert_product_spec(data: dict):
    assert_common_fields(data)
    assert isinstance(data["product_code"], str) and len(data["product_code"]) > 0
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ["DRAFT", "ACTIVE", "WITHDRAWN"]
    assert data["target_kv100_cst"] > 0
    assert 0 < data["kv100_tolerance_pct"] <= 25
    assert 0 <= data["min_additive_treat_pct"] <= 100
    assert data["base_stock_group"] in ["GROUP_I", "GROUP_II", "GROUP_III", "GROUP_IV"]
    assert data["additive_family"] in [
        "ZDDP_PCMO", "LOW_SAPS", "HDEO_API_CK4", "GEAR_EP", "FOOD_GRADE_H1",
    ]


def assert_blend_recipe(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["product_spec_id"])
    assert isinstance(data["spec_revision_pinned"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert data["total_mass_basis_kg"] > 0
    assert data["predicted_kv100_cst"] > 0
    assert isinstance(data["component_count"], int) and data["component_count"] >= 1


def assert_recipe_component(data: dict):
    assert_immutable_child_fields(data)
    assert is_valid_uuid(data["blend_recipe_id"])
    assert data["component_type"] in ["BASE_OIL", "VI_IMPROVER", "ADDITIVE_PACKAGE", "DYE"]
    assert 0 < data["mass_fraction_pct"] <= 100
    assert data["nominal_kv100_cst"] > 0


def assert_blend_tank(data: dict):
    assert_common_fields(data)
    assert isinstance(data["tank_code"], str) and len(data["tank_code"]) > 0
    assert data["capacity_l"] > 0
    assert data["status"] in ["AVAILABLE", "CHARGED", "QUARANTINED"]
    assert data["heel_volume_l"] >= 0
    assert data["heel_additive_family"] in [
        "NONE", "ZDDP_PCMO", "LOW_SAPS", "HDEO_API_CK4", "GEAR_EP", "FOOD_GRADE_H1",
    ]


def assert_blend_batch(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["blend_recipe_id"])
    assert isinstance(data["batch_code"], str) and len(data["batch_code"]) > 0
    assert data["planned_volume_l"] > 0
    assert data["production_status"] in [
        "PLANNED", "CHARGING", "BLENDED", "RELEASED", "QUARANTINED", "REWORKED", "DISPOSED",
    ]
    assert data["qc_status"] in ["PENDING", "SAMPLED", "PASSED", "FAILED", "WAIVED"]
    assert isinstance(data["claim_eligible"], bool)
    assert isinstance(data["estimated_component_cost_cents"], int)
    assert isinstance(data["component_cost_cents"], int)
    assert isinstance(data["retain_count"], int) and data["retain_count"] >= 0


def assert_component_draw(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data["blend_batch_id"])
    assert is_valid_uuid(data["component_lot_id"])
    assert data["drawn_kg"] > 0
    assert isinstance(data["unit_cost_cents_per_kg"], int)
    assert data["status"] in ["RESERVED", "CONSUMED", "RETURNED"]


def assert_qc_result(data: dict):
    assert_immutable_child_fields(data)
    assert is_valid_uuid(data["blend_batch_id"])
    assert data["test_type"] in ["KV100", "KV40", "TBN", "FLASH_POINT"]
    assert data["measured_value"] > 0
    assert data["result"] in ["PASS", "FAIL"]
    assert is_iso8601_timestamp(data["tested_at"]), "tested_at must be ISO 8601 UTC"
    assert isinstance(data["technician_user_id"], str) and len(data["technician_user_id"]) > 0


def assert_retain_sample(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["blend_batch_id"])
    assert isinstance(data["retain_code"], str) and len(data["retain_code"]) > 0
    assert data["volume_ml"] >= 100
    assert is_iso8601_timestamp(data["retained_at"]), "retained_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data["retention_until"]), "retention_until must be ISO 8601 UTC"
    assert data["status"] in ["HELD", "DISPOSED"]


def assert_approval_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["product_spec_id"])
    assert data["claim_body"] in ["API", "ILSAC", "OEM_MB", "OEM_VW", "OEM_CAT", "JASO"]
    assert isinstance(data["claim_code"], str) and len(data["claim_code"]) > 0
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["requires_recertification"], bool)


def assert_package_configuration(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["product_spec_id"])
    assert data["package_type"] in [
        "BULK", "IBC_1000L", "DRUM_205L", "PAIL_20L", "CASE_12X1L",
    ]
    assert isinstance(data["label_brand"], str) and len(data["label_brand"]) > 0
    assert data["fill_volume_l"] > 0
    assert isinstance(data["private_label"], bool)
    assert isinstance(data["claim_codes"], list)
    assert data["status"] in [
        "DRAFT", "ACTIVE", "CLAIM_BLOCKED", "SUPERSEDED", "RETIRED",
    ]


def assert_packaging_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["line_code"], str) and len(data["line_code"]) > 0
    assert isinstance(data["max_concurrent_runs"], int) and data["max_concurrent_runs"] >= 1
    assert data["status"] in ["AVAILABLE", "DOWN"]
    assert isinstance(data["scheduled_run_count"], int) and data["scheduled_run_count"] >= 0


def assert_packaging_run(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["blend_batch_id"])
    assert is_valid_uuid(data["package_configuration_id"])
    assert is_valid_uuid(data["packaging_line_id"])
    assert isinstance(data["planned_units"], int) and data["planned_units"] > 0
    assert data["status"] in ["SCHEDULED", "RUNNING", "COMPLETED", "CANCELLED"]


def assert_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["delivery_mode"] in ["BULK_DELIVERY", "PACKAGED"]
    assert isinstance(data["takeback_linked"], bool)
    assert data["status"] in ["DRAFT", "CONFIRMED", "HOLD", "INVOICED", "VOID"]
    for money in (
        "subtotal_cents",
        "freight_surcharge_cents",
        "pre_credit_total_cents",
        "takeback_credit_applied_cents",
        "total_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be whole cents in an integer field"


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["package_configuration_id"])
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["status"] in ["OPEN", "HOLD", "CANCELLED"]


def assert_takeback_collection(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in [
        "SCHEDULED", "COLLECTED", "ASSAYED", "CREDITED", "REJECTED",
    ]
    assert isinstance(data["credit_cents"], int)
    if data.get("credit_variant") is not None:
        assert data["credit_variant"] in ["FLAT_RATE", "ASSAY_ADJUSTED"]


def assert_spec_change_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["product_spec_id"])
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "IN_REVIEW", "CLEARED", "REJECTED", "EFFECTIVE", "WITHDRAWN",
    ]
    assert data["viscosity_review"] in ["PENDING", "CLEARED", "BLOCKED"]
    assert data["approval_review"] in ["PENDING", "CLEARED", "BLOCKED"]
    assert isinstance(data["claims_to_suspend_count"], int)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_mass_conserved(lot: dict, draws: list):
    """available_kg plus the drawn mass of every reserved or consumed draw
    against a lot equals its received_kg."""
    outstanding = sum(
        d["drawn_kg"] for d in draws if d["status"] in ("RESERVED", "CONSUMED")
    )
    assert lot["available_kg"] + outstanding == pytest.approx(lot["received_kg"], abs=0.001), (
        f"mass not conserved on lot {lot['id']}: available_kg {lot['available_kg']} "
        f"+ outstanding {outstanding} != received_kg {lot['received_kg']}"
    )


def assert_credit_ledger_conserved(customer: dict, credited_collections: list, applied_orders: list):
    """granted take-back credit minus applied take-back credit is invariant."""
    granted = sum(c["credit_cents"] for c in credited_collections if c["status"] == "CREDITED")
    applied = sum(
        o["takeback_credit_applied_cents"]
        for o in applied_orders
        if o["status"] in ("CONFIRMED", "HOLD", "INVOICED")
    )
    assert customer["takeback_credit_balance_cents"] == granted - applied, (
        f"credit ledger not conserved: balance "
        f"{customer['takeback_credit_balance_cents']} != granted {granted} - applied {applied}"
    )


def assert_order_money_chain(order: dict):
    """The order's money fields must agree with each other."""
    assert order["pre_credit_total_cents"] == order["subtotal_cents"] + order["freight_surcharge_cents"], (
        "pre_credit_total_cents must equal subtotal_cents plus freight_surcharge_cents"
    )
    assert order["total_cents"] == order["pre_credit_total_cents"] - order["takeback_credit_applied_cents"], (
        "total_cents must equal pre_credit_total_cents minus takeback_credit_applied_cents"
    )
