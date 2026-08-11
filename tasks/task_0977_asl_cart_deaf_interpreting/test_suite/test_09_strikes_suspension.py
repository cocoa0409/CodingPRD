"""No-show strikes: the rolling 365-day count, the three-strike auto-suspension,
the depth-4 cascade, and the compensating rescind (which never reinstates)."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_org,
    create_standard_rate_card,
    create_active_interpreter,
    add_availability,
    create_submitted_request,
    offer_to,
    accept_assignment,
    confirm_assignment,
    get_assignment,
    get_request,
    get_interpreter,
    create_manual_strike,
    create_interpreter_payload,
    setup_confirmed_assignment,
    drive_to_checkout,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_interpreter_with_two_strikes_and_two_confirmed():
    """Interpreter i1 carries 2 ACTIVE manual strikes (2026-03-01/02, inside the
    rolling window); A3 CONFIRMED for 2026-06-12T14:00-15:00; A4 CONFIRMED for
    2026-06-20T14:00-15:00 (no buffer overlap); clock parked past the grace."""
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card()
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    create_manual_strike(interp["id"], "2026-03-01T09:00:00Z")
    create_manual_strike(interp["id"], "2026-03-02T09:00:00Z")

    def _confirmed(start_date):
        req = create_submitted_request(
            org["id"], scheduled_start=f"{start_date}T14:00:00Z",
            scheduled_end=f"{start_date}T15:00:00Z", estimated_mileage=5)
        asg = offer_to(req["id"], interp["id"])
        accept_assignment(asg)
        confirm_assignment(asg)
        return req, asg

    req3, asg3 = _confirmed("2026-06-12")
    req4, asg4 = _confirmed("2026-06-20")
    set_clock("2026-06-12T14:16:00Z")  # 16 minutes past A3's start (grace 15)
    return {"org": org, "interpreter": interp,
            "req3": req3, "asg3": asg3, "req4": req4, "asg4": asg4}


# ─── Difficulty: transitive_cascade / no-show depth-4 chain ──────────

def test_no_show_creates_strike_and_auto_suspends_at_three():
    """PRD §3.6: "Marking stamps `no_show_marked_at`, moves the assignment to
    `NO_SHOW`, and fires a four-link cascade. Link one: a strike is created for the
    interpreter with `occurred_at` set to the assignment's scheduled start and status
    `ACTIVE`. Link two: the interpreter's `active_strike_count` is recomputed as the
    number of their `ACTIVE` strikes whose `occurred_at` falls on or after the
    logical time minus 365 days — the window edge is inclusive, so a strike exactly
    365 days old still counts. Link three: when that count reaches three or more and
    the interpreter is `ACTIVE`, the interpreter is auto-suspended per §3.2."

    Design: Difficulty/transitive_cascade/no_show_strike_suspension_cancels_future_assignments
    """
    ctx = _setup_interpreter_with_two_strikes_and_two_confirmed()
    marked = get_success_data(api_client.mark_no_show(ctx["asg3"]["id"], ADMIN))
    assert marked["status"] == "NO_SHOW"
    interp = get_interpreter(ctx["interpreter"]["id"])
    assert interp["active_strike_count"] == 3, (
        "the new strike (occurred_at = scheduled start) joins the two manual ones"
    )
    assert interp["status"] == "SUSPENDED"


def test_suspension_cascade_cancels_other_assignment_and_rematches():
    """PRD §3.6: "Link four: the suspension cascade cancels the interpreter's other
    non-terminal assignments and re-matches their requests, while the no-showed
    request itself returns to `MATCHING` if attempts remain, else falls to
    `UNFILLED`."
    PRD §3.6: "system-driven cancellations (the supersede of §3.4 and the suspension
    cascade of §3.2) take the last" of the `cancelled_by` values — `SYSTEM`.

    Design: Difficulty/transitive_cascade/no_show_strike_suspension_cancels_future_assignments
    """
    ctx = _setup_interpreter_with_two_strikes_and_two_confirmed()
    get_success_data(api_client.mark_no_show(ctx["asg3"]["id"], ADMIN))
    asg4 = get_assignment(ctx["asg4"]["id"])
    assert asg4["status"] == "CANCELLED", "unrelated CONFIRMED assignment cascades"
    assert asg4["cancelled_by"] == "SYSTEM"
    req4 = get_request(ctx["req4"]["id"])
    assert req4["status"] == "MATCHING", (
        f"re-match with offer_attempt_count 1 < 3, got {req4['status']}"
    )


# ─── Difficulty: boundary_precision_check / strike threshold ─────────

def test_two_active_strikes_leave_interpreter_active():
    """PRD §3.6: "Link three: when that count reaches three or more and the
    interpreter is `ACTIVE`, the interpreter is auto-suspended per §3.2." (At
    exactly 2 rolling active strikes the threshold is not yet reached.)

    Design: Difficulty/boundary_precision_check/strike_threshold_third_active_strike_suspends
    """
    ctx = _setup_interpreter_with_two_strikes_and_two_confirmed()
    interp = get_interpreter(ctx["interpreter"]["id"])
    assert interp["active_strike_count"] == 2
    assert interp["status"] == "ACTIVE", "2 < 3: below the suspension threshold"


def test_third_active_strike_suspends():
    """PRD §3.6: "Link three: when that count reaches three or more and the
    interpreter is `ACTIVE`, the interpreter is auto-suspended per §3.2." and
    "Marking stamps `no_show_marked_at`, moves the assignment to `NO_SHOW`".
    (The mark-no-show creates the third rolling strike; the >= boundary is
    inclusive.)

    Design: Difficulty/boundary_precision_check/strike_threshold_third_active_strike_suspends
    """
    ctx = _setup_interpreter_with_two_strikes_and_two_confirmed()
    marked = get_success_data(api_client.mark_no_show(ctx["asg3"]["id"], ADMIN))
    assert marked["status"] == "NO_SHOW"
    interp = get_interpreter(ctx["interpreter"]["id"])
    assert interp["active_strike_count"] == 3
    assert interp["status"] == "SUSPENDED"


# ─── Difficulty: compensating_invariant / strike create then rescind ──

def _setup_no_show_then_get_strike():
    ctx = _setup_interpreter_with_two_strikes_and_two_confirmed()
    get_success_data(api_client.mark_no_show(ctx["asg3"]["id"], ADMIN))
    rows = get_success_data(api_client.list_assignment_strikes(ctx["asg3"]["id"], ADMIN))
    assert len(rows) == 1
    return ctx, rows[0]


def test_strike_rescind_restores_count_but_not_status():
    """PRD §3.6: "A strike may later be rescinded — moving it from `ACTIVE` to
    `RESCINDED` and stamping `rescinded_at` — which recomputes the rolling count
    downward when the strike was inside the window" and "Rescinding never reinstates
    by itself: a suspended interpreter stays `SUSPENDED` until the explicit
    reinstatement of §3.2." (The conserved quantity is the COUNT: 2 -> 3 -> 2; the
    status is a separate manual transition.)

    Design: Difficulty/compensating_invariant/strike_create_then_rescind_restores_active_count
    """
    ctx, strike3 = _setup_no_show_then_get_strike()
    interp = get_interpreter(ctx["interpreter"]["id"])
    assert interp["active_strike_count"] == 3 and interp["status"] == "SUSPENDED"
    get_success_data(api_client.rescind_strike(strike3["id"], ADMIN))
    interp = get_interpreter(ctx["interpreter"]["id"])
    assert interp["active_strike_count"] == 2, "rescind restores the conserved count"
    active_rows = get_success_data(api_client.list_interpreter_strikes(
        ctx["interpreter"]["id"], ADMIN, params={"status": "ACTIVE"}))
    assert len(active_rows) == 2
    assert interp["status"] == "SUSPENDED", "no automatic reinstatement"


def test_manual_reinstate_after_rescind_passes_gate():
    """PRD §3.2: "Reinstatement returns a suspended interpreter to `ACTIVE` only
    while their `active_strike_count` is below three; otherwise the attempt is
    rejected with `ERR_ACTIVE_STRIKES_AT_LIMIT`." (After the rescind the count is 2,
    so the explicit reinstatement succeeds.)

    Design: Difficulty/compensating_invariant/strike_create_then_rescind_restores_active_count
    """
    ctx, strike3 = _setup_no_show_then_get_strike()
    get_success_data(api_client.rescind_strike(strike3["id"], ADMIN))
    reinstated = get_success_data(api_client.reinstate_interpreter(
        ctx["interpreter"]["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"


# ─── Corner: conditional cascade, 365-day window edge, reinstate gate ──

def test_suspension_cascade_only_cancels_non_terminal_assignments():
    """PRD §3.2: "Either way, the cascade is identical — every assignment the
    interpreter holds in `OFFERED`, `ACCEPTED`, or `CONFIRMED` status is cancelled
    by the system with no fee, and each affected request returns to `MATCHING` if it
    still has offer attempts remaining, or falls to `UNFILLED` once attempts are
    exhausted." (A COMPLETED assignment is terminal for this cascade and untouched.)

    Design: Corner/state_machines/suspension_cascade_only_cancels_non_terminal_assignments
    """
    # A1: completed encounter (June 10). A2: CONFIRMED for June 20.
    ctx = setup_confirmed_assignment()
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 90, "mileage_claimed": 12})
    assert ctx["assignment"]["status"] == "COMPLETED"
    req2 = create_submitted_request(
        ctx["org"]["id"], scheduled_start="2026-06-20T14:00:00Z",
        scheduled_end="2026-06-20T15:00:00Z", estimated_mileage=5)
    asg2 = offer_to(req2["id"], ctx["interpreter"]["id"])
    accept_assignment(asg2)
    confirm_assignment(asg2)

    get_success_data(api_client.suspend_interpreter(ctx["interpreter"]["id"], ADMIN))
    a1_after = get_assignment(ctx["assignment"]["id"])
    assert a1_after["status"] == "COMPLETED", "terminal assignments are untouched"
    a2_after = get_assignment(asg2["id"])
    assert a2_after["status"] == "CANCELLED"
    assert a2_after["cancelled_by"] == "SYSTEM"
    assert get_request(req2["id"])["status"] == "MATCHING"


def test_strike_window_includes_exactly_365_day_old_strike():
    """PRD §3.6: "the interpreter's `active_strike_count` is recomputed as the
    number of their `ACTIVE` strikes whose `occurred_at` falls on or after the
    logical time minus 365 days — the window edge is inclusive, so a strike exactly
    365 days old still counts."
    (At 2026-06-12T14:16:00Z a strike at exactly 2025-06-12T14:16:00Z counts; one at
    14:15:59Z is one second too old and does not.)

    Design: Corner/calculations/strike_window_includes_exactly_365_day_old_strike
    """
    set_clock("2026-06-12T14:16:00Z")
    interp = get_success_data(api_client.create_interpreter(
        create_interpreter_payload(), ADMIN))
    create_manual_strike(interp["id"], "2025-06-12T14:16:00Z")  # exactly now - 365d
    create_manual_strike(interp["id"], "2025-06-12T14:15:59Z")  # one second older
    create_manual_strike(interp["id"], "2026-03-01T09:00:00Z")  # comfortably inside
    data = get_interpreter(interp["id"])
    assert data["active_strike_count"] == 2, (
        f"boundary strike included, one-second-older excluded: got {data['active_strike_count']}"
    )
    assert data["status"] == "PENDING_ONBOARD", "count 2 < 3: no suspension"


def test_reinstate_with_three_strikes_returns_active_strikes_at_limit():
    """PRD §3.2: "Reinstatement returns a suspended interpreter to `ACTIVE` only
    while their `active_strike_count` is below three; otherwise the attempt is
    rejected with `ERR_ACTIVE_STRIKES_AT_LIMIT`."
    PRD §3.2: "the system auto-suspends the moment the rolling strike count reaches
    three (§3.6)".

    Design: Corner/errors/reinstate_with_three_strikes_returns_active_strikes_at_limit
    """
    set_clock("2026-05-01T00:00:00Z")
    interp = create_active_interpreter()
    create_manual_strike(interp["id"], "2026-03-01T09:00:00Z")
    create_manual_strike(interp["id"], "2026-03-02T09:00:00Z")
    create_manual_strike(interp["id"], "2026-03-03T09:00:00Z")
    assert get_interpreter(interp["id"])["status"] == "SUSPENDED", (
        "the third rolling strike auto-suspends"
    )
    resp = api_client.reinstate_interpreter(interp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_STRIKES_AT_LIMIT)
    assert get_interpreter(interp["id"])["status"] == "SUSPENDED"
