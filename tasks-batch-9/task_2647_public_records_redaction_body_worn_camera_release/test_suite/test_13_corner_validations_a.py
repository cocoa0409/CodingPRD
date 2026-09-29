"""Validation refusals and the identical call that succeeds once the defect is cured.

Every scenario below pins one guard from the rejection ladder: the commercial
open-request limit, the clarification limit, responsive-record uniqueness, the
ordered intake window, the estimate-basis gate, the citation table, the clip
range, the certification ladder and the two segregation-of-duties pairs. Each
refusal is checked to have changed nothing at all.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_CERTIFICATION_INSUFFICIENT,
    ERR_CITATION_MISMATCH,
    ERR_DUPLICATE_RESPONSIVE_RECORD,
    ERR_ESTIMATE_BASIS_NOT_PERMITTED,
    ERR_INVALID_CLIP_RANGE,
    ERR_INVALID_TIME_RANGE,
    ERR_OPEN_REQUEST_LIMIT,
    ERR_SCOPE_CLARIFICATION_LIMIT,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_created,
    assert_fields,
    assert_modified,
    assert_money_is_integer_cents,
    assert_total_count,
    assert_waiver_pct,
)
from test_helpers.factories import (
    adjudication_payload,
    exemption_claim_payload,
    fee_estimate_payload,
    redaction_task_payload,
    request_payload,
    responsive_record_payload,
    scope_clarification_payload,
    submit_qa_payload,
)
from test_helpers.fixtures import (
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_claim,
    get_record,
    get_request,
    get_requester,
    get_staff,
    get_task,
    open_task,
    request_version,
    rule_inclusion,
)
from test_helpers.test_users import CLERK_HEADERS, make_counsel_headers, make_technician_headers


# --------------------------------------------- the commercial open-request cap
def _commercial_filer_with_two_open_requests(api):
    """A COMMERCIAL filer holding two INTAKE requests, plus an unlimited filer."""
    commercial = create_requester(api, "Bulk Data LLC", "ops@bulkdata.example", "COMMERCIAL")
    public = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    create_request(
        api,
        commercial["id"],
        subject_incident_number="INC-2026-0631",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-02T00:00:00Z",
        scope_narrative="Batch one",
    )
    create_request(
        api,
        commercial["id"],
        subject_incident_number="INC-2026-0632",
        requested_date_from="2026-07-02T00:00:00Z",
        requested_date_to="2026-07-03T00:00:00Z",
        scope_narrative="Batch two",
    )
    return {"commercial_id": commercial["id"], "public_id": public["id"]}


def _third_commercial_request(api, commercial_id):
    """The third intake, taken while the pre-insert count is still two."""
    return api.create_request(
        request_payload(
            commercial_id,
            subject_incident_number="INC-2026-0633",
            requested_date_from="2026-07-03T00:00:00Z",
            requested_date_to="2026-07-04T00:00:00Z",
            scope_narrative="Batch three",
        ),
        CLERK_HEADERS,
    )


def test_a_fourth_open_commercial_request_is_refused(api):
    """The third intake lands at a pre-insert count of two; the fourth is refused.

    PRD: "A filer whose `requester_type` is `COMMERCIAL` may hold at most three requests whose `processing_status` is none of `RELEASED`, `DENIED` and `CLOSED`, and the count is taken **before** the new row would be inserted: a commercial filer already holding three open requests is refused with `ERR_OPEN_REQUEST_LIMIT`, while one holding two is accepted and ends up with three."

    Design: Corner/validations/commercial_requester_is_refused_a_fourth_open_request
    """
    scenario = _commercial_filer_with_two_open_requests(api)

    third = _third_commercial_request(api, scenario["commercial_id"])
    accepted = assert_created(third)
    assert_fields(accepted, processing_status="INTAKE")
    assert get_requester(api, scenario["commercial_id"])["open_request_count"] == 3

    fourth = api.create_request(
        request_payload(
            scenario["commercial_id"],
            subject_incident_number="INC-2026-0634",
            requested_date_from="2026-07-04T00:00:00Z",
            requested_date_to="2026-07-05T00:00:00Z",
            scope_narrative="Batch four",
        ),
        CLERK_HEADERS,
    )

    validate_error(fourth, ERR_OPEN_REQUEST_LIMIT, 409)
    assert get_requester(api, scenario["commercial_id"])["open_request_count"] == 3
    assert_total_count(
        api.list_requests(CLERK_HEADERS, params={"requester_id": scenario["commercial_id"]}), 3
    )


def test_a_general_public_filer_is_not_rate_limited(api):
    """The cap is scoped to COMMERCIAL, so a GENERAL_PUBLIC intake is untouched by it.

    PRD: "No other `requester_type` is limited."

    Design: Corner/validations/commercial_requester_is_refused_a_fourth_open_request
    """
    scenario = _commercial_filer_with_two_open_requests(api)
    assert_created(_third_commercial_request(api, scenario["commercial_id"]))

    response = api.create_request(
        request_payload(
            scenario["public_id"],
            subject_incident_number="INC-2026-0635",
            requested_date_from="2026-07-05T00:00:00Z",
            requested_date_to="2026-07-06T00:00:00Z",
            scope_narrative="Unaffected requester",
        ),
        CLERK_HEADERS,
    )

    created = assert_created(response)
    assert_fields(created, processing_status="INTAKE")
    assert get_requester(api, scenario["public_id"])["open_request_count"] == 1
    assert get_requester(api, scenario["commercial_id"])["open_request_count"] == 3


# ------------------------------------------------ the clarification allowance
def _request_awaiting_clarification(api):
    """One GENERAL_PUBLIC filer's request sitting at INTAKE with a broad scope."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0636",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-31T00:00:00Z",
        scope_narrative="Everything in July",
    )
    return {"requester_id": requester["id"], "request_id": request["id"]}


def test_two_clarifications_are_accepted_and_counted(api):
    """The first clarification leaves INTAKE and the second is a legal SCOPING self-loop.

    PRD: "From `INTAKE` it advances the request `INTAKE → SCOPING`; from `SCOPING` it is a legal self-loop, and each loop re-runs every side effect below, which is precisely how a second clarification supersedes the first."

    Design: Corner/validations/third_scope_clarification_is_refused
    """
    scenario = _request_awaiting_clarification(api)

    first = api.clarify_scope(
        scenario["request_id"],
        scope_clarification_payload(
            request_version(api, scenario["request_id"]),
            scope_narrative="First narrowing",
            requested_date_from="2026-07-01T00:00:00Z",
            requested_date_to="2026-07-15T00:00:00Z",
        ),
        CLERK_HEADERS,
    )
    once = assert_modified(first)
    assert_fields(
        once,
        processing_status="SCOPING",
        scope_clarification_count=1,
        scope_narrative="First narrowing",
    )

    second = api.clarify_scope(
        scenario["request_id"],
        scope_clarification_payload(
            once["version"],
            scope_narrative="Second narrowing",
            requested_date_from="2026-07-01T00:00:00Z",
            requested_date_to="2026-07-07T00:00:00Z",
        ),
        CLERK_HEADERS,
    )

    twice = assert_modified(second)
    assert_fields(
        twice,
        processing_status="SCOPING",
        scope_clarification_count=2,
        scope_narrative="Second narrowing",
    )
    assert twice["version"] == once["version"] + 1


def test_a_third_scope_clarification_is_refused(api):
    """At a count of two the allowance is spent, and the second narrowing stands.

    PRD: "A request accepts at most two clarifications in total: a further clarification attempted once `scope_clarification_count` has already reached 2 is refused with `ERR_SCOPE_CLARIFICATION_LIMIT`."

    Design: Corner/validations/third_scope_clarification_is_refused
    """
    scenario = _request_awaiting_clarification(api)
    clarify_scope(
        api,
        scenario["request_id"],
        scope_narrative="First narrowing",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-15T00:00:00Z",
    )
    clarify_scope(
        api,
        scenario["request_id"],
        scope_narrative="Second narrowing",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-07T00:00:00Z",
    )
    before = get_request(api, scenario["request_id"])

    response = api.clarify_scope(
        scenario["request_id"],
        scope_clarification_payload(
            before["version"],
            scope_narrative="Third narrowing",
            requested_date_from="2026-07-01T00:00:00Z",
            requested_date_to="2026-07-02T00:00:00Z",
        ),
        CLERK_HEADERS,
    )

    validate_error(response, ERR_SCOPE_CLARIFICATION_LIMIT, 409)
    assert_fields(
        get_request(api, scenario["request_id"]),
        scope_clarification_count=2,
        scope_narrative="Second narrowing",
        processing_status="SCOPING",
        version=before["version"],
    )


