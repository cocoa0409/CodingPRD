"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import FORMULA_DEFAULTS, LINE_DEFAULTS, TIER_DEFAULTS


def create_customer_payload(brand_name="Acme", **overrides) -> dict:
    defaults = {"brand_name": brand_name}
    defaults.update(overrides)
    return defaults


def create_raw_material_payload(name="VitC", allergen_class="NONE", **overrides) -> dict:
    defaults = {"name": name, "allergen_class": allergen_class}
    defaults.update(overrides)
    return defaults


def create_material_lot_payload(
    raw_material_id,
    supplier_name="SuppCo",
    supplier_coa_ref="COA-1",
    qty_received=10000000,
    **overrides,
) -> dict:
    defaults = {
        "raw_material_id": raw_material_id,
        "supplier_name": supplier_name,
        "supplier_coa_ref": supplier_coa_ref,
        "qty_received": qty_received,
    }
    defaults.update(overrides)
    return defaults


def create_identity_test_payload(result="PASS", coa_match=True, **overrides) -> dict:
    defaults = {"result": result, "coa_match": coa_match}
    defaults.update(overrides)
    return defaults


def create_coa_review_payload(review_outcome="APPROVE", **overrides) -> dict:
    defaults = {"review_outcome": review_outcome}
    defaults.update(overrides)
    return defaults


def create_formula_line_payload(
    raw_material_id,
    theoretical_qty_mg_per_unit=LINE_DEFAULTS["theoretical_qty_mg_per_unit"],
    overage_pct=LINE_DEFAULTS["overage_pct"],
    is_label_claim_line=LINE_DEFAULTS["is_label_claim_line"],
    label_claim_mg_per_unit=LINE_DEFAULTS["label_claim_mg_per_unit"],
    **overrides,
) -> dict:
    defaults = {
        "raw_material_id": raw_material_id,
        "theoretical_qty_mg_per_unit": theoretical_qty_mg_per_unit,
        "overage_pct": overage_pct,
        "is_label_claim_line": is_label_claim_line,
        "label_claim_mg_per_unit": label_claim_mg_per_unit,
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(
    name=FORMULA_DEFAULTS["name"],
    dosage_form=FORMULA_DEFAULTS["dosage_form"],
    allergen_class=FORMULA_DEFAULTS["allergen_class"],
    min_order_qty=FORMULA_DEFAULTS["min_order_qty"],
    batch_size_units=FORMULA_DEFAULTS["batch_size_units"],
    shelf_life_months=FORMULA_DEFAULTS["shelf_life_months"],
    overage_basis=FORMULA_DEFAULTS["overage_basis"],
    lines=None,
    price_tiers=None,
    **overrides,
) -> dict:
    defaults = {
        "name": name,
        "dosage_form": dosage_form,
        "allergen_class": allergen_class,
        "min_order_qty": min_order_qty,
        "batch_size_units": batch_size_units,
        "shelf_life_months": shelf_life_months,
        "overage_basis": overage_basis,
        "lines": lines if lines is not None else [],
        "price_tiers": (
            price_tiers
            if price_tiers is not None
            else [dict(t) for t in TIER_DEFAULTS]
        ),
    }
    defaults.update(overrides)
    return defaults


def create_manufacturing_order_payload(
    customer_id, formula_id, ordered_qty=10000, **overrides
) -> dict:
    defaults = {
        "customer_id": customer_id,
        "formula_id": formula_id,
        "ordered_qty": ordered_qty,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(
    production_line_id,
    planned_start="2026-09-01T08:00:00Z",
    planned_end="2026-09-01T16:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "production_line_id": production_line_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
    }
    defaults.update(overrides)
    return defaults


def create_consumption_payload(material_lot_id, qty_consumed=5500000, **overrides) -> dict:
    defaults = {"material_lot_id": material_lot_id, "qty_consumed": qty_consumed}
    defaults.update(overrides)
    return defaults


def create_completion_payload(
    actual_yield_units=9800, actual_bulk_mass_g=5390, **overrides
) -> dict:
    defaults = {
        "actual_yield_units": actual_yield_units,
        "actual_bulk_mass_g": actual_bulk_mass_g,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(
    actual_yield_units, actual_bulk_mass_g, expected_batch_version, **overrides
) -> dict:
    defaults = {
        "actual_yield_units": actual_yield_units,
        "actual_bulk_mass_g": actual_bulk_mass_g,
        "expected_batch_version": expected_batch_version,
    }
    defaults.update(overrides)
    return defaults


def create_assay_payload(assayed_mg_per_unit=470, **overrides) -> dict:
    defaults = {"assayed_mg_per_unit": assayed_mg_per_unit}
    defaults.update(overrides)
    return defaults


def create_assay_review_payload(review_outcome="ACCEPT", **overrides) -> dict:
    defaults = {"review_outcome": review_outcome}
    defaults.update(overrides)
    return defaults


def create_stability_study_payload(chamber_id, protocol="REAL_TIME", **overrides) -> dict:
    defaults = {"chamber_id": chamber_id, "protocol": protocol}
    defaults.update(overrides)
    return defaults


def create_study_completion_payload(pull_results=None, **overrides) -> dict:
    defaults = {
        "pull_results": (
            pull_results if pull_results is not None else [{"pull_month": 3, "passed": True}]
        )
    }
    defaults.update(overrides)
    return defaults


def create_stability_chamber_payload(name="CH1", capacity_units=50000, **overrides) -> dict:
    defaults = {"name": name, "capacity_units": capacity_units}
    defaults.update(overrides)
    return defaults


def create_production_line_payload(name="L1", **overrides) -> dict:
    defaults = {"name": name}
    defaults.update(overrides)
    return defaults


def create_cleaning_validation_payload(notes=None, **overrides) -> dict:
    defaults = {}
    if notes is not None:
        defaults["notes"] = notes
    defaults.update(overrides)
    return defaults


def create_swab_payload(result="PASS", **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_recall_payload(
    scope_type, scope_id, reason="supplier contamination", **overrides
) -> dict:
    defaults = {"scope_type": scope_type, "scope_id": scope_id, "reason": reason}
    defaults.update(overrides)
    return defaults
