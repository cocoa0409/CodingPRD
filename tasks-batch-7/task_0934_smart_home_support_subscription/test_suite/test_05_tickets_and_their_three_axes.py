"""Ticket creation, the three independent axes, closure and reopening."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_is_null,
    assert_same_instant,
    assert_ticket,
    create_ticket_payload,
    fetch_ticket,
    first_response,
    list_tickets,
    make_owner_headers,
    new_household,
    new_member,
    new_plan,
    new_subscription,
    new_ticket,
    open_session,
    set_clock,
    setup_account,
    setup_resolved_ticket,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


def test_ticket_creation_pins_both_sla_targets_from_the_in_force_plan(api):
    """PRD 3.5: "`first_response_target_minutes` is set to the plan's
    `first_response_minutes_p1` when the severity is `P1`, `first_response_minutes_p2`
    when it is `P2`, and `first_response_minutes_p3` when it is `P3`."
    PRD 3.5: "`onsite_resolution_target_minutes` is set to sixty times the plan's
    `onsite_resolution_hours_p1`, `onsite_resolution_hours_p2` or
    `onsite_resolution_hours_p3`, selected the same way — the plan states the onsite
    promise in hours and the ticket stores it in minutes."
    PRD 3.5: "The new row begins with `workflow_status` `NEW`, `sla_status` `WITHIN`
    and `dispatch_status` `NOT_REQUIRED`"

    The PLUS plan's P3 targets are 720 minutes and 168 hours, so the pinned onsite
    target is 168 * 60 == 10080 minutes.

    Design: Corner/entities/ticket_creation_pins_computed_sla_targets_from_the_in_force_plan
    """
    world = setup_account(
        plan_kind="PLUS", allow_overage=False, name="Target House", email_prefix="tgt"
    )

    data = validate_success(
        api.create_ticket(
            create_ticket_payload(
                world["household"]["id"],
                severity="P3",
                summary="App notifications delayed",
                opened_by_member_id=world["owner"]["id"],
            ),
            world["owner_headers"],
        ),
        201,
    )

    assert_ticket(data)
    assert data["first_response_target_minutes"] == 720
    assert data["onsite_resolution_target_minutes"] == 10080
    assert data["workflow_status"] == "NEW"
    assert data["sla_status"] == "WITHIN"
    assert data["dispatch_status"] == "NOT_REQUIRED"
    assert data["remote_session_failure_count"] == 0
    assert data["sla_counted_minutes"] == 0


def test_ticket_read_with_unknown_id_reports_ticket_not_found(api):
    """PRD 2.9 rung 10: "Every `Ticket` id named in the path or body exists — otherwise
    `ERR_TICKET_NOT_FOUND`. Applies to the ticket endpoints, visit booking and RMA
    opening."

    Design: Corner/entities/ticket_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_ticket("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(response, ApiErrorId.ERR_TICKET_NOT_FOUND.value, 404)


def test_severity_outside_the_enumeration_reports_invalid_enum(api):
    """PRD 3.5: "A `severity` outside the three-member enumeration is refused with
    `ERR_INVALID_ENUM`"
    PRD 2.9 rung 21: "A value outside the field's enumeration is rejected with
    `ERR_INVALID_ENUM` (HTTP 422). No other field routes here; every other bad value
    is `ERR_INVALID_REQUEST`."

    Design: Corner/validations/invalid_severity_enum_returns_invalid_enum
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Enum House", email_prefix="enu"
    )

    response = api.create_ticket(
        create_ticket_payload(
            world["household"]["id"],
            severity="P4",
            summary="Unknown severity",
            opened_by_member_id=world["owner"]["id"],
        ),
        world["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 422)

    assert list_tickets(household_id=world["household"]["id"]) == []


def test_closing_a_ticket_that_was_never_resolved_is_an_invalid_state(api):
    """PRD 3.5: "Closing is a `SupportAgent` act on a `RESOLVED` ticket."
    PRD 2.9 rung 27: "The target row's current state on the relevant axis permits the
    requested transition, together with any other state precondition of that
    transition for which no more specific rung exists — otherwise
    `ERR_INVALID_STATE`."

    Design: Corner/validations/closing_a_ticket_that_was_never_resolved_returns_invalid_state
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="State House", email_prefix="sta"
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P3",
        summary="Just opened",
        opened_by_member_id=world["owner"]["id"],
    )

    response = api.close_ticket(ticket["id"], {}, AGENT)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    current = fetch_ticket(ticket["id"])
    assert current["workflow_status"] == "NEW"
    assert_is_null(current, "closed_at", "Ticket")


