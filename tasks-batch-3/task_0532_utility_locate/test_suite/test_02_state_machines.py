"""State-machine behavior: mark-out refresh cycle, damage-report branching, invalid
transitions, terminal lockdown, clock-driven auto-transitions.

Covers Difficulty/non_linear_state_machine and the state_machines / errors corner instances.
"""
from test_helpers import (
    validate_success, validate_error,
    register_excavator, register_member, register_tech, create_ticket, submit_ticket,
    first_notification, post_response, dispatch, go_en_route, create_markout, complete_markout,
    create_refresh_markout, current_ticket_version,
    setup_cleared_ticket, setup_marked_ticket, setup_en_route_with_markout, setup_submitted_ticket,
    file_damage_report, review_damage_report,
    create_meet, set_clock,
    make_excavator_headers, make_facility_owner_headers, make_locate_tech_headers,
    ApiErrorId, COVERING_POLYGON,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/markout_refresh_cycle_complete_to_superseded
# ─────────────────────────────────────────────────────────────────────────────

def test_markout_refresh_supersedes_prior_complete(api):
    """PRD §3.7: "When the refresh mark-out reaches `COMPLETE`, the prior mark-out it supersedes is
    moved to `SUPERSEDED`; the ticket's `markout_completed_at` is reset to the refresh's completion
    instant and its `dig_window_expires_at` is recomputed from that new completion, sliding the
    window forward."

    Design: Difficulty/non_linear_state_machine/markout_refresh_cycle_complete_to_superseded
    """
    base = setup_marked_ticket()
    tech_id = base["tech"]["id"]
    tid = base["ticket"]["id"]
    mk1_id = base["markout"]["id"]

    version = current_ticket_version(tid, tech_id)
    mk2 = create_refresh_markout(base["assignment"]["id"], tid, tech_id,
                                 supersedes_markout_id=mk1_id, expected_ticket_version=version,
                                 marks_count=6)
    completed = validate_success(
        api.complete_mark_out(mk2["id"], make_locate_tech_headers(tech_id)), 200
    )

    mk1_after = validate_success(api.get_mark_out(mk1_id, make_locate_tech_headers(tech_id)), 200)
    assert mk1_after["status"] == "SUPERSEDED"
    assert completed["status"] == "COMPLETE"
    assert completed["is_refresh"] is True


def test_markout_refresh_flag_true_ticket_stays_marked(api):
    """PRD §3.7: "The mark-out's `is_refresh` flag is computed true exactly when
    `supersedes_markout_id` is present."
    PRD §3.7: "The ticket stays `MARKED` throughout, now with a fresh window."

    Design: Difficulty/non_linear_state_machine/markout_refresh_cycle_complete_to_superseded
    """
    base = setup_marked_ticket()
    tech_id = base["tech"]["id"]
    tid = base["ticket"]["id"]
    version = current_ticket_version(tid, tech_id)
    mk2 = create_refresh_markout(base["assignment"]["id"], tid, tech_id,
                                 supersedes_markout_id=base["markout"]["id"],
                                 expected_ticket_version=version, marks_count=6)
    assert mk2["is_refresh"] is True
    complete_markout(mk2["id"], tech_id)
    ticket = validate_success(api.get_locate_ticket(tid, make_locate_tech_headers(tech_id)), 200)
    assert ticket["status"] == "MARKED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/damage_report_branching_settle_or_dispute
# ─────────────────────────────────────────────────────────────────────────────

def test_damage_report_branches_settle_and_dispute(api):
    """PRD §3.8: "From `UNDER_REVIEW`, the owner may settle the claim, moving it to `SETTLED`"
    PRD §3.8: "Alternatively, the excavator who owns the parent ticket's `excavator_id` may dispute
    the claim, moving it to `DISPUTED`"

    Design: Difficulty/non_linear_state_machine/damage_report_branching_settle_or_dispute
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    mem_h = make_facility_owner_headers(mem["id"])

    dr1 = file_damage_report(ticket["id"], mem["id"], 4000, dug_within_marks=False)
    dr2 = file_damage_report(ticket["id"], mem["id"], 4000, dug_within_marks=False)
    review_damage_report(dr1["id"], mem["id"])
    review_damage_report(dr2["id"], mem["id"])

    settled = validate_success(api.settle_damage_report(dr1["id"], mem_h), 200)
    disputed = validate_success(
        api.dispute_damage_report(dr2["id"], make_excavator_headers(exc["id"])), 200
    )
    assert settled["status"] == "SETTLED"
    assert disputed["status"] == "DISPUTED"


def test_damage_report_review_moves_to_under_review(api):
    """PRD §3.8: "A `FacilityOwner` who owns the report's `member_utility_id` opens review,
    advancing the report from `FILED` to `UNDER_REVIEW`"

    Design: Difficulty/non_linear_state_machine/damage_report_branching_settle_or_dispute
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    dr = file_damage_report(ticket["id"], mem["id"], 4000, dug_within_marks=False)
    reviewed = validate_success(
        api.review_damage_report(dr["id"], make_facility_owner_headers(mem["id"])), 200
    )
    assert reviewed["status"] == "UNDER_REVIEW"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/submit_ticket_from_submitted_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_submit_already_submitted_ticket_rejected(api):
    """PRD §3.2: "Submission is only allowed while the ticket is still in `INTAKE`; otherwise it is
    rejected with `ERR_TICKET_NOT_IN_INTAKE`."

    Design: Corner/state_machines/submit_ticket_from_submitted_returns_invalid_state
    """
    base = setup_submitted_ticket(ticket_type="EMERGENCY")
    resp = api.submit_ticket(base["ticket"]["id"], make_excavator_headers(base["excavator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_IN_INTAKE)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/cancel_closed_ticket_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_cancel_marked_ticket_rejected(api):
    """PRD §3.2: "An excavator may cancel a ticket while it is in `INTAKE` or `SUBMITTED`; a cancel
    attempt in any other state is rejected with `ERR_TICKET_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_closed_ticket_returns_invalid_state
    """
    base = setup_marked_ticket()
    resp = api.cancel_ticket(base["ticket"]["id"], make_excavator_headers(base["excavator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_CANCELLABLE)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/assignment_en_route_from_completed_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_en_route_completed_assignment_rejected(api):
    """PRD §3.6: "Going en route moves the assignment from `DISPATCHED` to `EN_ROUTE`; it requires
    the assignment to be in `DISPATCHED` (otherwise `ERR_ASSIGNMENT_NOT_DISPATCHED`)"

    Design: Corner/state_machines/assignment_en_route_from_completed_returns_invalid_state
    """
    base = setup_marked_ticket()
    tech_id = base["tech"]["id"]
    # Complete the assignment (mark-out already COMPLETE).
    validate_success(api.complete_assignment(base["assignment"]["id"], make_locate_tech_headers(tech_id)), 200)
    resp = api.assignment_en_route(base["assignment"]["id"], make_locate_tech_headers(tech_id))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_DISPATCHED)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/assignment_breached_on_clock_advance_past_deadline
# ─────────────────────────────────────────────────────────────────────────────

def test_assignment_breached_on_clock_past_deadline(api):
    """PRD §3.6: "When the clock advances strictly past an assignment's `sla_deadline_at` while the
    assignment is still in `DISPATCHED` or `EN_ROUTE`, the assignment auto-transitions to
    `BREACHED`, its `sla_breached` flag is set to true, and the tech's `active_assignment_count`
    is decremented by one."

    Design: Corner/state_machines/assignment_breached_on_clock_advance_past_deadline
    """
    base = setup_cleared_ticket(ticket_type="EMERGENCY", member_facility="GAS",
                                emergency_contact_minutes=60)
    mem_id = base["member"]["id"]
    asg = dispatch(base["ticket"]["id"], base["notification"]["id"], base["tech"]["id"], mem_id)
    # deadline = 00:00 + ceil(60*0.5)=30 -> 00:30. Advance past it.
    set_clock("2026-05-01T00:31:00Z")
    after = validate_success(
        api.get_locate_assignment(asg["id"], make_facility_owner_headers(mem_id)), 200
    )
    assert after["status"] == "BREACHED"
    assert after["sla_breached"] is True
    tech = validate_success(api.get_locate_tech(base["tech"]["id"], make_facility_owner_headers(mem_id)), 200)
    assert tech["active_assignment_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/ticket_expired_on_clock_past_dig_window
# ─────────────────────────────────────────────────────────────────────────────

def test_ticket_expired_on_clock_past_dig_window(api):
    """PRD §3.7: "The dig window is also policed by the clock: when the clock advances strictly past
    a marked ticket's `dig_window_expires_at`, the ticket auto-transitions to `EXPIRED` and, as a
    cascade, its active `COMPLETE` mark-out is moved to `EXPIRED`."

    Design: Corner/state_machines/ticket_expired_on_clock_past_dig_window
    """
    base = setup_marked_ticket()
    tid = base["ticket"]["id"]
    mk_id = base["markout"]["id"]
    # mark completed at 05-01, window expires 05-22; advance past it.
    set_clock("2026-05-23T00:00:00Z")
    ticket = validate_success(api.get_locate_ticket(tid, make_excavator_headers(base["excavator"]["id"])), 200)
    markout = validate_success(api.get_mark_out(mk_id, make_locate_tech_headers(base["tech"]["id"])), 200)
    assert ticket["status"] == "EXPIRED"
    assert markout["status"] == "EXPIRED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/meet_complete_from_requested_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_complete_meet_still_requested_rejected(api):
    """PRD §3.9: "Completing a scheduled meet moves it from `SCHEDULED` to `COMPLETED` and requires
    the request to be in `SCHEDULED` (otherwise `ERR_MEET_NOT_SCHEDULED`)"

    Design: Corner/state_machines/meet_complete_from_requested_returns_invalid_state
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL")
    meet = create_meet(ticket["id"], mem["id"], exc["id"], 10, 60)
    resp = api.complete_meet_request(meet["id"], make_facility_owner_headers(mem["id"]))
    validate_error(resp, ApiErrorId.ERR_MEET_NOT_SCHEDULED)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/errors/assignment_cancel_from_terminal_returns_error
# ─────────────────────────────────────────────────────────────────────────────

def test_cancel_already_cancelled_assignment_rejected(api):
    """PRD §3.6: "A `FacilityOwner` (or `CallCenter` operator) may cancel an assignment while it is
    in `DISPATCHED` or `EN_ROUTE`; a cancel in any other state is rejected with
    `ERR_ASSIGNMENT_NOT_CANCELLABLE`."

    Design: Corner/errors/assignment_cancel_from_terminal_returns_error
    """
    base = setup_cleared_ticket()
    mem_id = base["member"]["id"]
    asg = dispatch(base["ticket"]["id"], base["notification"]["id"], base["tech"]["id"], mem_id)
    mem_h = make_facility_owner_headers(mem_id)
    validate_success(api.cancel_assignment(asg["id"], mem_h), 200)
    resp = api.cancel_assignment(asg["id"], mem_h)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE)
