"""Crew labor: half-open overlap discipline, compensating cancel, overtime boundary (PRD 2.8, 3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_crew,
    create_crew,
    get_success_data,
    setup_booked_order,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


def test_crew_half_open_adjacency_allowed(api):
    """PRD section 2.8: "A crew assignment's worked hours form a half-open
    interval that includes `start_hour` and excludes `end_hour`. When two
    confirmed crews of the same agent on the same service date have intersecting
    intervals, the later confirmation is rejected with
    `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409); back-to-back intervals, where one
    crew's `end_hour` equals the other's `start_hour`, do not intersect and are
    allowed."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_interval_adjacency
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    cr1 = create_crew(ctx, service_end="ORIGIN", start_hour=8, end_hour=12, crew_size=2)
    cr2 = create_crew(ctx, service_end="ORIGIN", start_hour=12, end_hour=16, crew_size=2)

    confirmed1 = confirm_crew(ctx, cr1["id"], service_end="ORIGIN")
    assert confirmed1["status"] == "CONFIRMED"
    confirmed2 = confirm_crew(ctx, cr2["id"], service_end="ORIGIN")
    assert confirmed2["status"] == "CONFIRMED", (
        "start == predecessor's end is adjacency, not overlap (half-open intervals)"
    )


def test_crew_half_open_overlap_rejected(api):
    """PRD section 2.8: "A crew assignment's worked hours form a half-open
    interval that includes `start_hour` and excludes `end_hour`. When two
    confirmed crews of the same agent on the same service date have intersecting
    intervals, the later confirmation is rejected with
    `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409); back-to-back intervals, where one
    crew's `end_hour` equals the other's `start_hour`, do not intersect and are
    allowed."
    PRD section 3.6: "Confirming a crew booking is the sourcing agent's own act:
    the crew must be `REQUESTED` (otherwise `ERR_TRANSITION_NOT_ALLOWED`), the
    caller's `X-User-ID` must equal the crew's `agent_id` (else
    `ERR_FORBIDDEN_ROLE`), and no other `CONFIRMED` crew of the same agent on the
    same `service_date` may have a worked interval intersecting this one under the
    half-open rule of §2.8 — a conflict is rejected with
    `ERR_CREW_SCHEDULE_CONFLICT`, while back-to-back intervals are allowed."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_interval_adjacency
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    cr1 = create_crew(ctx, service_end="ORIGIN", start_hour=8, end_hour=12, crew_size=2)
    cr3 = create_crew(ctx, service_end="ORIGIN", start_hour=11, end_hour=13, crew_size=1)
    confirm_crew(ctx, cr1["id"], service_end="ORIGIN")

    resp = api.confirm_crew_assignment(cr3["id"], ctx["origin_h"])
    validate_error(resp, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)

    after = get_success_data(api.get_crew_assignment(cr3["id"], ADMIN))
    assert after["status"] == "REQUESTED", "[11,13) intersects [8,12) and must stay unconfirmed"


