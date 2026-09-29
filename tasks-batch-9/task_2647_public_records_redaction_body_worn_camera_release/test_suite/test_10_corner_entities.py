"""Entity-level corners: declared defaults, stored echoes, envelopes and uniqueness.

Each test replays one instance of the corner design's `entities` section from an
empty database: what a create call must materialise, what a read must give back
unchanged, which not-found code each resource family owns, and where a duplicate
or a forged system field must be refused or ignored.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_DENIAL_LETTER_NOT_FOUND,
    ERR_DEPICTED_INDIVIDUAL_NOT_FOUND,
    ERR_DUPLICATE_DEPICTED_LABEL,
    ERR_EXEMPTION_CLAIM_NOT_FOUND,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_LITIGATION_HOLD_NOT_FOUND,
    ERR_REDACTION_TASK_NOT_FOUND,
    ERR_REQUEST_NOT_FOUND,
    ERR_REQUESTER_NOT_FOUND,
    ERR_RESPONSIVE_RECORD_NOT_FOUND,
    ERR_VALIDATION,
    ERR_VIDEO_ASSET_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_created,
    assert_fields,
    assert_ids,
    assert_ledger_conservation,
    assert_ledger_entry_fields,
    assert_list_response,
    assert_money_is_integer_cents,
    assert_total_count,
    assert_waiver_pct,
)
from test_helpers.factories import (
    depicted_individual_payload,
    exemption_claim_payload,
    payment_payload,
    redaction_task_payload,
    request_payload,
    requester_payload,
    responsive_record_payload,
    video_asset_payload,
)
from test_helpers.fixtures import (
    attach_record,
    clarify_scope,
    create_asset,
    create_depicted_individual,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_asset,
    get_individual,
    get_record,
    get_request,
    get_requester,
    post_payment,
    rule_inclusion,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_counsel_headers,
    make_requester_headers,
    make_technician_headers,
)

OTHER_UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000fe"


# ------------------------------------------------- VideoAsset creation defaults
def _catalogue_minimal_recording(api):
    """Catalogue a recording supplying only the eight mandatory inputs."""
    return api.create_video_asset(
        video_asset_payload(
            incident_number="INC-2026-0601",
            device_serial="AXON-0601",
            officer_badge="B-1101",
            recorded_start_at="2026-07-25T08:00:00Z",
            duration_ms=600000,
            classification="ROUTINE",
            retention_category="NON_EVIDENTIARY_180D",
            scheduled_purge_at="2027-01-21T00:00:00Z",
        ),
        CLERK_HEADERS,
    )


def test_a_new_recording_opens_scheduled_with_no_depicted_individuals(api):
    """The create response already carries SCHEDULED, a zero count and no suspending hold.

    PRD: "A new recording opens with `disposition_state` at `SCHEDULED` and `depicted_individual_count` at 0."

    Design: Corner/entities/video_asset_create_returns_declared_defaults_and_state
    """
    response = _catalogue_minimal_recording(api)

    asset = assert_created(response)
    assert_fields(
        asset,
        disposition_state="SCHEDULED",
        depicted_individual_count=0,
        suspended_by_hold_id=None,
    )
    assert_fields(
        get_asset(api, asset["id"]),
        disposition_state="SCHEDULED",
        depicted_individual_count=0,
        suspended_by_hold_id=None,
    )


def test_a_freshly_catalogued_recording_is_not_retention_locked(api):
    """No ACTIVE hold and no responsive record exist, so the lock computes to false.

    PRD: "`retention_locked` on a recording is true exactly when at least one litigation hold with `status` `ACTIVE` carries a `scope_incident_number` equal to the recording's `incident_number`, or at least one responsive record references the recording with `inclusion_status` among `CANDIDATE`, `RESPONSIVE` and `WITHHELD_IN_FULL` on a request whose `processing_status` is none of `RELEASED`, `DENIED` and `CLOSED`."

    Design: Corner/entities/video_asset_create_returns_declared_defaults_and_state
    """
    response = _catalogue_minimal_recording(api)

    asset = assert_created(response)
    assert asset["retention_locked"] is False
    assert get_asset(api, asset["id"])["retention_locked"] is False


def test_is_critical_incident_defaults_to_false_when_the_flag_is_omitted(api):
    """The optional flag is absent from the payload, so the row comes back false at version 1.

    PRD: "The payload names the `incident_number` the recording belongs to, the `device_serial` of the camera, the `officer_badge` of the officer wearing it, the `recorded_start_at` wall-clock instant at which recording began, the `duration_ms` length in milliseconds, which must be strictly greater than zero, the `classification` drawn from `ROUTINE`, `USE_OF_FORCE`, `JUVENILE_CONTACT`, `OFFICER_INVOLVED_SHOOTING` and `IN_CUSTODY_DEATH`, the `retention_category` drawn from `EVIDENTIARY_7Y`, `INVESTIGATIVE_3Y` and `NON_EVIDENTIARY_180D`, the `scheduled_purge_at` instant that is the earliest moment the retention schedule permits destruction, and an optional `is_critical_incident` flag defaulting to false that marks the recording as depicting a statutorily defined critical incident."

    Design: Corner/entities/video_asset_create_returns_declared_defaults_and_state
    """
    response = _catalogue_minimal_recording(api)

    asset = assert_created(response)
    assert asset["is_critical_incident"] is False
    assert_fields(asset, duration_ms=600000, classification="ROUTINE")
    assert_common_fields(asset, 1)


# ------------------------------------------------------- VideoAsset read-back
def _catalogue_critical_recording(api):
    """A twenty-minute officer-involved-shooting recording flagged critical."""
    return create_asset(
        api,
        incident_number="INC-2026-0602",
        device_serial="AXON-0602",
        officer_badge="B-1102",
        recorded_start_at="2026-07-26T21:15:00Z",
        duration_ms=1200000,
        classification="OFFICER_INVOLVED_SHOOTING",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-26T00:00:00Z",
        is_critical_incident=True,
    )


def test_get_video_asset_gives_back_every_stored_input_unchanged(api):
    """The read projection reads storage: all nine declared inputs echo exactly.

    PRD: "The payload names the `incident_number` the recording belongs to, the `device_serial` of the camera, the `officer_badge` of the officer wearing it, the `recorded_start_at` wall-clock instant at which recording began, the `duration_ms` length in milliseconds, which must be strictly greater than zero, the `classification` drawn from `ROUTINE`, `USE_OF_FORCE`, `JUVENILE_CONTACT`, `OFFICER_INVOLVED_SHOOTING` and `IN_CUSTODY_DEATH`, the `retention_category` drawn from `EVIDENTIARY_7Y`, `INVESTIGATIVE_3Y` and `NON_EVIDENTIARY_180D`, the `scheduled_purge_at` instant that is the earliest moment the retention schedule permits destruction, and an optional `is_critical_incident` flag defaulting to false that marks the recording as depicting a statutorily defined critical incident."

    Design: Corner/entities/video_asset_get_returns_stored_representation
    """
    created = _catalogue_critical_recording(api)

    fetched = validate_success(api.get_video_asset(created["id"], SUPERVISOR_HEADERS), 200)

    assert_fields(
        fetched,
        incident_number="INC-2026-0602",
        device_serial="AXON-0602",
        officer_badge="B-1102",
        recorded_start_at="2026-07-26T21:15:00Z",
        duration_ms=1200000,
        classification="OFFICER_INVOLVED_SHOOTING",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-26T00:00:00Z",
    )
    assert fetched["is_critical_incident"] is True


def test_reading_a_recording_never_bumps_its_version(api):
    """The same id comes back at version 1, because a read mutates nothing.

    PRD: "Almost every resource additionally carries an `updated_at` timestamp in the same format, refreshed on every mutation of that resource, and a `version` integer that starts at 1 when the resource is created and increases by exactly 1 on each mutation."

    Design: Corner/entities/video_asset_get_returns_stored_representation
    """
    created = _catalogue_critical_recording(api)
    assert_common_fields(created, 1)

    fetched = get_asset(api, created["id"])

    assert_common_fields(fetched, 1)
    assert_fields(fetched, id=created["id"], created_at=created["created_at"])


# --------------------------------------------------------- request pagination
def _three_requests_from_one_filer(api):
    """One GENERAL_PUBLIC filer with three requests received on the same day."""
    requester = create_requester(api, "Ada Public", "ada@example.org", "GENERAL_PUBLIC")
    first = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0603",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-02T00:00:00Z",
        scope_narrative="First request",
    )
    second = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0604",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-02T00:00:00Z",
        scope_narrative="Second request",
    )
    third = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0605",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-02T00:00:00Z",
        scope_narrative="Third request",
    )
    return {
        "requester_id": requester["id"],
        "ids": [first["id"], second["id"], third["id"]],
    }


def test_the_first_page_counts_the_whole_filtered_set_and_flags_more_rows(api):
    """Three rows on file: limit 2 returns two rows but reports total_count 3 and has_more.

    PRD: "When a list endpoint responds, its `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether further rows exist beyond the returned page."

    Design: Corner/entities/requests_list_paginates_with_total_count_and_has_more
    """
    _three_requests_from_one_filer(api)

    rows, meta = assert_total_count(
        api.list_requests(CLERK_HEADERS, params={"limit": 2, "offset": 0}), 3
    )

    assert len(rows) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True


def test_the_last_page_repeats_the_total_and_clears_has_more(api):
    """Oldest row first: page one is the first two requests and page two the third alone.

    PRD: "Unless a particular endpoint's description states otherwise, list results are ordered by `created_at` ascending — oldest row first."

    Design: Corner/entities/requests_list_paginates_with_total_count_and_has_more
    """
    scenario = _three_requests_from_one_filer(api)
    first_page, _first_meta = assert_list_response(
        api.list_requests(CLERK_HEADERS, params={"limit": 2, "offset": 0})
    )

    second_page, second_meta = assert_total_count(
        api.list_requests(CLERK_HEADERS, params={"limit": 2, "offset": 2}), 3
    )

    assert_ids(first_page, scenario["ids"][:2])
    assert_ids(second_page, scenario["ids"][2:])
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False


# ------------------------------------------------- per-family not-found codes
def test_each_resource_family_answers_with_its_own_not_found_code(api):
    """Nine well-formed but unknown ids yield nine distinct 404 identifiers.

    PRD: "The mapping from path segment to error is fixed: a missing `/requests/{id}` yields `ERR_REQUEST_NOT_FOUND`, `/video-assets/{id}` yields `ERR_VIDEO_ASSET_NOT_FOUND`, `/responsive-records/{id}` yields `ERR_RESPONSIVE_RECORD_NOT_FOUND`, `/exemption-claims/{id}` yields `ERR_EXEMPTION_CLAIM_NOT_FOUND`, `/redaction-tasks/{id}` yields `ERR_REDACTION_TASK_NOT_FOUND`, `/depicted-individuals/{id}` yields `ERR_DEPICTED_INDIVIDUAL_NOT_FOUND`, `/denial-letters/{id}` yields `ERR_DENIAL_LETTER_NOT_FOUND`, `/litigation-holds/{id}` yields `ERR_LITIGATION_HOLD_NOT_FOUND` and `/fee-ledger-entries/{id}` yields `ERR_LEDGER_ENTRY_NOT_FOUND`."

    Design: Corner/entities/unknown_path_ids_return_their_own_not_found_code
    """
    validate_error(api.get_request(NON_EXISTENT_UUID, CLERK_HEADERS), ERR_REQUEST_NOT_FOUND, 404)
    validate_error(
        api.get_video_asset(NON_EXISTENT_UUID, CLERK_HEADERS), ERR_VIDEO_ASSET_NOT_FOUND, 404
    )
    validate_error(
        api.get_responsive_record(NON_EXISTENT_UUID, CLERK_HEADERS),
        ERR_RESPONSIVE_RECORD_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_exemption_claim(NON_EXISTENT_UUID, CLERK_HEADERS),
        ERR_EXEMPTION_CLAIM_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_redaction_task(NON_EXISTENT_UUID, CLERK_HEADERS),
        ERR_REDACTION_TASK_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_depicted_individual(NON_EXISTENT_UUID, CLERK_HEADERS),
        ERR_DEPICTED_INDIVIDUAL_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_denial_letter(NON_EXISTENT_UUID, CLERK_HEADERS), ERR_DENIAL_LETTER_NOT_FOUND, 404
    )
    validate_error(
        api.get_litigation_hold(NON_EXISTENT_UUID, CLERK_HEADERS),
        ERR_LITIGATION_HOLD_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_ledger_entry(NON_EXISTENT_UUID, CLERK_HEADERS), ERR_LEDGER_ENTRY_NOT_FOUND, 404
    )


# ------------------------------------------------------ Requester validation
def test_registering_a_filer_without_an_email_is_a_schema_failure(api):
    """The omitted required field is the only difference between 400 and 201.

    PRD: "Schema validation: the body parses, every required input field is present and non-null, every enumeration field holds a declared value, every integer field is an integer inside its declared range, and pagination parameters are in range — `ERR_VALIDATION`."

    Design: Corner/entities/requester_create_missing_required_email_returns_validation
    """
    without_email = requester_payload("No Email", "noemail@example.org", "GENERAL_PUBLIC")
    without_email.pop("email")

    rejected = api.create_requester(without_email, CLERK_HEADERS)

    validate_error(rejected, ERR_VALIDATION, 400)
    accepted = assert_created(
        api.create_requester(
            requester_payload("No Email", "noemail@example.org", "GENERAL_PUBLIC"),
            CLERK_HEADERS,
        )
    )
    assert_fields(
        accepted,
        full_name="No Email",
        email="noemail@example.org",
        requester_type="GENERAL_PUBLIC",
    )


# ------------------------------------------------------- frozen waiver figures
def _three_filers(api):
    """A media filer, an indigency-certified media filer and a commercial broker."""
    media = create_requester(api, "Mel Media", "mel@press.example", "MEDIA")
    indigent = create_requester(
        api, "Indy Gent", "indy@press.example", "MEDIA", indigency_certified=True
    )
    commercial = create_requester(api, "Comm Broker", "broker@data.example", "COMMERCIAL")
    return {"media": media, "indigent": indigent, "commercial": commercial}


def test_fee_waiver_pct_is_frozen_three_ways_at_registration(api):
    """Indigency beats type at 1.00, plain MEDIA is 0.25 and COMMERCIAL is 0.00.

    PRD: "Registration freezes the filer's statutory waiver fraction once and for all: `fee_waiver_pct` is set to 1.00 when `indigency_certified` is true, otherwise to 0.25 when `requester_type` is `MEDIA`, otherwise to 0.00."

    Design: Corner/entities/requester_fee_waiver_pct_computed_from_type_and_indigency
    """
    filers = _three_filers(api)

    assert_waiver_pct(filers["media"], "fee_waiver_pct", 0.25)
    assert_waiver_pct(filers["indigent"], "fee_waiver_pct", 1.00)
    assert_waiver_pct(filers["commercial"], "fee_waiver_pct", 0.00)
    assert_waiver_pct(get_requester(api, filers["media"]["id"]), "fee_waiver_pct", 0.25)
    assert_waiver_pct(get_requester(api, filers["indigent"]["id"]), "fee_waiver_pct", 1.00)
    assert_waiver_pct(get_requester(api, filers["commercial"]["id"]), "fee_waiver_pct", 0.00)


def test_indigency_certified_defaults_to_false_when_the_flag_is_omitted(api):
    """The media filer who filed no affidavit is stored false, not null and not absent.

    PRD: "Filers are registered by either a `RecordsClerk` or a `RecordsSupervisor` and carry a `full_name`, an `email` used for estimates, notices and denial letters, a `requester_type` drawn from `MEDIA`, `INVOLVED_PARTY`, `ATTORNEY`, `GENERAL_PUBLIC` and `COMMERCIAL`, and an optional `indigency_certified` flag that defaults to false and records whether a certified indigency affidavit was filed."

    Design: Corner/entities/requester_fee_waiver_pct_computed_from_type_and_indigency
    """
    filers = _three_filers(api)

    assert filers["media"]["indigency_certified"] is False
    assert filers["commercial"]["indigency_certified"] is False
    assert filers["indigent"]["indigency_certified"] is True
    assert get_requester(api, filers["media"]["id"])["indigency_certified"] is False


def test_a_newly_registered_filer_holds_no_open_requests(api):
    """No request has been filed yet, so all three counters read zero.

    PRD: "`open_request_count` starts at 0 and thereafter reflects the number of that filer's requests whose `processing_status` is none of `RELEASED`, `DENIED` and `CLOSED`."

    Design: Corner/entities/requester_fee_waiver_pct_computed_from_type_and_indigency
    """
    filers = _three_filers(api)

    for filer in (filers["media"], filers["indigent"], filers["commercial"]):
        assert_fields(filer, open_request_count=0)
        assert_fields(get_requester(api, filer["id"]), open_request_count=0)


# ------------------------------------------- ExemptionClaim system fields
def _record_under_exemption_review(api):
    """One counsel and one RESPONSIVE record on a twenty-minute ROUTINE recording."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0606",
        device_serial="AXON-0606",
        officer_badge="B-1106",
        recorded_start_at="2026-07-27T10:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-27T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0606",
        requested_date_from="2026-07-27T00:00:00Z",
        requested_date_to="2026-07-28T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0606",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Arrest sequence only",
        requested_date_from="2026-07-27T00:00:00Z",
        requested_date_to="2026-07-27T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return {
        "counsel_id": counsel["id"],
        "request_id": request["id"],
        "record_id": record["id"],
    }


