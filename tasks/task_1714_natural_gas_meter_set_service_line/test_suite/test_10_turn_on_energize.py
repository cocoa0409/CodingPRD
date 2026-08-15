"""Appliance turn-on safety checks and the energize gate."""
from test_helpers import (
    ApiErrorId,
    add_load,
    complete_turn_on_payload,
    create_turn_on_event_payload,
    get_success_data,
    refresh_application,
    refresh_meter_set,
    setup_meter_installed_app,
    setup_turn_on_app,
    validate_error,
    validate_paginated,
    validate_success,
    verify_turn_on,
)

TWO_APPLIANCE_LOADS = [
    {"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000},
    {"appliance_type": "RANGE", "quantity": 1, "btuh_input_rating": 65000},
]


class TestEnergizeGate:
    def test_energize_rejected_until_every_load_verified(self, api, technician_headers):
        """PRD §3.6: "The technician may turn the gas on only when the application is unheld, the meter set stands at `READY_FOR_TURN_ON` (else `ERR_METER_NOT_READY`), and every appliance load of the application has at least one `VERIFIED` turn-on event (else `ERR_TURN_ON_INCOMPLETE`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/energize_needs_all_turn_ons_verified
        """
        ctx = setup_turn_on_app(loads=list(TWO_APPLIANCE_LOADS), observed_drop=0.250)
        assert ctx["app"]["status"] == "TURN_ON"
        assert ctx["meter_set"]["status"] == "READY_FOR_TURN_ON"

        verify_turn_on(ctx["app"]["id"], ctx["loads"][0]["id"], co_reading_ppm=2.5)
        resp = api.energize_application(ctx["app"]["id"], technician_headers)
        validate_error(resp, ApiErrorId.ERR_TURN_ON_INCOMPLETE, expected_status=422)
        assert refresh_application(ctx["app"]["id"])["status"] == "TURN_ON"

    def test_energize_succeeds_once_all_loads_verified(self, api, technician_headers):
        """PRD §3.6: "Energizing moves the application from `TURN_ON` to `ENERGIZED` and the meter set from `READY_FOR_TURN_ON` to `ENERGIZED` with it."

        Design: Difficulty/cross_entity_state_dependency/energize_needs_all_turn_ons_verified
        """
        ctx = setup_turn_on_app(loads=list(TWO_APPLIANCE_LOADS), observed_drop=0.250)
        verify_turn_on(ctx["app"]["id"], ctx["loads"][0]["id"], co_reading_ppm=2.5)
        verify_turn_on(ctx["app"]["id"], ctx["loads"][1]["id"], co_reading_ppm=3.1)

        resp = api.energize_application(ctx["app"]["id"], technician_headers)
        energized = validate_success(resp)
        assert energized["status"] == "ENERGIZED"
        assert refresh_meter_set(ctx["meter_set"]["id"])["status"] == "ENERGIZED"


class TestTurnOnCreation:
    def test_load_from_another_application_rejected(self, api, technician_headers):
        """PRD §3.6: "The technician schedules a turn-on event by naming the `service_application_id` and the `appliance_load_id` — which must belong to that same application, else `ERR_LOAD_APP_MISMATCH` (HTTP 422)"

        Design: Corner/errors/turn_on_load_app_mismatch_rejected
        """
        from test_helpers import create_application, create_builder
        builder = create_builder()
        app_a = create_application(builder, service_address="1 A St")
        app_b = create_application(builder, service_address="2 B St")
        load_b = add_load(app_b["id"], builder["id"], appliance_type="FURNACE",
                          quantity=1, btuh_input_rating=80000)

        resp = api.create_turn_on_event(
            create_turn_on_event_payload(app_a["id"], load_b["id"]), technician_headers
        )
        validate_error(resp, ApiErrorId.ERR_LOAD_APP_MISMATCH, expected_status=422)

        resp = api.list_turn_on_events(
            technician_headers, params={"service_application_id": app_a["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0


class TestTurnOnCompletion:
    def test_complete_before_turn_on_state_rejected(self, api, technician_headers):
        """PRD §3.6: "Completing the event is possible only while the application sits in `TURN_ON` (else `ERR_METER_NOT_READY`, HTTP 409)"

        Design: Corner/errors/turn_on_complete_before_meter_ready_rejected
        """
        ctx = setup_meter_installed_app()
        assert ctx["app"]["status"] == "METER_WORK"
        event = get_success_data(
            api.create_turn_on_event(
                create_turn_on_event_payload(ctx["app"]["id"], ctx["loads"][0]["id"]),
                technician_headers,
            )
        )
        resp = api.complete_turn_on_event(
            event["id"], complete_turn_on_payload(), technician_headers
        )
        validate_error(resp, ApiErrorId.ERR_METER_NOT_READY, expected_status=409)

        after = get_success_data(api.get_turn_on_event(event["id"], technician_headers))
        assert after["status"] == "SCHEDULED"

    def test_failed_event_retries_to_verified(self, api, technician_headers):
        """PRD §3.6: "The event becomes `VERIFIED` if and only if no odor was detected, ignition verified, venting verified, and the carbon-monoxide reading is strictly below 9.0 parts per million — a reading of exactly 9.0 fails; any other outcome makes it `FAILED`."
        PRD §3.6: "A failed event can be re-opened from `FAILED` back to `SCHEDULED` for another attempt."

        Design: Corner/state_machines/turn_on_failure_retry_cycle
        """
        ctx = setup_turn_on_app()
        event = get_success_data(
            api.create_turn_on_event(
                create_turn_on_event_payload(ctx["app"]["id"], ctx["loads"][0]["id"]),
                technician_headers,
            )
        )
        v0 = event["version"]

        failed = get_success_data(
            api.complete_turn_on_event(
                event["id"], complete_turn_on_payload(odor_detected=True),
                technician_headers,
            )
        )
        assert failed["status"] == "FAILED", "odor fails regardless of the other checks"
        assert failed["version"] == v0 + 1

        resp = api.retry_turn_on_event(event["id"], technician_headers)
        reopened = validate_success(resp)
        assert reopened["id"] == event["id"], "retry re-opens the same row"
        assert reopened["status"] == "SCHEDULED"
        assert reopened["version"] == v0 + 2

        verified = get_success_data(
            api.complete_turn_on_event(
                event["id"], complete_turn_on_payload(co_reading_ppm=1.5),
                technician_headers,
            )
        )
        assert verified["status"] == "VERIFIED"

        resp = api.list_turn_on_events(
            technician_headers, params={"service_application_id": ctx["app"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, "the retry loop never creates extra rows"

    def test_co_reading_at_threshold_fails_below_passes(self, api, technician_headers):
        """PRD §3.6: "The event becomes `VERIFIED` if and only if no odor was detected, ignition verified, venting verified, and the carbon-monoxide reading is strictly below 9.0 parts per million — a reading of exactly 9.0 fails; any other outcome makes it `FAILED`."

        Design: Corner/calculations/co_threshold_nine_ppm_fails
        """
        ctx = setup_turn_on_app()
        event = get_success_data(
            api.create_turn_on_event(
                create_turn_on_event_payload(ctx["app"]["id"], ctx["loads"][0]["id"]),
                technician_headers,
            )
        )

        failed = get_success_data(
            api.complete_turn_on_event(
                event["id"], complete_turn_on_payload(co_reading_ppm=9.0),
                technician_headers,
            )
        )
        assert failed["status"] == "FAILED", "9.0 ppm is not strictly below 9.0"

        get_success_data(api.retry_turn_on_event(event["id"], technician_headers))
        verified = get_success_data(
            api.complete_turn_on_event(
                event["id"], complete_turn_on_payload(co_reading_ppm=8.9),
                technician_headers,
            )
        )
        assert verified["status"] == "VERIFIED", "8.9 ppm is strictly below the threshold"
