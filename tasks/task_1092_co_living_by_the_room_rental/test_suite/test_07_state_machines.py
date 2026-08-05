"""Corner queue B — initial states, invalid transitions, terminal lockdown,
cyclic bounds, and the conditional room out-of-service cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    pending_membership, active_tenancy, base_portfolio, new_room,
    open_ticket, resolve_ticket, file_incident, adjudicate, dispute,
    new_payout, project, file_notice, do_move_out, set_clock,
    read_membership, read_room, read_house, read_member, read_incident,
    read_ticket, read_payout,
    manager_headers, compliance_headers, finance_headers, make_member_headers,
)


def test_membership_starts_in_pending_move_in_and_current(api):
    """PRD §3.4: "it creates the membership in tenancy_status PENDING_MOVE_IN and
    billing_status CURRENT". PRD §3.4: "period_days is fixed at 7 when the billing
    cycle is WEEKLY ... base_period_rate_cents is pinned to the room's
    weekly_rate_cents when WEEKLY ... and deposit_cents is copied from the
    application's required_deposit_cents."

    Design: Corner/state_machines/corner_membership_starts_in_pending_move_in_and_current
    """
    ctx = pending_membership(api, weekly=25000, monthly=100000, budget=60000)
    mem = ctx["membership"]
    assert ctx["application"]["required_deposit_cents"] == 25000
    assert mem["version"] == 1
    assert mem["tenancy_status"] == "PENDING_MOVE_IN" and mem["billing_status"] == "CURRENT"
    assert mem["period_days"] == 7 and mem["base_period_rate_cents"] == 25000
    assert mem["deposit_cents"] == 25000
    assert mem["notice_reason"] is None and mem["scheduled_move_out_date"] is None
    assert mem["actual_move_out_date"] is None and mem["effective_end_date"] is None
    assert mem["balance_due_cents"] == 0
    assert mem["member_id"] == ctx["member"]["id"] and mem["room_id"] == ctx["room"]["id"]
    assert mem["house_id"] == ctx["house"]["id"]
    from test_helpers import read_application
    assert read_application(api, ctx["application"]["id"])["status"] == "CONVERTED"
    assert read_room(api, ctx["room"]["id"])["occupancy_state"] == "RESERVED"


def test_move_in_twice_returns_invalid_membership_state(api):
    """PRD §3.4: "Moving the resident in is a CommunityManager action, legal only
    from PENDING_MOVE_IN (ERR_INVALID_MEMBERSHIP_STATE)."

    Design: Corner/state_machines/corner_move_in_twice_returns_invalid_membership_state
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    resp = api.move_in(ctx["membership"]["id"], manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_MEMBERSHIP_STATE.value)
    assert read_membership(api, ctx["membership"]["id"])["tenancy_status"] == "ACTIVE"
    assert read_room(api, ctx["room"]["id"])["occupancy_state"] == "OCCUPIED"
    house = read_house(api, ctx["house"]["id"])
    assert house["occupied_room_count"] == 1 and house["reserved_room_count"] == 0


