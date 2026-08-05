"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

The test harness resets the database (and the logical clock to its
2026-05-01T00:00:00Z startup default) before every individual test, so every
helper here builds its preconditions from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_host_site_payload, create_host_agreement_payload,
    create_grant_program_payload, create_station_payload, create_port_payload,
    create_session_payload, stop_payload, create_reservation_payload,
    create_rebate_claim_payload,
)
from .test_users import (
    admin_headers, make_admin_headers, tech_headers,
    make_driver_headers, make_host_operator_headers,
)


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(iso: str):
    """Advance the logical clock to `iso` (ProgramAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, admin_headers()))


# --------------------------------------------------------------------------- #
# Basic entity builders
# --------------------------------------------------------------------------- #
def new_site(**overrides) -> dict:
    return get_success_data(
        api_client.create_host_site(create_host_site_payload(**overrides), admin_headers())
    )


def new_grant(**overrides) -> dict:
    return get_success_data(
        api_client.create_grant_program(create_grant_program_payload(**overrides), admin_headers())
    )


def new_station(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_station(create_station_payload(site_id, **overrides), admin_headers())
    )


def new_port(station_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_port(create_port_payload(station_id, **overrides), admin_headers())
    )


def new_agreement(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_host_agreement(create_host_agreement_payload(site_id, **overrides), admin_headers())
    )


def active_agreement(site_id: str, **overrides) -> dict:
    """Create a DRAFT agreement, propose it, and activate it -> ACTIVE."""
    agr = new_agreement(site_id, **overrides)
    get_success_data(api_client.propose_agreement(agr["id"], {}, admin_headers()))
    return get_success_data(api_client.activate_agreement(agr["id"], admin_headers()))


def site_with_port(power_kw: float = 100, **site_overrides):
    """Site + PENDING station + one IN_SERVICE/AVAILABLE port.

    Returns (site, station, port).
    """
    site = new_site(**site_overrides)
    station = new_station(site["id"])
    port = new_port(station["id"], power_kw=power_kw)
    return site, station, port


def get_station_version(station_id: str) -> int:
    return get_success_data(api_client.get_station(station_id, admin_headers()))["version"]


def get_site_version(site_id: str) -> int:
    return get_success_data(api_client.get_host_site(site_id, admin_headers()))["version"]


def get_site(site_id: str) -> dict:
    return get_success_data(api_client.get_host_site(site_id, admin_headers()))


def get_station(station_id: str) -> dict:
    return get_success_data(api_client.get_station(station_id, admin_headers()))


def get_port(port_id: str) -> dict:
    return get_success_data(api_client.get_port(port_id, admin_headers()))


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_session(session_id, admin_headers()))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_rebate_claim(claim_id, admin_headers()))


# --------------------------------------------------------------------------- #
# Charging-session lifecycle builders
# --------------------------------------------------------------------------- #
def start_session(port_id: str, driver_id: str = "drv-1", clock: str = None) -> dict:
    if clock:
        set_clock(clock)
    return get_success_data(
        api_client.create_session(create_session_payload(port_id, driver_id),
                                  make_driver_headers(driver_id))
    )


def stop_session(session_id: str, energy_kwh: float, driver_id: str = "drv-1",
                 clock: str = None) -> dict:
    if clock:
        set_clock(clock)
    return get_success_data(
        api_client.stop_session(session_id, stop_payload(energy_kwh),
                                make_driver_headers(driver_id))
    )


def finalize_session(session_id: str, clock: str = None) -> dict:
    if clock:
        set_clock(clock)
    return get_success_data(api_client.finalize_session(session_id, admin_headers()))


def finalized_session(port_id: str, energy_kwh: float, started: str, stopped: str,
                      unplugged: str, driver_id: str = "drv-1") -> dict:
    """Start -> stop -> finalize a session across the three supplied clock instants."""
    s = start_session(port_id, driver_id, clock=started)
    stop_session(s["id"], energy_kwh, driver_id, clock=stopped)
    return finalize_session(s["id"], clock=unplugged)


# --------------------------------------------------------------------------- #
# Commissioned grant station (grant + site + active agreement + ADA port)
# --------------------------------------------------------------------------- #
def commissioned_grant_station(grant_overrides=None, ada_port=True, power_kw=180):
    """Full chain to a COMMISSIONED grant-enrolled station with one 180kW ADA port.

    Returns dict with keys: site, grant, station, port.
    """
    grant = new_grant(**(grant_overrides or {}))
    site = new_site()
    active_agreement(site["id"])
    station = new_station(site["id"], grant_id=grant["id"], ada_accessible=True)
    port = new_port(station["id"], power_kw=power_kw, ada_accessible=ada_port)
    get_success_data(api_client.commission_station(station["id"], admin_headers()))
    return {"site": site, "grant": grant, "station": station, "port": port}


# --------------------------------------------------------------------------- #
# Two-session OFFPEAK ledger for revenue statements
#   each session: energy 37.625 kWh OFFPEAK, idle 0 -> final_cost 1003
#   gross 2006, per-session processor fee 59
# --------------------------------------------------------------------------- #
def setup_two_offpeak_finalized_sessions():
    """Site (share 0.15, fee 0.029/flat 30) + station + one 100kW port + two
    FINALIZED OFFPEAK sessions of 1003 cents each.

    Returns dict with keys: site_id, station_id, port_id.
    """
    site = new_site(transaction_fee_pct=0.029, transaction_fee_flat_cents=30)
    station = new_station(site["id"])
    port = new_port(station["id"], power_kw=100)
    finalized_session(port["id"], 37.625,
                      started="2026-05-02T02:00:00Z",
                      stopped="2026-05-02T02:30:00Z",
                      unplugged="2026-05-02T02:35:00Z")
    finalized_session(port["id"], 37.625,
                      started="2026-05-03T02:00:00Z",
                      stopped="2026-05-03T02:30:00Z",
                      unplugged="2026-05-03T02:35:00Z")
    return {"site_id": site["id"], "station_id": station["id"], "port_id": port["id"]}


# --------------------------------------------------------------------------- #
# Rebate claim lifecycle builders
# --------------------------------------------------------------------------- #
def setup_draft_grant_claim(reported_uptime_pct=97.0, reported_energy_kwh=1000):
    """Commissioned grant station + a DRAFT rebate claim (period 05-01..06-01).

    Returns dict with keys: env (commissioned_grant_station result), claim_id.
    """
    env = commissioned_grant_station()
    stn_v = get_station_version(env["station"]["id"])
    claim = get_success_data(api_client.create_rebate_claim(
        create_rebate_claim_payload(env["station"]["id"], env["grant"]["id"], stn_v,
                                    reported_uptime_pct=reported_uptime_pct,
                                    reported_energy_kwh=reported_energy_kwh),
        admin_headers()))
    return {"env": env, "claim_id": claim["id"]}


def setup_submitted_claim_with_downtime():
    """Commissioned grant station with a CRITICAL work order (opened 05-10,
    resolved 05-12 -> 2880 min downtime) inside the claim period, then a claim
    created and SUBMITTED (estimated 20000). Ready for the audit trigger.

    Returns dict with keys: env, claim_id.
    """
    set_clock("2026-05-01T00:00:00Z")
    env = commissioned_grant_station()
    set_clock("2026-05-10T00:00:00Z")
    wo = get_success_data(api_client.create_work_order(
        {"port_id": env["port"]["id"], "severity": "CRITICAL", "description": "connector fault"},
        tech_headers()))
    set_clock("2026-05-12T00:00:00Z")
    get_success_data(api_client.resolve_work_order(wo["id"], tech_headers()))
    stn_v = get_station_version(env["station"]["id"])
    claim = get_success_data(api_client.create_rebate_claim(
        create_rebate_claim_payload(env["station"]["id"], env["grant"]["id"], stn_v),
        admin_headers()))
    get_success_data(api_client.submit_rebate_claim(claim["id"], make_admin_headers("admin-1")))
    return {"env": env, "claim_id": claim["id"]}


def setup_audited_compliant_claim(submitter="admin-1"):
    """Commissioned grant station (no downtime) + claim submitted by `submitter`
    then audited -> AUDITED, COMPLIANT. Ready for the approve trigger.

    Returns dict with keys: env, claim_id, submitter.
    """
    env = commissioned_grant_station()
    stn_v = get_station_version(env["station"]["id"])
    claim = get_success_data(api_client.create_rebate_claim(
        create_rebate_claim_payload(env["station"]["id"], env["grant"]["id"], stn_v),
        admin_headers()))
    get_success_data(api_client.submit_rebate_claim(claim["id"], make_admin_headers(submitter)))
    get_success_data(api_client.audit_rebate_claim(claim["id"], make_admin_headers(submitter)))
    return {"env": env, "claim_id": claim["id"], "submitter": submitter}


def setup_grant_station_for_claim():
    """Grant + site + grant station with a 180kW ADA port (NOT commissioned) and
    the station's observed version. For OCC/period-validation claim-create tests.

    Returns dict with keys: site, grant, station, port, station_version.
    """
    grant = new_grant()
    site = new_site()
    station = new_station(site["id"], grant_id=grant["id"], ada_accessible=True)
    port = new_port(station["id"], power_kw=180, ada_accessible=True)
    stn_v = get_station_version(station["id"])
    return {"site": site, "grant": grant, "station": station, "port": port,
            "station_version": stn_v}


# --------------------------------------------------------------------------- #
# Reservation builder
# --------------------------------------------------------------------------- #
def new_reservation(port_id: str, driver_id="drv-1",
                    window_start="2026-05-04T10:00:00Z",
                    window_end="2026-05-04T11:00:00Z") -> dict:
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(port_id, driver_id, window_start, window_end),
            make_driver_headers(driver_id))
    )


def confirmed_reservation(port_id: str, driver_id="drv-1",
                          window_start="2026-05-04T10:00:00Z",
                          window_end="2026-05-04T11:00:00Z") -> dict:
    r = new_reservation(port_id, driver_id, window_start, window_end)
    return get_success_data(api_client.confirm_reservation(r["id"], make_driver_headers(driver_id)))