def _assert_forged_claim(api, scenario):
    """Assert a staff claim whose payload also tries to dictate the system fields."""
    return api.assert_exemption_claim(
        scenario["record_id"],
        exemption_claim_payload(
            "PERSONAL_PRIVACY",
            "PARTIAL_REDACT",
            claim_source="DEPICTED_OBJECTION",
            status="SUSTAINED",
            id="client-chosen-id",
        ),
        make_counsel_headers(scenario["counsel_id"]),
    )


def test_a_staff_claim_ignores_the_client_supplied_source_and_status(api):
    """The payload's DEPICTED_OBJECTION and SUSTAINED are discarded by the server.

    PRD: "The claim is created with `status` `ASSERTED`, `claim_source` `STAFF_ANALYSIS`, `asserted_by_staff_id` set to the asserting attorney's `X-User-ID`, `depicted_individual_id` null, and `adjudicated_by_staff_id`, `adjudicated_at` and `adjudication_note` all null."

    Design: Corner/entities/exemption_claim_ignores_client_supplied_claim_source_extra_field
    """
    scenario = _record_under_exemption_review(api)

    response = _assert_forged_claim(api, scenario)

    claim = assert_created(response)
    assert_fields(
        claim,
        claim_source="STAFF_ANALYSIS",
        status="ASSERTED",
        asserted_by_staff_id=scenario["counsel_id"],
        depicted_individual_id=None,
        adjudicated_by_staff_id=None,
        adjudicated_at=None,
        adjudication_note=None,
    )


