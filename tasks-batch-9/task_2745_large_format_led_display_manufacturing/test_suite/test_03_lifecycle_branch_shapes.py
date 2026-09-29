"""Lifecycles whose shape is not a straight line.

A module loops on itself through rework until the allowance is spent, a project
advances two independent state dimensions side by side, and a warranty claim
forks into two branches that write disjoint field sets.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_ENGINEERING_ALREADY_APPROVED,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_MODULE_STATE,
)
from test_helpers.assertions import (
    assert_cabinet_fields,
    assert_case_fields,
    assert_cents,
    assert_module_fields,
    assert_project_fields,
)
from test_helpers.constants import (
    CABINET_POPULATED,
    CASE_APPROVED,
    CASE_DENIED,
    ENGINEERING_APPROVED,
    ENGINEERING_REJECTED,
    MODULE_REWORK,
    MODULE_SCRAPPED,
    PRODUCTION_IN_ASSEMBLY,
    PRODUCTION_NOT_STARTED,
    REVISION_APPROVED,
    REVISION_REJECTED,
    WARRANTY_CASE_INSTANT,
)
from test_helpers.factories import pixel_test_payload

#: A dead-pixel count of 5 exceeds the FP10-IN allowance of 3, so the test fails
#: however small the cluster is.
FAILING_DEAD_PIXELS = 5

REJECTION_REASON = "Cable tray clashes with the ceiling grid"
DENIAL_REASON = "Physical impact damage is excluded from the brightness warranty"


def _manufactured_module(plant):
    """One freshly registered FP10-IN module, still on zero rework cycles."""
    model = plant.register_model()
    return plant.register_module(model["id"], "M-9")


def _two_responded_degradation_claims(plant):
    """A commissioned GOLD wall with two identical brightness claims answered."""
    scene = plant.commissioned_scene()
    plant.set_clock(WARRANTY_CASE_INSTANT)
    case_a = plant.open_degradation_case(
        scene.contract["id"], scene.cabinet["id"], measured_brightness_nits=4600
    )
    case_b = plant.open_degradation_case(
        scene.contract["id"], scene.cabinet["id"], measured_brightness_nits=4600
    )
    plant.respond(case_a["id"])
    plant.respond(case_b["id"])
    scene.case_a = case_a
    scene.case_b = case_b
    return scene


class TestModuleReworkSelfLoop:
    """Repeated failures hold the module in one state while a counter climbs."""

    def test_the_first_two_failures_loop_the_module_through_rework(self, plant):
        """A failing test from `MANUFACTURED` therefore yields
        `MANUFACTURED → REWORK` on the first two failures and
        `MANUFACTURED → SCRAPPED` on a failure that exhausts the allowance; a
        failing retest yields the `REWORK → REWORK` self-loop while the allowance
        holds and `REWORK → SCRAPPED` once it is spent.

        Design: Difficulty/non_linear_state_machine/module_rework_self_loop_bounded_then_scrapped
        """
        module = _manufactured_module(plant)
        assert_module_fields(module, rework_cycles=0)

        first = plant.pixel_test(module["id"], FAILING_DEAD_PIXELS, 1)
        assert_module_fields(first, module_state=MODULE_REWORK, rework_cycles=1)

        second = plant.pixel_test(module["id"], FAILING_DEAD_PIXELS, 1)
        assert_module_fields(second, module_state=MODULE_REWORK, rework_cycles=2)

    def test_the_third_failure_diverts_to_the_terminal_state(self, plant):
        """The candidate cycle count is the module's current `rework_cycles` plus
        1, that value is **always** written back to `rework_cycles`, and then the
        module lands in `REWORK` if the candidate count is within the plant's
        allowance of **two** rework cycles, or in `SCRAPPED` if the candidate
        count exceeds it.

        Design: Difficulty/non_linear_state_machine/module_rework_self_loop_bounded_then_scrapped
        """
        module = _manufactured_module(plant)
        plant.pixel_test(module["id"], FAILING_DEAD_PIXELS, 1)
        plant.pixel_test(module["id"], FAILING_DEAD_PIXELS, 1)

        third = plant.pixel_test(module["id"], FAILING_DEAD_PIXELS, 1)

        assert_module_fields(third, module_state=MODULE_SCRAPPED, rework_cycles=3)

    def test_a_passing_retest_cannot_revive_a_scrapped_module(self, plant):
        """The operation is available while the module is `MANUFACTURED` or
        `REWORK`; in any other state it is refused with
        `ERR_INVALID_MODULE_STATE`.

        Design: Difficulty/non_linear_state_machine/module_rework_self_loop_bounded_then_scrapped
        """
        module = _manufactured_module(plant)
        for _ in range(3):
            plant.pixel_test(module["id"], FAILING_DEAD_PIXELS, 1)

        response = plant.api.pixel_test_module(
            module["id"], pixel_test_payload(1, 1), plant.operator
        )

        validate_error(response, ERR_INVALID_MODULE_STATE, 409)
        scrapped = plant.module(module["id"])
        assert_module_fields(
            scrapped,
            module_state=MODULE_SCRAPPED,
            rework_cycles=3,
            cabinet_id=None,
            slot_index=None,
        )


class TestProjectStateDimensions:
    """Engineering and production advance without constraining one another."""

    def _rejected_then_approved_wall(self, plant):
        model = plant.register_model()
        project = plant.create_project(model["id"])
        first = plant.submit_revision(project["id"])
        plant.review_revision(first["id"], "REJECT", REJECTION_REASON)
        second = plant.submit_revision(project["id"])
        plant.review_revision(second["id"], "APPROVE")
        return model, project, first, second

    def test_the_engineering_dimension_loops_while_production_waits(self, plant):
        """`engineering_state` tracks the structural drawing package and moves
        through `DRAFT`, `UNDER_REVIEW`, `REJECTED` and `APPROVED`, starting at
        `DRAFT`; `APPROVED` is terminal for that dimension.

        Design: Difficulty/non_linear_state_machine/project_engineering_and_production_dimensions_advance_independently
        """
        _, project, first, second = self._rejected_then_approved_wall(plant)

        first_read = plant.revision(first["id"])
        assert first_read["revision_number"] == 1
        assert first_read["revision_state"] == REVISION_REJECTED
        assert first_read["rejection_reason"] == REJECTION_REASON

        second_read = plant.revision(second["id"])
        assert second_read["revision_number"] == 2
        assert second_read["revision_state"] == REVISION_APPROVED

        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            production_state=PRODUCTION_NOT_STARTED,
            approved_revision_number=2,
        )

    def test_a_rejection_leaves_the_approved_revision_number_unset(self, plant):
        """`REJECT` moves the revision `SUBMITTED → REJECTED`, requires the
        `reason` to be present and between 1 and 240 characters (a missing or
        empty reason is refused with `ERR_VALIDATION_FAILED`), stores it as the
        revision's `rejection_reason`, moves the project's `engineering_state`
        `UNDER_REVIEW → REJECTED`, and leaves `approved_revision_number` unset.

        Design: Difficulty/non_linear_state_machine/project_engineering_and_production_dimensions_advance_independently
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        revision = plant.submit_revision(project["id"])

        plant.review_revision(revision["id"], "REJECT", REJECTION_REASON)

        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_REJECTED,
            production_state=PRODUCTION_NOT_STARTED,
            approved_revision_number=None,
        )

    def test_the_first_install_moves_production_and_leaves_engineering_alone(self, plant):
        """The very first install anywhere on the project also moves the
        project's `production_state` `NOT_STARTED → IN_ASSEMBLY`.

        Design: Difficulty/non_linear_state_machine/project_engineering_and_production_dimensions_advance_independently
        """
        model, project, _, _ = self._rejected_then_approved_wall(plant)
        cabinet = plant.plan_cabinet(project["id"])
        module = plant.calibrated_module(model["id"])

        plant.install(cabinet["id"], module["id"], 1)

        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            production_state=PRODUCTION_IN_ASSEMBLY,
            approved_revision_number=2,
        )
        assert_cabinet_fields(
            plant.cabinet(cabinet["id"]),
            cabinet_state=CABINET_POPULATED,
            installed_module_count=1,
        )

    def test_a_further_submission_after_approval_moves_neither_dimension(self, plant):
        """A project whose `engineering_state` is already `APPROVED` accepts no
        further revision submission — otherwise `ERR_ENGINEERING_ALREADY_APPROVED`.

        Design: Difficulty/non_linear_state_machine/project_engineering_and_production_dimensions_advance_independently
        """
        model, project, _, _ = self._rejected_then_approved_wall(plant)
        cabinet = plant.plan_cabinet(project["id"])
        module = plant.calibrated_module(model["id"])
        plant.install(cabinet["id"], module["id"], 1)

        response = plant.api.create_drawing_revision(
            {
                "project_id": project["id"],
                "structural_load_kg_per_sqm": 100.00,
                "wind_load_kph": 100,
                "mounting_type": "WALL",
                "service_access_side": "FRONT",
            },
            plant.engineer,
        )

        validate_error(response, ERR_ENGINEERING_ALREADY_APPROVED, 409)
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            production_state=PRODUCTION_IN_ASSEMBLY,
            approved_revision_number=2,
        )


class TestServiceCaseAssessmentFork:
    """The two assessment branches write disjoint sets of fields."""

    def test_approval_pins_the_basis_the_credit_and_the_faulty_module(self, plant):
        """Approval also pins which module will be swapped, writing it to
        `resolved_faulty_module_id`.

        Design: Difficulty/non_linear_state_machine/service_case_fork_approve_vs_deny_divergent_side_effects
        """
        scene = _two_responded_degradation_claims(plant)

        approved = plant.assess(
            scene.case_a["id"],
            decision="APPROVE",
            assessment_basis="PRO_RATA_REMAINING_TERM",
        )

        assert_case_fields(
            approved,
            case_state=CASE_APPROVED,
            assessment_basis="PRO_RATA_REMAINING_TERM",
            resolved_faulty_module_id=scene.modules[0]["id"],
            denial_reason=None,
        )
        assert_cents(approved["credit_cents"], 92160, "credit_cents")

    def test_denial_records_a_reason_and_pins_nothing(self, plant):
        """A `DENY` requires `denial_reason` to be present and between 1 and 240
        characters, stores it, sets `credit_cents` to 0, leaves
        `assessment_basis` null, leaves both `resolved_faulty_module_id` and
        `replacement_module_id` null, and moves the case `RESPONDED → DENIED`,
        which is terminal.

        Design: Difficulty/non_linear_state_machine/service_case_fork_approve_vs_deny_divergent_side_effects
        """
        scene = _two_responded_degradation_claims(plant)

        denied = plant.assess(
            scene.case_b["id"], decision="DENY", denial_reason=DENIAL_REASON
        )

        assert_case_fields(
            denied,
            case_state=CASE_DENIED,
            assessment_basis=None,
            resolved_faulty_module_id=None,
            replacement_module_id=None,
            denial_reason=DENIAL_REASON,
        )
        assert_cents(denied["credit_cents"], 0, "credit_cents")

    def test_the_fork_is_taken_only_once(self, plant):
        """The case's `case_state` permits the operation: `OPEN` for response,
        `RESPONDED` for assessment, `APPROVED` for fulfilment — otherwise
        `ERR_INVALID_CASE_STATE`.

        Design: Difficulty/non_linear_state_machine/service_case_fork_approve_vs_deny_divergent_side_effects
        """
        scene = _two_responded_degradation_claims(plant)
        plant.assess(
            scene.case_a["id"],
            decision="APPROVE",
            assessment_basis="PRO_RATA_REMAINING_TERM",
        )

        response = plant.api.assess_case(
            scene.case_a["id"],
            {"decision": "DENY", "denial_reason": DENIAL_REASON},
            plant.service,
        )

        validate_error(response, ERR_INVALID_CASE_STATE, 409)
        unchanged = plant.case(scene.case_a["id"])
        assert_case_fields(
            unchanged,
            case_state=CASE_APPROVED,
            assessment_basis="PRO_RATA_REMAINING_TERM",
            denial_reason=None,
        )
        assert_cents(unchanged["credit_cents"], 92160, "credit_cents")
