"""Port parallel axes, the host-agreement negotiation cycle, and invalid-state lockdowns.

Difficulty: non_linear_state_machine/{port_parallel_axes...,host_agreement_cyclic...}.
Corner: state_machines/{finalize_active...,resolve_already_resolved...,activate_already_active...}.
"""
from test_helpers import (
    validate_success, validate_error, api_client,
    admin_headers, tech_headers, make_driver_headers, make_host_operator_headers,
    new_site, new_station, new_port, new_agreement, site_with_port, start_session,
    new_reservation,
)


# --------------------------------------------------------------------------- #
# non_linear_state_machine / port_parallel_axes_occupancy_moves_operational_fixed
# --------------------------------------------------------------------------- #
def test_confirm_moves_occupancy_to_reserved(api):
    """PRD §3.3: "confirming a reservation moves an `AVAILABLE` port to `RESERVED`".

    Design: Difficulty/non_linear_state_machine/port_parallel_axes_occupancy_moves_operational_fixed
    """
    _, _, port = site_with_port(power_kw=100)
    r = new_reservation(port["id"], driver_id="drv-1")
    validate_success(api.confirm_reservation(r["id"], make_driver_headers("drv-1")), 200)
    refreshed = validate_success(api.get_port(port["id"], admin_headers()), 200)
    assert refreshed["occupancy_status"] == "RESERVED"


def test_confirm_leaves_operational_axis_in_service(api):
    """PRD §3.3: "Every port tracks two independent status axes at once. ... These axes
    move independently: a port can be `OUT_OF_SERVICE` while its occupancy is being
    freed, and an `IN_SERVICE` port cycles through occupancy states as sessions and
    reservations come and go."

    Design: Difficulty/non_linear_state_machine/port_parallel_axes_occupancy_moves_operational_fixed
    """
    _, _, port = site_with_port(power_kw=100)
    r = new_reservation(port["id"], driver_id="drv-1")
    validate_success(api.confirm_reservation(r["id"], make_driver_headers("drv-1")), 200)
    refreshed = validate_success(api.get_port(port["id"], admin_headers()), 200)
    assert refreshed["operational_status"] == "IN_SERVICE"


# --------------------------------------------------------------------------- #
# non_linear_state_machine / host_agreement_cyclic_propose_counter_loop
# --------------------------------------------------------------------------- #
def _agreement_after_two_counters(api):
    site = new_site()
    agr = new_agreement(site["id"])
    validate_success(api.propose_agreement(agr["id"], {}, admin_headers()), 200)
    op = make_host_operator_headers(site["id"])
    validate_success(api.counter_agreement(agr["id"], {"counter_revenue_share_pct": 0.12}, op), 200)
    validate_success(api.propose_agreement(agr["id"], {"proposed_revenue_share_pct": 0.13}, admin_headers()), 200)
    return validate_success(api.counter_agreement(agr["id"], {"counter_revenue_share_pct": 0.125}, op), 200)


def test_two_counter_rounds_leave_status_countered(api):
    """PRD §3.1: "The host, acting as the owning `HostOperator`, counters a `PROPOSED`
    agreement into `COUNTERED`, which records the supplied `counter_revenue_share_pct`
    and increments `round_count` by one ... This `PROPOSED` ↔ `COUNTERED` loop may
    repeat any number of rounds."

    Design: Difficulty/non_linear_state_machine/host_agreement_cyclic_propose_counter_loop
    """
    final = _agreement_after_two_counters(api)
    assert final["status"] == "COUNTERED"


def test_two_counter_rounds_set_round_count_to_two(api):
    """PRD §3.1: "The host, acting as the owning `HostOperator`, counters a `PROPOSED`
    agreement into `COUNTERED`, which records the supplied `counter_revenue_share_pct`
    and increments `round_count` by one ... This `PROPOSED` ↔ `COUNTERED` loop may
    repeat any number of rounds."

    Design: Difficulty/non_linear_state_machine/host_agreement_cyclic_propose_counter_loop
    """
    final = _agreement_after_two_counters(api)
    assert final["round_count"] == 2


# --------------------------------------------------------------------------- #
# Corner: state_machines
# --------------------------------------------------------------------------- #
def test_finalize_active_session_returns_invalid_state(api):
    """PRD §3.4: "A `ProgramAdmin` finalizes a `STOPPED` session, stamping
    `unplugged_at` with the current instant and computing the idle penalty."
    PRD §2.10: "... then whether the target resource is in a state from which the
    requested transition is legal (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/finalize_active_session_returns_invalid_state
    """
    _, _, port = site_with_port(power_kw=100)
    s = start_session(port["id"], driver_id="drv-1")  # still ACTIVE, not STOPPED
    res = api.finalize_session(s["id"], admin_headers())
    validate_error(res, "ERR_INVALID_STATE")


def test_resolve_already_resolved_work_order_returns_invalid_state(api):
    """PRD §3.6: "Resolving an `OPEN` work order into `RESOLVED` stamps `resolved_at`
    at the current instant and recomputes `sla_breached`. Legal work-order states are
    `OPEN` and `RESOLVED`."
    PRD §2.10: "... then whether the target resource is in a state from which the
    requested transition is legal (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/resolve_already_resolved_work_order_terminal_lockdown
    """
    site = new_site()
    station = new_station(site["id"])
    port = new_port(station["id"], power_kw=100)
    wo = validate_success(
        api.create_work_order({"port_id": port["id"], "severity": "LOW", "description": "cosmetic"},
                              tech_headers()), 201)
    validate_success(api.resolve_work_order(wo["id"], tech_headers()), 200)
    res = api.resolve_work_order(wo["id"], tech_headers())
    validate_error(res, "ERR_INVALID_STATE")


def test_activate_already_active_agreement_returns_invalid_state(api):
    """PRD §3.1: "Activating from any state other than `PROPOSED` is likewise an
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_agreement_returns_invalid_state
    """
    site = new_site()
    agr = new_agreement(site["id"])
    validate_success(api.propose_agreement(agr["id"], {}, admin_headers()), 200)
    validate_success(api.activate_agreement(agr["id"], admin_headers()), 200)
    res = api.activate_agreement(agr["id"], admin_headers())
    validate_error(res, "ERR_INVALID_STATE")
