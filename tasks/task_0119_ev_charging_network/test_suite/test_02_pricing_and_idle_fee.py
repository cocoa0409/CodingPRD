"""Session pricing: ENERGY vs TIME variants, tiered energy cost, idle-occupancy fee.

Queue A (Difficulty): dual_variant_calc / combinatorial_formula / boundary_precision_check
on the session_cost and idle_occupancy_fee calculations.
Queue B (Corner): the >grace idle counterpart and the non-rating cost preview.
"""
import pytest

from test_helpers import (
    validate_success,
    setup_environment,
    run_energy_session,
    set_clock,
    start_session,
    post_meter,
    begin_charging,
    TEST_USERS,
    make_driver_headers,
)

STATION = TEST_USERS["station_headers"]


def test_energy_session_total_cost_is_tiered_plus_idle_plus_fee(api):
    """PRD §3.8: "the energy cost is the first-tier quantity times
    `energy_rate_t1_cents`, plus the second-tier quantity times `energy_rate_t2_cents`,
    plus the third-tier quantity times `energy_rate_t3_cents`, with that sum rounded
    half up to whole cents."
    PRD §3.8: "The final `total_cost_cents` is the variable cost plus `idle_fee_cents`
    plus `session_fee_cents`."

    Design: Difficulty/dual_variant_calc/session_cost_energy_vs_time_same_session
    """
    env = setup_environment(email="ce@x.com")
    # 35 kWh, 50 charging min (00:00->00:50), 25 idle min (00:50->01:15) on ENERGY tariff.
    sess = run_energy_session(
        env, begin_at="2026-06-01T00:00:00Z", suspend_at="2026-06-01T00:50:00Z",
        end_at="2026-06-01T01:15:00Z", end_kwh=35,
    )
    assert sess["energy_delivered_kwh"] == 35, "35 kWh delivered"
    # energy 20*30 + 15*25 = 975; idle (25-10)*50 = 750; fee 100 -> 1825
    assert sess["idle_fee_cents"] == 750, f"idle fee must be 750, got {sess['idle_fee_cents']}"
    assert sess["total_cost_cents"] == 1825, f"ENERGY total must be 1825, got {sess['total_cost_cents']}"


def test_time_session_total_cost_uses_charging_minutes_rate(api):
    """PRD §3.8: "Under `TIME_BASED`, the variable cost is the session's
    `charging_minutes` multiplied by `time_rate_cents_per_min`, and the energy tiers
    are ignored entirely."
    PRD §3.8: "Because the two modes price the same physical session by different
    bases, an identical session yields a different total under each mode."

    Design: Difficulty/dual_variant_calc/session_cost_energy_vs_time_same_session
    """
    env = setup_environment(email="ct@x.com", tariff_overrides={"pricing_mode": "TIME_BASED"})
    # Same physical session as the ENERGY test: 50 charging min, 25 idle min, 35 kWh.
    sess = run_energy_session(
        env, begin_at="2026-06-01T00:00:00Z", suspend_at="2026-06-01T00:50:00Z",
        end_at="2026-06-01T01:15:00Z", end_kwh=35,
    )
    assert sess["charging_minutes"] == 50, f"charging_minutes must be 50, got {sess['charging_minutes']}"
    # time 50*40 = 2000; idle (25-10)*50 = 750; fee 100 -> 2850 (differs from ENERGY 1825)
    assert sess["idle_fee_cents"] == 750, f"idle fee must be 750, got {sess['idle_fee_cents']}"
    assert sess["total_cost_cents"] == 2850, f"TIME total must be 2850, got {sess['total_cost_cents']}"


def test_tiered_energy_cost_three_inputs_nested_minmax(api):
    """PRD §3.8: "the first-tier quantity is the smaller of that energy and
    `energy_tier_1_max_kwh`; the second-tier quantity is the energy in excess of
    `energy_tier_1_max_kwh`, floored at zero, but capped at the width of tier two,
    which is `energy_tier_2_max_kwh` minus `energy_tier_1_max_kwh`; and the third-tier
    quantity is the energy in excess of `energy_tier_2_max_kwh`, floored at zero."

    Design: Difficulty/combinatorial_formula/tiered_energy_cost_three_inputs_nested_minmax
    """
    env = setup_environment(email="tier@x.com")
    sess = run_energy_session(
        env, begin_at="2026-06-01T00:00:00Z", suspend_at="2026-06-01T00:50:00Z",
        end_at="2026-06-01T01:15:00Z", end_kwh=35,
    )
    # 35 kWh -> t1=20@30=600, t2=15@25=375 (NOT 35*30=1050), t3=0 -> energy 975
    # idle 750 + fee 100 -> 1825
    assert sess["total_cost_cents"] == 1825, (
        f"tiered cost must be 1825 (20*30 + 15*25 + idle 750 + fee 100), "
        f"got {sess['total_cost_cents']}"
    )


