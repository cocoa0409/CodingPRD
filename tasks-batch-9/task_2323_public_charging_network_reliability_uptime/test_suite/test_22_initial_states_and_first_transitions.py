"""Where each dimension starts, and what the first declared transition does."""
from test_helpers import (
    OPERATOR_HEADERS,
    api_client,
    create_station,
    ingest_outage,
    install_charging_port,
    intake_complaint,
    read_charging_port,
    read_complaint,
    read_outage_event,
    read_station,
    register_commissionable_host_site,
    set_clock,
    validate_paginated,
    validate_success,
)


def _site_station_and_dispenser(station_code: str = "ST-1"):
    host_site = register_commissionable_host_site("HS-1", committed_service_capacity_kw=400.00)
    station = create_station(
        host_site["id"], station_code, power_class="DCFC_150", declared_port_count=1
    )
    port = install_charging_port(
        station["id"],
        "DS-1",
        connector_type="CCS1",
        rated_power_kw=150.00,
        terminal_model="PT-4",
    )
    return host_site, station, port


def test_every_dimension_seeds_its_own_declared_starting_value():
    """Five rows, five dimensions, and a MINOR fault that changes none of them.

    PRD §3.2: "A new station opens in `DRAFT` with `suspension_source` set to
    `NONE`" and "A newly installed dispenser starts with
    `terminal_certification_status` of `PENDING`, a `service_state` of
    `IN_SERVICE`, a `maintenance_state` of `NONE`, and `retired_at` null".
    PRD §3.4: "A new outage opens in `DETECTED` with `cleared_at`,
    `pre_exclusion_state`, `excluded_at` and `dispatch_created_by_user_id` all
    null and `is_system_generated` false", and "`MINOR` and `INFORMATIONAL`
    faults deliberately leave the dispenser in service".  PRD §3.9: "A fresh
    complaint opens with `state` at `INTAKE` and `refund_state` at `NONE`, with
    `linked_outage_event_id`, `refund_basis`, `refund_amount_cents`,
    `retained_amount_cents`, `refund_requested_by_user_id` and
    `refund_settled_at` all null".

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    set_clock("2026-08-01T00:00:00Z")
    _host_site, station, port = _site_station_and_dispenser()

    outage = ingest_outage(
        port["id"], "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )
    complaint = intake_complaint(
        station["id"],
        port["id"],
        "2026-07-31T10:00:00Z",
        "2026-07-31T10:30:00Z",
        8.000,
        45,
        400,
        complaint_type="PRICE_MISMATCH",
    )

    station_row = read_station(station["id"])
    assert station_row["status"] == "DRAFT"
    assert station_row["suspension_source"] == "NONE"

    port_row = read_charging_port(port["id"])
    assert port_row["service_state"] == "IN_SERVICE", (
        "only CRITICAL and MAJOR pull a dispenser out of service, and this fault is MINOR"
    )
    assert port_row["maintenance_state"] == "NONE"
    assert port_row["terminal_certification_status"] == "PENDING"

    outage_row = read_outage_event(outage["id"])
    assert outage_row["state"] == "DETECTED"
    assert outage_row["cleared_at"] is None
    assert outage_row["pre_exclusion_state"] is None
    assert outage_row["is_system_generated"] is False
    assert outage_row["excluded_cause_claim"] == "NONE"

    complaint_row = read_complaint(complaint["id"])
    assert complaint_row["state"] == "INTAKE"
    assert complaint_row["refund_state"] == "NONE"
    assert complaint_row["refund_basis"] is None
    assert complaint_row["linked_outage_event_id"] is None

    dispatches, _meta = validate_paginated(
        api_client.list_maintenance_dispatches(OPERATOR_HEADERS, params={"port_id": port["id"]})
    )
    assert dispatches == [], "no dispatch exists until one is created"


def test_classification_rewrites_the_fault_class_and_that_value_drives_the_cascade():
    """The classified severity, not the ingested one, decides the service state.

    PRD §3.4: "After triage a `NetworkOperator` classifies the outage, advancing
    it `DETECTED → CLASSIFIED` while overwriting `fault_class` with the payload
    value", and "If the newly written `fault_class` is `CRITICAL` or `MAJOR` and
    the dispenser is still `IN_SERVICE`, classification drives the dispenser out
    of service exactly as ingestion would".  PRD §3.3 gives the automatic
    suspension only to an operational station: "whenever a dispenser on an
    operational station enters `OUT_OF_SERVICE` ... the station moves
    `OPERATIONAL → SUSPENDED`".

    Design: Corner/state_machines/classify_outage_moves_detected_to_classified_and_records_fault_class
    """
    set_clock("2026-08-01T00:00:00Z")
    _host_site, station, port = _site_station_and_dispenser()

    outage = ingest_outage(
        port["id"],
        "2026-08-01T00:00:00Z",
        fault_class="INFORMATIONAL",
        fault_code="OCPP-INF-01",
    )
    assert read_charging_port(port["id"])["service_state"] == "IN_SERVICE"

    response = api_client.classify_outage_event(
        outage["id"], {"fault_class": "MAJOR"}, OPERATOR_HEADERS
    )
    data = validate_success(response, 200)

    assert data["state"] == "CLASSIFIED"
    assert data["fault_class"] == "MAJOR"
    assert data["cleared_at"] is None
    assert data["excluded_cause_claim"] == "NONE"

    assert read_charging_port(port["id"])["service_state"] == "OUT_OF_SERVICE"

    station_row = read_station(station["id"])
    assert station_row["out_of_service_port_count"] == 1
    assert station_row["status"] == "DRAFT", (
        "a DRAFT station has no OPERATIONAL → SUSPENDED edge to take"
    )

    classified, _meta = validate_paginated(
        api_client.list_port_outage_events(
            port["id"], OPERATOR_HEADERS, params={"state": "CLASSIFIED"}
        )
    )
    assert len(classified) == 1
    assert classified[0]["id"] == outage["id"]
