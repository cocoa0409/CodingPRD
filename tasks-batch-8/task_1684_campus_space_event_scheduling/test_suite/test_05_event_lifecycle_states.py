"""Event lifecycle: state-transition legality, deadlines, expiry, check-in
windows, and the term priority lock."""

from test_helpers import (
    assert_same_instant,
    FACILITIES_MANAGER,
    SCHEDULER,
    ApiErrorId,
    advance_term_to_scheduling,
    approve_event,
    check_in_event,
    confirm_event,
    create_block,
    create_event,
    create_grant,
    create_run,
    create_term,
    daily_close,
    drive_event_to_completed,
    get_event,
    get_invoice,
    get_term,
    list_all_invoices,
    org_headers,
    set_clock,
    setup_approved_event,
    setup_confirmed_event,
    setup_org_room,
    validate_error,
    validate_success,
)


def test_decline_after_approve_returns_invalid_state(api):
    """PRD §3.4: "A `Scheduler` may instead decline a `REQUESTED` event,
    supplying a `reason` that is stored as the event's `decline_reason` as the
    event moves to `DECLINED`."
    PRD §2.9: "State validity: the target resource is in a valid from-state for
    the requested transition, including the rule that approval cannot occur
    after the decision deadline (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/decline_after_approve_returns_invalid_state
    """
    scn = setup_approved_event(room_overrides={"capacity": 10})
    response = api.decline_event(scn.event["id"], {"reason": "late"}, SCHEDULER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_event(scn.event["id"])["status"] == "APPROVED"


def test_cancel_completed_event_returns_invalid_state(api):
    """PRD §3.4: "Cancellation is available from `REQUESTED`, `APPROVED`,
    `CONFIRMED`, and `BUMPED`."
    PRD §3.4: "An event that does proceed completes at the daily-close once the
    clock reaches its `end_at`, moving from `IN_PROGRESS` to `COMPLETED`."

    Design: Corner/state_machines/cancel_completed_event_returns_invalid_state
    """
    scn = setup_confirmed_event(
        room_overrides={
            "capacity": 10,
            "internal_hourly_rate_cents": 1000,
            "student_hourly_rate_cents": 500,
            "external_hourly_rate_cents": 2000,
        },
        event_overrides={"expected_attendance": 5},
    )
    event = drive_event_to_completed(
        scn.event["id"], scn.org, "2026-09-14T16:00:00Z"
    )
    assert event["status"] == "COMPLETED"

    response = api.cancel_event(scn.event["id"], SCHEDULER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_event(scn.event["id"])["status"] == "COMPLETED"

    invoice = get_invoice(scn.invoice["id"])
    assert invoice["status"] == "FINALIZED"
    assert invoice["total_cents"] == 1000, "one off-peak bucket at 1000 cents"


def test_rebook_cancelled_event_returns_invalid_state(api):
    """PRD §3.4: "Events cancelled from `REQUESTED` or `BUMPED` have no live
    invoice — a request never had one, and a bumped event's provisional invoice
    was voided at bump time — so the fee is zero and no invoice is created or
    transitioned."
    PRD §3.4: "Rebooking — available to a `Scheduler` or the owning
    `OrgRequester` — supplies a new `room_id` and applies the same room gates as
    approval"

    Design: Corner/state_machines/rebook_cancelled_event_returns_invalid_state
    """
    scn = setup_org_room(room_overrides={"capacity": 10})
    event = create_event(scn.org, scn.room["id"], expected_attendance=5)
    cancelled = validate_success(
        api.cancel_event(event["id"], org_headers(scn.org)), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0

    response = api.rebook_event(event["id"], {"room_id": scn.room["id"]}, SCHEDULER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_event(event["id"])["status"] == "CANCELLED"
    assert list_all_invoices() == [], "cancelling a REQUESTED event creates none"


def test_create_initial_states_across_entities(api):
    """PRD §3.3: "New blocks are `UNPLACED`, with `assigned_room_id` and
    `scheduling_run_id` null until a run places them."
    PRD §3.7: "The new grant is `REQUESTED`, its `room_id` is copied from the
    event's room, and its `return_deadline` is computed as 24 hours after the
    event's `end_at`."
    PRD §3.6: "An invoice is born `PROVISIONAL` at event approval or rebooking"

    Design: Corner/state_machines/create_initial_states_across_entities
    """
    term = create_term()
    block = create_block(
        term["id"], course_code="ART-110", instructor_name="Dr. B",
        enrollment=95, days_of_week=["TUE"], start_time="11:00", end_time="12:15",
        required_features=["PROJECTOR", "VIDEO_CONF"],
    )
    assert block["status"] == "UNPLACED"
    assert block["assigned_room_id"] is None
    assert block["scheduling_run_id"] is None
    assert block["priority_score"] == 980, "95*10 + 10 PROJECTOR + 20 VIDEO_CONF"

    run = create_run(term["id"], expected_term_version=term["version"])
    assert run["status"] == "DRAFT"

    scn = setup_approved_event(
        room_overrides={"capacity": 10},
        event_overrides={
            "expected_attendance": 5,
            "start_at": "2026-12-20T14:00:00Z",
            "end_at": "2026-12-20T15:00:00Z",
        },
    )
    assert scn.invoice["status"] == "PROVISIONAL"

    grant = create_grant(scn.event["id"], scn.org, grant_type="CARD_ACCESS")
    assert grant["status"] == "REQUESTED"
    assert grant["room_id"] == scn.room["id"]
    assert_same_instant(grant["return_deadline"], "2026-12-21T15:00:00Z")


def test_second_check_in_returns_invalid_state(api):
    """PRD §3.4: "Check-in moves a `CONFIRMED` event to `IN_PROGRESS`."
    PRD §2.9: "State validity: the target resource is in a valid from-state for
    the requested transition, including the rule that approval cannot occur
    after the decision deadline (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/second_checkin_returns_invalid_state
    """
    scn = setup_confirmed_event(
        room_overrides={"capacity": 10},
        event_overrides={"expected_attendance": 5},
    )
    set_clock("2026-09-14T14:00:00Z")
    first = check_in_event(scn.event["id"], scn.org)
    assert first["status"] == "IN_PROGRESS"

    response = api.check_in_event(scn.event["id"], FACILITIES_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    after = get_event(scn.event["id"])
    assert after["status"] == "IN_PROGRESS"
    assert after["checked_in_at"] == first["checked_in_at"]


def test_request_expires_after_decision_deadline(api):
    """PRD §3.4: "Requests left undecided expire on their own: the daily-close
    moves a `REQUESTED` event past its `decision_deadline` to `EXPIRED`"

    Design: Corner/state_machines/request_expires_after_decision_deadline
    """
    scn = setup_org_room(room_overrides={"capacity": 10})
    event = create_event(scn.org, scn.room["id"], expected_attendance=5)
    assert_same_instant(event["decision_deadline"], "2026-08-04T00:00:00Z")

    set_clock("2026-08-05T00:00:00Z")
    counters = daily_close()
    assert counters["requests_expired"] == 1
    assert get_event(event["id"])["status"] == "EXPIRED"


def test_approval_expiry_voids_provisional_invoice(api):
    """PRD §3.4: "an `APPROVED` event past its `confirm_deadline` to `EXPIRED`
    with its provisional invoice voided."

    Design: Corner/state_machines/approval_expiry_voids_provisional_invoice
    """
    scn = setup_approved_event(
        room_overrides={"capacity": 10},
        event_overrides={"expected_attendance": 5},
    )
    assert scn.invoice["status"] == "PROVISIONAL"

    set_clock("2026-08-04T00:00:00Z")
    counters = daily_close()
    assert counters["approvals_expired"] == 1
    assert get_event(scn.event["id"])["status"] == "EXPIRED"
    assert get_invoice(scn.invoice["id"])["status"] == "VOIDED"


def test_check_in_window_early_and_late_boundaries(api):
    """PRD §3.4: "Either the owning `OrgRequester` or a `FacilitiesManager` may
    check in, but only within the window from thirty minutes before the event's
    `start_at` through fifteen minutes after it, both bounds inclusive; outside
    that window the attempt is rejected with `ERR_CHECKIN_WINDOW_CLOSED`."

    Design: Corner/validations/checkin_window_early_and_late_boundaries
    """
    scn = setup_org_room(room_overrides={"capacity": 30})
    events = []
    for day in ("14", "15", "16"):
        ev = create_event(
            scn.org, scn.room["id"],
            title=f"D{day}", expected_attendance=5,
            start_at=f"2026-09-{day}T14:00:00Z",
            end_at=f"2026-09-{day}T15:00:00Z",
        )
        approve_event(ev["id"])
        confirm_event(ev["id"], scn.org)
        events.append(ev)

    requester = org_headers(scn.org)

    # One minute before the window opens (start - 31m).
    set_clock("2026-09-14T13:29:00Z")
    early = api.check_in_event(events[0]["id"], requester)
    validate_error(early, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)

    # Exactly start + 15m is inside the inclusive grace edge.
    set_clock("2026-09-15T14:15:00Z")
    edge = validate_success(api.check_in_event(events[1]["id"], requester), 200)
    assert edge["status"] == "IN_PROGRESS"

    # One minute past the grace edge.
    set_clock("2026-09-16T14:16:00Z")
    late = api.check_in_event(events[2]["id"], requester)
    validate_error(late, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)
    assert get_event(events[2]["id"])["status"] == "CONFIRMED"


def test_approve_locked_during_priority_window_then_allowed_in_general(api):
    """PRD §3.3: "While a term is in `SCHEDULING`, approval or rebooking of any
    ad-hoc event whose span from `start_at` to `end_at` intersects that term's
    instructional dates is rejected with `ERR_TERM_PRIORITY_LOCKED` until the
    term reaches `GENERAL`"

    Design: Corner/validations/approve_during_priority_window_locked_then_general_allows
    """
    term = create_term()
    scn = setup_org_room(room_overrides={"capacity": 30})
    advance_term_to_scheduling(term["id"])

    ev1 = create_event(
        scn.org, scn.room["id"],
        title="Early", expected_attendance=5,
        start_at="2026-09-14T14:00:00Z", end_at="2026-09-14T15:00:00Z",
    )
    locked = api.approve_event(ev1["id"], SCHEDULER)
    validate_error(locked, ApiErrorId.ERR_TERM_PRIORITY_LOCKED)
    assert get_event(ev1["id"])["status"] == "REQUESTED"

    set_clock("2026-09-02T00:00:00Z")
    daily_close()
    assert get_term(term["id"])["status"] == "GENERAL"

    ev2 = create_event(
        scn.org, scn.room["id"],
        title="Late", expected_attendance=5,
        start_at="2026-09-16T14:00:00Z", end_at="2026-09-16T15:00:00Z",
    )
    approved = validate_success(api.approve_event(ev2["id"], SCHEDULER), 200)
    assert approved["status"] == "APPROVED"
