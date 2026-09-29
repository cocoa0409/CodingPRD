"""Entity-level contracts: what a create call returns, which defaults it
applies, which fields the server mints, and how identifiers must resolve."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    BUSINESS_HOURS_CLOCK,
    INSPECTOR,
    SUPERVISOR,
    UNKNOWN_UUID,
    ApiErrorId,
    api_client,
    appeal_vote_payload,
    assert_append_only_fields,
    assert_common_fields,
    assert_equipment,
    assert_inspection_request,
    assert_portion_accounting,
    assert_sample,
    certify,
    create_applicant_account,
    create_designated_area,
    create_request,
    equipment_payload,
    grading_result_payload,
    inspection_request_payload,
    inspector_payload,
    protein_analysis_payload,
    read_appeal,
    read_equipment,
    read_request,
    read_sample,
    sample_payload,
    service_area_payload,
    set_clock,
    setup_appeal_under_review,
    setup_certificated_request,
    setup_graded_request,
    setup_office,
    setup_sampled_request,
    validate_error,
    validate_paginated,
    validate_success,
)


GRADING_SCHEDULE = {
    "service_class": "GRADING",
    "base_fee_cents": 8000,
    "per_thousand_bushel_rate_cents": 2000,
    "minimum_fee_cents": 10000,
}

APPEAL_SCHEDULE = {"service_class": "APPEAL", "base_fee_cents": 20000}


def test_a_new_inspection_request_materialises_every_system_and_derived_field():
    """`grading_status` starts at `OPEN` and runs
    `OPEN → SAMPLED → GRADED → GRADE_CERTIFIED`, with
    `GRADE_CERTIFIED → UNDER_APPEAL` and back again when rights are exercised.
    `weighing_status` starts at `PENDING` when `requested_services` includes
    `WEIGHING` and at `NOT_REQUIRED` when it does not, and runs through
    `WEIGHED`, `SUPERVISED` and `WEIGHT_CERTIFIED`.

    Two derived figures sit alongside them: `grade_revision_count` starts at 0
    and counts the appeals on this request decided in the applicant's favour, and
    `certified_quantity_bushels` is the quantity fees are assessed on — it is
    initialised from `declared_quantity_bushels` and becomes the `net_bushels` of
    the operative weighing record once one exists in `WEIGHED` or `SUPERVISED`
    status.

    Every persisted resource carries a server-minted `id`: a UUID string with no
    type prefix and no embedded meaning.

    Design: Corner/entities/inspection_request_creation_returns_every_declared_field
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    applicant = create_applicant_account()

    response = api_client.create_inspection_request(
        inspection_request_payload(
            applicant["id"],
            area["id"],
            lot_identifier="LOT-CREATE",
            declared_quantity_bushels=4000,
            requested_services=["GRADING", "WEIGHING"],
        ),
        ADMIN,
    )
    request = validate_success(response, 201)

    assert_common_fields(request)
    assert_inspection_request(request)
    assert request["version"] == 1
    assert request["created_at"] == request["updated_at"]
    assert request["grading_status"] == "OPEN"
    assert request["weighing_status"] == "PENDING"
    assert request["certified_quantity_bushels"] == 4000
    assert request["grade_revision_count"] == 0

    read_back = read_request(request["id"])
    for field in (
        "id",
        "applicant_id",
        "service_area_id",
        "commodity",
        "point_of_service",
        "lot_identifier",
        "declared_quantity_bushels",
        "requested_services",
        "grading_status",
        "weighing_status",
        "certified_quantity_bushels",
        "grade_revision_count",
        "version",
    ):
        assert read_back[field] == request[field]

    grading_only = create_request(
        applicant["id"],
        area["id"],
        lot_identifier="LOT-CREATE-2",
        requested_services=["GRADING"],
    )
    assert grading_only["weighing_status"] == "NOT_REQUIRED"


