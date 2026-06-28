"""Violation scoring: provisional vs confirmed points, escalation, standing tier.

Covers the driver-domain dual-variant calculation (provisional vs confirmed with
repeat-offender escalation) and the corner-design standing-tier / dismiss instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_driver_headers, make_host_headers, TEST_USERS,
    setup_host_driver_spot, create_booking, log_violation, confirm_violation,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: dual_variant_calc / provisional_vs_confirmed_violation_points_escalation ───

def test_confirmed_points_apply_escalation_after_one_prior(api):
    """PRD §3.8: "The assessed points are the record's `base_points` multiplied by the
    weight of its `violation_kind` (the same `OVERSTAY` = 1, `UNAUTHORIZED_GATE` = 2,
    `NO_SHOW` = 3 weights) multiplied by a repeat-offender escalation factor, then rounded
    half up to a whole number of points."
    PRD §3.8: "The escalation factor in basis points is 10000 plus 2500 for each of the
    driver's already-confirmed records that were created before this one ... capped at 3
    such priors".

    With one prior CONFIRMED record, the escalation is 12500 bps. A second record
    (UNAUTHORIZED_GATE w=2, base 2) assesses round_half_up(2*2*1.25) = 5.

    Design: Difficulty/dual_variant_calc/provisional_vs_confirmed_violation_points_escalation
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=10000,
                                                spot_overrides={"zone_code": "Z2"})
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", spot["version"])
    # First record confirmed -> establishes one prior CONFIRMED.
    vr1 = log_violation(host["id"], booking["id"], "OVERSTAY", 3)
    confirm_violation(vr1["id"])
    # Second OPEN record, then confirm under escalation.
    vr2 = log_violation(host["id"], booking["id"], "UNAUTHORIZED_GATE", 2)
    confirmed2 = confirm_violation(vr2["id"])
    assert confirmed2["assessed_points"] == 5, confirmed2["assessed_points"]


def test_confirm_accumulates_violation_points(api):
    """PRD §3.8: "Confirming a record adds its `assessed_points` to the driver's
    `violation_points`".

    First confirm of OVERSTAY base 3 (w=1, no priors) assesses 3; second confirm of
    UNAUTHORIZED_GATE base 2 (w=2, one prior, 1.25x) assesses 5; total violation_points = 8.

    Design: Difficulty/dual_variant_calc/provisional_vs_confirmed_violation_points_escalation
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=10000,
                                                spot_overrides={"zone_code": "Z2b"})
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", spot["version"])
    vr1 = log_violation(host["id"], booking["id"], "OVERSTAY", 3)
    confirm_violation(vr1["id"])
    vr2 = log_violation(host["id"], booking["id"], "UNAUTHORIZED_GATE", 2)
    confirm_violation(vr2["id"])
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["violation_points"] == 8, drv["violation_points"]


# ─── Corner: calculations / standing_tier_watch_at_exactly_five_points ───

def test_standing_tier_watch_at_exactly_five_points(api):
    """PRD §3.8: "the tier is `SUSPENDED` when `violation_points` is at least 10, `WATCH`
    when `violation_points` is at least 5 but below 10 (5 is inclusive and maps to `WATCH`,
    while 4 remains `GOOD`)".

    An OVERSTAY (w=1) base 5 with no priors assesses 5; confirming it moves the driver's
    standing_tier to WATCH at exactly the 5-point boundary.

    Design: Corner/calculations/standing_tier_watch_at_exactly_five_points
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000,
                                                spot_overrides={"zone_code": "ZCA7"})
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", spot["version"])
    vr = log_violation(host["id"], booking["id"], "OVERSTAY", 5)
    confirmed = confirm_violation(vr["id"])
    assert confirmed["assessed_points"] == 5, confirmed["assessed_points"]
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["standing_tier"] == "WATCH", drv["standing_tier"]


# ─── Corner: calculations / dismiss_violation_zero_points_provisional_drops ───

def test_dismiss_violation_zeroes_points_and_drops_provisional(api):
    """PRD §3.8: "Dismissing a record instead requires it to be `OPEN`, advances its
    `status` from `OPEN` to `DISMISSED`, sets its `assessed_points` to 0, leaves the
    driver's `violation_points` unchanged".
    PRD §3.8: "Whether a record is confirmed or dismissed, the driver's
    `provisional_violation_points` is re-derived because the set of open records has shrunk."

    An OPEN OVERSTAY base 3 contributes provisional 3; dismissing it sets assessed_points=0,
    provisional back to 0, and confirmed violation_points stay 0.

    Design: Corner/calculations/dismiss_violation_zero_points_provisional_drops
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000,
                                                spot_overrides={"zone_code": "ZCA8"})
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", spot["version"])
    vr = log_violation(host["id"], booking["id"], "OVERSTAY", 3)
    dismissed = get_success_data(api.dismiss_violation(vr["id"], ADMIN))
    assert dismissed["assessed_points"] == 0, dismissed["assessed_points"]
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["provisional_violation_points"] == 0, drv["provisional_violation_points"]
    assert drv["violation_points"] == 0, drv["violation_points"]
