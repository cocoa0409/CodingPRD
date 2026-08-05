"""Revenue-statement reconciliation (GROSS vs NET, round-per-session) and the
reservation available-ports conservation invariant.

Difficulty: dual_variant_calc/revenue_host_share_gross_vs_net,
combinatorial_formula/revenue_host_share_round_per_session_then_sum,
compensating_invariant/reservation_confirm_cancel_conserves_available_ports.
"""
from test_helpers import (
    validate_success, admin_headers, make_driver_headers,
    create_revenue_statement_payload,
    setup_two_offpeak_finalized_sessions, get_site_version, get_station,
    site_with_port, new_reservation,
)


# --------------------------------------------------------------------------- #
# dual_variant_calc / revenue_host_share_gross_vs_net
# gross 2006; GROSS host_share 300; NET host_share 284
# --------------------------------------------------------------------------- #
def test_gross_statement_host_share_is_300(api):
    """PRD §3.8: "The `gross_revenue_cents` is the sum of their `final_cost_cents`."
    PRD §3.8: "Under the `GROSS` basis, the host share is the sum over the included
    sessions of each session's `final_cost_cents` multiplied by the site's
    `revenue_share_pct`, rounded half-up per session."

    Design: Difficulty/dual_variant_calc/revenue_host_share_gross_vs_net
    """
    ctx = setup_two_offpeak_finalized_sessions()
    site_v = get_site_version(ctx["site_id"])
    stmt = validate_success(api.create_revenue_statement(
        create_revenue_statement_payload(ctx["site_id"], site_v, basis="GROSS"), admin_headers()), 201)
    assert stmt["gross_revenue_cents"] == 2006
    assert stmt["host_share_cents"] == 300


def test_net_statement_host_share_is_284(api):
    """PRD §3.8: "Under the `NET` basis, the host share is the sum over the included
    sessions of the same `revenue_share_pct` multiplied not by the full `final_cost_cents`
    but by the amount net of that session's processor fee ... Because the net basis
    shrinks each session's base by the processor fee, it yields a strictly lower host
    share than the gross basis whenever fees are positive."

    Design: Difficulty/dual_variant_calc/revenue_host_share_gross_vs_net
    """
    ctx = setup_two_offpeak_finalized_sessions()
    site_v = get_site_version(ctx["site_id"])
    stmt = validate_success(api.create_revenue_statement(
        create_revenue_statement_payload(ctx["site_id"], site_v, basis="NET"), admin_headers()), 201)
    assert stmt["host_share_cents"] == 284


# --------------------------------------------------------------------------- #
# combinatorial_formula / revenue_host_share_round_per_session_then_sum
# round(150.45)+round(150.45)=150+150=300, NOT round(2006*0.15)=301
# --------------------------------------------------------------------------- #
def test_host_share_rounds_per_session_not_once_at_end(api):
    """PRD §3.8: "in both cases the per-session amount is rounded half-up before
    summation — the rounding is applied per session, never by summing exact values and
    rounding once."

    Design: Difficulty/combinatorial_formula/revenue_host_share_round_per_session_then_sum
    """
    ctx = setup_two_offpeak_finalized_sessions()
    site_v = get_site_version(ctx["site_id"])
    stmt = validate_success(api.create_revenue_statement(
        create_revenue_statement_payload(ctx["site_id"], site_v, basis="GROSS"), admin_headers()), 201)
    # round(150.45) per session summed = 300, not round(2006*0.15)=301.
    assert stmt["host_share_cents"] == 300
    assert stmt["host_share_cents"] != 301


def test_statement_session_count_is_two(api):
    """PRD §3.8: "These sessions are processed in a deterministic order ... The
    `session_count` is the number of such sessions."

    Design: Difficulty/combinatorial_formula/revenue_host_share_round_per_session_then_sum
    """
    ctx = setup_two_offpeak_finalized_sessions()
    site_v = get_site_version(ctx["site_id"])
    stmt = validate_success(api.create_revenue_statement(
        create_revenue_statement_payload(ctx["site_id"], site_v, basis="GROSS"), admin_headers()), 201)
    assert stmt["session_count"] == 2


# --------------------------------------------------------------------------- #
# compensating_invariant / reservation_confirm_cancel_conserves_available_ports
# --------------------------------------------------------------------------- #
def test_confirm_reservation_drops_available_ports_to_zero(api):
    """PRD §3.2: "those counts are the number of ports on the station and, respectively,
    the number of its ports that are simultaneously `IN_SERVICE` on the operational axis
    and `AVAILABLE` on the occupancy axis."
    PRD §3.3: "confirming a reservation moves an `AVAILABLE` port to `RESERVED`".

    Design: Difficulty/compensating_invariant/reservation_confirm_cancel_conserves_available_ports
    """
    _, station, port = site_with_port(power_kw=100)
    assert get_station(station["id"])["available_ports"] == 1
    r = new_reservation(port["id"], driver_id="drv-1")
    validate_success(api.confirm_reservation(r["id"], make_driver_headers("drv-1")), 200)
    assert get_station(station["id"])["available_ports"] == 0


def test_cancel_confirmed_reservation_restores_available_ports(api):
    """PRD §3.5: "cancelling a `CONFIRMED` reservation releases its hold, returning the
    port's `occupancy_status` to `AVAILABLE` and restoring the station's
    `available_ports`."

    Design: Difficulty/compensating_invariant/reservation_confirm_cancel_conserves_available_ports
    """
    _, station, port = site_with_port(power_kw=100)
    r = new_reservation(port["id"], driver_id="drv-1")
    validate_success(api.confirm_reservation(r["id"], make_driver_headers("drv-1")), 200)
    validate_success(api.cancel_reservation(r["id"], make_driver_headers("drv-1")), 200)
    refreshed_port = validate_success(api.get_port(port["id"], admin_headers()), 200)
    assert refreshed_port["occupancy_status"] == "AVAILABLE"
    assert get_station(station["id"])["available_ports"] == 1
