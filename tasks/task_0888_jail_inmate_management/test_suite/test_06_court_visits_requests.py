"""Court event cycle, request deny/appeal cycle, and visitation rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, fixtures,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
HEALTH = TEST_USERS["health_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / court_event_continuance_cycle
# ---------------------------------------------------------------------------
def _setup_continued_twice(api):
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], charge_severity="FELONY", sentence_days=200)
    event = fixtures.schedule_court_event(api, booking["id"], "2026-06-01T09:00:00Z", "ARRAIGNMENT")
    get_success_data(api.continue_court_event(event["id"], {"new_event_datetime": "2026-06-15T09:00:00Z"}, SCHEDULER))
    get_success_data(api.continue_court_event(event["id"], {"new_event_datetime": "2026-07-01T09:00:00Z"}, SCHEDULER))
    return event


def test_two_continuances_settle_back_to_scheduled(api):
    """PRD §3.5: "The event therefore settles back in `SCHEDULED` and may be continued again
    later, growing `continuance_count` each time."

    Design: Difficulty/non_linear_state_machine/court_event_continuance_cycle
    """
    event = _setup_continued_twice(api)
    data = get_success_data(api.list_court_events(event["booking_id"], SCHEDULER))
    ce = next(e for e in data if e["id"] == event["id"])
    assert ce["court_event_status"] == "SCHEDULED", f"got {ce['court_event_status']}"
    assert ce["continuance_count"] == 2, f"expected 2, got {ce['continuance_count']}"


def test_continuance_reschedules_to_latest_datetime(api):
    """PRD §3.5: "then completes by re-scheduling to the `new_event_datetime`, returning
    `CONTINUED → SCHEDULED` with `event_datetime` set to the new value."

    Design: Difficulty/non_linear_state_machine/court_event_continuance_cycle
    """
    event = _setup_continued_twice(api)
    data = get_success_data(api.list_court_events(event["booking_id"], SCHEDULER))
    ce = next(e for e in data if e["id"] == event["id"])
    assert ce["event_datetime"] == "2026-07-01T09:00:00Z", f"got {ce['event_datetime']}"


def test_attend_already_attended_event_rejected(api):
    """PRD §3.5: "a `Scheduler` may mark a `SCHEDULED` event as attended, moving it from
    `SCHEDULED` to the terminal `ATTENDED`. Acting on an event that is not in a valid source
    state for the requested transition is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/attend_already_attended_court_event_returns_invalid_state
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], charge_severity="FELONY", sentence_days=200)
    event = fixtures.schedule_court_event(api, booking["id"], "2026-06-01T09:00:00Z", "HEARING")
    validate_success(api.attend_court_event(event["id"], SCHEDULER))
    resp = api.attend_court_event(event["id"], SCHEDULER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# non_linear_state_machine / request_deny_appeal_cycle
# ---------------------------------------------------------------------------
def _setup_denied_then_appealed(api):
    inmate = fixtures.create_inmate(api, sex="FEMALE")
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=60)
    request = fixtures.file_request(api, booking["id"], "GRIEVANCE", "cell temperature complaint")
    get_success_data(api.review_request(request["id"], HEALTH))
    get_success_data(api.deny_request(request["id"], HEALTH))
    get_success_data(api.appeal_request(request["id"], HEALTH))
    return request


def test_appeal_returns_request_to_under_review(api):
    """PRD §3.7: "A `DENIED` request may be appealed back into review, which returns it from
    `DENIED` to `UNDER_REVIEW` and increments its `appeal_count` by 1".

    Design: Difficulty/non_linear_state_machine/request_deny_appeal_cycle
    """
    request = _setup_denied_then_appealed(api)
    data = get_success_data(api.list_requests(request["booking_id"], HEALTH))
    rq = next(r for r in data if r["id"] == request["id"])
    assert rq["request_status"] == "UNDER_REVIEW", f"got {rq['request_status']}"


def test_appeal_increments_appeal_count(api):
    """PRD §3.7: "A `DENIED` request may be appealed back into review, which returns it from
    `DENIED` to `UNDER_REVIEW` and increments its `appeal_count` by 1".

    Design: Difficulty/non_linear_state_machine/request_deny_appeal_cycle
    """
    request = _setup_denied_then_appealed(api)
    data = get_success_data(api.list_requests(request["booking_id"], HEALTH))
    rq = next(r for r in data if r["id"] == request["id"])
    assert rq["appeal_count"] == 1, f"expected 1, got {rq['appeal_count']}"


