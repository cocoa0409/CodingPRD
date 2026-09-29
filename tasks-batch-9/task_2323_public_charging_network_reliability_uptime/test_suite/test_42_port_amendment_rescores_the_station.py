"""Amending a dispenser's interoperability flags touches nothing else."""
from test_helpers import (
    OPERATOR_HEADERS,
    api_client,
    assert_two_decimals,
    assert_version_advanced_by,
    read_charging_port,
    read_station,
    setup_station,
    validate_success,
)


def test_enabling_contactless_lifts_the_score_while_a_roaming_upgrade_alone_does_not():
    """The roaming share needs a certified terminal as well as a modern version.

    PRD §3.2: "The four interoperability attributes remain amendable afterwards by
    a `NetworkOperator` — an amendment may carry any subset of
    `contactless_enabled`, `plug_and_charge_enabled`, `price_display_verified`, and
    `roaming_ocpi_version` — and each amendment recomputes the station's
    `payment_interop_score` and increments the dispenser's `version`."  PRD §3.2 on
    the shares: "the contactless share counts dispensers whose
    `contactless_enabled` is true ... and the roaming share counts dispensers that
    are both certified — `terminal_certification_status` equal to `CERTIFIED` — and
    publishing at `V2_2_1` or `V2_3_0` ... The score is one hundred multiplied by
    the weighted sum of those four shares, weighting contactless at forty percent
    and each of Plug-and-Charge, price display and roaming at twenty percent."

    Design: Corner/endpoints/patching_port_interoperability_flags_rescores_the_station_only
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=2,
        ports=[
            {
                "dispenser_serial": "DS-1",
                "terminal_model": "PT-9",
                "contactless_enabled": True,
                "plug_and_charge_enabled": True,
                "price_display_verified": True,
                "roaming_ocpi_version": "V2_2_1",
                "certify": "CERTIFIED",
            },
            {
                "dispenser_serial": "DS-2",
                "connector_type": "NACS",
                "terminal_model": "PT-3",
                "plug_and_charge_enabled": True,
                "price_display_verified": True,
                "roaming_ocpi_version": "V2_1_1",
            },
        ],
        stop_at="DRAFT",
    )
    station_id = scenario["station"]["id"]
    weaker_port = scenario["ports"][1]

    before = read_station(station_id)
    assert float(before["payment_interop_score"]) == 70.00, (
        "contactless 1/2 at 40%, plug-and-charge 2/2, display 2/2, roaming 1/2 at 20%"
    )
    assert_two_decimals(before["payment_interop_score"], "payment_interop_score")
    assert read_charging_port(weaker_port["id"])["terminal_certification_status"] == "PENDING"

    amended = validate_success(
        api_client.update_charging_port(
            weaker_port["id"], {"contactless_enabled": True}, OPERATOR_HEADERS
        )
    )

    assert amended["contactless_enabled"] is True
    assert_version_advanced_by(amended, weaker_port["version"], 1, "ChargingPort")
    assert amended["service_state"] == "IN_SERVICE", "an amendment carries only the four flags"
    assert amended["maintenance_state"] == "NONE"
    assert amended["terminal_certification_status"] == "PENDING"
    assert float(read_station(station_id)["payment_interop_score"]) == 90.00

    upgraded = validate_success(
        api_client.update_charging_port(
            weaker_port["id"], {"roaming_ocpi_version": "V2_2_1"}, OPERATOR_HEADERS
        )
    )

    assert upgraded["roaming_ocpi_version"] == "V2_2_1"
    assert upgraded["terminal_certification_status"] == "PENDING", (
        "an operator cannot certify a terminal by amending it"
    )

    after = read_station(station_id)
    assert float(after["payment_interop_score"]) == 90.00, (
        "roaming compliance also requires a CERTIFIED terminal"
    )
    assert after["commissioned_port_count"] == 2
    assert float(after["installed_power_kw"]) == 300.00
