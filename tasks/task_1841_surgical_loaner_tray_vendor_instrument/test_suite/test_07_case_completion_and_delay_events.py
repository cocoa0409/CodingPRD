"""Case completion, the tray cascade, and delay-event recording with its
vendor-attribution rules (provisional vs final variants)."""
from test_helpers import (
    ApiErrorId,
    add_tray,
    coordinator,
    create_case,
    create_request,
    create_room,
    create_vendor,
    deliver_and_verify,
    get_success_data,
    make_nurse_headers,
    make_scheduler_headers,
    open_turn,
    set_clock,
    setup_approved_request,
    start_cycle_at,
    sterilize_and_stage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_delay_event_payload, \
    start_case_payload

SCHEDULER = make_scheduler_headers()
NURSE = make_nurse_headers()


class TestReadyOnTimeCase:
    def test_delay_zero_for_ready_ontime_case(self, api):
        """PRD: "A successful start stamps `actual_start_at` from the clock,
        computes `delay_minutes_provisional` as the whole minutes by which the
        actual start passed the scheduled start (never below zero), and
        applies the all-or-nothing provisional attribution:
        `vendor_delay_minutes_provisional` equals the full provisional delay
        when the override was used, and 0 otherwise."
        PRD: "if no events exist at all, it inherits
        `vendor_delay_minutes_provisional`."
        PRD: "Trays of linked requests that stood `STAGED` move to `IN_USE`."

        Design: Corner/calculations/delay_zero_for_ready_ontime_case
        """
        world = setup_approved_request()
        tray = world["trays"][0]
        deliver_and_verify(world, at="2026-08-02T08:00:00Z")
        sterilize_and_stage(world, tray["id"])
        ready = validate_success(
            api.get_request(world["request"]["id"], SCHEDULER))
        assert ready["readiness"] == "READY"

        started = validate_success(
            api.start_case(world["case"]["id"], {}, SCHEDULER))
        assert started["status"] == "IN_PROGRESS", \
            "a READY request lets the case start with no override"
        assert started["delay_minutes_provisional"] == 0
        assert started["vendor_delay_minutes_provisional"] == 0
        tray_now = validate_success(api.get_tray(tray["id"], SCHEDULER))
        assert tray_now["status"] == "IN_USE"

        set_clock("2026-08-03T12:30:00Z")
        completed = validate_success(api.complete_case(world["case"]["id"],
                                                       SCHEDULER))
        assert completed["vendor_delay_minutes_final"] == 0


class TestDelayEventRecording:
    def _started_case(self, api, start_at="2026-08-03T09:00:00Z"):
        room = create_room()
        case = create_case(room["id"], case_number="C-1")
        set_clock(start_at)
        get_success_data(api.start_case(case["id"], {}, SCHEDULER))
        return case

    def test_delay_event_zero_minutes_rejected(self, api):
        """PRD: "An `ORScheduler` or `ORCirculatorNurse` records a delay event
        with a `cause` of `VENDOR_LATE_DELIVERY`, `STERILIZATION_TURNAROUND`,
        `REP_ACCESS_ISSUE`, `PATIENT`, `STAFFING`, or `OTHER`, and a `minutes`
        value that must be greater than zero, else `ERR_DELAY_EVENT_INVALID`
        (422)."

        Design: Corner/validations/delay_event_zero_minutes_rejected
        """
        case = self._started_case(api)
        resp = api.create_delay_event(
            case["id"], create_delay_event_payload("PATIENT", 0), SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_DELAY_EVENT_INVALID)

        recorded = validate_success(
            api.create_delay_event(
                case["id"], create_delay_event_payload("PATIENT", 1),
                SCHEDULER), 201)
        assert recorded["cause"] == "PATIENT"
        assert recorded["recorded_by_role"] == "ORScheduler"
        _rows, meta = validate_paginated(
            api.list_delay_events(SCHEDULER, params={"case_id": case["id"]}))
        assert meta["total_count"] == 1

    def test_delay_event_vendor_cause_requires_link_rejected(self, api):
        """PRD: "For the three vendor-attributable causes
        (`VENDOR_LATE_DELIVERY`, `STERILIZATION_TURNAROUND`,
        `REP_ACCESS_ISSUE`) the event must name an `attributable_request_id`,
        and that request must be one of this case's own loaner requests; a
        missing or foreign link fails with `ERR_DELAY_REQUEST_LINK` (422)."

        Design: Corner/validations/delay_event_vendor_cause_requires_link_rejected
        """
        vendor = create_vendor()
        room = create_room()
        case1 = create_case(room["id"], case_number="C-1",
                            scheduled_start_at="2026-08-03T09:00:00Z",
                            scheduled_end_at="2026-08-03T10:00:00Z")
        case2 = create_case(room["id"], case_number="C-2",
                            scheduled_start_at="2026-08-03T11:00:00Z",
                            scheduled_end_at="2026-08-03T12:00:00Z")
        rq1 = create_request(case1["id"], vendor["id"], "STANDARD")
        add_tray(rq1["id"], tray_code="T-1", declared_instrument_count=5,
                 replacement_value_cents=1000)
        set_clock("2026-08-03T09:00:00Z")
        get_success_data(api.start_case(case1["id"], {}, SCHEDULER))
        set_clock("2026-08-03T11:00:00Z")
        get_success_data(api.start_case(case2["id"], {}, SCHEDULER))

        # Vendor-flavored cause with no link at all.
        resp = api.create_delay_event(
            case2["id"],
            create_delay_event_payload("VENDOR_LATE_DELIVERY", 10),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_DELAY_REQUEST_LINK)
        # A link to a request of a different case is equally foreign.
        resp2 = api.create_delay_event(
            case2["id"],
            create_delay_event_payload("VENDOR_LATE_DELIVERY", 10,
                                       attributable_request_id=rq1["id"]),
            SCHEDULER)
        validate_error(resp2, ApiErrorId.ERR_DELAY_REQUEST_LINK)

    def test_delay_event_overattribution_rejected(self, api):
        """PRD: "Attribution is capped: after inserting the event, the sum of
        `minutes` over all vendor-cause events of the case must not exceed the
        case's `delay_minutes_provisional`, else the recording is rejected
        with `ERR_CASE_DELAY_OVERATTRIBUTED` (422)."

        Design: Corner/validations/delay_event_overattribution_rejected
        """
        # Case started thirty minutes late with a readiness override, so the
        # provisional delay (and the vendor-attribution budget) is 30.
        world = setup_approved_request()
        set_clock("2026-08-03T09:30:00Z")
        get_success_data(
            api.start_case(world["case"]["id"],
                           start_case_payload(
                               override_readiness=True,
                               override_reason="tray not delivered"),
                           SCHEDULER))
        case_id = world["case"]["id"]
        rq_id = world["request"]["id"]

        first = validate_success(
            api.create_delay_event(
                case_id,
                create_delay_event_payload("VENDOR_LATE_DELIVERY", 20,
                                           attributable_request_id=rq_id),
                SCHEDULER), 201)
        assert first["cause"] == "VENDOR_LATE_DELIVERY"

        # 20 already attributed; another 20 would total 40 > 30.
        resp = api.create_delay_event(
            case_id,
            create_delay_event_payload("STERILIZATION_TURNAROUND", 20,
                                       attributable_request_id=rq_id),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_CASE_DELAY_OVERATTRIBUTED)
        _rows, meta = validate_paginated(
            api.list_delay_events(SCHEDULER, params={"case_id": case_id}))
        assert meta["total_count"] == 1


class TestDelayAttributionVariants:
    """Difficulty instance: provisional all-or-nothing vs final per-cause
    attribution on identical case data."""

    def _override_started_world(self, api):
        """Tray delivered very late (08:45 on case day), still PROCESSING at
        case time; case started at 09:50 under a readiness override."""
        world = setup_approved_request()
        deliver_and_verify(world, at="2026-08-03T08:45:00Z")
        turn = open_turn(world["trays"][0]["id"])
        start_cycle_at(world, turn["id"], "2026-08-03T09:15:00Z")
        set_clock("2026-08-03T09:50:00Z")
        started = validate_success(
            api.start_case(world["case"]["id"],
                           start_case_payload(
                               override_readiness=True,
                               override_reason="surgeon proceeds without tray"),
                           SCHEDULER))
        return world, started

    def test_case_delay_provisional_all_or_nothing_with_override(self, api):
        """PRD: "A successful start stamps `actual_start_at` from the clock,
        computes `delay_minutes_provisional` as the whole minutes by which the
        actual start passed the scheduled start (never below zero), and
        applies the all-or-nothing provisional attribution:
        `vendor_delay_minutes_provisional` equals the full provisional delay
        when the override was used, and 0 otherwise."

        Design: Difficulty/dual_variant_calc/case_delay_provisional_vs_final_attribution
        """
        _world, started = self._override_started_world(api)
        assert started["delay_minutes_provisional"] == 50, \
            "09:50 actual start against the 09:00 scheduled start"
        assert started["vendor_delay_minutes_provisional"] == 50, \
            "override used: the full provisional delay is vendor-attributed"
        assert started["vendor_delay_minutes_final"] is None, \
            "final attribution does not exist before completion"

    def test_case_delay_final_attribution_excludes_non_vendor_causes(self, api):
        """PRD: "if at least one delay event exists,
        `vendor_delay_minutes_final` is the sum of `minutes` over the
        vendor-cause events — `VENDOR_LATE_DELIVERY`,
        `STERILIZATION_TURNAROUND`, and `REP_ACCESS_ISSUE` — capped at
        `delay_minutes_provisional`; if no events exist at all, it inherits
        `vendor_delay_minutes_provisional`."

        Design: Difficulty/dual_variant_calc/case_delay_provisional_vs_final_attribution
        """
        world, started = self._override_started_world(api)
        case_id = world["case"]["id"]
        rq_id = world["request"]["id"]
        assert started["vendor_delay_minutes_provisional"] == 50

        # 30 vendor-cause minutes + 20 patient minutes.
        get_success_data(
            api.create_delay_event(
                case_id,
                create_delay_event_payload("STERILIZATION_TURNAROUND", 30,
                                           attributable_request_id=rq_id),
                SCHEDULER), 201)
        get_success_data(
            api.create_delay_event(
                case_id, create_delay_event_payload("PATIENT", 20), NURSE),
            201)

        set_clock("2026-08-03T12:30:00Z")
        completed = validate_success(api.complete_case(case_id, SCHEDULER))
        assert completed["status"] == "COMPLETED"
        assert completed["vendor_delay_minutes_final"] == 30, \
            "only the vendor-cause event counts; PATIENT minutes are excluded"
        assert completed["vendor_delay_minutes_final"] != \
            completed["vendor_delay_minutes_provisional"], \
            "final adjudication (30) diverges from the provisional 50"