def test_notice_on_pending_move_in_returns_invalid_membership_state(api):
    """PRD §3.8: "Notice is legal only from ACTIVE (ERR_INVALID_MEMBERSHIP_STATE)."

    Design: Corner/state_machines/corner_notice_on_pending_move_in_membership_returns_invalid_membership_state
    """
    ctx = pending_membership(api, weekly=25000, monthly=100000, budget=60000)
    resp = api.file_notice(ctx["membership"]["id"],
                           {"reason": "MEMBER_INITIATED", "scheduled_move_out_date": "2026-07-01"},
                           make_member_headers(ctx["member"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_MEMBERSHIP_STATE.value)
    mem = read_membership(api, ctx["membership"]["id"])
    assert mem["tenancy_status"] == "PENDING_MOVE_IN" and mem["notice_reason"] is None
    assert read_room(api, ctx["room"]["id"])["occupancy_state"] == "RESERVED"
    assert read_house(api, ctx["house"]["id"])["notice_pending_room_count"] == 0


def test_cancel_a_moved_out_membership_returns_invalid_membership_state(api):
    """PRD §3.4: "Cancellation is legal only from PENDING_MOVE_IN
    (ERR_INVALID_MEMBERSHIP_STATE) and takes an optional cancel_reason."

    Design: Corner/state_machines/corner_cancel_a_moved_out_membership_returns_invalid_membership_state
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    file_notice(api, ctx["membership"]["id"], "MEMBER_INITIATED", "2026-06-18",
                member_id=ctx["member"]["id"])
    set_clock(api, "2026-06-18T00:00:00Z")
    do_move_out(api, ctx["membership"]["id"], "2026-06-18")
    resp = api.cancel_membership(ctx["membership"]["id"],
                                 {"cancel_reason": "late cancellation attempt"}, manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_MEMBERSHIP_STATE.value)
    mem = read_membership(api, ctx["membership"]["id"])
    assert mem["tenancy_status"] == "MOVED_OUT" and mem["effective_end_date"] == "2026-06-18"
    room = read_room(api, ctx["room"]["id"])
    assert room["occupancy_state"] == "VACANT" and room["available_from_date"] is None
    house = read_house(api, ctx["house"]["id"])
    assert house["vacant_room_count"] == 1 and house["notice_pending_room_count"] == 0


def test_third_dispute_returns_dispute_limit_reached(api):
    """PRD §3.7: "it is legal only while the incident is UPHELD (otherwise
    ERR_INVALID_INCIDENT_STATE) and only while dispute_round is below the two-round
    ceiling (otherwise ERR_DISPUTE_LIMIT_REACHED)."

    Design: Corner/state_machines/corner_third_dispute_returns_dispute_limit_reached
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    set_clock(api, "2026-06-03T00:00:00Z")
    inc = file_incident(api, ctx["membership"]["id"], co="co-2", rule_code="CLEANLINESS",
                        severity="MINOR", description="Dishes left in the shared sink for three days",
                        occurred_at="2026-06-02T09:00:00.000Z")
    member_id = ctx["member"]["id"]
    adjudicate(api, inc["id"], "UPHOLD", co="co-1")
    dispute(api, inc["id"], member_id, reason="Those were not my dishes")
    adjudicate(api, inc["id"], "UPHOLD", co="co-1")
    dispute(api, inc["id"], member_id, reason="Photographic evidence attached")
    adjudicate(api, inc["id"], "UPHOLD", co="co-1")
    resp = api.dispute_incident(inc["id"], {"dispute_reason": "Third attempt"},
                                make_member_headers(member_id))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_LIMIT_REACHED.value)
    stored = read_incident(api, inc["id"])
    assert stored["status"] == "UPHELD" and stored["dispute_round"] == 2
    m = read_member(api, member_id)
    assert m["strike_points"] == 1 and m["standing_band"] == "WATCH"
    assert read_membership(api, ctx["membership"]["id"])["tenancy_status"] == "ACTIVE"


def test_critical_room_ticket_out_of_service_then_resolve_restores(api):
    """PRD §3.9: "a CRITICAL ticket whose area is ROOM and whose room_id names a
    room currently VACANT drives that room VACANT → OUT_OF_SERVICE". PRD §3.9:
    "when the ticket had taken a room OUT_OF_SERVICE — returns that room
    OUT_OF_SERVICE → VACANT and recomputes the house's counts and posture."

    Design: Corner/state_machines/corner_critical_room_ticket_takes_vacant_room_out_of_service_and_resolve_restores_it
    """
    base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
    host_id, house_id = base["host"]["id"], base["house"]["id"]
    room1 = new_room(api, house_id, host_id, "101", weekly_rate_cents=25000, monthly_rate_cents=100000)
    room2 = new_room(api, house_id, host_id, "102", weekly_rate_cents=20000,
                     monthly_rate_cents=80000, private_bath=False)
    ticket = validate_success(api.create_ticket(
        {"house_id": house_id, "area": "ROOM", "severity": "CRITICAL",
         "description": "Window frame rotted through", "room_id": room2["id"]}, manager_headers()), 201)
    assert ticket["sla_deadline_at"] == "2026-06-02T00:00:00.000Z"
    assert read_room(api, room2["id"])["occupancy_state"] == "OUT_OF_SERVICE"
    house = read_house(api, house_id)
    assert house["out_of_service_room_count"] == 1 and house["vacant_room_count"] == 1
    assert house["total_room_count"] == 2
    assert read_room(api, room1["id"])["occupancy_state"] == "VACANT"
    resolved = resolve_ticket(api, ticket["id"], resolution_note="Frame replaced")
    assert resolved["status"] == "RESOLVED" and resolved["breach_hours"] == 0
    assert resolved["rent_credit_cents"] == 0
    assert read_room(api, room2["id"])["occupancy_state"] == "VACANT"
    house2 = read_house(api, house_id)
    assert house2["out_of_service_room_count"] == 0 and house2["vacant_room_count"] == 2
    assert house2["compliance_posture"] == "OPEN"


