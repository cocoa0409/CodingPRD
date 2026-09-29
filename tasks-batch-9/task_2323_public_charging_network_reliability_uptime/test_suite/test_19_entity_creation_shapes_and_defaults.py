"""What creation writes, what it defaults, and what a read gives back."""
from test_helpers import (
    AUDITOR_HEADERS,
    OPERATOR_HEADERS,
    api_client,
    assert_instant_equals,
    create_station,
    is_valid_uuid,
    read_station,
    register_host_site,
    set_clock,
    validate_success,
)


def test_registering_a_host_site_echoes_every_supplied_attribute():
    """Every declared business field comes back exactly as submitted.

    PRD §3.1: registration supplies "a `site_code`, the `host_org_name` under which
    the property owner does business, and the `committed_service_capacity_kw` the
    host contracted to make available", plus the six optional attributes, and "Each
    site also exposes a computed `station_count` ... It starts at zero".

    Design: Corner/entities/create_host_site_echoes_every_declared_field_and_starts_station_count_at_zero
    """
    response = api_client.create_host_site(
        {
            "site_code": "HS-1",
            "host_org_name": "Alder Court Retail",
            "committed_service_capacity_kw": 640.50,
            "agreement_status": "EXECUTED",
            "power_upgrade_status": "IN_PROGRESS",
            "access_hours_mode": "RESTRICTED",
            "access_open_minute": 300,
            "access_close_minute": 1290,
            "parking_enforcement_mode": "SIGNAGE_ONLY",
        },
        OPERATOR_HEADERS,
    )

    data = validate_success(response, 201)

    assert data["site_code"] == "HS-1"
    assert data["host_org_name"] == "Alder Court Retail"
    assert float(data["committed_service_capacity_kw"]) == 640.50
    assert data["agreement_status"] == "EXECUTED"
    assert data["power_upgrade_status"] == "IN_PROGRESS"
    assert data["access_hours_mode"] == "RESTRICTED"
    assert data["access_open_minute"] == 300
    assert data["access_close_minute"] == 1290
    assert data["parking_enforcement_mode"] == "SIGNAGE_ONLY"
    assert data["station_count"] == 0

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]


