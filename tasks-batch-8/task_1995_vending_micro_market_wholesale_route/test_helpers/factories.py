"""Payload factories — one per entity, input fields only (PRD §3)."""

__all__ = [
    "create_operator_payload",
    "create_route_payload",
    "create_product_payload",
    "create_location_payload",
    "create_planogram_payload",
    "create_telemetry_event_payload",
    "create_order_payload",
    "create_promotion_payload",
    "create_credit_claim_payload",
    "create_service_ticket_payload",
]


def create_operator_payload(name="Test Operator", default_tender=None) -> dict:
    payload = {"name": name}
    if default_tender is not None:
        payload["default_tender"] = default_tender
    return payload


def create_route_payload(route_code="R-TEST", delivery_weekdays=("MON",),
                         daily_case_capacity=100, min_order_cents=0) -> dict:
    return {
        "route_code": route_code,
        "delivery_weekdays": list(delivery_weekdays),
        "daily_case_capacity": daily_case_capacity,
        "min_order_cents": min_order_cents,
    }


def create_product_payload(sku="SKU-1", name="Test Product", category="SNACK",
                           eligible_location_types=("OFFICE",), case_pack_qty=10,
                           base_price_cents=1000, cost_cents=600,
                           shelf_life_days=90, perishability_class=None) -> dict:
    payload = {
        "sku": sku,
        "name": name,
        "category": category,
        "eligible_location_types": list(eligible_location_types),
        "case_pack_qty": case_pack_qty,
        "base_price_cents": base_price_cents,
        "cost_cents": cost_cents,
        "shelf_life_days": shelf_life_days,
    }
    if perishability_class is not None:
        payload["perishability_class"] = perishability_class
    return payload


def create_location_payload(operator_id, route_id, name="Test Location",
                            location_type="OFFICE") -> dict:
    return {
        "operator_id": operator_id,
        "name": name,
        "location_type": location_type,
        "route_id": route_id,
    }


def create_planogram_payload(location_id, slots, name="Test Planogram") -> dict:
    return {
        "location_id": location_id,
        "name": name,
        "slots": slots,
    }


def create_telemetry_event_payload(location_id, recorded_at, items,
                                   cash_collected_cents=0, cashless_sales_cents=0) -> dict:
    return {
        "location_id": location_id,
        "recorded_at": recorded_at,
        "cash_collected_cents": cash_collected_cents,
        "cashless_sales_cents": cashless_sales_cents,
        "items": items,
    }


def create_order_payload(location_id, requested_delivery_date, lines) -> dict:
    return {
        "location_id": location_id,
        "requested_delivery_date": requested_delivery_date,
        "lines": lines,
    }


def create_promotion_payload(product_id, discount_type, discount_value,
                             starts_at, ends_at, stacking_class,
                             operator_id=None) -> dict:
    payload = {
        "product_id": product_id,
        "discount_type": discount_type,
        "discount_value": discount_value,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "stacking_class": stacking_class,
    }
    if operator_id is not None:
        payload["operator_id"] = operator_id
    return payload


def create_credit_claim_payload(order_id, lines) -> dict:
    return {
        "order_id": order_id,
        "lines": lines,
    }


def create_service_ticket_payload(location_id, equipment_model="VENDO-540",
                                  issue_type="REPAIR", parts=None) -> dict:
    return {
        "location_id": location_id,
        "equipment_model": equipment_model,
        "issue_type": issue_type,
        "parts": parts if parts is not None else [],
    }
