"""Dispatch creation reports the certification failure, not the port mismatch."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    TECHNICIAN_L2,
    ApiErrorId,
    api_client,
    create_maintenance_dispatch_payload,
    ingest_and_classify_outage,
    read_charging_port,
    read_outage_event,
    set_clock,
    setup_station,
    validate_error,
    validate_paginated,
)


def _classified_fault_on_the_first_of_two_dcfc_350_dispensers():
    scenario = setup_station(
        clock="2026-06-19T10:00:00Z",
        site_code="HS-PD-2",
        station_code="ST-PD-2",
        committed_service_capacity_kw=1600.00,
        power_class="DCFC_350",
        declared_port_count=2,
        ports=[
            dict(
                FULLY_COMPLIANT_PORT,
                dispenser_serial="DS-PD-2A",
                connector_type="NACS",
                roaming_ocpi_version="V2_3_0",
            ),
            dict(
                FULLY_COMPLIANT_PORT,
                dispenser_serial="DS-PD-2B",
                connector_type="CCS1",
                roaming_ocpi_version="V2_3_0",
            ),
        ],
    )
    set_clock("2026-06-19T12:00:00Z")
    outage = ingest_and_classify_outage(
        scenario["ports"][0]["id"],
        "2026-06-19T11:00:00Z",
        fault_class="MAJOR",
        fault_code="EVSE-MAJ-11",
    )
    return scenario, outage


def _dispatch_an_underqualified_technician_at_the_wrong_dispenser(scenario, outage):
    """One call that violates certification coverage and port ownership at once."""
    payload = create_maintenance_dispatch_payload(
        outage["id"],
        scenario["ports"][1]["id"],
        TECHNICIAN_L2,
        "2026-06-19T13:00:00Z",
        "2026-06-19T18:00:00Z",
        technician_certification_class="L2",
    )
    return api_client.create_maintenance_dispatch(payload, OPERATOR_HEADERS)


def test_the_certification_check_precedes_the_cross_entity_ownership_check():
    """Both rules are broken by the same call, and certification is reported.

    PRD §2.11 evaluates "11. Technician certification coverage —
    `ERR_TECHNICIAN_NOT_CERTIFIED`" before "13. Cross-entity ownership —
    `ERR_OUTAGE_PORT_MISMATCH`".  PRD §3.5 fixes the ranking: "a `DCFC_350`
    station requires `DCFC_HV`".

    Design: Difficulty/priority_pair_validation_conflict/dispatch_technician_certification_check_wins_over_outage_port_mismatch
    """
    scenario, outage = _classified_fault_on_the_first_of_two_dcfc_350_dispensers()

    response = _dispatch_an_underqualified_technician_at_the_wrong_dispenser(scenario, outage)

    body = validate_error(response, ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED, 422)
    assert body["error_id"] != "ERR_OUTAGE_PORT_MISMATCH", (
        "the supplied port_id does belong to a different dispenser than the "
        "outage, but that is the lower-priority failure"
    )


def test_the_rejected_dispatch_leaves_no_trace_on_the_outage_or_the_dispenser():
    """A rejected creation performs no partial transition.

    PRD §3.5: creation is what makes "The outage advances `CLASSIFIED →
    DISPATCHED`" and "the dispenser's repair posture moves `NONE →
    DISPATCH_PENDING`" — neither may happen when the guards reject the request.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_technician_certification_check_wins_over_outage_port_mismatch
    """
    scenario, outage = _classified_fault_on_the_first_of_two_dcfc_350_dispensers()

    _dispatch_an_underqualified_technician_at_the_wrong_dispenser(scenario, outage)

    assert read_outage_event(outage["id"])["state"] == "CLASSIFIED"
    assert read_charging_port(scenario["ports"][1]["id"])["maintenance_state"] == "NONE"

    rows, _meta = validate_paginated(
        api_client.list_maintenance_dispatches(
            OPERATOR_HEADERS, params={"outage_event_id": outage["id"]}
        )
    )
    assert rows == [], f"no dispatch should exist for this outage, got {rows}"
