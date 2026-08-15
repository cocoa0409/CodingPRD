"""Drop-in queue claims: gap-free positions, per-student and per-day capacity,
call-next selection, terminal-state lockdown and the daily-close expiry sweep."""
from test_helpers import (
    ApiErrorId,
    assert_drop_in_ticket,
    create_advisor,
    create_drop_in_ticket_payload,
    create_student,
    join_queue,
    make_advisor_headers,
    set_logical_clock,
    validate_error,
    validate_success,
)


# ─── Difficulty: resource_temporal_overlap / dropin_queue_instantaneous_capacity

def test_fourth_ticket_rejected_at_day_capacity(api, front_desk_headers):
    """PRD §3.5: "And the day itself is capped: once the `queue_date` already has 3 active tickets (counting `QUEUED` and `CALLED` together), further intake is rejected with `ERR_QUEUE_CAPACITY_REACHED`, regardless of which students are queuing."

    Design: Difficulty/resource_temporal_overlap/dropin_queue_instantaneous_capacity
    """
    students = [
        create_student(full_name=f"Q{i}", email=f"q{i}@x.edu") for i in (1, 2, 3, 4)
    ]
    for s in students[:3]:
        join_queue(s["id"], reason="question")
    res = api.create_drop_in_ticket(
        create_drop_in_ticket_payload(students[3]["id"], reason="waitlist"),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_QUEUE_CAPACITY_REACHED)


def test_leave_frees_slot_and_position_counts_all_statuses(api, front_desk_headers):
    """PRD §3.5: "The ticket's `queue_date` is the logical calendar date at intake — it is what groups the day's queue — and its `position` is one more than the number of pre-existing tickets sharing that `queue_date`, counting tickets of any status."
    PRD §3.5: "the student departs — recorded by `FrontDeskStaff`, an `Advisor`, or the director — which moves a ticket from `QUEUED` or `CALLED` to `LEFT`."

    Design: Difficulty/resource_temporal_overlap/dropin_queue_instantaneous_capacity
    """
    students = [
        create_student(full_name=f"Q{i}", email=f"q{i}@x.edu") for i in (1, 2, 3, 4)
    ]
    first = join_queue(students[0]["id"], reason="schedule question")
    join_queue(students[1]["id"], reason="hold question")
    join_queue(students[2]["id"], reason="plan review")
    validate_error(
        api.create_drop_in_ticket(
            create_drop_in_ticket_payload(students[3]["id"], reason="waitlist"),
            front_desk_headers,
        ),
        ApiErrorId.ERR_QUEUE_CAPACITY_REACHED,
    )
    # Freeing one active slot immediately admits a new ticket; position counts
    # every pre-existing ticket of the day, the LEFT one included.
    validate_success(api.leave_drop_in_ticket(first["id"], front_desk_headers), 200)
    res = api.create_drop_in_ticket(
        create_drop_in_ticket_payload(students[3]["id"], reason="waitlist"),
        front_desk_headers,
    )
    ticket = validate_success(res, 201)
    assert_drop_in_ticket(ticket)
    assert ticket["status"] == "QUEUED"
    assert ticket["position"] == 4, (
        "3 pre-existing tickets of the queue_date (one now LEFT) -> position 4"
    )


# ─── Corner: calculations / queue_position_assigns_creation_order ────────────

def test_queue_position_assigns_creation_order(api, front_desk_headers):
    """PRD §3.5: "The position is fixed at creation and never changes; positions are gap-free within a day, creation order and position order always coincide, and a ticket's `id` is never consulted for ordering."
    PRD §2.4: "Before it has ever been set, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own."

    Design: Corner/calculations/queue_position_assigns_creation_order
    """
    s1 = create_student(full_name="QC1", email="qc1@x.edu")
    s2 = create_student(full_name="QC2", email="qc2@x.edu")
    t1 = join_queue(s1["id"], reason="a")
    t2 = join_queue(s2["id"], reason="b")
    assert t1["position"] == 1
    assert t2["position"] == 2
    assert t2["queue_date"] == "2026-08-01", "logical clock default calendar date"


