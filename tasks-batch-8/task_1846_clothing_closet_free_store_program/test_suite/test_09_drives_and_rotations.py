"""Special drives: lazy status advancement, manual close, buffered window
conflicts; seasonal rotations: window gate and the two-phase move cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_special_drive,
    create_drive,
    create_rotation,
    create_zone,
    get_item,
    get_zone,
    grade_items,
    open_batch_in_sort,
    set_clock,
    setup_sorting_staff,
    stock_items,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

WINTER_COAT = {"category": "COATS", "season": "WINTER", "quality_grade": "GOOD"}


class TestDriveLifecycle:
    def test_drive_lazy_status_advancement(self, api):
        """PRD: "A new drive opens `UPCOMING`."
        PRD: "A special drive moves from `UPCOMING` to `ACTIVE` when the clock
        stands within its window, and from `ACTIVE` to `CLOSED` once the window
        has passed; these advancements occur whenever the drive is read and
        whenever a check-in evaluates the drive pools available to a visit."

        Design: Corner/state_machines/drive_lazy_status_advancement
        """
        drive = create_drive("WINTER_COATS", "COATS", "2026-08-05T00:00:00Z",
                             "2026-08-10T00:00:00Z", bonus_items_per_client=1)
        assert_special_drive(drive)
        assert drive["status"] == "UPCOMING"

        read = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert read["status"] == "UPCOMING", "start_at not reached"

        set_clock("2026-08-06T00:00:00Z")
        read = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert read["status"] == "ACTIVE"

        set_clock("2026-08-11T00:00:00Z")
        read = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert read["status"] == "CLOSED", "window passed"

    def test_drive_manual_close_and_reclose_rejected(self, api):
        """PRD: "A `ProgramAdmin` may also close a drive early from `UPCOMING` or
        `ACTIVE`; closing an already `CLOSED` drive is `ERR_INVALID_STATE`."

        Design: Corner/endpoints/drive_manual_close_and_reclose_rejected
        """
        drive = create_drive("WINTER_COATS", "COATS", "2026-09-01T00:00:00Z",
                             "2026-09-10T00:00:00Z", bonus_items_per_client=1)
        assert drive["status"] == "UPCOMING"

        closed = validate_success(api.close_drive(drive["id"], ADMIN), 200)
        assert closed["status"] == "CLOSED"

        resp = api.close_drive(drive["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDriveWindowBuffer:
    def test_same_type_drive_within_buffer_rejected(self, api):
        """PRD: "Drives of the same `drive_type` may not crowd one another: a new
        drive whose window conflicts with another same-type drive's window inside
        a 7-day buffer is rejected with `ERR_DRIVE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/drive_window_seven_day_buffer_conflict
        """
        create_drive("INTERVIEW_ATTIRE", "INTERVIEW_ATTIRE",
                     "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
                     bonus_items_per_client=2)

        resp = api.create_drive(
            {"drive_type": "INTERVIEW_ATTIRE", "target_category": "INTERVIEW_ATTIRE",
             "start_at": "2026-08-25T00:00:00Z", "end_at": "2026-08-30T00:00:00Z",
             "bonus_items_per_client": 1},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DRIVE_WINDOW_CONFLICT)

    def test_same_type_drive_outside_buffer_and_cross_type_allowed(self, api):
        """PRD: "Drives of the same `drive_type` may not crowd one another: a new
        drive whose window conflicts with another same-type drive's window inside
        a 7-day buffer is rejected with `ERR_DRIVE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/drive_window_seven_day_buffer_conflict
        """
        create_drive("INTERVIEW_ATTIRE", "INTERVIEW_ATTIRE",
                     "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
                     bonus_items_per_client=2)

        outside = validate_success(
            api.create_drive(
                {"drive_type": "INTERVIEW_ATTIRE",
                 "target_category": "INTERVIEW_ATTIRE",
                 "start_at": "2026-08-28T00:00:00Z", "end_at": "2026-09-05T00:00:00Z",
                 "bonus_items_per_client": 1},
                ADMIN),
            201)
        assert outside["status"] == "UPCOMING", "an 8-day gap is outside the buffer"

        cross_type = validate_success(
            api.create_drive(
                {"drive_type": "WINTER_COATS", "target_category": "COATS",
                 "start_at": "2026-08-15T00:00:00Z", "end_at": "2026-08-18T00:00:00Z",
                 "bonus_items_per_client": 1},
                ADMIN),
            201)
        assert cross_type["status"] == "UPCOMING", (
            "different drive_type may overlap freely")


class TestRotationWindow:
    def test_rotation_execute_outside_window_rejected(self, api):
        """PRD: "Executing the rotation requires it to be `SCHEDULED` (otherwise
        `ERR_INVALID_STATE`) and the current instant to lie inside the window,
        boundaries inclusive (otherwise `ERR_ROTATION_OUTSIDE_WINDOW`)."
        PRD: "A scheduled rotation may instead be cancelled, moving it from
        `SCHEDULED` to `CANCELLED` (any other state is `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/rotation_execute_outside_window_rejected
        """
        rotation = create_rotation("WINTER", "2026-09-01T00:00:00Z",
                                   "2026-09-02T00:00:00Z")
        assert rotation["status"] == "SCHEDULED"

        resp = api.execute_rotation(rotation["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROTATION_OUTSIDE_WINDOW)

        cancelled = validate_success(api.cancel_rotation(rotation["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"


class TestRotationCascade:
    def _setup_winter_zone_and_rotations(self, api):
        """WINTER-policy zone (cap 2) with 2 WINTER coats stocked (FULL), plus
        rotations R1 (target SUMMER, window covering the default clock) and R2
        (target WINTER, window 2026-08-03..2026-08-04)."""
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], donor_name="Donor F",
                                   item_count_declared=2)
        items = grade_items(batch["id"], [dict(WINTER_COAT), dict(WINTER_COAT)],
                            staff["headers"])
        zone = create_zone("ZW", "WINTER", 2)
        stock_items([item["id"] for item in items], zone["id"], staff["headers"])
        r1 = create_rotation("SUMMER", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
        r2 = create_rotation("WINTER", "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z")
        return {"staff": staff, "items": items, "zone": zone, "r1": r1, "r2": r2}

    def test_rotation_phase_out_empties_offseason_items(self, api):
        """PRD: "Phase-out comes first: every `STOCKED` item whose `season` is
        neither the `target_season` nor `ALL_SEASON` moves to `OFF_SEASON`,
        leaving its zone — `storage_zone_id` is cleared, the zone's
        `current_stock` is decremented, and its `posture` recomputed, item by
        item."
        PRD: "The rotation stamps `executed_at` and records the phase totals in
        `moved_out_count` and `moved_in_count`."

        Design: Difficulty/transitive_cascade/rotation_phaseout_phasein_posture_cascade
        """
        env = self._setup_winter_zone_and_rotations(api)
        assert get_zone(env["zone"]["id"])["posture"] == "FULL"

        executed = validate_success(api.execute_rotation(env["r1"]["id"], ADMIN), 200)
        assert executed["status"] == "COMPLETED"
        assert executed["moved_out_count"] == 2
        assert executed["moved_in_count"] == 0
        assert executed["executed_at"] is not None

        zone = get_zone(env["zone"]["id"])
        assert zone["current_stock"] == 0
        assert zone["posture"] == "AVAILABLE"
        for item in env["items"]:
            reread = get_item(item["id"])
            assert reread["status"] == "OFF_SEASON"
            assert reread["storage_zone_id"] is None

    def test_rotation_phase_in_restocks_capacity_gated(self, api):
        """PRD: "Phase-in follows: every `OFF_SEASON` item whose `season` equals
        the `target_season` is considered for restocking in creation order,
        oldest first, with no identifier tie-break ever applied. For each item,
        the eligible zones are those whose `season_policy` is the `target_season`
        or `ALL_SEASON` and whose posture is not `FULL`; they are ranked by
        `current_stock` ascending, ties broken by the zone's own creation
        timestamp ascending, and the item is placed into the first zone in that
        ranking — `storage_zone_id` set, `stocked_at` stamped, stock incremented,
        posture recomputed — before the next item is considered."

        Design: Difficulty/transitive_cascade/rotation_phaseout_phasein_posture_cascade
        """
        env = self._setup_winter_zone_and_rotations(api)
        executed_r1 = validate_success(api.execute_rotation(env["r1"]["id"], ADMIN), 200)
        assert executed_r1["moved_out_count"] == 2

        set_clock("2026-08-03T00:00:00Z")
        executed_r2 = validate_success(api.execute_rotation(env["r2"]["id"], ADMIN), 200)
        assert executed_r2["moved_out_count"] == 0
        assert executed_r2["moved_in_count"] == 2, (
            "the phase-in selector restocks both WINTER coats, oldest first")

        zone = get_zone(env["zone"]["id"])
        assert zone["current_stock"] == 2
        assert zone["posture"] == "FULL"
        for item in env["items"]:
            reread = get_item(item["id"])
            assert reread["status"] == "STOCKED"
            assert reread["storage_zone_id"] == env["zone"]["id"]