# ----------------------------------------- one recording, one responsive record
def _request_with_one_attached_recording(api):
    """A clarified request carrying one CANDIDATE record over a ten-minute recording."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0637",
        device_serial="AXON-0637",
        officer_badge="B-1132",
        recorded_start_at="2026-07-23T12:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-23T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0637",
        requested_date_from="2026-07-23T00:00:00Z",
        requested_date_to="2026-07-24T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0637",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Single unit",
        requested_date_from="2026-07-23T00:00:00Z",
        requested_date_to="2026-07-23T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    return {
        "asset_id": asset["id"],
        "request_id": request["id"],
        "record_id": record["id"],
    }


def test_the_same_recording_cannot_be_attached_twice(api):
    """Uniqueness is on the (request_id, video_asset_id) pair, so the second attach fails.

    PRD: "A recording may be attached to a given request only once, so a second attempt to create a responsive record for the same combination of `request_id` and `video_asset_id` is rejected with `ERR_DUPLICATE_RESPONSIVE_RECORD` (HTTP 409)."

    Design: Corner/validations/same_recording_cannot_be_attached_twice_to_one_request
    """
    scenario = _request_with_one_attached_recording(api)

    response = api.attach_responsive_record(
        scenario["request_id"], responsive_record_payload(scenario["asset_id"]), CLERK_HEADERS
    )

    validate_error(response, ERR_DUPLICATE_RESPONSIVE_RECORD, 409)
    assert get_request(api, scenario["request_id"])["responsive_record_count"] == 1
    rows, _meta = assert_total_count(
        api.list_responsive_records(CLERK_HEADERS, params={"request_id": scenario["request_id"]}), 1
    )
    assert [row["id"] for row in rows] == [scenario["record_id"]]


# ------------------------------------------------ the ordered intake window
def test_intake_with_a_reversed_date_window_is_refused(api):
    """A from-instant after the to-instant creates no request row at all.

    PRD: "`requested_date_from` must not fall after `requested_date_to`; a reversed pair is refused with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/intake_with_reversed_date_range_is_refused
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")

    response = api.create_request(
        request_payload(
            requester["id"],
            subject_incident_number="INC-2026-0638",
            requested_date_from="2026-07-20T00:00:00Z",
            requested_date_to="2026-07-10T00:00:00Z",
            scope_narrative="Reversed window",
        ),
        CLERK_HEADERS,
    )

    validate_error(response, ERR_INVALID_TIME_RANGE, 422)
    assert get_requester(api, requester["id"])["open_request_count"] == 0
    assert_total_count(api.list_requests(CLERK_HEADERS, params={"requester_id": requester["id"]}), 0)


def test_intake_with_equal_date_endpoints_is_accepted(api):
    """The comparison is inclusive, so an equal pair opens the file normally.

    PRD: "A successful intake creates the request at `processing_status` `INTAKE`, `fee_status` `NOT_ASSESSED` and `version` 1, increments the filer's `open_request_count` by 1, and strikes the first `statutory_deadline_at`."

    Design: Corner/validations/intake_with_reversed_date_range_is_refused
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    api.create_request(
        request_payload(
            requester["id"],
            subject_incident_number="INC-2026-0638",
            requested_date_from="2026-07-20T00:00:00Z",
            requested_date_to="2026-07-10T00:00:00Z",
            scope_narrative="Reversed window",
        ),
        CLERK_HEADERS,
    )

    response = api.create_request(
        request_payload(
            requester["id"],
            subject_incident_number="INC-2026-0638",
            requested_date_from="2026-07-10T00:00:00Z",
            requested_date_to="2026-07-10T00:00:00Z",
            scope_narrative="Single instant window",
        ),
        CLERK_HEADERS,
    )

    created = assert_created(response)
    assert_common_fields(created, 1)
    assert_fields(created, processing_status="INTAKE", fee_status="NOT_ASSESSED")
    assert get_requester(api, requester["id"])["open_request_count"] == 1
    assert_total_count(api.list_requests(CLERK_HEADERS, params={"requester_id": requester["id"]}), 1)


# --------------------------------------------- the estimate-basis phase gate
def _scoping_request_with_candidate_record(api):
    """A SCOPING request whose single twenty-minute recording is still CANDIDATE."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0639",
        device_serial="AXON-0639",
        officer_badge="B-1133",
        recorded_start_at="2026-07-22T15:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-22T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0639",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-23T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0639",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Single unit",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-22T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    return {"request_id": request["id"], "record_id": record["id"]}


