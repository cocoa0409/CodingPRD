"""Rooms, surgical case creation, buffered-overlap scheduling, and the
OCC-guarded reschedule with its dependent-window re-derivation."""
from test_helpers import (
    CLOCK_DEFAULT,
    ApiErrorId,
    assert_same_instant,
    assert_surgical_case,
    coordinator,
    create_case,
    create_room,
    get_success_data,
    make_scheduler_headers,
    setup_approved_request,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_access_pass_payload,
    create_case_payload,
    reschedule_case_payload,
)
from test_helpers.factories import create_case_payload


def _create_case_pair_room():
    return create_room("OR-1", 30)


class TestCaseCreation:
    def test_case_create_computed_and_system_fields(self, api):
        """PRD: "New cases begin `SCHEDULED`, with `actual_start_at` and
        `actual_end_at` null, `delay_minutes_provisional` and
        `vendor_delay_minutes_provisional` at 0, and
        `vendor_delay_minutes_final` null until completion."
        PRD: "Before any clock call has been made, the current time is exactly
        2026-08-01T00:00:00Z."

        Design: Corner/entities/case_create_computed_and_system_fields
        """
        room = _create_case_pair_room()
        case = validate_success(
            api.create_case(create_case_payload(room["id"], case_number="C-1"),
                            make_scheduler_headers()), 201)
        assert_surgical_case(case)
        assert case["status"] == "SCHEDULED"
        assert case["actual_start_at"] is None
        assert case["actual_end_at"] is None
        assert case["delay_minutes_provisional"] == 0
        assert case["vendor_delay_minutes_provisional"] == 0
        assert case["vendor_delay_minutes_final"] is None
        assert_same_instant(case["created_at"], CLOCK_DEFAULT, "case.created_at")

    def test_create_case_missing_case_number_returns_400(self, api):
        """PRD: "**Body well-formedness** — the request body parses, contains
        every required field, and every field has a valid type and, where
        enumerated, a valid enum member, else `ERR_VALIDATION` (400)."
        PRD: "Each case carries a unique `case_number`"

        Design: Corner/entities/create_case_missing_case_number_returns_400
        """
        room = _create_case_pair_room()
        payload = create_case_payload(room["id"], case_number="C-1")
        del payload["case_number"]
        resp = api.create_case(payload, make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _rows, meta = validate_paginated(
            api.list_cases(make_scheduler_headers()))
        assert meta["total_count"] == 0, "no case may be persisted"

    def test_duplicate_case_number_rejected(self, api):
        """PRD: "Each case carries a unique `case_number` — duplicates are
        rejected with `ERR_DUPLICATE_CASE_NUMBER` (409)"

        Design: Corner/validations/duplicate_case_number_rejected
        """
        r1 = create_room("OR-1", 30)
        r2 = create_room("OR-2", 30)
        get_success_data(
            api.create_case(create_case_payload(r1["id"], case_number="C-1"),
                            make_scheduler_headers()), 201)
        resp = api.create_case(
            create_case_payload(r2["id"], case_number="C-1",
                                scheduled_start_at="2026-08-04T09:00:00Z",
                                scheduled_end_at="2026-08-04T12:00:00Z"),
            make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER)
        _rows, meta = validate_paginated(
            api.list_cases(make_scheduler_headers()))
        assert meta["total_count"] == 1, \
            "uniqueness is global, not per room or per day"


class TestRoomBufferedOverlap:
    """Difficulty instance: pairwise buffered half-open conflict on ORRoom."""

    def test_room_gap_equal_to_buffer_is_allowed(self, api):
        """PRD: "The window must also fit the room under buffered half-open
        semantics: two cases in the same room coexist without conflict only
        when one begins at or after the other's scheduled end plus the room's
        `turnover_buffer_minutes`, and only cases that still occupy the room —
        those `SCHEDULED` or `IN_PROGRESS` — participate in the check."

        Design: Difficulty/resource_temporal_overlap/or_room_buffered_half_open_conflict
        """
        room = _create_case_pair_room()
        get_success_data(
            api.create_case(
                create_case_payload(room["id"], case_number="C-A",
                                    scheduled_start_at="2026-08-03T09:00:00Z",
                                    scheduled_end_at="2026-08-03T11:00:00Z"),
                make_scheduler_headers()), 201)
        # Case B begins exactly buffer (30 min) after case A's end: allowed.
        case_b = validate_success(
            api.create_case(
                create_case_payload(room["id"], case_number="C-B",
                                    procedure_type="TOTAL_HIP",
                                    surgeon_name="Dr. B",
                                    scheduled_start_at="2026-08-03T11:30:00Z",
                                    scheduled_end_at="2026-08-03T13:00:00Z"),
                make_scheduler_headers()), 201)
        assert case_b["status"] == "SCHEDULED", \
            "a gap exactly equal to the turnover buffer satisfies the rule"

    def test_room_gap_below_buffer_is_rejected(self, api):
        """PRD: "The window must also fit the room under buffered half-open
        semantics: two cases in the same room coexist without conflict only
        when one begins at or after the other's scheduled end plus the room's
        `turnover_buffer_minutes`, and only cases that still occupy the room —
        those `SCHEDULED` or `IN_PROGRESS` — participate in the check. A
        colliding window is rejected with `ERR_ROOM_TIME_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/or_room_buffered_half_open_conflict
        """
        room = _create_case_pair_room()
        get_success_data(
            api.create_case(
                create_case_payload(room["id"], case_number="C-A",
                                    scheduled_start_at="2026-08-03T09:00:00Z",
                                    scheduled_end_at="2026-08-03T11:00:00Z"),
                make_scheduler_headers()), 201)
        get_success_data(
            api.create_case(
                create_case_payload(room["id"], case_number="C-B",
                                    scheduled_start_at="2026-08-03T11:30:00Z",
                                    scheduled_end_at="2026-08-03T13:00:00Z"),
                make_scheduler_headers()), 201)
        # Case C starts one minute short of the required buffer: rejected.
        resp = api.create_case(
            create_case_payload(room["id"], case_number="C-C",
                                procedure_type="TOTAL_HIP", surgeon_name="Dr. C",
                                scheduled_start_at="2026-08-03T11:29:00Z",
                                scheduled_end_at="2026-08-03T13:00:00Z"),
            make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)
        _rows, meta = validate_paginated(
            api.list_cases(make_scheduler_headers(),
                           params={"or_room_id": room["id"]}))
        assert meta["total_count"] == 2, "the colliding case must not persist"


class TestReschedule:
    def test_reschedule_stale_version_returns_412(self, api):
        """PRD: "A reschedule request must carry `expected_case_version` equal
        to the case's current `version`."
        PRD: "if the case's version has advanced since that observation, the
        reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD: "The case's `version` increments by one"

        Design: Corner/complexity_layers/reschedule_stale_version_returns_412
        """
        room = _create_case_pair_room()
        case = create_case(room["id"], case_number="C-1")
        observed_version = case["version"]

        moved = validate_success(
            api.reschedule_case(
                case["id"],
                reschedule_case_payload(observed_version),
                make_scheduler_headers()))
        assert moved["version"] == observed_version + 1, \
            "a successful reschedule increments the case version by one"
        assert_same_instant(moved["scheduled_start_at"],
                            "2026-08-05T14:00:00Z", "case.scheduled_start_at")

        # Replaying the stale observed version is rejected.
        resp = api.reschedule_case(
            case["id"],
            reschedule_case_payload(
                observed_version,
                scheduled_start_at="2026-08-06T14:00:00Z",
                scheduled_end_at="2026-08-06T17:00:00Z"),
            make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_case(case["id"], coordinator()))
        assert_same_instant(after["scheduled_start_at"],
                            "2026-08-05T14:00:00Z", "case.scheduled_start_at")

    def test_reschedule_recomputes_dependent_windows(self, api):
        """PRD: "The case's `version` increments by one, and the new schedule
        re-derives everything pinned to it: each linked loaner request in
        `APPROVED` has its `required_delivery_by` recomputed from the new
        start; the trays of those requests have both
        `required_sterile_ready_by` and `projected_sterile_ready_at` recomputed
        and each linked request's readiness re-derived; whenever that
        re-derivation flips an `APPROVED` request into `AT_RISK` or `NOT_READY`
        and the new scheduled start is no more than twenty-four hours away, the
        system opens an escalation automatically, typed by cause; and every
        access pass of the case still `REQUESTED` or `APPROVED` has its
        `window_start_at` and `window_end_at` recomputed."
        PRD: "`window_start_at` is the case's `scheduled_start_at` minus two
        hours (120 minutes) and is inclusive, while `window_end_at` is the
        case's `scheduled_end_at` plus thirty minutes and is exclusive"

        Design: Corner/complexity_layers/reschedule_recomputes_dependent_windows
        """
        world = setup_approved_request()
        rep = world["rep"]
        case = world["case"]
        request = world["request"]
        tray = world["trays"][0]
        pass_resp = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                coordinator()), 201)
        get_success_data(
            api.decide_access_pass(pass_resp["id"], {"decision": "APPROVE"},
                                   coordinator()))

        moved = validate_success(
            api.reschedule_case(
                case["id"],
                reschedule_case_payload(
                    case["version"],
                    scheduled_start_at="2026-08-04T09:00:00Z",
                    scheduled_end_at="2026-08-04T12:00:00Z"),
                make_scheduler_headers()))
        assert moved["version"] == case["version"] + 1

        # Request deadline: new start minus the 24-hour URGENT lead.
        req_after = validate_success(api.get_request(request["id"],
                                                     make_scheduler_headers()))
        assert_same_instant(req_after["required_delivery_by"],
                            "2026-08-03T09:00:00Z",
                            "request.required_delivery_by")
        # Tray sterile window: new start minus the one-hour prep buffer.
        tray_after = validate_success(api.get_tray(tray["id"],
                                                   make_scheduler_headers()))
        assert_same_instant(tray_after["required_sterile_ready_by"],
                            "2026-08-04T08:00:00Z",
                            "tray.required_sterile_ready_by")
        # Pass window: two hours lead / thirty minutes trail around the new
        # window.
        pass_after = validate_success(
            api.get_access_pass(pass_resp["id"], make_scheduler_headers()))
        assert_same_instant(pass_after["window_start_at"],
                            "2026-08-04T07:00:00Z", "pass.window_start_at")
        assert_same_instant(pass_after["window_end_at"],
                            "2026-08-04T12:30:00Z", "pass.window_end_at")


