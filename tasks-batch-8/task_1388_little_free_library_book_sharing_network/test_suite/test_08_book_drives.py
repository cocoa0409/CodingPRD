"""Book drives: fork-join approval, window semantics, lifecycle cascades."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_drive,
    create_active_school,
    create_active_steward,
    create_open_drive_with_batch,
    create_school,
    get_linked_batch,
    intake_items,
    list_batch_items,
    make_school_liaison_headers,
    make_steward_headers,
    pin_clock,
    propose_drive,
    run_sweep,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _steward_and_school(name_pair=("Join Tester", "Join School"),
                        restricted=None):
    steward = create_active_steward(full_name=name_pair[0])
    school = create_active_school(name=name_pair[1],
                                  restricted_categories=restricted or [])
    return steward, school


class TestForkJoinApproval:
    def test_drive_join_requires_both_approvals_and_creates_linked_batch(
        self, api
    ):
        """PRD §3.7: "Approval is a fork-join across two independent
        dimensions. The school's liaison decides the `school_approval_status` —
        the caller's `X-User-ID` must equal the drive's `school_id` or the
        attempt fails with `ERR_FORBIDDEN_OWNERSHIP` — while a `NetworkAdmin`
        decides the `network_approval_status`; each decision is a `decision` of
        `APPROVE` or `REJECT`."
        PRD §3.7: "Only when both dimensions stand `APPROVED` does the drive
        join into `APPROVED`, and the join mints the drive's linked donation
        batch: a batch with `source_type` `BOOK_DRIVE`, its `drive_id` pointing
        back to the drive, the school's `region_code`, and `RECEIVED` status."

        Design: Corner/state_machines/drive_join_requires_both_approvals_and_creates_linked_batch
        """
        pin_clock()
        steward, school = _steward_and_school()
        drive = propose_drive(school["id"], steward["id"], goal_books=10)

        after_school = validate_success(
            api.drive_school_decision(
                drive["id"], "APPROVE",
                make_school_liaison_headers(school["id"]),
            ),
            200,
        )
        # One dimension approved: the join is not complete.
        assert after_school["status"] == "PROPOSED"
        assert after_school["school_approval_status"] == "APPROVED"
        assert after_school["network_approval_status"] == "PENDING"

        after_network = validate_success(
            api.drive_network_decision(drive["id"], "APPROVE", ADMIN), 200
        )
        assert after_network["status"] == "APPROVED"

        batch = get_linked_batch(drive["id"])
        assert batch["drive_id"] == drive["id"]
        assert batch["source_type"] == "BOOK_DRIVE"
        assert batch["status"] == "RECEIVED"

    def test_drive_reject_makes_terminal_and_blocks_further_decisions(self, api):
        """PRD §3.7: "A `REJECT` from either side moves the drive straight to
        terminal `REJECTED` and marks the deciding dimension `REJECTED`."
        PRD §2.8: "State preconditions. The target entity sits in the exact
        from-state the transition requires — failures are `ERR_INVALID_STATE`
        or `ERR_DRIVE_NOT_OPEN` (409)."

        Design: Corner/state_machines/drive_reject_makes_terminal_and_blocks_further_decisions
        """
        pin_clock()
        steward, school = _steward_and_school(("Reject Tester", "Reject School"))
        drive = propose_drive(school["id"], steward["id"], goal_books=10)

        rejected = validate_success(
            api.drive_school_decision(
                drive["id"], "REJECT",
                make_school_liaison_headers(school["id"]),
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["school_approval_status"] == "REJECTED"

        res = api.drive_network_decision(drive["id"], "APPROVE", ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)

        after = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert after["status"] == "REJECTED"
        assert after["school_approval_status"] == "REJECTED"


class TestDriveWindow:
    def test_drive_window_transitions_via_sweep(self, api):
        """PRD §3.7: "From there the calendar drives the lifecycle: a map sweep
        opens an `APPROVED` drive once the current instant reaches `starts_at`,
        moving it to `OPEN`, and collection closes either manually — the
        coordinator steward or a `NetworkAdmin` moves an `OPEN` drive to
        `COLLECTION_CLOSED` — or automatically when a sweep finds `ends_at`
        reached."
        PRD §3.9: "`APPROVED` drives whose `starts_at` has arrived open; `OPEN`
        drives whose `ends_at` has arrived move to `COLLECTION_CLOSED`".

        Design: Corner/state_machines/drive_window_transitions_via_sweep
        """
        pin_clock()
        steward, school = _steward_and_school(("Window Tester", "Window School"))
        drive = propose_drive(school["id"], steward["id"], goal_books=10,
                              starts_at="2026-09-01T00:00:00Z",
                              ends_at="2026-10-01T00:00:00Z")
        approve_drive(drive["id"], school["id"])

        sweep1 = run_sweep()  # 2026-08-01: starts_at not yet reached
        assert sweep1["opened_drive_count"] == 0

        pin_clock("2026-09-01T00:00:00Z")
        sweep2 = run_sweep()  # at starts_at (inclusive): opens
        assert sweep2["opened_drive_count"] == 1

        pin_clock("2026-10-01T00:00:00Z")
        sweep3 = run_sweep()  # at ends_at (exclusive end reached): closes
        assert sweep3["closed_drive_count"] == 1

        after = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert after["status"] == "COLLECTION_CLOSED"

    def test_drive_window_adjacent_accepted(self, api):
        """PRD §3.7: "One school cannot run overlapping drives: a new window
        that intersects any non-terminal drive of the same school under
        half-open semantics is rejected with `ERR_DRIVE_WINDOW_OVERLAP`, though
        back-to-back adjacency — one drive's `ends_at` equal to another's
        `starts_at` — is allowed."
        PRD §3.7: "The window is half-open: it includes its start instant and
        excludes its end."

        Design: Difficulty/resource_temporal_overlap/drive_window_half_open_overlap_rules
        """
        pin_clock()
        steward, school = _steward_and_school(("Omar Farouk", "Sunnyside High"))
        propose_drive(school["id"], steward["id"], goal_books=50,
                      starts_at="2026-09-01T00:00:00Z",
                      ends_at="2026-10-01T00:00:00Z")

        # Zero-gap adjacency: [09-01, 10-01) and [10-01, 11-01) share no instant.
        adjacent = validate_success(
            api.create_drive(
                {
                    "school_id": school["id"],
                    "goal_books": 30,
                    "starts_at": "2026-10-01T00:00:00Z",
                    "ends_at": "2026-11-01T00:00:00Z",
                },
                make_steward_headers(steward["id"]),
            ),
            201,
        )
        assert adjacent["status"] == "PROPOSED"

    def test_drive_window_overlap_rejected(self, api):
        """PRD §3.7: "One school cannot run overlapping drives: a new window
        that intersects any non-terminal drive of the same school under
        half-open semantics is rejected with `ERR_DRIVE_WINDOW_OVERLAP`, though
        back-to-back adjacency — one drive's `ends_at` equal to another's
        `starts_at` — is allowed."

        Design: Difficulty/resource_temporal_overlap/drive_window_half_open_overlap_rules
        """
        pin_clock()
        steward, school = _steward_and_school(("Omar Farouk", "Sunnyside High"))
        propose_drive(school["id"], steward["id"], goal_books=50,
                      starts_at="2026-09-01T00:00:00Z",
                      ends_at="2026-10-01T00:00:00Z")
        propose_drive(school["id"], steward["id"], goal_books=30,
                      starts_at="2026-10-01T00:00:00Z",
                      ends_at="2026-11-01T00:00:00Z")

        res = api.create_drive(
            {
                "school_id": school["id"],
                "goal_books": 20,
                "starts_at": "2026-09-15T00:00:00Z",
                "ends_at": "2026-10-15T00:00:00Z",
            },
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DRIVE_WINDOW_OVERLAP.value,
                       expected_status=422)

        _data, meta = validate_paginated(
            api.list_drives(ADMIN, params={"school_id": school["id"]})
        )
        assert meta["total_count"] == 2

    def test_drive_window_invalid_rejected(self, api):
        """PRD §3.7: "The window is half-open: it includes its start instant
        and excludes its end, and an end that does not fall strictly after the
        start is `ERR_DRIVE_WINDOW_INVALID`."

        Design: Corner/validations/drive_window_invalid_rejected
        """
        pin_clock()
        steward, school = _steward_and_school(("Window Invalid", "WI School"))
        res = api.create_drive(
            {
                "school_id": school["id"],
                "goal_books": 5,
                "starts_at": "2026-09-01T00:00:00Z",
                "ends_at": "2026-09-01T00:00:00Z",
            },
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DRIVE_WINDOW_INVALID.value,
                       expected_status=422)


class TestDriveLifecycleGates:
    def test_school_inactive_blocks_drive_creation(self, api):
        """PRD §3.7: "An `ACTIVE` steward proposes a drive for an `ACTIVE`
        school — proposing as a suspended steward fails with
        `ERR_STEWARD_NOT_ACTIVE`, and a school in any other status fails with
        `ERR_SCHOOL_NOT_ACTIVE`."

        Design: Corner/validations/school_inactive_blocks_drive_creation
        """
        pin_clock()
        steward = create_active_steward(full_name="School Gate",
                                        email="sg@example.org")
        school = create_school(name="Dormant School")  # left REGISTERED

        res = api.create_drive(
            {
                "school_id": school["id"],
                "goal_books": 5,
                "starts_at": "2026-09-01T00:00:00Z",
                "ends_at": "2026-10-01T00:00:00Z",
            },
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SCHOOL_NOT_ACTIVE.value,
                       expected_status=422)

    def test_drive_cancel_cascades_to_linked_batch_and_items(self, api):
        """PRD §3.7: "The coordinator or an administrator may cancel from
        `PROPOSED`, `APPROVED`, or `OPEN`; anything later is past the point of
        cancellation. Cancelling a merely `PROPOSED` drive changes nothing
        downstream, but cancelling from `APPROVED` or `OPEN` closes the linked
        batch — its status drops to `CLOSED` — and writes off every
        still-`AVAILABLE` book in it as `RECYCLED`."

        Design: Corner/state_machines/drive_cancel_cascades_to_linked_batch_and_items
        """
        pin_clock()
        steward, school = _steward_and_school(("Cancel Tester", "Cancel School"))
        drive, batch = create_open_drive_with_batch(school, steward,
                                                    goal_books=10)
        intake_items(batch["id"], [
            {"title": "DC1", "category": "FICTION", "condition_grade": "A"},
            {"title": "DC2", "category": "NONFICTION", "condition_grade": "B"},
        ])

        cancelled = validate_success(
            api.transition_drive_status(
                drive["id"], "CANCELLED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"

        batch_after = validate_success(api.get_batch(batch["id"],
                                                     TEST_USERS["hub_headers"]),
                                       200)
        assert batch_after["status"] == "CLOSED"

        for item in list_batch_items(batch["id"]):
            assert item["status"] == "RECYCLED"
            assert item["box_id"] is None


class TestSchoolStatusCycle:
    def test_school_status_cycle_and_invalid_same_state(self, api):
        """PRD §3.7: "A school starts `REGISTERED` and cycles to `ACTIVE` (from
        `REGISTERED` or `INACTIVE`) or back to `INACTIVE` (from `ACTIVE`) under
        administrative control via a status operation taking a `target_status`
        of `ACTIVE` or `INACTIVE`, each change incrementing its `version`."
        PRD §2.8: "State preconditions. The target entity sits in the exact
        from-state the transition requires — failures are `ERR_INVALID_STATE`
        or `ERR_DRIVE_NOT_OPEN` (409)."

        Design: Corner/state_machines/school_status_cycle_and_invalid_same_state
        """
        pin_clock()
        school = create_school(name="Cycle School", region_code="WA")
        assert school["status"] == "REGISTERED"

        active = validate_success(
            api.transition_school_status(school["id"], "ACTIVE", ADMIN), 200
        )
        assert active["status"] == "ACTIVE"
        inactive = validate_success(
            api.transition_school_status(school["id"], "INACTIVE", ADMIN), 200
        )
        assert inactive["status"] == "INACTIVE"
        reactivated = validate_success(
            api.transition_school_status(school["id"], "ACTIVE", ADMIN), 200
        )
        assert reactivated["status"] == "ACTIVE"

        # ACTIVE -> ACTIVE is not a listed transition.
        res = api.transition_school_status(school["id"], "ACTIVE", ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)