def test_a_host_site_registration_mints_its_own_identity_and_defaults():
    """The four system fields are server-managed and read the logical clock.

    PRD §2.4: "`id` (string): a server-minted UUID", both timestamps read the
    logical clock, and "`version` (integer): a counter that increments by one on
    every mutation".  PRD §3.1 supplies the six defaults: `agreement_status`
    "defaulting to `DRAFT`", `power_upgrade_status` "defaulting to `REQUESTED`",
    `access_hours_mode` "defaults to `TWENTY_FOUR_SEVEN`", `access_open_minute`
    "defaults to 0", `access_close_minute` "defaults to 1440", and
    `parking_enforcement_mode` "defaulting to `NONE`".

    Design: Corner/entities/create_host_site_generates_id_timestamps_and_initial_version
    """
    set_clock("2026-06-01T00:00:00Z")

    data = validate_success(
        api_client.create_host_site(
            {
                "site_code": "HS-1",
                "host_org_name": "Alder Court Retail",
                "committed_service_capacity_kw": 400.00,
            },
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert is_valid_uuid(data["id"]), f"expected a server-minted UUID, got {data['id']!r}"
    assert_instant_equals(data["created_at"], "2026-06-01T00:00:00Z", "created_at")
    assert_instant_equals(data["updated_at"], "2026-06-01T00:00:00Z", "updated_at")
    assert data["version"] == 1

    assert data["agreement_status"] == "DRAFT"
    assert data["power_upgrade_status"] == "REQUESTED"
    assert data["access_hours_mode"] == "TWENTY_FOUR_SEVEN"
    assert data["access_open_minute"] == 0
    assert data["access_close_minute"] == 1440
    assert data["parking_enforcement_mode"] == "NONE"


def test_reading_a_station_returns_the_stored_row_with_its_zeroed_ledger():
    """A read recomputes nothing; it hands back what creation wrote.

    PRD §3.2: "A new station opens in `DRAFT` with `suspension_source` set to
    `NONE` and `commissioned_at` null", and its derived bank —
    `commissioned_port_count`, `out_of_service_port_count`, `installed_power_kw`,
    `payment_interop_score`, the three-part downtime ledger and
    `refund_liability_cents` — is such that "All of them begin at zero."

    Design: Corner/entities/get_station_by_id_returns_the_stored_row_unchanged
    """
    host_site = register_host_site(
        "HS-1",
        committed_service_capacity_kw=400.00,
        agreement_status="EXECUTED",
        power_upgrade_status="ENERGIZED",
        parking_enforcement_mode="TOWING_ENFORCED",
    )
    station = create_station(
        host_site["id"],
        "ST-1",
        power_class="DCFC_150",
        declared_port_count=2,
        corridor_designated=True,
    )

    response = api_client.get_station(station["id"], AUDITOR_HEADERS)
    data = validate_success(response)

    assert response.json()["response_type"] == "object"
    assert data["host_site_id"] == host_site["id"]
    assert data["station_code"] == "ST-1"
    assert data["power_class"] == "DCFC_150"
    assert data["declared_port_count"] == 2
    assert data["corridor_designated"] is True
    assert data["status"] == "DRAFT"
    assert data["suspension_source"] == "NONE"
    assert data["commissioned_at"] is None
    assert data["commissioned_port_count"] == 0
    assert data["out_of_service_port_count"] == 0
    assert float(data["installed_power_kw"]) == 0
    assert float(data["payment_interop_score"]) == 0
    assert data["gross_downtime_minutes_lifetime"] == 0
    assert data["excluded_downtime_minutes_lifetime"] == 0
    assert data["billable_downtime_minutes_lifetime"] == 0
    assert data["refund_liability_cents"] == 0


def test_installing_a_dispenser_without_the_optional_flags_takes_the_least_capable_values():
    """The four interoperability defaults are materialised, not left null.

    PRD §3.2: "Four interoperability attributes are optional at install time and
    all default to their least-capable value: `contactless_enabled` (false) ...
    `plug_and_charge_enabled` (false) ... `price_display_verified` (false) ... and
    `roaming_ocpi_version` (`NONE`)", and "A newly installed dispenser starts with
    `terminal_certification_status` of `PENDING`, a `service_state` of
    `IN_SERVICE`, a `maintenance_state` of `NONE`, and `retired_at` null".

    Design: Corner/entities/create_charging_port_omitting_optional_flags_applies_declared_defaults
    """
    host_site = register_host_site(
        "HS-1",
        committed_service_capacity_kw=400.00,
        agreement_status="EXECUTED",
        power_upgrade_status="ENERGIZED",
        parking_enforcement_mode="TOWING_ENFORCED",
    )
    station = create_station(host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=1)

    port = validate_success(
        api_client.create_charging_port(
            {
                "station_id": station["id"],
                "connector_type": "CCS1",
                "rated_power_kw": 150.00,
                "dispenser_serial": "DS-1",
                "terminal_model": "PT-4",
            },
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert port["contactless_enabled"] is False
    assert port["plug_and_charge_enabled"] is False
    assert port["price_display_verified"] is False
    assert port["roaming_ocpi_version"] == "NONE"
    assert port["terminal_certification_status"] == "PENDING"
    assert port["service_state"] == "IN_SERVICE"
    assert port["maintenance_state"] == "NONE"
    assert port["retired_at"] is None

    after = read_station(station["id"])
    assert float(after["payment_interop_score"]) == 0.00, (
        "no share is satisfied, so the weighted sum is zero"
    )
    assert after["commissioned_port_count"] == 1
    assert float(after["installed_power_kw"]) == 150.00
    assert after["corridor_designated"] is False, (
        "the station-level optional flag also took its declared default"
    )
