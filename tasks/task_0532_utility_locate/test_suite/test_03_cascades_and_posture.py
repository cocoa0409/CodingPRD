"""Bubble-up cascades and conserved-quantity invariants: positive-response -> ticket posture,
mark-out complete -> ticket MARKED + window, assignment cancel counter conservation, refresh
window conservation, cancel cascades to meet requests, immediate submit fan-out.

Covers Difficulty/transitive_cascade, Difficulty/compensating_invariant, and the
endpoints / consistency_model corner instances.
"""
from test_helpers import (
    validate_success, validate_error,
    register_excavator, register_member, register_tech, create_ticket, submit_ticket,
    first_notification, get_notification_for_member, post_response, dispatch, go_en_route,
    create_markout, complete_markout,
    create_refresh_markout, current_ticket_version,
    setup_cleared_ticket, setup_marked_ticket, setup_en_route_with_markout,
    create_meet, set_clock,
    make_excavator_headers, make_facility_owner_headers, make_locate_tech_headers,
    ApiErrorId, COVERING_POLYGON,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/transitive_cascade/positive_response_bubbles_ticket_all_clear_then_markable
# ─────────────────────────────────────────────────────────────────────────────

def test_positive_response_bubbles_ticket_to_responses_complete(api):
    """PRD §3.4: "For a `CLEAR` or `MARKED_BY_OWNER` response, if the open count has now reached
    zero and no notification is in `CONFLICT`, the ticket advances from `SUBMITTED` to
    `RESPONSES_COMPLETE`."

    Design: Difficulty/transitive_cascade/positive_response_bubbles_ticket_all_clear_then_markable
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note = first_notification(ticket["id"], mem["id"])

    post_response(note["id"], mem["id"], "CLEAR")
    after = validate_success(
        api.get_locate_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200
    )
    assert after["open_response_count"] == 0
    assert after["response_posture"] == "ALL_CLEAR"
    assert after["status"] == "RESPONSES_COMPLETE"


def test_positive_response_sets_notification_clear(api):
    """PRD §3.4: "A `CLEAR` outcome moves the notification's `response_status` to `CLEAR`"
    PRD §3.4: "In every case the ticket's `open_response_count` is decreased by one and the
    ticket's `response_posture` is recomputed."

    Design: Difficulty/transitive_cascade/positive_response_bubbles_ticket_all_clear_then_markable
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note = first_notification(ticket["id"], mem["id"])
    post_response(note["id"], mem["id"], "CLEAR")
    note_after = validate_success(
        api.get_utility_notification(note["id"], make_facility_owner_headers(mem["id"])), 200
    )
    assert note_after["response_status"] == "CLEAR"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/transitive_cascade/markout_complete_bubbles_ticket_marked_and_window
# ─────────────────────────────────────────────────────────────────────────────

def test_markout_complete_bubbles_ticket_marked_and_window(api):
    """PRD §3.7: "This bubbles up to the ticket: the ticket's `markout_completed_at` is set to the
    completion instant, its `dig_window_expires_at` — the latest legal dig start — is set to that
    same 21-day expiry, and the ticket advances from `RESPONSES_COMPLETE` to `MARKED`."

    Design: Difficulty/transitive_cascade/markout_complete_bubbles_ticket_marked_and_window
    """
    base = setup_en_route_with_markout(ticket_type="EMERGENCY", marks_count=3)
    complete_markout(base["markout"]["id"], base["tech"]["id"])
    ticket = validate_success(
        api.get_locate_ticket(base["ticket"]["id"], make_excavator_headers(base["excavator"]["id"])), 200
    )
    assert ticket["status"] == "MARKED"
    assert ticket["markout_completed_at"] == "2026-05-01T00:00:00Z"
    assert ticket["dig_window_expires_at"] == "2026-05-22T00:00:00Z"


def test_markout_complete_sets_valid_until_21_days(api):
    """PRD §3.7: "On completion the mark-out stamps `completed_at` with the clock and sets its
    `valid_until` to `completed_at` plus 21 days, the mark-out validity span."

    Design: Difficulty/transitive_cascade/markout_complete_bubbles_ticket_marked_and_window
    """
    base = setup_en_route_with_markout(ticket_type="EMERGENCY", marks_count=3)
    completed = validate_success(
        api.complete_mark_out(base["markout"]["id"], make_locate_tech_headers(base["tech"]["id"])), 200
    )
    assert completed["status"] == "COMPLETE"
    assert completed["valid_until"] == "2026-05-22T00:00:00Z"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/compensating_invariant/tech_active_assignment_count_conserved_on_cancel
# ─────────────────────────────────────────────────────────────────────────────

def test_tech_count_conserved_after_dispatch_then_cancel(api):
    """PRD §3.6: "Cancellation moves the assignment to `CANCELLED`, decrements the tech's
    `active_assignment_count` by one, and as a cascade moves any `IN_PROGRESS` `MarkOut` for that
    assignment to `EXPIRED`."

    Design: Difficulty/compensating_invariant/tech_active_assignment_count_conserved_on_cancel
    """
    base = setup_cleared_ticket()
    mem_id = base["member"]["id"]
    tech_id = base["tech"]["id"]
    asg = dispatch(base["ticket"]["id"], base["notification"]["id"], tech_id, mem_id)
    validate_success(api.cancel_assignment(asg["id"], make_facility_owner_headers(mem_id)), 200)
    tech = validate_success(api.get_locate_tech(tech_id, make_facility_owner_headers(mem_id)), 200)
    assert tech["active_assignment_count"] == 0


def test_assignment_cancel_status_and_count_decrement(api):
    """PRD §3.6: "Cancellation moves the assignment to `CANCELLED`, decrements the tech's
    `active_assignment_count` by one"

    Design: Difficulty/compensating_invariant/tech_active_assignment_count_conserved_on_cancel
    """
    base = setup_cleared_ticket()
    mem_id = base["member"]["id"]
    asg = dispatch(base["ticket"]["id"], base["notification"]["id"], base["tech"]["id"], mem_id)
    cancelled = validate_success(
        api.cancel_assignment(asg["id"], make_facility_owner_headers(mem_id)), 200
    )
    assert cancelled["status"] == "CANCELLED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/compensating_invariant/ticket_open_response_count_conserved_on_markout_expiry
# ─────────────────────────────────────────────────────────────────────────────

def test_refresh_resets_markout_completed_at_and_window(api):
    """PRD §3.7: "the ticket's `markout_completed_at` is reset to the refresh's completion instant
    and its `dig_window_expires_at` is recomputed from that new completion, sliding the window
    forward."

    Design: Difficulty/compensating_invariant/ticket_open_response_count_conserved_on_markout_expiry
    """
    base = setup_marked_ticket()
    tid = base["ticket"]["id"]
    tech_id = base["tech"]["id"]
    set_clock("2026-05-02T00:00:00Z")
    version = current_ticket_version(tid, tech_id)
    mk2 = create_refresh_markout(base["assignment"]["id"], tid, tech_id,
                                 supersedes_markout_id=base["markout"]["id"],
                                 expected_ticket_version=version, marks_count=7)
    complete_markout(mk2["id"], tech_id)
    ticket = validate_success(api.get_locate_ticket(tid, make_locate_tech_headers(tech_id)), 200)
    assert ticket["markout_completed_at"] == "2026-05-02T00:00:00Z"
    assert ticket["dig_window_expires_at"] == "2026-05-23T00:00:00Z"


def test_refresh_conserves_single_complete_markout(api):
    """PRD §3.7: "When the refresh mark-out reaches `COMPLETE`, the prior mark-out it supersedes is
    moved to `SUPERSEDED`"

    Design: Difficulty/compensating_invariant/ticket_open_response_count_conserved_on_markout_expiry
    """
    base = setup_marked_ticket()
    tid = base["ticket"]["id"]
    tech_id = base["tech"]["id"]
    mk1_id = base["markout"]["id"]
    set_clock("2026-05-02T00:00:00Z")
    version = current_ticket_version(tid, tech_id)
    mk2 = create_refresh_markout(base["assignment"]["id"], tid, tech_id,
                                 supersedes_markout_id=mk1_id,
                                 expected_ticket_version=version, marks_count=7)
    mk2_after = validate_success(api.complete_mark_out(mk2["id"], make_locate_tech_headers(tech_id)), 200)
    mk1_after = validate_success(api.get_mark_out(mk1_id, make_locate_tech_headers(tech_id)), 200)
    assert mk1_after["status"] == "SUPERSEDED"
    assert mk2_after["status"] == "COMPLETE"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/endpoints/cancel_ticket_cascades_meet_requests_to_declined
# ─────────────────────────────────────────────────────────────────────────────

def test_cancel_ticket_cascades_meet_to_declined(api):
    """PRD §3.2: "When a cancel succeeds the ticket moves to `CANCELLED`; any still-`PENDING`
    notifications remain `PENDING` (no member may answer a cancelled ticket) and, as a cascade,
    every open `MeetRequest` for the ticket — those in `REQUESTED` or `SCHEDULED` — is moved to
    `DECLINED`."

    Design: Corner/endpoints/cancel_ticket_cascades_meet_requests_to_declined
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL")
    meet = create_meet(ticket["id"], mem["id"], exc["id"], 10, 60)
    exc_h = make_excavator_headers(exc["id"])
    cancelled = validate_success(api.cancel_ticket(ticket["id"], exc_h), 200)
    assert cancelled["status"] == "CANCELLED"
    meet_after = validate_success(api.get_meet_request(meet["id"], exc_h), 200)
    assert meet_after["status"] == "DECLINED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/endpoints/cancel_ticket_blocked_by_active_assignment
# ─────────────────────────────────────────────────────────────────────────────

def test_cancel_ticket_blocked_by_active_assignment(api):
    """PRD §3.2: "Cancelling from `SUBMITTED` carries an additional guard: it is blocked with
    `ERR_ASSIGNMENT_ACTIVE` if any `LocateAssignment` for the ticket is currently `DISPATCHED` or
    `EN_ROUTE`."

    Design: Corner/endpoints/cancel_ticket_blocked_by_active_assignment
    """
    # Two covering members: clear mem_a's leg so a tech can be dispatched on it,
    # while mem_b's leg stays PENDING to keep the ticket in SUBMITTED. The
    # ERR_ASSIGNMENT_ACTIVE guard only applies when cancelling FROM SUBMITTED.
    exc = register_excavator()
    mem_a = register_member(name="Gas A", facility_type="GAS", service_polygon=COVERING_POLYGON)
    register_member(name="Elec B", facility_type="ELECTRIC", service_polygon=COVERING_POLYGON)
    tech = register_tech(mem_a["id"], certified=("GAS",))
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note_a = get_notification_for_member(ticket["id"], mem_a["id"])
    post_response(note_a["id"], mem_a["id"], "CLEAR")
    dispatch(ticket["id"], note_a["id"], tech["id"], mem_a["id"])
    resp = api.cancel_ticket(ticket["id"], make_excavator_headers(exc["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_ACTIVE)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/consistency_model/notification_side_effects_visible_in_same_submit_response
# ─────────────────────────────────────────────────────────────────────────────

def test_submit_response_reflects_notification_fanout(api):
    """PRD §3.2: "The ticket's `notified_member_count` is set to the number of notifications created
    and `open_response_count` is set to the same value. Finally the ticket's `response_posture` is
    recomputed to `AWAITING_RESPONSES`."

    Design: Corner/consistency_model/notification_side_effects_visible_in_same_submit_response
    """
    exc = register_excavator()
    register_member(name="Gas A", facility_type="GAS", service_polygon=COVERING_POLYGON)
    register_member(name="Water B", facility_type="WATER", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    after = validate_success(api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200)
    assert after["notified_member_count"] == 2
    assert after["open_response_count"] == 2
    assert after["response_posture"] == "AWAITING_RESPONSES"
