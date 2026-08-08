"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ZONING_DISTRICT": "COMMERCIAL",
    "MAX_SIGN_AREA_SQFT": 200,
    "MAX_HEIGHT_FT": 50,
    "MIN_SETBACK_FT": 10,
    "ALLOWED_ILLUMINATION": "EXTERNAL",
    "MAX_SIGNS": 5,
    "APPLICANT_NAME": "Test Applicant",
    "APPLICANT_EMAIL": "applicant@example.com",
    "INSPECTOR_NAME": "Test Inspector",
    "STRUCTURE_HEIGHT_FT": 40,
}

_email_seq = [0]


def _unique_email(prefix="applicant"):
    _email_seq[0] += 1
    return f"{prefix}{_email_seq[0]}@example.com"


def create_parcel_payload(**overrides) -> dict:
    defaults = {
        "zoning_district": DEFAULTS["ZONING_DISTRICT"],
        "max_sign_area_sqft": DEFAULTS["MAX_SIGN_AREA_SQFT"],
        "max_height_ft": DEFAULTS["MAX_HEIGHT_FT"],
        "min_setback_ft": DEFAULTS["MIN_SETBACK_FT"],
        "allowed_illumination": DEFAULTS["ALLOWED_ILLUMINATION"],
        "max_signs": DEFAULTS["MAX_SIGNS"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["APPLICANT_NAME"],
        "contact_email": _unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["INSPECTOR_NAME"]}
    defaults.update(overrides)
    return defaults


def create_application_payload(parcel_id, applicant_id, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "applicant_id": applicant_id,
        "sign_type": "WALL",
        "requested_area_sqft": 40,
        "requested_height_ft": 20,
        "requested_setback_ft": 15,
        "requested_illumination": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_variance_payload(application_id, kind, requested_value=None,
                            justification="hardship", **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "kind": kind,
        "justification": justification,
    }
    if requested_value is not None:
        defaults["requested_value"] = requested_value
    defaults.update(overrides)
    return defaults


def create_billboard_payload(parcel_id, operator_id, face_count=1,
                             is_digital=False, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "operator_id": operator_id,
        "face_count": face_count,
        "is_digital": is_digital,
        "structure_height_ft": DEFAULTS["STRUCTURE_HEIGHT_FT"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(billboard_id, expected_billboard_version, start_date,
                         end_date, lessee_name="Ad Buyer", **overrides) -> dict:
    defaults = {
        "billboard_id": billboard_id,
        "lessee_name": lessee_name,
        "start_date": start_date,
        "end_date": end_date,
        "expected_billboard_version": expected_billboard_version,
    }
    defaults.update(overrides)
    return defaults


def create_non_conforming_payload(parcel_id, original_value_cents=1000000,
                                  amortization_period_years=5,
                                  description="legacy sign", **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "description": description,
        "original_value_cents": original_value_cents,
        "amortization_period_years": amortization_period_years,
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(parcel_id, kind="NO_PERMIT", permit_id=None,
                             **overrides) -> dict:
    defaults = {"parcel_id": parcel_id, "kind": kind}
    if permit_id is not None:
        defaults["permit_id"] = permit_id
    defaults.update(overrides)
    return defaults


def create_inspection_payload(permit_id, inspector_id, scheduled_start,
                              scheduled_end, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "inspector_id": inspector_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults
