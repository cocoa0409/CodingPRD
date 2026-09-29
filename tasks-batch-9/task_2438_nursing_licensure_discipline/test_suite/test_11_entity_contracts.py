"""Resource representations: envelopes, defaults, system fields, and listings."""
from test_helpers import (
    ADMIN,
    ANALYST,
    BOARD_DEFAULTS,
    CLOCK_DEFAULT_STAMP,
    INVESTIGATOR,
    UNKNOWN_UUID,
    ApiClient,
    ApiErrorId,
    assert_created_fresh,
    assert_decimal_equals,
    assert_education_program,
    assert_nurse,
    assert_pagination_meta,
    board_config_payload,
    ce_record_payload,
    education_program_payload,
    evidence_request_payload,
    is_valid_uuid,
    license_application_payload,
    mint_license,
    nurse_payload,
    record_clean_screening,
    seed_active_license,
    seed_application,
    seed_compact_board,
    seed_investigated_complaint,
    seed_nurse,
    seed_program,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verify_application_qualification,
)


def test_board_config_create_returns_the_envelope_and_minted_system_fields(
    api: ApiClient,
):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    PRD §2.6: "`version` (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every mutation, including mutations
    that only touch derived fields."

    PRD §2.6: "`id` (string): a server-minted UUID. It carries no type prefix of
    any kind."

    Design: Corner/entities/create_state_board_config_returns_201_with_envelope_and_system_fields
    """
    response = api.create_board_config(
        board_config_payload(state_code="OH", board_name="Ohio Board of Nursing",
                             compact_member=True),
        ADMIN,
    )

    board = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object", (
        f"A single resource is an object response, got {body['response_type']}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id starts with req_, got {body['meta']['api_request_id']}"
    )
    assert body["meta"]["api_request_timestamp"], "api_request_timestamp must be present"
    assert board["state_code"] == "OH"
    assert board["board_name"] == "Ohio Board of Nursing"
    assert board["compact_member"] is True
    assert board["status"] == "ACTIVE"
    assert_created_fresh(board)


def test_board_config_omitting_every_optional_knob_applies_the_defaults(api: ApiClient):
    """PRD §2.5: "Every one of those parameters is optional at creation and takes
    the stated default when omitted."

    PRD §2.5: "Whether the state has enacted the Nurse Licensure Compact is
    recorded in `compact_member`, which defaults to false."

    PRD §2.5: "Criminal-history screening is governed by `criminal_lookback_years`,
    defaulting to 7, together with `disqualifying_offense_codes`, an array of
    offence codes that defaults to the two codes `FEL-A` and `SEX-1`."

    PRD §2.5: "The record also carries a `status` of either `ACTIVE` or
    `ARCHIVED`, initialised to `ACTIVE`; an `ARCHIVED` board accepts no new
    licence applications and no new renewals."

    Design: Corner/entities/state_board_config_defaults_applied_when_every_optional_is_omitted
    """
    board = validate_success(
        api.create_board_config(
            board_config_payload(state_code="MI",
                                 board_name="Michigan Board of Nursing"),
            ADMIN,
        ),
        201,
    )

    assert board["compact_member"] is False, (
        "compact_member defaults to false, not true"
    )
    assert board["status"] == "ACTIVE"
    assert board["disqualifying_offense_codes"] == ["FEL-A", "SEX-1"], (
        f"The default offence list is the two named codes, got "
        f"{board['disqualifying_offense_codes']}"
    )
    for knob, expected in BOARD_DEFAULTS.items():
        if knob in ("compact_member", "status", "disqualifying_offense_codes"):
            continue
        actual = board[knob]
        if isinstance(expected, bool):
            assert actual is expected, f"{knob} defaults to {expected}, got {actual!r}"
        elif isinstance(expected, float):
            assert_decimal_equals(actual, expected, knob)
        else:
            assert actual == expected, f"{knob} defaults to {expected}, got {actual!r}"


def test_education_program_read_back_returns_the_stored_representation(api: ApiClient):
    """PRD §3.1: "A newly registered program's `approval_status` is `APPROVED`."

    PRD §3.1: "A program declares the board it answers to through
    `state_board_config_id`, a board-assigned `program_code` that must be unique
    within that board (a collision yields `ERR_PROGRAM_CODE_EXISTS`), a
    human-readable `program_name`, the credential it awards in `degree_level` —
    one of `PN`, `ADN`, `BSN`, or `MSN` — its first-time examination pass rate in
    `nclex_first_time_pass_rate_bp` as an integer basis-point figure between 0 and
    10000, and an `approval_expires_on` instant that is compared against the
    logical clock whenever an application leans on the program."

    PRD §2.6: "`version` (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every mutation, including mutations
    that only touch derived fields."

    Design: Corner/entities/get_education_program_returns_the_stored_representation
    """
    board = seed_compact_board(api)
    program = seed_program(api, board["id"])

    fetched = validate_success(api.get_education_program(program["id"], ANALYST))

    assert_education_program(fetched)
    assert fetched["id"] == program["id"]
    assert fetched["state_board_config_id"] == board["id"]
    assert fetched["program_code"] == "OH-BSN-01"
    assert fetched["degree_level"] == "BSN"
    assert fetched["nclex_first_time_pass_rate_bp"] == 8800
    assert fetched["approval_expires_on"].startswith("2032-01-01")
    assert fetched["approval_status"] == "APPROVED"
    assert fetched["version"] == 1, (
        f"A read is not a mutation, got version {fetched['version']}"
    )


def test_education_program_listing_under_a_board_paginates_by_creation_order(
    api: ApiClient,
):
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before pagination is
    applied), and `has_more` (true when records remain beyond the current page)."

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered
    by `created_at` ascending — oldest record first."

    PRD §3.1: "Programs may be listed for a board and narrowed by
    `approval_status` or by `degree_level`."

    Design: Corner/entities/list_education_programs_under_board_paginates_with_total_count_and_has_more
    """
    board = seed_compact_board(api)
    first = seed_program(api, board["id"], program_code="OH-PN-01",
                         program_name="Buckeye PN", degree_level="PN",
                         nclex_first_time_pass_rate_bp=7800)
    seed_program(api, board["id"], program_code="OH-ADN-01",
                 program_name="Buckeye ADN", degree_level="ADN",
                 nclex_first_time_pass_rate_bp=8400)
    third = seed_program(api, board["id"], program_code="OH-BSN-01",
                         program_name="Buckeye BSN", degree_level="BSN",
                         nclex_first_time_pass_rate_bp=8800)

    page_one, meta_one = validate_paginated(
        api.list_board_education_programs(board["id"], ADMIN,
                                          params={"limit": 2, "offset": 0})
    )
    page_two, meta_two = validate_paginated(
        api.list_board_education_programs(board["id"], ADMIN,
                                          params={"limit": 2, "offset": 2})
    )

    assert_pagination_meta(meta_one, limit=2, offset=0, total_count=3, has_more=True)
    assert len(page_one) == 2, f"A limit of 2 returns two rows, got {len(page_one)}"
    assert_pagination_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)
    assert len(page_two) == 1, f"One row remains, got {len(page_two)}"
    assert page_one[0]["id"] == first["id"], (
        "Oldest record first, so the earliest registration heads the first page"
    )
    assert page_two[0]["id"] == third["id"], (
        "The third registration is the only row on the second page"
    )

    filtered, filtered_meta = validate_paginated(
        api.list_board_education_programs(board["id"], ADMIN,
                                          params={"degree_level": "BSN"})
    )
    assert filtered_meta["total_count"] == 1, (
        f"Only one program awards a BSN, got {filtered_meta['total_count']}"
    )
    assert [row["id"] for row in filtered] == [third["id"]]


