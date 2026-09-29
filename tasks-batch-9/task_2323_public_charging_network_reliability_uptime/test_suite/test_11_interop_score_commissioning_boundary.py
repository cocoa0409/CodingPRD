"""The inclusive 90.00 interoperability boundary, pinned from both sides."""
from test_helpers import (
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    certify_terminal,
    create_station,
    install_charging_port,
    move_station_status,
    read_station,
    setup_station,
    validate_error,
    validate_success,
)

ALL_FLAGS_AND_COMPLIANT_ROAMING = {
    "contactless_enabled": True,
    "plug_and_charge_enabled": True,
    "price_display_verified": True,
    "roaming_ocpi_version": "V2_2_1",
}


def _boundary_pair():
    """Two stations identical apart from one certified payment terminal: A scores
    exactly 90.00, B scores 80.00."""
    scenario = setup_station(
        clock="2026-06-03T09:00:00Z",
        site_code="HS-BD-1",
        station_code="ST-BD-A",
        committed_service_capacity_kw=1600.00,
        power_class="DCFC_150",
        declared_port_count=2,
        stop_at="COMMISSIONING",
        ports=[
            dict(
                ALL_FLAGS_AND_COMPLIANT_ROAMING,
                dispenser_serial="DS-BD-A1",
                connector_type="CCS1",
                certify="CERTIFIED",
            ),
            dict(
                ALL_FLAGS_AND_COMPLIANT_ROAMING,
                dispenser_serial="DS-BD-A2",
                connector_type="NACS",
            ),
        ],
    )

    station_b = create_station(
        scenario["host_site"]["id"],
        station_code="ST-BD-B",
        power_class="DCFC_150",
        declared_port_count=2,
    )
    for serial, connector in (("DS-BD-B1", "CCS1"), ("DS-BD-B2", "NACS")):
        install_charging_port(
            station_b["id"],
            serial,
            connector_type=connector,
            **ALL_FLAGS_AND_COMPLIANT_ROAMING,
        )
    station_b = move_station_status(station_b["id"], "COMMISSIONING")

    return scenario["station"], station_b


def test_commission_accepts_a_station_scoring_exactly_ninety():
    """The comparison is inclusive, so the boundary itself commissions.

    PRD §3.3: "Finally, `payment_interop_score` must be at least 90.00. The
    boundary itself passes: a station scoring exactly 90.00 commissions."

    Design: Difficulty/boundary_precision_check/commission_accepts_interop_score_exactly_at_ninety_and_rejects_eighty
    """
    station_a, _station_b = _boundary_pair()

    assert float(read_station(station_a["id"])["payment_interop_score"]) == 90.00, (
        "one of two dispensers is certified and roaming-compliant, so the score is "
        "100 * (0.40 + 0.20 + 0.20 + 0.20 * 1/2)"
    )

    data = validate_success(api_client.commission_station(station_a["id"], OPERATOR_HEADERS))

    assert data["status"] == "OPERATIONAL"
    assert_instant_equals(data["commissioned_at"], "2026-06-03T09:00:00Z", "commissioned_at")


def test_commission_rejects_a_station_scoring_eighty():
    """One certification lower and the same ladder rejects the station.

    PRD §3.3: "Anything below yields `ERR_INTEROP_SCORE_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/commission_accepts_interop_score_exactly_at_ninety_and_rejects_eighty
    """
    _station_a, station_b = _boundary_pair()

    assert float(read_station(station_b["id"])["payment_interop_score"]) == 80.00, (
        "neither dispenser is certified, so the roaming share is zero"
    )

    response = api_client.commission_station(station_b["id"], OPERATOR_HEADERS)

    validate_error(response, ApiErrorId.ERR_INTEROP_SCORE_BELOW_THRESHOLD, 422)

    station = read_station(station_b["id"])
    assert station["status"] == "COMMISSIONING", "the rejected station must not advance"
    assert station["commissioned_at"] is None
