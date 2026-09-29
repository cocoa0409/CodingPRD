"""Inclusive temporal bounds on fault ingestion and on the dispatch window."""
from test_helpers import (
    OPERATOR_HEADERS,
    TECHNICIAN_1,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    classify_outage,
    create_maintenance_dispatch_payload,
    create_outage_event_payload,
    ingest_outage,
    read_charging_port,
    read_outage_event,
    setup_station,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_station_with_one_plain_dispenser():
    """A DRAFT station whose single dispenser was installed at the clock's
    startup reading, so its `created_at` is exactly 2026-08-01T00:00:00Z."""
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        ports=[{"dispenser_serial": "DS-1", "terminal_model": "PT-4"}],
        stop_at="DRAFT",
    )
    return scenario["station"]["id"], scenario["ports"][0]["id"]


def _ingest(port_id, detected_at):
    return api_client.create_outage_event(
        create_outage_event_payload(
            port_id, detected_at, fault_class="MINOR", fault_code="OCPP-MIN-01"
        ),
        OPERATOR_HEADERS,
    )


def test_a_fault_may_be_detected_at_the_clock_and_at_the_dispensers_own_birth():
    """Reading either bound as exclusive rejects the one legitimate instant.

    PRD §3.4: "`detected_at` is bounded on both sides: it may not be later than
    the logical clock's current reading, or the request fails with
    `ERR_DETECTED_AT_IN_FUTURE`, and it may not be earlier than the dispenser's
    own `created_at`, or the request fails with `ERR_DETECTED_AT_BEFORE_PORT`.  A
    new outage opens in `DETECTED` with `cleared_at`, `pre_exclusion_state`,
    `excluded_at` and `dispatch_created_by_user_id` all null and
    `is_system_generated` false."

    Design: Corner/validations/outage_detection_timestamp_is_bounded_by_the_clock_and_the_ports_creation
    """
    _station_id, port_id = _draft_station_with_one_plain_dispenser()

    validate_error(
        _ingest(port_id, "2026-08-01T00:00:01Z"), ApiErrorId.ERR_DETECTED_AT_IN_FUTURE, 422
    )
    validate_error(
        _ingest(port_id, "2026-07-31T23:59:59Z"), ApiErrorId.ERR_DETECTED_AT_BEFORE_PORT, 422
    )

    data = validate_success(_ingest(port_id, "2026-08-01T00:00:00Z"), 201)

    assert data["state"] == "DETECTED"
    assert_instant_equals(data["detected_at"], "2026-08-01T00:00:00Z", "detected_at")
    assert data["cleared_at"] is None
    assert data["pre_exclusion_state"] is None
    assert data["excluded_at"] is None
    assert data["dispatch_created_by_user_id"] is None
    assert data["is_system_generated"] is False

    rows, meta = validate_paginated(
        api_client.list_port_outage_events(port_id, OPERATOR_HEADERS)
    )
    assert len(rows) == 1, "neither rejection may create a row"
    assert meta["total_count"] == 1


def test_a_dispatch_window_may_open_exactly_at_detection_but_never_before_it():
    """One error id guards two clauses, and a zero-length window must fail too.

    PRD §3.5: "The window must be well-formed: `window_end_at` strictly after
    `window_start_at`, and `window_start_at` no earlier than the outage's
    `detected_at`, or the request fails with `ERR_DISPATCH_WINDOW_INVALID`."  PRD
    §3.5 on what creation propagates: "The outage advances `CLASSIFIED →
    DISPATCHED`, recording the creating operator's `X-User-ID` as
    `dispatch_created_by_user_id` ... and the dispenser's repair posture moves
    `NONE → DISPATCH_PENDING` under the aggregate rule of §3.2."

    Design: Corner/validations/dispatch_window_must_be_well_formed_and_not_precede_detection
    """
    _station_id, port_id = _draft_station_with_one_plain_dispenser()

    outage = ingest_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )
    outage = classify_outage(outage["id"], fault_class="MINOR")
    assert outage["state"] == "CLASSIFIED"

    def _dispatch(window_start_at, window_end_at):
        return api_client.create_maintenance_dispatch(
            create_maintenance_dispatch_payload(
                outage["id"],
                port_id,
                TECHNICIAN_1,
                window_start_at,
                window_end_at,
                technician_certification_class="DCFC_BASIC",
            ),
            OPERATOR_HEADERS,
        )

    validate_error(
        _dispatch("2026-07-31T23:00:00Z", "2026-08-01T08:00:00Z"),
        ApiErrorId.ERR_DISPATCH_WINDOW_INVALID,
        422,
    )
    assert read_outage_event(outage["id"])["state"] == "CLASSIFIED"

    validate_error(
        _dispatch("2026-08-01T08:00:00Z", "2026-08-01T08:00:00Z"),
        ApiErrorId.ERR_DISPATCH_WINDOW_INVALID,
        422,
    )
    assert read_outage_event(outage["id"])["state"] == "CLASSIFIED"
    assert read_charging_port(port_id)["maintenance_state"] == "NONE"

    data = validate_success(
        _dispatch("2026-08-01T00:00:00Z", "2026-08-01T08:00:00Z"), 201
    )

    assert data["state"] == "CREATED"
    assert_instant_equals(data["window_start_at"], "2026-08-01T00:00:00Z", "window_start_at")
    assert read_outage_event(outage["id"])["state"] == "DISPATCHED"
    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING"

    rows, meta = validate_paginated(
        api_client.list_maintenance_dispatches(OPERATOR_HEADERS, {"port_id": port_id})
    )
    assert len(rows) == 1, "no rejected call may consume the dispenser's window"
    assert meta["total_count"] == 1
