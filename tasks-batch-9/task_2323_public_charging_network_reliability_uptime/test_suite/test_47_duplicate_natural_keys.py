"""All four natural keys are global, and existence still outranks them."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    assert_version_unchanged,
    create_charging_port_payload,
    create_host_site_payload,
    create_spare_part_payload,
    create_station,
    create_station_payload,
    install_charging_port,
    read_host_site,
    read_spare_part,
    read_station,
    register_host_site,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_reusing_a_code_under_a_different_parent_is_still_a_collision():
    """Scoping any of these keys to its parent would let ST-1 exist twice.

    PRD §3.1: "The `site_code` must be non-empty and globally unique, compared
    case-sensitively; a collision is rejected with `ERR_SITE_CODE_DUPLICATE`."  PRD
    §3.2 on the station: "a globally unique `station_code` (a collision yields
    `ERR_STATION_CODE_DUPLICATE`)"; and on the dispenser: "a globally unique
    `dispenser_serial` for the cabinet (a collision yields
    `ERR_DISPENSER_SERIAL_DUPLICATE`)".  PRD §3.6 on the depot: "a globally unique
    manufacturer `part_number` (a collision yields `ERR_PART_NUMBER_DUPLICATE`)".
    PRD §2.11 orders "Existence of every identifier" third and "Natural-key
    uniqueness" sixth.

    Design: Corner/errors/duplicate_natural_keys_are_rejected_after_existence_but_before_state
    """
    first_site = register_host_site("HS-1", committed_service_capacity_kw=400.00)
    second_site = register_host_site("HS-2", committed_service_capacity_kw=250.00)
    first_station = create_station(first_site["id"], "ST-1", declared_port_count=1)
    second_station = create_station(
        second_site["id"], "ST-9", power_class="L2_19", declared_port_count=1
    )
    install_charging_port(first_station["id"], "DS-1", terminal_model="PT-4")
    part = validate_success(
        api_client.create_spare_part(
            create_spare_part_payload("SP-1", part_class="DISPENSER", lead_time_days=3),
            OPERATOR_HEADERS,
        ),
        201,
    )

    site_version = read_host_site(first_site["id"])["version"]
    station_version = read_station(second_station["id"])["version"]
    part_version = read_spare_part(part["id"])["version"]

    validate_error(
        api_client.create_host_site(
            create_host_site_payload("HS-1", committed_service_capacity_kw=120.00),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_SITE_CODE_DUPLICATE,
        409,
    )
    validate_error(
        api_client.create_station(
            create_station_payload(second_site["id"], "ST-1", declared_port_count=1),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_STATION_CODE_DUPLICATE,
        409,
    )
    validate_error(
        api_client.create_charging_port(
            create_charging_port_payload(
                second_station["id"], "DS-1", rated_power_kw=19.20, terminal_model="PT-4"
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_DISPENSER_SERIAL_DUPLICATE,
        409,
    )
    validate_error(
        api_client.create_spare_part(
            create_spare_part_payload("SP-1", part_class="POWER_MODULE", lead_time_days=10),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_PART_NUMBER_DUPLICATE,
        409,
    )
    validate_error(
        api_client.create_station(
            create_station_payload(NON_EXISTENT_UUID, "ST-1", declared_port_count=1),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_HOST_SITE_NOT_FOUND,
        404,
    )

    _sites, site_meta = validate_paginated(api_client.list_host_sites(OPERATOR_HEADERS))
    assert site_meta["total_count"] == 2

    _stations, station_meta = validate_paginated(
        api_client.list_host_site_stations(second_site["id"], OPERATOR_HEADERS)
    )
    assert station_meta["total_count"] == 1, "the duplicate station never landed"

    _ports, port_meta = validate_paginated(
        api_client.list_station_charging_ports(second_station["id"], OPERATOR_HEADERS)
    )
    assert port_meta["total_count"] == 0, "the duplicate dispenser never landed"

    _parts, part_meta = validate_paginated(api_client.list_spare_parts(OPERATOR_HEADERS))
    assert part_meta["total_count"] == 1

    assert_version_unchanged(read_host_site(first_site["id"]), site_version, "HostSite")
    assert_version_unchanged(read_station(second_station["id"]), station_version, "Station")
    assert_version_unchanged(read_spare_part(part["id"]), part_version, "SparePart")
