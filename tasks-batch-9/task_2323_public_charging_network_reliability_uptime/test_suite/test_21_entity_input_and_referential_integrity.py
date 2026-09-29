"""Shape, existence, cross-reference and uniqueness failures on creation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    SUPPORT_HEADERS,
    ApiErrorId,
    api_client,
    create_station,
    install_charging_port,
    read_host_site,
    read_station,
    register_host_site,
    validate_error,
    validate_paginated,
)


def _commissionable_site(capacity_kw: float = 400.00):
    return register_host_site(
        "HS-1",
        committed_service_capacity_kw=capacity_kw,
        agreement_status="EXECUTED",
        power_upgrade_status="ENERGIZED",
        parking_enforcement_mode="TOWING_ENFORCED",
    )


def test_reading_an_unknown_station_id_yields_the_station_not_found_error():
    """A well-formed but unknown id is a 404 on the error envelope.

    PRD §2.5: "Identifiers embedded in the URL path are resolved left to right, and
    the first path segment that names nothing aborts the request with that
    segment's own 404 error", the station's being `ERR_STATION_NOT_FOUND`.

    Design: Corner/entities/get_station_with_unknown_id_returns_station_not_found
    """
    response = api_client.get_station(NON_EXISTENT_UUID, OPERATOR_HEADERS)

    validate_error(response, ApiErrorId.ERR_STATION_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "the error envelope carries meta.api_request_id too"
    )


def test_creating_a_station_without_a_power_class_is_a_shape_failure():
    """A missing required field is rejected before any row is written.

    PRD §2.11, priority 5: "Request-body shape: every required field present, every
    enum value inside its declared set ... — `ERR_INVALID_REQUEST`."  PRD §3.2 makes
    `power_class` required: a station names "the `power_class` of its dispensers —
    one of `L2_19`, `DCFC_150`, or `DCFC_350`".

    Design: Corner/entities/create_station_missing_required_power_class_rejected
    """
    host_site = _commissionable_site()

    response = api_client.create_station(
        {"host_site_id": host_site["id"], "station_code": "ST-1", "declared_port_count": 1},
        OPERATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    assert read_host_site(host_site["id"])["station_count"] == 0
    rows, _meta = validate_paginated(
        api_client.list_host_site_stations(host_site["id"], OPERATOR_HEADERS)
    )
    assert rows == [], f"no partial station may be created, got {rows}"


def test_a_connector_type_outside_the_declared_set_is_rejected():
    """The enum is closed, so free text does not pass.

    PRD §3.2: a dispenser names "its `connector_type` — one of `CCS1`, `NACS`,
    `CHADEMO`, or `J1772`".  PRD §2.11, priority 5, rejects a value outside a
    declared set with `ERR_INVALID_REQUEST`.

    Design: Corner/entities/create_charging_port_with_invalid_connector_type_enum_rejected
    """
    host_site = _commissionable_site()
    station = create_station(host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=1)

    response = api_client.create_charging_port(
        {
            "station_id": station["id"],
            "connector_type": "TYPE2_MENNEKES",
            "rated_power_kw": 150.00,
            "dispenser_serial": "DS-1",
            "terminal_model": "PT-4",
        },
        OPERATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    after = read_station(station["id"])
    assert after["commissioned_port_count"] == 0
    assert float(after["installed_power_kw"]) == 0
    rows, _meta = validate_paginated(
        api_client.list_station_charging_ports(station["id"], OPERATOR_HEADERS)
    )
    assert rows == []


def test_a_station_under_an_unknown_host_site_is_an_existence_failure():
    """Existence is checked at priority 3, ahead of the shape check at 5.

    PRD §2.5: body foreign keys "are resolved in this declaration order:
    `host_site_id`, `station_id`, `port_id` ..." and the matching failure is
    `ERR_HOST_SITE_NOT_FOUND`, "returned with HTTP 404".

    Design: Corner/entities/create_station_under_unknown_host_site_returns_host_site_not_found
    """
    host_site = register_host_site("HS-1", committed_service_capacity_kw=400.00)

    response = api_client.create_station(
        {
            "host_site_id": NON_EXISTENT_UUID,
            "station_code": "ST-1",
            "power_class": "DCFC_150",
            "declared_port_count": 1,
        },
        OPERATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_HOST_SITE_NOT_FOUND, 404)
    assert read_host_site(host_site["id"])["station_count"] == 0, (
        "the real site was never named and must be untouched"
    )


def test_a_complaint_naming_a_dispenser_of_another_station_is_rejected():
    """Both foreign keys resolve, and they still have to agree.

    PRD §3.9: "Three checks guard intake.  The dispenser must belong to the station
    named — otherwise `ERR_COMPLAINT_PORT_MISMATCH`."

    Design: Corner/entities/create_complaint_with_port_belonging_to_another_station_rejected
    """
    host_site = _commissionable_site(capacity_kw=800.00)
    first = create_station(host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=1)
    second = create_station(host_site["id"], "ST-2", power_class="DCFC_150", declared_port_count=1)
    install_charging_port(first["id"], "DS-1", connector_type="CCS1", terminal_model="PT-4")
    foreign_port = install_charging_port(
        second["id"], "DS-2", connector_type="CCS1", terminal_model="PT-4"
    )

    response = api_client.create_customer_complaint(
        {
            "station_id": first["id"],
            "port_id": foreign_port["id"],
            "complaint_type": "PAYMENT_DECLINED",
            "session_started_at": "2026-07-31T10:00:00Z",
            "session_ended_at": "2026-07-31T10:20:00Z",
            "session_energy_kwh": 5.000,
            "session_price_per_kwh_cents": 40,
            "session_charged_cents": 200,
        },
        SUPPORT_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_COMPLAINT_PORT_MISMATCH, 409)

    by_station, _meta = validate_paginated(
        api_client.list_customer_complaints(SUPPORT_HEADERS, params={"station_id": first["id"]})
    )
    assert by_station == []
    by_port, _meta = validate_paginated(
        api_client.list_customer_complaints(SUPPORT_HEADERS, params={"port_id": foreign_port["id"]})
    )
    assert by_port == []


def test_a_dispenser_serial_is_unique_across_the_whole_network():
    """Uniqueness is global, not scoped to the station.

    PRD §3.2: a dispenser carries "a globally unique `dispenser_serial` for the
    cabinet (a collision yields `ERR_DISPENSER_SERIAL_DUPLICATE`)".

    Design: Corner/entities/duplicate_dispenser_serial_across_two_stations_rejected
    """
    host_site = _commissionable_site(capacity_kw=800.00)
    first = create_station(host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=1)
    second = create_station(host_site["id"], "ST-2", power_class="DCFC_150", declared_port_count=1)
    original = install_charging_port(
        first["id"], "DS-1", connector_type="CCS1", terminal_model="PT-4"
    )

    response = api_client.create_charging_port(
        {
            "station_id": second["id"],
            "connector_type": "NACS",
            "rated_power_kw": 150.00,
            "dispenser_serial": "DS-1",
            "terminal_model": "PT-9",
        },
        OPERATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_DISPENSER_SERIAL_DUPLICATE, 409)

    after = read_station(second["id"])
    assert after["commissioned_port_count"] == 0
    assert float(after["installed_power_kw"]) == 0

    kept, _meta = validate_paginated(
        api_client.list_station_charging_ports(first["id"], OPERATOR_HEADERS)
    )
    assert len(kept) == 1
    assert kept[0]["id"] == original["id"]
