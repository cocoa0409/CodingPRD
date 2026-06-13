"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying only source:input fields, with sensible
defaults that tests override via **overrides.
"""


def create_customer_payload(**overrides) -> dict:
    """Customer create body. hoa_governed defaults to False."""
    payload = {
        "full_name": "Test Owner",
        "email": "owner@example.com",
        "hoa_governed": False,
    }
    payload.update(overrides)
    return payload


def create_project_payload(customer_id: str, **overrides) -> dict:
    """Project create body. job_type defaults to FENCE."""
    payload = {
        "customer_id": customer_id,
        "site_address": "1 Test Lane",
        "job_type": "FENCE",
    }
    payload.update(overrides)
    return payload


def create_estimate_payload(**overrides) -> dict:
    """Estimate create body. tax_rate_pct is optional (server default 7.25)."""
    payload: dict = {}
    payload.update(overrides)
    return payload


def create_line_item_payload(estimate_id: str, **overrides) -> dict:
    """LineItem create body. accessory and grade_slope_pct are optional."""
    payload = {
        "estimate_id": estimate_id,
        "work_type": "FENCE",
        "material": "CEDAR",
        "style": "PRIVACY",
        "quantity_units": 100,
    }
    payload.update(overrides)
    return payload


def create_site_measure_payload(measured_quantities, **overrides) -> dict:
    """SiteMeasure create body. measured_quantities is a list of
    {line_item_id, measured_units}."""
    payload = {
        "measured_quantities": measured_quantities,
        "property_line_note": "5ft setback respected, no encroachment",
        "setback_ok": True,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(**overrides) -> dict:
    """Permit create body."""
    payload = {
        "permit_type": "FENCE_PERMIT",
        "jurisdiction": "City of Elm",
    }
    payload.update(overrides)
    return payload


def create_hoa_approval_payload(**overrides) -> dict:
    """HoaApproval create body."""
    payload = {
        "architectural_packet_ref": "PKT-1",
    }
    payload.update(overrides)
    return payload


def create_material_order_payload(**overrides) -> dict:
    """MaterialOrder create body. waste_factor_pct is optional (server default 10)."""
    payload = {
        "supplier_name": "Acme",
        "dock_id": "DOCK_1",
        "delivery_window_start": "2026-07-01T08:00:00Z",
        "delivery_window_end": "2026-07-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_crew_booking_payload(**overrides) -> dict:
    """CrewBooking create body."""
    payload = {
        "crew_id": "CREW_1",
        "window_start": "2026-07-20T08:00:00Z",
        "window_end": "2026-07-20T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_change_order_payload(project_id: str, line_item_id: str,
                                expected_project_version: int, **overrides) -> dict:
    """ChangeOrder create body. new_quantity_units / new_accessory optional."""
    payload = {
        "project_id": project_id,
        "line_item_id": line_item_id,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload
