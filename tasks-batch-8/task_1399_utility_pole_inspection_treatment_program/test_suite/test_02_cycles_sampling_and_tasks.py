"""Cycle opening, population sampling, and manual task-creation guards (PRD §3.2, §3.4)."""
from test_helpers import (
    CLOCK_DEFAULT_ISO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equals,
    assert_inspection_cycle,
    assert_inspection_task,
    create_cycle,
    create_inspection_task_payload,
    create_manual_task,
    create_open_cycle,
    create_pole,
    get_cycle,
    get_pole,
    open_cycle,
    set_clock,
    submit_and_accept_task,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEmptyPoolOpen:
    def test_empty_pool_open_succeeds_with_zero_tasks(self, api, program_manager_headers):
        """PRD §3.2: "Opening with an empty eligible pool succeeds cleanly: zero tasks
        are created and `sample_pool_size` is zero."

        Design: Difficulty/boundary_precision_check/empty_sample_pool_opens_clean
        """
        cycle = create_cycle(year=2026, cycle_length_years=10, sample_pct=100,
                             strength_variant_policy="CONSERVATIVE")
        resp = api.open_inspection_cycle(cycle["id"], program_manager_headers)
        opened = validate_success(resp, expected_status=200)
        assert_inspection_cycle(opened)
        assert opened["status"] == "OPEN"
        assert opened["sample_pool_size"] == 0
        assert opened["tasks_total"] == 0

    def test_empty_pool_open_stamps_opened_at(self, api, program_manager_headers):
        """PRD §3.2: "The open stamps `opened_at` from the logical clock and immediately
        runs population sampling across the entire pole register."
        PRD §2.5: "At server startup the logical clock is set to exactly
        `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time."

        Design: Difficulty/boundary_precision_check/empty_sample_pool_opens_clean
        """
        cycle = create_cycle(year=2026, cycle_length_years=10, sample_pct=100,
                             strength_variant_policy="CONSERVATIVE")
        opened = open_cycle(cycle["id"])
        assert_instant_equals(opened["opened_at"], CLOCK_DEFAULT_ISO, "opened_at")
        reread = get_cycle(cycle["id"])
        assert_instant_equals(reread["opened_at"], CLOCK_DEFAULT_ISO, "opened_at")
        assert reread["reconciled_at"] is None


class TestSamplingRanking:
    def test_sampling_ranks_never_inspected_first(self, api, program_manager_headers):
        """PRD §3.2: "The pool is ranked with never-inspected poles first, then by
        `last_inspection_date` ascending (oldest inspection first), with ties broken by
        the pole's `created_at` ascending. The sample size is the pool size multiplied
        by `sample_pct` and divided by 100, rounded down to a whole number, but never
        less than one when the pool is non-empty and `sample_pct` is above zero".
        PRD §3.2: "The top-ranked poles up to the sample size each receive one `OPEN`
        `InspectionTask` whose inclusive due window runs from `opened_at` through the
        instant 120 days later — a full field season."

        Design: Corner/calculations/sampling_ranks_never_inspected_first
        """
        # Historical inspection at 2010-01-01 so one pole carries a last_inspection_date.
        set_clock("2010-01-01T00:00:00Z")
        p_old = create_pole(pole_number="P-OLD", species="LARCH", original_class="2",
                            install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                            gis_tag="RURAL", height_ft=35)
        p_new = create_pole(pole_number="P-NEW", species="LARCH", original_class="2",
                            install_date="2001-05-01", gis_lat=46.1, gis_lon=-121.1,
                            gis_tag="RURAL", height_ft=35)
        cycle_a = create_open_cycle(year=2010, cycle_length_years=10, sample_pct=0)
        t_old = create_manual_task(cycle_a["id"], p_old["id"],
                                   due_window_start="2010-01-10T00:00:00Z",
                                   due_window_end="2010-01-20T00:00:00Z")
        submit_and_accept_task(
            t_old["id"],
            shell_thickness_in=2.25, sound_wood_pct=100, decay_pocket_depth_in=0.0,
            moisture_pct=20,
        )

        set_clock(CLOCK_DEFAULT_ISO)
        cycle_b = create_cycle(year=2026, cycle_length_years=10, sample_pct=50,
                               strength_variant_policy="CONSERVATIVE")
        opened = open_cycle(cycle_b["id"])
        assert opened["sample_pool_size"] == 2, (
            f"both poles eligible (P-OLD 16y overdue, P-NEW never inspected); "
            f"got pool {opened['sample_pool_size']}"
        )
        assert opened["tasks_total"] == 1, "floor(2 * 50 / 100) == 1"

        data, meta = validate_paginated(
            api.list_inspection_tasks(program_manager_headers,
                                      params={"cycle_id": cycle_b["id"]})
        )
        assert len(data) == 1
        task = data[0]
        assert task["pole_id"] == p_new["id"], (
            "never-inspected pole (NULL last_inspection_date) outranks the dated pole"
        )
        assert task["status"] == "OPEN"
        assert_instant_equals(task["due_window_start"], CLOCK_DEFAULT_ISO,
                              "due_window_start")
        assert_instant_equals(task["due_window_end"], "2026-11-29T00:00:00Z",
                              "due_window_end (opened_at + 120 days)")


class TestTaskListPagination:
    def test_task_list_pagination_envelope(self, api, program_manager_headers):
        """PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return."

        Design: Corner/endpoints/task_list_pagination_envelope
        """
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        p1 = create_pole(pole_number="P-PG1", species="LARCH", original_class="2",
                         install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                         gis_tag="RURAL", height_ft=35)
        p2 = create_pole(pole_number="P-PG2", species="LARCH", original_class="2",
                         install_date="2001-05-01", gis_lat=46.1, gis_lon=-121.1,
                         gis_tag="RURAL", height_ft=35)
        create_manual_task(cycle["id"], p1["id"])
        create_manual_task(cycle["id"], p2["id"])

        page1, meta1 = validate_paginated(
            api.list_inspection_tasks(
                program_manager_headers,
                params={"cycle_id": cycle["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_inspection_tasks(
                program_manager_headers,
                params={"cycle_id": cycle["id"], "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1
        assert page1[0]["id"] != page2[0]["id"], "pages must contain distinct tasks"


class TestManualTaskCreationGuards:
    def test_task_create_bogus_pole_returns_not_found(self, api, program_manager_headers):
        """PRD §2.9: "Only after path identifiers resolve does the system resolve
        foreign-key identifiers carried in the request body — `pole_id`, `cycle_id`,
        `crew_id`, `budget_id`, and `treatment_order_id`."
        PRD §2.9: "Each unresolved identifier maps to its resource-specific error:
        `ERR_POLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`,
        `ERR_TREATMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND`."

        Design: Corner/entities/task_create_bogus_pole_returns_not_found
        """
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        resp = api.create_inspection_task(
            create_inspection_task_payload(cycle["id"], NON_EXISTENT_UUID),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_POLE_NOT_FOUND)

    def test_task_create_into_draft_cycle_rejected(self, api, program_manager_headers):
        """PRD §3.2: "the target cycle must be `OPEN` (creating into a `DRAFT` or
        `RECONCILED` cycle is rejected with `ERR_CYCLE_NOT_OPEN`)".

        Design: Corner/endpoints/task_create_into_draft_cycle_rejected
        """
        cycle = create_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        pole = create_pole(pole_number="P-DC", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        resp = api.create_inspection_task(
            create_inspection_task_payload(cycle["id"], pole["id"]),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    def test_duplicate_inspection_same_cycle_rejected(self, api, program_manager_headers):
        """PRD §3.2: "no other non-terminal task may already exist for the same pole
        within the same cycle (`ERR_DUPLICATE_INSPECTION`)".

        Design: Corner/validations/duplicate_inspection_same_cycle_rejected
        """
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        pole = create_pole(pole_number="P-DI", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        create_manual_task(cycle["id"], pole["id"],
                           due_window_start="2026-08-10T00:00:00Z",
                           due_window_end="2026-08-20T00:00:00Z")
        # Disjoint window: isolates the duplicate rule from the window-overlap rule.
        resp = api.create_inspection_task(
            create_inspection_task_payload(
                cycle["id"], pole["id"],
                due_window_start="2026-08-21T00:00:00Z",
                due_window_end="2026-08-30T00:00:00Z",
            ),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INSPECTION)

    def test_inverted_window_rejected(self, api, program_manager_headers):
        """PRD §3.2: "the task's due window is a closed interval, so `due_window_end`
        before `due_window_start` is rejected with `ERR_INVALID_WINDOW`".

        Design: Corner/validations/inverted_window_rejected
        """
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        pole = create_pole(pole_number="P-IW", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        resp = api.create_inspection_task(
            create_inspection_task_payload(
                cycle["id"], pole["id"],
                due_window_start="2026-08-20T00:00:00Z",
                due_window_end="2026-08-10T00:00:00Z",
            ),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestPoleClosedWindowOverlap:
    def test_task_window_touching_single_day_conflicts(self, api, program_manager_headers):
        """PRD §3.2: "the window must not touch any other non-terminal task's window
        for the same pole — because both intervals are closed, even touching at a
        single shared day is a conflict, rejected with `ERR_TASK_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pole_closed_window_touch_conflicts
        """
        pole = create_pole(pole_number="P-CW")
        cycle1 = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        cycle2 = create_open_cycle(year=2027, cycle_length_years=10, sample_pct=0)
        create_manual_task(cycle1["id"], pole["id"],
                           due_window_start="2026-08-10T00:00:00Z",
                           due_window_end="2026-08-20T00:00:00Z")
        resp = api.create_inspection_task(
            create_inspection_task_payload(
                cycle2["id"], pole["id"],
                due_window_start="2026-08-20T00:00:00Z",
                due_window_end="2026-08-30T00:00:00Z",
            ),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TASK_WINDOW_OVERLAP)

    def test_task_window_disjoint_succeeds(self, api, program_manager_headers):
        """PRD §3.2: "the window must not touch any other non-terminal task's window
        for the same pole — because both intervals are closed, even touching at a
        single shared day is a conflict, rejected with `ERR_TASK_WINDOW_OVERLAP`."
        A window starting the day after the existing window's end touches nothing, so
        creation succeeds.

        Design: Difficulty/resource_temporal_overlap/pole_closed_window_touch_conflicts
        """
        pole = create_pole(pole_number="P-CW")
        cycle1 = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        cycle2 = create_open_cycle(year=2027, cycle_length_years=10, sample_pct=0)
        create_manual_task(cycle1["id"], pole["id"],
                           due_window_start="2026-08-10T00:00:00Z",
                           due_window_end="2026-08-20T00:00:00Z")
        resp = api.create_inspection_task(
            create_inspection_task_payload(
                cycle2["id"], pole["id"],
                due_window_start="2026-08-21T00:00:00Z",
                due_window_end="2026-08-30T00:00:00Z",
            ),
            program_manager_headers,
        )
        task = validate_success(resp, expected_status=201)
        assert_inspection_task(task)
        assert task["status"] == "OPEN"
        assert task["cycle_id"] == cycle2["id"]


class TestWaiveRestoresEligibility:
    def _setup_sampled_pole(self, api, program_manager_headers):
        pole = create_pole(pole_number="P-SW")
        cycle_a = create_cycle(year=2026, cycle_length_years=10, sample_pct=100,
                               strength_variant_policy="CONSERVATIVE")
        opened = api.open_inspection_cycle(cycle_a["id"], program_manager_headers)
        opened = validate_success(opened, expected_status=200)
        assert opened["sample_pool_size"] == 1
        assert opened["tasks_total"] == 1
        data, _ = validate_paginated(
            api.list_inspection_tasks(program_manager_headers,
                                      params={"cycle_id": cycle_a["id"]})
        )
        assert len(data) == 1 and data[0]["pole_id"] == pole["id"]
        return pole, cycle_a, data[0]

    def test_waive_leaves_last_inspection_date_untouched(self, api, program_manager_headers):
        """PRD §3.4: "Waiver is a compensating action: because it does not touch the
        pole's `last_inspection_date`, the pole naturally re-enters the next cycle's
        eligible pool rather than silently dropping out of the inspection population."

        Design: Difficulty/compensating_invariant/sample_waive_restores_eligibility_pool
        """
        pole, _, task = self._setup_sampled_pole(api, program_manager_headers)
        resp = api.waive_inspection_task(task["id"], {"reason": "NO_ACCESS"},
                                         program_manager_headers)
        waived = validate_success(resp, expected_status=200)
        assert waived["status"] == "WAIVED"
        after = get_pole(pole["id"])
        assert after["last_inspection_date"] is None, (
            "waiving must not mark the pole inspected"
        )

    def test_waived_pole_resampled_next_cycle(self, api, program_manager_headers):
        """PRD §2.10: "Waiving an inspection task leaves the pole's
        `last_inspection_date` untouched, which deliberately returns the pole to the
        eligible sampling pool of a future cycle rather than marking it inspected."

        Design: Difficulty/compensating_invariant/sample_waive_restores_eligibility_pool
        """
        pole, _, task = self._setup_sampled_pole(api, program_manager_headers)
        validate_success(
            api.waive_inspection_task(task["id"], {"reason": "NO_ACCESS"},
                                      program_manager_headers),
            expected_status=200,
        )
        cycle_b = create_cycle(year=2027, cycle_length_years=10, sample_pct=100,
                               strength_variant_policy="CONSERVATIVE")
        opened_b = open_cycle(cycle_b["id"])
        assert opened_b["sample_pool_size"] == 1, (
            "waived pole must re-enter the eligible pool of the next cycle"
        )
        assert opened_b["tasks_total"] == 1
        data, _ = validate_paginated(
            api.list_inspection_tasks(program_manager_headers,
                                      params={"cycle_id": cycle_b["id"]})
        )
        assert len(data) == 1
        assert data[0]["pole_id"] == pole["id"], (
            "the same pole is sampled again after its earlier task was waived"
        )
        assert data[0]["status"] == "OPEN"
