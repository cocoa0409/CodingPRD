"""Payload factories — one per resource, input fields only."""

DEFAULTS = {
    "OPERATOR_LEGAL_NAME": "Blue Lagoon Aquatics",
    "OPERATOR_CONTACT_EMAIL": "ops@bluelagoon.example",
    "FACILITY_NAME": "Main Pool",
    "FACILITY_CLASS": "CLASS_B_PUBLIC",
    "SURFACE_AREA_SQFT": 1200,
    "WATER_VOLUME_GALLONS": 60000,
    "MAX_DEPTH_FEET": 10,
    "DRAIN_COUNT": 2,
    "TERM_START_DATE": "2026-05-01",
    "SCHEDULED_START_AT": "2026-05-01T09:00:00Z",
    "SCHEDULED_END_AT": "2026-05-01T11:00:00Z",
    "SAMPLED_AT": "2026-05-01T00:00:00Z",
    "STAFF_REF": "LG-001",
    "STAFF_NAME": "Ana Ruiz",
    "CERTIFICATION_EXPIRES_ON": "2026-12-31",
    "SHIFT_START_AT": "2026-05-02T08:00:00Z",
    "SHIFT_END_AT": "2026-05-02T16:00:00Z",
    "DRAIN_COVER_MODEL": "AquaSafe VGB-12",
    "EFFECTIVE_ON": "2026-05-01",
}


def create_operator_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["OPERATOR_LEGAL_NAME"],
        "contact_email": DEFAULTS["OPERATOR_CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_facility_payload(operator_id: str, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "name": DEFAULTS["FACILITY_NAME"],
        "facility_class": DEFAULTS["FACILITY_CLASS"],
        "surface_area_sqft": DEFAULTS["SURFACE_AREA_SQFT"],
        "water_volume_gallons": DEFAULTS["WATER_VOLUME_GALLONS"],
        "max_depth_feet": DEFAULTS["MAX_DEPTH_FEET"],
        "drain_count": DEFAULTS["DRAIN_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_spa_facility_payload(operator_id: str, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "name": "Rooftop Spa",
        "facility_class": "SPA",
        "surface_area_sqft": 400,
        "water_volume_gallons": 900,
        "max_depth_feet": 4,
        "drain_count": 2,
    }
    payload.update(overrides)
    return payload


def create_plan_review_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "project_type": "NEW_CONSTRUCTION",
        "drawing_reference": "DR-2026-014",
    }
    payload.update(overrides)
    return payload


def create_permit_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "permit_type": "ANNUAL",
        "term_start_date": DEFAULTS["TERM_START_DATE"],
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "inspection_type": "ROUTINE",
        "scheduled_start_at": DEFAULTS["SCHEDULED_START_AT"],
        "scheduled_end_at": DEFAULTS["SCHEDULED_END_AT"],
    }
    payload.update(overrides)
    return payload


def create_violation_payload(**overrides) -> dict:
    payload = {
        "code": "WQ-101",
        "severity": "CRITICAL",
        "description": "Free chlorine below minimum",
        "corrected_on_site": False,
    }
    payload.update(overrides)
    return payload


def create_water_reading_payload(**overrides) -> dict:
    """An in-range pool reading by default."""
    payload = {
        "sampled_at": DEFAULTS["SAMPLED_AT"],
        "source": "OPERATOR_LOG",
        "free_chlorine_ppm": 2.5,
        "combined_chloramine_ppm": 0.1,
        "ph": 7.4,
        "water_temp_f": 82.0,
    }
    payload.update(overrides)
    return payload


def create_closure_order_payload(facility_id: str, expected_facility_version: int,
                                 **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "closure_reason": "CHEMICAL",
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def create_staff_assignment_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "staff_ref": DEFAULTS["STAFF_REF"],
        "staff_name": DEFAULTS["STAFF_NAME"],
        "role_type": "LIFEGUARD",
        "certification_expires_on": DEFAULTS["CERTIFICATION_EXPIRES_ON"],
        "shift_start_at": DEFAULTS["SHIFT_START_AT"],
        "shift_end_at": DEFAULTS["SHIFT_END_AT"],
    }
    payload.update(overrides)
    return payload


def create_signage_payload(signage_type: str, **overrides) -> dict:
    payload = {
        "artifact_type": "SIGNAGE",
        "effective_on": DEFAULTS["EFFECTIVE_ON"],
        "signage_type": signage_type,
    }
    payload.update(overrides)
    return payload


def create_drain_certification_payload(sva_system_type: str = "MULTIPLE_MAIN_DRAINS",
                                       **overrides) -> dict:
    payload = {
        "artifact_type": "DRAIN_CERTIFICATION",
        "effective_on": DEFAULTS["EFFECTIVE_ON"],
        "drain_cover_model": DEFAULTS["DRAIN_COVER_MODEL"],
        "sva_system_type": sva_system_type,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "complaint_type": "WATER_QUALITY",
        "narrative": "Water was cloudy all weekend",
    }
    payload.update(overrides)
    return payload


def create_rwi_complaint_payload(facility_id: str, illness_case_count: int,
                                 symptom_onset_date: str = "2026-04-21",
                                 **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "complaint_type": "RWI_ILLNESS",
        "narrative": "Swimmers reported illness after the weekend",
        "symptom_onset_date": symptom_onset_date,
        "illness_case_count": illness_case_count,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
