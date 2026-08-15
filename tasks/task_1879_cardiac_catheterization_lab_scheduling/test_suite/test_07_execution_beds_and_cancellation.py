"""Case start/complete/cancel, recovery-bed lifecycle, and room status cycles."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    cancel_case,
    complete_case,
    create_cardiologist,
    create_circulating_nurse,
    create_device_lot,
    create_recovery_bed,
    create_room,
    create_scrub_technologist,
    get_bed,
    get_lot,
    post_case,
    reserve_device_usage,
    schedule_case_payload,
    set_clock,
    setup_case_workspace,
    setup_completed_workspace,
    setup_in_progress_workspace,
    staff_case,
    start_case,
    validate_error,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
TECHNOLOGIST = TEST_USERS["technologist_headers"]
NURSE_MANAGER = TEST_USERS["nurse_manager_headers"]


class TestBedReleaseProjectionVariants:
    def test_bed_window_scheduled_variant_before_completion(self, api):
        """PRD §3.3: "The secured bed moves `AVAILABLE` → `RESERVED`, records the
        case in `held_case_id`, and projects its recovery window with
        `window_start` at the case's `scheduled_end` and `window_end` ninety
        minutes later — the scheduled variant of the bed projection."

        Design: Difficulty/dual_variant_calc/bed_release_scheduled_vs_actual_variant
        """
        workspace = setup_case_workspace(priority="ELECTIVE")
        case = workspace["case"]
        assert_instant_equals(case["scheduled_end"], "2026-08-10T10:30:00Z")
        bed = get_bed(workspace["bed"]["id"])
        assert bed["status"] == "RESERVED"
        assert bed["held_case_id"] == case["id"]
        assert_instant_equals(bed["window_start"], "2026-08-10T10:30:00Z")
        assert_instant_equals(bed["window_end"], "2026-08-10T12:00:00Z")
        # scheduled variant: scheduled_end 10:30 + 90 minutes.

    def test_bed_window_actual_variant_after_completion(self, api):
        """PRD §3.7: "The recovery bed committed to the case moves `RESERVED` →
        `OCCUPIED`, and its window is recomputed from the actual finish:
        `window_start` becomes the case's `actual_end` and `window_end` ninety
        minutes after it."
        PRD §3.7: "In every variant the committed recovery window is ninety minutes
        long, anchored at the case's `scheduled_end` while the bed is merely
        reserved and re-anchored at `actual_end` upon occupation."

        Design: Difficulty/dual_variant_calc/bed_release_scheduled_vs_actual_variant
        """
        set_clock("2026-08-10T08:00:00Z")
        workspace = setup_case_workspace(priority="ELECTIVE")
        case = workspace["case"]
        scrub_tech = create_scrub_technologist()
        nurse = create_circulating_nurse()
        staff_case(case["id"], scrub_tech["id"], nurse["id"])
        set_clock("2026-08-10T10:00:00Z")
        start_case(case["id"], workspace["physician"]["id"])
        set_clock("2026-08-10T11:30:00Z")
        completed = complete_case(case["id"], workspace["physician"]["id"])
        assert completed["status"] == "COMPLETED"
        assert_instant_equals(completed["actual_end"], "2026-08-10T11:30:00Z")
        bed = get_bed(workspace["bed"]["id"])
        assert bed["status"] == "OCCUPIED"
        # actual variant: 11:30 + 90 minutes, diverging from the scheduled 12:00.
        assert_instant_equals(bed["window_start"], "2026-08-10T11:30:00Z")
        assert_instant_equals(bed["window_end"], "2026-08-10T13:00:00Z")


class TestCompletionCascade:
    def _setup_in_progress_with_usage(self, api):
        set_clock("2026-08-10T08:00:00Z")
        workspace = setup_in_progress_workspace(procedure_type="DEVICE_IMPLANT")
        lot = create_device_lot(device_type="PACEMAKER_LEAD", model_number="PL-7",
                                lot_number="LOT-L", ownership="CONSIGNMENT",
                                quantity_on_hand=4, reorder_threshold=3)
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 3)
        return workspace, lot, usage

    def test_completion_releases_reserved_usage_and_restores_lot(self, api):
        """PRD §3.7: "Every still-`ASSIGNED` staff assignment of the case is
        `RELEASED`, and every still-`RESERVED` device usage is `RELEASED`,
        recomputing each affected lot's `allocated_units` and derived `status`."
        PRD §3.5: "Releasing a reservation — manually by the technologist, or
        automatically when the case is bumped, cancelled, or completed — returns
        the units to the available pool: the usage moves `RESERVED` → `RELEASED`,
        `allocated_units` falls by the released `quantity`, `quantity_on_hand` is
        untouched, and the status recomputes."

        Design: Difficulty/transitive_cascade/completion_cascade_releases_reservation_and_restores_lot_status
        """
        workspace, lot, usage = self._setup_in_progress_with_usage(api)
        pre = get_lot(lot["id"])
        assert pre["available_units"] == 1
        assert pre["status"] == "LOW_STOCK", "available 4 - 3 == 1 < threshold 3"

        complete_case(workspace["case"]["id"], workspace["physician"]["id"])

        usages = api.list_lot_usages(lot["id"], TECHNOLOGIST).json()["data"]
        assert usages[0]["id"] == usage["id"]
        assert usages[0]["status"] == "RELEASED", "auto-release on completion"
        post = get_lot(lot["id"])
        assert post["allocated_units"] == 0
        assert post["quantity_on_hand"] == 4, "release does not consume stock"
        assert post["available_units"] == 4
        assert post["status"] == "ACTIVE", "available 4 >= threshold 3"

    def test_completion_occupies_recovery_bed(self, api):
        """PRD §3.7: "Completing moves the case to `COMPLETED`, stamps `actual_end`
        from the logical clock — null until now — and settles everything the case
        was holding. The recovery bed committed to the case moves `RESERVED` →
        `OCCUPIED`, and its window is recomputed from the actual finish:
        `window_start` becomes the case's `actual_end` and `window_end` ninety
        minutes after it."

        Design: Difficulty/transitive_cascade/completion_cascade_releases_reservation_and_restores_lot_status
        """
        workspace, _, _ = self._setup_in_progress_with_usage(api)
        completed = complete_case(workspace["case"]["id"],
                                  workspace["physician"]["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["actual_end"] is not None
        bed = get_bed(workspace["bed"]["id"])
        assert bed["status"] == "OCCUPIED"
        assert bed["held_case_id"] == workspace["case"]["id"]


class TestCancellation:
    def test_cancel_completed_case_returns_invalid_state(self, api):
        """PRD §3.7: "A scheduler can cancel a case from `POSTED`, `SCHEDULED`, or
        `BUMPED`, moving it to `CANCELLED`; attempts from `IN_PROGRESS`,
        `COMPLETED`, or an already-`CANCELLED` case are refused with
        `ERR_CASE_INVALID_STATE`."

        Design: Corner/state_machines/cancel_completed_case_returns_invalid_state
        """
        workspace = setup_completed_workspace()
        resp = api.cancel_case(workspace["case"]["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)
        current = validate_success(api.get_case(workspace["case"]["id"], SCHEDULER))
        assert current["status"] == "COMPLETED"


class TestBedLifecycle:
    def test_occupied_bed_release_valid_transition(self, api):
        """PRD §3.7: "Releasing a bed that is not `OCCUPIED` is refused with
        `ERR_BED_INVALID_STATE`; a valid release returns the bed `OCCUPIED` →
        `AVAILABLE` and clears `held_case_id`, `window_start`, and `window_end` to
        null."

        Design: Corner/state_machines/occupied_bed_release_valid_transition
        """
        workspace = setup_completed_workspace()
        bed = workspace["bed"]
        assert get_bed(bed["id"])["status"] == "OCCUPIED"
        released = validate_success(api.release_recovery_bed(bed["id"],
                                                             NURSE_MANAGER))
        assert released["status"] == "AVAILABLE"
        assert released["held_case_id"] is None
        assert released["window_start"] is None
        assert released["window_end"] is None

    def test_release_available_bed_returns_invalid_state(self, api):
        """PRD §3.7: "Releasing a bed that is not `OCCUPIED` is refused with
        `ERR_BED_INVALID_STATE`"

        Design: Corner/state_machines/release_available_bed_returns_invalid_state
        """
        bed = create_recovery_bed("Bed 1")
        resp = api.release_recovery_bed(bed["id"], NURSE_MANAGER)
        validate_error(resp, ApiErrorId.ERR_BED_INVALID_STATE, expected_status=409)
        assert get_bed(bed["id"])["status"] == "AVAILABLE"

    def test_reserved_bed_cannot_go_out_of_service(self, api):
        """PRD §3.1: "The nurse manager can take a bed `OUT_OF_SERVICE` and bring
        it back to `AVAILABLE`, but only an `AVAILABLE` bed may be taken out of
        service — attempting it on a `RESERVED` or `OCCUPIED` bed is refused with
        `ERR_RESOURCE_IN_USE` — and setting the status the bed already holds is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/reserved_bed_cannot_go_out_of_service
        """
        workspace = setup_case_workspace()
        bed = workspace["bed"]
        assert get_bed(bed["id"])["status"] == "RESERVED"
        resp = api.patch_recovery_bed(bed["id"], {"status": "OUT_OF_SERVICE"},
                                      NURSE_MANAGER)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_IN_USE, expected_status=409)
        assert get_bed(bed["id"])["status"] == "RESERVED"


class TestRoomStatusCycle:
    def test_room_out_of_service_and_return_cycle(self, api):
        """PRD §3.1: "The scheduler can later take a room `OUT_OF_SERVICE` and
        return it to `ACTIVE`, but a room may only be taken out of service when no
        case assigned to it is currently `SCHEDULED` or `IN_PROGRESS` — otherwise
        the change is refused with `ERR_RESOURCE_IN_USE`. Asking for the status the
        room already has is not treated as a no-op; it is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/room_out_of_service_and_return_cycle
        """
        room = create_room(room_name="Lab 1")
        out = validate_success(
            api.patch_room(room["id"], {"status": "OUT_OF_SERVICE"}, SCHEDULER))
        assert out["status"] == "OUT_OF_SERVICE"
        resp = api.patch_room(room["id"], {"status": "OUT_OF_SERVICE"}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        back = validate_success(
            api.patch_room(room["id"], {"status": "ACTIVE"}, SCHEDULER))
        assert back["status"] == "ACTIVE"

    def test_room_deactivation_with_scheduled_case_returns_resource_in_use(self, api):
        """PRD §3.1: "The scheduler can later take a room `OUT_OF_SERVICE` and
        return it to `ACTIVE`, but a room may only be taken out of service when no
        case assigned to it is currently `SCHEDULED` or `IN_PROGRESS` — otherwise
        the change is refused with `ERR_RESOURCE_IN_USE`."

        Design: Corner/state_machines/room_deactivation_with_scheduled_case_returns_resource_in_use
        """
        workspace = setup_case_workspace()
        room = workspace["room"]
        resp = api.patch_room(room["id"], {"status": "OUT_OF_SERVICE"}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_IN_USE, expected_status=409)
        cancel_case(workspace["case"]["id"])
        patched = validate_success(
            api.patch_room(room["id"], {"status": "OUT_OF_SERVICE"}, SCHEDULER))
        assert patched["status"] == "OUT_OF_SERVICE"


class TestImmediateConsistency:
    def test_schedule_mutation_visible_immediately_in_response_and_read(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.3: "The secured bed moves `AVAILABLE` → `RESERVED`, records the case
        in `held_case_id`, and projects its recovery window with `window_start` at
        the case's `scheduled_end` and `window_end` ninety minutes later — the
        scheduled variant of the bed projection."

        Design: Corner/consistency_model/schedule_mutation_visible_immediately_in_response_and_read
        """
        physician = create_cardiologist()
        room = create_room(room_name="Lab 1")
        bed = create_recovery_bed("Bed 1")
        case = post_case(physician["id"])
        resp = api.schedule_case(
            case["id"],
            schedule_case_payload(room["id"], "2026-08-10T09:00:00Z",
                                  bed_id=bed["id"]),
            SCHEDULER)
        scheduled = validate_success(resp, 200)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["lab_id"] == room["id"]
        assert_instant_equals(scheduled["scheduled_end"], "2026-08-10T10:30:00Z")

        fetched = validate_success(api.get_case(case["id"], SCHEDULER))
        assert fetched["status"] == scheduled["status"]
        assert fetched["lab_id"] == scheduled["lab_id"]
        assert fetched["scheduled_end"] == scheduled["scheduled_end"]
        assert get_bed(bed["id"])["status"] == "RESERVED", \
            "the side effect is visible immediately"
