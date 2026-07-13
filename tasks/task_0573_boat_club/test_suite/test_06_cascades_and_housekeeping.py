"""Housekeeping sweep cascades and no-show strike boundaries.

Translates queue A (Difficulty) instances for transitive_cascade and the no-show
strike boundary_precision check.
"""
import test_helpers as th
from test_helpers import validate_success


# --------------------------------------------------------------------------- #
# Setup helpers
# --------------------------------------------------------------------------- #
def _two_strikes_unlimited():
    """An UNLIMITED member driven to exactly 2 no-show strikes (still ACTIVE)."""
    ctx = th.setup_active_basic_member("UNLIMITED")
    m = ctx["member_id"]
    dock = ctx["dock_id"]
    th.set_clock("2026-05-04T08:00:00Z")
    th.create_confirmed_reservation(m, dock, "PONTOON", "2026-05-04T10:00:00Z", "2026-05-04T12:00:00Z")
    th.set_clock("2026-05-04T11:00:00Z")
    th.run_sweep()  # strike 1
    th.create_confirmed_reservation(m, dock, "PONTOON", "2026-05-04T14:00:00Z", "2026-05-04T16:00:00Z")
    th.set_clock("2026-05-04T15:00:00Z")
    th.run_sweep()  # strike 2
    return ctx


def _noshow_cascade_ready():
    """Two strikes already accrued, plus R3 and R4 CONFIRMED on the same boat; the
    clock sits just past R3's grace but before R4's start."""
    ctx = _two_strikes_unlimited()
    m, dock, b1 = ctx["member_id"], ctx["dock_id"], ctx["boat_ids"][0]
    r3 = th.create_confirmed_reservation(m, dock, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    r4 = th.create_confirmed_reservation(m, dock, "PONTOON", "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
    th.set_clock("2026-05-05T11:00:00Z")
    return ctx, b1, r3["id"], r4["id"]


def _damage_assessed_on_confirmed():
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r1 = th.create_confirmed_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    dr = th.file_damage_report(r1["id"], b1, "MODERATE", 20000)
    dr = th.assess_damage_report(dr["id"])
    return ctx, b1, r1["id"], dr


# --------------------------------------------------------------------------- #
# transitive_cascade (queue A) — no-show sweep depth-4 chain
# --------------------------------------------------------------------------- #
def test_noshow_sweep_suspends_and_cancels_sibling(api):
    """PRD §3.7: "Strikes accumulate since the member's most recent reinstatement, and
    when they reach three the member is suspended: the member transitions from
    `ACTIVE` to `SUSPENDED`, which itself cascades to cancel the member's other
    `CONFIRMED` reservations and release their boats, as in §3.1."

    Design: Difficulty/transitive_cascade/tc_noshow_suspend_cancel_release_depth4
    """
    ctx, b1, r3, r4 = _noshow_cascade_ready()
    m = ctx["member_id"]
    th.run_sweep()
    assert th.get_reservation(r3)["status"] == "NO_SHOW"
    member = th.get_member(m)
    assert member["status"] == "SUSPENDED"
    assert member["no_show_strikes"] == 3
    assert th.get_reservation(r4)["status"] == "CANCELLED"


def test_noshow_sweep_releases_boat_and_fees_member(api):
    """PRD §3.7: "Marking a no-show creates a flat 5,000-cent `NO_SHOW` fee for the
    member, increases the member's `no_show_strikes` by one, and releases the assigned
    boat (the `boat_id` is cleared and the boat stays `AVAILABLE`)."

    Design: Difficulty/transitive_cascade/tc_noshow_suspend_cancel_release_depth4
    """
    ctx, b1, r3, r4 = _noshow_cascade_ready()
    m = ctx["member_id"]
    th.run_sweep()
    # R4 was cancelled by the suspension cascade and its boat released.
    assert th.get_reservation(r4)["boat_id"] is None
    assert th.get_boat(b1)["status"] == "AVAILABLE"
    r3_fee = th.find_fees(reservation_id=r3, fee_type="NO_SHOW")
    assert len(r3_fee) == 1
    assert r3_fee[0]["amount_cents"] == 5000


# --------------------------------------------------------------------------- #
# transitive_cascade (queue A) — damage assess -> maintenance -> revert
# --------------------------------------------------------------------------- #
def test_damage_assess_sends_boat_to_maintenance(api):
    """PRD §3.6: "Assessing the report moves it from `FILED` to `ASSESSED`, computes
    `assessed_fee_cents`, creates a `DAMAGE` fee for the reservation's member, and
    sends the boat to `MAINTENANCE` — which in turn cascades any `CONFIRMED`
    reservation on that boat back to `REQUESTED` with its `boat_id` cleared, exactly
    as in §3.2."

    Design: Difficulty/transitive_cascade/tc_damage_maintenance_revert_depth3
    """
    ctx, b1, r1, dr = _damage_assessed_on_confirmed()
    assert dr["status"] == "ASSESSED"
    assert th.get_boat(b1)["status"] == "MAINTENANCE"


def test_damage_assess_reverts_confirmed_reservation(api):
    """PRD §3.6: "sends the boat to `MAINTENANCE` — which in turn cascades any
    `CONFIRMED` reservation on that boat back to `REQUESTED` with its `boat_id`
    cleared, exactly as in §3.2."

    Design: Difficulty/transitive_cascade/tc_damage_maintenance_revert_depth3
    """
    ctx, b1, r1, dr = _damage_assessed_on_confirmed()
    reverted = th.get_reservation(r1)
    assert reverted["status"] == "REQUESTED"
    assert reverted["boat_id"] is None


# --------------------------------------------------------------------------- #
# boundary_precision_check (queue A) — strike threshold 2 vs 3
# --------------------------------------------------------------------------- #
def test_member_active_at_two_strikes(api):
    """PRD §3.7: "Strikes accumulate since the member's most recent reinstatement, and
    when they reach three the member is suspended".

    Design: Difficulty/boundary_precision_check/bp_noshow_strike_threshold_2_vs_3
    """
    ctx = _two_strikes_unlimited()
    member = th.get_member(ctx["member_id"])
    assert member["no_show_strikes"] == 2
    assert member["status"] == "ACTIVE"


def test_member_suspended_on_third_strike(api):
    """PRD §3.7: "when they reach three the member is suspended: the member transitions
    from `ACTIVE` to `SUSPENDED`".

    Design: Difficulty/boundary_precision_check/bp_noshow_strike_threshold_2_vs_3
    """
    ctx = _two_strikes_unlimited()
    m, dock = ctx["member_id"], ctx["dock_id"]
    th.create_confirmed_reservation(m, dock, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.set_clock("2026-05-05T11:00:00Z")
    th.run_sweep()  # third strike
    member = th.get_member(m)
    assert member["no_show_strikes"] == 3
    assert member["status"] == "SUSPENDED"
