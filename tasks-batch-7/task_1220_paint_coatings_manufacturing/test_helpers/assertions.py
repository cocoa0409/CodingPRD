"""Entity assertions and domain invariant checkers.

Field-shape assertions follow PRD §2.4: primary resources carry id,
created_at, updated_at and version; formula lines and batch adjustments are
append-only and carry only id and created_at.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_FORMULA_STATUSES = {"DRAFT", "ACTIVE", "DEPRECATED"}
_VOC_RULE_STATUSES = {"DRAFT", "ACTIVE", "RETIRED"}
_MILL_STATUSES = {"ACTIVE", "MAINTENANCE"}
_BATCH_STATUSES = {
    "PLANNED", "MILLING", "TINTING", "QC_PENDING", "QC_APPROVED", "FILLING",
    "FILLED", "CLOSED", "REWORK", "ON_HOLD", "DISPOSAL_PENDING", "DISPOSED",
    "CANCELLED",
}
_ADJUSTMENT_KINDS = {"THINNER", "THICKENER", "TINT_SHOT", "EXEMPT_SOLVENT"}
_MATCH_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
_CONTAINER_STATUSES = {
    "IN_STOCK", "QUARANTINED", "REJECTED", "SHIPPED", "RETURNED",
    "OBSOLETE", "DISPOSAL_PENDING", "DISPOSED",
}
_SIZE_CODES = {"QUART", "GALLON", "FIVE_GALLON"}
_ORDER_STATUSES = {
    "PLACED", "RUSH_REVIEW", "SCHEDULED", "IN_PRODUCTION", "BLOCKED",
    "FULFILLED", "CANCELLED",
}
_CLAIM_STATUSES = {
    "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "SETTLED", "VOIDED",
}
_DISPOSAL_STATUSES = {"REQUESTED", "MANIFESTED", "DISPOSED", "CANCELLED"}
_CATEGORIES = {
    "FLAT", "NONFLAT", "PRIMER", "INDUSTRIAL_MAINTENANCE", "TRAFFIC_MARKING",
}
_FAMILIES = {"LATEX_INTERIOR", "LATEX_EXTERIOR", "ALKYD"}


def _assert_primary(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_append_only(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} is append-only: no updated_at"
    assert "version" not in data, f"{entity} is append-only: no version"


def assert_customer(data: dict):
    _assert_primary(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_state_code"], str)
    assert isinstance(data["annual_credit_cap_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["credit_used_ytd_cents"], int)


def assert_customer_ledger_invariants(data: dict):
    """Credit ledger sanity: balances are non-negative integer cents and the
    year's draw never exceeds the annual cap."""
    assert data["credit_balance_cents"] >= 0
    assert 0 <= data["credit_used_ytd_cents"] <= data["annual_credit_cap_cents"]


def assert_tint_base(data: dict):
    _assert_primary(data, "TintBase")
    assert isinstance(data["base_code"], str) and data["base_code"]
    assert data["product_category"] in _CATEGORIES
    assert data["base_family"] in _FAMILIES
    assert isinstance(data["base_voc_gpl"], (int, float))
    assert 0 <= data["water_fraction_pct"] < 100
    assert isinstance(data["density_kg_per_gal"], (int, float))
    assert isinstance(data["base_cost_per_gal_cents"], int)
    assert isinstance(data["unit_price_per_gal_cents"], int)
    assert isinstance(data["shelf_life_months"], int)
    assert isinstance(data["grind_spec_um"], (int, float))


def assert_colorant(data: dict):
    _assert_primary(data, "Colorant")
    assert isinstance(data["colorant_code"], str) and data["colorant_code"]
    assert isinstance(data["voc_g_per_unit"], (int, float))
    assert isinstance(data["cost_per_shot_cents"], int)
    assert isinstance(data["is_hazmat"], bool)


def assert_formula(data: dict):
    _assert_primary(data, "Formula")
    assert isinstance(data["formula_code"], str) and data["formula_code"]
    assert data["status"] in _FORMULA_STATUSES
    assert isinstance(data["formula_version_no"], int)
    assert isinstance(data["min_batch_gallons"], int)
    assert isinstance(data["is_custom"], bool)
    assert isinstance(data["target_delta_e"], (int, float))


def assert_formula_line(data: dict):
    _assert_append_only(data, "FormulaLine")
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("colorant_id", ""))
    assert data["shots_per_gallon"] > 0
    assert isinstance(data["sequence"], int)


def assert_voc_rule(data: dict):
    _assert_primary(data, "VocRule")
    assert data["category"] in _CATEGORIES
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["max_voc_gpl"], (int, float))
    assert data["status"] in _VOC_RULE_STATUSES


