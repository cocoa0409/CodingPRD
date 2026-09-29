"""Access control and resolution failures: the identity gate, applicant scope,
the role-exclusive operations, the segregation rules decided from the body, and
the not-found code every collection owns."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    CORN_NO_2_FACTORS,
    INSPECTOR,
    MALFORMED_ID,
    NO_IDENTITY_HEADERS,
    STANDARD_HOURS_OPEN_CLOCK,
    SUPERVISOR,
    UNKNOWN_UUID,
    ApiErrorId,
    api_client,
    appeal_payload,
    appeal_vote_payload,
    assign_appeal_sample,
    break_seal_payload,
    cast_vote,
    certificate_payload,
    clock_payload,
    close_watch_payload,
    comparison_check_payload,
    countersign,
    create_applicant_account,
    create_inspector_row,
    create_request,
    dismiss_payload,
    grading_result_payload,
    make_applicant_headers,
    make_identity_headers,
    payment_payload,
    read_appeal,
    read_applicant,
    read_certificate,
    read_equipment,
    read_inspector,
    read_request,
    read_sample,
    read_weighing,
    record_grading,
    sample_payload,
    schedule_watch,
    setup_appeal_panel,
    setup_certificated_request,
    setup_filed_appeal,
    setup_office,
    setup_sampled_request,
    setup_weighed_request,
    supervise_payload,
    suspension_payload,
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


def test_an_unidentified_caller_is_stopped_before_any_other_rule_runs():
    """Every request must carry a single identity header, `X-User-Id`, naming
    the acting user. That one value both authenticates the caller and determines
    the role they act in. A request with a missing or unknown `X-User-Id` is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Authentication is always
    evaluated before authorization.

    1. **Authentication** — `X-User-Id` must be present and known, else
    `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.

    Any role may advance it by supplying a `current_utc` instant.

    An `Auditor` has unrestricted read access across the whole system and no
    write authority whatsoever, save for the logical-clock control which every
    role may drive.

    Design: Corner/rbac/requests_without_a_user_header_are_unauthenticated
    """
    office = setup_office("DESIGNATED")
    area_id = office["area"]["id"]

    anonymous = api_client.get_service_area(area_id, NO_IDENTITY_HEADERS)
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    stranger = api_client.get_service_area(
        area_id, make_identity_headers("nobody_user")
    )
    validate_error(stranger, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # Authentication outranks path existence: the missing row is never consulted.
    unresolvable = api_client.get_inspector(UNKNOWN_UUID, NO_IDENTITY_HEADERS)
    validate_error(unresolvable, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # And it outranks schema validation, so an empty body is never inspected.
    empty_write = api_client.create_service_area({}, NO_IDENTITY_HEADERS)
    validate_error(empty_write, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    unheaded_action = api_client.suspend_inspector(
        office["inspector"]["id"], suspension_payload(), NO_IDENTITY_HEADERS
    )
    validate_error(unheaded_action, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert read_inspector(office["inspector"]["id"])["license_status"] == "ACTIVE"

    # Even the clock, which every role may drive, demands an identity.
    unheaded_clock = api_client.set_current_utc(
        clock_payload("2026-08-04T09:00:00Z"), NO_IDENTITY_HEADERS
    )
    validate_error(unheaded_clock, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    validate_success(api_client.get_service_area(area_id, AUDITOR), 200)
    validate_success(
        api_client.set_current_utc(clock_payload("2026-08-04T09:00:00Z"), AUDITOR), 200
    )


def test_an_applicant_reaching_into_another_account_never_reaches_the_version_gate():
    """4. **Applicant scope** — an `ApplicantUser` acting outside their own
    account is refused with `ERR_APPLICANT_SCOPE_VIOLATION` (403). Applies to
    every endpoint an `ApplicantUser` may reach.

    An `ApplicantUser` who reads or acts on an inspection request, certificate,
    appeal, sample, grading result, analysis, weighing, watch or payment
    belonging to a different applicant account is refused with
    `ERR_APPLICANT_SCOPE_VIOLATION` (HTTP 403).

    Filing an appeal requires `expected_certificate_version` in the body — a
    non-optional integer carrying the `version` of the challenged certificate as
    the client last read it. If it does not equal the certificate's current
    `version`, the filing is refused with `ERR_CERTIFICATE_VERSION_CONFLICT`
    (HTTP 412), the certificate is not moved to `UNDER_APPEAL`, and no deposit is
    charged.

    Design: Corner/rbac/applicant_scope_violation_precedes_the_version_check
    """
    office = setup_office(
        "DELEGATED", fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE)
    )
    owner = office["applicant"]
    outsider = create_applicant_account(
        name="Neighbouring Elevator", account_code="OTHER-1"
    )
    staged = setup_certificated_request(
        office,
        "GRADE",
        declared_quantity_bushels=500,
        portions_count=2,
        lot_identifier="LOT-AS1",
        seal_number="SEAL-AS1",
    )
    as_owner = make_applicant_headers(owner["id"])
    as_outsider = make_applicant_headers(outsider["id"])

    issued = read_certificate(staged["certificate"]["id"])
    assert issued["fee_total_cents"] == 10000
    stale_version = issued["version"]

    # Settling the fee advances the certificate, so the version read above is
    # now a stale echo.
    validate_success(
        api_client.record_payment(owner["id"], payment_payload(10000), as_owner), 200
    )
    current = read_certificate(issued["id"])
    assert current["version"] == stale_version + 1
    assert current["fee_settlement_status"] == "PAID"
    assert current["status"] == "ISSUED"

    trespass = api_client.create_appeal(
        appeal_payload(issued["id"], owner["id"], current["version"], "APPEAL"),
        as_outsider,
    )
    validate_error(trespass, ApiErrorId.ERR_APPLICANT_SCOPE_VIOLATION.value, 403)

    # Wrong on both counts, the caller hears about the scope and never the echo.
    doubly_wrong = api_client.create_appeal(
        appeal_payload(issued["id"], owner["id"], stale_version, "APPEAL"),
        as_outsider,
    )
    validate_error(doubly_wrong, ApiErrorId.ERR_APPLICANT_SCOPE_VIOLATION.value, 403)

    untouched = read_certificate(issued["id"])
    assert untouched["status"] == "ISSUED"
    assert untouched["version"] == current["version"]
    assert read_applicant(outsider["id"])["charges_total_cents"] == 0

    # The stale echo on its own is the 412 the scope check had been hiding.
    stale = api_client.create_appeal(
        appeal_payload(issued["id"], owner["id"], stale_version, "APPEAL"), as_owner
    )
    validate_error(stale, ApiErrorId.ERR_CERTIFICATE_VERSION_CONFLICT.value, 412)
    assert read_certificate(issued["id"])["status"] == "ISSUED"
    assert read_applicant(owner["id"])["charges_total_cents"] == 10000

    accepted = validate_success(
        api_client.create_appeal(
            appeal_payload(issued["id"], owner["id"], current["version"], "APPEAL"),
            as_owner,
        ),
        201,
    )
    assert accepted["status"] == "FILED"
    assert accepted["deposit_cents"] == 20000
    assert read_certificate(issued["id"])["status"] == "UNDER_APPEAL"
    assert read_applicant(owner["id"])["charges_total_cents"] == 30000

    every_account = api_client.list_applicants(as_owner)
    validate_error(every_account, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    own_account = validate_success(api_client.get_applicant(owner["id"], as_owner), 200)
    assert own_account["id"] == owner["id"]
    assert own_account["open_balance_cents"] == 20000


def test_each_role_exclusive_operation_is_closed_to_every_other_role():
    """2. **Authorization** — the declared role must be permitted for the
    endpoint, else `ERR_UNAUTHORIZED` (403). Applies to every endpoint.

    A `LicensedInspector` is a line inspector: they sample, grade, analyse, weigh
    and issue certificates, but never countersign a weighing, never break a seal,
    never run a vessel watch and never vote on an appeal.

    A `ServiceAdmin` is the field-office administrator of the delegated or
    designated agency. They configure service areas and fee schedules, register
    applicant accounts, licence and discipline inspectors, register and certify
    equipment, and may dismiss appeals.

    An `Auditor` has unrestricted read access across the whole system and no
    write authority whatsoever, save for the logical-clock control which every
    role may drive.

    Design: Corner/rbac/role_exclusive_operations_are_closed_to_every_other_role
    """
    office = setup_office(
        "DESIGNATED",
        clock=STANDARD_HOURS_OPEN_CLOCK,
        fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE),
        second_supervisor=True,
    )
    probationer = create_inspector_row(office["area"]["id"], "L-7001")

    # Discipline belongs to the administrator alone.
    supervisor_suspending = api_client.suspend_inspector(
        probationer["id"], suspension_payload("Under investigation"), SUPERVISOR
    )
    validate_error(supervisor_suspending, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_inspector(probationer["id"])["license_status"] == "PROBATIONARY"

    # Authorization outranks path existence, so the unknown row stays unseen.
    supervisor_on_nothing = api_client.suspend_inspector(
        UNKNOWN_UUID, suspension_payload(), SUPERVISOR
    )
    validate_error(supervisor_on_nothing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    # A line inspector never countersigns, never breaks a seal, never runs a watch.
    weighed = setup_weighed_request(office, lot_identifier="LOT-RB1")
    line_countersigning = api_client.supervise_weighing_record(
        weighed["weighing"]["id"], supervise_payload(office["supervisor"]["id"]), INSPECTOR
    )
    validate_error(line_countersigning, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_weighing(weighed["weighing"]["id"])["status"] == "WEIGHED"

    sampled = setup_sampled_request(
        office, lot_identifier="LOT-RB2", seal_number="SEAL-RB2"
    )
    line_breaking = api_client.break_seal(
        sampled["sample"]["id"], INSPECTOR, break_seal_payload()
    )
    validate_error(line_breaking, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_sample(sampled["sample"]["id"])["integrity_status"] == "SEALED"

    watch_request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        lot_identifier="LOT-RB3",
        requested_services=["GRADING", "EXPORT_SUPERVISION"],
    )
    watch = schedule_watch(
        watch_request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )
    line_starting = api_client.start_vessel_watch(watch["id"], INSPECTOR)
    validate_error(line_starting, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    line_closing = api_client.close_vessel_watch(
        watch["id"], close_watch_payload(3, True), INSPECTOR
    )
    validate_error(line_closing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert validate_success(api_client.get_vessel_watch(watch["id"], ADMIN), 200)[
        "status"
    ] == "SCHEDULED"

    # Dismissal belongs to the administrator alone as well.
    appealed = setup_filed_appeal(
        office,
        declared_quantity_bushels=500,
        portions_count=4,
        lot_identifier="LOT-RB4",
        seal_number="SEAL-RB4",
    )
    supervisor_dismissing = api_client.dismiss_appeal(
        appealed["appeal"]["id"], SUPERVISOR, dismiss_payload()
    )
    validate_error(supervisor_dismissing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_appeal(appealed["appeal"]["id"])["status"] == "FILED"

    # The auditor may write nothing at all.
    auditor_certifying = api_client.create_certificate(
        certificate_payload(
            sampled["request"]["id"], office["inspector"]["id"], "GRADE"
        ),
        AUDITOR,
    )
    validate_error(auditor_certifying, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    auditor_grading = api_client.create_grading_result(
        grading_result_payload(
            sampled["request"]["id"],
            sampled["sample"]["id"],
            office["inspector"]["id"],
        ),
        AUDITOR,
    )
    validate_error(auditor_grading, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    auditor_sampling = api_client.create_sample(
        sample_payload(
            watch_request["id"],
            office["probe"]["id"],
            office["inspector"]["id"],
            seal_number="SEAL-RB5",
            portions_count=2,
        ),
        AUDITOR,
    )
    validate_error(auditor_sampling, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    auditor_paying = api_client.record_payment(
        office["applicant"]["id"], payment_payload(1000), AUDITOR
    )
    validate_error(auditor_paying, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert read_request(sampled["request"]["id"])["grading_status"] == "SAMPLED"

    # Reading, on the other hand, is entirely open to the auditor.
    validate_success(api_client.get_applicant(office["applicant"]["id"], AUDITOR), 200)
    validate_success(api_client.get_inspector(probationer["id"], AUDITOR), 200)
    validate_success(api_client.get_equipment(office["scale"]["id"], AUDITOR), 200)
    validate_success(
        api_client.get_certificate(appealed["certificate"]["id"], AUDITOR), 200
    )
    validate_success(api_client.get_appeal(appealed["appeal"]["id"], AUDITOR), 200)
    validate_paginated(api_client.list_appeal_votes(AUDITOR))
    validate_success(
        api_client.set_current_utc(clock_payload("2026-08-03T08:00:00Z"), AUDITOR), 200
    )


def test_the_challenged_grader_may_neither_regrade_nor_vote_on_their_own_work():
    """The regrading inspector must hold the `GRADING` endorsement with an
    `ACTIVE` licence and must not be the inspector who produced the challenged
    `FINAL` determination (`ERR_SEGREGATION_OF_DUTIES`).

    A member may cast at most one vote per appeal (`ERR_DUPLICATE_PANEL_VOTE`);
    the inspector who produced the challenged determination may not vote at all
    (`ERR_SEGREGATION_OF_DUTIES`); the voter must hold an `ACTIVE` licence; and
    on a `BOARD_APPEAL` every panel member must belong to a service area other
    than the challenged certificate's area
    (`ERR_BOARD_PANEL_COMPOSITION_INVALID`).

    The regrade itself is a grading determination carrying the `appeal_id`, and
    it moves the appeal `SAMPLE_ASSIGNED → UNDER_REVIEW`.

    The assignment retains a portion — `portions_retained` increases by one — and
    records `assigned_sample_id`.

    Design: Corner/rbac/original_grader_cannot_regrade_or_vote_on_their_own_determination
    """
    office = setup_office(
        "DELEGATED", fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE)
    )
    staged = setup_filed_appeal(
        office,
        declared_quantity_bushels=500,
        portions_count=4,
        lot_identifier="LOT-SG1",
        seal_number="SEAL-SG1",
    )
    original_grader = office["inspector"]
    panel = setup_appeal_panel(office, 2)
    regrader, voter = panel[0], panel[1]

    assigned = assign_appeal_sample(staged["appeal"]["id"], staged["sample"]["id"])
    assert assigned["status"] == "SAMPLE_ASSIGNED"
    assert assigned["assigned_sample_id"] == staged["sample"]["id"]

    self_regrade = api_client.create_grading_result(
        grading_result_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            original_grader["id"],
            CORN_NO_2_FACTORS,
            appeal_id=staged["appeal"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(self_regrade, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 422)

    held = read_appeal(staged["appeal"]["id"])
    assert held["status"] == "SAMPLE_ASSIGNED"
    refused = read_sample(staged["sample"]["id"])
    assert refused["portions_consumed"] == 1
    assert refused["portions_retained"] == 1

    regrade = record_grading(
        staged["request"]["id"],
        staged["sample"]["id"],
        regrader["id"],
        factors=CORN_NO_2_FACTORS,
        appeal_id=staged["appeal"]["id"],
    )
    assert regrade["assigned_grade"] == "US_NO_2"
    under_review = read_appeal(staged["appeal"]["id"])
    assert under_review["status"] == "UNDER_REVIEW"

    self_vote = api_client.create_appeal_vote(
        appeal_vote_payload(
            staged["appeal"]["id"],
            original_grader["id"],
            "UPHOLD",
            under_review["version"],
        ),
        SUPERVISOR,
    )
    validate_error(self_vote, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 422)
    assert read_appeal(staged["appeal"]["id"])["votes_cast_count"] == 0

    cast_vote(staged["appeal"]["id"], voter["id"], "UPHOLD")
    tallied = read_appeal(staged["appeal"]["id"])
    assert tallied["votes_cast_count"] == 1
    assert tallied["uphold_votes_count"] == 1

    twice = api_client.create_appeal_vote(
        appeal_vote_payload(
            staged["appeal"]["id"], voter["id"], "REVISE", tallied["version"]
        ),
        SUPERVISOR,
    )
    validate_error(twice, ApiErrorId.ERR_DUPLICATE_PANEL_VOTE.value, 422)
    unchanged = read_appeal(staged["appeal"]["id"])
    assert unchanged["votes_cast_count"] == 1
    assert unchanged["revise_votes_count"] == 0
    assert unchanged["version"] == tallied["version"]

    # The bar is per determination, not a stain on the inspector.
    elsewhere = setup_sampled_request(
        office,
        declared_quantity_bushels=500,
        portions_count=2,
        lot_identifier="LOT-SG2",
        seal_number="SEAL-SG2",
    )
    fresh = record_grading(
        elsewhere["request"]["id"],
        elsewhere["sample"]["id"],
        original_grader["id"],
        factors=CORN_NO_2_FACTORS,
    )
    assert fresh["status"] == "FINAL"


def test_a_weigher_may_never_countersign_their_own_weighing():
    """Three separations are absolute and are enforced on the operation that
    would breach them. A weighing must be countersigned by an inspector other
    than the one who performed it (`ERR_SELF_SUPERVISION_FORBIDDEN`).

    The record must be in `WEIGHED`, the supplied `supervisor_inspector_id` must
    differ from the record's `weigher_inspector_id`
    (`ERR_SELF_SUPERVISION_FORBIDDEN`), and the supervisor must hold the
    `SUPERVISION` endorsement with an `ACTIVE` licence. On success the record
    moves `WEIGHED → SUPERVISED`, `supervisor_inspector_id` is recorded where it
    had been null, and the request's weighing dimension advances
    `WEIGHED → SUPERVISED`.

    The check's deviation is the instrument reading minus the reference value,
    rounded half up to 2 decimals, and it is stored as
    `last_comparison_deviation_pct` while `comparison_check_count` increases by
    one. The instrument's `recent_deviations_pct` keeps at most the three most
    recent deviations including this one, oldest first in ascending creation
    order, and `rolling_bias_pct` is the arithmetic mean of those retained
    deviations, rounded half up to 2 decimals.

    Otherwise it resolves to `APPROVED`.

    A proficiency deviation counts against the inspector when the absolute value
    of a comparison check's deviation exceeds 0.25 percentage points, a
    deliberately tighter bar than the one that troubles the instrument itself.

    Design: Corner/rbac/self_supervision_and_self_check_are_both_refused
    """
    office = setup_office(
        "DESIGNATED",
        area_overrides={"supervision_required": True},
        second_supervisor=True,
    )
    staged = setup_weighed_request(
        office, weigher_id=office["supervisor"]["id"], lot_identifier="LOT-SF1"
    )
    assert staged["weighing"]["weigher_inspector_id"] == office["supervisor"]["id"]

    self_signed = api_client.supervise_weighing_record(
        staged["weighing"]["id"],
        supervise_payload(office["supervisor"]["id"]),
        SUPERVISOR,
    )
    validate_error(self_signed, ApiErrorId.ERR_SELF_SUPERVISION_FORBIDDEN.value, 422)

    stalled = read_weighing(staged["weighing"]["id"])
    assert stalled["status"] == "WEIGHED"
    assert stalled["supervisor_inspector_id"] is None
    assert read_request(staged["request"]["id"])["weighing_status"] == "WEIGHED"

    untouched = read_equipment(office["instrument"]["id"])
    assert untouched["comparison_check_count"] == 0
    assert untouched["recent_deviations_pct"] == []
    assert untouched["rolling_bias_pct"] is None
    assert untouched["last_comparison_deviation_pct"] is None

    countersigned = countersign(
        staged["weighing"]["id"], office["supervisor_2"]["id"]
    )
    assert countersigned["status"] == "SUPERVISED"
    assert countersigned["supervisor_inspector_id"] == office["supervisor_2"]["id"]
    assert read_request(staged["request"]["id"])["weighing_status"] == "SUPERVISED"

    validate_success(
        api_client.create_comparison_check(
            comparison_check_payload(
                office["instrument"]["id"], office["supervisor_2"]["id"], 12.00, 12.10
            ),
            SUPERVISOR,
        ),
        201,
    )
    checked = read_equipment(office["instrument"]["id"])
    assert checked["last_comparison_deviation_pct"] == 0.10
    assert checked["recent_deviations_pct"] == [0.10]
    assert checked["rolling_bias_pct"] == 0.10
    assert checked["comparison_check_count"] == 1
    assert checked["approval_status"] == "APPROVED"

    clean = read_inspector(office["supervisor_2"]["id"])
    assert clean["check_sample_deviation_count"] == 0
    assert clean["performance_score"] == 100


def test_every_collection_answers_an_unknown_id_with_its_own_not_found_code():
    """3. **Path existence** — every `{id}` in the path must resolve, else that
    entity's not-found code (404). Applies to every endpoint with a path
    parameter.

    Where a path names a parent collection member before a child — the
    certificates belonging to one inspection request, or the appeals filed
    against one certificate — the parent is resolved first, and a missing parent
    produces the parent's own not-found error (`ERR_INSPECTION_REQUEST_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`) before the child collection is ever consulted.
    The same precedence governs foreign keys carried in a request body: each
    named row must exist, and the failure is reported with that entity's
    not-found code — `ERR_SERVICE_AREA_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`,
    `ERR_APPLICANT_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
    `ERR_EQUIPMENT_NOT_FOUND` (for `sampling_device_id`, `scale_id` and
    `instrument_id` alike), `ERR_SAMPLE_NOT_FOUND`,
    `ERR_GRADING_RESULT_NOT_FOUND`, `ERR_PROTEIN_ANALYSIS_NOT_FOUND`,
    `ERR_WEIGHING_RECORD_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_APPEAL_VOTE_NOT_FOUND` or `ERR_VESSEL_WATCH_NOT_FOUND`. All of these
    carry HTTP 404.

    6. **Body reference existence** — every foreign key named in the body must
    resolve, else that entity's not-found code (404). Applies to every write
    endpoint carrying a foreign key.

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
    """
    office = setup_office("DESIGNATED")
    staged = setup_sampled_request(
        office, lot_identifier="LOT-NF1", seal_number="SEAL-NF1"
    )

    readers = [
        (api_client.get_service_area, ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND),
        (api_client.get_fee_schedule, ApiErrorId.ERR_FEE_SCHEDULE_NOT_FOUND),
        (api_client.get_applicant, ApiErrorId.ERR_APPLICANT_NOT_FOUND),
        (api_client.get_inspector, ApiErrorId.ERR_INSPECTOR_NOT_FOUND),
        (api_client.get_equipment, ApiErrorId.ERR_EQUIPMENT_NOT_FOUND),
        (
            api_client.get_inspection_request,
            ApiErrorId.ERR_INSPECTION_REQUEST_NOT_FOUND,
        ),
        (api_client.get_sample, ApiErrorId.ERR_SAMPLE_NOT_FOUND),
        (api_client.get_grading_result, ApiErrorId.ERR_GRADING_RESULT_NOT_FOUND),
        (api_client.get_protein_analysis, ApiErrorId.ERR_PROTEIN_ANALYSIS_NOT_FOUND),
        (api_client.get_weighing_record, ApiErrorId.ERR_WEIGHING_RECORD_NOT_FOUND),
        (api_client.get_certificate, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
        (api_client.get_appeal, ApiErrorId.ERR_APPEAL_NOT_FOUND),
        (api_client.get_appeal_vote, ApiErrorId.ERR_APPEAL_VOTE_NOT_FOUND),
        (api_client.get_vessel_watch, ApiErrorId.ERR_VESSEL_WATCH_NOT_FOUND),
    ]
    for reader, expected in readers:
        validate_error(reader(UNKNOWN_UUID, ADMIN), expected.value, 404)

    # A nested read reports the parent's code, never the child's.
    validate_error(
        api_client.list_request_certificates(UNKNOWN_UUID, ADMIN),
        ApiErrorId.ERR_INSPECTION_REQUEST_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.list_certificate_appeals(UNKNOWN_UUID, ADMIN),
        ApiErrorId.ERR_CERTIFICATE_NOT_FOUND.value,
        404,
    )

    # A foreign key carried in the body answers with the same code.
    validate_error(
        api_client.create_sample(
            sample_payload(
                staged["request"]["id"],
                UNKNOWN_UUID,
                office["inspector"]["id"],
                seal_number="SEAL-NF2",
                portions_count=2,
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_EQUIPMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.create_sample(
            sample_payload(
                UNKNOWN_UUID,
                office["probe"]["id"],
                office["inspector"]["id"],
                seal_number="SEAL-NF3",
                portions_count=2,
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_INSPECTION_REQUEST_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.create_grading_result(
            grading_result_payload(
                staged["request"]["id"], UNKNOWN_UUID, office["inspector"]["id"]
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_SAMPLE_NOT_FOUND.value,
        404,
    )

    # An id that is not even a UUID still resolves to nothing, and never to 500.
    validate_error(
        api_client.get_sample(MALFORMED_ID, ADMIN),
        ApiErrorId.ERR_SAMPLE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_inspection_request(MALFORMED_ID, ADMIN),
        ApiErrorId.ERR_INSPECTION_REQUEST_NOT_FOUND.value,
        404,
    )

    # The rows that do exist are unaffected by any of it.
    assert read_sample(staged["sample"]["id"])["integrity_status"] == "SEALED"
    assert read_request(staged["request"]["id"])["grading_status"] == "SAMPLED"
