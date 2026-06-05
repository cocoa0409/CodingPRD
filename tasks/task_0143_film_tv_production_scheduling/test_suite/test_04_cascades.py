"""Cascading side-effects and conserved-quantity invariants:
mark-paid settlement, day-cancel fan-out, and book/schedule-then-cancel
conservation."""
from test_helpers import validate_success, fixtures
from test_helpers.fixtures import LP, AD, PC


# --------------------------------------------------------------------------- #
# Difficulty/transitive_cascade/markpaid_cascades_production_then_budget_lines
# --------------------------------------------------------------------------- #
def _setup_paid_ready(api, fringe_estimate=100_000):
    """ACTIVE production, BELOW_THE_LINE_LABOR line 500000 + FRINGES line, SAG
    crew wrapped at 13.0h/1 meal then approved. Returns dict with ids."""
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    btl = fixtures.create_budget_line(prod["id"], category="BELOW_THE_LINE_LABOR",
                                      estimated_cents=500_000)
    fr = fixtures.create_budget_line(prod["id"], category="FRINGES",
                                     estimated_cents=fringe_estimate)
    fixtures.create_union_fringe(prod["id"], union_code="SAG_AFTRA",
                                 fringe_rate_bps=1800, pension_health_flat_cents=15_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=200_000,
                                is_sag_aftra=True, union_code="SAG_AFTRA")
    fixtures.advance_production(prod["id"])
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-07-15", day_number=1)
    fixtures.advance_production(prod["id"])
    asg = fixtures.book_assignment(day["id"], crew["id"], day["version"],
                                   call_time="2026-07-15T06:00:00.000Z")
    cs = fixtures.create_call_sheet(day["id"], general_call_time="2026-07-15T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))
    validate_success(api.start_shooting_day(day["id"], AD))
    validate_success(api.check_in_assignment(asg["id"], AD))
    validate_success(api.check_out_assignment(
        asg["id"], {"wrap_time": "2026-07-15T19:00:00.000Z", "meal_breaks_taken": 1}, AD))
    validate_success(api.approve_pay_assignment(asg["id"], PC))
    return {"prod": prod, "btl": btl, "fr": fr, "asg": asg}


def test_mark_paid_increases_production_actual_cost(api):
    """PRD 3.5: "Marking paid settles the money: the production's actual_cost_cents
    is increased by the assignment's paid_cost_cents".

    paid_cost 278500 => Production.actual_cost_cents == 278500.

    Design: Difficulty/transitive_cascade/markpaid_cascades_production_then_budget_lines
    """
    s = _setup_paid_ready(api)
    validate_success(api.mark_paid_assignment(s["asg"]["id"], PC))
    prod = validate_success(api.get_production(s["prod"]["id"], LP))
    assert prod["actual_cost_cents"] == 278500, \
        f"expected actual_cost 278500, got {prod['actual_cost_cents']}"


def test_mark_paid_flows_labor_and_fringe_to_budget_lines(api):
    """PRD 3.5: "the production's BELOW_THE_LINE_LABOR budget line has its
    actual_cents increased by the paid_cost_cents less the fringe_cents (the labor
    portion), with that line's variance_cents recomputed; and the production's
    FRINGES budget line has its actual_cents increased by the fringe_cents, with
    its variance_cents recomputed."

    paid 278500, fringe 51000 => labor 227500 (variance 272500), fringe 51000
    (variance 49000).

    Design: Difficulty/transitive_cascade/markpaid_cascades_production_then_budget_lines
    """
    s = _setup_paid_ready(api)
    validate_success(api.mark_paid_assignment(s["asg"]["id"], PC))
    btl = validate_success(api.get_budget_line(s["btl"]["id"], LP))
    fr = validate_success(api.get_budget_line(s["fr"]["id"], LP))
    assert btl["actual_cents"] == 227500, \
        f"expected labor actual 227500, got {btl['actual_cents']}"
    assert btl["variance_cents"] == 272500, \
        f"expected labor variance 272500, got {btl['variance_cents']}"
    assert fr["actual_cents"] == 51000, \
        f"expected fringe actual 51000, got {fr['actual_cents']}"
    assert fr["variance_cents"] == 49000, \
        f"expected fringe variance 49000, got {fr['variance_cents']}"


# --------------------------------------------------------------------------- #
# Difficulty/transitive_cascade/cancel_called_day_cascades_callsheet_and_assignment
# --------------------------------------------------------------------------- #
def _setup_called_day_with_scene(api):
    """ACTIVE production, one CALLED day (published call sheet) with a SCHEDULED
    assignment and a scheduled scene. Returns dict of ids."""
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=500_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=200_000,
                                is_sag_aftra=False, union_code="NONE")
    fixtures.advance_production(prod["id"])
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-07-18", day_number=1)
    fixtures.advance_production(prod["id"])
    scene = fixtures.create_scene(prod["id"], scene_number="1A", page_eighths=8,
                                  int_ext="INT", day_night="DAY")
    fixtures.schedule_scene(scene["id"], day["id"])
    # Scheduling a scene recomputes the day's estimated_page_eighths, which is
    # itself a mutation (PRD 2.4) and bumps the day's version. Re-fetch the day
    # so the booking's expected_shooting_day_version reflects the current state.
    day = validate_success(api.get_shooting_day(day["id"], AD))
    asg = fixtures.book_assignment(day["id"], crew["id"], day["version"],
                                   call_time="2026-07-18T06:00:00.000Z")
    cs = fixtures.create_call_sheet(day["id"], general_call_time="2026-07-18T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))
    return {"prod": prod, "day": day, "scene": scene, "asg": asg, "cs": cs}


def test_cancel_called_day_cancels_callsheet_and_voids_assignment(api):
    """PRD 3.3: "when the cancelled day was already CALLED, the day's published
    call sheet is additionally transitioned from PUBLISHED to CANCELLED".
    PRD 3.3: "forces every assignment on the day whose attendance_status is
    SCHEDULED into NO_SHOW while setting that assignment's payment_status to VOID".

    Design: Difficulty/transitive_cascade/cancel_called_day_cascades_callsheet_and_assignment
    """
    s = _setup_called_day_with_scene(api)
    cancelled = validate_success(api.cancel_shooting_day(s["day"]["id"], AD))
    assert cancelled["status"] == "CANCELLED"
    cs = validate_success(api.get_call_sheet(s["cs"]["id"], AD))
    assert cs["status"] == "CANCELLED", f"expected call sheet CANCELLED, got {cs['status']}"
    asg = validate_success(api.get_assignment(s["asg"]["id"], AD))
    assert asg["attendance_status"] == "NO_SHOW"
    assert asg["payment_status"] == "VOID"


def test_cancel_called_day_unschedules_scene(api):
    """PRD 3.3: "unschedules every scene scheduled on the day by resetting each
    scene's shooting_day_id to null."

    Design: Difficulty/transitive_cascade/cancel_called_day_cascades_callsheet_and_assignment
    """
    s = _setup_called_day_with_scene(api)
    validate_success(api.cancel_shooting_day(s["day"]["id"], AD))
    scene = validate_success(api.get_scene(s["scene"]["id"], AD))
    assert scene["shooting_day_id"] is None, \
        f"expected scene shooting_day_id null, got {scene['shooting_day_id']!r}"


# --------------------------------------------------------------------------- #
# Difficulty/compensating_invariant/committed_cost_conserved_under_book_then_cancel
# --------------------------------------------------------------------------- #
def test_committed_cost_returns_to_zero_after_cancel(api):
    """PRD 3.5: "The production's committed_cost_cents is the running sum, across
    all of the production's assignments, of estimated_cost_cents for assignments
    whose payment_status is UNPAID or APPROVED plus paid_cost_cents for
    assignments whose payment_status is PAID". PRD 3.3: "forces every assignment
    on the day whose attendance_status is SCHEDULED into NO_SHOW while setting
    that assignment's payment_status to VOID".

    Booking adds estimated 251000 to committed; cancelling the day VOIDs the
    assignment, so committed_cost_cents returns to 0.

    Design: Difficulty/compensating_invariant/committed_cost_conserved_under_book_then_cancel
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000,
        call_time="2026-08-10T06:00:00.000Z", shoot_date="2026-08-10")
    asg = validate_success(api.get_assignment(ctx["assignment"]["id"], AD))
    assert asg["estimated_cost_cents"] == 251000
    cs = fixtures.create_call_sheet(ctx["day"]["id"], general_call_time="2026-08-10T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))
    validate_success(api.cancel_shooting_day(ctx["day"]["id"], AD))
    voided = validate_success(api.get_assignment(ctx["assignment"]["id"], AD))
    assert voided["payment_status"] == "VOID"
    prod = validate_success(api.get_production(ctx["prod"]["id"], LP))
    assert prod["committed_cost_cents"] == 0, \
        f"expected committed_cost 0 after cancel, got {prod['committed_cost_cents']}"


def test_committed_cost_reflects_booking_before_cancel(api):
    """PRD 3.4: "Creating it computes a forward-looking estimated_cost_cents
    (detailed in Section 3.5), recomputes the production's committed_cost_cents".

    Right after booking, committed_cost_cents equals the assignment estimate
    (251000) — the forward leg of the conserved quantity.

    Design: Difficulty/compensating_invariant/committed_cost_conserved_under_book_then_cancel
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000,
        call_time="2026-08-10T06:00:00.000Z", shoot_date="2026-08-10")
    prod = validate_success(api.get_production(ctx["prod"]["id"], LP))
    assert prod["committed_cost_cents"] == 251000, \
        f"expected committed_cost 251000 after booking, got {prod['committed_cost_cents']}"


