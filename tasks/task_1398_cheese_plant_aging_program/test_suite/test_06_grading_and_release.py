"""Grading ladder rungs, age/wheel placement gates, grader segregation of
duties, the re-grade supersession chain, and release eligibility."""
import pytest

from test_helpers import (
    ApiErrorId,
    QA_CAROL,
    QA_DAVE,
    create_aging_room,
    create_grading_event_payload,
    get_cheese_batch,
    grade_batch,
    make_completed_batch,
    make_graded_batch,
    make_qa_grader_headers,
    make_released_batch,
    place_wheels,
    release_batch,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

QA = TEST_USERS["qa_grader_headers"]


class TestGradeLadder:
    def test_grade_assignment_multi_branch_ladder(self, api):
        """PRD §3.7: "Otherwise, a batch whose `body_score` is at least eight,
        whose `flavor_score` is at least eight, and whose `moisture_pct` is at
        or below the variety's grade-A moisture ceiling — 37.0 for `CHEDDAR`,
        38.0 for `COLBY`, 42.0 for `BRICK`, 44.0 for `MUENSTER` — earns
        `GRADE_A`. Everything else is `GRADE_B`."

        Design: Difficulty/combinatorial_formula/grade_assignment_multi_branch_ladder
        """
        ctx = make_graded_batch(
            variety="CHEDDAR", wheels_produced=10, green_weight_kg=1000.0,
            volume_liters=10000.0, liters_committed=10000.0,
            age_to="2026-10-01T00:00:00Z",
            grade_readings={
                "moisture_pct": 38.0, "fat_dry_basis_pct": 52.0,
                "body_score": 9, "flavor_score": 9,
            },
        )
        assert ctx["grading_event"]["assigned_grade"] == "GRADE_B", (
            "A-level scores with moisture 38.0 above the 37.0 CHEDDAR grade-A "
            "ceiling (but within the 39.0 legal ceiling) must land GRADE_B"
        )
        assert ctx["batch"]["current_grade"] == "GRADE_B"
        assert ctx["batch"]["moisture_pct"] == pytest.approx(38.0)

    def test_grade_a_at_exact_grade_a_moisture_ceiling(self, api):
        """PRD §3.7: "Otherwise, a `moisture_pct` strictly above the variety's
        ceiling — 39.0 for `CHEDDAR`, 40.0 for `COLBY`, 44.0 for `BRICK`, 46.0
        for `MUENSTER` — yields `DOWNGRADE`; moisture exactly at the ceiling
        passes the check."
        PRD §3.7: "Otherwise, a batch whose `body_score` is at least eight,
        whose `flavor_score` is at least eight, and whose `moisture_pct` is at
        or below the variety's grade-A moisture ceiling — 37.0 for `CHEDDAR`,
        38.0 for `COLBY`, 42.0 for `BRICK`, 44.0 for `MUENSTER` — earns
        `GRADE_A`."

        Design: Difficulty/combinatorial_formula/grade_assignment_multi_branch_ladder
        """
        ctx = make_graded_batch(
            variety="CHEDDAR", wheels_produced=10, green_weight_kg=1000.0,
            volume_liters=10000.0, liters_committed=10000.0,
            age_to="2026-10-01T00:00:00Z",
            grade_readings={
                "moisture_pct": 37.0, "fat_dry_basis_pct": 52.0,
                "body_score": 8, "flavor_score": 8,
            },
        )
        assert ctx["grading_event"]["assigned_grade"] == "GRADE_A", (
            "moisture exactly at the 37.0 grade-A ceiling with scores exactly 8 "
            "must earn GRADE_A"
        )
        assert ctx["batch"]["current_grade"] == "GRADE_A"

    def test_grade_assignment_condemned_rung_on_low_score(self, api):
        """PRD §3.7: "The grade ladder is evaluated top-down, and the first
        matching rung wins. A `body_score` of two or less, or a `flavor_score`
        of two or less, condemns the batch outright: `CONDEMNED`."
        PRD §3.7: "Condemnation cascades. Whenever a grading assigns
        `CONDEMNED` — a first grading or a re-grade — the batch moves to
        terminal `CONDEMNED`, its `release_decision` is set to `REJECTED`, and
        every `OPEN` or `PARTIALLY_FILLED` allocation order against the batch
        is cancelled; `FILLED` orders are retained for traceability."

        Design: Corner/calculations/grade_assignment_condemned_rung_on_low_score
        """
        ctx = make_graded_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
            grade_readings={
                "moisture_pct": 40.0, "fat_dry_basis_pct": 55.0,
                "body_score": 2, "flavor_score": 10,
            },
        )
        assert ctx["grading_event"]["assigned_grade"] == "CONDEMNED", (
            "body_score 2 is at the inclusive <=2 condemnation boundary"
        )
        assert ctx["batch"]["status"] == "CONDEMNED"
        assert ctx["batch"]["release_decision"] == "REJECTED"

    def test_grade_assignment_downgrade_rung_on_fat_below_minimum(self, api):
        """PRD §3.7: "Otherwise, a `fat_dry_basis_pct` strictly below the
        variety's floor — 50.0 for `CHEDDAR`, `COLBY`, and `BRICK`, 48.0 for
        `MUENSTER` — also yields `DOWNGRADE`; fat exactly at the floor passes."

        Design: Corner/calculations/grade_assignment_downgrade_rung_on_fat_below_minimum
        """
        ctx = make_graded_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
            grade_readings={
                "moisture_pct": 40.0, "fat_dry_basis_pct": 47.9,
                "body_score": 9, "flavor_score": 9,
            },
        )
        assert ctx["grading_event"]["assigned_grade"] == "DOWNGRADE", (
            "fat-in-dry-matter 47.9 is strictly below the 48.0 MUENSTER floor"
        )


