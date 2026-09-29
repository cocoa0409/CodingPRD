"""Operations refused because of a neighbouring entity's state, not their own."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    assert_bay_ledger,
    assert_project_state,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_fabrication_manager_headers,
)


class TestPackageReviewBlockedByASupersededStage:
    """A perfectly valid DRAFT package cannot be reviewed once its stage is superseded."""

    def _superseded_stage_with_a_draft_package(self, api):
        state = fixtures.scoped_single_stage_project(api)
        state["package"] = fixtures.add_draft_package(
            api, state["filtration_stage"]["id"], state["material_spec"]["id"]
        )
        state["second_stages"] = fixtures.run_selection(api, state["project"]["id"])
        state["replacement_stage"] = state["second_stages"][0]
        return state

    def test_submitting_a_package_under_a_superseded_stage_is_refused(self, api):
        """The package is DRAFT and legal, yet the stage it hangs from refuses the submission.

        The PRD says "submission requires that the parent stage be `SELECTED` or
        `ENGINEERED`; a superseded stage refuses the submission with
        `ERR_STAGE_SUPERSEDED`", and of a re-run that "equipment packages whose stage
        has just been superseded keep their own status untouched -- nothing is deleted
        -- but their stage precondition now blocks every further engineering step on
        them, reported as `ERR_STAGE_SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/package_review_blocked_by_superseded_treatment_stage
        """
        state = self._superseded_stage_with_a_draft_package(api)

        response = api.submit_package_for_review(
            state["package"]["id"], make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.STAGE_SUPERSEDED.value, 409)

    def test_the_re_run_supersedes_the_old_stage_and_leaves_the_package_in_draft(
        self, api
    ):
        """The old stage is SUPERSEDED, the replacement is SELECTED, and the project self-loops.

        The PRD says "a project already in `SCOPED` may be re-scoped, which leaves it
        in `SCOPED` -- a `SCOPED → SCOPED` self-loop rather than a new state", and that
        on a permitted re-run "every existing stage of the project in `SELECTED` or
        `ENGINEERED` transitions to `SUPERSEDED` ... a fresh set of stages is then
        created exactly as on the first run".

        Design: Difficulty/cross_entity_state_dependency/package_review_blocked_by_superseded_treatment_stage
        """
        state = self._superseded_stage_with_a_draft_package(api)

        api.submit_package_for_review(
            state["package"]["id"], make_application_engineer_headers()
        )

        old_stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert old_stage["status"] == "SUPERSEDED"

        new_stage = validate_success(
            api.get_treatment_stage(
                state["replacement_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert new_stage["status"] == "SELECTED"

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "DRAFT"

        project = validate_success(
            api.get_project(state["project"]["id"], make_application_engineer_headers())
        )
        assert_project_state(project, status="SCOPED")


class TestBayBookingBlockedByHalfBuiltSkid:
    """A mechanically complete skid whose controls are untouched cannot be booked."""

    def _mechanically_complete_only(self, api):
        state = fixtures.released_single_stage_project(api)
        state["skid"] = fixtures.drive_skid_mechanically_complete(
            api, state["skid"]["id"]
        )
        return state

    def test_booking_a_skid_that_is_not_ready_is_refused(self, api):
        """Readiness is a fold of both axes, so a skid with untouched controls is refused.

        Booking requires that "the skid must be genuinely testable: its parent package
        must be in `RELEASED_FOR_FAB` and its `fat_readiness` must be `READY`,
        otherwise `ERR_SKID_NOT_FAT_READY`." And readiness only reaches `READY` when
        "`mechanical_status` is `MECH_COMPLETE` **and** `controls_status` is
        `CONTROLS_COMPLETE` **and** the parent package's status is `RELEASED_FOR_FAB`".

        Design: Difficulty/cross_entity_state_dependency/fat_scheduling_blocked_by_skid_readiness
        """
        state = self._mechanically_complete_only(api)

        response = api.create_fat_run(
            factories.fat_run_payload(
                state["skid"]["id"],
                state["test_bay"]["id"],
                state["skid"]["version"],
            ),
            make_fabrication_manager_headers(),
        )

        validate_error(response, ApiErrorId.SKID_NOT_FAT_READY.value, 422)

    def test_the_refused_booking_reserves_nothing_in_the_bay(self, api):
        """No run row is created and the bay's footprint-minute ledger stays at zero.

        A new bay "starts with `reserved_footprint_minutes` at 0", and section 2.11
        pins that "at every instant it equals the sum, over every factory test run
        booked on that bay whose status is still `SCHEDULED`, of that run's
        `footprint_sf` multiplied by its `duration_minutes`."

        Design: Difficulty/cross_entity_state_dependency/fat_scheduling_blocked_by_skid_readiness
        """
        state = self._mechanically_complete_only(api)

        api.create_fat_run(
            factories.fat_run_payload(
                state["skid"]["id"],
                state["test_bay"]["id"],
                state["skid"]["version"],
            ),
            make_fabrication_manager_headers(),
        )

        assert_skid_state(
            state["skid"],
            mechanical_status="MECH_COMPLETE",
            controls_status="PANEL_BUILD",
            fat_readiness="NOT_READY",
        )

        _, meta = validate_paginated(
            api.list_fat_runs(
                make_fabrication_manager_headers(),
                {"skid_id": state["skid"]["id"]},
            )
        )
        assert meta["total_count"] == 0

        bay = validate_success(
            api.get_test_bay(state["test_bay"]["id"], make_fabrication_manager_headers())
        )
        assert_bay_ledger(bay, 0)
