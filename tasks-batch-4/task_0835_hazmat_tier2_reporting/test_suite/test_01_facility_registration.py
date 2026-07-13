"""Facility registration, reads, listing, and emergency-response linkage."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_facility,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_facility_payload,
    make_regulator_headers,
    make_facility_operator_headers,
    register_facility,
)


def test_facility_registration_initializes_status_fields(api):
    """PRD §3.1: "its `compliance_posture` is `COMPLIANT`, its `erp_status` is
    `NONE`, its `version` is 1, and its emergency-response contact fields are empty."

    Design: Corner/entities/facility_create_returns_all_fields
    """
    resp = api.create_facility(create_facility_payload(), make_regulator_headers())
    data = validate_success(resp, expected_status=201)
    assert_facility(data)
    assert data["compliance_posture"] == "COMPLIANT"
    assert data["erp_status"] == "NONE"
    assert data["version"] == 1


def test_facility_registration_missing_required_field_rejected(api):
    """PRD §2.9: "the request body is checked for well-formedness — required fields
    present, enum values valid, numeric amounts non-negative, and an EHS chemical
    carrying its `tpq_lbs` — which fails with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/facility_create_missing_required_field_returns_invalid_request
    """
    payload = create_facility_payload()
    del payload["operator_name"]
    resp = api.create_facility(payload, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_unknown_facility_returns_not_found(api):
    """PRD §2.9: "any facility, chemical, inventory, filing, SDS, release, permit,
    inspection, case, risk-management plan, or path id that does not exist yields
    the corresponding not-found error (`ERR_FACILITY_NOT_FOUND`, ..."

    Design: Corner/entities/get_facility_not_found_returns_404
    """
    resp = api.get_facility(NON_EXISTENT_UUID, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND.value)


def test_list_facilities_returns_pagination_envelope(api):
    """PRD §2.3: "`total_count` reports the total number of records matching the
    filter before pagination, and `has_more` is `true` exactly when records remain
    beyond the current page."

    Design: Corner/entities/list_facilities_pagination_envelope
    """
    register_facility()
    register_facility()
    resp = api.list_facilities(make_regulator_headers())
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["total_count"] >= 2
    assert "has_more" in meta


def test_emergency_response_linkage_activates_and_bumps_version(api):
    """PRD §3.1: "This linkage populates the facility's `erp_contact_name`,
    `erp_contact_phone`, `erp_plan_ref`, and `erp_linked_lepc_district` fields
    respectively, flips `erp_status` from `NONE` to `ACTIVE`, and increments the
    facility's `version` by 1."

    Design: Corner/endpoints/emergency_response_plan_sets_active
    """
    facility = register_facility()
    fac_id = facility["id"]
    assert facility["version"] == 1
    payload = {
        "contact_name": "Jane Doe",
        "contact_phone": "555-0100",
        "plan_ref": "erp://v1",
        "linked_lepc_district": "Harris-LEPC",
    }
    resp = api.link_emergency_response_plan(fac_id, payload, make_facility_operator_headers(fac_id))
    data = validate_success(resp, expected_status=200)
    assert data["erp_status"] == "ACTIVE"
    assert data["version"] == 2
