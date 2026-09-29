"""Loops and independent axes: state paths that are not a single straight line."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_common_fields,
    assert_money,
    assert_pct,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_design_reviewer_headers,
    make_fabrication_manager_headers,
)


class TestEquipmentPackageRevisionLoop:
    """A package driven DRAFT to IN_REVIEW to DRAFT and back up to APPROVED."""

    def _revision_loop(self, api):
        state = fixtures.scoped_single_stage_project(api)
        package = fixtures.add_draft_package(
            api, state["filtration_stage"]["id"], state["material_spec"]["id"]
        )
        api.submit_package_for_review(package["id"], make_application_engineer_headers())
        api.decide_package_review(
            package["id"],
            {
                "decision": "REQUEST_REVISION",
                "review_note": "Raise design pressure to 200 psig",
            },
            make_design_reviewer_headers(),
        )
        api.update_equipment_package(
            package["id"],
            {"design_pressure_psig": 200},
            make_application_engineer_headers(),
        )
        api.submit_package_for_review(
            package["id"],
            make_application_engineer_headers(),
            {"submittal_note": "Rev 1 at 200 psig"},
        )
        state["package"] = package
        return state

    def test_second_pass_approval_prices_the_revised_pressure(self, api):
        """Approval after one revision round prices the 200 psig design, not the original 150.

        `REQUEST_REVISION` "moves the package `IN_REVIEW → DRAFT`, increments
        `revision_round` by 1, stores the acting operator's identifier as
        `reviewed_by_user_id`, and advances the package's `version` by 1. This is a
        genuine cycle: a package may loop `DRAFT → IN_REVIEW → DRAFT` any number of
        times, each loop adding one to the revision round, and no cap applies." On
        the revision "whichever fields are omitted keep their stored values, the
        supplied ones overwrite, `budgetary_cost_cents` is re-derived, and the
        package's `version` advances by 1."

        Design: Difficulty/non_linear_state_machine/equipment_package_revision_loop_back_to_draft
        """
        state = self._revision_loop(api)

        package = validate_success(
            api.decide_package_review(
                state["package"]["id"],
                {"decision": "APPROVE", "review_note": "Rev 1 accepted"},
                make_design_reviewer_headers(),
            )
        )

        assert package["status"] == "APPROVED"
        assert package["revision_round"] == 1
        assert package["design_pressure_psig"] == 200
        assert_money(package["budgetary_cost_cents"], 264576000, "budgetary_cost_cents")
        assert_money(package["firm_cost_cents"], 291033600, "firm_cost_cents")
        assert package["reviewed_by_user_id"] == "rev-1"

    def test_the_reviewed_loop_still_lands_a_clean_variance_and_engineers_the_stage(
        self, api
    ):
        """The revised package's variance is still the bare cost index and the stage engineers.

        `APPROVE` "moves the package `IN_REVIEW → APPROVED`, stamps `approved_at` with
        the logical clock's current instant, stores `reviewed_by_user_id`, and freezes
        the firm price. Approval also cascades: the parent stage transitions
        `SELECTED → ENGINEERED` and advances its own `version` by 1". `variance_flag`
        "becomes true when that fraction is **strictly greater than** 0.15; a variance
        of exactly 0.15 leaves the flag false."

        Design: Difficulty/non_linear_state_machine/equipment_package_revision_loop_back_to_draft
        """
        state = self._revision_loop(api)

        package = validate_success(
            api.decide_package_review(
                state["package"]["id"],
                {"decision": "APPROVE", "review_note": "Rev 1 accepted"},
                make_design_reviewer_headers(),
            )
        )

        assert_pct(package["cost_variance_pct"], 0.1000, "cost_variance_pct")
        assert package["variance_flag"] is False

        stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert stage["status"] == "ENGINEERED"


class TestSkidBuildDimensionsAdvanceIndependently:
    """The controls axis walks to completion while the mechanical axis stands still."""

    def _controls_complete_skid(self, api):
        state = fixtures.released_single_stage_project(api)
        for to_state in ("IO_CHECKED", "LOOP_TESTED", "CONTROLS_COMPLETE"):
            api.record_skid_milestone(
                state["skid"]["id"],
                factories.milestone_payload("CONTROLS", to_state),
                make_fabrication_manager_headers(),
            )
        return state

    def test_controls_axis_completes_while_the_mechanical_axis_stays_at_frame_set(
        self, api
    ):
        """Three controls milestones leave the mechanical status untouched at FRAME_SET.

        The PRD says "a skid is built along two axes that advance separately and never
        interfere" and that "on the controls axis the legal edges are
        `PANEL_BUILD → IO_CHECKED`, `IO_CHECKED → LOOP_TESTED` and
        `LOOP_TESTED → CONTROLS_COMPLETE`. Every accepted milestone leaves the other
        axis's status untouched, recomputes `fat_readiness`, and advances the skid's
        `version` by 1."

        Design: Difficulty/non_linear_state_machine/skid_controls_dimension_advances_without_mechanical
        """
        state = self._controls_complete_skid(api)

        skid = validate_success(
            api.get_skid(state["skid"]["id"], make_fabrication_manager_headers())
        )

        assert_skid_state(
            skid,
            mechanical_status="FRAME_SET",
            controls_status="CONTROLS_COMPLETE",
            rework_count=0,
        )
        assert_common_fields(skid, expected_version=4)

    def test_a_half_built_skid_is_not_ready_and_its_package_is_still_in_fabrication(
        self, api
    ):
        """Readiness stays NOT_READY because the mechanical axis has not completed.

        Readiness "is a three-way fold of both axes plus the parent package's status,
        and it is never supplied by a client. If `mechanical_status` is `REWORK`,
        readiness is `BLOCKED`. Otherwise, if `mechanical_status` is `MECH_COMPLETE`
        **and** `controls_status` is `CONTROLS_COMPLETE` **and** the parent package's
        status is `RELEASED_FOR_FAB`, readiness is `READY`. In every other case
        readiness is `NOT_READY` -- which is the practical consequence of dimension
        independence".

        Design: Difficulty/non_linear_state_machine/skid_controls_dimension_advances_without_mechanical
        """
        state = self._controls_complete_skid(api)

        skid = validate_success(
            api.get_skid(state["skid"]["id"], make_fabrication_manager_headers())
        )
        assert skid["fat_readiness"] == "NOT_READY"
        assert skid["footprint_sf"] == 5400
        assert skid["requires_exclusive_bay"] is False

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "RELEASED_FOR_FAB"
