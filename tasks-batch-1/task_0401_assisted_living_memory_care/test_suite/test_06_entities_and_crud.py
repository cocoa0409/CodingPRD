"""Entity creation, defaults, required-field and type validation, computed fields,
immutability, not-found handling, and list pagination.

Citations are verbatim from PRD.md §2.x, §3.1, §3.2, §3.9, §3.10.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_facility, assert_administration_record,
    create_facility, create_resident, create_unit, setup_resident_with_med_order,
    NON_EXISTENT_UUID, TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
NURSE = TEST_USERS["nurse_headers"]
CLINICAL = TEST_USERS["clinical_director_headers"]
STAFF = TEST_USERS["staff_headers"]


def test_create_facility_returns_201_with_defaults(api):
    """PRD §3.1: "On creation the facility's `license_status` is set to `ACTIVE` and all four
    computed metrics — `bed_count`, `occupied_bed_count`, `occupancy_rate_bps`, and
    `open_deficiency_count` — start at zero."

    Design: Corner/entities/create_facility_returns_201_with_defaults
    """
    resp = api.create_facility(
        {"name": "Sunrise", "state_code": "CA", "license_number": "CA-100", "care_point_rate_cents": 2000},
        REGISTRAR)
    fac = validate_success(resp, 201)
    assert_facility(fac)
    assert fac["license_status"] == "ACTIVE"
    assert fac["bed_count"] == 0
    assert fac["occupied_bed_count"] == 0
    assert fac["occupancy_rate_bps"] == 0
    assert fac["open_deficiency_count"] == 0
    assert fac["version"] == 1


def test_get_facility_not_found_returns_404(api):
    """PRD §2.5: "if the facility does not exist the response is `ERR_FACILITY_NOT_FOUND`"

    Design: Corner/entities/get_facility_not_found_returns_404
    """
    resp = api.get_facility(NON_EXISTENT_UUID, STAFF)
    validate_error(resp, "ERR_FACILITY_NOT_FOUND", expected_status=404)


def test_create_resident_missing_required_field_returns_invalid_request(api):
    """PRD §3.11: "A malformed body, a missing required field, or a type mismatch is rejected
    with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_resident_missing_required_field_returns_invalid_request
    """
    fac = create_facility()
    resp = api.create_resident({"facility_id": fac["id"], "date_of_birth": "1940-01-01"}, REGISTRAR)
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


def test_resident_stay_type_defaults_standard(api):
    """PRD §3.2: "The `stay_type` is one of `STANDARD` or `RESPITE` and defaults to `STANDARD`"
    PRD §3.2: "A freshly registered resident begins in status `PROSPECT`, with
    `current_care_points` and `open_balance_cents` both zero and `current_care_level` null until
    the first assessment is finalized."

    Design: Corner/entities/resident_stay_type_defaults_standard
    """
    fac = create_facility()
    res = validate_success(api.create_resident(
        {"facility_id": fac["id"], "full_name": "Default Dan", "date_of_birth": "1941-01-01"}, REGISTRAR), 201)
    assert res["stay_type"] == "STANDARD"
    assert res["respite_end_date"] is None
    assert res["status"] == "PROSPECT"


def test_respite_without_end_date_returns_invalid_respite_window(api):
    """PRD §3.2: "Supplying a respite stay without a valid end date, or supplying an end date on
    a standard stay, is rejected with `ERR_INVALID_RESPITE_WINDOW`."

    Design: Corner/entities/respite_without_end_date_returns_invalid_respite_window
    """
    fac = create_facility()
    resp = api.create_resident(
        {"facility_id": fac["id"], "full_name": "Resp Rose", "date_of_birth": "1942-01-01", "stay_type": "RESPITE"},
        REGISTRAR)
    validate_error(resp, "ERR_INVALID_RESPITE_WINDOW", expected_status=422)


def test_assessment_adl_out_of_range_returns_invalid_assessment_input(api):
    """PRD §3.2: "Any ADL score outside 0 through 4, a cognition score outside 0 through 10, or a
    negative behavior-flag count is rejected with `ERR_INVALID_ASSESSMENT_INPUT`."

    Design: Corner/entities/assessment_adl_out_of_range_returns_invalid_assessment_input
    """
    fac = create_facility()
    res = create_resident(fac["id"], full_name="Acuity Al", date_of_birth="1943-01-01")
    resp = api.create_assessment(
        {"resident_id": res["id"], "adl_bathing": 5, "adl_dressing": 1, "adl_toileting": 1,
         "adl_transferring": 1, "adl_eating": 1, "cognition_score": 0, "behavior_flags": 0}, CLINICAL)
    validate_error(resp, "ERR_INVALID_ASSESSMENT_INPUT", expected_status=422)


def test_emar_record_is_immutable_no_version_field(api):
    """PRD §2.4: "The medication administration record is an append-only, immutable audit event:
    each such record carries only an `id` and a `created_at`. It has no `updated_at` and no
    `version`, because once written it is never modified."

    Design: Corner/entities/emar_record_is_immutable_no_version_field
    """
    ctx = setup_resident_with_med_order(schedule_times=["08:00"], is_controlled=False)
    resp = api.record_administration(ctx["order"]["id"], {"scheduled_time": "08:00", "outcome": "GIVEN"}, NURSE)
    rec = validate_success(resp, 201)
    assert_administration_record(rec)
    assert rec["resident_id"] == ctx["resident"]["id"]
    assert rec["outcome"] == "GIVEN"
    assert "version" not in rec
    assert "updated_at" not in rec


def test_list_facilities_pagination_envelope(api):
    """PRD §2.3: "Each list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_facilities_pagination_envelope
    """
    create_facility()
    create_facility()
    data, meta = validate_paginated(api.list_facilities(STAFF))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_incident_requires_state_report_computed_severe(api):
    """PRD §3.9: "On creation the system computes `requires_state_report`, which is true when the
    severity is `SEVERE` or the incident type is `ELOPEMENT` — such incidents are state-reportable
    within twenty-four hours."

    Design: Corner/entities/incident_requires_state_report_computed_severe
    """
    fac = create_facility()
    res = create_resident(fac["id"], full_name="Inc Ivy", date_of_birth="1945-01-01")
    severe = validate_success(api.create_incident_report(
        {"resident_id": res["id"], "incident_type": "FALL", "occurred_at": "2026-03-01T08:00:00Z",
         "severity": "SEVERE"}, NURSE), 201)
    minor = validate_success(api.create_incident_report(
        {"resident_id": res["id"], "incident_type": "FALL", "occurred_at": "2026-03-01T09:00:00Z",
         "severity": "MINOR"}, NURSE), 201)
    assert severe["requires_state_report"] is True
    assert minor["requires_state_report"] is False


def test_create_resident_with_nonexistent_facility_returns_facility_not_found(api):
    """PRD §2.5: "When a create operation references a parent or related row — a `resident_id`, a
    `unit_id`, a `source_assessment_id`, a `supersedes_care_plan_id`, or a `medication_order_id` —
    and the referenced row does not exist, the request is rejected with the corresponding
    resource's not-found error."

    Design: Corner/entities/create_resident_with_nonexistent_facility_returns_facility_not_found
    """
    resp = api.create_resident(
        {"facility_id": NON_EXISTENT_UUID, "full_name": "Orphan", "date_of_birth": "1940-01-01"}, REGISTRAR)
    validate_error(resp, "ERR_FACILITY_NOT_FOUND", expected_status=404)


def test_duplicate_unit_number_returns_conflict(api):
    """PRD §3.1: "The `unit_number` must be unique within the facility among units that are not
    `RETIRED`; a collision is rejected with `ERR_DUPLICATE_UNIT_NUMBER`."

    Design: Corner/entities/duplicate_unit_number_returns_conflict
    """
    fac = create_facility()
    validate_success(api.create_unit(
        fac["id"], {"unit_number": "110", "wing": "ASSISTED_LIVING", "monthly_base_rent_cents": 400000}, REGISTRAR), 201)
    resp = api.create_unit(
        fac["id"], {"unit_number": "110", "wing": "MEMORY_CARE", "monthly_base_rent_cents": 450000}, REGISTRAR)
    validate_error(resp, "ERR_DUPLICATE_UNIT_NUMBER", expected_status=409)
