"""Recognition ledger: rolling vs lifetime variants, tiers, drive payoff."""
from test_helpers import (
    TEST_USERS,
    create_active_box,
    create_active_school,
    create_active_steward,
    create_open_drive_with_batch,
    create_sorted_batch,
    create_steward_with_active_box,
    create_upheld_complaint,
    dispatch_run,
    confirm_run,
    create_run_for_batch,
    ensure_module,
    events_of_type,
    intake_items,
    list_recognition_events,
    list_run_allocations,
    make_steward_headers,
    pin_clock,
    receive_allocation,
    record_completion,
    register_steward,
    report_maintenance,
    resolve_box_maintenance,
    resolve_maintenance,
    triage_maintenance,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestRollingVsLifetime:
    def _setup_aged_out_steward(self, api):
        """Steward earns +25 (TRAINING_PASSED) at 2025-01-01; one maintenance
        request reported the same day; clock then advanced to 2026-08-01, so
        the +25 event is outside the closed 365-day rolling window."""
        pin_clock("2025-01-01T00:00:00Z")
        orientation = ensure_module("ORIENTATION", "Orientation", 1)
        steward = register_steward(full_name="Ada Lovelace",
                                   email="ada@example.org", region_code="OR")
        record_completion(steward["id"], orientation["id"], score=90)
        validate_success(api.activate_steward(steward["id"], ADMIN), 200)
        box = create_active_box(steward, name="Maple St Box",
                                capacity_books=10, region_code="OR")
        request = report_maintenance(box["id"], category="WEAR",
                                     description="Roof seam splitting")
        pin_clock("2026-08-01T00:00:00Z")
        triage_maintenance(request["id"], severity="LOW",
                           scheduled_date="2026-08-02")
        return steward, request

    def test_rolling_excludes_aged_out_event_while_lifetime_counts_it(self, api):
        """PRD §3.2: "The `lifetime_points` total sums the `points_delta` of
        every RecognitionEvent the steward has ever received. The
        `rolling_points` total sums only those events whose `created_at` falls
        inside the closed window from 365 days before the current logical
        instant up to and including that instant."
        PRD §2.10: "resolving a maintenance request pays +40."

        Design: Difficulty/dual_variant_calc/recognition_rolling_vs_lifetime_window_ageout
        """
        steward, request = self._setup_aged_out_steward(api)

        before = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        # The 2025-01-01 +25 event aged out of [2025-08-01, 2026-08-01].
        assert before["rolling_points"] == 0
        assert before["lifetime_points"] == 25

        resolve_maintenance(request["id"])
        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        assert after["lifetime_points"] == 65
        assert after["rolling_points"] == 40

    def test_tier_keys_off_rolling_not_lifetime(self, api):
        """PRD §3.2: "The `recognition_tier` reads only the rolling figure,
        never the lifetime one. The thresholds are inclusive: at least 1,000
        rolling points earns `PLATINUM`, at least 600 earns `GOLD`, at least
        300 earns `SILVER`, at least 100 earns `BRONZE`, and anything below 100
        is `NONE` — exactly 100 is `BRONZE`, exactly 99 is `NONE`."

        Design: Difficulty/dual_variant_calc/recognition_rolling_vs_lifetime_window_ageout
        """
        steward, request = self._setup_aged_out_steward(api)
        resolve_maintenance(request["id"])
        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        # Lifetime 65 but rolling 40 < 100: tier stays NONE.
        assert after["lifetime_points"] == 65
        assert after["rolling_points"] == 40
        assert after["recognition_tier"] == "NONE"


class TestTierBoundary:
    def _setup_steward_at_90_points(self, api):
        """Steward at rolling_points 90: +25 ORIENTATION, +25 SAFETY, +40
        maintenance resolution; a dispatched run with 2 allocations pending."""
        pin_clock()
        orientation = ensure_module("ORIENTATION", "Orientation", 1)
        safety = ensure_module("SAFETY", "Content Safety", 2)
        steward = register_steward(full_name="Alan Turing",
                                   email="alan@example.org")
        record_completion(steward["id"], orientation["id"], score=90)
        validate_success(api.activate_steward(steward["id"], ADMIN), 200)
        record_completion(steward["id"], safety["id"], score=84)
        box = create_active_box(steward, name="Willow Box", capacity_books=10)
        resolve_box_maintenance(box["id"], category="WEAR",
                                description="Loose knob")

        batch, _items = create_sorted_batch(item_count=2, region_code="OR")
        run = create_run_for_batch(batch["id"])
        confirm_run(run["id"])
        allocations = list_run_allocations(run["id"])
        dispatch_run(run["id"])
        return steward, allocations

    def test_rolling_95_is_not_bronze(self, api):
        """PRD §3.2: "at least 100 earns `BRONZE`, and anything below 100 is
        `NONE` — exactly 100 is `BRONZE`, exactly 99 is `NONE`."
        PRD §2.10: "each placed allocation pays +5."

        Design: Difficulty/boundary_precision_check/tier_boundary_crossing_at_exactly_100_points
        """
        steward, allocations = self._setup_steward_at_90_points(api)
        receive_allocation(allocations[0]["id"], steward["id"])

        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        # 90 + 5 = 95 < 100.
        assert after["rolling_points"] == 95
        assert after["recognition_tier"] == "NONE"

    def test_rolling_exactly_100_is_bronze(self, api):
        """PRD §3.2: "at least 100 earns `BRONZE`, and anything below 100 is
        `NONE` — exactly 100 is `BRONZE`, exactly 99 is `NONE`."
        PRD §2.10: "each placed allocation pays +5."

        Design: Difficulty/boundary_precision_check/tier_boundary_crossing_at_exactly_100_points
        """
        steward, allocations = self._setup_steward_at_90_points(api)
        receive_allocation(allocations[0]["id"], steward["id"])
        receive_allocation(allocations[1]["id"], steward["id"])

        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        # 90 + 5 + 5 = 100: the >= boundary is inclusive.
        assert after["rolling_points"] == 100
        assert after["recognition_tier"] == "BRONZE"


class TestDriveCompletionCascade:
    def _setup_steward_at_215_points_with_open_drive(self, api):
        """Steward at rolling_points 215 (BRONZE): +25 x3 training passes,
        +40 x3 maintenance resolutions, +5 x4 allocation placements; plus an
        OPEN drive (goal 1) whose linked batch holds exactly 1 graded item."""
        pin_clock()
        orientation = ensure_module("ORIENTATION", "Orientation", 1)
        safety = ensure_module("SAFETY", "Content Safety", 2)
        curation = ensure_module("CURATION", "Curation", 2,
                                 prerequisite_module_id=orientation["id"])
        steward = register_steward(full_name="Hypatia Stone",
                                   email="hypatia@example.org")
        record_completion(steward["id"], orientation["id"], score=90)
        validate_success(api.activate_steward(steward["id"], ADMIN), 200)
        record_completion(steward["id"], safety["id"], score=88)
        record_completion(steward["id"], curation["id"], score=92)

        box = create_active_box(steward, name="Birch Box", capacity_books=10)
        resolve_box_maintenance(box["id"], category="WEAR",
                                description="Hinge squeak")
        resolve_box_maintenance(box["id"], category="WEAR",
                                description="Shelf sag")
        resolve_box_maintenance(box["id"], category="WEATHER_DAMAGE",
                                description="Paint peeling")

        batch, _items = create_sorted_batch(item_count=4, region_code="OR")
        run = create_run_for_batch(batch["id"])
        confirm_run(run["id"])
        allocations = list_run_allocations(run["id"])
        dispatch_run(run["id"])
        for allocation in allocations:
            receive_allocation(allocation["id"], steward["id"])

        school = create_active_school(name="Hawthorne Middle")
        drive, drive_batch = create_open_drive_with_batch(
            school, steward, goal_books=1,
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-20T00:00:00Z",
        )
        intake_items(drive_batch["id"], [
            {"title": "D1", "category": "FICTION", "condition_grade": "A"},
        ])
        validate_success(
            api.transition_drive_status(
                drive["id"], "COLLECTION_CLOSED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )
        return steward, school, drive

    def test_drive_completion_recognition_tier_crossing(self, api):
        """PRD §3.7: "Completion pays the coordinator a `DRIVE_COMPLETED` event
        worth +150 points when the drive qualifies and +50 when it does not,
        and increments the school's `drives_completed_count`."
        PRD §3.2: "The thresholds are inclusive: at least 1,000 rolling points
        earns `PLATINUM`, at least 600 earns `GOLD`, at least 300 earns
        `SILVER`, at least 100 earns `BRONZE`, and anything below 100 is
        `NONE`."

        Design: Difficulty/transitive_cascade/drive_completion_recognition_tier_crossing
        """
        steward, school, drive = (
            self._setup_steward_at_215_points_with_open_drive(api)
        )
        before = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        assert before["rolling_points"] == 215
        assert before["recognition_tier"] == "BRONZE"

        completed = validate_success(
            api.transition_drive_status(
                drive["id"], "COMPLETED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"

        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        assert after["rolling_points"] == 365
        # 365 >= 300: the event insert itself crosses BRONZE -> SILVER.
        assert after["recognition_tier"] == "SILVER"

        drive_events = events_of_type(
            list_recognition_events(steward["id"]), "DRIVE_COMPLETED"
        )
        assert len(drive_events) == 1
        assert drive_events[0]["points_delta"] == 150

    def test_drive_completion_increments_school_counter(self, api):
        """PRD §3.7: "Completion pays the coordinator a `DRIVE_COMPLETED` event
        worth +150 points when the drive qualifies and +50 when it does not,
        and increments the school's `drives_completed_count`."
        PRD §3.7: "its `drives_completed_count` tracks how many of its drives
        have reached `COMPLETED`."

        Design: Difficulty/transitive_cascade/drive_completion_recognition_tier_crossing
        """
        steward, school, drive = (
            self._setup_steward_at_215_points_with_open_drive(api)
        )
        validate_success(
            api.transition_drive_status(
                drive["id"], "COMPLETED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )
        school_after = validate_success(api.get_school(school["id"], ADMIN),
                                        200)
        assert school_after["drives_completed_count"] == 1


class TestDriveFulfillmentVariants:
    def _setup_quarantined_drive(self, api):
        """Drive goal 4 with 4 collected items; a distribution placed the 2
        CHILDREN items, and an upheld CHILDREN complaint quarantined them while
        the 2 FICTION items remain DISPATCHED; drive then COLLECTION_CLOSED."""
        pin_clock()
        scenario_steward, box = create_steward_with_active_box(
            steward_name="Grace Hopper", box_name="Oak Ave Box",
            region_code="OR",
        )
        steward = scenario_steward
        school = create_active_school(name="Ridgeview Elementary")
        drive, batch = create_open_drive_with_batch(
            school, steward, goal_books=4,
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-20T00:00:00Z",
        )
        intake_items(batch["id"], [
            {"title": "C1", "category": "CHILDREN", "condition_grade": "A"},
            {"title": "C2", "category": "CHILDREN", "condition_grade": "B"},
            {"title": "F1", "category": "FICTION", "condition_grade": "A"},
            {"title": "F2", "category": "FICTION", "condition_grade": "B"},
        ])
        sorted_batch = validate_success(
            api.sort_complete_batch(batch["id"], TEST_USERS["hub_headers"]),
            200,
        )
        run = validate_success(
            api.create_distribution_run(batch["id"],
                                        sorted_batch["version"],
                                        TEST_USERS["hub_headers"]),
            201,
        )
        confirm_run(run["id"])
        allocations = list_run_allocations(run["id"])
        dispatch_run(run["id"])
        # Items are drawn oldest-first: allocations[0]/[1] are C1/C2.
        receive_allocation(allocations[0]["id"], steward["id"])
        receive_allocation(allocations[1]["id"], steward["id"])

        validate_success(
            api.transition_drive_status(
                drive["id"], "COLLECTION_CLOSED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )

        # Uphold a CHILDREN complaint: the 2 PLACED CHILDREN books quarantine.
        create_upheld_complaint(
            box["id"], steward["id"], category="INAPPROPRIATE_CONTENT",
            description="Age-inappropriate children's books",
            target_category="CHILDREN",
        )
        return steward, drive

    def test_drive_fulfillment_gross_vs_net_quarantine(self, api):
        """PRD §3.7: "The gross lens, `fulfillment_pct_gross`, counts every
        book ever collected into the linked batch regardless of fate:
        `collected_count` is all items in the batch in any status, multiplied
        by 100 and floor-divided by `goal_books`. The net lens,
        `fulfillment_pct_net`, counts only books still in play:
        `accepted_count` covers items in `AVAILABLE`, `ALLOCATED`,
        `DISPATCHED`, or `PLACED`, excluding anything `QUARANTINED` or
        `RECYCLED`, again multiplied by 100 and floor-divided by `goal_books`."
        PRD §3.7: "The bonus line, `qualifies_for_bonus`, holds when the net
        percentage reaches at least 80 — the boundary is inclusive."

        Design: Difficulty/dual_variant_calc/drive_fulfillment_gross_vs_net_quarantine
        """
        steward, drive = self._setup_quarantined_drive(api)
        validate_success(
            api.transition_drive_status(
                drive["id"], "COMPLETED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )

        after = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert after["collected_count"] == 4
        # floor(4*100/4): QUARANTINED items still count toward gross.
        assert after["fulfillment_pct_gross"] == 100
        # floor(2*100/4): the 2 QUARANTINED CHILDREN items are excluded, the
        # 2 DISPATCHED FICTION items still count.
        assert after["fulfillment_pct_net"] == 50
        assert after["qualifies_for_bonus"] is False

    def test_quarantined_drive_completion_pays_base_points(self, api):
        """PRD §3.7: "Completion pays the coordinator a `DRIVE_COMPLETED` event
        worth +150 points when the drive qualifies and +50 when it does not."
        PRD §3.7: "The bonus line, `qualifies_for_bonus`, holds when the net
        percentage reaches at least 80 — the boundary is inclusive."

        Design: Difficulty/dual_variant_calc/drive_fulfillment_gross_vs_net_quarantine
        """
        steward, drive = self._setup_quarantined_drive(api)
        validate_success(
            api.transition_drive_status(
                drive["id"], "COMPLETED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )

        drive_events = events_of_type(
            list_recognition_events(steward["id"]), "DRIVE_COMPLETED"
        )
        assert len(drive_events) == 1
        # Net 50 < 80: the non-qualifying +50 variant.
        assert drive_events[0]["points_delta"] == 50

    def test_drive_fulfillment_floor_division(self, api):
        """PRD §3.7: "`collected_count` is all items in the batch in any
        status, multiplied by 100 and floor-divided by `goal_books`."
        PRD §2.9: "Percentages used by the book-drive metrics are integers
        produced by floor division — the fractional remainder is always
        discarded, never rounded up."
        PRD §3.7: "Completion pays the coordinator a `DRIVE_COMPLETED` event
        worth +150 points when the drive qualifies and +50 when it does not."

        Design: Corner/calculations/drive_fulfillment_floor_division
        """
        pin_clock()
        steward = create_active_steward(full_name="Floor Tester",
                                        email="ft@example.org")
        school = create_active_school(name="Floor School")
        drive, batch = create_open_drive_with_batch(
            school, steward, goal_books=3,
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-20T00:00:00Z",
        )
        intake_items(batch["id"], [
            {"title": "F1", "category": "FICTION", "condition_grade": "A"},
            {"title": "F2", "category": "FICTION", "condition_grade": "B"},
        ])
        validate_success(
            api.transition_drive_status(
                drive["id"], "COLLECTION_CLOSED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )
        validate_success(
            api.transition_drive_status(
                drive["id"], "COMPLETED",
                make_steward_headers(steward["id"]),
            ),
            200,
        )

        after = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        # floor(2*100/3) == 66, not 67.
        assert after["fulfillment_pct_gross"] == 66
        assert after["fulfillment_pct_net"] == 66
        assert after["qualifies_for_bonus"] is False

        drive_events = events_of_type(
            list_recognition_events(steward["id"]), "DRIVE_COMPLETED"
        )
        assert len(drive_events) == 1
        assert drive_events[0]["points_delta"] == 50