class TestGradingGates:
    def test_grader_who_signed_make_step_rejected_on_grading(self, api):
        """PRD §3.7: "And the grader must be independent of the make: a
        `grader_user_id` appearing anywhere in the originating make sheet's
        `step_signer_ids` fails with `ERR_SOLE_OPERATOR`."

        Design: Corner/state_machines/grader_who_signed_make_step_rejected_on_grading
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        place_wheels(ctx["batch_id"], room, 4)
        set_clock("2026-08-25T00:00:00Z")
        # cm_alice signed make steps; presenting the same id as the grader
        # violates the independence rule even under the QAGrader role.
        resp = api.create_grading_event(
            create_grading_event_payload(cheese_batch_id=ctx["batch_id"]),
            make_qa_grader_headers("cm_alice"),
        )
        validate_error(resp, ApiErrorId.ERR_SOLE_OPERATOR, 422)
        batch = get_cheese_batch(ctx["batch_id"])
        assert batch["status"] == "AGING", "a rejected grading leaves the batch AGING"

    def test_wheels_unplaced_and_age_unmet_reports_wheels_unplaced(self, api):
        """PRD §2.9: "Eighth, cross-entity state gates: `ERR_MILK_NOT_ACCEPTED`,
        `ERR_WHEELS_UNPLACED`, `ERR_BATCH_NOT_RELEASED`, and
        `ERR_PLANT_NOT_EXPORT_LISTED`. Ninth, booking, quantity, and sequencing
        constraints: ... Tenth, temporal rules: `ERR_AGE_MINIMUM_NOT_MET`, and
        lot expiry against the logical clock, which surfaces as
        `ERR_ADDITIVE_LOT_UNUSABLE`."
        PRD §3.7: "Every produced wheel must rest in the cellar —
        `wheels_placed` must exactly equal `wheels_produced`, failing
        `ERR_WHEELS_UNPLACED` otherwise (a `GREEN` batch, having placed
        nothing, always fails here)."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_fiscal_on_cutwrap_reconcile
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=5000.0, liters_committed=5000.0,
            green_weight_kg=500.0, wheels_produced=4,
        )
        # No placement, no clock advance: wheels_placed 0 < wheels_produced 4
        # and age 0 < 60 both hold.
        resp = api.create_grading_event(
            create_grading_event_payload(
                cheese_batch_id=ctx["batch_id"], moisture_pct=36.0,
                fat_dry_basis_pct=52.0,
            ),
            make_qa_grader_headers(QA_CAROL),
        )
        validate_error(resp, ApiErrorId.ERR_WHEELS_UNPLACED, 409)
        batch = get_cheese_batch(ctx["batch_id"])
        assert batch["status"] == "GREEN", "no transition may occur"

    def test_wheels_unplaced_fires_before_age_check(self, api):
        """PRD §3.7: "Before a batch's first grading, three gates apply. Every
        produced wheel must rest in the cellar — `wheels_placed` must exactly
        equal `wheels_produced`, failing `ERR_WHEELS_UNPLACED` otherwise (a
        `GREEN` batch, having placed nothing, always fails here). The youngest
        of the batch's `IN_ROOM` aging units — the minimum of their `age_days`
        — must be at least the batch's `min_age_days`, failing
        `ERR_AGE_MINIMUM_NOT_MET`; a youngest unit whose age exactly equals the
        minimum passes."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_fiscal_on_cutwrap_reconcile
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        place_wheels(ctx["batch_id"], room, 2)  # only 2 of 4 wheels placed
        set_clock("2026-08-25T00:00:00Z")  # 24 days: past the 21-day minimum
        resp = api.create_grading_event(
            create_grading_event_payload(cheese_batch_id=ctx["batch_id"]),
            make_qa_grader_headers(QA_CAROL),
        )
        validate_error(resp, ApiErrorId.ERR_WHEELS_UNPLACED, 409)
        batch = get_cheese_batch(ctx["batch_id"])
        assert batch["status"] == "AGING"

    def test_age_minimum_boundary_muenster_21_days(self, api):
        """PRD §3.7: "The youngest of the batch's `IN_ROOM` aging units — the
        minimum of their `age_days` — must be at least the batch's
        `min_age_days`, failing `ERR_AGE_MINIMUM_NOT_MET`; a youngest unit
        whose age exactly equals the minimum passes."

        Design: Corner/validations/age_minimum_boundary_muenster_21_days
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        place_wheels(ctx["batch_id"], room, 4)
        set_clock("2026-08-21T00:00:00Z")  # 20 days < 21-day MUENSTER minimum
        resp = api.create_grading_event(
            create_grading_event_payload(cheese_batch_id=ctx["batch_id"]),
            make_qa_grader_headers(QA_CAROL),
        )
        validate_error(resp, ApiErrorId.ERR_AGE_MINIMUM_NOT_MET, 422)
        set_clock("2026-08-22T00:00:00Z")  # exactly 21 days passes
        event = grade_batch(ctx["batch_id"], grader_id=QA_CAROL)
        assert event["assigned_grade"] == "GRADE_A"


