"""Barista assignment lifecycle: accept, decline, withdraw, the weekly-hour
ledger, and the amendment-driven re-offer loop.

Queue A (Difficulty): cross_entity_state_dependency, non_linear_state_machine,
compensating_invariant.
Queue B (Corner): state_machines.
"""
from test_helpers import (
    api_client,
    fixtures as fx,
    validate_success, validate_error,
    assert_assignment,
    ApiErrorId, NON_EXISTENT_UUID,
)

ERR = ApiErrorId


def _committed_hours(ctx):
    barista = validate_success(api_client.get_barista(ctx["barista"]["id"], fx.OPS), 200)
    return barista["committed_hours_this_week"]


# ─── cross_entity_state_dependency / assignment_accept_requires_barista_active ───

def test_accept_offered_assignment_moves_to_accepted(api):
    """PRD §3.4: "Accepting moves it from `OFFERED` to `ACCEPTED`, and three
    conditions must hold: the assignment is still `OFFERED`, the barista's own
    `status` is `ACTIVE`, and the parent booking is in `QUOTE`, `PENDING_DEPOSIT`,
    or `CONFIRMED`."

    With the barista ACTIVE and the booking in QUOTE, the offer accepts cleanly.

    Design: Difficulty/cross_entity_state_dependency/assignment_accept_requires_barista_active
    """
    ctx = fx.setup_quote_with_assignment(
        package_kind="FLAT",
        booking_overrides={"event_start": fx.IN_WEEK_EVENT_START,
                           "event_end": fx.IN_WEEK_EVENT_END})
    res = api_client.accept_assignment(ctx["assignment"]["id"], ctx["barista_headers"])
    accepted = validate_success(res, 200)
    assert_assignment(accepted)
    assert accepted["status"] == "ACCEPTED", accepted


def test_accept_commits_duration_hours_to_weekly_tally(api):
    """PRD §3.4: "A successful accept adds the `duration_hours` to the barista's
    `committed_hours_this_week` and increments both the barista's `version` and
    the assignment's `version`."
    PRD §3.2: "The new BaristaAssignment starts in `OFFERED` status, carries the
    booking's `booking_id`, and exposes a read-only `duration_hours`: the length
    of the booking's service window measured in hours, with any partial hour
    rounded up to the next whole hour."

    Accepting a two-hour event's offer raises the barista's weekly tally from 0
    to 2. The event is booked inside the clock's ISO week so the tally — which
    only counts assignments whose event_start falls inside the current ISO week
    (PRD §3.1) — reflects the commitment immediately.

    Design: Difficulty/cross_entity_state_dependency/assignment_accept_requires_barista_active
    """
    ctx = fx.setup_quote_with_assignment(
        package_kind="FLAT",
        booking_overrides={"event_start": fx.IN_WEEK_EVENT_START,
                           "event_end": fx.IN_WEEK_EVENT_END})
    assert ctx["assignment"]["duration_hours"] == 2, ctx["assignment"]
    assert _committed_hours(ctx) == 0

    validate_success(
        api_client.accept_assignment(ctx["assignment"]["id"], ctx["barista_headers"]), 200)
    assert _committed_hours(ctx) == 2


