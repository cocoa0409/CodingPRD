"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SITE_NAME": "Test Curb Site",
    "ADDRESS": "1 Test Ave",
    "STATE_CODE": "CA",
    "REVENUE_SHARE_PCT": 0.15,
    "TRANSACTION_FEE_PCT": 0.029,
    "TRANSACTION_FEE_FLAT_CENTS": 30,
    "TERM_START": "2026-05-01T00:00:00Z",
    "TERM_END": "2027-05-01T00:00:00Z",
    "GRANT_NAME": "NEVI",
    "PROGRAM_CODE": "NEVI",
    "MIN_UPTIME_PCT": 97.0,
    "MIN_PORTS": 1,
    "MIN_POWER_KW": 150,
    "REIMBURSEMENT_RATE": 20,
    "REIMBURSEMENT_CAP": 5000000,
    "CONNECTOR_TYPE": "CCS2",
    "POWER_KW": 100,
}


def create_host_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "address": DEFAULTS["ADDRESS"],
        "state_code": DEFAULTS["STATE_CODE"],
        "revenue_share_pct": DEFAULTS["REVENUE_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_host_agreement_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
        "proposed_revenue_share_pct": DEFAULTS["REVENUE_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_grant_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GRANT_NAME"],
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "min_uptime_pct": DEFAULTS["MIN_UPTIME_PCT"],
        "min_ports": DEFAULTS["MIN_PORTS"],
        "min_power_kw": DEFAULTS["MIN_POWER_KW"],
        "reimbursement_rate_cents_per_kwh": DEFAULTS["REIMBURSEMENT_RATE"],
        "reimbursement_cap_cents": DEFAULTS["REIMBURSEMENT_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "name": "S1",
    }
    defaults.update(overrides)
    return defaults


def create_port_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "connector_type": DEFAULTS["CONNECTOR_TYPE"],
        "power_kw": DEFAULTS["POWER_KW"],
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(port_id: str, driver_id: str = "drv-1", **overrides) -> dict:
    defaults = {"port_id": port_id, "driver_id": driver_id}
    defaults.update(overrides)
    return defaults


def stop_payload(energy_kwh: float, **overrides) -> dict:
    defaults = {"energy_kwh": energy_kwh}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(port_id: str, driver_id: str = "drv-1",
                               window_start: str = "2026-05-04T10:00:00Z",
                               window_end: str = "2026-05-04T11:00:00Z",
                               **overrides) -> dict:
    defaults = {
        "port_id": port_id,
        "driver_id": driver_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(station_id: str,
                                      window_start: str,
                                      window_end: str,
                                      reason: str = "inspection",
                                      **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "window_start": window_start,
        "window_end": window_end,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(port_id: str, severity: str = "LOW",
                              description: str = "fault", **overrides) -> dict:
    defaults = {"port_id": port_id, "severity": severity, "description": description}
    defaults.update(overrides)
    return defaults


def create_rebate_claim_payload(station_id: str, grant_id: str,
                                expected_station_version: int,
                                period_start: str = "2026-05-01T00:00:00Z",
                                period_end: str = "2026-06-01T00:00:00Z",
                                reported_energy_kwh: float = 1000,
                                reported_uptime_pct: float = 97.0,
                                **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "grant_id": grant_id,
        "period_start": period_start,
        "period_end": period_end,
        "reported_energy_kwh": reported_energy_kwh,
        "reported_uptime_pct": reported_uptime_pct,
        "expected_station_version": expected_station_version,
    }
    defaults.update(overrides)
    return defaults


def create_revenue_statement_payload(site_id: str, expected_site_version: int,
                                     basis: str = "GROSS",
                                     period_start: str = "2026-05-01T00:00:00Z",
                                     period_end: str = "2026-06-01T00:00:00Z",
                                     **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults
