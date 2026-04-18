"""Reservation fee calculation tests — provisional and final, per kind and plan.

Covers PRD §3.3 (pricing engine: meeting room, event area, workstation — HOURLY /
DAILY / MONTHLY — and the retrospective min-pick for workstation final fee).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    confirm_reservation,
    create_and_confirm_reservation,
    create_reservation,
    create_resource,
    get_reservation,
    make_tenant_member_headers,
    run_full_reservation_lifecycle,
    setup_tenant_member_badge,
    validate_success,
)


def test_meeting_room_provisional_fee_half_hour_rounding(api, admin_headers):
    """PRD §3.3: "For a meeting room, the billable unit count is the duration
    in hours rounded up to the nearest half-hour (so any spill past a
    half-hour boundary costs another half-hour), and the fee is the product of
    those units and `hourly_rate_cents`, rounded half-up to the nearest integer
    cent."

    Claim: booking 1.0 hour at hourly_rate_cents=991 → provisional 991¢ (2 * 991 / 2).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    mr = create_resource(kind="MEETING_ROOM", code="MR-FEE-1", hourly_rate_cents=991)
    advance_clock_to("2026-07-20T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, mr,
        "2026-07-20T09:00:00.000Z", "2026-07-20T10:00:00.000Z",
    )
    # 1.0 hour = 2 half-hour units * 991¢/2 -> 1 hour * 991¢/hour = 991¢.
    # Formula: units = ceil(hours*2)/2 = 1.0; fee = 1.0 * 991 = 991.
    assert confirmed["provisional_fee_cents"] == 991


def test_workstation_hourly_plan_provisional_fee(api, admin_headers):
    """PRD §3.3: "an `HOURLY` plan multiplies the raw fractional hours by
    `hourly_rate_cents` and rounds half-up to the nearest integer cent."

    Claim: 2h workstation on HOURLY at 800¢/h → provisional 1600¢.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-H-1", hourly_rate_cents=800)
    advance_clock_to("2026-07-21T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, ws,
        "2026-07-21T09:00:00.000Z", "2026-07-21T11:00:00.000Z",
    )
    assert confirmed["provisional_fee_cents"] == 1600


def test_workstation_daily_plan_provisional_fee(api, admin_headers):
    """PRD §3.3: "a `DAILY` plan divides the hours by the workstation-daily
    constant of eight hours per day, rounds up to the next whole day, and
    multiplies that day count by `daily_rate_cents`."

    Claim: 8h workstation on DAILY at daily_rate_cents=5000 → provisional 5000¢
    (1 day * 5000¢).
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="DAILY")
    ws = create_resource(
        kind="WORKSTATION", code="WS-D-1", hourly_rate_cents=800, daily_rate_cents=5000
    )
    advance_clock_to("2026-07-22T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, ws,
        "2026-07-22T09:00:00.000Z", "2026-07-22T17:00:00.000Z",
    )
    # ceil(8 / 8) = 1 day; 1 * 5000 = 5000.
    assert confirmed["provisional_fee_cents"] == 5000


def test_workstation_monthly_plan_provisional_is_zero(api, admin_headers):
    """PRD §3.3: "a `MONTHLY` plan sets the provisional fee to 0 because the
    entitlement is already paid for through the monthly commitment."

    Claim: workstation reservation under MONTHLY lease → provisional_fee_cents == 0.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(
        billing_plan="MONTHLY", monthly_rate_cents=90_000
    )
    ws = create_resource(
        kind="WORKSTATION", code="WS-M-1", hourly_rate_cents=800, daily_rate_cents=5000
    )
    advance_clock_to("2026-07-23T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, ws,
        "2026-07-23T09:00:00.000Z", "2026-07-23T17:00:00.000Z",
    )
    assert confirmed["provisional_fee_cents"] == 0


def test_event_area_provisional_fee_block_based(api, admin_headers):
    """PRD §3.3: "For an event area, the block count is the duration in hours
    divided by four and rounded up (so a two-hour booking still costs one
    four-hour block); the gross fee is the block count multiplied by
    `block_rate_cents`."

    Claim: 4h event area at block_rate_cents=10_000 on a weekday → provisional 10_000.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ev = create_resource(
        kind="EVENT_AREA", code="EVT-WD-1", block_rate_cents=10_000
    )
    # 2026-07-27 is a Monday.
    advance_clock_to("2026-07-27T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, ev,
        "2026-07-27T09:00:00.000Z", "2026-07-27T13:00:00.000Z",
    )
    # 1 block * 10_000 = 10_000.
    assert confirmed["provisional_fee_cents"] == 10_000