def test_closed_ticket_reports_the_ticket_closed_gate_on_a_customer_reply(api):
    """PRD 3.5: "It stamps `closed_at` with the logical-clock instant, moves
    `workflow_status` to `CLOSED`, and arms gate 3 for every subsequent
    ticket-scoped mutating request except survey submission."
    PRD 2.8: "If the `Ticket` the request resolves to has `workflow_status` equal to
    `CLOSED`, the request is refused with `ERR_TICKET_CLOSED` (HTTP 409)."
    PRD 3.6: "**Meeting the target.** Completing a remote session with a resolving
    verdict, or completing an onsite visit, recomputes the clock and moves the SLA
    axis to `MET` when the axis was in `WITHIN` or `AT_RISK` and the counted minutes
    are less than or equal to `onsite_resolution_target_minutes`."

    Design: Corner/state_machines/closed_ticket_is_locked_down_and_reports_the_ticket_closed_gate
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Closed House", email_prefix="clo"
    )
    ticket = setup_resolved_ticket(world, severity="P2", summary="Chime not sounding")
    validate_success(api.close_ticket(ticket["id"], {}, AGENT), 200)

    response = api.customer_reply(
        ticket["id"], {"message": "One more thing"}, world["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_TICKET_CLOSED.value, 409)

    current = fetch_ticket(ticket["id"])
    assert current["workflow_status"] == "CLOSED"
    assert current["sla_status"] == "MET"
    assert_same_instant(current["closed_at"], "2026-05-01T00:20:00Z", "Ticket.closed_at")


def test_reopen_at_exactly_the_168_hour_boundary_is_refused(api):
    """PRD 3.5: "It is permitted only while the logical clock is strictly before
    `resolved_at` plus 168 hours, which is seven days; at or after that instant the
    request is refused with `ERR_REOPEN_WINDOW_CLOSED`."

    resolved_at is 2026-05-01T00:20:00Z, so 168 hours later is exactly
    2026-05-08T00:20:00Z — the first instant that is no longer strictly before.

    Design: Corner/state_machines/reopen_after_the_168_hour_window_returns_reopen_window_closed
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Reopen House", email_prefix="reo"
    )
    ticket = setup_resolved_ticket(world, severity="P2", summary="Doorbell offline")
    set_clock("2026-05-08T00:20:00Z")

    response = api.reopen_ticket(
        ticket["id"], {"reason": "It came back."}, world["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED.value, 409)

    current = fetch_ticket(ticket["id"])
    assert current["workflow_status"] == "RESOLVED"
    assert_same_instant(current["resolved_at"], "2026-05-01T00:20:00Z", "Ticket.resolved_at")


# ==========================================================================
# Difficulty: the pause/resume loop and the two pinned sibling axes
# ==========================================================================
def _pause_resume_world():
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Loop House", email_prefix="loop"
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P2",
        summary="Camera feed stutters",
        opened_by_member_id=world["owner"]["id"],
    )
    set_clock("2026-05-01T00:30:00Z")
    first_response(ticket["id"], "Triaged.")
    open_session(ticket["id"])
    world["ticket"] = ticket
    return world


def _run_two_pause_cycles(api, world):
    ticket_id = world["ticket"]["id"]
    owner = world["owner_headers"]
    set_clock("2026-05-01T01:00:00Z")
    validate_success(
        api.await_customer(ticket_id, {"note": "Need a photo of the LED."}, AGENT), 200
    )
    set_clock("2026-05-01T03:00:00Z")
    validate_success(api.customer_reply(ticket_id, {"message": "Here is the photo."}, owner), 200)
    set_clock("2026-05-01T04:00:00Z")
    validate_success(api.await_customer(ticket_id, {"note": "Please power-cycle."}, AGENT), 200)
    set_clock("2026-05-01T05:00:00Z")
    validate_success(
        api.customer_reply(ticket_id, {"message": "Done, still broken."}, owner), 200
    )


def test_two_pause_resume_cycles_leave_the_workflow_and_dispatch_axes_untouched(api):
    """PRD 3.5: "Parking the ticket on the customer moves `REMOTE_DIAG →
    AWAITING_CUSTOMER` and is permitted only while `pause_started_at` is null; the
    customer's reply moves `AWAITING_CUSTOMER → REMOTE_DIAG` and is permitted only
    while `pause_started_at` is not null. That pair may repeat any number of times."
    PRD 3.6: "The customer's reply is an `Owner` or `Member` act and carries a
    required `message`; it adds the whole minutes from `pause_started_at` to the
    current instant, by floor division on a 60-second minute, to
    `sla_paused_minutes`, clears `pause_started_at` to null and moves the SLA axis
    back to `WITHIN`."

    Design: Difficulty/non_linear_state_machine/ticket_pause_resume_loop_leaves_other_two_axes_pinned
    """
    world = _pause_resume_world()
    _run_two_pause_cycles(api, world)

    ticket = fetch_ticket(world["ticket"]["id"])
    assert ticket["workflow_status"] == "REMOTE_DIAG"
    assert ticket["sla_status"] == "WITHIN"
    assert ticket["dispatch_status"] == "NOT_REQUIRED"
    assert_is_null(ticket, "pause_started_at", "Ticket")


def test_two_pause_resume_cycles_bank_every_paused_minute(api):
    """PRD 3.6: "A minute is classified **paused** when it lies inside one of the
    ticket's customer-wait segments."
    PRD 3.6: "When the in-force plan's `coverage_mode` is `TWENTY_FOUR_SEVEN`, every
    minute is covered: `sla_uncovered_minutes` is always 0 and the counted minutes
    are simply the elapsed minutes less the paused minutes."

    Two segments — 01:00 to 03:00 and 04:00 to 05:00 — bank 120 + 60 == 180 minutes,
    leaving 300 elapsed minutes less 180 paused, i.e. 120 counted.

    Design: Difficulty/non_linear_state_machine/ticket_pause_resume_loop_leaves_other_two_axes_pinned
    """
    world = _pause_resume_world()
    _run_two_pause_cycles(api, world)

    ticket = fetch_ticket(world["ticket"]["id"])
    assert ticket["sla_paused_minutes"] == 180
    assert ticket["sla_uncovered_minutes"] == 0
    assert ticket["sla_counted_minutes"] == 120


# ==========================================================================
# Difficulty: rung 19 pre-empts rung 27
# ==========================================================================
def _cross_household_ticket_world():
    set_clock("2026-05-01T00:00:00Z")
    plan = new_plan("PRO")
    household_a = new_household(
        name="Scope A", region_code="NWA", billing_email="sa@example.com"
    )
    owner_a = new_member(household_a["id"], "OWNER", full_name="Own A", email="owna@example.com")
    new_subscription(household_a["id"], plan["id"], allow_overage=False)

    household_b = new_household(
        name="Scope B", region_code="NWA", billing_email="sb@example.com"
    )
    owner_b = new_member(household_b["id"], "OWNER", full_name="Own B", email="ownb@example.com")
    new_subscription(household_b["id"], plan["id"], allow_overage=False)

    ticket_b = new_ticket(
        household_b["id"],
        make_owner_headers(owner_b["id"]),
        severity="P3",
        summary="Sensor battery low",
        opened_by_member_id=owner_b["id"],
    )
    return {"ticket_b": ticket_b, "headers_a": make_owner_headers(owner_a["id"])}


def test_row_scope_denial_is_reported_before_the_workflow_state_error(api):
    """PRD 2.9 rung 19: "Row scope, as defined in §2.1 — otherwise
    `ERR_ROW_SCOPE_DENIED`. Applies to every endpoint whose authorised roles include
    an entity-backed role and whose target row is household-scoped or
    technician-scoped."
    PRD 2.9: "Rungs are evaluated strictly in ascending priority order; **the first
    rung that fails is the error reported, and no later rung is evaluated**."

    The reply also violates the from-state rule at rung 27 — a NEW ticket has a null
    `pause_started_at` — but rung 19 sits above it.

    Design: Difficulty/priority_pair_validation_conflict/row_scope_denial_preempts_invalid_state_on_customer_reply
    """
    world = _cross_household_ticket_world()

    response = api.customer_reply(
        world["ticket_b"]["id"], {"message": "Not my household."}, world["headers_a"]
    )
    error = validate_error(response, ApiErrorId.ERR_ROW_SCOPE_DENIED.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value


def test_row_scope_denied_reply_writes_nothing_to_the_target_ticket(api):
    """PRD 2.1: "A listed entity-backed role that addresses a row outside its scope —
    an `Owner` touching another household's device, a `Technician` completing a visit
    booked into another technician's slot — is rejected with `ERR_ROW_SCOPE_DENIED`
    (HTTP 403)."
    PRD 2.4: "a `version` integer that begins at 1 when the row is created and
    increases by exactly 1 each time the row is mutated."

    Design: Difficulty/priority_pair_validation_conflict/row_scope_denial_preempts_invalid_state_on_customer_reply
    """
    world = _cross_household_ticket_world()
    before = fetch_ticket(world["ticket_b"]["id"])

    api.customer_reply(
        world["ticket_b"]["id"], {"message": "Not my household."}, world["headers_a"]
    )

    after = fetch_ticket(world["ticket_b"]["id"])
    assert after["workflow_status"] == "NEW"
    assert after["version"] == before["version"]
