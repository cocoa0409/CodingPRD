"""Entity creation, retrieval, defaults, computed/system field ownership, type
constraints, immutability, and parent-FK integrity.

Queue B (Corner): entities section instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_epi_headers,
    ApiErrorId,
    create_program_payload,
    create_jurisdiction_payload,
    create_case_payload,
    create_contact_payload,
    create_monitoring_period_payload,
    assert_exposure_event,
)
from test_helpers import fixtures as fx

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_program_returns_201_with_defaulted_clock(api):
    """PRD §3.1: "Creating a `SurveillanceProgram` requires a `name` and accepts an optional
    `description`; on creation the program's `current_date` is initialized to
    `2026-01-01T00:00:00.000Z`."

    Design: Corner/entities/create_program_returns_201_with_defaulted_clock
    """
    res = api.create_program(create_program_payload(name="State PH"), fx.ADMIN)
    data = validate_success(res, expected_status=201)
    assert data["name"] == "State PH"
    assert data["current_date"] == "2026-01-01T00:00:00.000Z", data["current_date"]
    assert data["version"] == 1


def test_get_program_returns_stored_entity(api):
    """PRD §2.4: "Each `SurveillanceProgram` owns a deterministic surveillance clock exposed as
    `current_date`, a UTC date-time that defaults to `2026-01-01T00:00:00.000Z` when the program
    is created and advances only through the explicit clock-setting capability."

    Design: Corner/entities/get_program_returns_stored_entity
    """
    program = fx.create_program(name="State PH")
    data = validate_success(api.get_program(program["id"], make_epi_headers()))
    assert data["name"] == "State PH"
    assert data["current_date"] == "2026-01-01T00:00:00.000Z"


def test_get_program_nonexistent_returns_program_not_found(api):
    """PRD §2.5: "an unknown program, jurisdiction, condition, case, contact, lab result,
    monitoring period, transfer, cluster, or export surfaces the matching not-found error
    (`ERR_PROGRAM_NOT_FOUND`, ...)."

    Design: Corner/entities/get_program_nonexistent_returns_program_not_found
    """
    res = api.get_program(MISSING_UUID, make_epi_headers())
    validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


def test_create_jurisdiction_missing_fips_code_returns_invalid_request(api):
    """PRD §3.1: "A `Jurisdiction` is created with a `name` and a five-digit county `fips_code`".
    PRD §3.13: "A malformed body, a missing required field, or any such out-of-domain input is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_jurisdiction_missing_fips_code_returns_invalid_request
    """
    program = fx.create_program()
    res = api.create_jurisdiction({"program_id": program["id"], "name": "County 1"}, fx.ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_jurisdiction_defaults_active_monitoring_count_zero(api):
    """PRD §3.1: "Each jurisdiction begins with its `active_monitoring_count` at 0."

    Design: Corner/entities/create_jurisdiction_defaults_active_monitoring_count_zero
    """
    program = fx.create_program()
    res = api.create_jurisdiction(create_jurisdiction_payload(program["id"]), fx.ADMIN)
    data = validate_success(res, expected_status=201)
    assert data["active_monitoring_count"] == 0


def test_create_case_client_computed_fields_ignored(api):
    """PRD §3.3: "A new case begins in `OPEN` with `classification` `SUSPECT`,
    `completeness_score` 0, `contact_count` 0, and `linked_positive_count` 0."

    Design: Corner/entities/create_case_client_computed_classification_input_ignored
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    res = api.create_case(
        create_case_payload(
            program["id"], j, patient_reference="PT-Z",
            classification="CONFIRMED", completeness_score=99,
        ),
        make_investigator_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["classification"] == "SUSPECT"
    assert data["status"] == "OPEN"
    assert data["completeness_score"] == 0
    assert data["contact_count"] == 0


def test_create_case_system_fields_client_input_ignored(api):
    """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a UUID".
    PRD §3.3: "A new case begins in `OPEN`".
    PRD §2.4: "`version` (integer): a system-managed counter that starts at its initial value".

    Design: Corner/entities/create_case_system_fields_client_input_ignored
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    bogus_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    res = api.create_case(
        create_case_payload(
            program["id"], j, patient_reference="PT-SYS", status="CLOSED", id=bogus_id,
        ),
        make_investigator_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["status"] == "OPEN"
    assert data["version"] == 1
    assert data["id"] != bogus_id


def test_create_contact_invalid_exposure_setting_enum_returns_invalid_request(api):
    """PRD §3.6: "the `exposure_setting` (one of `HOUSEHOLD`, `HEALTHCARE`, `WORKPLACE`,
    `SOCIAL`, or `COMMUNITY`)".
    PRD §3.13: "enum-typed fields must carry a recognized member, ... A malformed body, a
    missing required field, or any such out-of-domain input is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_contact_invalid_exposure_setting_enum_returns_invalid_request
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    res = api.create_contact(
        create_contact_payload(
            program["id"], ci["id"], j, contact_reference="K-BADENUM", exposure_setting="PARTY",
        ),
        make_tracer_headers(j),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_contact_negative_proximity_meters_returns_invalid_request(api):
    """PRD §3.6: "the closest `proximity_meters` during exposure (a non-negative number)".
    PRD §3.13: "numeric fields such as `proximity_meters` and `cumulative_exposure_minutes` and
    the condition's day-counts must be non-negative ... is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_contact_negative_proximity_meters_returns_invalid_request
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    res = api.create_contact(
        create_contact_payload(
            program["id"], ci["id"], j, contact_reference="K-NEG", proximity_meters=-1,
        ),
        make_tracer_headers(j),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_monitoring_period_end_before_start_returns_invalid_request(api):
    """PRD §3.8: "an inclusive `start_date`, and an inclusive `end_date` that must be on or
    after `start_date`."
    PRD §3.13: "a monitoring period's `end_date` must be at or after its `start_date` ... is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/monitoring_period_end_before_start_returns_invalid_request
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    kb = fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-B")
    res = api.create_monitoring_period(
        kb["id"],
        create_monitoring_period_payload("2026-03-29T00:00:00.000Z", "2026-03-16T00:00:00.000Z"),
        make_tracer_headers(j),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_exposure_event_immutable_no_version_field(api):
    """PRD §2.4: "An `ExposureEvent` is an append-only encounter record: it carries only an `id`
    and a `created_at`. It has no `updated_at` and no `version`, because it is never modified
    after creation."
    PRD §3.10: "the event's `program_id` and `case_id` are copied from the contact at creation
    (the `case_id` derived from the contact's `source_case_id`)."

    Design: Corner/entities/exposure_event_immutable_no_version_field
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    kee = fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-EE")
    res = api.create_exposure_event(
        kee["id"], {"encounter_date": "2026-03-15T00:00:00.000Z", "setting_note": "kitchen"},
        make_tracer_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["contact_id"] == kee["id"]
    assert data["case_id"] == ci["id"]
    assert_exposure_event(data)


def test_create_case_wrong_parent_program_for_jurisdiction_returns_not_found(api):
    """PRD §2.5: "On any create or resolve operation, the foreign keys it accepts ... must each
    reference an existing row within the same program; an unresolved reference yields the
    corresponding not-found error."

    Design: Corner/entities/create_case_wrong_parent_program_for_jurisdiction_returns_not_found
    """
    p1 = fx.create_program(name="State PH 1")
    j1 = fx.create_jurisdiction(p1["id"], fips_code="06001")
    p2 = fx.create_program(name="State PH 2")
    fx.create_condition(p2["id"])
    # Open a case in P2 but naming jurisdiction j1 (belongs to P1) -> jurisdiction FK unresolved in P2.
    res = api.create_case(
        create_case_payload(p2["id"], j1["id"], patient_reference="PT-XP"),
        make_investigator_headers(j1["id"]),
    )
    validate_error(res, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value)
