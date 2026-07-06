"""Session billing: per-minute vs per-hour variants, ceil/surcharge ordering,
min-block flooring, reconciliation, and immediate visibility."""
from test_helpers import (
    validate_success,
    provision_med_phone, provision_court_onsite_per_hour,
    create_ended_session, set_clock,
    make_client_headers, coordinator_headers,
    factories,
)


def _court_onsite_2h45m_ended_session():
    """COURT/PER_HOUR/ONSITE session connected 09:00 -> ended 11:45 (2h45m = 9900s)."""
    env = provision_court_onsite_per_hour()
    set_clock("2026-03-10T08:50:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T11:45:00Z",
        request_overrides={"modality": "ONSITE", "required_tier": "LEGAL"},
    )
    env.update({"request": req, "assignment": asg, "session": session})
    return env


def test_per_hour_onsite_session_bills_ceil_hours_plus_travel(api):
    """PRD 3.5: "For a per-hour plan, divide the duration in seconds by 3600 and round
    up to the next whole hour to get the raw units, then take the larger of that figure
    and the plan's min_block_units; the charge is that number of billed units multiplied
    by rate_cents, plus - and only when the modality is ONSITE - the plan's
    travel_surcharge_cents added once after the multiplication."

    Design: Difficulty/dual_variant_calc/session_billing_per_minute_vs_per_hour_diverge
    """
    env = _court_onsite_2h45m_ended_session()
    session = env["session"]
    # 9900s -> ceil(9900/3600) = 3 hours; max(3, min_block 2) = 3; 3*12000 + 4500 = 40500.
    assert session["billed_units"] == 3, f"expected 3 billed hours, got {session['billed_units']}"
    assert session["billed_amount_cents"] == 40500, (
        f"expected 40500c, got {session['billed_amount_cents']}"
    )


def test_per_minute_session_does_not_add_travel_surcharge(api):
    """PRD 3.5: "For a per-minute plan, divide the duration in seconds by 60 and round up
    to the next whole minute to get the raw units, then take the larger of that figure and
    the plan's min_block_units; the charge is that number of billed units multiplied by
    rate_cents, and no travel surcharge is ever added."

    Design: Difficulty/dual_variant_calc/session_billing_per_minute_vs_per_hour_diverge
    """
    # Same 2h45m (9900s) duration, but under a PER_MINUTE plan: ceil(9900/60)=165 minutes,
    # max(165, min 10)=165, 165*195=32175 with NO surcharge -> diverges from the 40500 hour case.
    env = provision_med_phone()
    set_clock("2026-03-10T08:50:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T11:45:00Z",
    )
    assert session["billed_units"] == 165, f"expected 165 minutes, got {session['billed_units']}"
    assert session["billed_amount_cents"] == 32175, (
        f"expected 32175c (no surcharge), got {session['billed_amount_cents']}"
    )


def test_ceil_before_multiply_then_surcharge_order_pinned(api):
    """PRD 2.7: "Where a calculation converts elapsed time into billable units, the
    conversion uses ceiling - any partial unit rounds up to the next whole unit - and
    that ceiling is applied to the time-to-units step before any multiplication by a rate.
    For onsite per-hour work, the flat travel surcharge is added after the rate
    multiplication, never folded into it; this per-line ordering is fixed."

    Design: Difficulty/combinatorial_formula/session_billing_ceil_before_multiply_then_surcharge_order
    """
    env = _court_onsite_2h45m_ended_session()
    session = env["session"]
    # ceil(9900/3600)=3 BEFORE multiply: 3*12000=36000, +4500 surcharge AFTER = 40500.
    assert session["billed_units"] == 3
    assert session["billed_amount_cents"] == 40500, (
        f"40500 requires ceil-then-multiply-then-surcharge; got {session['billed_amount_cents']}"
    )


def test_per_hour_onsite_full_session_entity_valid(api):
    """PRD 3.5: "the charge is that number of billed units multiplied by rate_cents, plus
    - and only when the modality is ONSITE - the plan's travel_surcharge_cents added once
    after the multiplication."

    Design: Difficulty/combinatorial_formula/session_billing_ceil_before_multiply_then_surcharge_order
    """
    env = _court_onsite_2h45m_ended_session()
    fetched = validate_success(api.get_session(env["session"]["id"], coordinator_headers()))
    assert fetched["billed_units"] == 3
    assert fetched["billed_amount_cents"] == 40500


def test_per_minute_min_block_floor_at_4_minutes(api):
    """PRD 3.5: "For a per-minute plan, divide the duration in seconds by 60 and round up
    to the next whole minute to get the raw units, then take the larger of that figure and
    the plan's min_block_units; the charge is that number of billed units multiplied by
    rate_cents, and no travel surcharge is ever added."

    Design: Difficulty/boundary_precision_check/per_minute_min_block_floor_at_4_minutes
    """
    env = provision_med_phone()  # 195c/min, min_block 10
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:04:00Z",
    )
    # 240s -> ceil=4 min, but floored to min_block 10 -> billed_units=10, 10*195=1950.
    assert session["billed_units"] == 10, f"4 min must floor to 10, got {session['billed_units']}"
    assert session["billed_amount_cents"] == 1950, (
        f"expected 1950c, got {session['billed_amount_cents']}"
    )


def test_per_minute_billed_amount_above_min_block(api):
    """PRD 3.5: "divide the duration in seconds by 60 and round up to the next whole
    minute to get the raw units, then take the larger of that figure and the plan's
    min_block_units; the charge is that number of billed units multiplied by rate_cents."

    Design: Difficulty/boundary_precision_check/per_minute_min_block_floor_at_4_minutes
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    # 20 min is above the 10-min floor: ceil(1200/60)=20, max(20,10)=20, 20*195=3900.
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    assert session["billed_units"] == 20
    assert session["billed_amount_cents"] == 3900


def test_reconcile_recomputes_billed_amount(api):
    """PRD 3.8: "Reconciliation recomputes billed_amount_cents from the corrected units
    against the effective rate plan - the corrected figure is treated as already-whole
    units, still floored to the plan's min_block_units, with the same rate and the same
    onsite surcharge rule applied - and moves the session to RECONCILED."

    Design: Corner/calculations/reconcile_recomputes_billed_amount
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:50:00Z",
    )
    # 50 min ended (9750c), dispute, then reconcile to 20 units -> 20*195 = 3900.
    client_h = make_client_headers(env["client"]["id"])
    validate_success(api.dispute_session(session["id"], client_h))
    reconciled = validate_success(
        api.reconcile_session(session["id"], factories.reconcile_payload(20), coordinator_headers())
    )
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["billed_units"] == 20, f"expected 20, got {reconciled['billed_units']}"
    assert reconciled["billed_amount_cents"] == 3900, (
        f"expected 3900c, got {reconciled['billed_amount_cents']}"
    )


def test_end_session_response_carries_billed_amount_immediately(api):
    """PRD 3.5: "On end, ended_at is stamped with the clock, the session-billing
    calculation runs to set billed_units and billed_amount_cents, and the session moves
    to ENDED."

    Design: Corner/consistency_model/immediate_visibility_of_billing_on_end
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    # create_ended_session returns the end-response body; billing must already be present.
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    assert session["status"] == "ENDED"
    assert session["billed_amount_cents"] == 3900, "end response must carry billed_amount_cents"
    assert session["billed_units"] == 20
