"""Call intake, triage, cancellation lockdown, and the append-only audit
trail."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    assert_call_event,
    complete_repair,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    diagnose_call,
    drive_call_on_site,
    get_call,
    intake_call,
    open_triaged_call,
    parse_iso8601_utc,
    start_repair,
    triage_call,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestAfterHoursBoundary:
    def test_after_hours_flag_at_exactly_1800_vs_175959(self, api):
        """PRD: intake "computes `after_hours` — true when the UTC hour of
        `received_at` is at or after 18 or before 6, so 18:00:00Z is
        after-hours while 17:59:59Z is not".

        Design: Difficulty/boundary_precision_check/after_hours_flag_at_exactly_1800_vs_175959
        """
        create_standard_rate_card()
        veh = create_vehicle()
        early = intake_call(veh["id"], symptom_category="LIGHTING",
                            received_at="2026-08-03T17:59:59Z")
        edge = intake_call(veh["id"], symptom_category="LIGHTING",
                           received_at="2026-08-03T18:00:00Z")
        assert early["after_hours"] is False, (
            "17:59:59Z is one second before the boundary: business hours")
        assert edge["after_hours"] is True, (
            "18:00:00Z exactly is after-hours: the comparison is >= 18")

    def test_after_hours_flag_stamps_received_at_from_logical_clock(self, api):
        """PRD: "Intake stamps `received_at` from the logical clock" — the
        stamped instants read back exactly, and the boundary instants carry
        the pinned flags.

        Design: Difficulty/boundary_precision_check/after_hours_flag_at_exactly_1800_vs_175959
        """
        create_standard_rate_card()
        veh = create_vehicle()
        early = intake_call(veh["id"], symptom_category="LIGHTING",
                            received_at="2026-08-03T17:59:59Z")
        edge = intake_call(veh["id"], symptom_category="LIGHTING",
                           received_at="2026-08-03T18:00:00Z")
        assert parse_iso8601_utc(early["received_at"]) == \
            parse_iso8601_utc("2026-08-03T17:59:59Z")
        assert parse_iso8601_utc(edge["received_at"]) == \
            parse_iso8601_utc("2026-08-03T18:00:00Z")
        assert (early["after_hours"], edge["after_hours"]) == (False, True)


class TestTriageStateMachine:
    def test_triage_on_triaged_call_rejected(self, api):
        """PRD: "Setting the call's `severity` — `BLOCKING`, `DRIVABLE`, or
        `DEFERRED` — moves it from `RECEIVED` to `TRIAGED`" — triage is
        declared only from `RECEIVED`, so a second triage fails
        `ERR_INVALID_STATE` and the computed priority is left unchanged.

        Design: Corner/state_machines/triage_on_triaged_call_rejected
        """
        advance_clock("2026-08-05T09:00:00Z")
        veh = create_vehicle()
        call = intake_call(veh["id"], symptom_category="LIGHTING")
        triaged = triage_call(call["id"], severity="DRIVABLE")
        assert triaged["priority"] == "P2_URGENT"

        resp = api.triage_service_call(call["id"], {"severity": "BLOCKING"},
                                       DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_call(call["id"])
        assert after["priority"] == "P2_URGENT", "no re-triage side effects"
        assert after["status"] == "TRIAGED"


class TestCancellation:
    def test_cancel_terminal_lockdown_and_late_cancel_rejected(self, api):
        """PRD: "Once a call is `CANCELLED` it is terminal: any further action
        attempted against it is rejected with `ERR_CALL_ALREADY_TERMINAL`."
        PRD: cancellation is declared only from `RECEIVED`, `TRIAGED`,
        `DISPATCHED`, or `EN_ROUTE` — "A call may be cancelled from `RECEIVED`
        by a `Dispatcher`" — so cancelling a `REPAIR_COMPLETED` call fails
        `ERR_INVALID_STATE`.

        Design: Corner/state_machines/cancel_terminal_lockdown_and_late_cancel_rejected
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()
        advance_clock("2026-08-05T09:00:00Z")

        call_a = open_triaged_call(veh_a["id"], symptom_category="LIGHTING",
                                   severity="DEFERRED",
                                   breakdown_location_text="site A")
        cancelled = validate_success(api.cancel_service_call(
            call_a["id"], {"reason": "customer cancelled"}, DISPATCHER))
        assert cancelled["status"] == "CANCELLED"

        call_b = open_triaged_call(veh_b["id"], severity="DRIVABLE",
                                   breakdown_location_text="site B")
        call_b, dispatch_b = drive_call_on_site(
            call_b, tech["id"], tech_headers, "2026-08-05T09:00:00Z",
            "2026-08-05T13:00:00Z", arrive_at="2026-08-05T09:40:00Z")
        diagnose_call(call_b["id"], tech_headers, diagnosis_summary="fuse")
        start_repair(call_b["id"], tech_headers)
        complete_repair(call_b["id"], tech_headers, 0.5, 90020)

        resp_a = api.cancel_service_call(call_a["id"], {"reason": "again"},
                                         DISPATCHER)
        validate_error(resp_a, ApiErrorId.ERR_CALL_ALREADY_TERMINAL)
        resp_b = api.cancel_service_call(call_b["id"], {"reason": "too late"},
                                         DISPATCHER)
        validate_error(resp_b, ApiErrorId.ERR_INVALID_STATE)


