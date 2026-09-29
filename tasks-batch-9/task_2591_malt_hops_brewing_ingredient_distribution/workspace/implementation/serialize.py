"""Entity -> JSON projections.

Purely derived fields are recomputed at read time (never bumping a version) so
that clock movement and downstream state changes are always reflected.
"""

from calc import (
    contract_remaining,
    contract_shortfall,
    contracts_of_program,
    malt_lot_available,
    malt_lot_committed,
    recompute_brewer,
    zone_occupied,
)
from db import dt_out
from util import D, num


def _common(ent, out):
    out["created_at"] = dt_out(ent, "created_at")
    out["updated_at"] = dt_out(ent, "updated_at")
    out["version"] = ent["version"]
    return out


def brewer_out(brewer):
    recompute_brewer(brewer, bump=False)
    return _common(
        brewer,
        {
            "id": brewer["id"],
            "name": brewer["name"],
            "brewery_license_no": brewer["brewery_license_no"],
            "credit_terms_days": brewer["credit_terms_days"],
            "credit_limit_cents": brewer["credit_limit_cents"],
            "cold_chain_certified": brewer["cold_chain_certified"],
            "legacy_trailing_lbs": num(brewer["legacy_trailing_lbs"]),
            "ar_balance_cents": brewer["ar_balance_cents"],
            "open_order_exposure_cents": brewer["open_order_exposure_cents"],
            "credit_exposure_cents": brewer["credit_exposure_cents"],
            "credit_utilization_pct": num(brewer["credit_utilization_pct"]),
            "credit_status": brewer["credit_status"],
            "trailing_12mo_volume_lbs": num(brewer["trailing_12mo_volume_lbs"]),
            "freight_program_tier": brewer["freight_program_tier"],
        },
    )


def program_out(program):
    total = D(0)
    for contract in contracts_of_program(program["id"]):
        if contract["status"] in ("ACTIVE", "SHORTFALL_ADJUSTED", "CARRY_FORWARD_PENDING"):
            total += D(contract["contracted_lbs"])
    program["total_contracted_lbs"] = total
    return _common(
        program,
        {
            "id": program["id"],
            "crop_year": program["crop_year"],
            "contract_open_date": dt_out(program, "contract_open_date"),
            "harvest_report_due_date": dt_out(program, "harvest_report_due_date"),
            "status": program["status"],
            "harvest_yield_pct": num(program["harvest_yield_pct"]),
            "total_contracted_lbs": num(total),
            "allocatable_pool_lbs": num(program["allocatable_pool_lbs"]),
            "unallocated_pool_lbs": num(program["unallocated_pool_lbs"]),
            "harvest_reported_at": dt_out(program, "harvest_reported_at"),
        },
    )


def variety_out(variety):
    return _common(
        variety,
        {
            "id": variety["id"],
            "variety_code": variety["variety_code"],
            "name": variety["name"],
            "substitution_group": variety["substitution_group"],
            "alpha_acid_target_pct": num(variety["alpha_acid_target_pct"]),
            "cold_storage_required": variety["cold_storage_required"],
            "pallet_quantity_lbs": num(variety["pallet_quantity_lbs"]),
            "min_order_lbs": num(variety["min_order_lbs"]),
            "spot_price_cents_per_lb": num(variety["spot_price_cents_per_lb"]),
            "available_spot_lbs": num(variety["available_spot_lbs"]),
        },
    )


def contract_out(contract):
    remaining = contract_remaining(contract)
    shortfall = contract_shortfall(contract)
    contract["remaining_lbs"] = remaining
    contract["shortfall_lbs"] = shortfall
    return _common(
        contract,
        {
            "id": contract["id"],
            "brewer_id": contract["brewer_id"],
            "variety_id": contract["variety_id"],
            "crop_year_program_id": contract["crop_year_program_id"],
            "contract_type": contract["contract_type"],
            "contracted_lbs": num(contract["contracted_lbs"]),
            "price_per_lb_cents": num(contract["price_per_lb_cents"]),
            "delivery_window_start": dt_out(contract, "delivery_window_start"),
            "delivery_window_end": dt_out(contract, "delivery_window_end"),
            "carried_forward_from_contract_id": contract["carried_forward_from_contract_id"],
            "carry_forward_target_program_id": contract["carry_forward_target_program_id"],
            "allocated_lbs": num(contract["allocated_lbs"]),
            "committed_lbs": num(contract["committed_lbs"]),
            "carried_forward_out_lbs": num(contract["carried_forward_out_lbs"]),
            "defaulted_lbs": num(contract["defaulted_lbs"]),
            "resold_lbs": num(contract["resold_lbs"]),
            "remaining_lbs": num(remaining),
            "shortfall_lbs": num(shortfall),
            "substitution_covered_lbs": num(contract["substitution_covered_lbs"]),
            "settlement_variant": contract["settlement_variant"],
            "settlement_damages_cents": contract["settlement_damages_cents"],
            "settlement_admin_fee_cents": contract["settlement_admin_fee_cents"],
            "settlement_total_cents": contract["settlement_total_cents"],
            "resale_credit_cents": contract["resale_credit_cents"],
            "defaulted_by_user_id": contract["defaulted_by_user_id"],
            "carry_forward_requested_lbs": num(contract["carry_forward_requested_lbs"]),
            "carry_forward_fee_cents": contract["carry_forward_fee_cents"],
            "status": contract["status"],
        },
    )


