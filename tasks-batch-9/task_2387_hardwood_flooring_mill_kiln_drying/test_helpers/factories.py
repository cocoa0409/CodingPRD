"""Payload factories — one per write operation, input fields only.

Every factory accepts ``**overrides`` so a test can pin exactly the field it is
exercising and inherit sensible values for the rest.
"""

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def create_species_profile_payload(**overrides) -> dict:
    payload = {
        "species_code": TEST_DEFAULTS["SPECIES_CODE"],
        "common_name": TEST_DEFAULTS["SPECIES_COMMON_NAME"],
        "density_class": "DENSE",
        "tangential_shrinkage_coefficient": TEST_DEFAULTS["SPECIES_COEFFICIENT"],
        "target_moisture_pct": TEST_DEFAULTS["SPECIES_TARGET_MC"],
        "max_moisture_gradient_pp": TEST_DEFAULTS["SPECIES_MAX_GRADIENT"],
    }
    payload.update(overrides)
    return payload


def create_drying_schedule_payload(species_profile_id, expected_species_profile_version=1, **overrides) -> dict:
    payload = {
        "species_profile_id": species_profile_id,
        "schedule_code": TEST_DEFAULTS["SCHEDULE_CODE"],
        "thickness_in": 1.00,
        "initial_moisture_pct": 45.0,
        "final_moisture_pct": 7.0,
        "conditioning_hours": 24,
        "stress_relief_hours": 12,
        "expected_species_profile_version": expected_species_profile_version,
    }
    payload.update(overrides)
    return payload


def create_kiln_chamber_payload(**overrides) -> dict:
    payload = {
        "chamber_code": TEST_DEFAULTS["CHAMBER_CODE"],
        "capacity_board_feet": TEST_DEFAULTS["CHAMBER_CAPACITY_BF"],
    }
    payload.update(overrides)
    return payload


def start_maintenance_payload(**overrides) -> dict:
    payload = {"maintenance_note": "Fan bearing replacement"}
    payload.update(overrides)
    return payload