def test_the_claim_identifier_is_server_minted_not_client_chosen(api):
    """The forged id never reaches storage: the row carries a canonical UUID at version 1.

    PRD: "Every persisted resource carries a server-minted `id` in canonical UUID form with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits."

    Design: Corner/entities/exemption_claim_ignores_client_supplied_claim_source_extra_field
    """
    scenario = _record_under_exemption_review(api)

    claim = assert_created(_assert_forged_claim(api, scenario))

    assert claim["id"] != "client-chosen-id"
    assert is_valid_uuid(claim["id"])
    assert_common_fields(claim, 1)


# ------------------------------------------------- RedactionTask enumeration
def _record_ready_for_redaction(api):
    """A level-2 technician and a RESPONSIVE record on a twenty-minute recording."""
    technician = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0607",
        device_serial="AXON-0607",
        officer_badge="B-1107",
        recorded_start_at="2026-07-28T10:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-28T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0607",
        requested_date_from="2026-07-28T00:00:00Z",
        requested_date_to="2026-07-29T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0607",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Arrest sequence only",
        requested_date_from="2026-07-28T00:00:00Z",
        requested_date_to="2026-07-28T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return {
        "tech_id": technician["id"],
        "request_id": request["id"],
        "record_id": record["id"],
    }


def test_an_undeclared_target_type_is_refused_before_any_row_is_written(api):
    """TATTOO is not a declared obscuration target, so nothing is created.

    PRD: "Schema validation: the body parses, every required input field is present and non-null, every enumeration field holds a declared value, every integer field is an integer inside its declared range, and pagination parameters are in range — `ERR_VALIDATION`."

    Design: Corner/entities/redaction_task_rejects_undeclared_target_type_enum
    """
    scenario = _record_ready_for_redaction(api)

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "TATTOO", 0, 60000),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_VALIDATION, 400)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        0,
    )