class TestCallEventAuditTrail:
    def test_call_events_audit_trail_ordering(self, api):
        """PRD: "Every state transition, posting, decision, and system cascade
        described in Section 3 appends the corresponding `CallEvent` to the
        affected call's trail" and a `CallEvent` "carries only `id` and
        `created_at` alongside its content fields (`service_call_id`,
        `event_type`, `actor_role`, `actor_id`, and an optional free-text
        `note`); it has no `updated_at` and no `version`". The logical clock
        is advanced between steps so the created_at-ascending list order is
        fully determined.

        Design: Corner/endpoints/call_events_audit_trail_ordering
        """
        create_standard_rate_card()
        veh = create_vehicle()
        tech, tech_headers = create_technician()
        call = intake_call(veh["id"], received_at="2026-08-05T09:00:00Z")
        advance_clock("2026-08-05T09:01:00Z")
        call = triage_call(call["id"], severity="DRIVABLE")
        advance_clock("2026-08-05T09:02:00Z")
        # Spread every step onto its own logical-clock instant so the
        # created_at-ascending audit order is fully determined.
        call, dispatch = drive_call_on_site(
            call, tech["id"], tech_headers, "2026-08-05T09:00:00Z",
            "2026-08-05T13:00:00Z", accept_at="2026-08-05T09:03:00Z",
            depart_at="2026-08-05T09:04:00Z", arrive_at="2026-08-05T09:05:00Z")
        advance_clock("2026-08-05T09:06:00Z")
        diagnose_call(call["id"], tech_headers, diagnosis_summary="fuse")
        advance_clock("2026-08-05T09:07:00Z")
        start_repair(call["id"], tech_headers)
        advance_clock("2026-08-05T09:08:00Z")
        complete_repair(call["id"], tech_headers, 0.5, 90020)

        events, meta = validate_paginated(
            api.list_service_call_events(call["id"], DISPATCHER,
                                         params={"limit": 100}))
        types = [e["event_type"] for e in events]
        assert types == [
            "CALL_RECEIVED", "TRIAGED", "DISPATCH_CREATED",
            "DISPATCH_ACCEPTED", "DISPATCH_DEPARTED", "DISPATCH_ARRIVED",
            "DIAGNOSED", "REPAIR_STARTED", "REPAIR_COMPLETED",
        ], f"audit trail must list every transition in order, got {types}"
        for event in events:
            assert_call_event(event)
