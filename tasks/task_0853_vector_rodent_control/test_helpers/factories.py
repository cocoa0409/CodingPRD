"""Payload factories — one per record type, input fields only."""

DEFAULTS = {
    "ZONE_NAME": "Riverside",
    "ZONE_CODE": "Z-RIV",
    "POPULATION_DENSITY": 4200,
    "OWNER_NAME": "Dana Ruiz",
    "OWNER_EMAIL": "dana@example.com",
    "OWNER_ADDRESS": "12 Elm St",
    "PARCEL_NUMBER": "APN-1001",
    "ADDRESS_LINE": "12 Elm St",
    "PROPERTY_TYPE": "RESIDENTIAL_MULTI",
    "OFFICER_NAME": "Iris Vega",
    "BADGE_NUMBER": "B-101",
    "CERT_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "COMPLAINT_DESCRIPTION": "Burrows along the alley fence",
    "REQUIRED_ACTIONS": ["REMOVE_HARBORAGE"],
    "STATION_CODE": "BS-01",
}


def create_zone_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ZONE_NAME"],
        "code": DEFAULTS["ZONE_CODE"],
        "population_density_per_sqkm": DEFAULTS["POPULATION_DENSITY"],
    }
    payload.update(overrides)
    return payload


def create_property_owner_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["OWNER_NAME"],
        "email": DEFAULTS["OWNER_EMAIL"],
        "mailing_address": DEFAULTS["OWNER_ADDRESS"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(zone_id, owner_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "owner_id": owner_id,
        "address_line": DEFAULTS["ADDRESS_LINE"],
        "parcel_number": DEFAULTS["PARCEL_NUMBER"],
        "property_type": DEFAULTS["PROPERTY_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_officer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["OFFICER_NAME"],
        "badge_number": DEFAULTS["BADGE_NUMBER"],
        "rank": "FIELD_INSPECTOR",
        "certification_expires_at": DEFAULTS["CERT_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "complaint_type": "HARBORAGE",
        "reporter_type": "RESIDENT",
        "description": DEFAULTS["COMPLAINT_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def triage_payload(severity="HIGH", **overrides) -> dict:
    payload = {"severity": severity}
    payload.update(overrides)
    return payload


def close_complaint_payload(closure_reason="WITHDRAWN", **overrides) -> dict:
    payload = {"closure_reason": closure_reason}
    payload.update(overrides)
    return payload


def create_inspection_payload(kind, officer_id, scheduled_start, scheduled_end,
                              **overrides) -> dict:
    payload = {
        "kind": kind,
        "officer_id": officer_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(harborage_score=4, attractant_score=4,
                              sanitation_score=3, burrow_count=0,
                              **overrides) -> dict:
    payload = {
        "harborage_score": harborage_score,
        "attractant_score": attractant_score,
        "sanitation_score": sanitation_score,
        "burrow_count": burrow_count,
    }
    payload.update(overrides)
    return payload


def complete_inspection_payload(result, **overrides) -> dict:
    payload = {"result": result}
    payload.update(overrides)
    return payload


def create_abatement_order_payload(inspection_id, expected_property_version,
                                   **overrides) -> dict:
    payload = {
        "inspection_id": inspection_id,
        "required_actions": list(DEFAULTS["REQUIRED_ACTIONS"]),
        "expected_property_version": expected_property_version,
    }
    payload.update(overrides)
    return payload


def create_notice_payload(notice_type="ABATEMENT_ORDER",
                          delivery_method="CERTIFIED_MAIL", **overrides) -> dict:
    payload = {"notice_type": notice_type, "delivery_method": delivery_method}
    payload.update(overrides)
    return payload


def service_result_payload(service_outcome="DELIVERED", **overrides) -> dict:
    payload = {"service_outcome": service_outcome}
    payload.update(overrides)
    return payload


def extend_order_payload(extension_days=7, reason="Contractor lead time",
                         **overrides) -> dict:
    payload = {"extension_days": extension_days, "reason": reason}
    payload.update(overrides)
    return payload


def city_abate_payload(actual_labor_hours=4, actual_materials_cents=12000,
                       **overrides) -> dict:
    payload = {
        "actual_labor_hours": actual_labor_hours,
        "actual_materials_cents": actual_materials_cents,
    }
    payload.update(overrides)
    return payload


def create_bait_station_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "station_code": DEFAULTS["STATION_CODE"],
        "bait_type": "BAIT_BLOCK",
    }
    payload.update(overrides)
    return payload


def create_reading_payload(take_pct=30, activity_sign_count=1,
                           station_condition="INTACT", **overrides) -> dict:
    payload = {
        "take_pct": take_pct,
        "activity_sign_count": activity_sign_count,
        "station_condition": station_condition,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(abatement_order_id, expected_abatement_order_version,
                           **overrides) -> dict:
    payload = {
        "abatement_order_id": abatement_order_id,
        "expected_abatement_order_version": expected_abatement_order_version,
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, method="CHECK", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "method": method}
    payload.update(overrides)
    return payload


def void_invoice_payload(void_reason="Owner produced proof of prior abatement",
                         **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload
