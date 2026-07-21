"""Payload factories — one per entity, input fields only."""


def create_product_payload(**overrides) -> dict:
    payload = {
        "name": "Test Shoe",
        "brand": "TestBrand",
        "category": "REGULAR",
        "base_price_cents": 9000,
    }
    payload.update(overrides)
    return payload


def create_inventory_item_payload(product_id, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "size": 9.0,
        "width": "D",
        "lot_number": "LOT1",
        "quantity_on_hand": 5,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Customer",
        "date_of_birth": "1960-01-01",
    }
    payload.update(overrides)
    return payload


def create_measurement_payload(**overrides) -> dict:
    payload = {
        "foot_length_mm_left": 250.0,
        "foot_length_mm_right": 252.0,
        "foot_width_mm_left": 95.0,
        "foot_width_mm_right": 96.0,
    }
    payload.update(overrides)
    return payload


def create_fitter_payload(**overrides) -> dict:
    payload = {"full_name": "Test Fitter"}
    payload.update(overrides)
    return payload


def create_gait_lab_payload(**overrides) -> dict:
    payload = {"name": "Test Lab", "concurrent_capacity": 1}
    payload.update(overrides)
    return payload


def create_appointment_payload(customer_id, fitter_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "fitter_id": fitter_id,
        "appointment_type": "FITTING",
        "start_time": "2026-07-02T10:00:00Z",
        "end_time": "2026-07-02T10:30:00Z",
    }
    payload.update(overrides)
    return payload


def create_sale_payload(customer_id, fitter_id, **overrides) -> dict:
    payload = {"customer_id": customer_id, "fitter_id": fitter_id}
    payload.update(overrides)
    return payload


def create_sale_line_payload(inventory_item_id, **overrides) -> dict:
    payload = {"inventory_item_id": inventory_item_id, "quantity": 1}
    payload.update(overrides)
    return payload


def create_certification_payload(expected_customer_version, **overrides) -> dict:
    payload = {
        "certifying_physician_npi": "1234567890",
        "prescribing_practitioner_npi": "0987654321",
        "statement_date": "2026-06-01",
        "in_person_visit_date": "2026-05-01",
        "expected_customer_version": expected_customer_version,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(customer_id, sale_id, certification_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "sale_id": sale_id,
        "certification_id": certification_id,
        "hcpcs_code": "A5500",
        "billed_amount_cents": 30000,
    }
    payload.update(overrides)
    return payload


def create_return_payload(sale_id, sale_line_id, **overrides) -> dict:
    payload = {
        "sale_id": sale_id,
        "sale_line_id": sale_line_id,
        "return_type": "RETURN",
    }
    payload.update(overrides)
    return payload


def create_special_order_payload(customer_id, product_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_id": product_id,
        "requested_size": 9.0,
        "requested_width": "D",
        "deposit_cents": 3000,
    }
    payload.update(overrides)
    return payload


def create_recall_payload(product_id, **overrides) -> dict:
    payload = {"product_id": product_id, "reason": "safety recall"}
    payload.update(overrides)
    return payload


def create_ledger_payload(customer_id, points_delta, reason, **overrides) -> dict:
    payload = {"customer_id": customer_id, "points_delta": points_delta, "reason": reason}
    payload.update(overrides)
    return payload