def offer_out(offer):
    return _common(
        offer,
        {
            "id": offer["id"],
            "hop_contract_id": offer["hop_contract_id"],
            "substitute_variety_id": offer["substitute_variety_id"],
            "created_contract_id": offer["created_contract_id"],
            "offered_lbs": num(offer["offered_lbs"]),
            "offered_price_cents_per_lb": num(offer["offered_price_cents_per_lb"]),
            "alpha_acid_delta_pct": num(offer["alpha_acid_delta_pct"]),
            "selection_mode": offer["selection_mode"],
            "responded_at": dt_out(offer, "responded_at"),
            "status": offer["status"],
        },
    )


def malt_product_out(product):
    return _common(
        product,
        {
            "id": product["id"],
            "sku": product["sku"],
            "name": product["name"],
            "malt_class": product["malt_class"],
            "pallet_quantity_lbs": num(product["pallet_quantity_lbs"]),
            "min_order_lbs": num(product["min_order_lbs"]),
            "list_price_cents_per_lb": num(product["list_price_cents_per_lb"]),
            "max_moisture_pct": num(product["max_moisture_pct"]),
            "min_diastatic_power": num(product["min_diastatic_power"]),
            "cold_storage_required": product["cold_storage_required"],
        },
    )


def malt_lot_out(lot):
    committed = malt_lot_committed(lot)
    available = malt_lot_available(lot)
    lot["committed_lbs"] = committed
    lot["available_lbs"] = available
    return _common(
        lot,
        {
            "id": lot["id"],
            "malt_product_id": lot["malt_product_id"],
            "lot_code": lot["lot_code"],
            "quantity_lbs": num(lot["quantity_lbs"]),
            "received_at": dt_out(lot, "received_at"),
            "committed_lbs": num(committed),
            "available_lbs": num(available),
            "color_lovibond": num(lot["color_lovibond"]),
            "extract_pct": num(lot["extract_pct"]),
            "moisture_pct": num(lot["moisture_pct"]),
            "protein_pct": num(lot["protein_pct"]),
            "diastatic_power": num(lot["diastatic_power"]),
            "analysis_count": lot["analysis_count"],
            "analyzed_by_user_id": lot["analyzed_by_user_id"],
            "released_by_user_id": lot["released_by_user_id"],
            "quarantine_reason": lot["quarantine_reason"],
            "status": lot["status"],
        },
    )


def strain_out(strain):
    return _common(
        strain,
        {
            "id": strain["id"],
            "strain_code": strain["strain_code"],
            "name": strain["name"],
            "fermentation_type": strain["fermentation_type"],
            "propagation_lead_time_days": strain["propagation_lead_time_days"],
            "viability_pct_at_ship": num(strain["viability_pct_at_ship"]),
            "cells_per_ml_slurry_billion": num(strain["cells_per_ml_slurry_billion"]),
            "min_batch_l": num(strain["min_batch_l"]),
            "vessel_max_l": num(strain["vessel_max_l"]),
            "cold_storage_required": strain["cold_storage_required"],
            "list_price_cents_per_l": num(strain["list_price_cents_per_l"]),
        },
    )


def recipe_out(recipe):
    return _common(
        recipe,
        {
            "id": recipe["id"],
            "brewer_id": recipe["brewer_id"],
            "malt_product_id": recipe["malt_product_id"],
            "yeast_strain_id": recipe["yeast_strain_id"],
            "name": recipe["name"],
            "batch_volume_bbl": num(recipe["batch_volume_bbl"]),
            "original_gravity_plato": num(recipe["original_gravity_plato"]),
            "adjunct_pct": num(recipe["adjunct_pct"]),
            "target_color_lovibond": num(recipe["target_color_lovibond"]),
            "target_extract_pct": num(recipe["target_extract_pct"]),
            "target_protein_pct": num(recipe["target_protein_pct"]),
            "requested_pitch_rate_million_cells_per_ml_per_plato": num(
                recipe["requested_pitch_rate_million_cells_per_ml_per_plato"]
            ),
        },
    )


def job_out(job):
    return _common(
        job,
        {
            "id": job["id"],
            "brewer_id": job["brewer_id"],
            "recipe_id": job["recipe_id"],
            "yeast_strain_id": job["yeast_strain_id"],
            "pitch_date": dt_out(job, "pitch_date"),
            "replaces_job_id": job["replaces_job_id"],
            "recommended_pitch_rate_million_cells_per_ml_per_plato": num(
                job["recommended_pitch_rate_million_cells_per_ml_per_plato"]
            ),
            "required_cells_billion": num(job["required_cells_billion"]),
            "recommended_slurry_l": num(job["recommended_slurry_l"]),
            "propagation_volume_l": num(job["propagation_volume_l"]),
            "pitch_rate_advice": job["pitch_rate_advice"],
            "ready_at": dt_out(job, "ready_at"),
            "failure_reason": job["failure_reason"],
            "status": job["status"],
        },
    )