def test_tiered_energy_cost_crosses_all_three_tiers(api):
    """PRD §3.8: "the third-tier quantity is the energy in excess of
    `energy_tier_2_max_kwh`, floored at zero. The energy cost is the first-tier
    quantity times `energy_rate_t1_cents`, plus the second-tier quantity times
    `energy_rate_t2_cents`, plus the third-tier quantity times `energy_rate_t3_cents`,
    with that sum rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/tiered_energy_cost_three_inputs_nested_minmax
    """
    env = setup_environment(email="tier3@x.com")
    # 75 kWh, no idle (stop right after charging): t1=20@30=600, t2=30@25=750,
    # t3=25@20=500 -> energy 1850; idle 0; fee 100 -> 1950
    sess = run_energy_session(
        env, begin_at="2026-06-01T00:00:00Z", suspend_at=None,
        end_at="2026-06-01T00:40:00Z", end_kwh=75,
    )
    assert sess["idle_fee_cents"] == 0, "no suspension -> no idle minutes -> no idle fee"
    assert sess["total_cost_cents"] == 1950, (
        f"three-tier cost must be 1950 (600+750+500 + fee 100), got {sess['total_cost_cents']}"
    )


def test_idle_fee_grace_inclusive_boundary(api):
    """PRD §3.8: "the billable idle minutes equal the session's `idle_minutes` minus
    the tariff's `idle_grace_minutes`, floored at zero, so that idle minutes equal to
    the grace produce no fee and the fee applies strictly beyond the grace".
    PRD §3.8: "when `idle_minutes` is less than or equal to `idle_grace_minutes` the
    fee is exactly zero".

    Design: Difficulty/boundary_precision_check/idle_fee_grace_inclusive_boundary
    """
    env = setup_environment(email="ib@x.com")
    # 5 kWh, charge 00:00->00:20 (20 min), idle exactly 10 min (00:20->00:30), grace 10.
    sess = run_energy_session(
        env, begin_at="2026-06-01T00:00:00Z", suspend_at="2026-06-01T00:20:00Z",
        end_at="2026-06-01T00:30:00Z", end_kwh=5,
    )
    assert sess["idle_minutes"] == 10, f"idle_minutes must be 10, got {sess['idle_minutes']}"
    assert sess["idle_fee_cents"] == 0, "idle == grace is inclusive: fee is exactly 0"
    # energy 5*30=150 + idle 0 + fee 100 -> 250
    assert sess["total_cost_cents"] == 250, f"total must be 250, got {sess['total_cost_cents']}"


def test_idle_fee_below_grace_boundary(api):
    """PRD §3.8: "when `idle_minutes` is less than or equal to `idle_grace_minutes`
    the fee is exactly zero, and only when `idle_minutes` strictly exceeds the grace
    does the fee equal the excess minutes times the per-minute rate."

    Design: Difficulty/boundary_precision_check/idle_fee_grace_inclusive_boundary
    """
    env = setup_environment(email="ibl@x.com")
    # idle 9 min (00:20->00:29), one minute below the 10-min grace: still 0 fee.
    sess = run_energy_session(
        env, begin_at="2026-06-01T00:00:00Z", suspend_at="2026-06-01T00:20:00Z",
        end_at="2026-06-01T00:29:00Z", end_kwh=5,
    )
    assert sess["idle_minutes"] == 9, f"idle_minutes must be 9, got {sess['idle_minutes']}"
    assert sess["idle_fee_cents"] == 0, "idle below grace produces no fee"
    assert sess["total_cost_cents"] == 250, f"total must be 250, got {sess['total_cost_cents']}"


def test_idle_fee_beyond_grace_correct(api):
    """PRD §3.8: "only when `idle_minutes` strictly exceeds the grace does the fee
    equal the excess minutes times the per-minute rate."
    PRD §3.8: "the `idle_fee_cents` then equals those billable idle minutes
    multiplied by `idle_fee_cents_per_min`."

    Design: Corner/calculations/idle_fee_beyond_grace_correct
    """
    env = setup_environment(email="if@x.com")
    # 5 kWh, charge 00:00->00:20, idle 11 min (00:20->00:31), grace 10 -> 1 billable min * 50.
    sess = run_energy_session(
        env, begin_at="2026-06-01T00:00:00Z", suspend_at="2026-06-01T00:20:00Z",
        end_at="2026-06-01T00:31:00Z", end_kwh=5,
    )
    assert sess["idle_minutes"] == 11, f"idle_minutes must be 11, got {sess['idle_minutes']}"
    assert sess["idle_fee_cents"] == 50, f"idle fee must be 50 (1*50), got {sess['idle_fee_cents']}"
    # energy 150 + idle 50 + fee 100 -> 300
    assert sess["total_cost_cents"] == 300, f"total must be 300, got {sess['total_cost_cents']}"


def test_cost_preview_computes_without_rating(api):
    """PRD §3.6: "A computed read previews the session cost and idle fee for the
    current meter state without rating the session, exposing what `total_cost_cents`
    and the idle-occupancy fee would be if the session stopped now."

    Design: Corner/calculations/cost_preview_computes_without_rating
    """
    env = setup_environment(email="cp@x.com")
    did = env["driver"]["id"]
    sess = start_session(env["stall"]["id"], did)
    post_meter(sess["id"], 0, "2026-06-01T00:00:00Z", "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    post_meter(sess["id"], 18, "2026-06-01T00:10:00Z", "SAMPLE_PERIODIC")
    resp = api.cost_preview(sess["id"], make_driver_headers(did))
    data = validate_success(resp, expected_status=200)
    # 18 kWh * 30c = 540 + idle 0 + fee 100 -> 640
    assert data["total_cost_cents"] == 640, f"preview total must be 640, got {data['total_cost_cents']}"
    assert data["billing_status"] == "UNBILLED", "preview must not rate the session"
    drv = validate_success(api.get_driver(did, make_driver_headers(did)), expected_status=200)
    assert drv["wallet_balance_cents"] == 100000, "preview must not debit the wallet"