# --------------------------------------------------------------------------- #
# Difficulty/compensating_invariant/page_eighths_conserved_under_schedule_then_cancel
# --------------------------------------------------------------------------- #
def test_page_eighths_returns_to_zero_after_cancel(api):
    """PRD 3.3: "A day also tracks an estimated_page_eighths figure, which is the
    sum of the page lengths of all scenes currently scheduled onto it".
    PRD 3.3: "unschedules every scene scheduled on the day by resetting each
    scene's shooting_day_id to null."

    Scheduling an 8-eighth scene drives the day to 8; cancel resets the scene and
    the day's estimated_page_eighths returns to 0, while the scene's own
    page_eighths stays 8.

    Design: Difficulty/compensating_invariant/page_eighths_conserved_under_schedule_then_cancel
    """
    prod, day = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-08-12", day_number=1)
    scene = fixtures.create_scene(prod["id"], scene_number="12A", page_eighths=8,
                                  int_ext="EXT", day_night="NIGHT")
    fixtures.schedule_scene(scene["id"], day["id"])
    validate_success(api.cancel_shooting_day(day["id"], AD))
    day_after = validate_success(api.get_shooting_day(day["id"], AD))
    assert day_after["estimated_page_eighths"] == 0, \
        f"expected page_eighths 0, got {day_after['estimated_page_eighths']}"
    scene_after = validate_success(api.get_scene(scene["id"], AD))
    assert scene_after["shooting_day_id"] is None
    assert scene_after["page_eighths"] == 8, \
        f"expected scene page_eighths 8, got {scene_after['page_eighths']}"


