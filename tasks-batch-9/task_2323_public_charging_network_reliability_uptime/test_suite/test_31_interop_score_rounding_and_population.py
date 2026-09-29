"""The interoperability score: one terminal rounding, over the scored population."""
from test_helpers import (
    AUDITOR_HEADERS,
    OPERATOR_HEADERS,
    api_client,
    assert_two_decimals,
    certify_terminal,
    create_station,
    install_charging_port,
    read_station,
    register_commissionable_host_site,
    set_clock,
    validate_success,
)


def _three_port_draft_station():
    """Two fully flagged dispensers plus one that is neither contactless nor
    publishing to a roaming-compliant OCPI version."""
    set_clock("2026-08-01T00:00:00Z")
    host_site = register_commissionable_host_site("HS-1", committed_service_capacity_kw=800.00)
    station = create_station(
        host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=3
    )
    first = install_charging_port(
        station["id"],
        "DS-1",
        connector_type="CCS1",
        rated_power_kw=150.00,
        terminal_model="PT-9",
        contactless_enabled=True,
        plug_and_charge_enabled=True,
        price_display_verified=True,
        roaming_ocpi_version="V2_2_1",
    )
    second = install_charging_port(
        station["id"],
        "DS-2",
        connector_type="NACS",
        rated_power_kw=150.00,
        terminal_model="PT-9",
        contactless_enabled=True,
        plug_and_charge_enabled=True,
        price_display_verified=True,
        roaming_ocpi_version="V2_2_1",
    )
    third = install_charging_port(
        station["id"],
        "DS-3",
        connector_type="CHADEMO",
        rated_power_kw=150.00,
        terminal_model="PT-3",
        plug_and_charge_enabled=True,
        price_display_verified=True,
        roaming_ocpi_version="V2_1_1",
    )
    return station, [first, second, third]


def test_two_repeating_shares_are_rounded_once_over_the_weighted_sum():
    """Rounding each weighted term first gives 73.34 instead of 73.33.

    PRD §3.2: "the roaming share counts dispensers that are both certified —
    `terminal_certification_status` equal to `CERTIFIED` — and publishing at
    `V2_2_1` or `V2_3_0`.  The four shares are left as exact fractions and are
    never individually rounded.  The score is one hundred multiplied by the
    weighted sum of those four shares, weighting contactless at forty percent and
    each of Plug-and-Charge, price display and roaming at twenty percent, and that
    single product is rounded half up to two decimal places."  PRD §3.2 also fixes
    when it moves: "Either outcome recomputes the station's
    `payment_interop_score`".

    Design: Corner/calculations/interop_score_rounds_once_over_the_weighted_sum_not_per_term
    """
    station, ports = _three_port_draft_station()
    certify_terminal(ports[2]["id"], "CERTIFIED")

    before = read_station(station["id"])
    assert float(before["payment_interop_score"]) == 66.67, (
        "the certified dispenser publishes at V2_1_1, so the roaming share is still zero"
    )

    data = validate_success(
        api_client.record_terminal_certification(
            ports[0]["id"], "CERTIFIED", AUDITOR_HEADERS
        )
    )
    assert data["terminal_certification_status"] == "CERTIFIED"

    after = read_station(station["id"])
    assert_two_decimals(after["payment_interop_score"], "payment_interop_score")
    assert float(after["payment_interop_score"]) == 73.33, (
        "contactless 2/3 and roaming 1/3 give an exact 73.3333... that rounds once"
    )
    assert after["commissioned_port_count"] == 3
    assert float(after["installed_power_kw"]) == 450.00


def test_retiring_the_worst_dispenser_raises_the_score_to_the_commissioning_boundary():
    """A denominator frozen at the original port count moves the score the wrong way.

    PRD §3.2: "`payment_interop_score` is a weighted percentage over the station's
    *scored* dispensers, which are exactly those whose `service_state` is
    `IN_SERVICE` or `OUT_OF_SERVICE`."  And: "Because retired dispensers leave both
    the numerator and the denominator, retiring a non-compliant dispenser *raises*
    the score."  PRD §3.3, gate 6: "`payment_interop_score` must be at least 90.00.
    The boundary itself passes: a station scoring exactly 90.00 commissions."

    Design: Corner/calculations/retiring_a_non_compliant_port_raises_the_interop_score
    """
    station, ports = _three_port_draft_station()
    certify_terminal(ports[0]["id"], "CERTIFIED")
    certify_terminal(ports[2]["id"], "CERTIFIED")

    before = read_station(station["id"])
    assert float(before["payment_interop_score"]) == 73.33

    data = validate_success(api_client.retire_charging_port(ports[2]["id"], OPERATOR_HEADERS))
    assert data["service_state"] == "RETIRED"

    after = read_station(station["id"])
    assert float(after["payment_interop_score"]) == 90.00, (
        "the surviving pair scores 2/2 contactless, 2/2 plug-and-charge, 2/2 price "
        "display and 1/2 roaming"
    )
    assert after["commissioned_port_count"] == 2
    assert float(after["installed_power_kw"]) == 300.00