def assert_mill(data: dict):
    _assert_primary(data, "Mill")
    assert isinstance(data["mill_code"], str) and data["mill_code"]
    assert isinstance(data["capacity_gallons"], int)
    assert data["status"] in _MILL_STATUSES
    assert isinstance(data["reserved_minutes"], int)
    assert data["reserved_minutes"] >= 0


def assert_batch(data: dict):
    _assert_primary(data, "Batch")
    assert isinstance(data.get("batch_code"), str) and data["batch_code"]
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("mill_id", ""))
    assert data["status"] in _BATCH_STATUSES
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["dispersion_cycles"], int)
    assert data["dispersion_cycles"] >= 0
    assert isinstance(data["pinned_formula_version_no"], int)
    assert data["product_category"] in _CATEGORIES
    assert data["base_family"] in _FAMILIES


def assert_batch_invariants(data: dict):
    """Batch accounting sanity that must hold at every lifecycle point."""
    assert isinstance(data["theoretical_cost_cents"], int)
    assert data["theoretical_cost_cents"] >= 0
    if data.get("actual_cost_cents") is not None:
        assert isinstance(data["actual_cost_cents"], int)
        assert data["actual_cost_cents"] >= 0
    if data.get("voc_actual_gpl") is not None:
        assert data["voc_actual_gpl"] >= 0


def assert_batch_adjustment(data: dict):
    _assert_append_only(data, "BatchAdjustment")
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["kind"] in _ADJUSTMENT_KINDS
    assert data["quantity"] > 0
    assert isinstance(data["voc_contribution_g"], (int, float))
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 0


def assert_color_match(data: dict):
    _assert_primary(data, "ColorMatch")
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["status"] in _MATCH_STATUSES
    assert isinstance(data["cycle_index"], int)
    assert isinstance(data["measured_delta_e"], (int, float))
    assert isinstance(data["threshold_delta_e"], (int, float))
    assert isinstance(data["measured_by_user_id"], str)


def assert_container(data: dict):
    _assert_primary(data, "Container")
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["size_code"] in _SIZE_CODES
    assert data["status"] in _CONTAINER_STATUSES
    assert isinstance(data["nominal_fill_g"], int)
    assert isinstance(data["actual_fill_g"], int)
    assert data["fill_variance_g"] == data["actual_fill_g"] - data["nominal_fill_g"]
    assert isinstance(data["net_weight_kg"], (int, float))
    assert isinstance(data["freeze_exposure_count"], int)
    assert data["freeze_exposure_count"] >= 0


def assert_order(data: dict):
    _assert_primary(data, "SalesOrder")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in _ORDER_STATUSES
    assert isinstance(data["rush_flag"], bool)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["setup_fee_cents"], int)
    assert isinstance(data["rush_fee_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_order_invariants(data: dict):
    """Pricing identity: total is always subtotal + setup + rush fee."""
    assert (
        data["total_cents"]
        == data["subtotal_cents"] + data["setup_fee_cents"] + data["rush_fee_cents"]
    ), "total_cents must equal subtotal + setup fee + rush fee"


def assert_credit_claim(data: dict):
    _assert_primary(data, "CreditClaim")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("container_id", ""))
    assert data["claim_type"] in {"FREEZE_DAMAGE", "SHELF_LIFE_EXPIRY"}
    assert data["status"] in _CLAIM_STATUSES
    assert data["invoice_value_cents"] > 0
    assert isinstance(data["provisional_credit_cents"], int)
    assert isinstance(data["remaining_days_at_claim"], int)


def assert_disposal_request(data: dict):
    _assert_primary(data, "DisposalRequest")
    assert data["reason"] in {
        "OBSOLETE_STOCK", "RETURNED_GOODS", "BATCH_REJECT", "DAMAGED_STOCK",
    }
    assert data["status"] in _DISPOSAL_STATUSES
    assert data["hazmat_class"] in {"HAZARDOUS", "NON_HAZARDOUS"}
    assert isinstance(data["expected_destroyed_kg"], (int, float))
    assert data["expected_destroyed_kg"] >= 0


def assert_disposal_cost_invariants(data: dict):
    """Disposal pricing identity once the request has been priced."""
    if data.get("gross_cost_cents") is not None:
        assert isinstance(data["gross_cost_cents"], int)
        assert isinstance(data["recovery_credit_cents"], int)
        assert data["net_cost_cents"] == (
            data["gross_cost_cents"] - data["recovery_credit_cents"]
        )
        assert data["recovery_credit_cents"] >= 0