def test_adjudicated_basis_is_refused_while_the_request_is_scoping(api):
    """No record has been ruled responsive yet, so the adjudicated basis is unavailable.

    PRD: "An `ADJUDICATED` estimate attempted too early is refused with `ERR_ESTIMATE_BASIS_NOT_PERMITTED`."

    Design: Corner/validations/adjudicated_basis_is_refused_while_scoping_then_permitted
    """
    scenario = _scoping_request_with_candidate_record(api)
    before = get_request(api, scenario["request_id"])

    response = api.create_fee_estimate(
        scenario["request_id"],
        fee_estimate_payload(before["version"], "ADJUDICATED", "DVD"),
        CLERK_HEADERS,
    )

    validate_error(response, ERR_ESTIMATE_BASIS_NOT_PERMITTED, 422)
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="NOT_ASSESSED",
        processing_status="SCOPING",
        version=before["version"],
        estimated_total_cents=0,
        deposit_required_cents=0,
    )
    assert_total_count(api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS), 0)


def test_the_identical_adjudicated_estimate_lands_once_a_record_is_responsive(api):
    """Ruling the record responsive opens the gate, and the same basis prices the file.

    PRD: "Otherwise — a positive total at or under the deposit threshold — the request moves to `fee_status` `ESTIMATED`."

    Design: Corner/validations/adjudicated_basis_is_refused_while_scoping_then_permitted
    """
    scenario = _scoping_request_with_candidate_record(api)
    api.create_fee_estimate(
        scenario["request_id"],
        fee_estimate_payload(request_version(api, scenario["request_id"]), "ADJUDICATED", "DVD"),
        CLERK_HEADERS,
    )
    rule_inclusion(api, scenario["record_id"], "RESPONSIVE")
    assert get_request(api, scenario["request_id"])["processing_status"] == "EXEMPTION_REVIEW"

    estimate = create_estimate(api, scenario["request_id"], "ADJUDICATED", "DVD")

    assert_fields(
        estimate,
        basis="ADJUDICATED",
        status="ACTIVE",
        sequence_number=1,
        projected_review_minutes=20,
        projected_burden_minutes=5,
        billable_minutes=0,
        estimated_labor_cents=0,
        media_production_cents=500,
        subtotal_cents=500,
        waiver_credit_cents=0,
        estimated_total_cents=500,
        deposit_required_cents=0,
    )
    assert_waiver_pct(estimate, "effective_waiver_pct", 0.00)
    assert_money_is_integer_cents(
        estimate,
        "estimated_labor_cents",
        "media_production_cents",
        "subtotal_cents",
        "waiver_credit_cents",
        "estimated_total_cents",
        "deposit_required_cents",
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="ESTIMATED",
        deposit_due_at=None,
        estimated_total_cents=500,
        deposit_required_cents=0,
    )


# ------------------------------------------------ the code-to-citation table
def _responsive_record_for_a_privacy_claim(api):
    """One attorney and one RESPONSIVE twenty-minute record with a five-minute baseline."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0640",
        device_serial="AXON-0640",
        officer_badge="B-1134",
        recorded_start_at="2026-07-21T18:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-21T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0640",
        requested_date_from="2026-07-21T00:00:00Z",
        requested_date_to="2026-07-22T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0640",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Hallway camera",
        requested_date_from="2026-07-21T00:00:00Z",
        requested_date_to="2026-07-21T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return {
        "counsel_id": counsel["id"],
        "request_id": request["id"],
        "record_id": record["id"],
    }


def test_a_mismatched_statutory_citation_is_refused(api):
    """A valid citation belonging to a different code is still a mismatch.

    PRD: "Any other string, including a correct citation paired with the wrong code, is refused with `ERR_CITATION_MISMATCH`."

    Design: Corner/validations/statutory_citation_must_match_the_mapped_code
    """
    scenario = _responsive_record_for_a_privacy_claim(api)

    response = api.assert_exemption_claim(
        scenario["record_id"],
        exemption_claim_payload("PERSONAL_PRIVACY", "PARTIAL_REDACT", "119.071(2)(c)"),
        make_counsel_headers(scenario["counsel_id"]),
    )

    validate_error(response, ERR_CITATION_MISMATCH, 422)
    assert_fields(
        get_record(api, scenario["record_id"]),
        unadjudicated_claim_count=0,
        presumptive_burden_minutes=5,
        adjudicated_burden_minutes=5,
        release_posture="OPEN",
    )
    assert get_request(api, scenario["request_id"])["unadjudicated_claim_count"] == 0
    assert_total_count(
        api.list_exemption_claims(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        0,
    )


def test_the_mapped_citation_is_accepted_and_reprices_the_burden(api):
    """119.071(4)(d) is the privacy citation, and the claim adds eight presumptive minutes.

    PRD: "The record's two burden figures are re-derived from the baseline obscuration plus a sum over claims: `presumptive_burden_minutes` is the baseline plus the total `estimated_redaction_minutes` of every claim on the record whose `status` is `ASSERTED` or `SUSTAINED`, while `adjudicated_burden_minutes` is the baseline plus the total over claims whose `status` is `SUSTAINED` only."

    Design: Corner/validations/statutory_citation_must_match_the_mapped_code
    """
    scenario = _responsive_record_for_a_privacy_claim(api)
    api.assert_exemption_claim(
        scenario["record_id"],
        exemption_claim_payload("PERSONAL_PRIVACY", "PARTIAL_REDACT", "119.071(2)(c)"),
        make_counsel_headers(scenario["counsel_id"]),
    )

    response = api.assert_exemption_claim(
        scenario["record_id"],
        exemption_claim_payload("PERSONAL_PRIVACY", "PARTIAL_REDACT", "119.071(4)(d)"),
        make_counsel_headers(scenario["counsel_id"]),
    )

    claim = assert_created(response)
    assert_fields(
        claim,
        exemption_code="PERSONAL_PRIVACY",
        statutory_citation="119.071(4)(d)",
        status="ASSERTED",
        claim_source="STAFF_ANALYSIS",
        asserted_by_staff_id=scenario["counsel_id"],
        estimated_redaction_minutes=8,
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        unadjudicated_claim_count=1,
        presumptive_burden_minutes=13,
        adjudicated_burden_minutes=5,
        release_posture="RESTRICTED",
    )
    assert_total_count(
        api.list_exemption_claims(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        1,
    )


# ----------------------------------------------------- the clip-range guard
def _responsive_record_for_clip_work(api):
    """A level-two technician and a RESPONSIVE record over a 1200000 ms recording."""
    technician = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0641",
        device_serial="AXON-0641",
        officer_badge="B-1135",
        recorded_start_at="2026-07-20T19:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-20T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0641",
        requested_date_from="2026-07-20T00:00:00Z",
        requested_date_to="2026-07-21T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0641",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Full recording",
        requested_date_from="2026-07-20T00:00:00Z",
        requested_date_to="2026-07-20T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return {
        "tech_id": technician["id"],
        "request_id": request["id"],
        "record_id": record["id"],
    }


def test_clip_ranges_outside_the_recording_or_zero_length_are_refused(api):
    """One millisecond past the duration and a zero-length interval are both invalid.

    PRD: "The clip interval must satisfy `clip_start_ms` at least zero, `clip_end_ms` strictly greater than `clip_start_ms`, and `clip_end_ms` no greater than the `duration_ms` of the recording behind the parent record; any violation is refused with `ERR_INVALID_CLIP_RANGE`."

    Design: Corner/validations/clip_range_must_be_ordered_and_inside_the_recording
    """
    scenario = _responsive_record_for_clip_work(api)
    headers = make_technician_headers(scenario["tech_id"])

    past_end = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 0, 1200001),
        headers,
    )
    validate_error(past_end, ERR_INVALID_CLIP_RANGE, 422)

    zero_length = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 60000, 60000),
        headers,
    )

    validate_error(zero_length, ERR_INVALID_CLIP_RANGE, 422)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        0,
    )
    assert get_request(api, scenario["request_id"])["processing_status"] == "EXEMPTION_REVIEW"


def test_the_full_length_clip_range_is_accepted(api):
    """clip_end_ms equal to the recording's duration is inside the bound and opens work.

    PRD: "The task is created at `status` `DRAFT` with `rework_count` 0, `logged_labor_minutes` 0, `approved_labor_minutes` 0 and `defect_codes` as an empty array, and with `qa_reviewer_id`, `qa_window_start_at` and `qa_window_end_at` all null until the first submission books a reviewer."

    Design: Corner/validations/clip_range_must_be_ordered_and_inside_the_recording
    """
    scenario = _responsive_record_for_clip_work(api)
    headers = make_technician_headers(scenario["tech_id"])
    api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 0, 1200001),
        headers,
    )

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 0, 1200000),
        headers,
    )

    task = assert_created(response)
    assert_fields(
        task,
        status="DRAFT",
        rework_count=0,
        logged_labor_minutes=0,
        approved_labor_minutes=0,
        clip_start_ms=0,
        clip_end_ms=1200000,
        qa_reviewer_id=None,
        qa_window_start_at=None,
        qa_window_end_at=None,
    )
    assert task["defect_codes"] == []
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        1,
    )
    assert get_request(api, scenario["request_id"])["processing_status"] == "REDACTION"


# ------------------------------------------- the juvenile certification ladder
def _juvenile_claim_with_two_technicians(api):
    """A JUVENILE PARTIAL_REDACT claim on a RESPONSIVE record, with a level-2 and a level-3 tech."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    tess = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    vic = create_staff(api, "Vic Tech", "TECHNICIAN", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0642",
        device_serial="AXON-0642",
        officer_badge="B-1136",
        recorded_start_at="2026-07-19T14:00:00Z",
        duration_ms=1200000,
        classification="JUVENILE_CONTACT",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-19T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0642",
        requested_date_from="2026-07-19T00:00:00Z",
        requested_date_to="2026-07-20T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0642",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Contact with the minor only",
        requested_date_from="2026-07-19T00:00:00Z",
        requested_date_to="2026-07-19T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(api, record["id"], counsel["id"], "JUVENILE", "PARTIAL_REDACT")
    return {
        "tech_level_two_id": tess["id"],
        "tech_level_three_id": vic["id"],
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
    }