def test_crew_confirm_blocked_while_slot_held(api):
    """PRD section 3.6: "no other `CONFIRMED` crew of the same agent on the same
    `service_date` may have a worked interval intersecting this one under the
    half-open rule of §2.8 — a conflict is rejected with
    `ERR_CREW_SCHEDULE_CONFLICT`, while back-to-back intervals are allowed."

    Design: Difficulty/compensating_invariant/crew_hours_confirm_cancel_roundtrip
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    crew_a = create_crew(ctx, service_end="ORIGIN", start_hour=8, end_hour=12, crew_size=2)
    crew_b = create_crew(ctx, service_end="ORIGIN", start_hour=8, end_hour=12, crew_size=3)
    confirm_crew(ctx, crew_a["id"], service_end="ORIGIN")

    resp = api.confirm_crew_assignment(crew_b["id"], ctx["origin_h"])
    validate_error(resp, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)
    after = get_success_data(api.get_crew_assignment(crew_b["id"], ADMIN))
    assert after["status"] == "REQUESTED", "the identical slot is held by the confirmed crew"


def test_crew_confirm_cancel_roundtrip_restores_pool(api):
    """PRD section 3.6: "Cancellation by the origin agent, the destination agent,
    or the booking agent is allowed from `REQUESTED` or `CONFIRMED` and lands the
    crew in the terminal `CANCELLED`; cancelling a `CONFIRMED` crew returns its
    hours to the agent's pool for that date as a compensating action, and an
    order-level cancellation cascades `REQUESTED` and `CONFIRMED` crews to
    `CANCELLED` with the same compensation."

    Design: Difficulty/compensating_invariant/crew_hours_confirm_cancel_roundtrip
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    crew_a = create_crew(ctx, service_end="ORIGIN", start_hour=8, end_hour=12, crew_size=2)
    crew_b = create_crew(ctx, service_end="ORIGIN", start_hour=8, end_hour=12, crew_size=3)
    confirm_crew(ctx, crew_a["id"], service_end="ORIGIN")
    blocked = api.confirm_crew_assignment(crew_b["id"], ctx["origin_h"])
    validate_error(blocked, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)

    cancelled = get_success_data(api.cancel_crew_assignment(crew_a["id"], ctx["origin_h"]))
    assert cancelled["status"] == "CANCELLED"

    confirmed_b = get_success_data(api.confirm_crew_assignment(crew_b["id"], ctx["origin_h"]))
    assert confirmed_b["status"] == "CONFIRMED", (
        "the cancelled hours returned to the agent-date pool, so the identical interval confirms"
    )

    # The pool now holds exactly crew B's confirmed hours on that date.
    crews, _meta = validate_paginated(
        api.list_crew_assignments(
            ADMIN,
            params={"agent_id": ctx["origin_agent"]["id"], "status": "CONFIRMED"},
        )
    )
    total_confirmed_hours = sum(c["labor_hours"] for c in crews)
    assert total_confirmed_hours == 4, (
        f"only crew B's 4 hours remain confirmed, got {total_confirmed_hours}"
    )


def test_crew_overtime_exactly_8_hours_boundary(api):
    """PRD section 3.6: "Regular hours are `labor_hours` capped at 8 — a shift of
    exactly eight hours earns no overtime — and overtime hours are whatever
    remains beyond 8. Each worker earns the regular hours times the order's tariff
    `hourly_labor_rate_cents`, plus the overtime hours times that rate times one
    and a half, with only the overtime component rounded half up to integer cents.
    The crew's `invoice_amount_cents` is that per-worker amount multiplied by
    `crew_size`; the rounding is pinned so that the per-worker overtime is rounded
    before the crew-size multiplication, never after."
    PRD section 3.6: "A new crew assignment opens in `REQUESTED` with
    `labor_hours` computed as the end hour minus the start hour."

    Design: Corner/calculations/crew_overtime_exactly_8_hours_boundary
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    cr8 = create_crew(
        ctx, service_end="ORIGIN", service_date="2026-06-10T00:00:00Z",
        start_hour=8, end_hour=16, crew_size=3,
    )
    assert cr8["labor_hours"] == 8
    assert cr8["invoice_amount_cents"] == 96000, (
        f"3 * 8 * 4000 with no overtime at exactly 8 hours, got {cr8['invoice_amount_cents']}"
    )

    cr9 = create_crew(
        ctx, service_end="ORIGIN", service_date="2026-06-11T00:00:00Z",
        start_hour=8, end_hour=17, crew_size=2,
    )
    assert cr9["labor_hours"] == 9
    # 2 * (8*4000 + round_half_up(1*4000*1.5)) = 2 * 38000
    assert cr9["invoice_amount_cents"] == 76000, (
        f"one OT hour per worker at 1.5x, got {cr9['invoice_amount_cents']}"
    )
