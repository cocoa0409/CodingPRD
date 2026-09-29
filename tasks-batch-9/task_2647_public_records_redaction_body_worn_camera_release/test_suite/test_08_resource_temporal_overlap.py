"""Two bookable resources with deliberately different interval semantics.

A record's clip timeline is half-open with no buffer; a reviewer's calendar is
closed and inflated by a thirty-minute buffer on both sides.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_CLIP_OVERLAP, ERR_QA_WINDOW_CONFLICT
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_modified,
    assert_total_count,
)
from test_helpers.factories import redaction_task_payload, submit_qa_payload
from test_helpers.fixtures import (
    attach_record,
    clarify_scope,
    create_asset,
    create_request,
    create_requester,
    create_staff,
    get_request,
    get_staff,
    get_task,
    open_task,
    record_verdict,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import CLERK_HEADERS, make_technician_headers


def _record_with_one_draft_face_task(api):
    """An hour of ROUTINE footage, one RESPONSIVE record, a DRAFT FACE task on [0,30000)."""
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0515",
        device_serial="AXON-0515",
        officer_badge="B-1109",
        recorded_start_at="2026-07-22T15:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-22T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0515",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-23T00:00:00Z",
        scope_narrative="BWC video for INC-2026-0515",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="First minute of contact",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-22T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    first = open_task(api, record["id"], tech["id"], "FACE", 0, 30000)
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "tech_id": tech["id"],
        "first_task_id": first["id"],
    }


def test_adjacent_clip_intervals_are_both_accepted(api):
    """A task ending at 30000 ms and one starting at 30000 ms are adjacent, not overlapping.

    PRD: "Because the intervals are half-open, a task ending at 30000 milliseconds and a task starting at 30000 milliseconds are adjacent rather than overlapping and both are accepted, while a single millisecond of penetration — a new task starting at 29999 — is a conflict."

    Design: Difficulty/resource_temporal_overlap/clip_overlap_half_open_adjacency_on_responsive_record
    """
    scenario = _record_with_one_draft_face_task(api)

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 30000, 60000),
        make_technician_headers(scenario["tech_id"]),
    )

    adjacent = assert_created(response)
    assert_fields(adjacent, status="DRAFT", clip_start_ms=30000, clip_end_ms=60000)
    first = get_task(api, scenario["first_task_id"])
    assert_fields(
        first,
        status="DRAFT",
        logged_labor_minutes=0,
        approved_labor_minutes=0,
        rework_count=0,
    )
    assert first["defect_codes"] == []


def test_one_millisecond_of_penetration_is_a_clip_conflict(api):
    """A FACE task starting at 29999 intersects the incumbent and is refused.

    PRD: "Two tasks conflict only when they sit on the same responsive record, carry the same `target_type`, the existing task's `status` is `DRAFT`, `QA_PENDING`, `QA_REJECTED` or `APPROVED`, and their intervals genuinely intersect — that is, the new `clip_start_ms` is strictly less than the existing `clip_end_ms` and the existing `clip_start_ms` is strictly less than the new `clip_end_ms`."

    Design: Difficulty/resource_temporal_overlap/clip_overlap_half_open_adjacency_on_responsive_record
    """
    scenario = _record_with_one_draft_face_task(api)
    api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 30000, 60000),
        make_technician_headers(scenario["tech_id"]),
    )

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 29999, 30000),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_CLIP_OVERLAP, 409)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        2,
    )


def test_a_different_target_type_may_occupy_the_identical_range(api):
    """A plate blur over the same seconds as a face blur is always accepted.

    PRD: "And a different `target_type` over the identical range is always accepted: a face blur and a plate blur legitimately cover the same seconds."

    Design: Difficulty/resource_temporal_overlap/clip_overlap_half_open_adjacency_on_responsive_record
    """
    scenario = _record_with_one_draft_face_task(api)
    api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 30000, 60000),
        make_technician_headers(scenario["tech_id"]),
    )
    api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 29999, 30000),
        make_technician_headers(scenario["tech_id"]),
    )

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "LICENSE_PLATE", 0, 30000),
        make_technician_headers(scenario["tech_id"]),
    )

    plate = assert_created(response)
    assert_fields(plate, target_type="LICENSE_PLATE", clip_start_ms=0, clip_end_ms=30000)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        3,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="REDACTION",
        billable_labor_minutes=0,
    )


def _reviewer_holding_one_booking(api):
    """Three non-overlapping FACE tasks; task A already booked 13:00-14:00 with one reviewer."""
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0516",
        device_serial="AXON-0516",
        officer_badge="B-1110",
        recorded_start_at="2026-07-21T11:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-21T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0516",
        requested_date_from="2026-07-21T00:00:00Z",
        requested_date_to="2026-07-22T00:00:00Z",
        scope_narrative="BWC video for INC-2026-0516",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Opening 30 seconds",
        requested_date_from="2026-07-21T00:00:00Z",
        requested_date_to="2026-07-21T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task_a = open_task(api, record["id"], tech["id"], "FACE", 0, 10000)
    task_b = open_task(api, record["id"], tech["id"], "FACE", 10000, 20000)
    task_c = open_task(api, record["id"], tech["id"], "FACE", 20000, 30000)
    submit_for_qa(
        api, task_a["id"], tech["id"], reviewer["id"], 5,
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
    )
    return {
        "request_id": request["id"],
        "tech_id": tech["id"],
        "reviewer_id": reviewer["id"],
        "task_a_id": task_a["id"],
        "task_b_id": task_b["id"],
        "task_c_id": task_c["id"],
    }


def test_a_window_exactly_thirty_minutes_after_the_incumbent_conflicts(api):
    """14:30 buffered back by thirty minutes touches the incumbent's 14:00 close.

    PRD: "Two windows that merely touch — one ending at 14:00 and the next starting at 14:00 — do conflict here, and so do windows exactly thirty minutes apart; a gap of thirty-one minutes is clear."

    Design: Difficulty/resource_temporal_overlap/qa_window_buffered_closed_interval_on_reviewer
    """
    scenario = _reviewer_holding_one_booking(api)

    response = api.submit_qa(
        scenario["task_b_id"],
        submit_qa_payload(
            scenario["reviewer_id"], 4, "2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_QA_WINDOW_CONFLICT, 409)
    assert_fields(
        get_task(api, scenario["task_b_id"]),
        status="DRAFT",
        logged_labor_minutes=0,
        qa_reviewer_id=None,
        qa_window_start_at=None,
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1


def test_a_gap_of_thirty_one_minutes_is_clear(api):
    """One further minute clears the buffer and the booking is accepted.

    PRD: "A booking conflicts with an existing one when both name the same `qa_reviewer_id`, the existing task's `status` is `QA_PENDING`, and the buffered intervals meet — that is, the new `qa_window_start_at` moved thirty minutes earlier is at or before the existing `qa_window_end_at`, and the existing `qa_window_start_at` moved thirty minutes earlier is at or before the new `qa_window_end_at`."

    Design: Difficulty/resource_temporal_overlap/qa_window_buffered_closed_interval_on_reviewer
    """
    scenario = _reviewer_holding_one_booking(api)
    api.submit_qa(
        scenario["task_b_id"],
        submit_qa_payload(
            scenario["reviewer_id"], 4, "2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    response = api.submit_qa(
        scenario["task_b_id"],
        submit_qa_payload(
            scenario["reviewer_id"], 4, "2026-08-01T14:31:00Z", "2026-08-01T15:31:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    booked = assert_modified(response)
    assert_fields(
        booked,
        status="QA_PENDING",
        qa_window_start_at="2026-08-01T14:31:00Z",
        logged_labor_minutes=4,
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 2


def test_a_failed_review_frees_the_reviewers_calendar(api):
    """Task A leaves QA_PENDING, so task C may book squarely inside A's old window.

    PRD: "Tasks that have already passed or failed review free the reviewer's calendar entirely and are ignored."

    Design: Difficulty/resource_temporal_overlap/qa_window_buffered_closed_interval_on_reviewer
    """
    scenario = _reviewer_holding_one_booking(api)
    submit_for_qa(
        api, scenario["task_b_id"], scenario["tech_id"], scenario["reviewer_id"], 4,
        "2026-08-01T14:31:00Z", "2026-08-01T15:31:00Z",
    )

    record_verdict(
        api, scenario["task_a_id"], scenario["reviewer_id"], "FAIL", ["FACE_MISSED"]
    )

    failed = get_task(api, scenario["task_a_id"])
    assert_fields(failed, status="QA_REJECTED", approved_labor_minutes=0)
    assert failed["defect_codes"] == ["FACE_MISSED"]
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1

    response = api.submit_qa(
        scenario["task_c_id"],
        submit_qa_payload(
            scenario["reviewer_id"], 3, "2026-08-01T13:00:00Z", "2026-08-01T13:30:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    assert_modified(response)
    assert get_task(api, scenario["task_c_id"])["status"] == "QA_PENDING"
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 2
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 0