def order_out(order):
    return _common(
        order,
        {
            "id": order["id"],
            "brewer_id": order["brewer_id"],
            "requested_ship_date": dt_out(order, "requested_ship_date"),
            "purchase_order_ref": order["purchase_order_ref"],
            "fulfillment_status": order["fulfillment_status"],
            "credit_status": order["credit_status"],
            "subtotal_cents": order["subtotal_cents"],
            "volume_discount_cents": order["volume_discount_cents"],
            "chargeable_lbs": num(order["chargeable_lbs"]),
            "freight_cents": order["freight_cents"],
            "pallet_break_fee_cents": order["pallet_break_fee_cents"],
            "small_order_surcharge_cents": order["small_order_surcharge_cents"],
            "total_cents": order["total_cents"],
            "fee_variant": order["fee_variant"],
            "freight_tier_applied": order["freight_tier_applied"],
            "final_freight_adjustment_cents": order["final_freight_adjustment_cents"],
            "requires_cold_chain": order["requires_cold_chain"],
            "line_count": order["line_count"],
            "invoiced_at": dt_out(order, "invoiced_at"),
            "delivered_at": dt_out(order, "delivered_at"),
            "cancel_reason": order["cancel_reason"],
        },
    )


def line_out(line):
    return _common(
        line,
        {
            "id": line["id"],
            "sales_order_id": line["sales_order_id"],
            "hop_contract_id": line["hop_contract_id"],
            "malt_lot_id": line["malt_lot_id"],
            "yeast_propagation_job_id": line["yeast_propagation_job_id"],
            "hop_variety_id": line["hop_variety_id"],
            "item_type": line["item_type"],
            "allocation_source": line["allocation_source"],
            "quantity": num(line["quantity"]),
            "uom": line["uom"],
            "unit_price_cents": num(line["unit_price_cents"]),
            "extended_cents": line["extended_cents"],
            "pallet_break": line["pallet_break"],
            "cold_chain_required": line["cold_chain_required"],
            "trimmed_lbs": num(line["trimmed_lbs"]),
            "status": line["status"],
        },
    )


def zone_out(zone):
    occupied = zone_occupied(zone)
    zone["occupied_pallets"] = occupied
    return _common(
        zone,
        {
            "id": zone["id"],
            "zone_code": zone["zone_code"],
            "temp_setpoint_c": num(zone["temp_setpoint_c"]),
            "tolerance_c": num(zone["tolerance_c"]),
            "capacity_pallets": zone["capacity_pallets"],
            "occupied_pallets": occupied,
        },
    )


def shipment_out(shipment):
    return _common(
        shipment,
        {
            "id": shipment["id"],
            "sales_order_id": shipment["sales_order_id"],
            "cold_storage_zone_id": shipment["cold_storage_zone_id"],
            "pallet_count": shipment["pallet_count"],
            "stage_from": dt_out(shipment, "stage_from"),
            "stage_until": dt_out(shipment, "stage_until"),
            "reefer_setpoint_c": num(shipment["reefer_setpoint_c"]),
            "reefer_tolerance_c": num(shipment["reefer_tolerance_c"]),
            "excursion_minutes": shipment["excursion_minutes"],
            "reading_count": shipment["reading_count"],
            "last_reading_at": dt_out(shipment, "last_reading_at"),
            "status": shipment["status"],
        },
    )


def reading_out(reading):
    return {
        "id": reading["id"],
        "cold_chain_shipment_id": reading["cold_chain_shipment_id"],
        "temp_c": num(reading["temp_c"]),
        "recorded_at": dt_out(reading, "recorded_at"),
        "interval_minutes": reading["interval_minutes"],
        "in_violation": reading["in_violation"],
        "cumulative_excursion_minutes": reading["cumulative_excursion_minutes"],
        "created_at": dt_out(reading, "created_at"),
    }


def _opt_num(value):
    return None if value is None else num(value)


def spec_match_out(result):
    return {
        "malt_lot_id": result["malt_lot_id"],
        "recipe_id": result["recipe_id"],
        "match_score": _opt_num(result["match_score"]),
        "match_grade": result["match_grade"],
        "deviation_color": _opt_num(result["deviation_color"]),
        "deviation_extract": _opt_num(result["deviation_extract"]),
        "deviation_protein": _opt_num(result["deviation_protein"]),
        "hard_fail_reason": result["hard_fail_reason"],
        "applicable_diastatic_power_floor": _opt_num(
            result["applicable_diastatic_power_floor"]
        ),
    }
