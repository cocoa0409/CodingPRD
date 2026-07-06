"""Validation precedence, boundary precision, cross-entity state dependencies, temporal/spatial
overlap, and submission/dispatch guard errors.

Covers Difficulty/priority_pair_validation_conflict, Difficulty/boundary_precision_check,
Difficulty/cross_entity_state_dependency, Difficulty/resource_temporal_overlap, and the
validations corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    register_excavator, register_member, register_tech, create_ticket, submit_ticket,
    first_notification, get_notification_for_member, post_response, dispatch, go_en_route,
    create_markout, complete_markout,
    setup_cleared_ticket, setup_en_route_with_markout, setup_submitted_ticket,
    create_meet, schedule_meet, set_clock,
    make_excavator_headers, make_facility_owner_headers, make_locate_tech_headers,
    ApiErrorId, COVERING_POLYGON,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/priority_pair_validation_conflict/state_vs_ownership_on_positive_response
# ─────────────────────────────────────────────────────────────────────────────

def test_answered_notification_state_beats_ownership(api):
    """PRD §3.4: "Posting is permitted only while the parent ticket is `SUBMITTED` (otherwise
    `ERR_TICKET_NOT_ACCEPTING_RESPONSES`) and only while the target notification is still `PENDING`
    (otherwise `ERR_NOTIFICATION_ALREADY_ANSWERED`); the acting `FacilityOwner` must own the
    notification's `member_utility_id`, or the request is rejected with `ERR_NOT_NOTIFICATION_OWNER`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_ownership_on_positive_response
    """
    exc = register_excavator()
    mem_a = register_member(name="Gas A", facility_type="GAS", service_polygon=COVERING_POLYGON)
    # mem_b must also cover the dig site so BOTH members are routed notifications;
    # that keeps the ticket in SUBMITTED after mem_a answers (mem_b's leg is still
    # PENDING), isolating notification-state (not ticket-state) as the tripped guard.
    mem_b = register_member(name="Elec B", facility_type="ELECTRIC",
                            service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note_a = get_notification_for_member(ticket["id"], mem_a["id"])
    post_response(note_a["id"], mem_a["id"], "CLEAR")
    # Non-owner B answers the already-answered notification: state error (409) wins over ownership.
    resp = api.create_positive_response(
        {"notification_id": note_a["id"], "outcome": "CONFLICT"},
        make_facility_owner_headers(mem_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOTIFICATION_ALREADY_ANSWERED)


def test_answered_notification_second_owner_post_rejected(api):
    """PRD §3.4: "only while the target notification is still `PENDING` (otherwise
    `ERR_NOTIFICATION_ALREADY_ANSWERED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_ownership_on_positive_response
    """
    # Two covering members so answering one leg leaves the ticket in SUBMITTED
    # (the other leg is still PENDING), isolating the notification-already-answered
    # guard rather than the ticket-state guard.
    exc = register_excavator()
    mem_a = register_member(name="Gas A", facility_type="GAS", service_polygon=COVERING_POLYGON)
    register_member(name="Elec B", facility_type="ELECTRIC", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note = get_notification_for_member(ticket["id"], mem_a["id"])
    post_response(note["id"], mem_a["id"], "CLEAR")
    resp = api.create_positive_response(
        {"notification_id": note["id"], "outcome": "CLEAR"},
        make_facility_owner_headers(mem_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOTIFICATION_ALREADY_ANSWERED)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/priority_pair_validation_conflict/certification_safety_vs_fiscal_geometry_on_markout
# ─────────────────────────────────────────────────────────────────────────────

def test_uncertified_tech_dispatch_rejected(api):
    """PRD §3.6: "the tech's `certified_facility_types` must include the notified member's
    `facility_type`, or the create is rejected with `ERR_TECH_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/certification_safety_vs_fiscal_geometry_on_markout
    """
    base = setup_cleared_ticket(ticket_type="EMERGENCY", member_facility="GAS",
                                tech_certified=("WATER",))
    resp = api.create_locate_assignment(
        {"ticket_id": base["ticket"]["id"], "notification_id": base["notification"]["id"],
         "locate_tech_id": base["tech"]["id"]},
        make_facility_owner_headers(base["member"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TECH_NOT_CERTIFIED)


def test_certified_tech_dispatch_succeeds(api):
    """PRD §3.6: "the tech's `certified_facility_types` must include the notified member's
    `facility_type`, or the create is rejected with `ERR_TECH_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/certification_safety_vs_fiscal_geometry_on_markout
    """
    base = setup_cleared_ticket(ticket_type="EMERGENCY", member_facility="GAS",
                                tech_certified=("GAS",))
    asg = validate_success(
        api.create_locate_assignment(
            {"ticket_id": base["ticket"]["id"], "notification_id": base["notification"]["id"],
             "locate_tech_id": base["tech"]["id"]},
            make_facility_owner_headers(base["member"]["id"]),
        ), 201,
    )
    assert asg["status"] == "DISPATCHED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/sla_breach_at_exact_due_instant_ticket_expiry
# ─────────────────────────────────────────────────────────────────────────────

def test_ticket_not_expired_at_exact_due_but_expired_after(api):
    """PRD §3.5: "When the clock is advanced strictly past a submitted ticket's `sla_due_at` while
    at least one notification remains `PENDING` (that is, `open_response_count` is greater than
    zero), the ticket auto-transitions from `SUBMITTED` to `EXPIRED` and its `response_posture` is
    recomputed to `SLA_BREACHED`."

    Design: Difficulty/boundary_precision_check/sla_breach_at_exact_due_instant_ticket_expiry
    """
    base = setup_submitted_ticket(ticket_type="EMERGENCY")
    tid = base["ticket"]["id"]
    exc_h = make_excavator_headers(base["excavator"]["id"])
    # sla_due_at = 02:00:00. At exactly due (not strictly past): still SUBMITTED.
    set_clock("2026-05-01T02:00:00Z")
    at_due = validate_success(api.get_locate_ticket(tid, exc_h), 200)
    assert at_due["status"] == "SUBMITTED"
    assert at_due["response_posture"] == "AWAITING_RESPONSES"
    # One second past: EXPIRED / SLA_BREACHED.
    set_clock("2026-05-01T02:00:01Z")
    past = validate_success(api.get_locate_ticket(tid, exc_h), 200)
    assert past["status"] == "EXPIRED"
    assert past["response_posture"] == "SLA_BREACHED"


def test_ticket_expired_blocks_further_response(api):
    """PRD §3.5: "Each still-pending notification keeps its `PENDING` `response_status`, but the
    ticket is now expired and no member may respond to it any longer."

    Design: Difficulty/boundary_precision_check/sla_breach_at_exact_due_instant_ticket_expiry
    """
    base = setup_submitted_ticket(ticket_type="EMERGENCY")
    tid = base["ticket"]["id"]
    note = base["notification"]
    mem_id = base["member"]["id"]
    set_clock("2026-05-01T02:00:01Z")
    resp = api.create_positive_response(
        {"notification_id": note["id"], "outcome": "CLEAR"},
        make_facility_owner_headers(mem_id),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_ACCEPTING_RESPONSES)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/no_members_in_area_empty_set_on_submit
# ─────────────────────────────────────────────────────────────────────────────

def test_submit_no_members_in_area_rejected(api):
    """PRD §3.2: "at least one `ACTIVE` member utility's `service_polygon` must overlap the
    `dig_polygon` under the routing predicate of §2.7, failing which the submission is rejected
    with `ERR_NO_MEMBERS_IN_AREA`"

    Design: Difficulty/boundary_precision_check/no_members_in_area_empty_set_on_submit
    """
    exc = register_excavator()
    register_member(name="FarAway", facility_type="TELECOM",
                    service_polygon={"min_x": 900, "min_y": 900, "max_x": 1000, "max_y": 1000})
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    resp = api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_MEMBERS_IN_AREA)


def test_submit_with_covering_member_succeeds(api):
    """PRD §3.2: "at least one `ACTIVE` member utility's `service_polygon` must overlap the
    `dig_polygon` under the routing predicate of §2.7, failing which the submission is rejected
    with `ERR_NO_MEMBERS_IN_AREA`"

    Design: Difficulty/boundary_precision_check/no_members_in_area_empty_set_on_submit
    """
    exc = register_excavator()
    register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    after = validate_success(api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200)
    assert after["status"] == "SUBMITTED"
    assert after["notified_member_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/markout_complete_requires_ticket_all_clear
# ─────────────────────────────────────────────────────────────────────────────

def test_markout_complete_requires_all_clear(api):
    """PRD §3.7: "Completion requires the mark-out to be in `IN_PROGRESS` (otherwise
    `ERR_MARKOUT_NOT_IN_PROGRESS`), the parent ticket's `response_posture` to be `ALL_CLEAR` — no
    unresolved conflict may remain — (otherwise `ERR_TICKET_NOT_ALL_CLEAR`)"

    Design: Difficulty/cross_entity_state_dependency/markout_complete_requires_ticket_all_clear
    """
    exc = register_excavator()
    mem_a = register_member(name="Gas A", facility_type="GAS", service_polygon=COVERING_POLYGON)
    mem_b = register_member(name="Water B", facility_type="WATER", service_polygon=COVERING_POLYGON)
    tech = register_tech(mem_a["id"], certified=("GAS",))
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note_a = get_notification_for_member(ticket["id"], mem_a["id"])
    note_b = get_notification_for_member(ticket["id"], mem_b["id"])
    post_response(note_a["id"], mem_a["id"], "CLEAR")
    post_response(note_b["id"], mem_b["id"], "CONFLICT")
    asg = dispatch(ticket["id"], note_a["id"], tech["id"], mem_a["id"])
    go_en_route(asg["id"], tech["id"])
    mk = create_markout(asg["id"], ticket["id"], tech["id"], marks_count=2)
    resp = api.complete_mark_out(mk["id"], make_locate_tech_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_ALL_CLEAR)
    ticket_after = validate_success(api.get_locate_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200)
    assert ticket_after["response_posture"] == "CONFLICT"


def test_conflict_response_sets_posture_conflict(api):
    """PRD §3.4: "For a `CONFLICT` response the posture becomes `CONFLICT`, and that conflict blocks
    the ticket from reaching `RESPONSES_COMPLETE` even once the open count hits zero — a single
    unresolved conflict holds the whole dig."

    Design: Difficulty/cross_entity_state_dependency/markout_complete_requires_ticket_all_clear
    """
    exc = register_excavator()
    mem_a = register_member(name="Gas A", facility_type="GAS", service_polygon=COVERING_POLYGON)
    mem_b = register_member(name="Water B", facility_type="WATER", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note_a = get_notification_for_member(ticket["id"], mem_a["id"])
    note_b = get_notification_for_member(ticket["id"], mem_b["id"])
    post_response(note_a["id"], mem_a["id"], "CLEAR")
    post_response(note_b["id"], mem_b["id"], "CONFLICT")
    ticket_after = validate_success(api.get_locate_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200)
    assert ticket_after["response_posture"] == "CONFLICT"
    assert ticket_after["status"] == "SUBMITTED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/assignment_complete_requires_markout_complete
# ─────────────────────────────────────────────────────────────────────────────

def test_assignment_complete_requires_markout_complete(api):
    """PRD §3.6: "Completing the assignment moves it from `EN_ROUTE` to `COMPLETED`; it requires
    the assignment to be in `EN_ROUTE` (otherwise `ERR_ASSIGNMENT_NOT_EN_ROUTE`), the acting tech to
    own it (otherwise `ERR_NOT_ASSIGNMENT_TECH`), and a `MarkOut` for this assignment to already be
    in `COMPLETE` (otherwise `ERR_MARKOUT_NOT_COMPLETE`)."

    Design: Difficulty/cross_entity_state_dependency/assignment_complete_requires_markout_complete
    """
    base = setup_en_route_with_markout(ticket_type="EMERGENCY", marks_count=2)
    resp = api.complete_assignment(base["assignment"]["id"], make_locate_tech_headers(base["tech"]["id"]))
    validate_error(resp, ApiErrorId.ERR_MARKOUT_NOT_COMPLETE)


def test_assignment_completes_after_markout_complete(api):
    """PRD §3.6: "On completion the assignment stamps `completed_at` with the clock, sets
    `sla_breached` to true exactly when `completed_at` is strictly after `sla_deadline_at`, moves to
    `COMPLETED`, and decrements the tech's `active_assignment_count` by one."

    Design: Difficulty/cross_entity_state_dependency/assignment_complete_requires_markout_complete
    """
    base = setup_en_route_with_markout(ticket_type="EMERGENCY", marks_count=2)
    complete_markout(base["markout"]["id"], base["tech"]["id"])
    completed = validate_success(
        api.complete_assignment(base["assignment"]["id"], make_locate_tech_headers(base["tech"]["id"])), 200
    )
    assert completed["status"] == "COMPLETED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/meet_window_half_open_overlap_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_meet_window_overlap_rejected(api):
    """PRD §3.9: "Overlap is judged on the half-open interval from `proposed_start_min` up to but
    not including `proposed_end_min`, so two windows that merely touch at an endpoint do not
    overlap; a genuine overlap is rejected with `ERR_MEET_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/meet_window_half_open_overlap_rejected
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL")
    meet1 = create_meet(ticket["id"], mem["id"], exc["id"], 100, 200)
    meet2 = create_meet(ticket["id"], mem["id"], exc["id"], 150, 250)
    schedule_meet(meet1["id"], mem["id"])
    resp = api.schedule_meet_request(meet2["id"], make_facility_owner_headers(mem["id"]))
    validate_error(resp, ApiErrorId.ERR_MEET_WINDOW_OVERLAP)


