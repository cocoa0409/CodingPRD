"""Follow-up call scheduling and the monitoring lifecycle: the NO_ANSWER retry
cycle, the WORSENED escalation cascade, case-overlap vs specialist-buffer
scheduling rules, and window well-formedness.

Translations of Difficulty rules `non_linear_state_machine` / `transitive_cascade`
/ `resource_temporal_overlap` and Corner `validations`.
"""
from test_helpers import (
    ApiErrorId,
    create_follow_up_call_payload,
    make_specialist_headers,
    setup_monitoring_case,
    setup_triaged_case_for_followups,
    setup_two_triaged_cases_one_specialist,
    validate_error,
    validate_success,
)


def _first_followup(ctx):
    calls = sorted(ctx["followups"], key=lambda c: c["sequence_index"])
    return calls[0]


def test_no_answer_reverts_call_to_scheduled(api):
    """PRD §3.6: "When the outcome is `NO_ANSWER` and the call's `attempt_count` is
    below 3, the call reverts from `ATTEMPTED` back to `SCHEDULED`, and its
    `scheduled_start` and `scheduled_end` are pushed forward by 6 hours from the
    current logical clock for a retry."

    Design: Difficulty/non_linear_state_machine/followup_reschedule_cycle
    """
    ctx = setup_monitoring_case(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    fu = _first_followup(ctx)
    api.attempt_follow_up_call(fu["id"], headers)
    call = validate_success(api.complete_follow_up_call(fu["id"], {"outcome": "NO_ANSWER"}, headers))
    assert call["status"] == "SCHEDULED"


def test_attempt_increments_attempt_count(api):
    """PRD §3.6: "Placing a call moves it from `SCHEDULED` to `ATTEMPTED` and
    increments its `attempt_count` by one; it is permitted only while the call is
    `SCHEDULED` and the owning case is not `CLOSED`."

    Design: Difficulty/non_linear_state_machine/followup_reschedule_cycle
    """
    ctx = setup_monitoring_case(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    fu = _first_followup(ctx)
    api.attempt_follow_up_call(fu["id"], headers)
    call = validate_success(api.complete_follow_up_call(fu["id"], {"outcome": "NO_ANSWER"}, headers))
    assert call["attempt_count"] == 1


def test_worsened_completion_completes_call_and_retriages_case(api):
    """PRD §3.6: "If the outcome is `WORSENED`, the case is driven to `RETRIAGE`,
    superseding its active assessment and disposition so it can be re-assessed."

    Design: Difficulty/transitive_cascade/worsened_followup_cascade_depth2
    """
    ctx = setup_monitoring_case(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    fu = _first_followup(ctx)
    api.attempt_follow_up_call(fu["id"], headers)
    call = validate_success(api.complete_follow_up_call(fu["id"], {"outcome": "WORSENED"}, headers))
    assert call["status"] == "COMPLETED"
    assert call["outcome"] == "WORSENED"
    case = validate_success(api.get_case(ctx["case"]["id"], headers))
    assert case["status"] == "RETRIAGE"


def test_worsened_completion_supersedes_assessment_and_disposition(api):
    """PRD §3.6: "If the outcome is `WORSENED`, the case is driven to `RETRIAGE`,
    superseding its active assessment and disposition so it can be re-assessed."

    Design: Difficulty/transitive_cascade/worsened_followup_cascade_depth2
    """
    ctx = setup_monitoring_case(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    fu = _first_followup(ctx)
    api.attempt_follow_up_call(fu["id"], headers)
    api.complete_follow_up_call(fu["id"], {"outcome": "WORSENED"}, headers)
    ra = validate_success(api.get_risk_assessment(ctx["ra"]["id"], headers))
    disp = validate_success(api.get_disposition(ctx["disposition"]["id"], headers))
    assert ra["status"] == "SUPERSEDED"
    assert disp["status"] == "SUPERSEDED"


def test_case_followup_halfopen_overlap_rejected(api):
    """PRD §3.6: "the new call must not overlap, on a half-open basis, any existing
    `SCHEDULED` or `ATTEMPTED` call of the same case: two windows conflict when they
    share any instant in their half-open ranges, but adjacency where one window's
    end equals another's start is allowed; an overlap is rejected with
    `ERR_FOLLOWUP_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/case_followup_halfopen_overlap
    """
    ctx = setup_triaged_case_for_followups(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    api.create_follow_up_call(
        ctx["case"]["id"],
        create_follow_up_call_payload(ctx["spi"]["id"], 0,
                                      "2026-06-02T00:00:00Z", "2026-06-02T00:30:00Z"),
        headers)
    resp = api.create_follow_up_call(
        ctx["case"]["id"],
        create_follow_up_call_payload(ctx["spi2"]["id"], 1,
                                      "2026-06-02T00:15:00Z", "2026-06-02T00:45:00Z"),
        headers)
    validate_error(resp, ApiErrorId.ERR_FOLLOWUP_OVERLAP)


def test_case_followup_adjacency_allowed(api):
    """PRD §3.6: "two windows conflict when they share any instant in their
    half-open ranges, but adjacency where one window's end equals another's start
    is allowed; an overlap is rejected with `ERR_FOLLOWUP_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/case_followup_halfopen_overlap
    """
    ctx = setup_triaged_case_for_followups(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    api.create_follow_up_call(
        ctx["case"]["id"],
        create_follow_up_call_payload(ctx["spi"]["id"], 0,
                                      "2026-06-02T00:00:00Z", "2026-06-02T00:30:00Z"),
        headers)
    adj = validate_success(api.create_follow_up_call(
        ctx["case"]["id"],
        create_follow_up_call_payload(ctx["spi2"]["id"], 2,
                                      "2026-06-02T00:30:00Z", "2026-06-02T01:00:00Z"),
        headers), 201)
    assert adj["status"] == "SCHEDULED"


def test_specialist_double_booking_rejected(api):
    """PRD §3.6: "treating the new call's window as a closed interval, the gap
    between it and every existing `SCHEDULED` or `ATTEMPTED` call of the same
    specialist must be at least 15 minutes — a gap of exactly 15 minutes is allowed,
    while any smaller gap, including touching intervals, is rejected with
    `ERR_SPECIALIST_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/specialist_buffer_double_booking
    """
    ctx = setup_two_triaged_cases_one_specialist(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    resp = api.create_follow_up_call(
        ctx["case2"]["id"],
        create_follow_up_call_payload(ctx["spi"]["id"], 0,
                                      "2026-06-02T10:30:00Z", "2026-06-02T10:45:00Z"),
        headers)
    validate_error(resp, ApiErrorId.ERR_SPECIALIST_DOUBLE_BOOKED)


def test_specialist_exactly_15_minute_gap_allowed(api):
    """PRD §3.6: "the gap between it and every existing `SCHEDULED` or `ATTEMPTED`
    call of the same specialist must be at least 15 minutes — a gap of exactly 15
    minutes is allowed, while any smaller gap, including touching intervals, is
    rejected with `ERR_SPECIALIST_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/specialist_buffer_double_booking
    """
    ctx = setup_two_triaged_cases_one_specialist(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    ok = validate_success(api.create_follow_up_call(
        ctx["case2"]["id"],
        create_follow_up_call_payload(ctx["spi"]["id"], 1,
                                      "2026-06-02T10:45:00Z", "2026-06-02T11:00:00Z"),
        headers), 201)
    assert ok["status"] == "SCHEDULED"


def test_followup_invalid_window_rejected(api):
    """PRD §3.6: "the window must be well formed: `scheduled_end` must be strictly
    greater than `scheduled_start`, or the request is rejected with
    `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/followup_invalid_window_rejected
    """
    ctx = setup_triaged_case_for_followups(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    resp = api.create_follow_up_call(
        ctx["case"]["id"],
        create_follow_up_call_payload(ctx["spi"]["id"], 0,
                                      "2026-06-02T10:00:00Z", "2026-06-02T10:00:00Z"),
        headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
