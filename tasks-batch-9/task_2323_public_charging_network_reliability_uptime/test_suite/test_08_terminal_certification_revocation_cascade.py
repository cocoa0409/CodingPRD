"""Revoking a payment terminal cascades three levels down the hierarchy."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    api_client,
    assert_instant_equals,
    certify_terminal,
    read_charging_port,
    read_station,
    setup_station,
    validate_paginated,
)


def _two_certified_dispensers_on_an_operational_station():
    return setup_station(
        clock="2026-06-18T10:00:00Z",
        site_code="HS-CR-1",
        station_code="ST-CR-1",
        committed_service_capacity_kw=800.00,
        power_class="DCFC_150",
        declared_port_count=2,
        ports=[
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-CR-1", connector_type="CCS1"),
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-CR-2", connector_type="NACS"),
        ],
    )


def test_revocation_forces_the_dispenser_out_of_service_and_synthesises_an_outage():
    """The revoked terminal manufactures an outage the caller never filed.

    PRD §3.2: "`REVOKED` on a dispenser that is currently `IN_SERVICE` ... drives
    `service_state` from `IN_SERVICE` to `OUT_OF_SERVICE`, raises the station's
    out-of-service count, synthesises an outage event on that dispenser with
    `is_system_generated` set to true, a `fault_class` of `MAJOR`, a `fault_code`
    of `TERMINAL_CERT_REVOKED`, and `detected_at` set to the logical clock's
    current reading".

    Design: Difficulty/transitive_cascade/terminal_certification_revocation_cascades_three_levels_port_outage_station
    """
    scenario = _two_certified_dispensers_on_an_operational_station()
    revoked_port_id = scenario["ports"][0]["id"]

    revoked = certify_terminal(revoked_port_id, "REVOKED")

    assert revoked["terminal_certification_status"] == "REVOKED"
    assert revoked["service_state"] == "OUT_OF_SERVICE"

    rows, _meta = validate_paginated(
        api_client.list_port_outage_events(revoked_port_id, OPERATOR_HEADERS)
    )
    assert len(rows) == 1, f"exactly one synthesised outage expected, got {len(rows)}"
    outage = rows[0]
    assert outage["is_system_generated"] is True
    assert outage["fault_class"] == "MAJOR"
    assert outage["fault_code"] == "TERMINAL_CERT_REVOKED"
    assert outage["state"] == "DETECTED"
    assert_instant_equals(outage["detected_at"], "2026-06-18T10:00:00Z", "detected_at")
    assert outage["cleared_at"] is None


def test_revocation_suspends_the_station_and_rescores_interoperability():
    """The station absorbs both the out-of-service count and the lost roaming share.

    PRD §3.2: "the roaming share counts dispensers that are both certified —
    `terminal_certification_status` equal to `CERTIFIED` — and publishing at
    `V2_2_1` or `V2_3_0`", weighted at twenty percent.  PRD §3.2 also has
    revocation "may drive the station from `OPERATIONAL` to `SUSPENDED` with
    `suspension_source` set to `AUTOMATIC`".

    Design: Difficulty/transitive_cascade/terminal_certification_revocation_cascades_three_levels_port_outage_station
    """
    scenario = _two_certified_dispensers_on_an_operational_station()
    station_id = scenario["station"]["id"]

    assert float(read_station(station_id)["payment_interop_score"]) == 100.00

    certify_terminal(scenario["ports"][0]["id"], "REVOKED")

    station = read_station(station_id)
    assert station["out_of_service_port_count"] == 1
    assert station["status"] == "SUSPENDED"
    assert station["suspension_source"] == "AUTOMATIC"
    assert float(station["payment_interop_score"]) == 90.00, (
        "only the roaming term loses a compliant dispenser: "
        "100 * (0.40 + 0.20 + 0.20 + 0.20 * 1/2) is 90.00, got "
        f"{station['payment_interop_score']}"
    )


def test_the_cascade_does_not_spill_onto_the_untouched_dispenser():
    """A revocation is scoped to the dispenser it names.

    PRD §3.2 scopes the outcome to "a dispenser that is currently `IN_SERVICE`" —
    the one named by the request — and a newly installed dispenser keeps "a
    `service_state` of `IN_SERVICE`" until something moves it.

    Design: Difficulty/transitive_cascade/terminal_certification_revocation_cascades_three_levels_port_outage_station
    """
    scenario = _two_certified_dispensers_on_an_operational_station()
    untouched_port_id = scenario["ports"][1]["id"]

    certify_terminal(scenario["ports"][0]["id"], "REVOKED")

    untouched = read_charging_port(untouched_port_id)
    assert untouched["service_state"] == "IN_SERVICE"
    assert untouched["terminal_certification_status"] == "CERTIFIED"

    rows, _meta = validate_paginated(
        api_client.list_port_outage_events(untouched_port_id, OPERATOR_HEADERS)
    )
    assert rows == [], f"no outage should have been synthesised here, got {rows}"