class TestRegradeChain:
    def test_cheese_batch_regrade_cycle_graded_to_graded(self, api):
        """PRD §3.7: "A batch already `GRADED` may be re-graded while its
        `release_decision` is still `PENDING` — a released batch may not be
        re-graded, failing `ERR_INVALID_STATE` — and the independence check
        against `step_signer_ids` applies again. Each re-grade chains to its
        predecessor: the new event's `supersedes_grading_event_id` references
        the previously latest grading event on that batch, forming a
        self-referential audit chain."

        Design: Difficulty/non_linear_state_machine/cheese_batch_regrade_cycle_graded_to_graded
        """
        ctx = make_graded_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
            grade_readings={
                "moisture_pct": 40.0, "fat_dry_basis_pct": 50.0,
                "body_score": 9, "flavor_score": 9,
            },
            grader_id=QA_CAROL,
        )
        ge1 = ctx["grading_event"]
        assert ge1["assigned_grade"] == "GRADE_A", (
            "moisture 40.0 is at or below the 44.0 MUENSTER grade-A ceiling"
        )
        ge2 = validate_success(
            api.create_grading_event(
                create_grading_event_payload(
                    cheese_batch_id=ctx["batch_id"], moisture_pct=45.0,
                    fat_dry_basis_pct=50.0,
                ),
                make_qa_grader_headers(QA_DAVE),
            ),
            201,
        )
        assert ge2["assigned_grade"] == "GRADE_B", (
            "moisture 45.0 is above the 44.0 grade-A ceiling but within the "
            "46.0 legal ceiling, landing exactly one rung down at GRADE_B"
        )
        assert ge2["supersedes_grading_event_id"] == ge1["id"], (
            "the re-grade must chain to the previously latest grading event"
        )
        batch = get_cheese_batch(ctx["batch_id"])
        assert batch["status"] == "GRADED" and batch["current_grade"] == "GRADE_B"

    def test_regrade_updates_batch_to_latest_readings(self, api):
        """PRD §3.7: "Whatever the outcome, the batch's `moisture_pct`,
        `fat_dry_basis_pct`, and `current_grade` are updated to the latest
        event's readings and assigned grade."

        Design: Difficulty/non_linear_state_machine/cheese_batch_regrade_cycle_graded_to_graded
        """
        ctx = make_graded_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
            grade_readings={
                "moisture_pct": 40.0, "fat_dry_basis_pct": 50.0,
                "body_score": 9, "flavor_score": 9,
            },
            grader_id=QA_CAROL,
        )
        ge2 = validate_success(
            api.create_grading_event(
                create_grading_event_payload(
                    cheese_batch_id=ctx["batch_id"], moisture_pct=44.5,
                    fat_dry_basis_pct=52.0,
                ),
                make_qa_grader_headers(QA_DAVE),
            ),
            201,
        )
        batch = get_cheese_batch(ctx["batch_id"])
        assert batch["moisture_pct"] == pytest.approx(44.5)
        assert batch["fat_dry_basis_pct"] == pytest.approx(52.0)
        assert batch["current_grade"] == ge2["assigned_grade"] == "GRADE_B"

    def test_grading_event_self_referential_chain_links_prior_event(self, api):
        """PRD §3.7: "Each re-grade chains to its predecessor: the new event's
        `supersedes_grading_event_id` references the previously latest grading
        event on that batch, forming a self-referential audit chain."
        PRD §2.3: "grading events by `plant_id`, `cheese_batch_id`, and
        `supersedes_grading_event_id`;"

        Design: Corner/entities/grading_event_self_referential_chain_links_prior_event
        """
        ctx = make_graded_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
            grade_readings={
                "moisture_pct": 40.0, "fat_dry_basis_pct": 50.0,
                "body_score": 9, "flavor_score": 9,
            },
            grader_id=QA_CAROL,
        )
        ge1_id = ctx["grading_event"]["id"]
        _, meta_before = validate_paginated(
            api.list_grading_events(
                QA,
                params={
                    "cheese_batch_id": ctx["batch_id"],
                    "supersedes_grading_event_id": ge1_id,
                },
            )
        )
        assert meta_before["total_count"] == 0, (
            "no superseding event exists before the re-grade"
        )
        ge2 = validate_success(
            api.create_grading_event(
                create_grading_event_payload(
                    cheese_batch_id=ctx["batch_id"], moisture_pct=41.0,
                    fat_dry_basis_pct=50.0,
                ),
                make_qa_grader_headers(QA_DAVE),
            ),
            201,
        )
        assert ge2["supersedes_grading_event_id"] == ge1_id
        _, meta_after = validate_paginated(
            api.list_grading_events(
                QA,
                params={
                    "cheese_batch_id": ctx["batch_id"],
                    "supersedes_grading_event_id": ge1_id,
                },
            )
        )
        assert meta_after["total_count"] == 1, (
            "the supersedes filter must find exactly the re-grade"
        )

    def test_regrade_of_released_batch_blocked(self, api):
        """PRD §3.7: "A batch already `GRADED` may be re-graded while its
        `release_decision` is still `PENDING` — a released batch may not be
        re-graded, failing `ERR_INVALID_STATE` — and the independence check
        against `step_signer_ids` applies again."

        Design: Corner/cross_cutting_layers/regrade_of_released_batch_blocked
        """
        ctx = make_graded_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
            grade_readings={
                "moisture_pct": 40.0, "fat_dry_basis_pct": 50.0,
                "body_score": 9, "flavor_score": 9,
            },
            grader_id=QA_CAROL,
        )
        release_batch(ctx["batch_id"])
        resp = api.create_grading_event(
            create_grading_event_payload(
                cheese_batch_id=ctx["batch_id"], body_score=1, flavor_score=1,
            ),
            make_qa_grader_headers(QA_DAVE),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        batch = get_cheese_batch(ctx["batch_id"])
        assert batch["current_grade"] == "GRADE_A", (
            "a blocked re-grade leaves the released grade unchanged"
        )