# ─── Corner: errors / student_already_has_active_ticket_rejected ─────────────

def test_student_already_has_active_ticket_rejected(api, front_desk_headers):
    """PRD §3.5: "A student may hold at most one active ticket — `QUEUED` or `CALLED` — per `queue_date`; a second join the same day is rejected with `ERR_STUDENT_ALREADY_HAS_ACTIVE_TICKET`."

    Design: Corner/errors/student_already_has_active_ticket_rejected
    """
    student = create_student(full_name="R6", email="r6e@x.edu")
    join_queue(student["id"], reason="first")
    res = api.create_drop_in_ticket(
        create_drop_in_ticket_payload(student["id"], reason="second"),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_STUDENT_ALREADY_HAS_ACTIVE_TICKET)


# ─── Corner: errors / queue_empty_call_next_rejected ─────────────────────────

def test_queue_empty_call_next_rejected(api):
    """PRD §3.5: "When no `QUEUED` ticket exists for the current logical date, the call is rejected with `ERR_QUEUE_EMPTY`."

    Design: Corner/errors/queue_empty_call_next_rejected
    """
    advisor = create_advisor(full_name="Advisor R7", email="r7a@x.edu")
    res = api.call_next_drop_in_ticket(make_advisor_headers(advisor["id"]))
    validate_error(res, ApiErrorId.ERR_QUEUE_EMPTY)


# ─── Corner: state_machines / dropin_leave_from_served_rejected ──────────────

def test_dropin_leave_from_served_rejected(api, front_desk_headers):
    """PRD §3.5: "Serving a ticket that is not `CALLED`, or recording a departure for a ticket not in `QUEUED` or `CALLED`, is rejected with `ERR_TICKET_INVALID_STATE`; an unknown ticket reference yields `ERR_TICKET_NOT_FOUND`."
    PRD §3.5: "`SERVED` and `LEFT` are terminal."

    Design: Corner/state_machines/dropin_leave_from_served_rejected
    """
    advisor = create_advisor(full_name="Advisor SM5", email="sm5@x.edu")
    student = create_student(full_name="S5", email="s5c@x.edu")
    ticket = join_queue(student["id"], reason="quick question")
    advisor_hdrs = make_advisor_headers(advisor["id"])
    called = validate_success(api.call_next_drop_in_ticket(advisor_hdrs), 200)
    assert called["id"] == ticket["id"]
    served = validate_success(
        api.complete_drop_in_ticket(ticket["id"], advisor_hdrs), 200
    )
    assert served["status"] == "SERVED"
    res = api.leave_drop_in_ticket(ticket["id"], front_desk_headers)
    validate_error(res, ApiErrorId.ERR_TICKET_INVALID_STATE)


# ─── Corner: cross_cutting_layers / daily_close_expires_stale_queued_tickets ──

def test_daily_close_expires_stale_queued_tickets(api, director_headers):
    """PRD §3.5: "The close-of-day sweep moves every ticket still `QUEUED` whose `queue_date` predates the current logical date to `LEFT`."
    PRD §3.9: "And every drop-in ticket still `QUEUED` from an earlier `queue_date` is marked `LEFT`. The sweep's response reports the two tallies as `no_show_marked` and `queue_expired`."

    Design: Corner/cross_cutting_layers/daily_close_expires_stale_queued_tickets
    """
    student = create_student(full_name="OP1", email="op1@x.edu")
    ticket = join_queue(student["id"], reason="late question")  # queued 2026-08-01
    set_logical_clock("2026-08-02T08:00:00Z")
    report = validate_success(api.daily_close(director_headers), 200)
    assert report["queue_expired"] == 1
    after = validate_success(
        api.get_drop_in_ticket(ticket["id"], director_headers), 200
    )
    assert after["status"] == "LEFT"
