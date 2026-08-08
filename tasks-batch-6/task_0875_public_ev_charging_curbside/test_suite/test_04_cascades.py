"""Transitive cascades: critical work order and agreement termination.

Difficulty: transitive_cascade/{critical_work_order...,agreement_terminate...}.
"""
from test_helpers import (
    validate_success, api_client, admin_headers, tech_headers,
    new_site, new_station, new_port, active_agreement, site_with_port,
    start_session, get_port, get_session, get_station,
)


# --------------------------------------------------------------------------- #
# transitive_cascade / critical_work_order_cascade_port_session_occupancy
# --------------------------------------------------------------------------- #
def _critical_wo_over_active_session(api):
    _, _, port = site_with_port(power_kw=180)
    s = start_session(port["id"], driver_id="drv-1", clock="2026-05-05T09:00:00Z")
    validate_success(
        api.create_work_order({"port_id": port["id"], "severity": "CRITICAL", "description": "arc fault"},
                              tech_headers()), 201)
    return port["id"], s["id"]


def test_critical_work_order_drives_port_oos_and_aborts_session(api):
    """PRD §3.6: "Opening a `CRITICAL` work order triggers a three-level cascade: the
    port's `operational_status` is driven to `OUT_OF_SERVICE`, its `ACTIVE` charging
    session is driven to `ABORTED`, and that abort frees the port's `occupancy_status`
    to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/critical_work_order_cascade_port_session_occupancy
    """
    port_id, session_id = _critical_wo_over_active_session(api)
    assert get_port(port_id)["operational_status"] == "OUT_OF_SERVICE"
    assert get_session(session_id)["status"] == "ABORTED"


def test_critical_work_order_zeroes_cost_and_frees_occupancy(api):
    """PRD §3.6: "Opening a `CRITICAL` work order triggers a three-level cascade: the
    port's `operational_status` is driven to `OUT_OF_SERVICE`, its `ACTIVE` charging
    session is driven to `ABORTED`, and that abort frees the port's `occupancy_status`
    to `AVAILABLE`."
    PRD §3.4: "its `ACTIVE` session is driven to the terminal `ABORTED` state with
    `final_cost_cents` set to 0 and no revenue posted".

    Design: Difficulty/transitive_cascade/critical_work_order_cascade_port_session_occupancy
    """
    port_id, session_id = _critical_wo_over_active_session(api)
    assert get_session(session_id)["final_cost_cents"] == 0
    assert get_port(port_id)["occupancy_status"] == "AVAILABLE"


# --------------------------------------------------------------------------- #
# transitive_cascade / agreement_terminate_cascade_station_port_session
# --------------------------------------------------------------------------- #
def _terminated_agreement_over_commissioned_station(api):
    site = new_site()
    agr = active_agreement(site["id"])
    station = new_station(site["id"])
    port = new_port(station["id"], power_kw=180)
    validate_success(api.commission_station(station["id"], admin_headers()), 200)
    s = start_session(port["id"], driver_id="drv-1", clock="2026-05-05T09:00:00Z")
    validate_success(api.terminate_agreement(agr["id"], admin_headers()), 200)
    return station["id"], port["id"], s["id"]


def test_terminate_decommissions_station_and_oos_ports(api):
    """PRD §3.1: "Terminating an `ACTIVE` agreement moves it to the terminal
    `TERMINATED` state and triggers a three-level cascade: every `Station` for that
    `site_id` whose `operational_status` is `PENDING`, `COMMISSIONED`, or `SUSPENDED`
    is driven to `DECOMMISSIONED`; each such station's ports whose `operational_status`
    is `IN_SERVICE` are driven to `OUT_OF_SERVICE` with `oos_opened_at` set to the
    current clock instant ..."

    Design: Difficulty/transitive_cascade/agreement_terminate_cascade_station_port_session
    """
    station_id, port_id, _ = _terminated_agreement_over_commissioned_station(api)
    assert get_station(station_id)["operational_status"] == "DECOMMISSIONED"
    assert get_port(port_id)["operational_status"] == "OUT_OF_SERVICE"


def test_terminate_aborts_active_session_on_the_station(api):
    """PRD §3.1: "... and each such port's `ACTIVE` charging session is driven to
    `ABORTED` with its `final_cost_cents` set to 0 and no revenue posted."

    Design: Difficulty/transitive_cascade/agreement_terminate_cascade_station_port_session
    """
    _, _, session_id = _terminated_agreement_over_commissioned_station(api)
    assert get_session(session_id)["status"] == "ABORTED"