def test_a_juvenile_linked_face_task_refuses_a_level_two_technician(api):
    """Linking a face blur to a JUVENILE claim raises the requirement past level 2.

    PRD: "The requirement for a given task is derived from what the task obscures and from the exemption it implements: a task whose `target_type` is `FACE` or `LICENSE_PLATE` requires level 1 as its base, any other `target_type` requires level 2 as its base, and if the task names an `exemption_claim_id` whose claim carries `exemption_code` `JUVENILE` the requirement is raised to 3 regardless of target."

    Design: Corner/validations/juvenile_linked_task_demands_certification_level_three
    """
    scenario = _juvenile_claim_with_two_technicians(api)

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(
            scenario["tech_level_two_id"], "FACE", 0, 60000, scenario["claim_id"]
        ),
        make_technician_headers(scenario["tech_level_two_id"]),
    )

    validate_error(response, ERR_CERTIFICATION_INSUFFICIENT, 422)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        0,
    )
    assert get_request(api, scenario["request_id"])["processing_status"] == "EXEMPTION_REVIEW"


def test_a_level_three_technician_clears_the_juvenile_task(api):
    """The level-3 tech takes the juvenile clip, and an unlinked PROTECTED_CONTENT task needs only 2.

    PRD: "The technician nominated on the task must hold at least the derived requirement."

    Design: Corner/validations/juvenile_linked_task_demands_certification_level_three
    """
    scenario = _juvenile_claim_with_two_technicians(api)
    api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(
            scenario["tech_level_two_id"], "FACE", 0, 60000, scenario["claim_id"]
        ),
        make_technician_headers(scenario["tech_level_two_id"]),
    )

    juvenile_task = assert_created(
        api.create_redaction_task(
            scenario["record_id"],
            redaction_task_payload(
                scenario["tech_level_three_id"], "FACE", 0, 60000, scenario["claim_id"]
            ),
            make_technician_headers(scenario["tech_level_three_id"]),
        )
    )
    protected_task = assert_created(
        api.create_redaction_task(
            scenario["record_id"],
            redaction_task_payload(
                scenario["tech_level_two_id"], "PROTECTED_CONTENT", 60000, 120000
            ),
            make_technician_headers(scenario["tech_level_two_id"]),
        )
    )

    assert_fields(
        juvenile_task,
        status="DRAFT",
        assigned_technician_id=scenario["tech_level_three_id"],
        exemption_claim_id=scenario["claim_id"],
    )
    assert_fields(
        protected_task,
        status="DRAFT",
        target_type="PROTECTED_CONTENT",
        assigned_technician_id=scenario["tech_level_two_id"],
        exemption_claim_id=None,
    )
    assert get_claim(api, scenario["claim_id"])["estimated_redaction_minutes"] == 16
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        2,
    )
    assert get_request(api, scenario["request_id"])["processing_status"] == "REDACTION"