def test_the_same_payload_with_a_declared_target_opens_a_draft_task(api):
    """FACE is accepted and the task opens with every declared production default.

    PRD: "The task is created at `status` `DRAFT` with `rework_count` 0, `logged_labor_minutes` 0, `approved_labor_minutes` 0 and `defect_codes` as an empty array, and with `qa_reviewer_id`, `qa_window_start_at` and `qa_window_end_at` all null until the first submission books a reviewer."

    Design: Corner/entities/redaction_task_rejects_undeclared_target_type_enum
    """
    scenario = _record_ready_for_redaction(api)

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 0, 60000),
        make_technician_headers(scenario["tech_id"]),
    )

    task = assert_created(response)
    assert_fields(
        task,
        target_type="FACE",
        status="DRAFT",
        rework_count=0,
        logged_labor_minutes=0,
        approved_labor_minutes=0,
        defect_codes=[],
        qa_reviewer_id=None,
        qa_window_start_at=None,
        qa_window_end_at=None,
    )
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        1,
    )


# ------------------------------------------- FeeLedgerEntry immutable posting
def _request_owing_a_deposit(api):
    """A one-hour USE_OF_FORCE recording priced at 4725 cents, so 2363 is due.

    Review 120 plus burden 15 less the sixty-minute allowance is 75 billable
    minutes, 5250 cents of labour, a 525-cent tier-two credit and a 4725-cent
    total, half of which rounds half up to a 2363-cent deposit.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0608",
        device_serial="AXON-0608",
        officer_badge="B-1108",
        recorded_start_at="2026-07-29T10:00:00Z",
        duration_ms=3600000,
        classification="USE_OF_FORCE",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-29T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0608",
        requested_date_from="2026-07-29T00:00:00Z",
        requested_date_to="2026-07-30T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0608",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Full incident video",
        requested_date_from="2026-07-29T00:00:00Z",
        requested_date_to="2026-07-29T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    estimate = create_estimate(api, request["id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    return {
        "request_id": request["id"],
        "requester_id": requester["id"],
        "estimate": estimate,
    }


def test_a_posted_ledger_line_carries_no_version_and_no_updated_at(api):
    """The deposit payment's row exposes id and created_at and nothing else.

    PRD: "The single exception is the cost-recovery ledger entry: because the ledger is append-only and a posted line is never edited, a ledger entry carries only `id` and `created_at` — it has neither `updated_at` nor `version`, and neither field appears in its representation."

    Design: Corner/entities/fee_ledger_entry_is_immutable_and_versionless
    """
    scenario = _request_owing_a_deposit(api)

    response = api.post_payment(
        scenario["request_id"],
        payment_payload(2363, "Deposit paid by card"),
        make_requester_headers(scenario["requester_id"]),
    )

    entry = assert_created(response)
    assert_ledger_entry_fields(entry)
    assert_fields(
        entry,
        entry_type="DEPOSIT_PAYMENT",
        source_kind="DEPOSIT",
        amount_cents=2363,
        reverses_entry_id=None,
        memo="Deposit paid by card",
    )
    assert_money_is_integer_cents(entry, "amount_cents")
    fetched = validate_success(api.get_ledger_entry(entry["id"], SUPERVISOR_HEADERS), 200)
    assert_ledger_entry_fields(fetched)
    assert_fields(fetched, id=entry["id"], entry_type="DEPOSIT_PAYMENT", amount_cents=2363)


def test_the_payment_re_derives_the_request_money_from_the_ledger(api):
    """One positive line makes deposit_paid and deposit_balance both 2363 cents.

    PRD: "A successful payment appends a ledger line with `entry_type` `DEPOSIT_PAYMENT` and `source_kind` `DEPOSIT` carrying the positive amount, then re-derives `deposit_paid_cents` and `deposit_balance_cents`."

    Design: Corner/entities/fee_ledger_entry_is_immutable_and_versionless
    """
    scenario = _request_owing_a_deposit(api)

    post_payment(api, scenario["request_id"], scenario["requester_id"], 2363)

    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        deposit_paid_cents=2363,
        deposit_balance_cents=2363,
        fee_recognized_cents=0,
        waiver_credit_total_cents=0,
    )
    assert_ledger_conservation(request)
    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        1,
    )


def test_the_qualifying_deposit_moves_the_fee_dimension_to_deposit_paid(api):
    """The balance has reached the 2363-cent requirement, so DEPOSIT_DUE closes.

    PRD: "When `fee_status` is `DEPOSIT_DUE` and `deposit_balance_cents` after the payment has reached `deposit_required_cents`, the request moves `DEPOSIT_DUE → DEPOSIT_PAID`; on that specific edge, and only on it, `tolled_days` is frozen and `statutory_deadline_at` is re-struck as described in §3.3."

    Design: Corner/entities/fee_ledger_entry_is_immutable_and_versionless
    """
    scenario = _request_owing_a_deposit(api)
    assert get_request(api, scenario["request_id"])["fee_status"] == "DEPOSIT_DUE"

    post_payment(api, scenario["request_id"], scenario["requester_id"], 2363)

    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="DEPOSIT_PAID",
        deposit_required_cents=2363,
    )


def test_the_request_mirrors_the_active_estimate_money(api):
    """The 4725-cent total and 2363-cent deposit appear on the request unchanged.

    PRD: "The request's `estimated_total_cents` and `deposit_required_cents` mirror the new estimate's corresponding figures — and are 0 whenever no `ACTIVE` estimate exists — and the request's `version` increases by 1."

    Design: Corner/entities/fee_ledger_entry_is_immutable_and_versionless
    """
    scenario = _request_owing_a_deposit(api)

    estimate = scenario["estimate"]

    assert_fields(estimate, estimated_total_cents=4725, deposit_required_cents=2363)
    assert_money_is_integer_cents(estimate, "estimated_total_cents", "deposit_required_cents")
    assert_fields(
        get_request(api, scenario["request_id"]),
        estimated_total_cents=4725,
        deposit_required_cents=2363,
    )


# ------------------------------------- ResponsiveRecord parent and body keys
def _intake_request_and_recording(api):
    """One filer, one recording and one request still sitting at INTAKE."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0609",
        device_serial="AXON-0609",
        officer_badge="B-1109",
        recorded_start_at="2026-07-30T10:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-30T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0609",
        requested_date_from="2026-07-30T00:00:00Z",
        requested_date_to="2026-07-31T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0609",
    )
    return {
        "requester_id": requester["id"],
        "asset_id": asset["id"],
        "request_id": request["id"],
    }


