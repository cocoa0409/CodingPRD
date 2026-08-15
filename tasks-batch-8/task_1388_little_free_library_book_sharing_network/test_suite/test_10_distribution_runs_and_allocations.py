"""Distribution planning, confirmation, dispatch, receipt, and cascades."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cancel_allocation,
    charter_box,
    create_active_box,
    create_active_steward,
    create_batch,
    create_draft_box,
    create_sorted_batch,
    create_steward_with_active_box,
    create_upheld_complaint,
    inspect_box,
    intake_items,
    list_batch_items,
    list_run_allocations,
    make_steward_headers,
    pin_clock,
    receive_allocation,
    run_sweep,
    setup_confirmed_run,
    setup_dispatched_run,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HUB = TEST_USERS["hub_headers"]


def _three_box_scenario(api):
    """Three ACTIVE LISTED boxes: A cap10 OR, B cap6 OR, C cap20 CA; one
    SORTED PUBLIC_DROP batch in OR with 12 graded FICTION items."""
    steward_a = create_active_steward(full_name="Steward A",
                                      email="sa@example.org", region_code="OR")
    steward_b = create_active_steward(full_name="Steward B",
                                      email="sb@example.org", region_code="OR")
    steward_c = create_active_steward(full_name="Steward C",
                                      email="sc@example.org", region_code="CA")
    box_a = create_active_box(steward_a, name="Box A", capacity_books=10,
                              region_code="OR")
    box_b = create_active_box(steward_b, name="Box B", capacity_books=6,
                              region_code="OR", latitude=45.53,
                              longitude=-122.69)
    box_c = create_active_box(steward_c, name="Box C", capacity_books=20,
                              region_code="CA", latitude=34.05,
                              longitude=-118.24)
    batch, _items = create_sorted_batch(item_count=12, region_code="OR")
    return box_a, box_b, box_c, batch


class TestNeedScoreSelector:
    def test_need_score_ranking_quantity_and_region_bonus(self, api):
        """PRD §3.8: "Each eligible box earns a `need_score`: take its
        remaining capacity capped at ten books and double it, add its
        `days_since_activity` capped at sixty days, and add a twenty-point
        bonus when the box's `region_code` matches the batch's `region_code`.
        Boxes rank by score from highest to lowest, ties broken in favor of the
        box created earliest; box ids never participate in ranking."
        PRD §3.8: "The surviving plan is frozen into the run's `plan_snapshot`,
        an ordered array of entries each naming a `box_id`, a `quantity`, and
        the box's `need_score`, ordered exactly as ranked."

        Design: Difficulty/combinatorial_formula/need_score_ranking_quantity_and_region_bonus
        """
        pin_clock()
        box_a, box_b, _box_c, batch = _three_box_scenario(api)
        run = validate_success(
            api.create_distribution_run(batch["id"], batch["version"], HUB),
            201,
        )
        # A = min(10,10)*2 + 0 + 20 = 40; B = min(6,10)*2 + 0 + 20 = 32;
        # 12 items: A gets 10, B gets min(6,10,2) = 2.
        assert run["plan_snapshot"] == [
            {"box_id": box_a["id"], "quantity": 10, "need_score": 40},
            {"box_id": box_b["id"], "quantity": 2, "need_score": 32},
        ]

    def test_need_score_drops_zero_quantity_box_and_sums_plan(self, api):
        """PRD §3.8: "Walking the ranking, each box is planned a quantity equal
        to the smallest of three figures — its remaining capacity, ten books,
        and the count of still-unassigned available graded items — and a box
        whose quantity works out to zero drops out of the plan."
        PRD §3.8: "`planned_item_count` is the sum of those quantities."

        Design: Difficulty/combinatorial_formula/need_score_ranking_quantity_and_region_bonus
        """
        pin_clock()
        _box_a, _box_b, box_c, batch = _three_box_scenario(api)
        run = validate_success(
            api.create_distribution_run(batch["id"], batch["version"], HUB),
            201,
        )
        # Box C (score 20) ranks last and remaining_items reaches 0 after B.
        assert all(entry["box_id"] != box_c["id"]
                   for entry in run["plan_snapshot"])
        assert run["planned_item_count"] == 12

    def test_selector_tie_break_by_created_at(self, api):
        """PRD §3.8: "Boxes rank by score from highest to lowest, ties broken
        in favor of the box created earliest; box ids never participate in
        ranking."

        Design: Corner/calculations/selector_tie_break_by_created_at
        """
        pin_clock()
        steward1 = create_active_steward(full_name="First Steward",
                                         email="first@example.org")
        steward2 = create_active_steward(full_name="Second Steward",
                                         email="second@example.org")
        box_first = create_draft_box(steward1, name="First Box",
                                     capacity_books=5)
        # One logical second later the second box is created.
        pin_clock("2026-08-01T00:00:01Z")
        box_second = create_draft_box(steward2, name="Second Box",
                                      capacity_books=5, latitude=45.53,
                                      longitude=-122.69)
        for box in (box_first, box_second):
            charter_box(box["id"])
            inspect_box(box["id"], "CONFIRMED")
            validate_success(
                api.transition_box_status(box["id"], "ACTIVE", ADMIN), 200
            )

        batch, _items = create_sorted_batch(item_count=8, region_code="OR")
        run = validate_success(
            api.create_distribution_run(batch["id"], batch["version"], HUB),
            201,
        )
        # Identical scores: min(5,10)*2 + 0 + 20 = 30. Tie broken by the
        # earlier created_at first: first takes 5, second takes 3 of 8.
        assert run["plan_snapshot"] == [
            {"box_id": box_first["id"], "quantity": 5, "need_score": 30},
            {"box_id": box_second["id"], "quantity": 3, "need_score": 30},
        ]
        assert run["planned_item_count"] == 8

    def test_selector_empty_pool_returns_no_eligible_boxes(self, api):
        """PRD §3.8: "When no eligible box exists or the batch holds no
        available graded items, the empty plan is rejected with
        `ERR_NO_ELIGIBLE_BOXES`."

        Design: Corner/calculations/selector_empty_pool_returns_no_eligible_boxes
        """
        pin_clock()
        batch, _items = create_sorted_batch(item_count=2, region_code="OR")

        res = api.create_distribution_run(batch["id"], batch["version"], HUB)
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_BOXES.value,
                       expected_status=422)

        _data, meta = validate_paginated(
            api.list_distribution_runs(HUB, params={"batch_id": batch["id"]})
        )
        assert meta["total_count"] == 0


class TestRunCreationGates:
    def test_run_create_rejected_state_priority_over_constraint(self, api):
        """PRD §3.8: "Creating a distribution run for a `SORTED` batch requires
        the `expected_batch_version` of §2.7."
        PRD §2.8: "State preconditions. The target entity sits in the exact
        from-state the transition requires — failures are `ERR_INVALID_STATE`
        or `ERR_DRIVE_NOT_OPEN` (409)."
        PRD §2.8: "A request that fails several rules at once must fail
        predictably, so validation runs as an ordered pipeline and the first
        failing stage wins."

        Design: Difficulty/priority_pair_validation_conflict/run_create_rejected_state_priority_over_constraint
        """
        pin_clock()
        # Batch still RECEIVED (state failure) AND zero boxes exist (the
        # selector constraint would also fail); the state error wins.
        batch = create_batch()
        intake_items(batch["id"], [
            {"title": "Solo", "category": "FICTION", "condition_grade": "A"},
        ])

        res = api.create_distribution_run(batch["id"], batch["version"], HUB)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)

    def test_run_create_rejected_leaves_no_run(self, api):
        """PRD §3.8: "When no eligible box exists or the batch holds no
        available graded items, the empty plan is rejected with
        `ERR_NO_ELIGIBLE_BOXES`."
        PRD §2.8: "State preconditions. The target entity sits in the exact
        from-state the transition requires — failures are `ERR_INVALID_STATE`
        or `ERR_DRIVE_NOT_OPEN` (409)."

        Design: Difficulty/priority_pair_validation_conflict/run_create_rejected_state_priority_over_constraint
        """
        pin_clock()
        batch = create_batch()
        intake_items(batch["id"], [
            {"title": "Solo", "category": "FICTION", "condition_grade": "A"},
        ])
        res = api.create_distribution_run(batch["id"], batch["version"], HUB)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)

        _data, meta = validate_paginated(
            api.list_distribution_runs(HUB, params={"batch_id": batch["id"]})
        )
        assert meta["total_count"] == 0

    def test_run_create_supersedes_prior_draft_run(self, api):
        """PRD §3.8: "Creating a newer run for the same batch supersedes any
        run still in `DRAFT` for that batch, moving it to `SUPERSEDED`."
        PRD §3.8: "Creating a distribution run for a `SORTED` batch requires
        the `expected_batch_version` of §2.7, and creating the run itself
        advances the batch's `version`, so a second writer holding a stale
        observation is turned away with `ERR_STALE_VERSION`."

        Design: Corner/state_machines/run_create_supersedes_prior_draft_run
        """
        pin_clock()
        _steward, _box = create_steward_with_active_box(
            steward_name="Supersede Owner", box_name="Supersede Box"
        )
        batch, _items = create_sorted_batch(item_count=2)
        run1 = validate_success(
            api.create_distribution_run(batch["id"], batch["version"], HUB),
            201,
        )
        batch_after = validate_success(api.get_batch(batch["id"], HUB), 200)

        run2 = validate_success(
            api.create_distribution_run(
                batch["id"], batch_after["version"], HUB
            ),
            201,
        )
        assert run2["status"] == "DRAFT"

        superseded = validate_success(
            api.get_distribution_run(run1["id"], HUB), 200
        )
        assert superseded["status"] == "SUPERSEDED"

        res = api.confirm_distribution_run(run1["id"], HUB)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)


class TestPlanRevalidation:
    def test_run_confirm_rejected_when_planned_box_flagged(self, api):
        """PRD §3.8: "Confirming a `DRAFT` run re-validates the frozen snapshot
        against the present: every planned box must still be `ACTIVE`, still
        `LISTED`, and still hold enough free capacity for its planned quantity,
        and the batch must still hold enough available graded items to cover
        `planned_item_count` — any drift fails with `ERR_PLAN_STALE`."
        PRD §3.4: "A delisting does not rewrite any existing draft plan, but it
        poisons one: a distribution run still in `DRAFT` whose snapshot
        contains the delisted box can no longer be confirmed and fails at
        confirm time with `ERR_PLAN_STALE`."

        Design: Difficulty/cross_entity_state_dependency/run_confirm_rejected_when_planned_box_flagged
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Marie Curie", box_name="Fir Box"
        )
        batch, _items = create_sorted_batch(item_count=2)
        run = validate_success(
            api.create_distribution_run(batch["id"], batch["version"], HUB),
            201,
        )
        # One upheld complaint flips the planned box LISTED -> FLAGGED.
        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Promo leaflets")
        box_now = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert box_now["listing_posture"] == "FLAGGED"

        res = api.confirm_distribution_run(run["id"], HUB)
        validate_error(res, ApiErrorId.ERR_PLAN_STALE.value,
                       expected_status=409)

        run_after = validate_success(
            api.get_distribution_run(run["id"], HUB), 200
        )
        assert run_after["status"] == "DRAFT"

    def test_run_confirm_rejection_materializes_nothing(self, api):
        """PRD §3.8: "A clean confirmation creates one allocation per planned
        book in `RESERVED` status, consuming boxes in snapshot order and
        drawing items from the batch's available graded pool oldest-first by
        `created_at`; each drawn book moves to `ALLOCATED` with its `box_id`
        set to the planned box."
        PRD §3.8: "any drift fails with `ERR_PLAN_STALE`."

        Design: Difficulty/cross_entity_state_dependency/run_confirm_rejected_when_planned_box_flagged
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Marie Curie", box_name="Fir Box"
        )
        batch, _items = create_sorted_batch(item_count=2)
        run = validate_success(
            api.create_distribution_run(batch["id"], batch["version"], HUB),
            201,
        )
        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Promo leaflets")

        res = api.confirm_distribution_run(run["id"], HUB)
        validate_error(res, ApiErrorId.ERR_PLAN_STALE.value,
                       expected_status=409)

        _data, meta = validate_paginated(
            api.list_run_allocations(run["id"], HUB)
        )
        assert meta["total_count"] == 0

        for item in list_batch_items(batch["id"]):
            assert item["status"] == "AVAILABLE"
            assert item["box_id"] is None


class TestBookPoolConservation:
    def test_confirm_then_cancel_all_restores_available_pool(self, api):
        """PRD §3.8: "A clean confirmation creates one allocation per planned
        book in `RESERVED` status ... each drawn book moves to `ALLOCATED`
        with its `box_id` set to the planned box."
        PRD §3.8: "Cancellation is the compensating lever, available to a
        `HubCoordinator` or `NetworkAdmin` while an allocation is `RESERVED` or
        `DISPATCHED`: the allocation becomes `CANCELLED`, its book returns to
        `AVAILABLE` with `box_id` cleared to null, and the same bubble-up
        check runs."
        PRD §3.8: "Its `item_count` only ever grows — items are never
        hard-deleted."

        Design: Difficulty/compensating_invariant/book_pool_conserved_under_confirm_then_cancel_all
        """
        pin_clock()
        scenario = setup_confirmed_run(item_count=3, capacity_books=10)
        batch = scenario["batch"]
        allocations = scenario["allocations"]

        # Immediately after confirm: 3 items ALLOCATED, 3 allocations RESERVED.
        for item in list_batch_items(batch["id"]):
            assert item["status"] == "ALLOCATED"
        for allocation in allocations:
            assert allocation["status"] == "RESERVED"
        mid = validate_success(api.get_batch(batch["id"], HUB), 200)
        assert mid["item_count"] == 3

        for allocation in allocations:
            cancel_allocation(allocation["id"])

        for item in list_batch_items(batch["id"]):
            assert item["status"] == "AVAILABLE"
            assert item["box_id"] is None
        for allocation in list_run_allocations(scenario["run"]["id"]):
            assert allocation["status"] == "CANCELLED"
        final = validate_success(api.get_batch(batch["id"], HUB), 200)
        assert final["item_count"] == 3

    def test_run_completes_and_stock_zero_after_cancel_all(self, api):
        """PRD §3.8: "Each placement also runs a bubble-up check: when every
        allocation of a run stands in `PLACED` or `CANCELLED`, the run closes
        itself as `COMPLETED`, whether from `DISPATCHED` or — when everything
        was cancelled before dispatch — directly from `CONFIRMED`."

        Design: Difficulty/compensating_invariant/book_pool_conserved_under_confirm_then_cancel_all
        """
        pin_clock()
        scenario = setup_confirmed_run(item_count=3, capacity_books=10)
        for allocation in scenario["allocations"]:
            cancel_allocation(allocation["id"])

        run_after = validate_success(
            api.get_distribution_run(scenario["run"]["id"], HUB), 200
        )
        assert run_after["status"] == "COMPLETED"

        box_after = validate_success(
            api.get_box(scenario["box"]["id"], ADMIN), 200
        )
        assert box_after["current_stock"] == 0


class TestBoxStockConservation:
    def test_stock_equals_placed_allocations_after_receives(self, api):
        """PRD §3.3: "The `current_stock` counts the box's allocations
        currently in `PLACED` status and is maintained invariantly as
        placements and removals happen."
        PRD §3.8: "the allocation becomes `PLACED` with `placed_at` stamped,
        the book becomes `PLACED`, the box's `current_stock` rises by one and
        its `last_activity_at` refreshes."

        Design: Difficulty/compensating_invariant/box_stock_conserved_under_receive_then_decommission
        """
        pin_clock()
        scenario = setup_dispatched_run(item_count=2, capacity_books=10)
        steward = scenario["steward"]
        box = scenario["box"]
        for allocation in scenario["allocations"]:
            receive_allocation(allocation["id"], steward["id"])

        box_after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert box_after["current_stock"] == 2
        placed = [
            a for a in list_run_allocations(scenario["run"]["id"])
            if a["status"] == "PLACED"
        ]
        assert len(placed) == 2
        assert box_after["current_stock"] == len(placed)

    def test_decommission_releases_stock_and_recycles_items(self, api):
        """PRD §3.3: "From `ACTIVE` or `SUSPENDED` it additionally unwinds the
        box's book load: allocations in `RESERVED` or `DISPATCHED` become
        `CANCELLED` and their books return to `AVAILABLE` with `box_id` cleared
        to null, while allocations already `PLACED` become `REMOVED` and their
        books are written off as `RECYCLED`; the box's `current_stock` is
        forced to 0 and its posture to `DELISTED`."
        PRD §3.8: "Allocations leave the active flow in one more way — a
        `PLACED` allocation becomes `REMOVED` when its box is decommissioned or
        when its book, sitting `QUARANTINED`, is recycled by a sweep — and
        removal writes the book off as `RECYCLED` and decrements the box's
        `current_stock` by one."

        Design: Difficulty/compensating_invariant/box_stock_conserved_under_receive_then_decommission
        """
        pin_clock()
        scenario = setup_dispatched_run(item_count=2, capacity_books=10)
        steward = scenario["steward"]
        box = scenario["box"]
        batch = scenario["batch"]
        for allocation in scenario["allocations"]:
            receive_allocation(allocation["id"], steward["id"])

        decommissioned = validate_success(
            api.transition_box_status(box["id"], "DECOMMISSIONED", ADMIN), 200
        )
        assert decommissioned["charter_status"] == "DECOMMISSIONED"
        assert decommissioned["listing_posture"] == "DELISTED"
        assert decommissioned["current_stock"] == 0

        data, meta = validate_paginated(
            api.list_allocations(ADMIN, params={"box_id": box["id"]})
        )
        assert meta["total_count"] == 2
        for allocation in data:
            assert allocation["status"] == "REMOVED"

        for item in list_batch_items(batch["id"]):
            assert item["status"] == "RECYCLED"
            assert item["box_id"] is None

        run_after = validate_success(
            api.get_distribution_run(scenario["run"]["id"], HUB), 200
        )
        assert run_after["status"] == "COMPLETED"


class TestRecallCascade:
    def _setup_delist_cascade(self, api):
        """Box with 4 DISPATCHED allocations and two upheld complaints
        (posture FLAGGED, upheld_complaints_90d == 2)."""
        pin_clock()
        scenario = setup_dispatched_run(item_count=4, capacity_books=10)
        steward = scenario["steward"]
        box = scenario["box"]
        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Ad flyers #1")
        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Ad flyers #2")
        box_now = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert box_now["listing_posture"] == "FLAGGED"
        assert box_now["upheld_complaints_90d"] == 2
        return scenario

    def test_complaint_upheld_delist_recall_chain(self, api):
        """PRD §3.4: "Third, an `ACTIVE` box is `DELISTED` when any delisting
        condition holds: at least one open critical maintenance request, at
        least three upheld complaints in the 90-day window, or staleness of at
        least 180 days."
        PRD §3.4: "Falling into `DELISTED` from `LISTED` or `FLAGGED` fires the
        same recall cascade as a suspension: in-flight allocations (`RESERVED`
        or `DISPATCHED`) for the box become `CANCELLED`, their books return to
        `AVAILABLE` with `box_id` cleared to null, and run-completion bubble-up
        checks fire for the runs those allocations belonged to."

        Design: Difficulty/transitive_cascade/complaint_upheld_delist_recall_chain
        """
        scenario = self._setup_delist_cascade(api)
        steward = scenario["steward"]
        box = scenario["box"]
        batch = scenario["batch"]

        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Ad flyers #3")

        box_after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert box_after["listing_posture"] == "DELISTED"
        assert box_after["upheld_complaints_90d"] == 3
        assert box_after["charter_status"] == "ACTIVE"

        for allocation in list_run_allocations(scenario["run"]["id"]):
            assert allocation["status"] == "CANCELLED"
        for item in list_batch_items(batch["id"]):
            assert item["status"] == "AVAILABLE"
            assert item["box_id"] is None

    def test_recall_cascade_bubbles_run_to_completed_and_counts_strikes(
        self, api
    ):
        """PRD §3.8: "when every allocation of a run stands in `PLACED` or
        `CANCELLED`, the run closes itself as `COMPLETED`."
        PRD §3.2: "A steward's `strike_count` is the number of complaints
        currently standing in an upheld terminal status — `RESOLVED_UPHELD` or
        `ADJUDICATED_UPHELD` — against boxes owned by that steward."

        Design: Difficulty/transitive_cascade/complaint_upheld_delist_recall_chain
        """
        scenario = self._setup_delist_cascade(api)
        steward = scenario["steward"]
        box = scenario["box"]

        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Ad flyers #3")

        run_after = validate_success(
            api.get_distribution_run(scenario["run"]["id"], HUB), 200
        )
        assert run_after["status"] == "COMPLETED"

        steward_after = validate_success(
            api.get_steward(steward["id"], ADMIN), 200
        )
        assert steward_after["strike_count"] == 3


class TestAllocationOwnership:
    def test_allocation_receive_rejected_for_non_owner_steward(self, api):
        """PRD §3.8: "Receipt is the steward's handshake. The owner steward of
        the destination box — or a `NetworkAdmin` acting on their behalf —
        confirms a `DISPATCHED` allocation as received; a steward acting on
        someone else's box is rejected with `ERR_FORBIDDEN_OWNERSHIP`, and a
        non-`ACTIVE` steward with `ERR_STEWARD_NOT_ACTIVE`."

        Design: Corner/state_machines/allocation_receive_rejected_for_non_owner_steward
        """
        pin_clock()
        scenario = setup_dispatched_run(item_count=1, capacity_books=10)
        other = create_active_steward(full_name="Owner B",
                                      email="ownerb@example.org")
        allocation = scenario["allocations"][0]

        res = api.receive_allocation(
            allocation["id"], make_steward_headers(other["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value,
                       expected_status=403)

        after = validate_success(api.get_allocation(allocation["id"], ADMIN),
                                 200)
        assert after["status"] == "DISPATCHED"


class TestQuarantineRecycleSweep:
    def test_quarantined_item_recycled_by_sweep_after_30_days(self, api):
        """PRD §3.9: "books still `QUARANTINED` thirty days after the
        `upheld_at` of the decision that quarantined them are recycled,
        clearing their `box_id`, turning the still-`PLACED` allocation
        `REMOVED`, and decrementing the box's `current_stock` by one."
        PRD §3.6: "every book physically placed in that box in the named
        category is quarantined, its status moving from `PLACED` to
        `QUARANTINED` while `box_id` stays set and the underlying allocation
        remains `PLACED`, so `current_stock` does not move."

        Design: Corner/state_machines/quarantined_item_recycled_by_sweep_after_30_days
        """
        pin_clock()
        scenario = setup_dispatched_run(item_count=1, capacity_books=10)
        steward = scenario["steward"]
        box = scenario["box"]
        allocation = scenario["allocations"][0]
        item_id = allocation["book_item_id"]
        receive_allocation(allocation["id"], steward["id"])

        # The book placed by the scenario is FICTION; quarantine that category.
        pin_clock("2026-08-02T00:00:00Z")
        create_upheld_complaint(box["id"], steward["id"],
                                category="INAPPROPRIATE_CONTENT",
                                description="Unsuitable",
                                target_category="FICTION")
        quarantined = validate_success(api.get_book_item(item_id, ADMIN), 200)
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["box_id"] == box["id"]

        # +29 days (upheld at 2026-08-02T00:00:00Z): not yet recycled.
        pin_clock("2026-08-31T00:00:00Z")
        sweep29 = run_sweep()
        assert sweep29["recycled_item_count"] == 0
        still = validate_success(api.get_book_item(item_id, ADMIN), 200)
        assert still["status"] == "QUARANTINED"

        # Exactly +30 days: the recycle boundary is inclusive.
        pin_clock("2026-09-01T00:00:00Z")
        sweep30 = run_sweep()
        assert sweep30["recycled_item_count"] == 1

        item_after = validate_success(api.get_book_item(item_id, ADMIN), 200)
        assert item_after["status"] == "RECYCLED"
        assert item_after["box_id"] is None

        allocation_after = validate_success(
            api.get_allocation(allocation["id"], ADMIN), 200
        )
        assert allocation_after["status"] == "REMOVED"

        box_after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert box_after["current_stock"] == 0