def test_offer_to_unknown_barista_rejected_not_found(api):
    """PRD §2.8: "The same 404 rejection applies to foreign keys supplied in a request
    body — `client_id`, `package_id`, `cart_id`, `travel_zone_id`, `addon_id`,
    `barista_id`, or `item_id` — that do not resolve to existing entities."

    Offering a booking to a non-existent barista id is rejected with
    ERR_RESOURCE_NOT_FOUND.

    Design: Difficulty/cross_entity_state_dependency/assignment_accept_requires_barista_active
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    booking = fx.create_quote_booking(ctx)
    res = api_client.offer_assignment(
        booking["id"], {"barista_id": NON_EXISTENT_UUID, "is_primary": True}, fx.OPS)
    validate_error(res, ERR.ERR_RESOURCE_NOT_FOUND, expected_status=404)


# ─── non_linear_state_machine / assignment_reoffer_loop_confirmed_offered_accepted ───

def _confirmed_in_week_booking():
    """CONFIRMED booking with a CONFIRMED assignment on an in-week event more than
    48h ahead of the clock (so the amendment window is still open)."""
    return fx.setup_confirmed_booking(
        package_kind="FLAT", accept=True,
        booking_overrides={"event_start": fx.IN_WEEK_LATE_EVENT_START,
                           "event_end": fx.IN_WEEK_LATE_EVENT_END})


def test_amend_returns_confirmed_assignment_to_offered(api):
    """PRD §3.4: "When a confirmed booking is amended, each `CONFIRMED` assignment
    returns to `OFFERED` — a re-offer loop that notifies the barista — subtracting
    its hours for now, to be re-added if the barista re-accepts."

    Amending a CONFIRMED booking loops its assignment CONFIRMED -> OFFERED and
    releases the barista's committed hours (2 -> 0).

    Design: Difficulty/non_linear_state_machine/assignment_reoffer_loop_confirmed_offered_accepted
    """
    ctx = _confirmed_in_week_booking()
    asg = validate_success(
        api_client.get_assignment(ctx["assignment"]["id"], fx.OPS), 200)
    assert asg["status"] == "CONFIRMED", asg
    assert _committed_hours(ctx) == 2

    amended = validate_success(
        api_client.amend_booking(ctx["booking"]["id"], {"guest_count": 50},
                                 ctx["client_headers"]), 200)
    assert amended["status"] == "QUOTE", amended

    asg_mid = validate_success(
        api_client.get_assignment(ctx["assignment"]["id"], fx.OPS), 200)
    assert asg_mid["status"] == "OFFERED", asg_mid
    assert _committed_hours(ctx) == 0


def test_reaccept_after_reoffer_recommits_hours(api):
    """PRD §3.4: "When a confirmed booking is amended, each `CONFIRMED` assignment
    returns to `OFFERED` — a re-offer loop that notifies the barista — subtracting
    its hours for now, to be re-added if the barista re-accepts."
    PRD §3.4: "Accepting moves it from `OFFERED` to `ACCEPTED`, and three
    conditions must hold: the assignment is still `OFFERED`, the barista's own
    `status` is `ACTIVE`, and the parent booking is in `QUOTE`, `PENDING_DEPOSIT`,
    or `CONFIRMED`."

    After the amendment re-offer, the barista re-accepts (OFFERED -> ACCEPTED on a
    QUOTE booking) and the weekly tally climbs back to 2.

    Design: Difficulty/non_linear_state_machine/assignment_reoffer_loop_confirmed_offered_accepted
    """
    ctx = _confirmed_in_week_booking()
    validate_success(
        api_client.amend_booking(ctx["booking"]["id"], {"guest_count": 50},
                                 ctx["client_headers"]), 200)
    asg_mid = validate_success(
        api_client.get_assignment(ctx["assignment"]["id"], fx.OPS), 200)
    assert asg_mid["status"] == "OFFERED", asg_mid
    assert _committed_hours(ctx) == 0

    reaccepted = validate_success(
        api_client.accept_assignment(ctx["assignment"]["id"], ctx["barista_headers"]), 200)
    assert reaccepted["status"] == "ACCEPTED", reaccepted
    assert _committed_hours(ctx) == 2


# ─── compensating_invariant / barista_weekly_hours_conserved_across_accept_withdraw ───

def test_accept_then_withdraw_conserves_weekly_hours(api):
    """PRD §3.4: "A successful accept adds the `duration_hours` to the barista's
    `committed_hours_this_week` and increments both the barista's `version` and
    the assignment's `version`."
    PRD §3.4: "an `ACCEPTED` assignment may be withdrawn to `CANCELLED` provided the
    parent booking has not yet reached `IN_PROGRESS` — there is no walking off
    mid-event — and the withdrawal subtracts the `duration_hours` from the
    barista's weekly commitment and increments the barista's `version`."

    The forward accept (+2 hours) and the compensating withdraw (-2 hours) leave
    the weekly tally exactly where it started.

    Design: Difficulty/compensating_invariant/barista_weekly_hours_conserved_across_accept_withdraw
    """
    ctx = fx.setup_quote_with_assignment(
        package_kind="FLAT",
        booking_overrides={"event_start": fx.IN_WEEK_EVENT_START,
                           "event_end": fx.IN_WEEK_EVENT_END})
    assert _committed_hours(ctx) == 0

    validate_success(
        api_client.accept_assignment(ctx["assignment"]["id"], ctx["barista_headers"]), 200)
    assert _committed_hours(ctx) == 2

    validate_success(
        api_client.withdraw_assignment(ctx["assignment"]["id"], ctx["barista_headers"]), 200)
    assert _committed_hours(ctx) == 0


def test_withdraw_moves_assignment_to_cancelled(api):
    """PRD §3.4: "an `ACCEPTED` assignment may be withdrawn to `CANCELLED` provided the
    parent booking has not yet reached `IN_PROGRESS` — there is no walking off
    mid-event — and the withdrawal subtracts the `duration_hours` from the
    barista's weekly commitment and increments the barista's `version`."

    Withdrawing an ACCEPTED assignment on a QUOTE booking lands it in CANCELLED.

    Design: Difficulty/compensating_invariant/barista_weekly_hours_conserved_across_accept_withdraw
    """
    ctx = fx.setup_quote_with_assignment(
        package_kind="FLAT", accept=True,
        booking_overrides={"event_start": fx.IN_WEEK_EVENT_START,
                           "event_end": fx.IN_WEEK_EVENT_END})
    withdrawn = validate_success(
        api_client.withdraw_assignment(ctx["assignment"]["id"], ctx["barista_headers"]), 200)
    assert withdrawn["status"] == "CANCELLED", withdrawn


# ─── Corner/state_machines: assignment decline is terminal ────────────────

def test_accept_after_decline_rejected(api):
    """PRD §3.4: "Accepting moves it from `OFFERED` to `ACCEPTED`, and three
    conditions must hold: the assignment is still `OFFERED`, the barista's own
    `status` is `ACTIVE`, and the parent booking is in `QUOTE`, `PENDING_DEPOSIT`,
    or `CONFIRMED`."
    PRD §2.10: "State-level checks come fifth: whether the target entity's status
    permits the requested transition (`ERR_INVALID_STATE`, HTTP 409) and whether
    referenced catalog entities are `ACTIVE` (the per-entity codes of §2.9)."

    A DECLINED assignment is no longer OFFERED, so accepting it is rejected.

    Design: Corner/state_machines/assignment_decline_terminal_no_reaccept
    """
    ctx = fx.setup_quote_with_assignment(package_kind="FLAT")
    declined = validate_success(
        api_client.decline_assignment(ctx["assignment"]["id"],
                                      {"decline_reason": "conflict"},
                                      ctx["barista_headers"]), 200)
    assert declined["status"] == "DECLINED", declined

    res = api_client.accept_assignment(ctx["assignment"]["id"], ctx["barista_headers"])
    validate_error(res, ERR.ERR_INVALID_STATE, expected_status=409)