class TestCaseCompletion:
    def test_case_complete_twice_rejected(self, api):
        """PRD: "Completing an `IN_PROGRESS` case stamps `actual_end_at` and
        computes the final vendor attribution"
        PRD: "An `ORScheduler` may start only a `SCHEDULED` case, else
        `ERR_CASE_INVALID_STATE`."
        PRD: "if no events exist at all, it inherits
        `vendor_delay_minutes_provisional`."

        Design: Corner/state_machines/case_complete_twice_rejected
        """
        room = _create_case_pair_room()
        case = create_case(room["id"], case_number="C-1")
        get_success_data(api.set_clock("2026-08-03T09:00:00Z", coordinator()))
        get_success_data(api.start_case(case["id"], {},
                                        make_scheduler_headers()))
        get_success_data(api.set_clock("2026-08-03T12:30:00Z", coordinator()))
        completed = get_success_data(api.complete_case(case["id"],
                                                       make_scheduler_headers()))
        assert completed["status"] == "COMPLETED"
        assert completed["vendor_delay_minutes_final"] == 0, \
            "no delay events: final attribution inherits the 0 provisional"

        resp = api.complete_case(case["id"], make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
        resp2 = api.start_case(case["id"], {}, make_scheduler_headers())
        validate_error(resp2, ApiErrorId.ERR_CASE_INVALID_STATE)
        assert validate_success(api.get_case(case["id"],
                                             coordinator()))["status"] == "COMPLETED"
