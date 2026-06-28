"""Payload factories — one per create endpoint, input fields only.

Field names are PRD-exact. Optional fields are only included when explicitly overridden,
so factories never assert a server-side default the implementer is free to choose.
"""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "TECH_NAME": "Test Tech",
    "ROUTE_NAME": "Test Route",
    "ADDRESS": "1 Test Way",
}


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_customer_payload(full_name=None, email="cust@example.com", **overrides) -> dict:
    payload = {
        "full_name": full_name or DEFAULTS["CUSTOMER_NAME"],
        "email": email,
    }
    payload.update(overrides)
    return payload


def create_technician_payload(full_name=None, **overrides) -> dict:
    payload = {"full_name": full_name or DEFAULTS["TECH_NAME"]}
    payload.update(overrides)
    return payload


def create_route_payload(name=None, **overrides) -> dict:
    payload = {"name": name or DEFAULTS["ROUTE_NAME"]}
    payload.update(overrides)
    return payload


def create_property_payload(customer_id, route_id, stories=1, address=None, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "route_id": route_id,
        "address": address or DEFAULTS["ADDRESS"],
        "stories": stories,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(property_id, expected_property_version, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "expected_property_version": expected_property_version,
    }
    payload.update(overrides)
    return payload


def create_line_item_payload(surface_type, service_type, measured_sqft, **overrides) -> dict:
    payload = {
        "surface_type": surface_type,
        "service_type": service_type,
        "measured_sqft": measured_sqft,
    }
    payload.update(overrides)
    return payload


def create_plan_payload(property_id, source_quote_id, cadence_days, start_utc, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "source_quote_id": source_quote_id,
        "cadence_days": cadence_days,
        "start_utc": start_utc,
    }
    payload.update(overrides)
    return payload


def generate_visit_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_visit_payload(property_id, quote_id, scheduled_date, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "quote_id": quote_id,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def schedule_visit_payload(expected_visit_version, **overrides) -> dict:
    payload = {"expected_visit_version": expected_visit_version}
    payload.update(overrides)
    return payload


def complete_visit_payload(re_measured_roof_sqft=0, re_measured_siding_sqft=0,
                           re_measured_concrete_sqft=0, **overrides) -> dict:
    payload = {
        "re_measured_roof_sqft": re_measured_roof_sqft,
        "re_measured_siding_sqft": re_measured_siding_sqft,
        "re_measured_concrete_sqft": re_measured_concrete_sqft,
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(visit_id, technician_id, window_start_utc, **overrides) -> dict:
    payload = {
        "visit_id": visit_id,
        "technician_id": technician_id,
        "window_start_utc": window_start_utc,
    }
    payload.update(overrides)
    return payload


def create_weather_window_payload(route_id, window_start_utc, window_end_utc,
                                  wind_mph, **overrides) -> dict:
    payload = {
        "route_id": route_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "wind_mph": wind_mph,
    }
    payload.update(overrides)
    return payload


def upload_photo_payload(phase, photo_url="http://img/photo.jpg", **overrides) -> dict:
    payload = {"phase": phase, "photo_url": photo_url}
    payload.update(overrides)
    return payload


def create_claim_payload(visit_id, reason="dissatisfied", **overrides) -> dict:
    payload = {"visit_id": visit_id, "reason": reason}
    payload.update(overrides)
    return payload