def test_scheduling_scene_raises_day_page_eighths(api):
    """PRD 3.3: "A successful scheduling sets the scene's shooting_day_id and
    recomputes the parent day's estimated_page_eighths."

    The forward leg: an 8-eighth scene scheduled onto a fresh day drives its
    estimated_page_eighths from 0 to 8.

    Design: Difficulty/compensating_invariant/page_eighths_conserved_under_schedule_then_cancel
    """
    prod, day = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-08-12", day_number=1)
    scene = fixtures.create_scene(prod["id"], scene_number="12A", page_eighths=8,
                                  int_ext="EXT", day_night="NIGHT")
    fixtures.schedule_scene(scene["id"], day["id"])
    day_after = validate_success(api.get_shooting_day(day["id"], AD))
    assert day_after["estimated_page_eighths"] == 8, \
        f"expected page_eighths 8, got {day_after['estimated_page_eighths']}"


# --------------------------------------------------------------------------- #
# Corner/consistency_model/page_eighths_visible_in_same_request_cycle
# --------------------------------------------------------------------------- #
def test_page_eighths_immediately_consistent_on_next_get(api):
    """PRD 3.3: "A successful scheduling sets the scene's shooting_day_id and
    recomputes the parent day's estimated_page_eighths."

    After scheduling, the parent day's estimated_page_eighths is immediately 8 on
    the next GET.

    Design: Corner/consistency_model/page_eighths_visible_in_same_request_cycle
    """
    prod, day = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-10-16", day_number=1)
    scene = fixtures.create_scene(prod["id"], scene_number="20A", page_eighths=8,
                                  int_ext="INT", day_night="DAY")
    fixtures.schedule_scene(scene["id"], day["id"])
    day_after = validate_success(api.get_shooting_day(day["id"], AD))
    assert day_after["estimated_page_eighths"] == 8, \
        f"expected page_eighths 8, got {day_after['estimated_page_eighths']}"
