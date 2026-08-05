"""Session energy pricing, idle-fee boundary, and the void money invariant.

Difficulty instances: combinatorial_formula/session_energy_cost_tiered_demand_cap,
boundary_precision_check/idle_fee_grace_boundary_exactly_10_minutes_zero_fee,
compensating_invariant/session_void_conserves_gross_revenue.
"""
from test_helpers import (
    validate_success, api_client, admin_headers, make_driver_headers,
    stop_payload, site_with_port, start_session, stop_session, finalize_session,
    finalized_session, set_clock, get_site,
)


# --------------------------------------------------------------------------- #
# combinatorial_formula / session_energy_cost_tiered_demand_cap
# energy 12.5 kWh, PEAK rate 48, 180kW demand +5 -> raw 662.5 -> 663; fee 100
# --------------------------------------------------------------------------- #
def test_peak_demand_energy_cost_is_663(api):
    """PRD §3.4: "The per-kWh base rate follows the bucket — 48 cents for `PEAK`, 36
    cents for `SHOULDER`, and 24 cents for `OFFPEAK`. A demand surcharge of 5 cents
    per kWh is added to the base rate when, and only when, the session's port has a
    `power_kw` of at least 150 ... `energy_cost_cents` is that raw amount rounded
    half-up to a whole cent, then capped so it never exceeds 50000 cents."
    PRD §3.4: "the hour is `PEAK` when it is at least 16 and before 21".

    Design: Difficulty/combinatorial_formula/session_energy_cost_tiered_demand_cap
    """
    _, _, port = site_with_port(power_kw=180)
    s = start_session(port["id"], driver_id="drv-1", clock="2026-05-01T17:00:00Z")
    set_clock("2026-05-01T17:30:00Z")
    stopped = validate_success(
        api.stop_session(s["id"], stop_payload(12.5), make_driver_headers("drv-1")), 200)
    assert stopped["tou_period"] == "PEAK"
    assert stopped["energy_cost_cents"] == 663


def test_peak_demand_preliminary_cost_is_763(api):
    """PRD §3.4: "The flat `session_fee_cents` is 100. At stop the system records
    `preliminary_cost_cents` as the sum of `energy_cost_cents` and `session_fee_cents`,
    before any idle fee is known."

    Design: Difficulty/combinatorial_formula/session_energy_cost_tiered_demand_cap
    """
    _, _, port = site_with_port(power_kw=180)
    s = start_session(port["id"], driver_id="drv-1", clock="2026-05-01T17:00:00Z")
    set_clock("2026-05-01T17:30:00Z")
    stopped = validate_success(
        api.stop_session(s["id"], stop_payload(12.5), make_driver_headers("drv-1")), 200)
    assert stopped["session_fee_cents"] == 100
    assert stopped["preliminary_cost_cents"] == 763


# --------------------------------------------------------------------------- #
# boundary_precision_check / idle_fee_grace_boundary_exactly_10_minutes_zero_fee
# --------------------------------------------------------------------------- #
def test_idle_exactly_10_minutes_charges_zero(api):
    """PRD §3.4: "When `idle_minutes` is 10 or fewer, `idle_fee_cents` is 0."
    PRD §3.4: "The `idle_minutes` are the whole minutes between `stopped_at` and
    `unplugged_at`, computed as the elapsed seconds divided by 60 and floored to an integer."

    Design: Difficulty/boundary_precision_check/idle_fee_grace_boundary_exactly_10_minutes_zero_fee
    """
    _, _, port = site_with_port(power_kw=100)
    s = start_session(port["id"], driver_id="drv-1", clock="2026-05-01T12:00:00Z")
    stop_session(s["id"], 10.0, driver_id="drv-1", clock="2026-05-01T12:30:00Z")
    set_clock("2026-05-01T12:40:00Z")  # idle exactly 10 minutes
    final = validate_success(api.finalize_session(s["id"], admin_headers()), 200)
    assert final["idle_minutes"] == 10
    assert final["idle_fee_cents"] == 0


def test_idle_11_minutes_charges_one_minute_beyond_grace(api):
    """PRD §3.4: "An idle fee applies only when `idle_minutes` is strictly greater than
    the 10-minute grace allowance; when it is, `idle_fee_cents` is the number of minutes
    beyond the grace — that is, `idle_minutes` minus 10 — multiplied by 40 cents per
    minute, then capped so it never exceeds 3000 cents."

    Design: Difficulty/boundary_precision_check/idle_fee_grace_boundary_exactly_10_minutes_zero_fee
    """
    _, _, port = site_with_port(power_kw=100)
    s = start_session(port["id"], driver_id="drv-1", clock="2026-05-01T12:00:00Z")
    stop_session(s["id"], 10.0, driver_id="drv-1", clock="2026-05-01T12:30:00Z")
    set_clock("2026-05-01T12:41:00Z")  # idle exactly 11 minutes
    final = validate_success(api.finalize_session(s["id"], admin_headers()), 200)
    assert final["idle_minutes"] == 11
    assert final["idle_fee_cents"] == 40


# --------------------------------------------------------------------------- #
# compensating_invariant / session_void_conserves_gross_revenue
# PEAK 17:00->17:30 (12.5 kWh -> energy 663), finalize 17:55 (idle 25 -> 600) -> final 1363
# --------------------------------------------------------------------------- #
def test_finalize_posts_final_cost_to_site_ledger(api):
    """PRD §3.4: "Finalizing also frees the port's `occupancy_status` to `AVAILABLE`
    and posts revenue to the ledger: the host site's `lifetime_gross_revenue_cents`
    increases by the session's `final_cost_cents`."
    PRD §3.4: "The `final_cost_cents` is the sum of `energy_cost_cents`,
    `session_fee_cents`, and `idle_fee_cents`."

    Design: Difficulty/compensating_invariant/session_void_conserves_gross_revenue
    """
    site, _, port = site_with_port(power_kw=180)
    s = finalized_session(port["id"], 12.5,
                          started="2026-05-01T17:00:00Z",
                          stopped="2026-05-01T17:30:00Z",
                          unplugged="2026-05-01T17:55:00Z")
    assert s["final_cost_cents"] == 1363
    refreshed = get_site(site["id"])
    assert refreshed["lifetime_gross_revenue_cents"] == 1363


def test_void_reverses_ledger_to_pre_finalize_value(api):
    """PRD §3.4: "A `ProgramAdmin` may void a `FINALIZED` session into `VOIDED`, which
    reverses the ledger posting by decreasing the host site's
    `lifetime_gross_revenue_cents` by that session's `final_cost_cents`, returning the
    ledger exactly to its pre-finalize value."

    Design: Difficulty/compensating_invariant/session_void_conserves_gross_revenue
    """
    site, _, port = site_with_port(power_kw=180)
    s = finalized_session(port["id"], 12.5,
                          started="2026-05-01T17:00:00Z",
                          stopped="2026-05-01T17:30:00Z",
                          unplugged="2026-05-01T17:55:00Z")
    assert s["final_cost_cents"] == 1363
    validate_success(api.void_session(s["id"], admin_headers()), 200)
    refreshed = get_site(site["id"])
    assert refreshed["lifetime_gross_revenue_cents"] == 0