def test_event_area_full_weekend_discount(api, admin_headers):
    """PRD §3.3: "if both `start_at` and `end_at` fall on a Saturday or Sunday (the
    full-weekend condition), the gross is halved via integer division by two
    (a 50% full-weekend discount); otherwise the gross is the fee."

    Claim: Saturday-only event area booking at block_rate_cents=10_000 →
    provisional = 10_000 // 2 = 5_000.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ev = create_resource(
        kind="EVENT_AREA", code="EVT-WKND-1", block_rate_cents=10_000
    )
    # 2026-08-01 is a Saturday.
    advance_clock_to("2026-08-01T07:00:00.000Z")
    confirmed = create_and_confirm_reservation(
        tenant, member, ev,
        "2026-08-01T09:00:00.000Z", "2026-08-01T13:00:00.000Z",
    )
    assert confirmed["provisional_fee_cents"] == 5_000


def test_workstation_final_fee_picks_cheaper_tier_retrospectively(api, admin_headers):
    """PRD §3.3: "for a workstation under `HOURLY` or `DAILY`, two candidate fees
    are computed — the hourly candidate is the billable duration multiplied by
    `hourly_rate_cents`, rounded half-up to the nearest integer cent, and the
    daily candidate is the billable duration divided by the eight-hour-per-day
    constant, rounded up to the next whole day, then multiplied by
    `daily_rate_cents` — and the smaller of the two is chosen as the final fee."

    Claim: 8h booking at 800¢/h + 5000¢/day provisional=5000 (daily wins). Early
    check-out after 5 actual hours: hourly=4000, daily=5000 → final 4000.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="DAILY")
    ws = create_resource(
        kind="WORKSTATION", code="WS-FLIP-1",
        hourly_rate_cents=800, daily_rate_cents=5000,
    )
    advance_clock_to("2026-08-03T07:00:00.000Z")
    reservation = create_and_confirm_reservation(
        tenant, member, ws,
        "2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z",
    )
    assert reservation["provisional_fee_cents"] == 5000
    advance_clock_to("2026-08-03T09:00:00.000Z")
    from test_helpers import check_in_reservation, check_out_reservation
    check_in_reservation(reservation, member, badge)
    advance_clock_to("2026-08-03T14:00:00.000Z")  # 5 actual hours
    check_out_reservation(reservation, member, badge)
    final = get_reservation(reservation["id"])
    assert final["status"] == "COMPLETED"
    assert final["final_fee_cents"] == 4000, (
        "PRD §3.3: final fee is min(hourly=4000, daily=5000) = 4000"
    )


def test_workstation_final_fee_tiebreak_picks_hourly(api, admin_headers):
    """PRD §3.3: "when the two candidates are exactly equal, the hourly
    candidate wins and the chosen plan is recorded as `HOURLY`."

    Claim: 7h booked (granularity OK), 6.25h actual check-out →
    hourly=round_half_up(6.25*800)=5000; daily=ceil(6.25/8)=1*5000=5000;
    tie → HOURLY branch → final_fee_cents == 5000.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="DAILY")
    ws = create_resource(
        kind="WORKSTATION", code="WS-TIE-2",
        hourly_rate_cents=800, daily_rate_cents=5000,
    )
    advance_clock_to("2026-08-05T07:00:00.000Z")
    reservation = create_and_confirm_reservation(
        tenant, member, ws,
        "2026-08-05T09:00:00.000Z", "2026-08-05T16:00:00.000Z",  # 7 hours booked
    )
    advance_clock_to("2026-08-05T09:00:00.000Z")
    from test_helpers import check_in_reservation, check_out_reservation
    check_in_reservation(reservation, member, badge)
    advance_clock_to("2026-08-05T15:15:00.000Z")  # 6.25 actual hours
    check_out_reservation(reservation, member, badge)
    final = get_reservation(reservation["id"])
    assert final["final_fee_cents"] == 5000
