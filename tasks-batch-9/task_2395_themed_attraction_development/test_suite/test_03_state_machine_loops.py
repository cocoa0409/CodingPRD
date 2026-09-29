"""States this system re-enters: the revision round and the scene hold."""
from test_helpers import (
    CREATIVE_DIRECTOR_USER_ID,
    TEST_USERS,
    add_package,
    assert_package_pricing,
    assert_scene_held_from,
    assert_scene_not_held,
    patch_project,
    read_capacity_summary,
    request_revision,
    revise_package,
    setup_program_at_schematic,
    setup_program_with_approved_package,
    setup_programmed_scene,
    submit_package,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]


class TestDesignPackageRevisionLoop:
    """SUBMITTED is occupied three times over two completed loops."""

    def test_two_completed_loops_leave_revision_round_at_two(self, api):
        """Submitting again moves `REVISION_REQUESTED` back to `SUBMITTED`, and this time the package's `revision_round` is incremented by one, counting the completed loop; `revision_round` starts at 0 and a first submission out of `DRAFT` does not touch it.

        From `REVISION_REQUESTED` the designer may re-price it — supplying a new
        `base_construction_cost_cents` together with the required
        `expected_package_version` — which re-runs all four pricing steps and
        advances the `version` again; re-pricing is also available while the package
        is still `DRAFT`.

        The second re-price lifts the base to 2800000000, which re-tiers the package
        into the eight-and-a-half-percent band for a total of 3341800000, and the
        package is back in SUBMITTED without a cent having been committed.

        Design: Difficulty/non_linear_state_machine/design_package_revision_loop_reenters_submitted_twice
        """
        ctx = setup_program_at_schematic(
            project_overrides={"budget_ceiling_cents": 9000000000}
        )
        package = add_package(ctx["project"]["id"], ctx["ride_system"]["id"])
        submit_package(package["id"])

        request_revision(package["id"], reason="Show set clashes with ride envelope in scene two")
        revise_package(package["id"], 2400000000)
        submit_package(package["id"])
        request_revision(package["id"], reason="Owner now wants the full practical rockwork restored")
        revise_package(package["id"], 2800000000)
        resubmitted = submit_package(package["id"])

        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_round"] == 2
        assert_package_pricing(resubmitted, base=2800000000, design_fee=238000000,
                               contingency=303800000, total=3341800000)
        assert resubmitted["submitted_by_user_id"] == CREATIVE_DIRECTOR_USER_ID
        programme = validate_success(api.get_project(ctx["project"]["id"], OWNER))
        assert programme["committed_cost_cents"] == 0

    def test_first_loop_re_prices_then_counts_one_completed_round(self):
        """An `OwnerRep` may return a `SUBMITTED` package for revision with a `reason`, moving it to `REVISION_REQUESTED` and advancing its `version`.

        Revision is a genuine loop, not a dead end.

        The first request for revision leaves the round counter untouched, the
        re-price to 2400000000 re-runs all four steps for a total of 2956800000,
        and only the return to SUBMITTED counts the loop as one.

        Design: Difficulty/non_linear_state_machine/design_package_revision_loop_reenters_submitted_twice
        """
        ctx = setup_program_at_schematic(
            project_overrides={"budget_ceiling_cents": 9000000000}
        )
        package = add_package(ctx["project"]["id"], ctx["ride_system"]["id"])
        first_submission = submit_package(package["id"])
        assert first_submission["revision_round"] == 0

        returned = request_revision(package["id"], reason="Show set clashes with ride envelope in scene two")
        assert returned["status"] == "REVISION_REQUESTED"
        assert returned["revision_round"] == 0

        repriced = revise_package(package["id"], 2400000000)
        assert repriced["status"] == "REVISION_REQUESTED"
        assert_package_pricing(repriced, base=2400000000, design_fee=240000000,
                               contingency=316800000, total=2956800000)

        resubmitted = submit_package(package["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_round"] == 1


class TestShowSceneHoldAndRelease:
    """PROGRAMMED leaves for HELD and comes back to precisely PROGRAMMED."""

    def _frozen_programme_with_two_programmed_scenes(self):
        ctx = setup_program_with_approved_package()
        ctx["sc1"] = setup_programmed_scene(ctx, "sc1", 92, 88, 85, 88)
        ctx["sc2"] = setup_programmed_scene(ctx, "sc2", 70, 60, 65, 70)
        ctx["project"] = patch_project(ctx["project"]["id"], budget_ceiling_cents=3000000000)
        return ctx

    def test_release_restores_each_scene_to_its_recorded_held_from_status(self, api):
        """Because the release target is pinned by `held_from_status` rather than by a fixed state, a scene that was `VALIDATED` before a freeze returns to `VALIDATED` and never regresses to `PROGRAMMED`.

        Leaving `FROZEN` reverses the cascade exactly.

        Raising the ceiling back to 3600000000 leaves the committed 3080000000 at or
        below the restricted-utilisation threshold, so the posture settles on OPEN,
        both scenes return to PROGRAMMED with their hold fields cleared, and the
        duration-weighted roll-up of 88.10 over 180 seconds and 66.50 over 120
        seconds returns to 79.46 without a single discipline score being rewritten.

        Design: Difficulty/non_linear_state_machine/show_scene_hold_and_release_restores_programmed_status
        """
        ctx = self._frozen_programme_with_two_programmed_scenes()

        released = patch_project(ctx["project"]["id"], budget_ceiling_cents=3600000000)
        summary = read_capacity_summary(ctx["project"]["id"])
        sc1 = validate_success(api.get_show_scene(ctx["sc1"]["id"], DESIGNER))
        sc2 = validate_success(api.get_show_scene(ctx["sc2"]["id"], DESIGNER))

        assert released["readiness_posture"] == "OPEN"
        assert sc1["status"] == "PROGRAMMED"
        assert_scene_not_held(sc1)
        assert float(sc1["scene_quality_score"]) == 88.10
        assert sc2["status"] == "PROGRAMMED"
        assert_scene_not_held(sc2)
        assert float(sc2["scene_quality_score"]) == 66.50
        assert float(summary["show_quality_score"]) == 79.46

    def test_hold_records_the_source_status_and_empties_the_roll_up(self, api):
        """Every scene of the programme whose `status` is `SEQUENCED`, `PROGRAMMED` or `VALIDATED` moves to `HELD`; its `held_from_status` is set to whichever of those three values it held immediately before the freeze; and its `hold_reason` is set to `SAFETY_FREEZE` when `open_critical_finding_count` is greater than zero, and to `BUDGET_FREEZE` otherwise.

        Scenes in `DRAFT`, `SEQUENCED` or `HELD` are excluded from both the
        numerator and the denominator, which is why a freeze cascade changes the
        programme's score without touching any score field; when the included set is
        empty the programme's score is exactly 0.00.

        Cutting the ceiling to 3000000000 below the committed 3080000000 freezes the
        programme on cost alone, so both scenes record PROGRAMMED as the status they
        came from, keep their own scores, and leave the programme roll-up empty.

        Design: Difficulty/non_linear_state_machine/show_scene_hold_and_release_restores_programmed_status
        """
        ctx = self._frozen_programme_with_two_programmed_scenes()

        sc1 = validate_success(api.get_show_scene(ctx["sc1"]["id"], DESIGNER))
        sc2 = validate_success(api.get_show_scene(ctx["sc2"]["id"], DESIGNER))

        assert ctx["project"]["readiness_posture"] == "FROZEN"
        assert_scene_held_from(sc1, held_from_status="PROGRAMMED", hold_reason="BUDGET_FREEZE")
        assert_scene_held_from(sc2, held_from_status="PROGRAMMED", hold_reason="BUDGET_FREEZE")
        assert float(sc1["scene_quality_score"]) == 88.10
        assert float(sc2["scene_quality_score"]) == 66.50
        assert float(ctx["project"]["show_quality_score"]) == 0.00