def test_the_unknown_path_parent_wins_over_an_equally_bogus_body_key(api):
    """Both identifiers are unknown, and only the path one is ever examined.

    PRD: "Endpoint paths nest resources, and the identifiers embedded in a path are resolved strictly left to right; the first identifier that resolves to nothing determines the reported error, and no later identifier or body field is examined."

    Design: Corner/entities/responsive_record_creation_rejects_unknown_request_or_asset_fk
    """
    _intake_request_and_recording(api)

    response = api.attach_responsive_record(
        NON_EXISTENT_UUID, responsive_record_payload(OTHER_UNKNOWN_UUID), CLERK_HEADERS
    )

    validate_error(response, ERR_REQUEST_NOT_FOUND, 404)


def test_each_unknown_body_foreign_key_reports_its_own_code(api):
    """An unknown video_asset_id and an unknown requester_id answer differently.

    PRD: "Foreign keys supplied inside a request body are resolved after the path, and each has its own code: an unknown `requester_id` yields `ERR_REQUESTER_NOT_FOUND`; an unknown `video_asset_id` yields `ERR_VIDEO_ASSET_NOT_FOUND`; an unknown `exemption_claim_id` yields `ERR_EXEMPTION_CLAIM_NOT_FOUND`; an unknown `depicted_individual_id` yields `ERR_DEPICTED_INDIVIDUAL_NOT_FOUND`; an unknown `responsive_record_id` yields `ERR_RESPONSIVE_RECORD_NOT_FOUND`; and an unknown `assigned_technician_id`, `qa_reviewer_id` or `asserted_by_staff_id` yields `ERR_STAFF_NOT_FOUND`."

    Design: Corner/entities/responsive_record_creation_rejects_unknown_request_or_asset_fk
    """
    scenario = _intake_request_and_recording(api)

    bad_asset = api.attach_responsive_record(
        scenario["request_id"], responsive_record_payload(OTHER_UNKNOWN_UUID), CLERK_HEADERS
    )
    bad_requester = api.create_request(
        request_payload(
            NON_EXISTENT_UUID,
            subject_incident_number="INC-2026-0609",
            requested_date_from="2026-07-30T00:00:00Z",
            requested_date_to="2026-07-31T00:00:00Z",
            scope_narrative="Orphan request",
        ),
        CLERK_HEADERS,
    )

    validate_error(bad_asset, ERR_VIDEO_ASSET_NOT_FOUND, 404)
    validate_error(bad_requester, ERR_REQUESTER_NOT_FOUND, 404)
    assert_total_count(
        api.list_responsive_records(
            CLERK_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        0,
    )


# -------------------------------- one recording answering two requests at once
def _one_recording_on_two_requests(api):
    """Two filers ask for the same ten-minute recording; Ann's record is kept, Bob's dropped."""
    requester_a = create_requester(api, "Ann One", "ann@example.org", "GENERAL_PUBLIC")
    requester_b = create_requester(api, "Bob Two", "bob@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0610",
        device_serial="AXON-0610",
        officer_badge="B-1110",
        recorded_start_at="2026-07-31T10:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    request_a = create_request(
        api,
        requester_a["id"],
        subject_incident_number="INC-2026-0610",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="Ann's request",
    )
    clarify_scope(
        api,
        request_a["id"],
        scope_narrative="Ann narrowed",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    request_b = create_request(
        api,
        requester_b["id"],
        subject_incident_number="INC-2026-0610",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="Bob's request",
    )
    clarify_scope(
        api,
        request_b["id"],
        scope_narrative="Bob narrowed",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record_a = attach_record(api, request_a["id"], asset["id"])
    record_b = attach_record(api, request_b["id"], asset["id"])
    rule_inclusion(api, record_a["id"], "RESPONSIVE")
    rule_inclusion(api, record_b["id"], "EXCLUDED")
    return {
        "asset_id": asset["id"],
        "request_a": request_a["id"],
        "request_b": request_b["id"],
        "record_a": record_a["id"],
        "record_b": record_b["id"],
    }


def test_the_same_recording_yields_two_independent_per_request_rows(api):
    """Two junction rows on one recording hold opposite inclusion postures.

    PRD: "Second, the same recording can be responsive to many different requests at the same time, each with its own exemption posture, its own redaction work and its own release date; responsiveness is therefore a per-request relationship carrying its own state, never a property of the recording itself."

    Design: Corner/entities/graph_topology_same_asset_serves_two_requests_independently
    """
    scenario = _one_recording_on_two_requests(api)

    record_a = get_record(api, scenario["record_a"])
    record_b = get_record(api, scenario["record_b"])

    assert scenario["record_a"] != scenario["record_b"]
    assert_fields(
        record_a,
        video_asset_id=scenario["asset_id"],
        request_id=scenario["request_a"],
        inclusion_status="RESPONSIVE",
    )
    assert_fields(
        record_b,
        video_asset_id=scenario["asset_id"],
        request_id=scenario["request_b"],
        inclusion_status="EXCLUDED",
    )
    assert_total_count(
        api.list_responsive_records(
            CLERK_HEADERS, params={"video_asset_id": scenario["asset_id"]}
        ),
        2,
    )


def test_each_request_counts_and_advances_on_its_own_ruling(api):
    """Ann's request counts one record and reaches EXEMPTION_REVIEW; Bob's counts none.

    PRD: "A ruling of `RESPONSIVE` moves the record `CANDIDATE → RESPONSIVE` and does considerably more: the request's `responsive_record_count`, `is_critical_incident`, `statutory_deadline_at` and `open_notification_count` are all recomputed — and note that the deadline may jump backwards or forwards here, because the anchor can move from `received_at` to the earliest critical-incident `recorded_start_at` — and the first such ruling bubbles up to advance the request `SCOPING → EXEMPTION_REVIEW`."

    Design: Corner/entities/graph_topology_same_asset_serves_two_requests_independently
    """
    scenario = _one_recording_on_two_requests(api)

    assert_fields(
        get_request(api, scenario["request_a"]),
        responsive_record_count=1,
        processing_status="EXEMPTION_REVIEW",
    )
    assert_fields(
        get_request(api, scenario["request_b"]),
        responsive_record_count=0,
        processing_status="SCOPING",
    )


def test_the_surviving_open_request_alone_keeps_the_recording_locked(api):
    """Bob's exclusion no longer justifies the lock, but Ann's open request does.

    PRD: "`retention_locked` on a recording is true exactly when at least one litigation hold with `status` `ACTIVE` carries a `scope_incident_number` equal to the recording's `incident_number`, or at least one responsive record references the recording with `inclusion_status` among `CANDIDATE`, `RESPONSIVE` and `WITHHELD_IN_FULL` on a request whose `processing_status` is none of `RELEASED`, `DENIED` and `CLOSED`."

    Design: Corner/entities/graph_topology_same_asset_serves_two_requests_independently
    """
    scenario = _one_recording_on_two_requests(api)

    asset = get_asset(api, scenario["asset_id"])

    assert asset["retention_locked"] is True
    assert_fields(asset, disposition_state="SCHEDULED", suspended_by_hold_id=None)


# --------------------------------- display_label uniqueness scoped to one asset
def _two_recordings_one_labelled(api):
    """Two recordings; the first already holds a VICTIM labelled Subject A."""
    asset_one = create_asset(
        api,
        incident_number="INC-2026-0611",
        device_serial="AXON-0611",
        officer_badge="B-1111",
        recorded_start_at="2026-07-31T11:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    asset_two = create_asset(
        api,
        incident_number="INC-2026-0612",
        device_serial="AXON-0612",
        officer_badge="B-1112",
        recorded_start_at="2026-07-31T12:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    individual_one = create_depicted_individual(api, asset_one["id"], "Subject A", "VICTIM")
    return {
        "asset_one": asset_one["id"],
        "asset_two": asset_two["id"],
        "individual_one": individual_one["id"],
    }


def _label_subject_a(api, asset_id):
    """Try to log a WITNESS called Subject A on the given recording."""
    return api.create_depicted_individual(
        asset_id, depicted_individual_payload("Subject A", "WITNESS"), CLERK_HEADERS
    )


def test_a_repeated_label_on_one_recording_is_refused(api):
    """Subject A cannot appear twice on the recording that already holds it.

    PRD: "A `display_label` is unique within one recording, so two depicted individuals on the same `video_asset_id` may not share a label; a collision is rejected with `ERR_DUPLICATE_DEPICTED_LABEL` (HTTP 409)."

    Design: Corner/entities/duplicate_depicted_label_rejected_per_video_asset
    """
    scenario = _two_recordings_one_labelled(api)

    response = _label_subject_a(api, scenario["asset_one"])

    validate_error(response, ERR_DUPLICATE_DEPICTED_LABEL, 409)
    assert_total_count(
        api.list_depicted_individuals(scenario["asset_one"], CLERK_HEADERS), 1
    )


def test_the_same_label_on_a_different_recording_is_accepted(api):
    """Uniqueness is scoped per recording, so Subject A is free on the second one.

    PRD: "A `display_label` is unique within one recording, so two depicted individuals on the same `video_asset_id` may not share a label; a collision is rejected with `ERR_DUPLICATE_DEPICTED_LABEL` (HTTP 409)."

    Design: Corner/entities/duplicate_depicted_label_rejected_per_video_asset
    """
    scenario = _two_recordings_one_labelled(api)
    validate_error(
        _label_subject_a(api, scenario["asset_one"]), ERR_DUPLICATE_DEPICTED_LABEL, 409
    )

    response = _label_subject_a(api, scenario["asset_two"])

    individual_two = assert_created(response)
    assert_fields(
        individual_two,
        video_asset_id=scenario["asset_two"],
        display_label="Subject A",
        relationship="WITNESS",
    )


def test_each_recording_counts_only_its_own_depicted_people(api):
    """The refused duplicate adds nothing; each recording ends with exactly one person.

    PRD: "Either way the recording's `depicted_individual_count` increases by 1."

    Design: Corner/entities/duplicate_depicted_label_rejected_per_video_asset
    """
    scenario = _two_recordings_one_labelled(api)
    _label_subject_a(api, scenario["asset_one"])

    _label_subject_a(api, scenario["asset_two"])

    assert get_asset(api, scenario["asset_one"])["depicted_individual_count"] == 1
    assert get_asset(api, scenario["asset_two"])["depicted_individual_count"] == 1


def test_a_victim_and_a_witness_both_open_at_pending(api):
    """Both relationships require notice, so both rows start at PENDING.

    PRD: "That derivation picks the individual's initial position directly — a row that requires notification is created at `notification_status` `PENDING`, and a row that does not is created at `notification_status` `NOT_REQUIRED`, which is terminal and never gates a release."

    Design: Corner/entities/duplicate_depicted_label_rejected_per_video_asset
    """
    scenario = _two_recordings_one_labelled(api)

    individual_two = assert_created(_label_subject_a(api, scenario["asset_two"]))

    assert_fields(
        get_individual(api, scenario["individual_one"]),
        relationship="VICTIM",
        notification_required=True,
        notification_status="PENDING",
        notice_method=None,
        notified_at=None,
    )
    assert_fields(
        get_individual(api, individual_two["id"]),
        relationship="WITNESS",
        notification_required=True,
        notification_status="PENDING",
        notice_method=None,
    )
