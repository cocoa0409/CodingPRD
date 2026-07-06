"""Payload factories — one per entity, input fields only."""


def create_client_payload(**overrides) -> dict:
    payload = {"name": "Test Owner", "phone": "555-0100"}
    payload.update(overrides)
    return payload


def create_project_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "address": "1 Test St",
        "estimated_total_value_cents": 100000,
    }
    payload.update(overrides)
    return payload


def create_lot_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "title": "Test lot",
    }
    payload.update(overrides)
    return payload


def create_sale_event_payload(project_id, crew_id, start_at, end_at, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "crew_id": crew_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {"name": "Test Crew"}
    payload.update(overrides)
    return payload


def create_transaction_payload(sale_event_id, lot_id, payment_method="CASH", **overrides) -> dict:
    payload = {
        "sale_event_id": sale_event_id,
        "lot_id": lot_id,
        "payment_method": payment_method,
    }
    payload.update(overrides)
    return payload


def create_bid_payload(lot_id, amount_cents, bidder_name="bidder", **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "amount_cents": amount_cents,
        "bidder_name": bidder_name,
    }
    payload.update(overrides)
    return payload


def create_haul_job_payload(project_id, truck_id, disposition_type, start_at, end_at, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "truck_id": truck_id,
        "disposition_type": disposition_type,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_truck_payload(**overrides) -> dict:
    payload = {"name": "Test Truck"}
    payload.update(overrides)
    return payload


def create_settlement_payload(project_id, expected_project_version, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload
