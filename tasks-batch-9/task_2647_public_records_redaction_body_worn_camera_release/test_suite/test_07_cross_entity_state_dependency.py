"""Writes whose legality depends on the state of a different entity.

A QA pass depends on the exemption claim its task implements; an inclusion ruling
depends on the phase the parent request has reached.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_REQUEST_STATE_INVALID, ERR_UNADJUDICATED_CLAIM
from test_helpers.assertions import assert_fields, assert_modified
from test_helpers.factories import inclusion_payload, qa_outcome_payload
from test_helpers.fixtures import (
    adjudicate,
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_request,
    create_requester,
    create_staff,
    get_claim,
    get_record,
    get_request,
    get_staff,
    get_task,
    open_task,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import CLERK_HEADERS, make_reviewer_headers


def _task_awaiting_an_undecided_claim(api):
    """A QA_PENDING face task implementing a still-ASSERTED privacy claim."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0513",
        device_serial="AXON-0513",
        officer_badge="B-1107",
        recorded_start_at="2026-07-24T08:00:00Z",
        duration_ms=900000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-24T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0513",
        requested_date_from="2026-07-24T00:00:00Z",
        requested_date_to="2026-07-25T00:00:00Z",
        scope_narrative="BWC video for INC-2026-0513",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Welfare check segment",
        requested_date_from="2026-07-24T00:00:00Z",
        requested_date_to="2026-07-24T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(
        api, record["id"], counsel_a["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT"
    )
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 30000, claim["id"])
    submit_for_qa(
        api, task["id"], tech["id"], reviewer["id"], 6,
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
    )
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "task_id": task["id"],
        "reviewer_id": reviewer["id"],
        "counsel_b_id": counsel_b["id"],
    }


def test_qa_pass_is_refused_while_the_implemented_claim_is_undecided(api):
    """A pass on a task whose claim is still ASSERTED is refused and changes nothing.

    PRD: "A pass additionally requires that the claim being implemented has actually been decided: if the task's `exemption_claim_id` is non-null and the referenced claim is still at `ASSERTED`, the pass is refused with `ERR_UNADJUDICATED_CLAIM`; a task whose `exemption_claim_id` is null carries no such dependency."

    Design: Difficulty/cross_entity_state_dependency/qa_pass_requires_sustained_exemption_claim
    """
    scenario = _task_awaiting_an_undecided_claim(api)

    response = api.record_qa_outcome(
        scenario["task_id"],
        qa_outcome_payload("PASS"),
        make_reviewer_headers(scenario["reviewer_id"]),
    )

    validate_error(response, ERR_UNADJUDICATED_CLAIM, 409)
    task = get_task(api, scenario["task_id"])
    assert_fields(task, status="QA_PENDING", approved_labor_minutes=0)
    assert task["defect_codes"] == []
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 0


def test_the_identical_qa_pass_succeeds_once_the_claim_is_sustained(api):
    """Sustaining the claim unblocks the same call, which then approves the work.

    PRD: "A pass moves the task `QA_PENDING → APPROVED`, freezes `approved_labor_minutes` at the current `logged_labor_minutes`, and sets `defect_codes` to the empty array."

    Design: Difficulty/cross_entity_state_dependency/qa_pass_requires_sustained_exemption_claim
    """
    scenario = _task_awaiting_an_undecided_claim(api)
    api.record_qa_outcome(
        scenario["task_id"],
        qa_outcome_payload("PASS"),
        make_reviewer_headers(scenario["reviewer_id"]),
    )

    adjudicate(api, scenario["claim_id"], scenario["counsel_b_id"], "SUSTAINED")
    assert_fields(
        get_claim(api, scenario["claim_id"]),
        status="SUSTAINED",
        adjudicated_by_staff_id=scenario["counsel_b_id"],
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="RESTRICTED",
        adjudicated_burden_minutes=10,
    )

    response = api.record_qa_outcome(
        scenario["task_id"],
        qa_outcome_payload("PASS"),
        make_reviewer_headers(scenario["reviewer_id"]),
    )

    approved = assert_modified(response)
    assert_fields(approved, status="APPROVED", approved_labor_minutes=6)
    assert get_record(api, scenario["record_id"])["approved_labor_minutes"] == 6
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0
    assert_fields(
        get_request(api, scenario["request_id"]),
        billable_labor_minutes=6,
        processing_status="RELEASE_READY",
    )


