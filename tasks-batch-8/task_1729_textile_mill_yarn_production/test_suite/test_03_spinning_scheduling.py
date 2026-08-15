"""Spinning: machines, yarn lots, scheduling discipline, spin-time costing."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_component,
    approve_recipe,
    create_draft_recipe,
    create_fiber_lot,
    create_machine_assignment_payload,
    create_spinning_machine,
    create_spinning_machine_payload,
    create_yarn_lot,
    get_success_data,
    schedule_assignment,
    setup_approved_recipe,
    setup_machine_with_yarn_lots,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]
SUPERVISOR = TEST_USERS["spinning_supervisor_headers"]
ADMIN = TEST_USERS["mill_admin_headers"]


class TestYarnLotCreation:
    def test_yarn_lot_initial_state_greige(self, api):
        """PRD §3.2: "A yarn lot starts in `GREIGE`."

        Design: Corner/state_machines/yarn_lot_initial_state_greige
        """
        base = setup_approved_recipe(component_weight_lbs=100.0)
        yarn_lot = create_yarn_lot(
            base["recipe"]["id"], spun_weight_lbs=100.0, actual_yarn_count_ne=20.0
        )
        assert yarn_lot["status"] == "GREIGE", "A yarn lot starts in GREIGE"

    def test_greige_yards_initialized_from_weight_and_count(self, api):
        """PRD §3.2: "Its `greige_yards_available` is initialized from the spun weight using the standard yards-per-pound figure for the count band the lot's actual count falls into: 8,400 yards per pound at Ne 10, 16,800 yards per pound at Ne 20, and 25,200 yards per pound at Ne 30."

        Design: Corner/calculations/greige_yards_initialized_from_weight_and_count
        """
        base = setup_approved_recipe(component_weight_lbs=200.0)
        yarn_lot = create_yarn_lot(
            base["recipe"]["id"], spun_weight_lbs=100.0, actual_yarn_count_ne=20.0
        )
        assert yarn_lot["greige_yards_available"] == pytest.approx(1680000.0), (
            "100 lbs at the Ne 20 band initialize to 100 * 16,800 yards"
        )


class TestMachineRegistration:
    def test_duplicate_machine_code_rejected(self, api):
        """PRD §3.2: "A `MillAdmin` registers each spinning machine with its floor `machine_code` (unique — duplicates are rejected with `ERR_DUPLICATE_KEY`) and its supported count band, `supported_count_min_ne` and `supported_count_max_ne`, both strictly greater than zero with the maximum strictly above the minimum."

        Design: Corner/validations/duplicate_machine_code_rejected
        """
        create_spinning_machine(machine_code="SPIN-DUP", min_ne=10.0, max_ne=30.0)
        resp = api.create_spinning_machine(
            create_spinning_machine_payload(
                machine_code="SPIN-DUP",
                supported_count_min_ne=15.0,
                supported_count_max_ne=25.0,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


class TestAssignmentGuards:
    def test_machine_assignment_bogus_machine_fk(self, api):
        """PRD §2.10: "Reference existence — every foreign-key field in the request body, such as `fiber_lot_id`, `recipe_id`, `machine_id`, `yarn_lot_id`, `shade_band_id`, `dye_lot_id`, or `roll_id`, resolves to an existing entity (`ERR_REFERENCE_NOT_FOUND`)."

        Design: Corner/validations/fk_reference_not_found
        """
        base = setup_approved_recipe(component_weight_lbs=100.0)
        yarn_lot = create_yarn_lot(
            base["recipe"]["id"], spun_weight_lbs=100.0, actual_yarn_count_ne=20.0
        )
        resp = api.create_machine_assignment(
            create_machine_assignment_payload(
                NON_EXISTENT_UUID,
                yarn_lot["id"],
                window_start="2026-08-14T08:00:00Z",
                window_end="2026-08-14T12:00:00Z",
            ),
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_count_out_of_range_rejected(self, api):
        """PRD §3.2: "Selector eligibility is enforced at scheduling time: the recipe's `target_yarn_count_ne` must lie within the machine's supported band from `supported_count_min_ne` to `supported_count_max_ne`, and a recipe whose target falls outside is rejected with `ERR_COUNT_OUT_OF_RANGE`."

        Design: Corner/validations/count_out_of_range_for_machine
        """
        ctx = setup_machine_with_yarn_lots(
            num_lots=1,
            target_yarn_count_ne=50.0,
            machine_min_ne=10.0,
            machine_max_ne=30.0,
            spun_weights=[100.0],
        )
        resp = api.create_machine_assignment(
            create_machine_assignment_payload(
                ctx["machine"]["id"],
                ctx["yarn_lots"][0]["id"],
                window_start="2026-08-14T08:00:00Z",
                window_end="2026-08-14T12:00:00Z",
            ),
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_COUNT_OUT_OF_RANGE)

    def test_cancel_completed_assignment_rejected(self, api):
        """PRD §3.2: "A `SCHEDULED` assignment may instead be cancelled, moving it to `CANCELLED`; assignments in `COMPLETED` and `CANCELLED` are terminal."

        Design: Corner/state_machines/machine_assignment_cancel_from_completed_rejected
        """
        ctx = setup_machine_with_yarn_lots(num_lots=1, spun_weights=[100.0])
        assignment = schedule_assignment(
            ctx["machine"]["id"], ctx["yarn_lots"][0]["id"]
        )
        get_success_data(api.start_machine_assignment(assignment["id"], SUPERVISOR))
        completed = get_success_data(
            api.complete_machine_assignment(assignment["id"], SUPERVISOR)
        )
        assert completed["status"] == "COMPLETED"

        resp = api.cancel_machine_assignment(assignment["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSpinCosting:
    def _setup_two_lot_blend(self, api):
        """Lot A 200 lbs @1.50 + lot B 200 lbs @2.00, 100 lbs each into the recipe."""
        lot_a = create_fiber_lot(received_weight_lbs=200.0, unit_cost_per_lb=1.5)
        lot_b = create_fiber_lot(received_weight_lbs=200.0, unit_cost_per_lb=2.0,
                                 fiber_type="POLYESTER")
        recipe = create_draft_recipe(recipe_code="CTN-POLY-50-50",
                                     target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot_a["id"], 100.0)
        add_component(recipe["id"], lot_b["id"], 100.0)
        approve_recipe(recipe["id"])
        return recipe

    def test_projected_cost_forward_looking(self, api):
        """PRD §3.1: "On approval the recipe's `approved_at` is stamped (it is null until then), its `version` increments, and its `projected_cost_per_lb` is computed with the forward-looking blend cost estimate: the sum, over all components, of each component's weight multiplied by its fiber lot's current `unit_cost_per_lb` at approval time, divided by the recipe's `total_component_weight_lbs`, rounded to 4 decimal places round half up."

        Design: Difficulty/dual_variant_calc/blend_cost_forward_looking_vs_chronological
        """
        recipe = self._setup_two_lot_blend(api)
        fetched = validate_success(api.get_blend_recipe(recipe["id"], PLANNER))
        assert fetched["projected_cost_per_lb"] == pytest.approx(1.75, abs=1e-4), (
            "forward-looking variant: (100*1.50 + 100*2.00) / 200 = 1.7500"
        )

    def test_actual_cost_chronological_differs(self, api):
        """PRD §3.2: "When an `IN_PROGRESS` assignment is completed, two things happen. First, the yarn lot's `actual_cost_per_lb` is computed with the chronological blend cost variant: the sum, over the recipe's components, of each component's weight multiplied by the `unit_cost_per_lb` recorded on its fiber lot at the moment the assignment completes, divided by the lot's `spun_weight_lbs`, rounded to 4 decimal places round half up. Because the denominator is the actual spun weight rather than the planned component sum — waste and count change pull the two apart — this chronological figure legitimately differs from the recipe's `projected_cost_per_lb` for identical inputs."

        Design: Difficulty/dual_variant_calc/blend_cost_forward_looking_vs_chronological
        """
        recipe = self._setup_two_lot_blend(api)
        yarn_lot = create_yarn_lot(
            recipe["id"], spun_weight_lbs=180.0, actual_yarn_count_ne=20.0
        )
        machine = create_spinning_machine(min_ne=10.0, max_ne=30.0)
        assignment = schedule_assignment(machine["id"], yarn_lot["id"])
        get_success_data(api.start_machine_assignment(assignment["id"], SUPERVISOR))
        get_success_data(api.complete_machine_assignment(assignment["id"], SUPERVISOR))

        spun = validate_success(api.get_yarn_lot(yarn_lot["id"], SUPERVISOR))
        assert spun["actual_cost_per_lb"] == pytest.approx(1.9444, abs=1e-4), (
            "chronological variant: (100*1.50 + 100*2.00) / 180 = 1.9444"
        )
        fetched_recipe = validate_success(
            api.get_blend_recipe(recipe["id"], PLANNER)
        )
        assert fetched_recipe["projected_cost_per_lb"] == pytest.approx(1.75, abs=1e-4)
        assert spun["actual_cost_per_lb"] != pytest.approx(
            fetched_recipe["projected_cost_per_lb"], abs=1e-9
        ), "The two variants legitimately differ for identical component inputs"


class TestWindowOverlap:
    def test_overlapping_window_rejected(self, api):
        """PRD §2.9: "A spinning machine can hold only one live assignment at a time: a new assignment's window — treated as half-open, covering its `window_start` inclusively and its `window_end` exclusively — must not overlap any other assignment on the same machine that is `SCHEDULED` or `IN_PROGRESS`, and `window_end` must fall strictly after `window_start`."
        PRD §2.9: "Either violation is rejected with `ERR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/machine_assignment_half_open_overlap
        """
        ctx = setup_machine_with_yarn_lots(num_lots=2,
                                           spun_weights=[100.0, 80.0])
        schedule_assignment(
            ctx["machine"]["id"], ctx["yarn_lots"][0]["id"],
            window_start="2026-08-14T08:00:00Z", window_end="2026-08-14T12:00:00Z",
        )
        resp = api.create_machine_assignment(
            create_machine_assignment_payload(
                ctx["machine"]["id"], ctx["yarn_lots"][1]["id"],
                window_start="2026-08-14T10:00:00Z",
                window_end="2026-08-14T14:00:00Z",
            ),
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)

    def test_touching_windows_allowed(self, api):
        """PRD §2.9: "A spinning machine can hold only one live assignment at a time: a new assignment's window — treated as half-open, covering its `window_start` inclusively and its `window_end` exclusively — must not overlap any other assignment on the same machine that is `SCHEDULED` or `IN_PROGRESS`, and `window_end` must fall strictly after `window_start`."

        Design: Difficulty/resource_temporal_overlap/machine_assignment_half_open_overlap
        """
        ctx = setup_machine_with_yarn_lots(num_lots=2,
                                           spun_weights=[100.0, 80.0])
        schedule_assignment(
            ctx["machine"]["id"], ctx["yarn_lots"][0]["id"],
            window_start="2026-08-14T08:00:00Z", window_end="2026-08-14T12:00:00Z",
        )
        # Back-to-back: [12:00, 16:00) touches but does not overlap [08:00, 12:00).
        resp = api.create_machine_assignment(
            create_machine_assignment_payload(
                ctx["machine"]["id"], ctx["yarn_lots"][1]["id"],
                window_start="2026-08-14T12:00:00Z",
                window_end="2026-08-14T16:00:00Z",
            ),
            SUPERVISOR,
        )
        second = validate_success(resp, 201)
        assert second["status"] == "SCHEDULED"
