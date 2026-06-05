"""SLA due-date arithmetic: provisional vs final variants, the three-input
non-linear effective resolve window, and the inclusive resolve boundary.

Difficulty queue A: dual_variant_calc, combinatorial_formula (window),
boundary_precision_check (resolve), compensating_invariant (hold/resume budget).
"""
from test_helpers import (
    api_client,
    validate_success,
    fixtures as fx,
    test_users as U,
    factories as F,
)


# ===========================================================================
# dual_variant_calc / sla_due_dates_provisional_vs_final_on_ticket
# ===========================================================================
def test_reprioritize_to_p1_rederives_resolve_window_on_original_open():
    """PRD §3.3: "both windows are re-derived from the new priority's multiplier
    but the window is still anchored on the original opened_at — the platform
    never re-anchors to "now" — and the already-accumulated paused_total_minutes
    are added back into the recomputed resolve_due_at."
    PRD §3.2: "multiplies the policy's resolve_target_minutes by the same
    multiplier and rounds that product up as well ... then sets ... resolve_due_at
    to opened_at plus the rounded resolve window."

    Design: Difficulty/dual_variant_calc/sla_due_dates_provisional_vs_final_on_ticket
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, category = fx.setup_catalog(default_priority="P3")
    ticket = fx.open_ticket(category["id"], requester_id="req-1")

    updated = validate_success(
        api_client.reprioritize_ticket(ticket["id"], {"priority": "P1"}, U.agent("agent-1"))
    )

    assert updated["priority"] == "P1"
    # ceil(240 * 0.25) = 60 minutes from the original opened_at (00:00).
    assert updated["resolve_due_at"] == "2026-06-01T01:00:00.000Z", \
        f"final-variant resolve_due_at should be opened+60, got {updated['resolve_due_at']}"
    assert updated["opened_at"] == "2026-06-01T00:00:00.000Z", \
        "opened_at must not be re-anchored by the final variant"


def test_open_ticket_provisional_resolve_window_from_open_priority():
    """PRD §3.2: "multiplies the policy's resolve_target_minutes by the same
    multiplier and rounds that product up as well, then sets response_due_at to
    opened_at plus the rounded response window and resolve_due_at to opened_at
    plus the rounded resolve window. At open the ticket's paused_total_minutes is
    zero, so no paused credit enters the resolve window yet."

    Design: Difficulty/dual_variant_calc/sla_due_dates_provisional_vs_final_on_ticket
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, category = fx.setup_catalog(default_priority="P3")
    ticket = fx.open_ticket(category["id"], requester_id="req-1")

    # P3 multiplier 1.0: ceil(240 * 1.0) = 240 -> opened+240 = 04:00.
    assert ticket["priority"] == "P3"
    assert ticket["paused_total_minutes"] == 0
    assert ticket["resolve_due_at"] == "2026-06-01T04:00:00.000Z", \
        f"provisional resolve_due_at should be opened+240, got {ticket['resolve_due_at']}"


# ===========================================================================
# combinatorial_formula / sla_effective_resolve_window_three_input_nonlinear
# ===========================================================================
def test_effective_resolve_window_combines_pause_and_reopen_after_ceil():
    """PRD §3.4: "Start from the policy's resolve_target_minutes, multiply by the
    ticket's priority multiplier, and round that product up to a whole minute. To
    that ceiling, add the ticket's accumulated paused_total_minutes, and then add
    the reopen penalty, which is sixty minutes for each time the ticket has been
    reopened. The two additions happen after the ceiling, never before it, and
    resolve_due_at is opened_at plus this effective figure."

    Design: Difficulty/combinatorial_formula/sla_effective_resolve_window_three_input_nonlinear
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, category = fx.setup_catalog(default_priority="P2")
    ticket = fx.open_ticket(category["id"], requester_id="req-3")
    tid = ticket["id"]

    fx.assign_and_start(tid, agent_id="agent-3")
    validate_success(api_client.hold_ticket(tid, U.agent("agent-3")))
    fx.advance_clock(90)
    validate_success(api_client.resume_ticket(tid, U.agent("agent-3")))
    validate_success(api_client.resolve_ticket(tid, U.agent("agent-3")))

    reopened = validate_success(api_client.reopen_ticket(tid, U.requester("req-3")))

    assert reopened["paused_total_minutes"] == 90
    assert reopened["reopen_count"] == 1
    # ceil(240 * 0.5) = 120; + 90 paused + 60 penalty = 270 -> opened+270 = 04:30.
    assert reopened["resolve_due_at"] == "2026-06-01T04:30:00.000Z", \
        f"expected opened+270 (120+90+60), got {reopened['resolve_due_at']}"


def test_effective_resolve_window_p2_ceiling_before_additions():
    """PRD §3.4: "The two additions happen after the ceiling, never before it,
    and resolve_due_at is opened_at plus this effective figure. The ordering is
    pinned: the multiplied base is ceiled first, then the integer minutes are
    added."

    Design: Difficulty/combinatorial_formula/sla_effective_resolve_window_three_input_nonlinear
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, category = fx.setup_catalog(default_priority="P2")
    ticket = fx.open_ticket(category["id"], requester_id="req-3b")

    # With no pause and no reopen yet, ceil(240*0.5)=120 -> opened+120 = 02:00.
    assert ticket["priority"] == "P2"
    assert ticket["paused_total_minutes"] == 0
    assert ticket["reopen_count"] == 0
    assert ticket["resolve_due_at"] == "2026-06-01T02:00:00.000Z", \
        f"P2 ceil(240*0.5)=120 -> opened+120, got {ticket['resolve_due_at']}"


