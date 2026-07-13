"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "EMAIL": "rider@example.com",
    "FULL_NAME": "Test Rider",
    "DOB": "1990-01-01",
    "PROOF_REF": "proof-doc-1",
    "PROOF_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "BASE_FARE": 1000,
    "PEAK_SURCHARGE": 300,
}


def create_fare_product_payload(**overrides) -> dict:
    payload = {
        "origin_zone": 1,
        "destination_zone": 3,
        "ticket_type": "SINGLE",
        "base_fare_cents": DEFAULTS["BASE_FARE"],
        "peak_surcharge_cents": DEFAULTS["PEAK_SURCHARGE"],
        "apportionment_method": "ZONE_COUNT",
    }
    payload.update(overrides)
    return payload


def create_agency_payload(code: str, zones_served, **overrides) -> dict:
    payload = {"code": code, "zones_served": list(zones_served)}
    payload.update(overrides)
    return payload


def create_passenger_payload(**overrides) -> dict:
    payload = {
        "email": DEFAULTS["EMAIL"],
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(passenger_id, category, expected_passenger_version, **overrides) -> dict:
    payload = {
        "passenger_id": passenger_id,
        "category": category,
        "proof_document_ref": DEFAULTS["PROOF_REF"],
        "proof_expires_at": DEFAULTS["PROOF_EXPIRES_AT"],
        "expected_passenger_version": expected_passenger_version,
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(passenger_id, fare_product_id, travel_period,
                          use_reduced_fare=None, wallet_apply_cents=None, **overrides) -> dict:
    payload = {
        "passenger_id": passenger_id,
        "fare_product_id": fare_product_id,
        "travel_period": travel_period,
    }
    if use_reduced_fare is not None:
        payload["use_reduced_fare"] = use_reduced_fare
    if wallet_apply_cents is not None:
        payload["wallet_apply_cents"] = wallet_apply_cents
    payload.update(overrides)
    return payload


def create_inspection_payload(passenger_id, observed_destination_zone, ticket_id=None, **overrides) -> dict:
    payload = {
        "passenger_id": passenger_id,
        "observed_destination_zone": observed_destination_zone,
    }
    if ticket_id is not None:
        payload["ticket_id"] = ticket_id
    payload.update(overrides)
    return payload


def create_upgrade_payload(inspection_id, ticket_id, **overrides) -> dict:
    payload = {"inspection_id": inspection_id, "ticket_id": ticket_id}
    payload.update(overrides)
    return payload


def create_citation_payload(inspection_id, passenger_id, **overrides) -> dict:
    payload = {"inspection_id": inspection_id, "passenger_id": passenger_id}
    payload.update(overrides)
    return payload


def create_refund_request_payload(ticket_id, refund_destination="WALLET", reason="changed plans", **overrides) -> dict:
    payload = {"ticket_id": ticket_id, "reason": reason, "refund_destination": refund_destination}
    payload.update(overrides)
    return payload


def create_disruption_payload(line_code, scheduled_departure, actual_departure,
                              window_start, window_end, **overrides) -> dict:
    payload = {
        "line_code": line_code,
        "scheduled_departure": scheduled_departure,
        "actual_departure": actual_departure,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_service_credit_payload(disruption_id, ticket_id, **overrides) -> dict:
    payload = {"disruption_id": disruption_id, "ticket_id": ticket_id}
    payload.update(overrides)
    return payload