def test_a_new_sample_applies_its_declared_defaults_from_the_logical_clock():
    """The `sample_type` defaults to `ORIGINAL` and may instead be `FILE` for a
    retained duplicate or `APPEAL` for a sample drawn for a challenge.

    On success the sample is `SEALED`, `collected_at` is stamped from the logical
    clock, `file_retention_until` is set to exactly 90 days after `collected_at`,
    `portions_consumed` and `portions_retained` are 0 so that
    `portions_available` equals `portions_count`, and — for an `ORIGINAL` sample
    — the request advances `OPEN → SAMPLED`.

    Design: Corner/entities/sample_creation_applies_declared_defaults
    """
    office = setup_office("DESIGNATED")
    request = create_request(
        office["applicant"]["id"], office["area"]["id"], lot_identifier="LOT-DEF"
    )

    response = api_client.create_sample(
        sample_payload(
            request["id"],
            office["probe"]["id"],
            office["inspector"]["id"],
            seal_number="SEAL-DEF",
            portions_count=3,
        ),
        INSPECTOR,
    )
    sample = validate_success(response, 201)

    assert_sample(sample)
    assert sample["sample_type"] == "ORIGINAL"
    assert sample["integrity_status"] == "SEALED"
    assert sample["portions_count"] == 3
    assert sample["portions_consumed"] == 0
    assert sample["portions_retained"] == 0
    assert sample["portions_available"] == 3
    assert_portion_accounting(sample)
    assert sample["collected_at"] == "2026-08-03T09:00:00.000Z"
    assert sample["file_retention_until"] == "2026-11-01T09:00:00.000Z"
    assert read_request(request["id"])["grading_status"] == "SAMPLED"

    no_count = api_client.create_sample(
        sample_payload(
            request["id"],
            office["probe"]["id"],
            office["inspector"]["id"],
            seal_number="SEAL-DEF-2",
            portions_count=...,
        ),
        INSPECTOR,
    )
    validate_error(no_count, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    over_the_maximum = api_client.create_sample(
        sample_payload(
            request["id"],
            office["probe"]["id"],
            office["inspector"]["id"],
            seal_number="SEAL-DEF-3",
            portions_count=11,
        ),
        INSPECTOR,
    )
    validate_error(over_the_maximum, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_an_inspection_request_without_its_required_inputs_is_refused():
    """**Schema** — required body fields present, correctly typed, inside their
    declared ranges and enum domains, with unknown fields rejected, else
    `ERR_INVALID_REQUEST` (422).

    That list may not be empty and **must** include `GRADING`; a request without
    it is refused with `ERR_SERVICE_NOT_REQUESTED`.

    Design: Corner/entities/inspection_request_missing_required_fields_returns_invalid_request
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    applicant = create_applicant_account()

    missing_services = api_client.create_inspection_request(
        inspection_request_payload(
            applicant["id"],
            area["id"],
            lot_identifier="LOT-MISS",
            declared_quantity_bushels=4000,
            requested_services=...,
        ),
        ADMIN,
    )
    validate_error(missing_services, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    grading_absent = api_client.create_inspection_request(
        inspection_request_payload(
            applicant["id"],
            area["id"],
            lot_identifier="LOT-MISS",
            declared_quantity_bushels=4000,
            requested_services=["WEIGHING"],
        ),
        ADMIN,
    )
    validate_error(grading_absent, ApiErrorId.ERR_SERVICE_NOT_REQUESTED.value, 422)

    zero_quantity = api_client.create_inspection_request(
        inspection_request_payload(
            applicant["id"],
            area["id"],
            lot_identifier="LOT-MISS",
            declared_quantity_bushels=0,
        ),
        ADMIN,
    )
    validate_error(zero_quantity, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    listed = api_client.list_inspection_requests(
        AUDITOR, {"applicant_id": applicant["id"]}
    )
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 0
    assert rows == []


def test_the_certificate_list_paginates_and_filters_over_the_matching_set():
    """Collection endpoints accept two query parameters. `limit` caps the number
    of rows returned; it defaults to 10, may not be smaller than 1 and may not be
    larger than 100. `offset` skips rows from the head of the result and defaults
    to 0, its smallest permitted value.

    Both are echoed back in `meta` alongside `total_count` (the number of rows
    matching the filters before the window is applied) and `has_more` (true when
    rows remain beyond the returned window).

    Certificates may be listed by `inspection_request_id`,
    `issuing_inspector_id`, `superseded_certificate_id`, `appeal_id`,
    `certificate_type`, `status` and `fee_settlement_status`.

    Design: Corner/entities/certificates_list_paginates_and_filters_by_declared_inputs
    """
    office = setup_office(
        "DELEGATED",
        fee_schedules=(GRADING_SCHEDULE,),
        applicant_overrides={"credit_limit_cents": 900000},
    )
    issued = []
    for index in range(12):
        staged = setup_certificated_request(
            office,
            "GRADE",
            declared_quantity_bushels=500,
            portions_count=1,
            lot_identifier=f"LOT-P{index}",
            seal_number=f"SEAL-P{index}",
        )
        issued.append(staged)
    assert issued[0]["certificate"]["fee_total_cents"] == 10000

    first_page = api_client.list_certificates(AUDITOR)
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 10
    assert meta["total_count"] == 12
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    tail = api_client.list_certificates(AUDITOR, {"limit": 5, "offset": 10})
    rows, meta = validate_paginated(tail)
    assert len(rows) == 2
    assert meta["total_count"] == 12
    assert meta["has_more"] is False

    other_type = api_client.list_certificates(AUDITOR, {"certificate_type": "WEIGHT"})
    rows, meta = validate_paginated(other_type)
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    by_request = api_client.list_certificates(
        AUDITOR, {"inspection_request_id": issued[0]["request"]["id"]}
    )
    rows, meta = validate_paginated(by_request)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == issued[0]["certificate"]["id"]

    validate_error(
        api_client.list_certificates(AUDITOR, {"limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api_client.list_certificates(AUDITOR, {"limit": 101}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )


def test_newly_registered_equipment_carries_only_server_minted_calibration_state():
    """Registration leaves the row in `PENDING_APPROVAL` with a null
    `certified_until`, a null `last_certification_error_lbs`, an empty
    `recent_deviations_pct`, a null `rolling_bias_pct`, a null
    `last_comparison_deviation_pct`, a `comparison_check_count` of 0 and a
    `consecutive_out_of_tolerance_checks` of 0.

    The instrument must be of kind `PROTEIN_INSTRUMENT`, must belong to the
    request's area, and — uniquely among equipment uses — may be either
    `APPROVED` or `DRIFT_WATCH` provided its `certified_until` is still in the
    future; anything else is `ERR_EQUIPMENT_NOT_APPROVED`.

    Design: Corner/entities/equipment_system_and_computed_fields_are_server_minted
    """
    office = setup_office("DESIGNATED")

    response = api_client.create_equipment(
        equipment_payload(
            office["area"]["id"],
            "PROTEIN_INSTRUMENT",
            asset_code="NIR-SYS",
            model="SpectraGrain 9",
        ),
        ADMIN,
    )
    instrument = validate_success(response, 201)

    assert_common_fields(instrument)
    assert_equipment(instrument)
    assert instrument["approval_status"] == "PENDING_APPROVAL"
    assert instrument["certified_until"] is None
    assert instrument["last_certification_error_lbs"] is None
    assert instrument["recent_deviations_pct"] == []
    assert instrument["rolling_bias_pct"] is None
    assert instrument["last_comparison_deviation_pct"] is None
    assert instrument["comparison_check_count"] == 0
    assert instrument["consecutive_out_of_tolerance_checks"] == 0
    assert instrument["capacity_lbs"] is None
    assert instrument["tolerance_lbs"] is None
    assert instrument["version"] == 1

    staged = setup_graded_request(
        office,
        requested_services=("GRADING", "PROTEIN"),
        portions_count=2,
        lot_identifier="LOT-SYS",
        seal_number="SEAL-SYS",
    )
    premature = api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            instrument["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(premature, ApiErrorId.ERR_EQUIPMENT_NOT_APPROVED.value, 409)

    certify(instrument["id"])
    approved = read_equipment(instrument["id"])
    assert approved["approval_status"] == "APPROVED"
    assert approved["certified_until"] is not None

    accepted = api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            instrument["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_success(accepted, 201)


def test_an_appeal_vote_exposes_no_version_and_can_never_be_recast():
    """A cast vote is an immutable act of a panel member, so an appeal vote row
    carries only `id` and `created_at` — it has **no** `updated_at` and **no**
    `version` field at all.

    Each accepted vote increments `votes_cast_count` and the counter for its own
    value, recomputes `effective_votes_count` as `revise_votes_count` plus
    `uphold_votes_count` — abstentions count toward neither side and are excluded
    from the denominator — and advances the appeal's `version`.

    A member may cast at most one vote per appeal (`ERR_DUPLICATE_PANEL_VOTE`);
    the inspector who produced the challenged determination may not vote at all
    (`ERR_SEGREGATION_OF_DUTIES`); the voter must hold an `ACTIVE` licence; and on
    a `BOARD_APPEAL` every panel member must belong to a service area other than
    the challenged certificate's area (`ERR_BOARD_PANEL_COMPOSITION_INVALID`).

    Design: Corner/entities/appeal_vote_is_immutable_and_carries_no_version_field
    """
    office = setup_office(
        "DELEGATED", fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE)
    )
    staged = setup_appeal_under_review(
        office,
        appeal_type="REINSPECTION",
        panel_size=1,
        declared_quantity_bushels=500,
        lot_identifier="LOT-VOTE",
        seal_number="SEAL-VOTE",
    )
    appeal = staged["appeal"]
    stale_version = appeal["version"]
    voter = staged["voters"][0]

    response = api_client.create_appeal_vote(
        appeal_vote_payload(
            appeal["id"],
            voter["id"],
            "REVISE",
            stale_version,
            rationale="Test weight below 54.0",
        ),
        SUPERVISOR,
    )
    vote = validate_success(response, 201)

    assert_append_only_fields(vote)
    assert "version" not in vote
    assert "updated_at" not in vote

    read_back = validate_success(api_client.get_appeal_vote(vote["id"], AUDITOR), 200)
    assert read_back["id"] == vote["id"]
    assert "version" not in read_back
    assert "updated_at" not in read_back

    tallied = read_appeal(appeal["id"])
    assert tallied["version"] > stale_version
    assert tallied["votes_cast_count"] == 1
    assert tallied["revise_votes_count"] == 1
    assert tallied["effective_votes_count"] == 1

    stale_repeat = api_client.create_appeal_vote(
        appeal_vote_payload(appeal["id"], voter["id"], "REVISE", stale_version),
        SUPERVISOR,
    )
    validate_error(stale_repeat, ApiErrorId.ERR_APPEAL_VERSION_CONFLICT.value, 412)

    fresh_repeat = api_client.create_appeal_vote(
        appeal_vote_payload(
            appeal["id"], voter["id"], "REVISE", tallied["version"]
        ),
        SUPERVISOR,
    )
    validate_error(fresh_repeat, ApiErrorId.ERR_DUPLICATE_PANEL_VOTE.value, 422)


def test_an_unknown_endorsement_and_an_out_of_range_multiplier_are_both_refused():
    """Licensing an **inspector** attaches a person to one area through
    `service_area_id` and records a `license_number` — unique within that area,
    so a collision yields `ERR_DUPLICATE_IDENTIFIER` — a `full_name` that is
    printed on certificates, a non-empty set of `endorsements` drawn from
    `SAMPLING`, `GRADING`, `PROTEIN`, `WEIGHING` and `SUPERVISION`, and a
    `license_expires_at` instant.

    A `ServiceAdmin` opens a field office by registering a **service area** with a
    `name` of 1 to 120 characters, a `state_code` of exactly two uppercase
    letters, and an `authority_type` of `DELEGATED` or `DESIGNATED`.

    `fee_multiplier_bp` starts at 10000, meaning no adjustment, and may be set
    anywhere from 10000 up to 15000; `supervision_required` starts true; and
    `concurrent_watch_capacity` starts at 2 and must be at least 1.

    Design: Corner/entities/inspector_endorsement_enum_rejects_unknown_value
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()

    unknown_member = api_client.create_inspector(
        inspector_payload(
            area["id"],
            license_number="L-1105",
            full_name="E. Enum",
            endorsements=["SAMPLING", "STOWAGE"],
        ),
        ADMIN,
    )
    validate_error(unknown_member, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    empty_set = api_client.create_inspector(
        inspector_payload(area["id"], license_number="L-1106", endorsements=[]),
        ADMIN,
    )
    validate_error(empty_set, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    long_state_code = api_client.create_service_area(
        service_area_payload(state_code="Texas"), ADMIN
    )
    validate_error(long_state_code, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    below_the_floor = api_client.create_service_area(
        service_area_payload(state_code="TX", fee_multiplier_bp=9999), ADMIN
    )
    validate_error(below_the_floor, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    above_the_ceiling = api_client.create_service_area(
        service_area_payload(state_code="TX", fee_multiplier_bp=15001), ADMIN
    )
    validate_error(above_the_ceiling, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    listed = api_client.list_inspectors(ADMIN, {"service_area_id": area["id"]})
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 0
    assert rows == []


def test_every_unresolved_body_reference_on_a_sample_reports_its_own_not_found():
    """The same precedence governs foreign keys carried in a request body: each
    named row must exist, and the failure is reported with that entity's
    not-found code — `ERR_SERVICE_AREA_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`,
    `ERR_APPLICANT_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
    `ERR_EQUIPMENT_NOT_FOUND` (for `sampling_device_id`, `scale_id` and
    `instrument_id` alike), `ERR_SAMPLE_NOT_FOUND`,
    `ERR_GRADING_RESULT_NOT_FOUND`, `ERR_PROTEIN_ANALYSIS_NOT_FOUND`,
    `ERR_WEIGHING_RECORD_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_APPEAL_VOTE_NOT_FOUND` or `ERR_VESSEL_WATCH_NOT_FOUND`.

    **Body reference existence** — every foreign key named in the body must
    resolve, else that entity's not-found code (404).

    Design: Corner/entities/sample_cannot_be_created_under_a_nonexistent_request
    """
    office = setup_office("DESIGNATED")
    request = create_request(
        office["applicant"]["id"], office["area"]["id"], lot_identifier="LOT-ORPH"
    )

    unknown_request = api_client.create_sample(
        sample_payload(
            UNKNOWN_UUID,
            office["probe"]["id"],
            office["inspector"]["id"],
            seal_number="SEAL-ORPH",
            portions_count=2,
        ),
        INSPECTOR,
    )
    validate_error(
        unknown_request, ApiErrorId.ERR_INSPECTION_REQUEST_NOT_FOUND.value, 404
    )

    unknown_device = api_client.create_sample(
        sample_payload(
            request["id"],
            UNKNOWN_UUID,
            office["inspector"]["id"],
            seal_number="SEAL-ORPH",
            portions_count=2,
        ),
        INSPECTOR,
    )
    validate_error(unknown_device, ApiErrorId.ERR_EQUIPMENT_NOT_FOUND.value, 404)

    unknown_inspector = api_client.create_sample(
        sample_payload(
            request["id"],
            office["probe"]["id"],
            UNKNOWN_UUID,
            seal_number="SEAL-ORPH",
            portions_count=2,
        ),
        INSPECTOR,
    )
    validate_error(unknown_inspector, ApiErrorId.ERR_INSPECTOR_NOT_FOUND.value, 404)

    filtered = api_client.list_samples(
        AUDITOR, {"inspection_request_id": UNKNOWN_UUID}
    )
    rows, meta = validate_paginated(filtered)
    assert meta["total_count"] == 0
    assert rows == []


def test_a_determination_may_not_name_a_sample_drawn_for_another_request():
    """The sample must belong to the same request
    (`ERR_SAMPLE_REQUEST_MISMATCH`), must be neither `BROKEN` nor `EXPIRED`, and
    must have at least one portion available; the inspector must hold the
    `GRADING` endorsement and a `PROBATIONARY` or `ACTIVE` licence.

    `ERR_SAMPLE_REQUEST_MISMATCH` guards grading-result creation,
    protein-analysis creation and appeal sample assignment.

    Design: Corner/entities/grading_result_sample_must_belong_to_the_named_request
    """
    office = setup_office("DESIGNATED")
    first = setup_sampled_request(
        office, portions_count=2, lot_identifier="LOT-FK-A", seal_number="SEAL-FK-A"
    )
    second = setup_sampled_request(
        office, portions_count=2, lot_identifier="LOT-FK-B", seal_number="SEAL-FK-B"
    )

    crossed = api_client.create_grading_result(
        grading_result_payload(
            second["request"]["id"],
            first["sample"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(crossed, ApiErrorId.ERR_SAMPLE_REQUEST_MISMATCH.value, 422)

    untouched = read_sample(first["sample"]["id"])
    assert untouched["portions_consumed"] == 0
    assert untouched["integrity_status"] == "SEALED"

    matched = api_client.create_grading_result(
        grading_result_payload(
            second["request"]["id"],
            second["sample"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_success(matched, 201)
    assert read_request(second["request"]["id"])["grading_status"] == "GRADED"
    assert read_sample(second["sample"]["id"])["portions_consumed"] == 1
