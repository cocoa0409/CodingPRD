"""Both ends of the regulatory band on the response-deadline chain."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    TECHNICIAN_1,
    TECHNICIAN_2,
    api_client,
    assert_instant_equals,
    create_maintenance_dispatch_payload,
    ingest_and_classify_outage,
    read_charging_port,
    read_station,
    setup_station,
    validate_success,
)


def test_a_critical_corridor_fault_is_lifted_back_to_the_two_hour_floor():
    """The floor applies after the corridor subtraction, not to the base allowance.

    PRD §3.5: "First, a base allowance is chosen from the outage's severity: four
    hours for `CRITICAL`, twelve hours for `MAJOR`, forty-eight hours for `MINOR`,
    and seven days for `INFORMATIONAL`.  Second, that base is scaled by the
    station's power class — halved for `DCFC_350`, reduced to three quarters for
    `DCFC_150`, and left unchanged for `L2_19` — with the scaled product rounded
    down to a whole number of minutes.  Third, if the station is
    `corridor_designated`, one hour is subtracted from the scaled figure; otherwise
    nothing is subtracted.  Fourth, the result is clamped into the regulatory band:
    it is raised to two hours if it fell below two hours, and capped at three days
    if it rose above three days.  The clamped allowance is added to the outage's
    `detected_at` to give a provisional deadline instant."  PRD §3.5: "If the host
    site's `access_hours_mode` is `TWENTY_FOUR_SEVEN`, the provisional instant is
    the deadline."

    Design: Corner/calculations/dispatch_deadline_regulatory_floor_overrides_the_corridor_tightening
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=800.00,
        power_class="DCFC_350",
        declared_port_count=1,
        corridor_designated=True,
        host_site_overrides={"access_hours_mode": "TWENTY_FOUR_SEVEN"},
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="CRITICAL", fault_code="EVSE-CRIT-01"
    )

    response = api_client.create_maintenance_dispatch(
        create_maintenance_dispatch_payload(
            outage["id"],
            port_id,
            TECHNICIAN_1,
            "2026-08-01T00:30:00Z",
            "2026-08-01T04:00:00Z",
            technician_certification_class="DCFC_HV",
        ),
        OPERATOR_HEADERS,
    )
    data = validate_success(response, 201)

    assert_instant_equals(
        data["response_deadline_at"], "2026-08-01T02:00:00Z", "response_deadline_at"
    )
    assert data["state"] == "CREATED"
    assert data["arrived_at"] is None
    assert data["response_met"] is None

    port_after = read_charging_port(port_id)
    assert port_after["maintenance_state"] == "DISPATCH_PENDING"
    assert port_after["service_state"] == "OUT_OF_SERVICE", "the CRITICAL fault pulled it"

    station_after = read_station(station_id)
    assert station_after["status"] == "SUSPENDED"
    assert station_after["suspension_source"] == "AUTOMATIC"


def test_an_informational_fault_on_a_level_two_station_is_capped_at_three_days():
    """Seven days scaled by one is still seven days, and the cap has to bite.

    PRD §3.5: the base allowance is "seven days for `INFORMATIONAL`", it is "left
    unchanged for `L2_19`", and "the result is clamped into the regulatory band: it
    is raised to two hours if it fell below two hours, and capped at three days if
    it rose above three days."  PRD §3.4: "`MINOR` and `INFORMATIONAL` faults
    deliberately leave the dispenser in service".  PRD §3.2: "Only `V2_2_1` and
    `V2_3_0` count as roaming-compliant."

    Design: Corner/calculations/dispatch_deadline_regulatory_cap_truncates_an_informational_fault
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=100.00,
        power_class="L2_19",
        declared_port_count=1,
        host_site_overrides={
            "parking_enforcement_mode": "SIGNAGE_ONLY",
            "access_hours_mode": "TWENTY_FOUR_SEVEN",
        },
        ports=[
            dict(
                FULLY_COMPLIANT_PORT,
                dispenser_serial="DS-1",
                connector_type="J1772",
                terminal_model="PT-2",
                roaming_ocpi_version="V2_3_0",
            )
        ],
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    outage = ingest_and_classify_outage(
        port_id,
        "2026-08-01T00:00:00Z",
        fault_class="INFORMATIONAL",
        fault_code="OCPP-INF-01",
    )

    response = api_client.create_maintenance_dispatch(
        create_maintenance_dispatch_payload(
            outage["id"],
            port_id,
            TECHNICIAN_2,
            "2026-08-01T01:00:00Z",
            "2026-08-04T12:00:00Z",
            technician_certification_class="L2",
        ),
        OPERATOR_HEADERS,
    )
    data = validate_success(response, 201)

    assert_instant_equals(
        data["response_deadline_at"], "2026-08-04T00:00:00Z", "response_deadline_at"
    )

    port_after = read_charging_port(port_id)
    assert port_after["service_state"] == "IN_SERVICE"
    assert port_after["maintenance_state"] == "DISPATCH_PENDING"

    station_after = read_station(station_id)
    assert station_after["status"] == "OPERATIONAL"
    assert station_after["suspension_source"] == "NONE"
    assert float(station_after["payment_interop_score"]) == 100.00
