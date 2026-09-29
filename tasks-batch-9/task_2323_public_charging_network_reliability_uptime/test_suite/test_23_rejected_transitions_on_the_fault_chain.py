"""Transitions whose declared preconditions are not met, and what they leave behind."""
from test_helpers import (
    OPERATOR_HEADERS,
    TECHNICIAN_HEADERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_dispatch,
    create_station,
    ingest_and_classify_outage,
    install_charging_port,
    read_charging_port,
    read_dispatch,
    read_outage_event,
    read_station,
    register_commissionable_host_site,
    set_clock,
    setup_station,
    validate_error,
    validate_success,
)


def _classified_minor_fault_on_an_operational_station(stop_at: str = "OPERATIONAL"):
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at=stop_at,
    )
    port_id = scenario["ports"][0]["id"]
    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )
    return scenario, outage


def test_classifying_an_already_classified_outage_is_rejected_and_changes_nothing():
    """Classification is not idempotent, and the rejected payload leaves no trace.

    PRD §3.4: classification advances the outage "`DETECTED → CLASSIFIED` while
    overwriting `fault_class` with the payload value" — `CLASSIFIED` is not a
    `DETECTED` state.  PRD §2.11, priority 8: "Transition legality: the target
    resource occupies a state from which the requested transition exists in the
    relevant dimension ... — `ERR_INVALID_STATE`."

    Design: Corner/state_machines/classify_outage_twice_second_attempt_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    host_site = register_commissionable_host_site("HS-1", committed_service_capacity_kw=400.00)
    station = create_station(
        host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=1
    )
    port = install_charging_port(
        station["id"],
        "DS-1",
        connector_type="CCS1",
        rated_power_kw=150.00,
        terminal_model="PT-4",
    )
    outage = ingest_and_classify_outage(
        port["id"], "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )

    response = api_client.classify_outage_event(
        outage["id"], {"fault_class": "CRITICAL"}, OPERATOR_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    after = read_outage_event(outage["id"])
    assert after["fault_class"] == "MINOR", "the second payload was not applied"
    assert after["state"] == "CLASSIFIED"

    assert read_charging_port(port["id"])["service_state"] == "IN_SERVICE", (
        "no CRITICAL cascade leaked out of the rejected call"
    )
    assert read_station(station["id"])["out_of_service_port_count"] == 0


def test_arriving_before_going_en_route_is_rejected_with_no_partial_side_effect():
    """`ARRIVE` is declared only from `EN_ROUTE`, and it settles two fields at once.

    PRD §3.5: "`ARRIVE` advances `EN_ROUTE → ON_SITE`, stamps `arrived_at` from
    the logical clock, and settles `response_met` once and for all: it is true
    when `arrived_at` is at or before `response_deadline_at` and false otherwise,
    and it stays null until arrival is posted."  PRD §2.11, priority 8, rejects a
    transition that does not exist from the occupied state with
    `ERR_INVALID_STATE`.  PRD §3.2: "When a first dispatch is created for a
    dispenser sitting at `NONE`, the dimension moves `NONE → DISPATCH_PENDING`".

    Design: Corner/state_machines/dispatch_arrive_before_en_route_rejected
    """
    scenario, outage = _classified_minor_fault_on_an_operational_station()
    port_id = scenario["ports"][0]["id"]
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
    )

    response = api_client.post_dispatch_progress(dispatch["id"], "ARRIVE", TECHNICIAN_HEADERS)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    after = read_dispatch(dispatch["id"])
    assert after["state"] == "CREATED"
    assert after["arrived_at"] is None
    assert after["response_met"] is None, "the arrival side effect must not run partially"

    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING", (
        "the posture set at dispatch creation is unchanged"
    )


def test_a_technician_cannot_go_en_route_to_a_station_still_being_commissioned():
    """The blocking condition sits on the station, not on the dispatch.

    PRD §3.5: "`EN_ROUTE` advances the dispatch `CREATED → EN_ROUTE` and
    additionally requires the station to be serviceable, meaning its `status` is
    `OPERATIONAL` or `SUSPENDED`; a dispatch against a station in any other
    lifecycle state is rejected with `ERR_STATION_NOT_SERVICEABLE`."

    Design: Corner/state_machines/dispatch_cannot_go_en_route_while_station_is_still_commissioning
    """
    scenario, outage = _classified_minor_fault_on_an_operational_station(stop_at="COMMISSIONING")
    port_id = scenario["ports"][0]["id"]
    station_id = scenario["station"]["id"]
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
    )

    response = api_client.post_dispatch_progress(dispatch["id"], "EN_ROUTE", TECHNICIAN_HEADERS)

    validate_error(response, ApiErrorId.ERR_STATION_NOT_SERVICEABLE, 409)

    assert read_station(station_id)["status"] == "COMMISSIONING"
    assert read_dispatch(dispatch["id"])["state"] == "CREATED"
    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING"


def test_an_exclusion_cannot_be_requested_once_the_dispenser_has_been_retired():
    """A retired dispenser freezes its historical outages.

    PRD §3.4: an exclusion "request is permitted only from `CLASSIFIED` or
    `RESOLVED`, only while the dispenser is not `RETIRED`".  PRD §2.11, priority
    21, maps that dependency to `ERR_PORT_RETIRED` and applies it to exclusion
    actions.  PRD §3.2: retirement "stamps `retired_at` from the logical clock ...
    recomputes the station's non-retired port count, `installed_power_kw` and
    `payment_interop_score`".

    Design: Corner/state_machines/exclusion_request_on_a_retired_port_rejected
    """
    scenario, outage = _classified_minor_fault_on_an_operational_station()
    port_id = scenario["ports"][0]["id"]
    station_id = scenario["station"]["id"]

    set_clock("2026-08-02T00:00:00Z")
    retired = validate_success(api_client.retire_charging_port(port_id, OPERATOR_HEADERS))
    assert retired["service_state"] == "RETIRED"

    response = api_client.submit_exclusion_action(
        outage["id"],
        {"action": "REQUEST", "excluded_cause_claim": "UTILITY_OUTAGE"},
        OPERATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_PORT_RETIRED, 409)

    port_after = read_charging_port(port_id)
    assert port_after["service_state"] == "RETIRED"
    assert_instant_equals(port_after["retired_at"], "2026-08-02T00:00:00Z", "retired_at")

    outage_after = read_outage_event(outage["id"])
    assert outage_after["state"] == "CLASSIFIED"
    assert outage_after["pre_exclusion_state"] is None

    station_after = read_station(station_id)
    assert station_after["commissioned_port_count"] == 0, (
        "the retired dispenser left the non-retired population"
    )
    assert float(station_after["installed_power_kw"]) == 0.00
