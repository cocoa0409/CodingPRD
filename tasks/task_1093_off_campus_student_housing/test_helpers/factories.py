"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only `source: input` fields appear here.
"""

DEFAULTS = {
    "UNI_NAME": "State University",
    "UNI_CODE": "SU",
    "AY_START": "2026-08-15",
    "AY_END": "2027-05-15",
    "PARTNER_ADMIN": "uni-admin-su",
    "PROP_NAME": "Maple Commons",
    "ADDRESS": "12 Maple St",
    "DISTANCE": 800,
    "RENT": 90000,
    "TERM_START": "2026-08-15",
    "TERM_END": "2027-08-01",
}


def create_university_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["UNI_NAME"],
        "code": DEFAULTS["UNI_CODE"],
        "partner_tier": "PREFERRED",
        "verification_required": True,
        "academic_year_start_date": DEFAULTS["AY_START"],
        "academic_year_end_date": DEFAULTS["AY_END"],
        "partner_admin_user_id": DEFAULTS["PARTNER_ADMIN"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(university_id, **overrides) -> dict:
    payload = {
        "university_id": university_id,
        "name": DEFAULTS["PROP_NAME"],
        "address_line": DEFAULTS["ADDRESS"],
        "distance_to_campus_m": DEFAULTS["DISTANCE"],
    }
    payload.update(overrides)
    return payload


def create_unit_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "unit_number": "101",
        "floorplan_code": "4x2",
        "bedroom_count": 4,
        "bathroom_count": 2,
        "bed_labels": ["A", "B", "C", "D"],
        "base_rent_cents_per_bed_monthly": DEFAULTS["RENT"],
    }
    payload.update(overrides)
    return payload


def create_student_payload(university_id, email, **overrides) -> dict:
    payload = {
        "university_id": university_id,
        "full_name": "Test Student",
        "email": email,
        "credit_score_band": "GOOD",
        "cleanliness_level": 3,
        "noise_tolerance": 3,
        "sleep_schedule": "EARLY",
        "smoker": False,
    }
    payload.update(overrides)
    return payload


def create_roommate_group_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "name": "Test Group",
        "required_size": 2,
    }
    payload.update(overrides)
    return payload


def create_lease_payload(student_id, unit_id, bed_label="A", **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "unit_id": unit_id,
        "bed_label": bed_label,
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
        "installment_count": 10,
    }
    payload.update(overrides)
    return payload


def create_guarantor_application_payload(lease_id, income_cents, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "guarantor_full_name": "Pat Lead",
        "guarantor_annual_income_cents": income_cents,
        "relationship": "PARENT",
    }
    payload.update(overrides)
    return payload


def create_sublet_payload(lease_id, subtenant_student_id, start_date, end_date,
                          sublet_rent_cents=85000, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "subtenant_student_id": subtenant_student_id,
        "start_date": start_date,
        "end_date": end_date,
        "sublet_rent_cents": sublet_rent_cents,
    }
    payload.update(overrides)
    return payload


def create_amenity_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "name": "Lot A Parking",
        "amenity_type": "PARKING",
        "capacity": 2,
        "monthly_fee_cents": 12000,
    }
    payload.update(overrides)
    return payload


def create_amenity_assignment_payload(amenity_id, lease_id, start_date, end_date,
                                      **overrides) -> dict:
    payload = {
        "amenity_id": amenity_id,
        "lease_id": lease_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def create_payout_payload(property_id, period_start_date, period_end_date,
                          expected_property_version, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "expected_property_version": expected_property_version,
    }
    payload.update(overrides)
    return payload