def test_meet_touching_windows_allowed(api):
    """PRD §3.9: "two windows that merely touch at an endpoint do not overlap"

    Design: Difficulty/resource_temporal_overlap/meet_window_half_open_overlap_rejected
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL")
    meet1 = create_meet(ticket["id"], mem["id"], exc["id"], 100, 200)
    meet2 = create_meet(ticket["id"], mem["id"], exc["id"], 200, 300)
    schedule_meet(meet1["id"], mem["id"])
    scheduled2 = validate_success(
        api.schedule_meet_request(meet2["id"], make_facility_owner_headers(mem["id"])), 200
    )
    assert scheduled2["status"] == "SCHEDULED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/dig_polygon_service_area_box_intersection_routing
# ─────────────────────────────────────────────────────────────────────────────

def test_routing_open_interior_overlap_only(api):
    """PRD §2.7: "A ticket routes to a member if and only if their two rectangles overlap on open
    interiors along both axes"
    PRD §2.7: "Rectangles that merely touch along an edge — for example, where a service
    rectangle's left edge exactly equals the dig rectangle's right edge — do not overlap and do not
    route."

    Design: Difficulty/resource_temporal_overlap/dig_polygon_service_area_box_intersection_routing
    """
    exc = register_excavator()
    m1 = register_member(name="Overlap M1", facility_type="GAS",
                         service_polygon={"min_x": 0, "min_y": 0, "max_x": 15, "max_y": 15})
    register_member(name="Touch M2", facility_type="WATER",
                    service_polygon={"min_x": 20, "min_y": 0, "max_x": 30, "max_y": 15})
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")  # dig [10,10,20,20]
    exc_h = make_excavator_headers(exc["id"])
    after = validate_success(api.submit_ticket(ticket["id"], exc_h), 200)
    assert after["notified_member_count"] == 1
    rows, _meta = validate_paginated(api.list_ticket_notifications(ticket["id"], exc_h))
    assert len(rows) == 1
    assert rows[0]["member_utility_id"] == m1["id"]


def test_routing_high_priority_flag_on_gas_notification(api):
    """PRD §3.2: "records `is_high_priority` as true when that member's `facility_type` is `GAS` or
    `OIL` and false otherwise."

    Design: Difficulty/resource_temporal_overlap/dig_polygon_service_area_box_intersection_routing
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="EMERGENCY")
    submit_ticket(ticket["id"], exc["id"])
    note = first_notification(ticket["id"], mem["id"])
    assert note["is_high_priority"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/meet_request_required_for_normal_non_white_lined_submit
# ─────────────────────────────────────────────────────────────────────────────

def test_normal_non_white_lined_requires_meet_request(api):
    """PRD §3.2: "if the ticket is `NORMAL` and not white-lined, a `MeetRequest` for this ticket
    must already exist in one of the states `REQUESTED`, `SCHEDULED`, or `COMPLETED`, failing which
    the submission is rejected with `ERR_MEET_REQUEST_REQUIRED`."

    Design: Corner/validations/meet_request_required_for_normal_non_white_lined_submit
    """
    exc = register_excavator()
    register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL")  # is_white_lined defaults false
    resp = api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"]))
    validate_error(resp, ApiErrorId.ERR_MEET_REQUEST_REQUIRED)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/submit_suspended_excavator_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_submit_suspended_excavator_rejected(api):
    """PRD §3.2: "then the filing excavator's `status` must be `ACTIVE`, or the submission is
    rejected with `ERR_EXCAVATOR_SUSPENDED`"

    Design: Corner/validations/submit_suspended_excavator_rejected
    """
    exc = register_excavator()
    register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL", is_white_lined=True)
    from test_helpers import TEST_USERS
    validate_success(api.suspend_excavator(exc["id"], TEST_USERS["admin_headers"]), 200)
    resp = api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"]))
    validate_error(resp, ApiErrorId.ERR_EXCAVATOR_SUSPENDED)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/dispatch_off_duty_tech_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_dispatch_off_duty_tech_rejected(api):
    """PRD §3.6: "the dispatched tech's `status` must be `AVAILABLE` and not `OFF_DUTY`, or the
    create is rejected with `ERR_TECH_OFF_DUTY`"

    Design: Corner/validations/dispatch_off_duty_tech_rejected
    """
    base = setup_cleared_ticket(ticket_type="EMERGENCY", member_facility="GAS", tech_certified=("GAS",))
    from test_helpers import TEST_USERS
    validate_success(api.set_tech_off_duty(base["tech"]["id"], TEST_USERS["admin_headers"]), 200)
    resp = api.create_locate_assignment(
        {"ticket_id": base["ticket"]["id"], "notification_id": base["notification"]["id"],
         "locate_tech_id": base["tech"]["id"]},
        make_facility_owner_headers(base["member"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TECH_OFF_DUTY)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/markout_not_refreshable_when_target_not_complete
# ─────────────────────────────────────────────────────────────────────────────

def test_refresh_target_not_complete_rejected(api):
    """PRD §3.7: "A refresh may only supersede a mark-out that is currently `COMPLETE` on that
    ticket, and only while the ticket's dig window has not yet expired (the clock is at or before
    the ticket's current `dig_window_expires_at`); a refresh that violates either condition is
    rejected with `ERR_MARKOUT_NOT_REFRESHABLE`."

    Design: Corner/validations/markout_not_refreshable_when_target_not_complete
    """
    base = setup_en_route_with_markout(ticket_type="EMERGENCY", marks_count=2)
    tid = base["ticket"]["id"]
    tech_id = base["tech"]["id"]
    mk1_id = base["markout"]["id"]  # left IN_PROGRESS
    ticket = validate_success(api.get_locate_ticket(tid, make_locate_tech_headers(tech_id)), 200)
    resp = api.create_mark_out(
        {"assignment_id": base["assignment"]["id"], "ticket_id": tid, "marks_count": 3,
         "supersedes_markout_id": mk1_id, "expected_ticket_version": ticket["version"]},
        make_locate_tech_headers(tech_id),
    )
    validate_error(resp, ApiErrorId.ERR_MARKOUT_NOT_REFRESHABLE)
