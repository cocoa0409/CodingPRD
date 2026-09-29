"""Approving an exclusion recovers the dispenser only on the CLASSIFIED branch."""
from test_helpers import (
    AUDITOR_HEADERS,
    OPERATOR_HEADERS,
    api_client,
    assert_instant_equals,
    classify_outage,
    ingest_outage,
    read_charging_port,
    read_outage_event,
    read_station,
    request_exclusion,
    setup_operational_station,
    validate_paginated,
    validate_success,
)


def test_approving_an_exclusion_requested_from_classified_returns_the_dispenser_to_service():
    """The recovery fires on the recorded pre-exclusion state, with no field visit.

    PRD §3.4: a request "moves to `EXCLUSION_REVIEW` and records which state it
    came from in `pre_exclusion_state`: `CLASSIFIED` when requested from
    `CLASSIFIED`".  `APPROVE` "moves it `EXCLUSION_REVIEW → EXCLUDED`; it stamps
    `excluded_at` from the logical clock ... and — when the state left was
    `CLASSIFIED` — returns the dispenser `OUT_OF_SERVICE → IN_SERVICE` provided no
    other unresolved outage remains on it."  PRD §3.3: "The system performs the
    same move on its own when the *last* out-of-service dispenser returns to
    service, but only when `suspension_source` is `AUTOMATIC` and the count has
    reached zero."

    Design: Corner/state_machines/exclusion_approval_restores_the_port_only_when_the_fault_was_still_unresolved
    """
    scenario = setup_operational_station(
        clock="2026-08-01T06:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        power_class="DCFC_150",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    outage = ingest_outage(
        port_id,
        "2026-08-01T06:00:00Z",
        fault_class="MAJOR",
        fault_code="EVSE-MAJ-11",
        excluded_cause_claim="NATURAL_DISASTER",
    )
    classify_outage(outage["id"], "MAJOR", excluded_cause_claim="NATURAL_DISASTER")
    requested = request_exclusion(outage["id"], "NATURAL_DISASTER")

    assert requested["state"] == "EXCLUSION_REVIEW"
    assert requested["pre_exclusion_state"] == "CLASSIFIED"
    assert read_charging_port(port_id)["service_state"] == "OUT_OF_SERVICE"
    before = read_station(station_id)
    assert before["status"] == "SUSPENDED"
    assert before["suspension_source"] == "AUTOMATIC"

    data = validate_success(
        api_client.submit_exclusion_action(outage["id"], {"action": "APPROVE"}, AUDITOR_HEADERS)
    )

    assert data["state"] == "EXCLUDED"
    assert_instant_equals(data["excluded_at"], "2026-08-01T06:00:00Z", "excluded_at")
    assert read_outage_event(outage["id"])["pre_exclusion_state"] == "CLASSIFIED", (
        "the state the outage left is recorded at REQUEST time, not inferred at APPROVE time"
    )

    assert read_charging_port(port_id)["service_state"] == "IN_SERVICE", (
        "the conditional cascade fired because pre_exclusion_state was CLASSIFIED"
    )

    after = read_station(station_id)
    assert after["out_of_service_port_count"] == 0
    assert after["status"] == "OPERATIONAL"
    assert after["suspension_source"] == "NONE"

    dispatches, _meta = validate_paginated(
        api_client.list_maintenance_dispatches(OPERATOR_HEADERS, params={"port_id": port_id})
    )
    assert dispatches == [], "the recovery happened with no field visit at all"