def create_product_line_payload(species_profile_id, **overrides) -> dict:
    payload = {
        "line_code": TEST_DEFAULTS["PRODUCT_LINE_CODE"],
        "species_profile_id": species_profile_id,
        "construction_type": "SOLID",
        "nominal_width_in": 3.250,
        "nominal_thickness_in": 0.750,
        "material_value_cents_per_sf": TEST_DEFAULTS["MATERIAL_VALUE_CENTS_PER_SF"],
        "warranty_funded_total_cents": TEST_DEFAULTS["WARRANTY_FUNDED_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_core_stock_payload(product_line_id, **overrides) -> dict:
    payload = {
        "product_line_id": product_line_id,
        "core_material": "HDF",
        "lot_reference": "HDF-2026-08",
        "available_square_feet": 20000.00,
    }
    payload.update(overrides)
    return payload


def create_prefinish_line_payload(**overrides) -> dict:
    payload = {
        "line_code": TEST_DEFAULTS["PREFINISH_LINE_CODE"],
        "daily_capacity_linear_feet": TEST_DEFAULTS["PREFINISH_CAPACITY_LF"],
        "coating_passes": TEST_DEFAULTS["COATING_PASSES"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Receiving deck
# ---------------------------------------------------------------------------


def create_green_receipt_payload(species_profile_id, **overrides) -> dict:
    payload = {
        "species_profile_id": species_profile_id,
        "supplier_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "received_board_feet": 6000,
        "receipt_grade": "FAS",
        "moisture_pct_at_receipt": 46.0,
    }
    payload.update(overrides)
    return payload


def accept_receipt_payload(accepted_board_feet=5800, **overrides) -> dict:
    payload = {"accepted_board_feet": accepted_board_feet}
    payload.update(overrides)
    return payload


def reject_receipt_payload(**overrides) -> dict:
    payload = {"rejection_reason": "Excessive sapstain on the outer courses"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Kiln charges
# ---------------------------------------------------------------------------


def create_kiln_charge_payload(drying_schedule_id, kiln_chamber_id, **overrides) -> dict:
    payload = {
        "drying_schedule_id": drying_schedule_id,
        "kiln_chamber_id": kiln_chamber_id,
        "planned_start_utc": TEST_DEFAULTS["CHARGE_START_UTC"],
    }
    payload.update(overrides)
    return payload


def allocate_receipt_payload(green_receipt_id, **overrides) -> dict:
    payload = {"green_receipt_id": green_receipt_id}
    payload.update(overrides)
    return payload


def deallocate_receipt_payload(green_receipt_id, **overrides) -> dict:
    payload = {"green_receipt_id": green_receipt_id}
    payload.update(overrides)
    return payload


def record_stress_test_payload(shell_moisture_pct=6.4, core_moisture_pct=8.2, **overrides) -> dict:
    payload = {
        "shell_moisture_pct": shell_moisture_pct,
        "core_moisture_pct": core_moisture_pct,
    }
    payload.update(overrides)
    return payload


def reschedule_charge_payload(planned_start_utc, **overrides) -> dict:
    payload = {"planned_start_utc": planned_start_utc}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Flooring lots
# ---------------------------------------------------------------------------


def create_flooring_lot_payload(product_line_id, kiln_charge_id, input_dry_bf=6000, **overrides) -> dict:
    payload = {
        "product_line_id": product_line_id,
        "kiln_charge_id": kiln_charge_id,
        "input_dry_bf": input_dry_bf,
    }
    payload.update(overrides)
    return payload


def complete_milling_payload(
    actual_milled_width_in=3.190,
    net_flooring_bf=4680,
    shorts_bf=180,
    sawdust_tons=1.20,
    shavings_tons=0.80,
    **overrides,
) -> dict:
    payload = {
        "actual_milled_width_in": actual_milled_width_in,
        "net_flooring_bf": net_flooring_bf,
        "shorts_bf": shorts_bf,
        "sawdust_tons": sawdust_tons,
        "shavings_tons": shavings_tons,
    }
    payload.update(overrides)
    return payload


def finalize_lot_payload(grade_run_id, **overrides) -> dict:
    payload = {"grade_run_id": grade_run_id}
    payload.update(overrides)
    return payload


def void_lot_payload(**overrides) -> dict:
    payload = {"void_reason": "Moulder setup error, lot withdrawn"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def create_grade_run_payload(flooring_lot_id, expected_lot_version, **overrides) -> dict:
    payload = {
        "flooring_lot_id": flooring_lot_id,
        "inspector_ruleset": "MILL_CHARACTER",
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def create_grade_bundle_payload(grade_class="CLEAR", bundle_board_feet=1187.25, average_length_in=50, **overrides) -> dict:
    payload = {
        "grade_class": grade_class,
        "bundle_board_feet": bundle_board_feet,
        "average_length_in": average_length_in,
    }
    payload.update(overrides)
    return payload


def supersede_grade_run_payload(replacement_grade_run_id, **overrides) -> dict:
    payload = {"replacement_grade_run_id": replacement_grade_run_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Prefinishing
# ---------------------------------------------------------------------------


def create_prefinish_run_payload(
    prefinish_line_id,
    flooring_lot_id,
    window_start_utc="2026-08-20T06:00:00.000Z",
    window_end_utc="2026-08-20T14:00:00.000Z",
    scheduled_linear_feet=5000,
    **overrides,
) -> dict:
    payload = {
        "prefinish_line_id": prefinish_line_id,
        "flooring_lot_id": flooring_lot_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "scheduled_linear_feet": scheduled_linear_feet,
        "sanding_grit_sequence": TEST_DEFAULTS["GRIT_SEQUENCE"],
        "stain_code": "NATURAL",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Byproducts
# ---------------------------------------------------------------------------


def create_byproduct_sale_payload(
    byproduct_batch_id,
    quantity_tons=5.00,
    unit_price_cents_per_ton=2200,
    haul_distance_miles=20,
    **overrides,
) -> dict:
    payload = {
        "byproduct_batch_id": byproduct_batch_id,
        "buyer_name": "Valley Pellet Co",
        "quantity_tons": quantity_tons,
        "unit_price_cents_per_ton": unit_price_cents_per_ton,
        "haul_distance_miles": haul_distance_miles,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------


def create_warranty_claim_payload(
    product_line_id,
    affected_square_feet=240,
    installation_date="2026-03-15",
    subfloor_moisture_pct_at_install=10.5,
    ambient_rh_pct_at_install=62,
    **overrides,
) -> dict:
    payload = {
        "product_line_id": product_line_id,
        "claim_type": "CUPPING",
        "affected_square_feet": affected_square_feet,
        "installation_date": installation_date,
        "subfloor_moisture_pct_at_install": subfloor_moisture_pct_at_install,
        "ambient_rh_pct_at_install": ambient_rh_pct_at_install,
    }
    payload.update(overrides)
    return payload


def request_info_payload(**overrides) -> dict:
    payload = {"info_request_note": "Send subfloor meter readings and photographs"}
    payload.update(overrides)
    return payload


def resubmit_claim_payload(
    affected_square_feet=170,
    subfloor_moisture_pct_at_install=10.5,
    ambient_rh_pct_at_install=62,
    **overrides,
) -> dict:
    payload = {
        "affected_square_feet": affected_square_feet,
        "subfloor_moisture_pct_at_install": subfloor_moisture_pct_at_install,
        "ambient_rh_pct_at_install": ambient_rh_pct_at_install,
    }
    payload.update(overrides)
    return payload


def adjudicate_claim_payload(
    decision="APPROVED",
    adjudicated_affected_sf=210,
    adjudicated_subfloor_moisture_pct=10.5,
    adjudicated_ambient_rh_pct=62,
    **overrides,
) -> dict:
    payload = {
        "decision": decision,
        "adjudicated_affected_sf": adjudicated_affected_sf,
        "adjudicated_subfloor_moisture_pct": adjudicated_subfloor_moisture_pct,
        "adjudicated_ambient_rh_pct": adjudicated_ambient_rh_pct,
    }
    payload.update(overrides)
    return payload


def reverse_claim_payload(**overrides) -> dict:
    payload = {"reversal_reason": "Third-party inspection overturned the finding"}
    payload.update(overrides)
    return payload


def fund_warranty_payload(amount_cents=100000, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def freeze_product_line_payload(**overrides) -> dict:
    payload = {"freeze_reason": "Pending metallurgical review of the moulder heads"}
    payload.update(overrides)
    return payload


__all__ = [
    "create_species_profile_payload",
    "create_drying_schedule_payload",
    "create_kiln_chamber_payload",
    "start_maintenance_payload",
    "create_product_line_payload",
    "create_core_stock_payload",
    "create_prefinish_line_payload",
    "create_green_receipt_payload",
    "accept_receipt_payload",
    "reject_receipt_payload",
    "create_kiln_charge_payload",
    "allocate_receipt_payload",
    "deallocate_receipt_payload",
    "record_stress_test_payload",
    "reschedule_charge_payload",
    "create_flooring_lot_payload",
    "complete_milling_payload",
    "finalize_lot_payload",
    "void_lot_payload",
    "create_grade_run_payload",
    "create_grade_bundle_payload",
    "supersede_grade_run_payload",
    "create_prefinish_run_payload",
    "create_byproduct_sale_payload",
    "create_warranty_claim_payload",
    "request_info_payload",
    "resubmit_claim_payload",
    "adjudicate_claim_payload",
    "reverse_claim_payload",
    "fund_warranty_payload",
    "freeze_product_line_payload",
]