# ===========================================================================
# boundary_precision_check / resolve_sla_inclusive_due_instant_is_met
# ===========================================================================
def test_resolve_exactly_at_due_instant_is_met():
    """PRD §3.6: "if the current clock is at or before resolve_due_at the
    sla_state becomes MET, and if it is strictly past it the sla_state becomes
    RESOLVE_BREACHED."
    PRD §2.8: "Time boundaries throughout the platform are inclusive of the due
    instant: a ticket whose work completes exactly at its due minute is on time,
    not late."

    Design: Difficulty/boundary_precision_check/resolve_sla_inclusive_due_instant_is_met
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_in_progress_ticket(default_priority="P3",
                                                  requester_id="req-9", agent_id="agent-9")
    # resolve_due = opened+240 (P3 base 240, mult 1.0). Advance to exactly +240.
    fx.advance_clock(240)
    resolved = validate_success(api_client.resolve_ticket(ticket["id"], U.agent("agent-9")))

    assert resolved["lifecycle_state"] == "RESOLVED"
    assert resolved["sla_state"] == "MET", \
        "resolving exactly at the inclusive due instant must be MET, not breached"


def test_resolve_one_minute_before_due_is_met():
    """PRD §3.6: "if the current clock is at or before resolve_due_at the
    sla_state becomes MET, and if it is strictly past it the sla_state becomes
    RESOLVE_BREACHED."

    Design: Difficulty/boundary_precision_check/resolve_sla_inclusive_due_instant_is_met
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_in_progress_ticket(default_priority="P3",
                                                  requester_id="req-9b", agent_id="agent-9b")
    fx.advance_clock(239)
    resolved = validate_success(api_client.resolve_ticket(ticket["id"], U.agent("agent-9b")))

    assert resolved["lifecycle_state"] == "RESOLVED"
    assert resolved["sla_state"] == "MET"


# ===========================================================================
# compensating_invariant / hold_resume_conserves_total_sla_budget_minutes
# ===========================================================================
def test_hold_then_resume_conserves_working_resolve_budget():
    """PRD §3.4: "Resuming a held ticket moves it from ON_HOLD back to
    IN_PROGRESS: the platform measures the elapsed paused interval as the whole
    number of minutes between pause_started_at and the current clock, adds that
    delta to the ticket's paused_total_minutes, pushes resolve_due_at out by the
    same delta, and sets sla_state back to RUNNING."

    Design: Difficulty/compensating_invariant/hold_resume_conserves_total_sla_budget_minutes
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_in_progress_ticket(default_priority="P3",
                                                  requester_id="req-14", agent_id="agent-14")
    tid = ticket["id"]

    fx.advance_clock(30)
    validate_success(api_client.hold_ticket(tid, U.agent("agent-14")))
    fx.advance_clock(45)
    resumed = validate_success(api_client.resume_ticket(tid, U.agent("agent-14")))

    assert resumed["paused_total_minutes"] == 45
    # opened+240 base, pushed out by 45 paused -> opened+285 = 04:45.
    assert resumed["resolve_due_at"] == "2026-06-01T04:45:00.000Z", \
        f"expected opened+285 (240+45), got {resumed['resolve_due_at']}"


def test_hold_resume_paused_credit_equals_elapsed_minutes():
    """PRD §3.4: "the platform measures the elapsed paused interval as the whole
    number of minutes between pause_started_at and the current clock, adds that
    delta to the ticket's paused_total_minutes, pushes resolve_due_at out by the
    same delta, and sets sla_state back to RUNNING."

    Design: Difficulty/compensating_invariant/hold_resume_conserves_total_sla_budget_minutes
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_in_progress_ticket(default_priority="P3",
                                                  requester_id="req-14b", agent_id="agent-14b")
    tid = ticket["id"]

    fx.advance_clock(30)
    validate_success(api_client.hold_ticket(tid, U.agent("agent-14b")))
    fx.advance_clock(45)
    resumed = validate_success(api_client.resume_ticket(tid, U.agent("agent-14b")))

    assert resumed["sla_state"] == "RUNNING"
    # Working budget conserved: resolve_due_at - opened_at - paused_total == 240.
    assert resumed["paused_total_minutes"] == 45
    assert resumed["resolve_due_at"] == "2026-06-01T04:45:00.000Z"
