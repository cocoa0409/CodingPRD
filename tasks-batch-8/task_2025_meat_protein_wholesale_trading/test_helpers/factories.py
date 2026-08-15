"""Payload factories — one per entity, input fields only (PRD §3).

Unique business codes default to a random suffix so a single test may create
several of the same entity without tripping the uniqueness rules of PRD §2.8.
"""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:8].upper()


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": f"PackCo {_suffix()}",
        "establishment_number": f"EST-{_suffix()}",
        "contact_email": "ops@packco.example",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    suffix = _suffix()
    defaults = {
        "name": f"Buyer {suffix}",
        "customer_code": f"CUST-{suffix}",
        "credit_limit_cents": 100_000_000,
        "allocation_tier": "TIER_1",
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "name": f"WH-{_suffix()}",
        "zone": "CHILLER",
        "capacity_lbs": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": f"PRD-{_suffix()}",
        "kind": "PRIMAL",
        "species": "BEEF",
        "max_fat_pct": 12.0,
        "shelf_life_days": 21,
        "required_temp_max_f": 40,
    }
    defaults.update(overrides)
    return defaults


def create_yield_spec_payload(carcass_product_id, output_product_id,
                              expected_yield_pct=50.0, min_yield_pct=45.0,
                              max_yield_pct=55.0, **overrides) -> dict:
    defaults = {
        "carcass_product_id": carcass_product_id,
        "output_product_id": output_product_id,
        "expected_yield_pct": expected_yield_pct,
        "min_yield_pct": min_yield_pct,
        "max_yield_pct": max_yield_pct,
    }
    defaults.update(overrides)
    return defaults


def create_price_sheet_payload(week_start_date="2026-08-03", **overrides) -> dict:
    defaults = {"week_start_date": week_start_date}
    defaults.update(overrides)
    return defaults


def create_sheet_line_payload(product_id, price_per_lb_cents=700,
                              weekly_supply_lbs=100_000, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "price_per_lb_cents": price_per_lb_cents,
        "weekly_supply_lbs": weekly_supply_lbs,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(supplier_id, product_id,
                                  ordered_weight_lbs=1000,
                                  contract_price_per_cwt_cents=20_000,
                                  required_delivery_date="2026-08-04",
                                  **overrides) -> dict:
    defaults = {
        "po_number": f"PO-{_suffix()}",
        "supplier_id": supplier_id,
        "product_id": product_id,
        "ordered_weight_lbs": ordered_weight_lbs,
        "contract_price_per_cwt_cents": contract_price_per_cwt_cents,
        "required_delivery_date": required_delivery_date,
    }
    defaults.update(overrides)
    return defaults


def receive_po_payload(warehouse_id, received_weight_lbs=1000,
                       lot_code=None, production_date="2026-08-01",
                       **overrides) -> dict:
    defaults = {
        "received_weight_lbs": received_weight_lbs,
        "warehouse_id": warehouse_id,
        "lot_code": lot_code or f"LOT-{_suffix()}",
        "production_date": production_date,
    }
    defaults.update(overrides)
    return defaults


def inspect_lot_payload(measured_fat_pct=10.0, **overrides) -> dict:
    defaults = {"measured_fat_pct": measured_fat_pct}
    defaults.update(overrides)
    return defaults


def create_fabrication_batch_payload(input_lot_id, loss_lbs=0, outputs=None,
                                     **overrides) -> dict:
    defaults = {
        "input_lot_id": input_lot_id,
        "loss_lbs": loss_lbs,
        "outputs": outputs if outputs is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_forward_contract_payload(customer_id, product_id, committed_lbs=100,
                                    fixed_price_per_lb_cents=650,
                                    delivery_week_start="2026-08-03",
                                    **overrides) -> dict:
    defaults = {
        "contract_number": f"FC-{_suffix()}",
        "customer_id": customer_id,
        "product_id": product_id,
        "committed_lbs": committed_lbs,
        "fixed_price_per_lb_cents": fixed_price_per_lb_cents,
        "delivery_week_start": delivery_week_start,
    }
    defaults.update(overrides)
    return defaults


def amend_forward_contract_payload(committed_lbs, fixed_price_per_lb_cents,
                                   delivery_week_start, expected_contract_version,
                                   **overrides) -> dict:
    defaults = {
        "committed_lbs": committed_lbs,
        "fixed_price_per_lb_cents": fixed_price_per_lb_cents,
        "delivery_week_start": delivery_week_start,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(customer_id, price_sheet_line_id, requested_lbs=100,
                              **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "price_sheet_line_id": price_sheet_line_id,
        "requested_lbs": requested_lbs,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(allocation_id, shipped_lbs=100, carrier_name="CAR-1",
                            trailer_temp_setpoint_f=36.0, **overrides) -> dict:
    defaults = {
        "allocation_id": allocation_id,
        "carrier_name": carrier_name,
        "trailer_temp_setpoint_f": trailer_temp_setpoint_f,
        "shipped_lbs": shipped_lbs,
    }
    defaults.update(overrides)
    return defaults


def temperature_reading_payload(reading_f=38.0,
                                recorded_at="2026-08-03T08:00:00Z",
                                **overrides) -> dict:
    defaults = {"reading_f": reading_f, "recorded_at": recorded_at}
    defaults.update(overrides)
    return defaults


def reject_shipment_payload(rejection_reason="refused at dock", **overrides) -> dict:
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


def create_claim_payload(shipment_id, claim_type="QUALITY_DEFECT",
                         claimed_amount_cents=10_000, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def claim_offer_payload(offer_cents, expected_claim_version, **overrides) -> dict:
    defaults = {
        "offer_cents": offer_cents,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def claim_counter_payload(counter_amount_cents, **overrides) -> dict:
    defaults = {"counter_amount_cents": counter_amount_cents}
    defaults.update(overrides)
    return defaults


def create_certificate_payload(lot_id, certificate_type="USDA_GRADE",
                               grade_result="CHOICE", certificate_number=None,
                               issued_by="USDA-JW", issue_date="2026-08-03",
                               **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "certificate_type": certificate_type,
        "certificate_number": certificate_number or f"CERT-{_suffix()}",
        "issued_by": issued_by,
        "issue_date": issue_date,
    }
    if certificate_type == "USDA_GRADE":
        defaults["grade_result"] = grade_result
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601="2026-08-03T00:00:00Z", **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
