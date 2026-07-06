"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. System- and
computed-source fields are never sent.
"""

DEFAULTS = {
    "OWNER_NAME": "Ivy Owner",
    "MAILING_ADDRESS": "1 Elm St",
    "CONTACT_EMAIL": "ivy@x.com",
    "SITE_ADDRESS": "10 Maple Ave",
    "LATITUDE": 40.1,
    "LONGITUDE": -74.1,
    "CREW_NAME": "Crew A",
    "MATERIAL_NAME": "Gray Paint",
    "UNIT_COST_CENTS": 1200,
    "QUANTITY_AVAILABLE": 10.0,
    "WINDOW_START": "2026-03-05T09:00:00Z",
    "WINDOW_END": "2026-03-05T12:00:00Z",
}


def create_property_owner_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["OWNER_NAME"],
        "mailing_address": DEFAULTS["MAILING_ADDRESS"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_site_payload(ownership_type="PUBLIC", property_owner_id=None, **overrides) -> dict:
    payload = {
        "ownership_type": ownership_type,
        "address": DEFAULTS["SITE_ADDRESS"],
        "latitude": DEFAULTS["LATITUDE"],
        "longitude": DEFAULTS["LONGITUDE"],
    }
    if property_owner_id is not None:
        payload["property_owner_id"] = property_owner_id
    payload.update(overrides)
    return payload


def create_report_payload(site_id, severity="HIGH", surface_type="WALL",
                          reported_via="PHONE_311", description="tag on wall",
                          **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "reported_via": reported_via,
        "surface_type": surface_type,
        "severity": severity,
        "description": description,
    }
    payload.update(overrides)
    return payload


def create_crew_payload(name=None, crew_type="CITY", is_offensive_certified=True,
                        **overrides) -> dict:
    payload = {
        "name": name or DEFAULTS["CREW_NAME"],
        "crew_type": crew_type,
        "is_offensive_certified": is_offensive_certified,
    }
    payload.update(overrides)
    return payload


def create_material_payload(name=None, category="PAINT", unit="LITERS",
                            unit_cost_cents=None, quantity_available=None,
                            **overrides) -> dict:
    payload = {
        "name": name or DEFAULTS["MATERIAL_NAME"],
        "category": category,
        "unit": unit,
        "unit_cost_cents": unit_cost_cents if unit_cost_cents is not None
        else DEFAULTS["UNIT_COST_CENTS"],
        "quantity_available": quantity_available if quantity_available is not None
        else DEFAULTS["QUANTITY_AVAILABLE"],
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(report_id, crew_id, method="PAINT_OVER",
                              estimated_labor_hours=2.0, material_lines=None,
                              scheduled_start=None, scheduled_end=None,
                              **overrides) -> dict:
    payload = {
        "report_id": report_id,
        "crew_id": crew_id,
        "scheduled_start": scheduled_start or DEFAULTS["WINDOW_START"],
        "scheduled_end": scheduled_end or DEFAULTS["WINDOW_END"],
        "method": method,
        "estimated_labor_hours": estimated_labor_hours,
    }
    if material_lines is not None:
        payload["material_lines"] = material_lines
    payload.update(overrides)
    return payload


def create_photo_payload(phase="BEFORE", url="http://p/photo.jpg", **overrides) -> dict:
    payload = {"phase": phase, "url": url}
    payload.update(overrides)
    return payload


def create_notice_payload(notice_type="COST_RECOVERY_NOTICE", cure_days=30,
                          expected_site_version=None, cost_recovery_id=None,
                          **overrides) -> dict:
    payload = {
        "notice_type": notice_type,
        "cure_days": cure_days,
        "expected_site_version": expected_site_version,
    }
    if cost_recovery_id is not None:
        payload["cost_recovery_id"] = cost_recovery_id
    payload.update(overrides)
    return payload