def _candidate_record_on_an_unclarified_request(api):
    """A recording attached while the request is still at INTAKE, left at CANDIDATE."""
    requester = create_requester(api, "Mo Media", "mo@dailywire.example", "MEDIA")
    asset = create_asset(
        api,
        incident_number="INC-2026-0514",
        device_serial="AXON-0514",
        officer_badge="B-1108",
        recorded_start_at="2026-07-23T21:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2027-01-19T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0514",
        requested_date_from="2026-07-23T00:00:00Z",
        requested_date_to="2026-07-24T00:00:00Z",
        scope_narrative="Any BWC video from INC-2026-0514",
    )
    record = attach_record(api, request["id"], asset["id"])
    return {"request_id": request["id"], "record_id": record["id"]}


def test_responsive_ruling_is_refused_while_the_request_sits_at_intake(api):
    """Responsiveness cannot be judged before anybody has clarified the scope.

    PRD: "The parent request must be at `SCOPING` or `EXEMPTION_REVIEW`; a request still at `INTAKE` is refused with `ERR_REQUEST_STATE_INVALID`, because responsiveness cannot be judged against a scope nobody has clarified."

    Design: Difficulty/cross_entity_state_dependency/responsive_ruling_requires_request_past_intake
    """
    scenario = _candidate_record_on_an_unclarified_request(api)

    response = api.rule_inclusion(
        scenario["record_id"], inclusion_payload("RESPONSIVE"), CLERK_HEADERS
    )

    validate_error(response, ERR_REQUEST_STATE_INVALID, 409)
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="CANDIDATE",
        release_posture="OPEN",
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="INTAKE",
        responsive_record_count=1,
    )


def test_the_identical_ruling_succeeds_once_the_scope_is_clarified(api):
    """Clarification moves the request to SCOPING, and the same ruling then lands.

    PRD: "A ruling of `RESPONSIVE` moves the record `CANDIDATE → RESPONSIVE` and does considerably more: the request's `responsive_record_count`, `is_critical_incident`, `statutory_deadline_at` and `open_notification_count` are all recomputed — and note that the deadline may jump backwards or forwards here, because the anchor can move from `received_at` to the earliest critical-incident `recorded_start_at` — and the first such ruling bubbles up to advance the request `SCOPING → EXEMPTION_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/responsive_ruling_requires_request_past_intake
    """
    scenario = _candidate_record_on_an_unclarified_request(api)
    api.rule_inclusion(scenario["record_id"], inclusion_payload("RESPONSIVE"), CLERK_HEADERS)

    # The attachment already recomputed the request's responsive_record_count and
    # therefore bumped its version, so the clarification must declare the version
    # the caller last observed rather than the one intake minted.
    clarify_scope(
        api,
        scenario["request_id"],
        scope_narrative="Narrowed to the 10-minute contact",
        requested_date_from="2026-07-23T00:00:00Z",
        requested_date_to="2026-07-23T23:59:59Z",
    )
    clarified = get_request(api, scenario["request_id"])
    assert_fields(clarified, processing_status="SCOPING", scope_clarification_count=1)
    assert clarified["version"] > 1

    response = api.rule_inclusion(
        scenario["record_id"], inclusion_payload("RESPONSIVE"), CLERK_HEADERS
    )

    ruled = assert_modified(response)
    assert_fields(
        ruled,
        inclusion_status="RESPONSIVE",
        estimated_review_minutes=10,
        presumptive_burden_minutes=3,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="EXEMPTION_REVIEW",
        responsive_record_count=1,
    )
