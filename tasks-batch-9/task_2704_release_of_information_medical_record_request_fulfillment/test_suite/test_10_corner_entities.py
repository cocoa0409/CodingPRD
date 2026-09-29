"""Entity-level corners: envelopes, declared defaults, server-owned fields and the
leaner append-only rows."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    Instant,
    assert_common_fields,
    assert_created_only_fields,
    assert_envelope,
    assert_error_envelope,
    assert_facility_money,
    assert_line,
    assert_line_sequence_contiguous,
    assert_no_line_type,
    assert_pagination_meta,
)
from test_helpers.constants import DEFAULT_SENSITIVE_CATEGORIES
from test_helpers.test_users import ANALYST_1, INTAKE_1, PLATFORM_ADMIN


def test_a_registered_fee_schedule_comes_back_in_the_full_success_envelope(api):
    """201, response_type object, every input echoed, version 1 and created_at == updated_at.

    PRD: "Most resources also carry three further common properties: `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first persisted; `updated_at`, the same format, refreshed on every mutation of that resource; and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource."

    Design: Corner/entities/state_fee_rule_created_with_full_success_envelope
    """
    fx.set_clock(api)

    response = api.create_state_fee_rule(f.state_fee_rule_payload(), PLATFORM_ADMIN)

    rule = assert_envelope(response, 201, "object")
    assert_common_fields(rule, expected_version=1)
    assert rule["state_code"] == "CA"
    assert rule["tier1_page_limit"] == 25
    assert rule["tier1_per_page_millicents"] == 27500
    assert rule["penalty_cap_cents"] == 25000
    assert rule["fee_forfeiture_on_late"] is True
    assert rule["created_at"] == rule["updated_at"]
    assert rule["created_at"].startswith("2026-08-01T00:00:00")


def test_a_facility_read_returns_the_stored_configuration_and_zeroed_ledgers(api):
    """GET echoes the onboarding inputs, defaults status to ACTIVE and leaves version at 1.

    PRD: "Four ledger fields on a facility are computed rather than supplied, and all four initialise to 0 when the facility is onboarded."

    Design: Corner/entities/facility_retrieval_returns_stored_configuration
    """
    fx.set_clock(api)
    rule = fx.make_fee_rule(api)
    created = fx.make_facility(
        api, rule["id"], legacy_gateway_job_minutes=45, legacy_gateway_buffer_minutes=5
    )

    facility = validate_success(api.get_facility(created["id"], PLATFORM_ADMIN), 200)

    assert facility["id"] == created["id"]
    assert facility["name"] == "Bay Regional Health"
    assert facility["state_fee_rule_id"] == rule["id"]
    assert facility["legacy_gateway_job_minutes"] == 45
    assert facility["legacy_gateway_buffer_minutes"] == 5
    assert facility["status"] == "ACTIVE"
    assert_facility_money(facility, receivable=0, collected=0, written_off=0)
    assert facility["penalty_exposure_cents"] == 0
    assert facility["version"] == 1


def _facility_with_three_patients(api):
    """One facility holding three patients, registered in a known order."""
    world = fx.base_world(api)
    second = fx.make_patient(api, world["facility_id"], mrn="MRN-SECOND")
    third = fx.make_patient(api, world["facility_id"], mrn="MRN-THIRD")
    return world, [world["patient_id"], second["id"], third["id"]]


def test_the_patient_listing_reports_limit_offset_total_count_and_has_more(api):
    """Three rows read two at a time: total_count holds at 3 while has_more flips.

    PRD: "For list responses the `meta` object carries `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of rows matching the filter before pagination), and `has_more` (true when rows remain beyond this page)."

    Design: Corner/entities/patients_listing_paginates_with_total_count_and_has_more
    """
    world, patient_ids = _facility_with_three_patients(api)
    query = {"facility_id": world["facility_id"], "limit": 2}

    first_response = api.list_patients(PLATFORM_ADMIN, dict(query, offset=0))
    assert first_response.json()["response_type"] == "array"
    page_1, meta_1 = validate_paginated(first_response)
    page_2, meta_2 = validate_paginated(api.list_patients(PLATFORM_ADMIN, dict(query, offset=2)))

    assert len(page_1) == 2
    assert meta_1["limit"] == 2 and meta_1["offset"] == 0
    assert_pagination_meta(meta_1, total_count=3, has_more=True)
    assert len(page_2) == 1
    assert meta_2["limit"] == 2 and meta_2["offset"] == 2
    assert_pagination_meta(meta_2, total_count=3, has_more=False)

    seen = [row["id"] for row in page_1] + [row["id"] for row in page_2]
    assert len(seen) == len(set(seen))
    assert sorted(seen) == sorted(patient_ids)


def test_the_mrn_filter_narrows_the_patient_listing_to_a_single_row(api):
    """total_count counts the rows matching the filter, not the rows in the table.

    PRD: "Patients may be listed with optional `facility_id` and `mrn` filters."

    Design: Corner/entities/patients_listing_paginates_with_total_count_and_has_more
    """
    world, patient_ids = _facility_with_three_patients(api)

    rows, meta = validate_paginated(
        api.list_patients(
            PLATFORM_ADMIN, {"facility_id": world["facility_id"], "mrn": "MRN-SECOND", "limit": 2}
        )
    )

    assert len(rows) == 1
    assert rows[0]["id"] == patient_ids[1]
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_a_patient_read_on_an_unknown_identifier_is_a_bare_not_found_envelope(api):
    """404 with the collection's own code, and no resource fields smuggled into data.

    PRD: "When a route carries a resource identifier and no entity of the addressed collection has that identifier, the call is rejected 404 with the collection's own code: `ERR_FACILITY_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_REQUESTER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_DENIAL_NOT_FOUND` or `ERR_AMENDMENT_NOT_FOUND`."

    Design: Corner/entities/patient_get_with_unknown_id_returns_not_found
    """
    fx.base_world(api)

    response = api.get_patient(NON_EXISTENT_UUID, PLATFORM_ADMIN)

    data = assert_error_envelope(response, e.ERR_PATIENT_NOT_FOUND, 404)
    assert "id" not in data
    assert "version" not in data
    assert "created_at" not in data


def test_a_request_without_a_delivery_format_is_a_schema_rejection(api):
    """delivery_format has no default, so its absence is caught at position 4 of the pipeline.

    PRD: "Body schema validation applies to every write endpoint and covers six failure shapes, all of which report `ERR_INVALID_REQUEST` (HTTP 400): a required field is missing; an enum-typed value falls outside its declared set; a numeric field arrives negative where the field is declared as zero or greater; a string exceeds its declared length bound; a datetime is not a valid ISO 8601 UTC instant; or a record segment declares `source_system` as `LEGACY_ARCHIVE` without a `legacy_job_start_at`, or declares any other source system while supplying one."

    Design: Corner/entities/request_create_missing_delivery_format_rejected
    """
    world = fx.third_party_world(api)
    payload = f.third_party_request_payload(
        world["facility_id"], world["patient_id"], world["requester_id"], world["authorization_id"]
    )
    del payload["delivery_format"]

    validate_error(api.create_request(payload, INTAKE_1), e.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_requests(INTAKE_1, {"facility_id": world["facility_id"], "limit": 10})
    )
    assert meta["total_count"] == 0


def test_an_onboarding_that_omits_every_option_lands_on_the_declared_defaults(api):
    """The segregation list defaults to the seven protected categories, not to an empty list.

    PRD: "The remaining facility inputs are optional and default as follows: `legacy_archive_enabled` defaults to false, meaning no legacy-archive compilation task may be opened against the facility; `legacy_retrieval_surcharge_cents` defaults to 0; `legacy_gateway_job_minutes` defaults to 30 and must be at least 1; `legacy_gateway_buffer_minutes` defaults to 10 and may be 0; and `sensitive_categories_requiring_specific_authorization` defaults to the full protected set `BEHAVIORAL_HEALTH`, `SUD_PART2`, `HIV`, `GENETIC`, `REPRODUCTIVE_HEALTH`, `MINOR_CONFIDENTIAL` and `PSYCHOTHERAPY_NOTES`."

    Design: Corner/entities/facility_create_applies_declared_defaults
    """
    fx.set_clock(api)
    rule = fx.make_fee_rule(api)

    facility = validate_success(
        api.create_facility(
            {"name": "Bay Regional Health", "state_fee_rule_id": rule["id"]}, PLATFORM_ADMIN
        ),
        201,
    )

    assert facility["legacy_archive_enabled"] is False
    assert facility["legacy_retrieval_surcharge_cents"] == 0
    assert facility["legacy_gateway_job_minutes"] == 30
    assert facility["legacy_gateway_buffer_minutes"] == 10
    assert len(facility["sensitive_categories_requiring_specific_authorization"]) == 7
    assert facility["sensitive_categories_requiring_specific_authorization"] == (
        DEFAULT_SENSITIVE_CATEGORIES
    )
    assert facility["status"] == "ACTIVE"
    assert facility["version"] == 1


def test_the_server_owns_the_arrival_anchor_the_deadline_and_the_intake_user(api):
    """Client-supplied values for computed and system fields are discarded.

    PRD: "On success the system stamps `received_at` with the current logical clock — this is the statutory clock's arrival anchor — records `intake_user_id` as the creating `X-User-ID`, sets `fulfillment_status` to `INTAKE_REVIEW` and `billing_status` to `PENDING_INVOICE`, leaves `release_reviewer_user_id` null, and computes `statutory_due_at`."

    Design: Corner/entities/request_computed_and_system_fields_are_server_owned_input_ignored
    """
    world = fx.third_party_world(api)
    payload = f.third_party_request_payload(
        world["facility_id"],
        world["patient_id"],
        world["requester_id"],
        world["authorization_id"],
        received_at="2020-01-01T00:00:00Z",
        statutory_due_at="2099-01-01T00:00:00Z",
        fulfillment_status="RELEASED",
        intake_user_id="u-analyst-1",
        version=99,
    )

    request = validate_success(api.create_request(payload, INTAKE_1), 201)

    assert request["received_at"] == Instant("2026-08-01T00:00:00Z")
    assert request["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
    assert request["fulfillment_status"] == "INTAKE_REVIEW"
    assert request["billing_status"] == "PENDING_INVOICE"
    assert request["intake_user_id"] == "u-intake-1"
    assert request["release_reviewer_user_id"] is None
    assert request["version"] == 1
    assert request["tolled_seconds"] == 0
    assert request["extension_applied"] is False
    assert request["page_count_total"] == 0
    assert request["penalty_exposure_cents"] == 0


def test_priced_lines_are_leaner_rows_carrying_neither_version_nor_updated_at(api):
    """An invoice line is an append-only artefact: id and created_at and nothing else.

    PRD: "Two resource kinds are deliberately leaner. Invoice lines and compliance events are append-only artefacts, never edited after they are written, and they therefore carry only `id` and `created_at` — an invoice line has no `updated_at` and no `version`, and a compliance event has no `updated_at` and no `version`."

    Design: Corner/entities/invoice_line_is_immutable_with_no_version_and_no_write_route
    """
    world = fx.third_party_world(api)
    scenario = fx.simple_third_party_request_at_release_ready(api, world, 25)
    invoice = fx.create_invoice(api, scenario["request_id"])

    lines, meta = fx.list_lines_of(api, invoice["id"])

    assert meta["total_count"] == 2
    assert_line_sequence_contiguous(lines)
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_no_line_type(lines, "PER_PAGE_TIER2")
    for line in lines:
        assert_created_only_fields(line)
    assert invoice["subtotal_cents"] == 2188
    assert invoice["amount_due_cents"] == 2188


def test_a_segment_naming_an_unknown_request_is_a_body_foreign_key_not_found(api):
    """The body foreign key resolves with the referenced collection's own code.

    PRD: "Foreign keys inside a write body are resolved with the same vocabulary, plus `ERR_STATE_FEE_RULE_NOT_FOUND` for an unknown fee schedule reference; a segment named in a sensitive-review decision list, or named as an amendment's `record_segment_id`, that belongs to a different request also reports `ERR_SEGMENT_NOT_FOUND`."

    Design: Corner/entities/record_segment_create_with_unknown_request_returns_not_found
    """
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])

    response = api.create_record_segment(
        f.record_segment_payload(NON_EXISTENT_UUID, "GENERAL_MEDICAL", "EHR_CURRENT"), ANALYST_1
    )

    validate_error(response, e.ERR_REQUEST_NOT_FOUND, 404)
    _, meta = fx.list_segments_for(api, request["id"])
    assert meta["total_count"] == 0


def test_a_requester_type_outside_the_eight_declared_values_is_refused(api):
    """requester_type is a closed enum, not free text.

    PRD: "A **requesting party** is registered by an `IntakeSpecialist` or a `PlatformAdmin` and is characterised first by its `requester_type`, one of exactly eight values: `PATIENT`, `PERSONAL_REPRESENTATIVE`, `ATTORNEY`, `INSURER`, `EMPLOYER`, `RESEARCHER`, `GOVERNMENT_AGENCY` or `OTHER_PROVIDER`."

    Design: Corner/entities/requester_type_outside_declared_enum_rejected
    """
    fx.base_world(api)
    payload = f.attorney_requester_payload(requester_type="SUBPOENA_CLERK")

    validate_error(api.create_requester(payload, INTAKE_1), e.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_requesters(INTAKE_1, {"limit": 10}))
    assert meta["total_count"] == 0


def test_an_inverted_date_range_gets_its_own_code_not_the_generic_one(api):
    """Interval ordering sits at position 5, one step past the body schema check.

    PRD: "A `date_range_end` earlier than `date_range_start` is refused with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/entities/request_date_range_end_before_start_rejected
    """
    world = fx.third_party_world(api)
    payload = f.third_party_request_payload(
        world["facility_id"],
        world["patient_id"],
        world["requester_id"],
        world["authorization_id"],
        date_range_start="2025-12-31",
        date_range_end="2024-01-01",
    )

    validate_error(api.create_request(payload, INTAKE_1), e.ERR_INVALID_DATE_RANGE, 400)

    _, meta = validate_paginated(
        api.list_requests(INTAKE_1, {"facility_id": world["facility_id"], "limit": 10})
    )
    assert meta["total_count"] == 0
