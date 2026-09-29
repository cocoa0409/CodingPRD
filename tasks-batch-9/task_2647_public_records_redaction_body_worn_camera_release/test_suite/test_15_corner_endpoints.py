"""Whole-call endpoint surfaces: packages, invoices, denial letters, lists and the clock.

Each scenario drives one endpoint to the point where its own contract — the
derived package kind, the priority-9 readiness set, the assembled citation
array, the filtered page meta or the frozen instant — is the only thing left
to observe.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import (
    ERR_NO_RELEASABLE_RECORDS,
    ERR_REQUEST_NOT_RELEASE_READY,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_ids,
    assert_ledger_conservation,
    assert_ledger_entry_fields,
    assert_list_response,
    assert_modified,
    assert_money_is_integer_cents,
    assert_total_count,
    assert_waiver_pct,
)
from test_helpers.factories import (
    clock_payload,
    denial_letter_payload,
    invoice_payload,
    release_package_payload,
)
from test_helpers.fixtures import (
    adjudicate,
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_record,
    get_request,
    get_requester,
    get_staff,
    get_task,
    issue_invoice,
    open_task,
    produce_release,
    record_verdict,
    rule_inclusion,
    set_clock,
    submit_for_qa,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_counsel_headers,
    make_reviewer_headers,
)


def _two_records_one_with_an_approved_task(api):
    """Record A holds an APPROVED FACE task; record B's only task was cancelled.

    Overruling record B's PERSONAL_PRIVACY claim cancels the task that
    implemented it, so B ends RESPONSIVE, posture OPEN, with no APPROVED task.
    The passing verdict on record A's task then leaves every task on the
    request terminal, which carries the request REDACTION -> RELEASE_READY.
    """
    tech = create_staff(api, "Tech One", "TECHNICIAN", 1)
    reviewer = create_staff(api, "Reviewer One", "REVIEWER", 2)
    counsel_a = create_staff(api, "Counsel A", "COUNSEL", 3)
    counsel_b = create_staff(api, "Counsel B", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_a = create_asset(
        api,
        incident_number="INC-2026-0651",
        device_serial="AXON-0651A",
        officer_badge="B-1146",
        recorded_start_at="2026-07-11T09:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-11T00:00:00Z",
    )
    asset_b = create_asset(
        api,
        incident_number="INC-2026-0651",
        device_serial="AXON-0651B",
        officer_badge="B-1147",
        recorded_start_at="2026-07-11T09:05:00Z",
        duration_ms=1800000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-11T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0651",
        requested_date_from="2026-07-11T00:00:00Z",
        requested_date_to="2026-07-12T00:00:00Z",
        scope_narrative="Both cameras on INC-2026-0651",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Both body cameras, full shift",
        requested_date_from="2026-07-11T00:00:00Z",
        requested_date_to="2026-07-11T23:59:59Z",
    )
    record_a = attach_record(api, request["id"], asset_a["id"])
    record_b = attach_record(api, request["id"], asset_b["id"])
    rule_inclusion(api, record_a["id"], "RESPONSIVE")
    rule_inclusion(api, record_b["id"], "RESPONSIVE")
    claim_b = assert_claim(
        api, record_b["id"], counsel_a["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT"
    )
    task_a = open_task(api, record_a["id"], tech["id"], "FACE", 0, 3600000)
    task_b = open_task(api, record_b["id"], tech["id"], "FACE", 0, 1800000, claim_b["id"])
    adjudicate(
        api,
        claim_b["id"],
        counsel_b["id"],
        "OVERRULED",
        adjudication_note="No privacy interest on camera B",
    )
    submit_for_qa(
        api, task_a["id"], tech["id"], reviewer["id"], 20,
        "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z",
    )
    record_verdict(api, task_a["id"], reviewer["id"], "PASS")
    return {
        "request_id": request["id"],
        "record_a_id": record_a["id"],
        "record_b_id": record_b["id"],
        "task_a_id": task_a["id"],
        "task_b_id": task_b["id"],
    }


def test_the_package_comes_back_interim_because_record_b_has_no_approved_task(api):
    """One 60-minute record goes out on one DVD; the 30-minute record is left behind.

    PRD: "Its `package_kind` is **derived and never supplied**: it is `FINAL` when the eligible set covered every `RESPONSIVE` record of the request, and `INTERIM` when `RESPONSIVE` records remain."

    Design: Corner/endpoints/interim_package_covers_only_the_record_with_an_approved_task
    """
    scenario = _two_records_one_with_an_approved_task(api)
    assert_fields(get_request(api, scenario["request_id"]), processing_status="RELEASE_READY")
    assert_fields(get_task(api, scenario["task_a_id"]), status="APPROVED")
    assert_fields(get_task(api, scenario["task_b_id"]), status="CANCELLED")
    assert_fields(
        get_record(api, scenario["record_b_id"]),
        release_posture="OPEN",
        unadjudicated_claim_count=0,
    )

    response = api.create_release_package(
        scenario["request_id"], release_package_payload("DVD"), CLERK_HEADERS
    )

    package = assert_created(response)
    assert_fields(
        package,
        package_kind="INTERIM",
        included_record_count=1,
        produced_minutes=60,
        disc_count=1,
        production_cost_cents=500,
        waived_notification_count=0,
        released_at="2026-08-01T00:00:00Z",
    )
    assert_money_is_integer_cents(package, "production_cost_cents")
    assert_fields(
        get_record(api, scenario["record_a_id"]),
        inclusion_status="RELEASED",
        released_at="2026-08-01T00:00:00Z",
    )
    assert_fields(get_record(api, scenario["record_b_id"]), inclusion_status="RESPONSIVE")
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="PARTIALLY_RELEASED",
        billable_labor_minutes=20,
    )


def test_a_second_package_finds_an_empty_eligible_set(api):
    """Record A is already RELEASED and record B is still ineligible, so nothing remains.

    PRD: "Beyond those, an eligible set that comes out empty after the sweep yields `ERR_NO_RELEASABLE_RECORDS`, and a request whose `fee_status` is `DEPOSIT_DUE` with `deposit_paid_cents` below `deposit_required_cents` yields `ERR_DEPOSIT_UNPAID`."

    Design: Corner/endpoints/interim_package_covers_only_the_record_with_an_approved_task
    """
    scenario = _two_records_one_with_an_approved_task(api)
    produce_release(api, scenario["request_id"], "DVD")

    response = api.create_release_package(
        scenario["request_id"], release_package_payload("DVD"), CLERK_HEADERS
    )

    validate_error(response, ERR_NO_RELEASABLE_RECORDS, 409)
    assert_total_count(
        api.list_release_packages(scenario["request_id"], CLERK_HEADERS), 1
    )
    assert_fields(
        get_request(api, scenario["request_id"]), processing_status="PARTIALLY_RELEASED"
    )


def _release_ready_request_with_an_estimate(api):
    """One 60-minute ROUTINE record, one APPROVED 20-minute FACE task, fee ESTIMATED.

    Review minutes 60 and baseline obscuration 15 give billable minutes of
    60 + 15 - 60 = 15, so the estimate lands at 1050 cents with no deposit and
    the fee dimension sits at ESTIMATED — which the invoice gate accepts. Only
    the processing dimension can therefore refuse the first invoice attempt.
    """
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0652",
        device_serial="AXON-0652",
        officer_badge="B-1148",
        recorded_start_at="2026-07-12T14:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-12T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0652",
        requested_date_from="2026-07-12T00:00:00Z",
        requested_date_to="2026-07-13T00:00:00Z",
        scope_narrative="Traffic stop footage for INC-2026-0652",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Whole hour of the stop",
        requested_date_from="2026-07-12T00:00:00Z",
        requested_date_to="2026-07-12T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    estimate = create_estimate(api, request["id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 3600000)
    submit_for_qa(
        api, task["id"], tech["id"], reviewer["id"], 20,
        "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z",
    )
    record_verdict(api, task["id"], reviewer["id"], "PASS")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "task_id": task["id"],
        "estimate": estimate,
    }


def test_invoicing_is_refused_while_the_request_is_only_release_ready(api):
    """RELEASE_READY is outside the invoice's accepted set even with an ESTIMATED fee.

    PRD: "Producing a package requires `processing_status` to be `RELEASE_READY` or `PARTIALLY_RELEASED`; invoicing requires it to be `RELEASED`, `PARTIALLY_RELEASED` or `DENIED`."

    Design: Corner/endpoints/invoice_is_refused_in_release_ready_then_priced_after_release
    """
    scenario = _release_ready_request_with_an_estimate(api)
    assert_fields(
        scenario["estimate"],
        billable_minutes=15,
        estimated_labor_cents=1050,
        media_production_cents=0,
        subtotal_cents=1050,
        estimated_total_cents=1050,
        deposit_required_cents=0,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASE_READY",
        fee_status="ESTIMATED",
    )

    response = api.issue_invoice(
        scenario["request_id"], invoice_payload("Too early"), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_REQUEST_NOT_RELEASE_READY, 409)
    assert_fields(
        get_request(api, scenario["request_id"]),
        invoiced_total_cents=0,
        fee_status="ESTIMATED",
        processing_status="RELEASE_READY",
    )
    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        0,
    )


def test_the_final_download_package_costs_nothing_to_produce(api):
    """The only RESPONSIVE record goes out, so the package is FINAL and free.

    PRD: "For `media_type` `DIGITAL_DOWNLOAD` the `disc_count` is 0 and the cost is 0 cents."

    Design: Corner/endpoints/invoice_is_refused_in_release_ready_then_priced_after_release
    """
    scenario = _release_ready_request_with_an_estimate(api)

    response = api.create_release_package(
        scenario["request_id"],
        release_package_payload("DIGITAL_DOWNLOAD"),
        CLERK_HEADERS,
    )

    package = assert_created(response)
    assert_fields(
        package,
        package_kind="FINAL",
        included_record_count=1,
        produced_minutes=60,
        disc_count=0,
        production_cost_cents=0,
    )
    assert_fields(get_record(api, scenario["record_id"]), inclusion_status="RELEASED")
    assert_fields(get_request(api, scenario["request_id"]), processing_status="RELEASED")


def test_the_invoice_prices_the_approved_task_at_its_complexity_factor(api):
    """Twenty approved FACE minutes at 4200 cents an hour price the whole invoice at 1400.

    PRD: "**First**, take the request's redaction tasks whose `status` is `APPROVED`, ordered by `created_at` ascending, and price each one on its own: that task's `approved_labor_minutes` divided by sixty, multiplied by the hourly rate of 4200 cents, multiplied by the complexity factor of its `target_type` — 1.00 for `FACE`, 0.85 for `LICENSE_PLATE`, 1.15 for `AUDIO_IDENTIFIER` and 1.30 for `PROTECTED_CONTENT` — and the result rounded half up to a whole cent."

    Design: Corner/endpoints/invoice_is_refused_in_release_ready_then_priced_after_release
    """
    scenario = _release_ready_request_with_an_estimate(api)
    produce_release(api, scenario["request_id"], "DIGITAL_DOWNLOAD")

    response = api.issue_invoice(
        scenario["request_id"], invoice_payload("Final invoice"), SUPERVISOR_HEADERS
    )

    assert_modified(response)
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        invoiced_total_cents=1400,
        fee_recognized_cents=1400,
        waiver_credit_total_cents=0,
        deposit_paid_cents=0,
        deposit_balance_cents=-1400,
    )
    assert_money_is_integer_cents(request, "invoiced_total_cents", "deposit_balance_cents")
    assert_ledger_conservation(request)
    assert_fields(get_task(api, scenario["task_id"]), approved_labor_minutes=20)


def test_the_zero_review_and_media_components_are_never_written_as_lines(api):
    """The released hour is fully absorbed by the free allowance, leaving one labour line.

    PRD: "Any component that computes to zero is skipped entirely rather than written as a zero line."

    Design: Corner/endpoints/invoice_is_refused_in_release_ready_then_priced_after_release
    """
    scenario = _release_ready_request_with_an_estimate(api)
    produce_release(api, scenario["request_id"], "DIGITAL_DOWNLOAD")

    issue_invoice(api, scenario["request_id"], memo="Final invoice")

    rows, _meta = assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        1,
    )
    assert_ledger_entry_fields(rows[0])
    assert_fields(
        rows[0],
        entry_type="LABOR_CHARGE",
        source_kind="INVOICE",
        amount_cents=-1400,
        request_id=scenario["request_id"],
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="INVOICED",
        processing_status="RELEASED",
    )


def _request_withheld_in_full_on_two_records(api):
    """Three sustained full-withhold claims over two records, two distinct citations.

    Both records carry a sustained `ONGOING_INVESTIGATION` claim, so its citation
    appears twice in the raw set, and record A additionally carries a sustained
    `PERSONAL_PRIVACY` claim. Every non-excluded record therefore sits at
    WITHHELD_IN_FULL with no unadjudicated claim left, which is what a FULL
    denial requires.
    """
    counsel_a = create_staff(api, "Counsel A", "COUNSEL", 3)
    counsel_b = create_staff(api, "Counsel B", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_a = create_asset(
        api,
        incident_number="INC-2026-0653",
        device_serial="AXON-0653A",
        officer_badge="B-1149",
        recorded_start_at="2026-07-13T20:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-13T00:00:00Z",
    )
    asset_b = create_asset(
        api,
        incident_number="INC-2026-0653",
        device_serial="AXON-0653B",
        officer_badge="B-1150",
        recorded_start_at="2026-07-13T20:05:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-13T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0653",
        requested_date_from="2026-07-13T00:00:00Z",
        requested_date_to="2026-07-14T00:00:00Z",
        scope_narrative="All footage from INC-2026-0653",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Both cameras, whole encounter",
        requested_date_from="2026-07-13T00:00:00Z",
        requested_date_to="2026-07-13T23:59:59Z",
    )
    record_a = attach_record(api, request["id"], asset_a["id"])
    record_b = attach_record(api, request["id"], asset_b["id"])
    rule_inclusion(api, record_a["id"], "RESPONSIVE")
    rule_inclusion(api, record_b["id"], "RESPONSIVE")
    claim_one = assert_claim(
        api, record_a["id"], counsel_a["id"], "ONGOING_INVESTIGATION", "FULL_WITHHOLD"
    )
    claim_two = assert_claim(
        api, record_a["id"], counsel_a["id"], "PERSONAL_PRIVACY", "FULL_WITHHOLD"
    )
    claim_three = assert_claim(
        api, record_b["id"], counsel_a["id"], "ONGOING_INVESTIGATION", "FULL_WITHHOLD"
    )
    for claim_id in (claim_one["id"], claim_two["id"], claim_three["id"]):
        adjudicate(
            api,
            claim_id,
            counsel_b["id"],
            "SUSTAINED",
            adjudication_note="Active criminal investigation",
        )
    return {
        "request_id": request["id"],
        "requester_id": requester["id"],
        "record_a_id": record_a["id"],
        "record_b_id": record_b["id"],
        "counsel_a_id": counsel_a["id"],
    }


def test_the_letter_deduplicates_and_sorts_the_sustained_citations(api):
    """Three sustained claims over two citations produce a two-entry sorted array.

    PRD: "Its `statutory_citations` array is assembled from the distinct `statutory_citation` values of the claims with `status` `SUSTAINED` on this request's records, deduplicated and sorted ascending as strings."

    Design: Corner/endpoints/full_denial_letter_derives_sorted_deduplicated_citations
    """
    scenario = _request_withheld_in_full_on_two_records(api)
    assert_fields(get_record(api, scenario["record_a_id"]), inclusion_status="WITHHELD_IN_FULL")
    assert_fields(get_record(api, scenario["record_b_id"]), inclusion_status="WITHHELD_IN_FULL")

    response = api.issue_denial_letter(
        scenario["request_id"],
        denial_letter_payload("FULL", "Petition the circuit court within thirty days"),
        make_counsel_headers(scenario["counsel_a_id"]),
    )

    letter = assert_created(response)
    assert letter["statutory_citations"] == ["119.071(2)(c)", "119.071(4)(d)"]
    assert_fields(letter, status="ISSUED", issued_at="2026-08-01T00:00:00Z", denial_type="FULL")


def test_the_letter_derives_its_appeal_authority_and_thirty_day_deadline(api):
    """A FULL denial points at the superior court and closes for appeal on 31 August.

    PRD: "Its `appeal_authority` is derived from the type: `SUPERIOR_COURT` when `denial_type` is `FULL`, `DISTRICT_ATTORNEY` when it is `PARTIAL`."

    Design: Corner/endpoints/full_denial_letter_derives_sorted_deduplicated_citations
    """
    scenario = _request_withheld_in_full_on_two_records(api)

    response = api.issue_denial_letter(
        scenario["request_id"],
        denial_letter_payload("FULL", "Petition the circuit court within thirty days"),
        make_counsel_headers(scenario["counsel_a_id"]),
    )

    letter = assert_created(response)
    assert_fields(
        letter,
        appeal_authority="SUPERIOR_COURT",
        appeal_deadline_at="2026-08-31T00:00:00Z",
        withheld_record_count=2,
        appeal_grounds=None,
        appeal_filed_at=None,
        appeal_decided_at=None,
    )


def test_the_full_denial_moves_the_request_and_frees_the_filers_slot(api):
    """Issuing the letter carries the request to DENIED and drops the open count to zero.

    PRD: "A `FULL` denial then moves the request `EXEMPTION_REVIEW → DENIED` and decrements the filer's `open_request_count` by 1; a `PARTIAL` denial moves `processing_status` not at all and only records the citations alongside the release it accompanies."

    Design: Corner/endpoints/full_denial_letter_derives_sorted_deduplicated_citations
    """
    scenario = _request_withheld_in_full_on_two_records(api)
    assert_fields(get_request(api, scenario["request_id"]), processing_status="EXEMPTION_REVIEW")
    assert_fields(get_requester(api, scenario["requester_id"]), open_request_count=1)

    api.issue_denial_letter(
        scenario["request_id"],
        denial_letter_payload("FULL", "Petition the circuit court within thirty days"),
        make_counsel_headers(scenario["counsel_a_id"]),
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="DENIED",
        unadjudicated_claim_count=0,
    )
    assert_fields(get_requester(api, scenario["requester_id"]), open_request_count=0)
    assert_total_count(
        api.list_denial_letters(scenario["request_id"], CLERK_HEADERS), 1
    )


def _three_tasks_two_booked_with_one_reviewer(api):
    """Three tasks on one record, created FACE then LICENSE_PLATE then AUDIO_IDENTIFIER.

    The first two are booked with the same reviewer in windows thirty-one
    minutes apart, so both sit at QA_PENDING; the audio task is never
    submitted and stays at DRAFT with no reviewer of its own.
    """
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0654",
        device_serial="AXON-0654",
        officer_badge="B-1151",
        recorded_start_at="2026-07-14T07:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-14T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0654",
        requested_date_from="2026-07-14T00:00:00Z",
        requested_date_to="2026-07-15T00:00:00Z",
        scope_narrative="Twenty minutes of contact on INC-2026-0654",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Whole twenty minutes",
        requested_date_from="2026-07-14T00:00:00Z",
        requested_date_to="2026-07-14T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    face = open_task(api, record["id"], tech["id"], "FACE", 0, 1200000)
    plate = open_task(api, record["id"], tech["id"], "LICENSE_PLATE", 0, 1200000)
    audio = open_task(api, record["id"], tech["id"], "AUDIO_IDENTIFIER", 0, 1200000)
    submit_for_qa(
        api, face["id"], tech["id"], reviewer["id"], 12,
        "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z",
    )
    submit_for_qa(
        api, plate["id"], tech["id"], reviewer["id"], 8,
        "2026-08-02T10:01:00Z", "2026-08-02T10:31:00Z",
    )
    return {
        "record_id": record["id"],
        "reviewer_id": reviewer["id"],
        "face_id": face["id"],
        "plate_id": plate["id"],
        "audio_id": audio["id"],
    }


def test_the_record_filter_returns_all_three_tasks_oldest_first(api):
    """Every task on the record comes back in creation order on a single page.

    PRD: "Unless a particular endpoint's description states otherwise, list results are ordered by `created_at` ascending — oldest row first."

    Design: Corner/endpoints/task_list_filters_compose_with_offset_pagination
    """
    scenario = _three_tasks_two_booked_with_one_reviewer(api)

    rows, meta = assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        3,
    )

    assert_ids(rows, [scenario["face_id"], scenario["plate_id"], scenario["audio_id"]])
    assert meta["has_more"] is False
    assert_fields(
        get_task(api, scenario["audio_id"]),
        status="DRAFT",
        qa_reviewer_id=None,
        logged_labor_minutes=0,
    )
    assert_fields(get_staff(api, scenario["reviewer_id"]), open_qa_assignment_count=2)


def test_the_reviewer_filter_reports_two_matches_on_a_one_row_page(api):
    """total_count counts the filtered rows before the page of one is cut.

    PRD: "When a list endpoint responds, its `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether further rows exist beyond the returned page."

    Design: Corner/endpoints/task_list_filters_compose_with_offset_pagination
    """
    scenario = _three_tasks_two_booked_with_one_reviewer(api)

    rows, meta = assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS,
            params={"qa_reviewer_id": scenario["reviewer_id"], "limit": 1, "offset": 0},
        ),
        2,
    )

    assert_ids(rows, [scenario["face_id"]])
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True


def test_the_second_page_of_the_reviewer_filter_skips_the_first_row(api):
    """An offset of one lands on the plate task and closes has_more.

    PRD: "`offset` controls how many rows are skipped before the page begins; it defaults to 0 and must not be negative."

    Design: Corner/endpoints/task_list_filters_compose_with_offset_pagination
    """
    scenario = _three_tasks_two_booked_with_one_reviewer(api)

    rows, meta = assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS,
            params={"qa_reviewer_id": scenario["reviewer_id"], "limit": 1, "offset": 1},
        ),
        2,
    )

    assert_ids(rows, [scenario["plate_id"]])
    assert meta["offset"] == 1
    assert meta["has_more"] is False


def test_a_limit_of_one_hundred_and_one_is_a_schema_failure(api):
    """One past the maximum page size is rejected before any row is read.

    PRD: "A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is a schema failure and is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/endpoints/task_list_filters_compose_with_offset_pagination
    """
    scenario = _three_tasks_two_booked_with_one_reviewer(api)

    response = api.list_redaction_tasks(
        CLERK_HEADERS,
        params={"responsive_record_id": scenario["record_id"], "limit": 101},
    )

    validate_error(response, ERR_VALIDATION, 400)


def _deposit_due_request_received_in_september(api):
    """A 120-minute request priced on DVD in September, with both instants frozen.

    Review minutes 120 plus baseline obscuration 30 less the sixty-minute
    allowance give 90 billable minutes, so the estimate is 6300 cents of labour
    plus one 500-cent disc, a 6800-cent subtotal in the 0.10 public-interest
    tier, a 680-cent credit, a 6120-cent total and a 3060-cent deposit. The fee
    dimension therefore enters DEPOSIT_DUE while the clock reads September.
    """
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    set_clock(api, "2026-09-10T12:00:00Z")
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0655",
        device_serial="AXON-0655",
        officer_badge="B-1152",
        recorded_start_at="2026-09-01T08:00:00Z",
        duration_ms=7200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-09-01T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        received_at="2026-09-10T12:00:00Z",
        subject_incident_number="INC-2026-0655",
        requested_date_from="2026-09-01T00:00:00Z",
        requested_date_to="2026-09-02T00:00:00Z",
        scope_narrative="Two hours of patrol footage for INC-2026-0655",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Both hours, unedited",
        requested_date_from="2026-09-01T00:00:00Z",
        requested_date_to="2026-09-01T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    estimate = create_estimate(api, request["id"], "PRESUMPTIVE", "DVD")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "reviewer_id": reviewer["id"],
        "estimate_id": estimate["id"],
    }


def test_rewinding_the_clock_mutates_no_entity(api):
    """Moving the clock five weeks backwards leaves the request's version untouched.

    PRD: "A test-driving capability accepts a `current_utc` instant and moves the logical clock to it; the call mutates no entity, and subsequent reads of the clock return the supplied value."

    Design: Corner/endpoints/clock_writes_nothing_and_frozen_instants_survive_a_rewind
    """
    scenario = _deposit_due_request_received_in_september(api)
    before = get_request(api, scenario["request_id"])

    get_success_data(
        api.set_clock(
            clock_payload("2026-08-01T00:00:00Z"),
            make_reviewer_headers(scenario["reviewer_id"]),
        )
    )

    after = get_request(api, scenario["request_id"])
    assert_fields(
        after,
        version=before["version"],
        updated_at=before["updated_at"],
        fee_status="DEPOSIT_DUE",
        processing_status="EXEMPTION_REVIEW",
    )
    assert_fields(get_record(api, scenario["record_id"]), inclusion_status="RESPONSIVE")


def test_the_deposit_due_instant_survives_the_rewind(api):
    """The due date stays thirty days past the September pricing, not past the new clock.

    PRD: "`deposit_due_at` itself is set when the fee dimension first enters `DEPOSIT_DUE`, at the logical clock of that moment advanced by thirty whole days, and is null until then."

    Design: Corner/endpoints/clock_writes_nothing_and_frozen_instants_survive_a_rewind
    """
    scenario = _deposit_due_request_received_in_september(api)

    get_success_data(
        api.set_clock(
            clock_payload("2026-08-01T00:00:00Z"),
            make_reviewer_headers(scenario["reviewer_id"]),
        )
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        deposit_due_at="2026-10-10T12:00:00Z",
        estimated_total_cents=6120,
        deposit_required_cents=3060,
        deposit_paid_cents=0,
    )
    rows, _meta = assert_list_response(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS)
    )
    estimate = rows[0]
    assert_fields(
        estimate,
        id=scenario["estimate_id"],
        status="ACTIVE",
        billable_minutes=90,
        estimated_labor_cents=6300,
        media_production_cents=500,
        subtotal_cents=6800,
        waiver_credit_cents=680,
        estimated_total_cents=6120,
    )
    assert_waiver_pct(estimate, "effective_waiver_pct", 0.10)


def test_the_statutory_deadline_survives_the_rewind(api):
    """The twenty-day floor is measured from received_at and is never re-struck by the clock.

    PRD: "**Step three applies a floor guard**: `statutory_deadline_at` is the later of the anchor advanced by the budget in whole days, and `received_at` advanced by twenty whole days."

    Design: Corner/endpoints/clock_writes_nothing_and_frozen_instants_survive_a_rewind
    """
    scenario = _deposit_due_request_received_in_september(api)

    get_success_data(
        api.set_clock(
            clock_payload("2026-08-01T00:00:00Z"),
            make_reviewer_headers(scenario["reviewer_id"]),
        )
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        received_at="2026-09-10T12:00:00Z",
        statutory_deadline_at="2026-09-30T12:00:00Z",
        tolled_days=0,
        is_critical_incident=False,
    )