# ------------------------------------ segregation of duties on adjudication
def _claim_asserted_by_one_of_two_attorneys(api):
    """One ASSERTED privacy claim asserted by Dana, with Rex available to decide it."""
    dana = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    rex = create_staff(api, "Rex Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0643",
        device_serial="AXON-0643",
        officer_badge="B-1137",
        recorded_start_at="2026-07-18T14:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-18T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0643",
        requested_date_from="2026-07-18T00:00:00Z",
        requested_date_to="2026-07-19T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0643",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Front desk camera",
        requested_date_from="2026-07-18T00:00:00Z",
        requested_date_to="2026-07-18T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(api, record["id"], dana["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT")
    return {
        "dana_id": dana["id"],
        "rex_id": rex["id"],
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
    }


def test_the_asserting_attorney_cannot_adjudicate_their_own_claim(api):
    """Dana asserted the claim, so Dana's sustain is refused and the claim stays ASSERTED.

    PRD: "The acting attorney's `X-User-ID` must differ from the claim's `asserted_by_staff_id`, or the call is refused with `ERR_SEGREGATION_OF_DUTIES`; where `asserted_by_staff_id` is null — which is the case for every claim that materialised from a depicted individual's objection — the condition is satisfied trivially and any attorney may decide it."

    Design: Corner/validations/counsel_cannot_adjudicate_their_own_assertion
    """
    scenario = _claim_asserted_by_one_of_two_attorneys(api)

    response = api.adjudicate_claim(
        scenario["claim_id"],
        adjudication_payload("SUSTAINED", "Self-adjudication attempt"),
        make_counsel_headers(scenario["dana_id"]),
    )

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
    assert_fields(
        get_claim(api, scenario["claim_id"]),
        status="ASSERTED",
        adjudicated_by_staff_id=None,
        adjudicated_at=None,
        adjudication_note=None,
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        unadjudicated_claim_count=1,
        adjudicated_burden_minutes=5,
        release_posture="RESTRICTED",
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        unadjudicated_claim_count=1,
        processing_status="EXEMPTION_REVIEW",
    )


def test_a_second_attorney_sustains_the_same_claim(api):
    """Rex is a different staff member, so the identical call decides the claim.

    PRD: "All three dispositions share the same bookkeeping on the claim itself: `adjudicated_by_staff_id` is set to the deciding attorney's `X-User-ID`, `adjudicated_at` is stamped with the logical clock, and `adjudication_note` is stored."

    Design: Corner/validations/counsel_cannot_adjudicate_their_own_assertion
    """
    scenario = _claim_asserted_by_one_of_two_attorneys(api)
    api.adjudicate_claim(
        scenario["claim_id"],
        adjudication_payload("SUSTAINED", "Self-adjudication attempt"),
        make_counsel_headers(scenario["dana_id"]),
    )

    response = api.adjudicate_claim(
        scenario["claim_id"],
        adjudication_payload("SUSTAINED", "Independent review sustains the privacy claim"),
        make_counsel_headers(scenario["rex_id"]),
    )

    decided = assert_modified(response)
    assert_fields(
        decided,
        status="SUSTAINED",
        adjudicated_by_staff_id=scenario["rex_id"],
        adjudication_note="Independent review sustains the privacy claim",
    )
    assert decided["adjudicated_at"] is not None
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="RESTRICTED",
        unadjudicated_claim_count=0,
        presumptive_burden_minutes=13,
        adjudicated_burden_minutes=13,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        unadjudicated_claim_count=0,
        processing_status="REDACTION",
    )


