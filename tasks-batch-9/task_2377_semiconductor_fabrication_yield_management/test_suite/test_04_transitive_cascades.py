"""Single acts whose consequences chain several entities deep.

Each scenario fires one request and then walks the whole chain of rows the
server was obliged to touch inside that same request.
"""

from test_helpers import (
    LotSpec,
    USER_PROCESS_ENGINEER,
    USER_QUALITY_MANAGER,
    build_line,
    complete_step,
    open_run,
    raise_particle_excursion,
    two_recipe_line_spec,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_ratio,
)


# --------------------------------------------------------------------------
# A particle reading reaching a lot hold five levels down
# --------------------------------------------------------------------------


def _open_etch_run_no_measurement(fab):
    """An open, unmeasured etch run on a clean chamber of a productive tool."""
    env = build_line(fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")]))
    complete_step(fab, env, step_ix=0, lot_ix=0)
    env.run = open_run(fab, env, step_ix=1, lot_ix=0)
    return env


class TestParticleReadingCascade:
    def test_a_gross_particle_reading_auto_contains_at_equipment_scope(self, fab):
        """Twice the limit contains itself at tool scope with no human in the loop.

        PRD: "The automatic `containment_scope` is chosen by magnitude:
        `EQUIPMENT` when the reading is at or above twice the chamber's
        `particle_limit`, and `CHAMBER` otherwise."

        Design: Difficulty/transitive_cascade/particle_reading_cascades_five_deep_to_lot_qual_hold
        """
        env = _open_etch_run_no_measurement(fab)

        raised = raise_particle_excursion(fab, env, 100.0, chamber_ix=1)

        assert_hours(raised["chamber"]["particle_count"], 100.0, "particle_count")
        excursion = raised["excursion"]
        assert excursion is not None, "a reading above the limit must open an excursion"
        assert_fields(
            excursion,
            source_type="PARTICLE",
            status="CONTAINED",
            severity_variant="FINAL",
            containment_scope="EQUIPMENT",
            affected_lot_count=1,
            severity_band="MEDIUM",
        )
        assert_ratio(excursion["trigger_value"], 100.0, "trigger_value")
        # A saturated 60.0 deviation term plus 3.0 for the single exposed lot.
        assert_hours(excursion["severity_score"], 63.00, "severity_score")
        assert_nulls(excursion, "contained_by_user_id")

    def test_the_cascade_reaches_the_lot_and_leaves_the_ledger_whole(self, fab):
        """Reading to excursion to tool-down to aborted run to lot hold.

        PRD: "Cascades chain. Containing an excursion at tool scope drives the
        tool from `PRODUCTIVE` to `DOWN`, which aborts every open run on that
        tool's chambers, which credits each run's reservation back to the tool's
        capacity ledger."

        Design: Difficulty/transitive_cascade/particle_reading_cascades_five_deep_to_lot_qual_hold
        """
        env = _open_etch_run_no_measurement(fab)
        raised = raise_particle_excursion(fab, env, 100.0, chamber_ix=1)

        tool = fab.read_equipment(env.equipments[1]["id"])
        assert tool["state"] == "DOWN"
        assert_hours(tool["available_capacity_hours"], 720.00, "available_capacity_hours")
        assert_hours(tool["hours_since_pm"], 0.0, "hours_since_pm")

        run = fab.read_step_run(env.run["id"])
        assert run["status"] == "ABORTED"
        assert_nulls(run, "actual_hours")
        assert_hours(run["reserved_hours"], 3.00, "reserved_hours")

        chamber = fab.read_chamber(env.chambers[1]["id"])
        assert_fields(chamber, qual_state="DISQUALIFIED", occupancy_state="FREE")

        lot = fab.read_lot(env.lots[0]["id"])
        assert_lot_state(
            lot, flow_state="IN_PROCESS", hold_state="QUAL_HOLD", current_step_seq=10
        )
        assert lot["hold_excursion_id"] == raised["excursion"]["id"]


# --------------------------------------------------------------------------
# An engineering change implementation reaching a lot hold
# --------------------------------------------------------------------------


def _approved_high_risk_notice(fab):
    """A CRITICAL notice approved against the etch recipe of an in-process lot."""
    env = build_line(fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")]))
    complete_step(fab, env, step_ix=0, lot_ix=0)
    env.run = open_run(fab, env, step_ix=1, lot_ix=0)

    etch_recipe = env.recipes[1]
    env.notice = fab.change_request(
        etch_recipe["id"], "CRITICAL", 104.0, "Four-percent etch depth increase",
        author_user_id=USER_PROCESS_ENGINEER,
    )
    env.recipe_version = etch_recipe["version"]
    return env


class TestChangeImplementationCascade:
    def test_approval_pins_the_revision_and_restricts_the_recipe(self, fab):
        """The blast-radius term lifts the score past the requal threshold.

        PRD: "The recipe is driven `QUALIFIED → RESTRICTED` with
        `restricted_reason` set to `ECN_PENDING_IMPLEMENTATION`; if a sibling
        approval has already left the recipe `RESTRICTED`, the recipe stays
        `RESTRICTED` with its `restricted_reason` unchanged."

        Design: Difficulty/transitive_cascade/ecn_implement_cascades_requalification_into_lot_qual_hold
        """
        env = _approved_high_risk_notice(fab)

        # 60.0 class + 10.0 delta + 15.0 * (1/20) blast radius.
        assert env.notice["impact_lot_count"] == 1
        assert_hours(env.notice["risk_score"], 70.75, "risk_score")
        assert env.notice["requires_full_requal"] is True

        approved = fab.approve_change_request(
            env.notice["id"], env.recipe_version, approver_user_id=USER_QUALITY_MANAGER
        )
        assert_fields(
            approved,
            status="APPROVED",
            pinned_recipe_revision=1,
            approver_user_id=USER_QUALITY_MANAGER,
        )
        assert_fields(
            fab.read_recipe(env.recipes[1]["id"]),
            status="RESTRICTED",
            restricted_reason="ECN_PENDING_IMPLEMENTATION",
        )

    def test_implementation_unqualifies_the_chambers_and_holds_their_lots(self, fab):
        """Only chambers set up on that recipe move, and the open run survives.

        PRD: "Implementing a high-risk recipe change returns the recipe to
        `QUALIFIED`, which unqualifies every chamber set up on that recipe,
        which places the in-process lots sitting in those chambers onto
        qualification hold."

        Design: Difficulty/transitive_cascade/ecn_implement_cascades_requalification_into_lot_qual_hold
        """
        env = _approved_high_risk_notice(fab)
        fab.approve_change_request(
            env.notice["id"], env.recipe_version, approver_user_id=USER_QUALITY_MANAGER
        )

        implemented = fab.implement_change_request(env.notice["id"])

        assert implemented["status"] == "IMPLEMENTED"
        recipe = fab.read_recipe(env.recipes[1]["id"])
        assert_fields(recipe, status="QUALIFIED", revision=2, restricted_reason="NONE")
        assert_hours(recipe["target_value"], 104.00, "target_value")

        assert fab.read_chamber(env.chambers[1]["id"])["qual_state"] == "UNQUALIFIED"
        assert fab.read_chamber(env.chambers[0]["id"])["qual_state"] == "QUALIFIED"

        lot = fab.read_lot(env.lots[0]["id"])
        assert_lot_state(lot, flow_state="IN_PROCESS", hold_state="QUAL_HOLD")
        assert_nulls(lot, "hold_excursion_id")
        # A requalification cascade is not a containment, so the run is untouched.
        assert fab.read_step_run(env.run["id"])["status"] == "OPEN"
