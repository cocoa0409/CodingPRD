"""Transient-charge computation: session_kind divergence, the pinned
multiplier→cap→flat order, the daily cap, the grace boundary, and the half-open
event window threshold.

PRD §3.6 governs gross_charge_cents; §2.6 the precision rules.
"""
from test_helpers import (
    validate_success,
    set_clock,
    setup_garage_with_zone,
    setup_transient_facility,
    setup_published_event_session,
    create_motorist,
    request_permit,
    activate_permit,
    create_space,
    open_session,
    close_session,
    get_zone,
)


def test_permit_session_billed_zero_vs_transient_metered(api):
    """PRD §3.6: "A `PERMIT` session is always billed zero, regardless of how long
    the vehicle stayed, because the monthly permit fee already covers it."
    PRD §3.6: "Otherwise the system counts billable hours by taking the duration in
    minutes, dividing by sixty, and rounding up to the next whole hour — every
    started hour is billed. The base metered amount is that billable-hour count
    multiplied by the rate plan's `hourly_cents`."

    A 150-min stay: PERMIT bills 0; identical TRANSIENT bills ceil(150/60)*500 = 1500.

    Design: Difficulty/dual_variant_calc/transient_charge_permit_zero_vs_transient_metered
    """
    set_clock("2026-06-01T09:00:00Z")
    facility = setup_garage_with_zone(
        zone_type="MIXED", permit_capacity=5, num_spaces=0,
        rate_overrides={"hourly_cents": 500, "daily_cap_cents": 4000,
                        "monthly_permit_cents": 9000, "grace_minutes": 15},
    )
    garage, zone = facility["garage"], facility["zone"]
    create_space(zone["id"], label="S1")
    create_space(zone["id"], label="S2")
    motorist = create_motorist("dv@x.com", default_plate="ABC123")
    permit = request_permit(zone["id"], motorist["id"], "ABC123")
    activate_permit(permit["id"], zone["version"])

    set_clock("2026-06-01T10:00:00Z")
    permit_sess = open_session(garage["id"], "ABC123", "2026-06-01T10:00:00Z", permit_id=permit["id"])
    trans_sess = open_session(garage["id"], "XYZ999", "2026-06-01T10:00:00Z")
    assert permit_sess["session_kind"] == "PERMIT"
    assert trans_sess["session_kind"] == "TRANSIENT"

    permit_exit = close_session(permit_sess["id"], "2026-06-01T12:30:00Z")
    trans_exit = close_session(trans_sess["id"], "2026-06-01T12:30:00Z")

    assert permit_exit["session_kind"] == "PERMIT"
    assert permit_exit["gross_charge_cents"] == 0
    assert trans_exit["session_kind"] == "TRANSIENT"
    assert trans_exit["gross_charge_cents"] == 1500


def test_event_priced_multiplier_then_cap_then_flat_order(api):
    """PRD §3.6: "When such a window applies, the metered amount is multiplied by
    the window's `multiplier` and the product is rounded to the nearest whole cent
    using round-half-up — this multiplier step is the only place rounding occurs in
    the pipeline."
    PRD §3.6: "the metered amount becomes the smaller of its current value and the
    cap. Finally, if an event window applied, the window's `flat_surcharge_cents` is
    added once, after the cap rather than before it."

    150 min at 500/h → 1500, ×2.0 = 3000 (under the 4000 cap), + flat 1000 = 4000.

    Design: Difficulty/combinatorial_formula/event_priced_metered_then_capped_then_flat_order
    """
    ctx = setup_published_event_session(
        window_start_utc="2026-06-01T09:00:00Z", window_end_utc="2026-06-01T18:00:00Z",
        multiplier=2.0, flat_surcharge_cents=1000, entry_at_utc="2026-06-01T10:00:00Z",
        plate="EVT777",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15,
    )
    exited = close_session(ctx["session"]["id"], "2026-06-01T12:30:00Z")
    assert exited["gross_charge_cents"] == 4000


def test_daily_cap_clamps_long_transient_stay(api):
    """PRD §3.6: "The system counts cap blocks by taking the duration in minutes,
    dividing by one thousand four hundred forty, and rounding up to the next whole
    24-hour block, then caps the metered amount at that block count multiplied by
    the rate plan's `daily_cap_cents` — the metered amount becomes the smaller of
    its current value and the cap."

    600 min (10h) at 500/h metered 5000 → clamped to one-block cap 4000.

    Design: Corner/calculations/daily_cap_clamps_long_transient_stay
    """
    facility = setup_transient_facility(
        num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
        monthly_permit_cents=9000, grace_minutes=15,
    )
    set_clock("2026-06-01T10:00:00Z")
    sess = open_session(facility["garage"]["id"], "CAP999", "2026-06-01T10:00:00Z")
    exited = close_session(sess["id"], "2026-06-01T20:00:00Z")
    assert exited["gross_charge_cents"] == 4000


def test_grace_minutes_boundary_exact_vs_over(api):
    """PRD §3.6: "If the duration is at or below the rate plan's `grace_minutes`,
    the charge is exactly zero and computation stops; grace does not subtract time
    from longer stays, it only zeroes out sub-grace visits."
    PRD §3.6: "every started hour is billed. The base metered amount is that
    billable-hour count multiplied by the rate plan's `hourly_cents`."

    15 min (== grace) bills 0; 16 min bills one started hour = 500.

    Design: Difficulty/boundary_precision_check/grace_minutes_boundary_exact_vs_over
    """
    facility = setup_transient_facility(
        num_spaces=2, hourly_cents=500, daily_cap_cents=4000,
        monthly_permit_cents=9000, grace_minutes=15,
    )
    garage = facility["garage"]
    set_clock("2026-06-01T10:00:00Z")
    s15 = open_session(garage["id"], "GRC015", "2026-06-01T10:00:00Z")
    s16 = open_session(garage["id"], "GRC016", "2026-06-01T10:00:00Z")
    e15 = close_session(s15["id"], "2026-06-01T10:15:00Z")
    e16 = close_session(s16["id"], "2026-06-01T10:16:00Z")
    assert e15["gross_charge_cents"] == 0
    assert e16["gross_charge_cents"] == 500


def test_event_window_exclusive_end_not_surcharged(api):
    """PRD §3.6: "The half-open interval runs from `window_start_utc` up to but not
    including `window_end_utc`".
    PRD §3.6: "the system selects the single window whose half-open interval from
    `window_start_utc` up to `window_end_utc` contains the session's `entry_at_utc`".

    Entry exactly at the exclusive window_end (18:00) is NOT in the window, so a
    60-min stay bills plain metered 500 (no ×2.0, no flat).

    Design: Corner/cross_cutting_complexity_layers/event_multiplier_threshold_inside_vs_outside_window
    """
    ctx = setup_published_event_session(
        window_start_utc="2026-06-01T09:00:00Z", window_end_utc="2026-06-01T18:00:00Z",
        multiplier=2.0, flat_surcharge_cents=1000, entry_at_utc="2026-06-01T18:00:00Z",
        plate="WIN111",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15,
    )
    exited = close_session(ctx["session"]["id"], "2026-06-01T19:00:00Z")
    assert exited["gross_charge_cents"] == 500