def test_resolve_a_resolved_ticket_returns_invalid_ticket_state(api):
    """PRD §3.9: "Resolving a work order is a CommunityManager action legal from
    OPEN or SCHEDULED (resolving an already-RESOLVED ticket is
    ERR_INVALID_TICKET_STATE)".

    Design: Corner/state_machines/corner_resolve_a_resolved_ticket_returns_invalid_ticket_state
    """
    base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
    ticket = open_ticket(api, base["house"]["id"], area="COMMON_AREA", severity="NORMAL",
                         description="Porch light out")
    first = resolve_ticket(api, ticket["id"], resolution_note="Bulb replaced")
    assert first["resolved_at"] == "2026-06-01T00:00:00.000Z"
    resp = api.resolve_ticket(ticket["id"], {"resolution_note": "Replaced again"}, manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_TICKET_STATE.value)
    stored = read_ticket(api, ticket["id"])
    assert stored["resolved_at"] == "2026-06-01T00:00:00.000Z"
    assert stored["rent_credit_cents"] == 0


def test_project_a_projected_payout_returns_invalid_payout_state(api):
    """PRD §3.10: "Projection — a FinanceAdmin action from DRAFT
    (ERR_INVALID_PAYOUT_STATE) — runs the accrual variant."

    Design: Corner/state_machines/corner_project_a_projected_payout_returns_invalid_payout_state
    """
    base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
    payout = new_payout(api, base["house"]["id"], "2026-06-01", "2026-06-30")
    project(api, payout["id"], fa="fa-1")
    resp = api.project_payout(payout["id"], finance_headers("fa-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_PAYOUT_STATE.value)
    stored = read_payout(api, payout["id"])
    assert stored["status"] == "PROJECTED" and stored["projected_by_user_id"] == "fa-1"
    assert stored["variant_applied"] == "ACCRUAL_PROJECTION" and stored["net_payout_cents"] == 0


def test_dispute_a_reported_incident_returns_invalid_incident_state(api):
    """PRD §3.7: "Disputing is a Member action on a tenancy they own, supplying a
    dispute_reason; it is legal only while the incident is UPHELD (otherwise
    ERR_INVALID_INCIDENT_STATE)".

    Design: Corner/state_machines/corner_dispute_a_reported_incident_returns_invalid_incident_state
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    set_clock(api, "2026-06-03T00:00:00Z")
    inc = file_incident(api, ctx["membership"]["id"], co="co-2", rule_code="UNAUTHORIZED_OCCUPANT",
                        severity="MINOR", description="Unlisted long-term guest",
                        occurred_at="2026-06-02T20:00:00.000Z")
    resp = api.dispute_incident(inc["id"], {"dispute_reason": "Nothing has been decided yet"},
                                make_member_headers(ctx["member"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_INCIDENT_STATE.value)
    stored = read_incident(api, inc["id"])
    assert stored["status"] == "REPORTED" and stored["dispute_round"] == 0
    m = read_member(api, ctx["member"]["id"])
    assert m["strike_points"] == 0 and m["standing_band"] == "GOOD"
