"""Temporal-overlap rules: half-open line intervals and the driver 30-minute
rest buffer (PRD §3.4, §3.6)."""
from test_helpers import (
    TEST_USERS,
    create_batch,
    create_line,
    create_plan,
    create_plant,
    create_product,
    create_route,
    create_driver,
    get_plan,
    lock_plan,
    make_operator_headers,
    release_plan,
    set_clock,
    setup_line_dirty_with_sesame,
    validate_error,
    validate_success,
)


class TestLineHalfOpenIntervalAdjacency:
    def test_adjacent_intervals_accepted(self, api):
        """PRD §3.4: "The occupation window is a half-open interval — it
        occupies the line from `scheduled_start_at` up to but not including
        `scheduled_end_at`."

        Design: Difficulty/resource_temporal_overlap/line_half_open_interval_adjacency
        """
        plant = create_plant(name="Plant Sigma")
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])

        b1 = create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"],
            scheduled_start_at="2026-08-09T07:00:00Z",
            scheduled_end_at="2026-08-09T09:00:00Z",
        )
        assert b1["status"] == "SCHEDULED"

        # Adjacent: [09:00, 11:00) touches [07:00, 09:00) at the boundary.
        plan_now = get_plan(plan["id"])
        b2 = create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=plan_now["version"],
            scheduled_start_at="2026-08-09T09:00:00Z",
            scheduled_end_at="2026-08-09T11:00:00Z",
        )
        assert b2["status"] == "SCHEDULED", (
            "half-open adjacency at 09:00 must be accepted"
        )

    def test_intersecting_interval_rejected(self, api):
        """PRD §3.4: "if the interval collides with another scheduled or
        in-flight batch on the same line, creation is rejected with
        `ERR_LINE_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/line_half_open_interval_adjacency
        """
        plant = create_plant(name="Plant Sigma 2")
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])

        create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"],
            scheduled_start_at="2026-08-09T07:00:00Z",
            scheduled_end_at="2026-08-09T09:00:00Z",
        )
        plan_now = get_plan(plan["id"])
        create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=plan_now["version"],
            scheduled_start_at="2026-08-09T09:00:00Z",
            scheduled_end_at="2026-08-09T11:00:00Z",
        )
        plan_now2 = get_plan(plan["id"])
        # [08:30, 10:00) intersects both prior batches.
        resp = api.create_batch(
            {
                "production_plan_id": plan["id"],
                "line_id": line["id"],
                "product_id": product_a["id"],
                "qty_units": 50,
                "scheduled_start_at": "2026-08-09T08:30:00Z",
                "scheduled_end_at": "2026-08-09T10:00:00Z",
                "expected_production_plan_version": plan_now2["version"],
            },
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_LINE_SCHEDULE_OVERLAP", expected_status=409)


class TestDriverWindowRestBuffer:
    def test_window_within_30_minutes_rejected(self, api):
        """PRD §3.6: "A driver may not be double-booked against the rest
        buffer: if the same driver already has a route whose window falls
        within 30 minutes of the requested window, creation is rejected with
        `ERR_DRIVER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/driver_window_rest_buffer
        """
        plant = create_plant(name="Plant Tau")
        driver = create_driver(plant["id"])
        create_route(
            plant["id"], driver["id"],
            window_start_at="2026-08-10T08:00:00Z",
            window_end_at="2026-08-10T10:00:00Z",
        )
        # 20-minute gap after the first window ends — inside the 30-minute buffer.
        resp = api.create_route(
            {
                "plant_id": plant["id"],
                "driver_id": driver["id"],
                "route_date": "2026-08-10",
                "window_start_at": "2026-08-10T10:20:00Z",
                "window_end_at": "2026-08-10T12:00:00Z",
                "truck_capacity_units": 500,
            },
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_DRIVER_WINDOW_OVERLAP", expected_status=409)

    def test_window_at_exactly_30_minutes_accepted(self, api):
        """PRD §3.6: "if the same driver already has a route whose window
        falls within 30 minutes of the requested window, creation is rejected
        with `ERR_DRIVER_WINDOW_OVERLAP`." A 30-minute gap is not "within 30
        minutes," so the second route is accepted.

        Design: Difficulty/resource_temporal_overlap/driver_window_rest_buffer
        """
        plant = create_plant(name="Plant Tau 2")
        driver = create_driver(plant["id"])
        create_route(
            plant["id"], driver["id"],
            window_start_at="2026-08-10T08:00:00Z",
            window_end_at="2026-08-10T10:00:00Z",
        )
        # Exactly 30 minutes after the first window ends.
        r3 = validate_success(
            api.create_route(
                {
                    "plant_id": plant["id"],
                    "driver_id": driver["id"],
                    "route_date": "2026-08-10",
                    "window_start_at": "2026-08-10T10:30:00Z",
                    "window_end_at": "2026-08-10T12:00:00Z",
                    "truck_capacity_units": 500,
                },
                TEST_USERS["planner_headers"],
            ),
            expected_status=201,
        )
        assert r3["status"] == "PLANNED"


class TestAllergenViolationBeatsScheduleOverlap:
    def test_allergen_violation_wins_when_both_apply(self, api):
        """PRD §2.9 step 7 (Safety and duty checks) is evaluated before step 8
        (Temporal windows): "Safety and duty checks — allergen segregation,
        pending sanitation, and segregation of duties; failure yields
        `ERR_ALLERGEN_SEGREGATION_VIOLATION`, `ERR_SANITATION_REQUIRED` (both
        HTTP 409), or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." Step 8 covers
        "Temporal windows — order cutoff, proof window, freshness window,
        the 72-hour return window, line schedule overlap, the driver rest
        buffer, and sanitation dwell time."

        Design: Difficulty/priority_pair_validation_conflict/allergen_violation_beats_schedule_overlap
        """
        # Line is DIRTY with SESAME residue (setup completes a SESAME batch at
        # 08:10). Plan has batch A (NONE) already SCHEDULED at 07:00-09:00 and
        # the completed SESAME batch at 09:00-10:00 is in the past.
        plant = create_plant(name="Plant Mu")
        product_a = create_product(plant["id"], sku="SKU-A", allergen_class="NONE")
        product_b = create_product(
            plant["id"], sku="SKU-B", name="Sesame 300", allergen_class="SESAME",
            unit_weight_g=300, base_price_cents=299, batch_capacity_units=400,
        )
        line = create_line(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"],
            scheduled_start_at="2026-08-09T07:00:00Z",
            scheduled_end_at="2026-08-09T09:00:00Z",
        )
        plan_now = get_plan(plan["id"])
        batch_b = create_batch(
            plan["id"], line["id"], product_b["id"],
            plan_version=plan_now["version"],
            qty_units=100,
            scheduled_start_at="2026-08-09T09:00:00Z",
            scheduled_end_at="2026-08-09T10:00:00Z",
        )
        release_plan(plan["id"])

        # Run batch B (SESAME) to COOLING so the line is DIRTY/SESAME.
        op = make_operator_headers("op-1")
        set_clock("2026-08-09T09:00:00Z")
        validate_success(api.start_mix(batch_b["id"], op))
        validate_success(api.start_proof(batch_b["id"], op))
        set_clock("2026-08-09T10:10:00Z")
        validate_success(api.start_bake(batch_b["id"], op))
        validate_success(api.complete_bake(batch_b["id"], op))

        plan_now2 = get_plan(plan["id"])
        # NONE batch on a SESAME-DIRTY line in a window (08:30-09:30) that also
        # overlaps the existing SCHEDULED batch at 07:00-09:00.
        resp = api.create_batch(
            {
                "production_plan_id": plan["id"],
                "line_id": line["id"],
                "product_id": product_a["id"],
                "qty_units": 50,
                "scheduled_start_at": "2026-08-09T08:30:00Z",
                "scheduled_end_at": "2026-08-09T09:30:00Z",
                "expected_production_plan_version": plan_now2["version"],
            },
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_ALLERGEN_SEGREGATION_VIOLATION", expected_status=409)

    def test_overlap_alone_yields_overlap_error(self, api):
        """PRD §3.4: "if the interval collides with another scheduled or
        in-flight batch on the same line, creation is rejected with
        `ERR_LINE_SCHEDULE_OVERLAP`." (A clean line with a same-allergen
        product removes the safety violation, so the temporal check fires.)

        Design: Difficulty/priority_pair_validation_conflict/allergen_violation_beats_schedule_overlap
        """
        plant = create_plant(name="Plant Mu 2")
        product_a = create_product(plant["id"], sku="SKU-A", allergen_class="NONE")
        line = create_line(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"],
            scheduled_start_at="2026-08-09T07:00:00Z",
            scheduled_end_at="2026-08-09T09:00:00Z",
        )
        plan_now = get_plan(plan["id"])
        # No allergen mismatch (line is CLEAN/NONE, product NONE); pure overlap.
        resp = api.create_batch(
            {
                "production_plan_id": plan["id"],
                "line_id": line["id"],
                "product_id": product_a["id"],
                "qty_units": 50,
                "scheduled_start_at": "2026-08-09T08:30:00Z",
                "scheduled_end_at": "2026-08-09T09:30:00Z",
                "expected_production_plan_version": plan_now["version"],
            },
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_LINE_SCHEDULE_OVERLAP", expected_status=409)
