"""Payload factories — one per entity, input fields only."""
from . import constants as C


def create_spec_payload(spec_code=C.SPEC_CODE_GMA, length_in=C.SPEC_LENGTH_IN,
                        width_in=C.SPEC_WIDTH_IN, height_in=C.SPEC_HEIGHT_IN,
                        board_count=C.SPEC_BOARD_COUNT, lumber_species="PINE",
                        requires_heat_treatment_default=None, **overrides):
    payload = {
        "spec_code": spec_code,
        "length_in": length_in,
        "width_in": width_in,
        "height_in": height_in,
        "board_count": board_count,
        "lumber_species": lumber_species,
    }
    if requires_heat_treatment_default is not None:
        payload["requires_heat_treatment_default"] = requires_heat_treatment_default
    payload.update(overrides)
    return payload


def create_lumber_index_payload(species="PINE",
                                price_per_mbf_cents=C.PINE_PRICE_PER_MBF_CENTS,
                                effective_from=C.INDEX_WINDOW_START,
                                effective_to=C.INDEX_WINDOW_END,
                                source_note=None, **overrides):
    payload = {
        "species": species,
        "price_per_mbf_cents": price_per_mbf_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    if source_note is not None:
        payload["source_note"] = source_note
    payload.update(overrides)
    return payload


def create_seasonal_index_payload(season_code="PEAK-2026-Q3",
                                  multiplier_bp=11_000,
                                  effective_from=C.CLOCK_DEFAULT,
                                  effective_to=C.INDEX_WINDOW_END,
                                  **overrides):
    payload = {
        "season_code": season_code,
        "multiplier_bp": multiplier_bp,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def create_core_batch_payload(supplier_name="CoreCo",
                              agreed_unit_price_cents=500,
                              manifest_count=1,
                              estimated_grade_mix=None, **overrides):
    payload = {
        "supplier_name": supplier_name,
        "agreed_unit_price_cents": agreed_unit_price_cents,
        "manifest_count": manifest_count,
        "estimated_grade_mix": estimated_grade_mix
        or {"A": 1.0, "B": 0.0, "SCRAP": 0.0},
    }
    payload.update(overrides)
    return payload


def create_core_unit_payload(batch_id, species="PINE", condition_notes=None,
                             **overrides):
    payload = {"batch_id": batch_id, "species": species}
    if condition_notes is not None:
        payload["condition_notes"] = condition_notes
    payload.update(overrides)
    return payload


def create_repair_order_payload(core_unit_id, target_spec_id, target_grade="A",
                                labor_minutes_estimate=30,
                                parts_cost_cents=None, **overrides):
    payload = {
        "core_unit_id": core_unit_id,
        "target_spec_id": target_spec_id,
        "target_grade": target_grade,
        "labor_minutes_estimate": labor_minutes_estimate,
    }
    if parts_cost_cents is not None:
        payload["parts_cost_cents"] = parts_cost_cents
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(spec_id, origin_type="NEW_BUILD",
                                 quantity_total=100, quality_grade="NEW",
                                 **overrides):
    payload = {
        "spec_id": spec_id,
        "origin_type": origin_type,
        "quantity_total": quantity_total,
    }
    if quality_grade is not None:
        payload["quality_grade"] = quality_grade
    payload.update(overrides)
    return payload


def create_ht_run_payload(chamber_code="CH-1", species_profile="PINE",
                          capacity_pallets=100, **overrides):
    payload = {
        "chamber_code": chamber_code,
        "species_profile": species_profile,
        "capacity_pallets": capacity_pallets,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(company_name="CustomerCo", **overrides):
    payload = {"company_name": company_name}
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, spec_id, quantity=1,
                         quality_grade_requested="NEW",
                         requested_delivery_date=C.DEFAULT_DELIVERY_DATE,
                         heat_treatment_required=None, **overrides):
    payload = {
        "customer_id": customer_id,
        "requested_delivery_date": requested_delivery_date,
        "spec_id": spec_id,
        "quantity": quantity,
        "quality_grade_requested": quality_grade_requested,
    }
    if heat_treatment_required is not None:
        payload["heat_treatment_required"] = heat_treatment_required
    payload.update(overrides)
    return payload


def create_order_line_payload(spec_id, quantity=1,
                              quality_grade_requested="NEW",
                              heat_treatment_required=None, **overrides):
    payload = {
        "spec_id": spec_id,
        "quantity": quantity,
        "quality_grade_requested": quality_grade_requested,
    }
    if heat_treatment_required is not None:
        payload["heat_treatment_required"] = heat_treatment_required
    payload.update(overrides)
    return payload


def create_pool_return_payload(customer_id, returned_count=1,
                               grade_on_return="A", route_stop_id=None,
                               **overrides):
    payload = {
        "customer_id": customer_id,
        "returned_count": returned_count,
        "grade_on_return": grade_on_return,
    }
    if route_stop_id is not None:
        payload["route_stop_id"] = route_stop_id
    payload.update(overrides)
    return payload


def create_route_payload(route_date=C.DEFAULT_ROUTE_DATE,
                         trailer_cube_capacity_cuft=5000,
                         planned_miles=40, **overrides):
    payload = {
        "route_date": route_date,
        "trailer_cube_capacity_cuft": trailer_cube_capacity_cuft,
        "planned_miles": planned_miles,
    }
    payload.update(overrides)
    return payload


def create_route_stop_payload(stop_sequence=1, stop_type="DELIVERY",
                              order_id=None, pickup_customer_id=None,
                              **overrides):
    payload = {"stop_sequence": stop_sequence, "stop_type": stop_type}
    if order_id is not None:
        payload["order_id"] = order_id
    if pickup_customer_id is not None:
        payload["pickup_customer_id"] = pickup_customer_id
    payload.update(overrides)
    return payload


def create_grinding_batch_payload(input_core_ids, **overrides):
    payload = {"input_core_ids": list(input_core_ids)}
    payload.update(overrides)
    return payload
