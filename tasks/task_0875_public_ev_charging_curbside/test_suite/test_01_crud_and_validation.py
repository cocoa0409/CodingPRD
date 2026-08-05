"""CRUD, computed defaults, not-found, and input-validation checks.

Each test translates exactly one queue-B (corner-design) instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, admin_headers, make_driver_headers,
    create_host_site_payload, create_station_payload,
    create_reservation_payload, create_session_payload, stop_payload,
    create_rebate_claim_payload,
    assert_host_site,
    new_site, new_station, site_with_port, start_session, setup_grant_station_for_claim,
    NON_EXISTENT_UUID,
)


def test_create_host_site_returns_201_with_computed_defaults(api):
    """PRD §3.1: "On creation the site's running ledger `lifetime_gross_revenue_cents`
    starts at 0, its derived `station_count` starts at 0, and its `version` starts at 1."

    Design: Corner/entities/create_host_site_returns_201_with_computed_defaults
    """
    res = api.create_host_site(create_host_site_payload(name="Curb Z"), admin_headers())
    site = validate_success(res, 201)
    assert_host_site(site)
    assert site["lifetime_gross_revenue_cents"] == 0
    assert site["station_count"] == 0
    assert site["version"] == 1


def test_get_station_not_found_returns_404(api):
    """PRD §2.8: "Each entity type has its own not-found code — for example
    `ERR_STATION_NOT_FOUND` ... — and the code raised names the resource type of
    the missing identifier."

    Design: Corner/entities/get_station_not_found_returns_404
    """
    res = api.get_station(NON_EXISTENT_UUID, admin_headers())
    validate_error(res, "ERR_STATION_NOT_FOUND")


def test_create_station_missing_required_name_returns_validation(api):
    """PRD §2.8: "Missing required fields, wrong types, and invalid enum values are
    rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_station_missing_required_name_returns_validation
    """
    site = new_site()
    payload = {"site_id": site["id"]}  # 'name' omitted
    res = api.create_station(payload, admin_headers())
    validate_error(res, "ERR_VALIDATION")


def test_host_site_station_count_reconciles_after_two_stations(api):
    """PRD §3.1: "On creation the site's running ledger `lifetime_gross_revenue_cents`
    starts at 0, its derived `station_count` starts at 0, and its `version` starts at 1."
    PRD §2.9: "A station's `station_count` on its host site, a station's `total_ports`
    and `available_ports`, and a host site's `lifetime_gross_revenue_cents` are all
    derived quantities that the system keeps current as the rows beneath them change."

    Design: Corner/entities/host_site_station_count_reconciles_after_two_stations
    """
    site = new_site()
    new_station(site["id"], name="S1")
    new_station(site["id"], name="S2")
    refreshed = validate_success(api.get_host_site(site["id"], admin_headers()), 200)
    assert refreshed["station_count"] == 2


def test_reservation_end_not_after_start_returns_invalid_window(api):
    """PRD §3.5: "A `Driver` creates a **reservation** by supplying a `port_id`, a
    `driver_id`, a `window_start`, and a `window_end`, where `window_end` must be
    later than `window_start` (else `ERR_INVALID_WINDOW`)."

    Design: Corner/validations/reservation_end_not_after_start_returns_invalid_window
    """
    _, _, port = site_with_port(power_kw=100)
    payload = create_reservation_payload(port["id"], driver_id="drv-1",
                                         window_start="2026-05-04T11:00:00Z",
                                         window_end="2026-05-04T10:00:00Z")
    res = api.create_reservation(payload, make_driver_headers("drv-1"))
    validate_error(res, "ERR_INVALID_WINDOW")


def test_rebate_claim_end_not_after_start_returns_invalid_period(api):
    """PRD §3.7: "A `ProgramAdmin` creates one against a `station_id` and `grant_id`
    with a `period_start`, a `period_end` (which must exceed `period_start`, else
    `ERR_INVALID_PERIOD`) ..."

    Design: Corner/validations/rebate_claim_end_not_after_start_returns_invalid_period
    """
    env = setup_grant_station_for_claim()
    payload = create_rebate_claim_payload(
        env["station"]["id"], env["grant"]["id"], env["station_version"],
        period_start="2026-06-01T00:00:00Z", period_end="2026-05-01T00:00:00Z")
    res = api.create_rebate_claim(payload, admin_headers())
    validate_error(res, "ERR_INVALID_PERIOD")


def test_stop_session_with_zero_energy_returns_energy_invalid(api):
    """PRD §3.4: "The owning driver stops an `ACTIVE` session, reporting delivered
    `energy_kwh`, which must be greater than 0 (else `ERR_ENERGY_INVALID`) ..."

    Design: Corner/validations/stop_session_with_zero_energy_returns_energy_invalid
    """
    _, _, port = site_with_port(power_kw=100)
    s = start_session(port["id"], driver_id="drv-1")
    res = api.stop_session(s["id"], stop_payload(0), make_driver_headers("drv-1"))
    validate_error(res, "ERR_ENERGY_INVALID")


def test_list_ports_by_station_reverse_lookup(api):
    """PRD §2.8: "The only nested read path in the system lists a station's ports."

    Design: Corner/endpoints/list_ports_by_station_reverse_lookup
    """
    site = new_site()
    station = new_station(site["id"])
    api_client.create_port({"station_id": station["id"], "connector_type": "CCS2", "power_kw": 100}, admin_headers())
    api_client.create_port({"station_id": station["id"], "connector_type": "NACS", "power_kw": 180}, admin_headers())
    data, meta = validate_paginated(api.list_station_ports(station["id"], admin_headers()))
    assert len(data) == 2
    assert meta["total_count"] == 2