def test_resolve_submitted_request_rejected(api):
    """PRD §3.7: "a `SUBMITTED` request is moved into review, becoming `UNDER_REVIEW`; a request
    `UNDER_REVIEW` may then be resolved (terminal `RESOLVED`) or denied (`DENIED`)." and "a
    request that is not in the expected state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/resolve_request_from_submitted_returns_invalid_state
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=40)
    request = fixtures.file_request(api, booking["id"], "MEDICAL", "sick call")  # stays SUBMITTED
    resp = api.resolve_request(request["id"], HEALTH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / visit_requires_visitor_approved
# ---------------------------------------------------------------------------
def test_visit_with_pending_visitor_rejected(api):
    """PRD §3.6: "The referenced visitor must already be `APPROVED`; a visit that names a
    still-`PENDING` visitor is rejected with `ERR_VISITOR_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/visit_requires_visitor_approved
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=40)
    visitor = fixtures.register_visitor(api, inmate["id"], "FAMILY", "Val Visitor")  # PENDING
    resp = api.create_visit(
        f.create_visit_payload(booking["id"], visitor["id"], "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z"),
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_VISITOR_NOT_APPROVED.value)


def test_visit_with_approved_visitor_succeeds(api):
    """PRD §3.6: "A `Scheduler` approves a pending visitor, moving `visitor_status` from
    `PENDING` to `APPROVED`." and "A new `Visit` enters `visit_status` `REQUESTED`."

    Design: Difficulty/cross_entity_state_dependency/visit_requires_visitor_approved
    """
    _inmate, booking, visitor = fixtures.setup_approved_visitor(api)
    resp = api.create_visit(
        f.create_visit_payload(booking["id"], visitor["id"], "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z"),
        SCHEDULER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["visit_status"] == "REQUESTED", f"got {data['visit_status']}"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / visit_thirty_minute_buffer
# ---------------------------------------------------------------------------
def test_visit_within_thirty_minute_buffer_rejected(api):
    """PRD §3.6: "treating each visit as a closed interval and extending it by a 30-minute
    buffer on each side, a requested visit that falls within that buffered window of any other
    non-cancelled visit on the same booking is rejected with `ERR_VISIT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/visit_thirty_minute_buffer
    """
    _inmate, booking, visitor = fixtures.setup_approved_visitor(api)
    fixtures.request_visit(api, booking["id"], visitor["id"], "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z")
    # 11:20 start is 20 min after the prior end 11:00 -> within the 30-min buffer.
    resp = api.create_visit(
        f.create_visit_payload(booking["id"], visitor["id"], "2026-05-03T11:20:00Z", "2026-05-03T11:50:00Z"),
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_OVERLAP.value)


# DELETED test_visit_exactly_thirty_minutes_after_allowed: non-unique-derivability
# (STEP 1b boundary-inclusive-vs-exclusive silence). PRD §3.6 says the buffered window is built
# by "treating each visit as a closed interval and extending it by a 30-minute buffer on each
# side"; a visit starting exactly at the closed boundary (11:30 == existing_end 11:00 + 30min)
# is rejected under the literal closed-interval-intersection reading (the impl's faithful reading)
# but allowed under an interior-only "falls within" reading. PRD prose does not uniquely pin the
# boundary choice, so the exactly-at-edge assertion is not uniquely derivable. Driving scaffold
# rule: Difficulty/resource_temporal_overlap/visit_thirty_minute_buffer (design intent ALLOW is
# not reproduced in PRD prose). Companion test at 11:20 (interior) remains and is unambiguous.


def test_visit_end_before_start_rejected(api):
    """PRD §3.6: "The requested visit's `end_datetime` must be strictly after its
    `start_datetime`, otherwise `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/visit_end_before_start_returns_invalid_time_range
    """
    inmate = fixtures.create_inmate(api, sex="FEMALE")
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=40)
    visitor = fixtures.register_visitor(api, inmate["id"], "FRIEND", "Guest")
    get_success_data(api.approve_visitor(visitor["id"], SCHEDULER))
    resp = api.create_visit(
        f.create_visit_payload(booking["id"], visitor["id"], "2026-05-03T11:00:00Z", "2026-05-03T10:00:00Z"),
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)