# ---------------------------------- segregation of duties on the QA booking
def _draft_task_with_a_separate_reviewer(api):
    """A DRAFT FACE task assigned to Tess, with Quinn registered as a level-2 reviewer."""
    tess = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    quinn = create_staff(api, "Quinn Reviewer", "REVIEWER", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0644",
        device_serial="AXON-0644",
        officer_badge="B-1138",
        recorded_start_at="2026-07-17T14:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-17T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0644",
        requested_date_from="2026-07-17T00:00:00Z",
        requested_date_to="2026-07-18T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0644",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Sally port camera",
        requested_date_from="2026-07-17T00:00:00Z",
        requested_date_to="2026-07-17T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tess["id"], "FACE", 0, 60000)
    return {
        "tech_id": tess["id"],
        "reviewer_id": quinn["id"],
        "request_id": request["id"],
        "task_id": task["id"],
    }


def test_a_technician_cannot_nominate_themselves_as_reviewer(api):
    """Self-nomination is refused even though the technician's level would satisfy review.

    PRD: "The nominated `qa_reviewer_id` must differ from `assigned_technician_id`, and self-nomination is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/nominated_reviewer_cannot_be_the_assigned_technician
    """
    scenario = _draft_task_with_a_separate_reviewer(api)

    response = api.submit_qa(
        scenario["task_id"],
        submit_qa_payload(
            scenario["tech_id"], 45, "2026-08-06T09:00:00Z", "2026-08-06T09:30:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
    assert_fields(
        get_task(api, scenario["task_id"]),
        status="DRAFT",
        qa_reviewer_id=None,
        logged_labor_minutes=0,
        rework_count=0,
    )
    assert get_staff(api, scenario["tech_id"])["open_qa_assignment_count"] == 0
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 0


def test_nominating_a_separate_reviewer_books_the_window(api):
    """Quinn is a different staff member, so the same submission books the calendar.

    PRD: "Whichever edge is taken, `qa_reviewer_id`, `qa_window_start_at`, `qa_window_end_at` and `logged_labor_minutes` are all overwritten by this call — the claimed minutes are replaced, never accumulated across attempts — and the nominated reviewer's `open_qa_assignment_count` increases by 1."

    Design: Corner/validations/nominated_reviewer_cannot_be_the_assigned_technician
    """
    scenario = _draft_task_with_a_separate_reviewer(api)
    api.submit_qa(
        scenario["task_id"],
        submit_qa_payload(
            scenario["tech_id"], 45, "2026-08-06T09:00:00Z", "2026-08-06T09:30:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    response = api.submit_qa(
        scenario["task_id"],
        submit_qa_payload(
            scenario["reviewer_id"], 45, "2026-08-06T09:00:00Z", "2026-08-06T09:30:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    submitted = assert_modified(response)
    assert_fields(
        submitted,
        status="QA_PENDING",
        qa_reviewer_id=scenario["reviewer_id"],
        logged_labor_minutes=45,
        rework_count=0,
        approved_labor_minutes=0,
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1
    assert get_staff(api, scenario["tech_id"])["open_qa_assignment_count"] == 0
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 0