def test_reading_a_nurse_with_an_absent_identifier_returns_the_family_code(
    api: ApiClient,
):
    """PRD §2.10: "Each resource family has its own not-found code:
    `ERR_BOARD_CONFIG_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
    `ERR_NURSE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_RENEWAL_NOT_FOUND`, `ERR_CE_RECORD_NOT_FOUND`,
    `ERR_COMPLAINT_NOT_FOUND`, `ERR_EVIDENCE_REQUEST_NOT_FOUND`,
    `ERR_MONITORING_AGREEMENT_NOT_FOUND`, `ERR_PROCEEDING_NOT_FOUND`, and
    `ERR_NOTIFICATION_REPORT_NOT_FOUND`."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/get_nurse_with_unknown_uuid_returns_nurse_not_found
    """
    seed_compact_board(api)

    response = api.get_nurse(UNKNOWN_UUID, ANALYST)

    validate_error(response, ApiErrorId.ERR_NURSE_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
        "An error carries a non-empty human-readable message"
    )


def test_education_program_create_without_a_degree_level_is_rejected(api: ApiClient):
    """PRD §2.11: "The body is well formed: every required field is present, every
    enum field carries a declared member, every numeric field is in range (contact
    minutes greater than zero, basis-point fields within 0 through 10000, state
    codes exactly two uppercase letters), and every interval pair is ordered — a
    records hold's start must be strictly before its end, and a monitoring
    agreement's `start_date` must be at or before its `end_date`. Otherwise
    `ERR_INVALID_REQUEST`."

    PRD §3.1: "Nursing education programs are registered under a board's approval
    authority by the same role."

    Design: Corner/entities/create_education_program_missing_degree_level_returns_invalid_request
    """
    board = seed_compact_board(api)
    payload = education_program_payload(board["id"])
    payload.pop("degree_level")

    response = api.create_education_program(payload, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _, meta = validate_paginated(
        api.list_board_education_programs(board["id"], ADMIN)
    )
    assert meta["total_count"] == 0, (
        f"A rejected registration writes no row, got {meta['total_count']}"
    )


def test_nurse_create_without_residency_evidence_yields_an_empty_array(api: ApiClient):
    """PRD §3.1: "Documentary support for that assertion lives in
    `residency_evidence`, an ordered array that defaults to empty."

    PRD §3.1: "`fee_credit_cents` and `fee_paid_total_cents` both start at 0 and
    behave as described in §2.12."

    PRD §3.1: "The nurse's aggregate `status` starts at `ACTIVE` and moves between
    `ACTIVE`, `ENCUMBERED`, and `REVOKED` on the rules in §2.7."

    Design: Corner/entities/create_nurse_without_residency_evidence_defaults_to_empty_array
    """
    board = seed_compact_board(api)

    nurse = validate_success(
        api.create_nurse(nurse_payload(board["id"]), ANALYST), 201
    )

    assert_nurse(nurse)
    assert nurse["residency_evidence"] == [], (
        f"An omitted array materialises as [] and never null, got "
        f"{nurse['residency_evidence']!r}"
    )
    assert nurse["status"] == "ACTIVE"
    assert nurse["fee_credit_cents"] == 0
    assert nurse["fee_paid_total_cents"] == 0
    assert nurse["prior_discipline_count"] == 0
    assert nurse["atd_participation_count"] == 0
    assert nurse["version"] == 1


def test_client_supplied_application_status_and_counters_are_ignored(api: ApiClient):
    """PRD §3.2: "A new application begins at `DRAFT` with `screening_status`
    `NOT_ORDERED`, `deficiency_cycle_count` 0, `board_decision` `NONE`,
    `prior_license_verified` false, an empty `screening_offense_records` array,
    and both `submitted_at` and `decided_at` null."

    PRD §3.2: "`nclex_result` reports the licensure examination outcome as `PASS`,
    `FAIL`, or `NOT_TAKEN` and defaults to `NOT_TAKEN`."

    Design: Corner/entities/license_application_computed_status_extra_field_input_ignored
    """
    board = seed_compact_board(api)
    program = seed_program(api, board["id"])
    nurse = seed_nurse(api, board["id"])

    application = validate_success(
        api.create_license_application(
            license_application_payload(nurse["id"], board["id"], program["id"],
                                        status="APPROVED",
                                        deficiency_cycle_count=9,
                                        board_decision="APPROVED_UNCONDITIONAL"),
            ANALYST,
        ),
        201,
    )

    assert application["status"] == "DRAFT", (
        f"The server owns status, so the submitted APPROVED is ignored, got "
        f"{application['status']}"
    )
    assert application["deficiency_cycle_count"] == 0
    assert application["board_decision"] == "NONE"
    assert application["screening_status"] == "NOT_ORDERED"
    assert application["screening_offense_records"] == []
    assert application["submitted_at"] is None
    assert application["decided_at"] is None
    assert application["prior_license_verified"] is False
    assert application["nclex_result"] == "PASS"


def test_client_supplied_nurse_system_fields_are_discarded(api: ApiClient):
    """PRD §2.6: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, recording when the record was first created, taken from the
    logical clock."

    PRD §2.4: "Before the clock is ever set, it reads exactly
    `2026-08-01T00:00:00Z`; that fixed startup default must never be replaced by
    real wall-clock time."

    PRD §2.6: "`updated_at` (string): an ISO 8601 UTC timestamp in the same
    format, refreshed on every mutation of the record."

    Design: Corner/entities/nurse_system_fields_are_server_minted_extra_field_input_ignored
    """
    board = seed_compact_board(api)
    sentinel = "11111111-1111-4111-8111-111111111111"

    nurse = validate_success(
        api.create_nurse(
            nurse_payload(board["id"], full_name="Kai Moreno", birth_year=1990,
                          ssn_last4="7712", id=sentinel, version=42,
                          created_at="1999-01-01T00:00:00.000Z"),
            ANALYST,
        ),
        201,
    )

    assert nurse["id"] != sentinel, "The identifier is minted by the server"
    assert is_valid_uuid(nurse["id"])
    assert nurse["version"] == 1, (
        f"A fresh record starts at version 1, got {nurse['version']}"
    )
    assert nurse["created_at"] == CLOCK_DEFAULT_STAMP, (
        f"created_at comes from the logical clock, got {nurse['created_at']}"
    )
    assert nurse["updated_at"] == nurse["created_at"]


def test_application_create_with_an_undeclared_pathway_is_rejected(api: ApiClient):
    """PRD §3.2: "The payload names the applicant through `nurse_id`, the board it
    is filed with through `board_config_id`, the route through `pathway` — either
    `EXAMINATION` or `ENDORSEMENT` — and the credential sought through
    `credential_type`, one of `RN`, `LPN`, `APRN`, or `NURSE_AIDE`."

    PRD §2.11: "The body is well formed: every required field is present, every
    enum field carries a declared member, every numeric field is in range (contact
    minutes greater than zero, basis-point fields within 0 through 10000, state
    codes exactly two uppercase letters), and every interval pair is ordered — a
    records hold's start must be strictly before its end, and a monitoring
    agreement's `start_date` must be at or before its `end_date`. Otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_license_application_with_invalid_pathway_enum_returns_invalid_request
    """
    board = seed_compact_board(api)
    program = seed_program(api, board["id"])
    nurse = seed_nurse(api, board["id"])

    response = api.create_license_application(
        license_application_payload(nurse["id"], board["id"], program["id"],
                                    pathway="RECIPROCITY"),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _, meta = validate_paginated(
        api.list_license_applications(ANALYST, params={"nurse_id": nurse["id"]})
    )
    assert meta["total_count"] == 0, (
        f"A rejected filing writes no row, got {meta['total_count']}"
    )


def test_records_demand_with_an_inverted_hold_window_is_rejected(api: ApiClient):
    """PRD §2.11: "The body is well formed: every required field is present, every
    enum field carries a declared member, every numeric field is in range (contact
    minutes greater than zero, basis-point fields within 0 through 10000, state
    codes exactly two uppercase letters), and every interval pair is ordered — a
    records hold's start must be strictly before its end, and a monitoring
    agreement's `start_date` must be at or before its `end_date`. Otherwise
    `ERR_INVALID_REQUEST`."

    PRD §2.11: "When a single request violates more than one rule, the response
    must be deterministic."

    PRD §3.6: "If that count has already reached the board's
    `max_concurrent_custodian_holds`, the demand is refused with
    `ERR_CUSTODIAN_HOLD_CAPACITY`."

    Design: Corner/entities/create_evidence_request_with_hold_end_before_start_returns_invalid_request
    """
    ctx = seed_active_license(api)
    complaint = seed_investigated_complaint(api, ctx["license_id"],
                                            incident_date="2026-07-02T00:00:00Z")

    response = api.create_evidence_request(
        complaint["id"],
        evidence_request_payload(hold_start_at="2026-09-05T00:00:00Z",
                                 hold_end_at="2026-08-05T00:00:00Z"),
        INVESTIGATOR,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_CUSTODIAN_HOLD_CAPACITY.value
    ), "A malformed window never reaches the capacity rule"
    _, meta = validate_paginated(
        api.list_complaint_evidence_requests(complaint["id"], INVESTIGATOR)
    )
    assert meta["total_count"] == 0, (
        f"A rejected demand writes no row, got {meta['total_count']}"
    )


def test_application_create_naming_an_absent_board_returns_the_board_code(
    api: ApiClient,
):
    """PRD §2.10: "Every parent identifier in a creation payload must resolve to
    an existing row of the entity it names, and a payload that names a missing
    parent is rejected with that parent's not-found code."

    PRD §2.11: "Every parent identifier supplied in the request body resolves —
    otherwise that family's not-found code."

    PRD §2.10: "All collections in this API are mounted at the root; there is no
    shared path prefix, and the entity graph is flat, linked by identifiers in
    request bodies rather than by deep URL nesting."

    Design: Corner/entities/create_license_application_with_unknown_board_config_id_returns_board_config_not_found
    """
    board = seed_compact_board(api)
    program = seed_program(api, board["id"])
    nurse = seed_nurse(api, board["id"])

    response = api.create_license_application(
        license_application_payload(nurse["id"], UNKNOWN_UUID, program["id"]),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_BOARD_CONFIG_NOT_FOUND.value, 404)
    _, meta = validate_paginated(
        api.list_license_applications(ANALYST, params={"nurse_id": nurse["id"]})
    )
    assert meta["total_count"] == 0, (
        f"A rejected filing writes no row, got {meta['total_count']}"
    )


def test_ce_claim_under_an_absent_renewal_returns_the_renewal_code(api: ApiClient):
    """PRD §2.10: "Where a path does contain a resource identifier, and where a
    sub-collection hangs off it, identifiers are resolved strictly left to right
    and the request fails on the first identifier that does not resolve."

    PRD §2.11: "Every resource identifier in the path exists, validated left to
    right — otherwise that family's not-found code."

    PRD §2.10: "Reading the evidence requests of a non-existent complaint
    therefore reports `ERR_COMPLAINT_NOT_FOUND`, never an empty list."

    Design: Corner/entities/create_ce_record_under_unknown_renewal_returns_renewal_not_found
    """
    seed_compact_board(api)

    response = api.create_ce_record(
        UNKNOWN_UUID,
        ce_record_payload(provider_code="OHNA-100", minutes=600,
                          completion_date="2027-03-15T00:00:00Z"),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_RENEWAL_NOT_FOUND.value, 404)
    validate_error(api.get_renewal_application(UNKNOWN_UUID, ANALYST),
                   ApiErrorId.ERR_RENEWAL_NOT_FOUND.value, 404)


def test_credential_listing_filtered_by_nurse_returns_only_that_nurses_row(
    api: ApiClient,
):
    """PRD §3.3: "Credentials may be listed and narrowed by `nurse_id`,
    `issuing_board_config_id`, `source_application_id`, `base_license_id`,
    `credential_type`, `license_status`, `encumbrance_status`, or
    `multistate_privilege_status`."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before pagination is
    applied), and `has_more` (true when records remain beyond the current page)."

    PRD §3.3: "The system mints a board-assigned `license_number`, sets
    `license_status` to `ACTIVE` and `encumbrance_status` to `CLEAR`, stamps
    `issued_on` from the logical clock, sets `expires_on` to `issued_on` advanced
    by the board's `renewal_period_months`, initialises `practice_restriction_codes`
    to an empty array and `open_encumbrance_count` to 0, and moves the source
    application from `APPROVED` to the terminal `ISSUED`."

    Design: Corner/entities/list_licenses_filtered_by_nurse_id_returns_only_that_nurses_rows
    """
    board = seed_compact_board(api)
    program = seed_program(api, board["id"])
    first_nurse = seed_nurse(api, board["id"], full_name="Dana Reed",
                             birth_year=1988, ssn_last4="4417")
    second_nurse = seed_nurse(api, board["id"], full_name="Kai Moreno",
                              birth_year=1990, ssn_last4="7712")
    credentials = {}
    for nurse in (first_nurse, second_nurse):
        application = seed_application(api, nurse["id"], board["id"], program["id"])
        submit_application(api, application["id"])
        verify_application_qualification(api, application["id"])
        record_clean_screening(api, application["id"])
        credentials[nurse["id"]] = mint_license(api, application["id"])["id"]

    rows, meta = validate_paginated(
        api.list_licenses(ANALYST, params={"nurse_id": first_nurse["id"],
                                          "limit": 10, "offset": 0})
    )

    assert meta["total_count"] == 1, (
        f"The filter narrows to one credential, got {meta['total_count']}"
    )
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [credentials[first_nurse["id"]]]
    assert credentials[second_nurse["id"]] not in [row["id"] for row in rows]

    _, unfiltered = validate_paginated(api.list_licenses(ANALYST))
    assert unfiltered["total_count"] == 2, (
        f"Both credentials exist, got {unfiltered['total_count']}"
    )
    _, active = validate_paginated(
        api.list_licenses(ANALYST, params={"license_status": "ACTIVE"})
    )
    assert active["total_count"] == 2
    _, suspended = validate_paginated(
        api.list_licenses(ANALYST, params={"encumbrance_status": "SUSPENDED"})
    )
    assert suspended["total_count"] == 0
