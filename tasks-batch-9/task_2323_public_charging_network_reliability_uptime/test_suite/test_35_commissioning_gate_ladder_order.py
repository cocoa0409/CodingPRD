"""The commissioning ladder reports the most fundamental unmet gate, in order."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    certify_terminal,
    create_station,
    install_charging_port,
    make_host_site_manager_headers,
    move_station_status,
    read_host_site,
    read_station,
    register_host_site,
    set_clock,
    setup_station,
    validate_error,
    validate_success,
)


def test_each_repaired_gate_reveals_exactly_the_next_one_in_the_declared_order():
    """Three gates are unmet at once, yet only the earliest one may be reported.

    PRD §3.3: "Then six gates are evaluated **in this order**, each with its own
    rejection", of which the second is "The host site's `power_upgrade_status`
    must be either `NOT_REQUIRED` or `ENERGIZED`; a site still at `REQUESTED` or
    `IN_PROGRESS` yields `ERR_POWER_UPGRADE_NOT_ENERGIZED`", the fourth "The
    station's non-retired dispenser count must be at least as large as its
    `declared_port_count`; a shortfall yields `ERR_PORT_COUNT_BELOW_DECLARED`",
    and the fifth "The station's `installed_power_kw` must not exceed the host
    site's `committed_service_capacity_kw`; exceeding it yields
    `ERR_SITE_CAPACITY_EXCEEDED`."  PRD §3.3 on the sixth: "Ordering the
    interoperability threshold last is deliberate — a station missing its
    paperwork should hear about the paperwork, not about its terminals.  When all
    six gates clear, the station stamps `commissioned_at` from the logical clock
    (this happens the first time it reaches `OPERATIONAL`; before that the field
    is null), sets `suspension_source` to `NONE`, and increments its `version`."

    Design: Corner/validations/commissioning_gates_surface_one_at_a_time_in_their_declared_order
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=100.00,
        power_class="DCFC_150",
        declared_port_count=2,
        host_site_overrides={"power_upgrade_status": "REQUESTED"},
        ports=[dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-1")],
        stop_at="COMMISSIONING",
    )
    site_id = scenario["host_site"]["id"]
    station_id = scenario["station"]["id"]

    first = read_station(station_id)
    assert first["status"] == "COMMISSIONING"
    assert float(first["payment_interop_score"]) == 100.00, (
        "the interoperability gate can never be the one that fires here"
    )

    validate_error(
        api_client.commission_station(station_id, OPERATOR_HEADERS),
        ApiErrorId.ERR_POWER_UPGRADE_NOT_ENERGIZED,
        422,
    )
    assert read_station(station_id)["status"] == "COMMISSIONING", "no partial commissioning"

    validate_success(
        api_client.update_host_site(
            site_id, {"power_upgrade_status": "ENERGIZED"}, OPERATOR_HEADERS
        )
    )

    validate_error(
        api_client.commission_station(station_id, OPERATOR_HEADERS),
        ApiErrorId.ERR_PORT_COUNT_BELOW_DECLARED,
        422,
    )
    assert read_station(station_id)["status"] == "COMMISSIONING"

    second_port = install_charging_port(
        station_id,
        "DS-2",
        connector_type="NACS",
        rated_power_kw=150.00,
        terminal_model="PT-9",
        contactless_enabled=True,
        plug_and_charge_enabled=True,
        price_display_verified=True,
        roaming_ocpi_version="V2_2_1",
    )
    certify_terminal(second_port["id"], "CERTIFIED")

    with_both_ports = read_station(station_id)
    assert with_both_ports["commissioned_port_count"] == 2
    assert float(with_both_ports["installed_power_kw"]) == 300.00
    assert float(with_both_ports["payment_interop_score"]) == 100.00

    validate_error(
        api_client.commission_station(station_id, OPERATOR_HEADERS),
        ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED,
        422,
    )
    assert read_station(station_id)["status"] == "COMMISSIONING"
    assert read_station(station_id)["commissioned_at"] is None

    validate_success(
        api_client.update_host_site(
            site_id, {"committed_service_capacity_kw": 400.00}, OPERATOR_HEADERS
        )
    )

    data = validate_success(api_client.commission_station(station_id, OPERATOR_HEADERS))

    assert data["status"] == "OPERATIONAL"
    assert data["suspension_source"] == "NONE"
    assert_instant_equals(data["commissioned_at"], "2026-08-01T00:00:00Z", "commissioned_at")
    assert float(data["payment_interop_score"]) == 100.00


def test_an_unconfigured_parking_enforcement_mode_blocks_the_third_gate():
    """The gate tests inequality against NONE, not a minimum enforcement strength.

    PRD §3.1: "`parking_enforcement_mode` describes the contracted level of
    anti-blocking enforcement and is one of `NONE`, `SIGNAGE_ONLY`, or
    `TOWING_ENFORCED`, defaulting to `NONE`."  PRD §3.3, gate 3: "The host site's
    `parking_enforcement_mode` must be `SIGNAGE_ONLY` or `TOWING_ENFORCED`; a
    site at `NONE` yields `ERR_PARKING_ENFORCEMENT_REQUIRED`."  PRD §3.1 on who
    may repair it: an amendment "is available to a `NetworkOperator` for any site
    and to a `HostSiteManager` only for the site whose `id` matches their
    `X-User-ID`".

    Design: Corner/validations/commissioning_requires_parking_enforcement_to_be_configured
    """
    set_clock("2026-08-01T00:00:00Z")
    host_site = register_host_site(
        "HS-1",
        committed_service_capacity_kw=400.00,
        agreement_status="EXECUTED",
        power_upgrade_status="ENERGIZED",
    )
    station = create_station(
        host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=1
    )
    port = install_charging_port(
        station["id"],
        "DS-1",
        rated_power_kw=150.00,
        terminal_model="PT-9",
        contactless_enabled=True,
        plug_and_charge_enabled=True,
        price_display_verified=True,
        roaming_ocpi_version="V2_2_1",
    )
    certify_terminal(port["id"], "CERTIFIED")
    move_station_status(station["id"], "COMMISSIONING")

    assert read_host_site(host_site["id"])["parking_enforcement_mode"] == "NONE", (
        "the declared default"
    )

    validate_error(
        api_client.commission_station(station["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_PARKING_ENFORCEMENT_REQUIRED,
        422,
    )
    assert read_station(station["id"])["status"] == "COMMISSIONING"

    amended = validate_success(
        api_client.update_host_site(
            host_site["id"],
            {"parking_enforcement_mode": "SIGNAGE_ONLY"},
            make_host_site_manager_headers(host_site["id"]),
        )
    )
    assert amended["parking_enforcement_mode"] == "SIGNAGE_ONLY", (
        "the weakest non-NONE value is enough"
    )

    data = validate_success(api_client.commission_station(station["id"], OPERATOR_HEADERS))
    assert data["status"] == "OPERATIONAL"
