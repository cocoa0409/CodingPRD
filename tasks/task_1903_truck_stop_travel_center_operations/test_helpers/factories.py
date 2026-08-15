"""Payload factories — one per create/action endpoint, input fields only."""
from .constants import (
    DEFAULT_CLOCK_ISO,
    REGISTER_FLOAT_CENTS,
)


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Site",
        "parking_total_spaces": 60,
        "parking_paid_capacity": 2,
        "shower_units_count": 1,
        "laundry_machines_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_price_payload(site_version, fuel_type="DIESEL", cents=385,
                              effective_from=DEFAULT_CLOCK_ISO,
                              effective_to=None, **overrides) -> dict:
    payload = {
        "fuel_type": fuel_type,
        "retail_cents_per_gallon": cents,
        "effective_from": effective_from,
        "expected_site_version": site_version,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    payload.update(overrides)
    return payload


def create_pump_payload(pump_number=1, fuel_types=("DIESEL",), **overrides) -> dict:
    payload = {"pump_number": pump_number, "fuel_types": list(fuel_types)}
    payload.update(overrides)
    return payload


def create_register_payload(register_code="R1", float_cents=REGISTER_FLOAT_CENTS,
                            **overrides) -> dict:
    payload = {"register_code": register_code, "float_cents": float_cents}
    payload.update(overrides)
    return payload


def create_shift_payload(register_id, cashier_user_id="cash-1", shift_label="DAY",
                         **overrides) -> dict:
    payload = {
        "register_id": register_id,
        "cashier_user_id": cashier_user_id,
        "shift_label": shift_label,
    }
    payload.update(overrides)
    return payload


def create_fuel_sale_payload(pump_id, shift_id, pricing_mode="RETAIL",
                             fuel_type="DIESEL", tender_type="CASH",
                             max_gallons=40.0, **overrides) -> dict:
    payload = {
        "pump_id": pump_id,
        "shift_id": shift_id,
        "pricing_mode": pricing_mode,
        "fuel_type": fuel_type,
        "tender_type": tender_type,
        "max_gallons": max_gallons,
    }
    payload.update(overrides)
    return payload


def dispensing_complete_payload(dispensed_gallons, **overrides) -> dict:
    payload = {"dispensed_gallons": dispensed_gallons}
    payload.update(overrides)
    return payload


def fuel_sale_pay_payload(tender_type="CASH", **overrides) -> dict:
    payload = {"tender_type": tender_type}
    payload.update(overrides)
    return payload


def fuel_sale_void_payload(reason="void", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def create_fleet_account_payload(name="Fleet A", credit_limit_cents=50_000_000,
                                 pricing_tier="T1", **overrides) -> dict:
    payload = {
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "pricing_tier": pricing_tier,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(contract_code="C-1", pricing_tier="T1",
                            discount_per_gallon_off=0.0,
                            applicable_fuel_types=("DIESEL",),
                            effective_from="2026-08-01T00:00:00Z",
                            effective_to="2027-08-01T00:00:00Z",
                            **overrides) -> dict:
    payload = {
        "contract_code": contract_code,
        "pricing_tier": pricing_tier,
        "discount_per_gallon_off": discount_per_gallon_off,
        "applicable_fuel_types": list(applicable_fuel_types),
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def amend_contract_payload(expected_contract_version, **overrides) -> dict:
    payload = {"expected_contract_version": expected_contract_version}
    payload.update(overrides)
    return payload


def create_loyalty_member_payload(full_name="Driver A", email="a@x.com",
                                  **overrides) -> dict:
    payload = {"full_name": full_name, "email": email}
    payload.update(overrides)
    return payload


def member_adjustment_payload(points_delta, reason="adjustment", **overrides) -> dict:
    payload = {"points_delta": points_delta, "reason": reason}
    payload.update(overrides)
    return payload


def create_member_vehicle_payload(plate="AAA111", vehicle_type="TRACTOR",
                                  **overrides) -> dict:
    payload = {"plate": plate, "vehicle_type": vehicle_type}
    payload.update(overrides)
    return payload


def create_discount_network_payload(name="FleetPass", discount_per_gallon=0.10,
                                    applicable_fuel_types=("DIESEL",),
                                    program_cap=2, **overrides) -> dict:
    payload = {
        "name": name,
        "discount_per_gallon": discount_per_gallon,
        "applicable_fuel_types": list(applicable_fuel_types),
        "program_cap": program_cap,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(network_program_id, **overrides) -> dict:
    payload = {"network_program_id": network_program_id}
    payload.update(overrides)
    return payload


def create_parking_space_payload(space_number="A1", space_type="STANDARD",
                                 is_reservable=True, **overrides) -> dict:
    payload = {
        "space_number": space_number,
        "space_type": space_type,
        "is_reservable": is_reservable,
    }
    payload.update(overrides)
    return payload


def create_parking_reservation_payload(loyalty_member_id, vehicle_plate,
                                       space_type="STANDARD",
                                       reserved_from="2026-08-12T22:00:00Z",
                                       reserved_to="2026-08-13T06:00:00Z",
                                       **overrides) -> dict:
    payload = {
        "loyalty_member_id": loyalty_member_id,
        "vehicle_plate": vehicle_plate,
        "space_type": space_type,
        "reserved_from": reserved_from,
        "reserved_to": reserved_to,
    }
    payload.update(overrides)
    return payload


def parking_check_in_payload(tender_type="CARD", shift_id=None, **overrides) -> dict:
    payload = {"tender_type": tender_type}
    if shift_id is not None:
        payload["shift_id"] = shift_id
    payload.update(overrides)
    return payload


def create_service_ticket_payload(service_type="SHOWER", **overrides) -> dict:
    payload = {"service_type": service_type}
    payload.update(overrides)
    return payload


def service_call_payload(service_type="SHOWER", **overrides) -> dict:
    payload = {"service_type": service_type}
    payload.update(overrides)
    return payload


def service_complete_payload(**overrides) -> dict:
    return dict(overrides)


def service_pay_payload(tender_type="CASH", **overrides) -> dict:
    payload = {"tender_type": tender_type}
    payload.update(overrides)
    return payload


def create_scale_ticket_payload(shift_id, vehicle_plate="TRK-9",
                                carrier_name="Acme Hauling", certified=True,
                                **overrides) -> dict:
    payload = {
        "shift_id": shift_id,
        "vehicle_plate": vehicle_plate,
        "carrier_name": carrier_name,
        "certified": certified,
    }
    payload.update(overrides)
    return payload


def scale_weigh_payload(weigh_kind, weight_lbs, **overrides) -> dict:
    payload = {"weigh_kind": weigh_kind, "weight_lbs": weight_lbs}
    payload.update(overrides)
    return payload


def scale_settle_payload(tender_type="CASH", **overrides) -> dict:
    payload = {"tender_type": tender_type}
    payload.update(overrides)
    return payload


def create_stock_item_payload(sku="SNACK-A", name="Snack A", category="RETAIL",
                              unit="ea", unit_price_cents=999, reorder_point=5,
                              initial_on_hand_quantity=50, **overrides) -> dict:
    payload = {
        "sku": sku,
        "name": name,
        "category": category,
        "unit": unit,
        "unit_price_cents": unit_price_cents,
        "reorder_point": reorder_point,
        "initial_on_hand_quantity": initial_on_hand_quantity,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(name="Parts R Us", category="GENERAL", **overrides) -> dict:
    payload = {"name": name, "category": category}
    payload.update(overrides)
    return payload


def create_vendor_price_payload(item_sku, unit="ea", unit_price_cents=3000,
                                **overrides) -> dict:
    payload = {"item_sku": item_sku, "unit": unit, "unit_price_cents": unit_price_cents}
    payload.update(overrides)
    return payload


def create_purchase_order_payload(vendor_id, lines, **overrides) -> dict:
    payload = {"vendor_id": vendor_id, "lines": lines}
    payload.update(overrides)
    return payload


def po_receive_payload(received_lines, **overrides) -> dict:
    payload = {"received_lines": received_lines}
    payload.update(overrides)
    return payload


def create_bay_payload(bay_number=1, **overrides) -> dict:
    payload = {"bay_number": bay_number}
    payload.update(overrides)
    return payload


def bay_maintenance_block_payload(blocked_from, blocked_to, reason="maintenance",
                                  **overrides) -> dict:
    payload = {"blocked_from": blocked_from, "blocked_to": blocked_to,
               "reason": reason}
    payload.update(overrides)
    return payload


def create_technician_payload(name="Tech One", hourly_rate_cents=12500,
                              **overrides) -> dict:
    payload = {"name": name, "hourly_rate_cents": hourly_rate_cents}
    payload.update(overrides)
    return payload


def create_work_order_payload(vehicle_plate="TRK-1", complaint="brake shake",
                              **overrides) -> dict:
    payload = {"vehicle_plate": vehicle_plate, "complaint": complaint}
    payload.update(overrides)
    return payload


def work_order_estimate_payload(labor_hours_est=2.0, **overrides) -> dict:
    payload = {"labor_hours_est": labor_hours_est}
    payload.update(overrides)
    return payload


def work_order_schedule_payload(bay_id, technician_id,
                                scheduled_from="2026-08-13T08:00:00Z",
                                scheduled_to="2026-08-13T10:00:00Z",
                                **overrides) -> dict:
    payload = {
        "bay_id": bay_id,
        "technician_id": technician_id,
        "scheduled_from": scheduled_from,
        "scheduled_to": scheduled_to,
    }
    payload.update(overrides)
    return payload


def issue_part_payload(stock_item_id, quantity, **overrides) -> dict:
    payload = {"stock_item_id": stock_item_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def complete_work_payload(labor_hours_actual, **overrides) -> dict:
    payload = {"labor_hours_actual": labor_hours_actual}
    payload.update(overrides)
    return payload


def work_order_close_payload(tender_type="CASH", **overrides) -> dict:
    payload = {"tender_type": tender_type}
    payload.update(overrides)
    return payload


def send_to_vendor_payload(vendor_name="Alignment Co", reason="rack down",
                           **overrides) -> dict:
    payload = {"vendor_name": vendor_name, "reason": reason}
    payload.update(overrides)
    return payload


def shift_drop_payload(amount_cents, denominations, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "denominations": denominations}
    payload.update(overrides)
    return payload


def shift_payout_payload(amount_cents, reason="payout", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


def shift_close_payload(counted_cash_cents, approve_variance=None,
                        **overrides) -> dict:
    payload = {"counted_cash_cents": counted_cash_cents}
    if approve_variance is not None:
        payload["approve_variance"] = approve_variance
    payload.update(overrides)
    return payload


def create_store_sale_payload(shift_id, lines, tender_type="CASH",
                              **overrides) -> dict:
    payload = {"shift_id": shift_id, "tender_type": tender_type, "lines": lines}
    payload.update(overrides)
    return payload


def store_sale_refund_payload(reason="wrong item", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def create_bulk_tank_payload(product_type="DIESEL", capacity_gallons=20000,
                             reorder_threshold_gallons=3000,
                             safety_stock_gallons=1500, daily_usage_gallons=950,
                             lead_time_days=4, initial_gallons=8500,
                             rack_price_cents_per_gallon_4dp=None,
                             **overrides) -> dict:
    payload = {
        "product_type": product_type,
        "capacity_gallons": capacity_gallons,
        "reorder_threshold_gallons": reorder_threshold_gallons,
        "safety_stock_gallons": safety_stock_gallons,
        "daily_usage_gallons": daily_usage_gallons,
        "lead_time_days": lead_time_days,
        "initial_gallons": initial_gallons,
    }
    if rack_price_cents_per_gallon_4dp is not None:
        payload["rack_price_cents_per_gallon_4dp"] = rack_price_cents_per_gallon_4dp
    payload.update(overrides)
    return payload


def tank_delivery_payload(gallons_delivered, **overrides) -> dict:
    payload = {"gallons_delivered": gallons_delivered}
    payload.update(overrides)
    return payload


def stick_reading_payload(reading_gallons, **overrides) -> dict:
    payload = {"reading_gallons": reading_gallons}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
