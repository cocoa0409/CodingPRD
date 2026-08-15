"""Network baseline: facility/unit/technologist creation, envelope and pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_facility,
    build_user_headers,
    create_facility,
    create_facility_payload,
    create_technologist,
    create_unit,
    create_unit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


def test_facility_creation_echoes_fields_and_system_fields(api):
    """PRD §2.5: "Newly created resources begin at `version` 1."
    PRD §3.1: "An `OperationsDirector` registers a `ContractedFacility` with a
    `name`, the street `address` of the pad site, the `supported_modalities`
    the facility hosts (any of `MRI`, `CT`, `PET`), and the electrical pad
    specification: `pad_amps_available` of shore-power amperage, the
    `pad_voltage` supply, and `pad_level_tolerance_deg`".

    Design: Corner/entities/facility_creation_echoes_fields_and_system_fields
    """
    payload = create_facility_payload(
        name="Hospital A", address="1 A St", supported_modalities=["CT", "MRI"]
    )
    resp = api.create_facility(payload, OPS)
    data = validate_success(resp, 201)
    assert_facility(data)
    assert data["version"] == 1, f"New facility version must be 1, got {data['version']}"
    assert data["name"] == "Hospital A"
    assert data["pad_amps_available"] == 150
    assert data["supported_modalities"] == ["CT", "MRI"]


def test_facility_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "Independently of this ladder, any request with a missing
    required field, a type mismatch, or an enum value outside the declared set
    is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/facility_missing_required_field_returns_invalid_request
    """
    payload = {
        "name": "Hospital A",
        "address": "1 A St",
        "supported_modalities": ["CT"],
        "pad_voltage": 480,
        "pad_level_tolerance_deg": 2.0,
    }
    resp = api.create_facility(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_unit_invalid_modality_enum_rejected(api):
    """PRD §3.1: "A `MobileImagingUnit` is registered with a unique operator
    `unit_code`, its `modality` (one of `MRI`, `CT`, or `PET`)".
    PRD §2.8: "Independently of this ladder, any request with a missing
    required field, a type mismatch, or an enum value outside the declared set
    is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/unit_invalid_modality_enum_rejected
    """
    payload = create_unit_payload(modality="XRAY")
    resp = api.create_unit(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_technologist_computed_dose_defaults_zero(api):
    """PRD §3.3: "Two computed exposure fields ride on the record:
    `current_day_dose_msv`, the sum of that technologist's recorded doses on
    appointments whose site day's `service_date` equals the logical clock date,
    and `monthly_dose_msv`, the same sum over the logical clock's calendar
    month. Both start at zero and are recomputed as dose records arrive (§3.7)."

    Design: Corner/entities/technologist_computed_dose_defaults_zero
    """
    tech = create_technologist()
    resp = api.get_technologist(tech["id"], OPS)
    data = validate_success(resp)
    assert data["current_day_dose_msv"] == 0, (
        f"Fresh technologist current_day_dose_msv must be 0, got {data['current_day_dose_msv']}"
    )
    assert data["monthly_dose_msv"] == 0, (
        f"Fresh technologist monthly_dose_msv must be 0, got {data['monthly_dose_msv']}"
    )


def test_list_facilities_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum
    of 100. The `offset` parameter states how many items to skip and defaults
    to 0."

    Design: Corner/endpoints/list_facilities_pagination_defaults
    """
    for i in range(12):
        create_facility(name=f"F{i + 1:02d}", address="a")

    data, meta = validate_paginated(api.list_facilities(OPS))
    assert len(data) == 10, f"Default page must hold 10 items, got {len(data)}"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(api.list_facilities(OPS, params={"limit": 5, "offset": 10}))
    assert len(data2) == 2, f"limit=5&offset=10 must hold 2 items, got {len(data2)}"
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False


def test_success_envelope_shape_on_get(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/success_envelope_shape_on_get
    """
    unit = create_unit()
    resp = api.get_unit(unit["id"], OPS)
    body = resp.json()
    assert body["response_type"] == "object", (
        f"Single-resource GET must have response_type 'object', got {body['response_type']}"
    )
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    data = validate_success(resp)
    assert data["unit_code"] == "MIU-01"
