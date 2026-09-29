"""State machines that cycle, and whose exits are owned by another entity.

Each scenario drives a row back into a state it has already occupied, then
proves the second visit arrived through a different edge than the first.
"""

from test_helpers import (
    LotSpec,
    build_line,
    complete_step,
    raise_spc_excursion,
    two_recipe_line_spec,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_timestamp_equals,
)


# --------------------------------------------------------------------------
# The change-notice revision cycle
# --------------------------------------------------------------------------


class TestChangeNoticeRevisionCycle:
    def test_the_revision_loop_returns_the_notice_to_submitted(self, fab):
        """SUBMITTED to REVISION_REQUESTED and back is a genuine cycle.

        PRD: "This is the cycle that makes the change-control machine cyclic:
        `SUBMITTED → REVISION_REQUESTED → SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/change_request_revision_cycle_then_third_request_rejects
        """
        recipe = fab.recipe("ETCH-100", "ETCH", 100.0, 100)
        notice = fab.change_request(
            recipe["id"], "MAJOR", 110.0, "Widen etch depth by ten percent"
        )
        # 35.0 class weight plus a saturated 25.0 delta term, no lots exposed.
        assert_hours(notice["risk_score"], 60.00, "risk_score")
        assert notice["requires_full_requal"] is False

        sent_back = fab.request_change_revision(notice["id"], "Attach split-lot evidence")
        assert_fields(sent_back, status="REVISION_REQUESTED", revision_round=0)

        resubmitted = fab.resubmit_change_request(
            notice["id"], "MAJOR", 110.0, "Split-lot evidence attached"
        )
        assert_fields(resubmitted, status="SUBMITTED", revision_round=1)

        sent_back_again = fab.request_change_revision(
            notice["id"], "Evidence covers only one tool"
        )
        assert_fields(sent_back_again, status="REVISION_REQUESTED", revision_round=1)

        resubmitted_again = fab.resubmit_change_request(
            notice["id"], "MAJOR", 110.0, "Evidence extended to both tools"
        )
        assert_fields(resubmitted_again, status="SUBMITTED", revision_round=2)
        assert sent_back["status"] == sent_back_again["status"]

    def test_the_third_revision_request_rejects_the_notice_outright(self, fab):
        """The same trigger branches to REJECTED once two rounds are on the clock.

        PRD: "Once `revision_round` has reached 2, the same request instead
        drives the notice `SUBMITTED → REJECTED` — the third review that would
        send it back terminates the notice outright."

        Design: Difficulty/non_linear_state_machine/change_request_revision_cycle_then_third_request_rejects
        """
        recipe = fab.recipe("ETCH-100", "ETCH", 100.0, 100)
        notice = fab.change_request(
            recipe["id"], "MAJOR", 110.0, "Widen etch depth by ten percent"
        )
        fab.request_change_revision(notice["id"], "Attach split-lot evidence")
        fab.resubmit_change_request(notice["id"], "MAJOR", 110.0, "Split-lot evidence attached")
        fab.request_change_revision(notice["id"], "Evidence covers only one tool")
        fab.resubmit_change_request(
            notice["id"], "MAJOR", 110.0, "Evidence extended to both tools"
        )

        rejected = fab.request_change_revision(notice["id"], "Third pass, closing the notice")

        assert_fields(rejected, status="REJECTED", revision_round=2)
        assert_nulls(rejected, "approver_user_id")

        # Nothing in the loop ever touched the recipe itself.
        assert_fields(
            fab.read_recipe(recipe["id"]), status="QUALIFIED", revision=1
        )
        assert_hours(fab.read_recipe(recipe["id"])["target_value"], 100.00, "target_value")


# --------------------------------------------------------------------------
# The chamber qualification cycle
# --------------------------------------------------------------------------


def _out_of_spec_run_on_the_etch_chamber(fab):
    """An open etch run whose 112.00 reading has opened an out-of-spec excursion."""
    env = build_line(fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")]))
    complete_step(fab, env, step_ix=0, lot_ix=0)
    env.raised = raise_spc_excursion(fab, env, 112.0, step_ix=1, lot_ix=0)
    return env


class TestChamberQualificationCycle:
    def test_chamber_containment_disqualifies_the_chamber_and_aborts_its_run(self, fab):
        """CHAMBER scope takes the chamber out of QUALIFIED and frees it.

        PRD: "At `CHAMBER` scope, the implicated chamber is driven `QUALIFIED →
        DISQUALIFIED` with `qualified_at` and `qual_expires_at` cleared to null,
        its open run is driven `OPEN → ABORTED` with the full reservation
        credited back to the tool, and that run's lot is raised to `QUAL_HOLD`
        with its `hold_excursion_id` set to this excursion."

        Design: Difficulty/non_linear_state_machine/chamber_qualification_cycles_through_disqualification_and_pm
        """
        env = _out_of_spec_run_on_the_etch_chamber(fab)
        chamber_id = env.chambers[1]["id"]
        excursion_id = env.raised["excursion"]["id"]
        assert env.raised["measurement"]["classification"] == "OUT_OF_SPEC"

        contained = fab.contain(excursion_id, "CHAMBER", chamber_id=chamber_id)

        assert_fields(
            contained,
            status="CONTAINED",
            severity_variant="FINAL",
            containment_scope="CHAMBER",
        )
        chamber = fab.read_chamber(chamber_id)
        assert_fields(chamber, qual_state="DISQUALIFIED", occupancy_state="FREE")
        assert_nulls(chamber, "qualified_at", "qual_expires_at")

        run = fab.read_step_run(env.raised["run"]["id"])
        assert run["status"] == "ABORTED"
        assert_nulls(run, "actual_hours")
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]), hold_state="QUAL_HOLD", current_step_seq=10
        )
        # A chamber-scope containment leaves the chart monitoring.
        assert fab.read_chart(env.charts[0]["id"])["status"] == "MONITORING"

    def test_maintenance_is_the_only_exit_from_disqualified(self, fab):
        """DISQUALIFIED is left through the parent tool, then re-qualified afresh.

        PRD: "every chamber of the tool whose `qual_state` is `DISQUALIFIED` is
        driven `DISQUALIFIED → UNQUALIFIED`, which is what closes the chamber
        cycle `QUALIFIED → DISQUALIFIED → UNQUALIFIED → QUALIFIED`; every lot on
        `QUAL_HOLD` whose `hold_excursion_id` names an excursion raised on a
        chamber of this tool is released back to `hold_state` `NONE` with its
        `hold_excursion_id` cleared to null; and the tool's `version` increments
        by 1."

        Design: Difficulty/non_linear_state_machine/chamber_qualification_cycles_through_disqualification_and_pm
        """
        env = _out_of_spec_run_on_the_etch_chamber(fab)
        chamber_id = env.chambers[1]["id"]
        equipment_id = env.equipments[1]["id"]
        fab.contain(env.raised["excursion"]["id"], "CHAMBER", chamber_id=chamber_id)

        assert fab.pm_start(equipment_id, "Post-excursion chamber clean")["state"] == "PM"
        after_pm = fab.pm_complete(equipment_id)

        assert after_pm["state"] == "IDLE"
        assert_hours(after_pm["available_capacity_hours"], 720.00, "available_capacity_hours")
        assert_timestamp_equals(after_pm["purge_until"], "2026-08-02T00:00:00Z", "purge_until")
        assert fab.read_chamber(chamber_id)["qual_state"] == "UNQUALIFIED"

        requalified = fab.qualify_chamber(chamber_id, "PASS")
        assert requalified["qual_state"] == "QUALIFIED"
        assert_timestamp_equals(
            requalified["qualified_at"], "2026-08-01T00:00:00Z", "qualified_at"
        )
        assert_timestamp_equals(
            requalified["qual_expires_at"], "2026-11-09T00:00:00Z", "qual_expires_at"
        )


# --------------------------------------------------------------------------
# The tool state cycle
# --------------------------------------------------------------------------


class TestEquipmentStateCycle:
    def test_equipment_scope_containment_drives_a_productive_tool_down(self, fab):
        """The tool leaves PRODUCTIVE through an edge no tool endpoint offers.

        PRD: "At `EQUIPMENT` scope, the tool itself is driven to `DOWN` from
        either `IDLE` or `PRODUCTIVE`; a `PRODUCTIVE` tool additionally has
        every open run on its chambers driven `OPEN → ABORTED`, and any chamber
        leaving `QUALIFIED` as part of that containment raises its in-process
        lots to `QUAL_HOLD`."

        Design: Difficulty/non_linear_state_machine/equipment_state_cycles_productive_down_pm_idle
        """
        env = _out_of_spec_run_on_the_etch_chamber(fab)
        equipment_id = env.equipments[1]["id"]

        productive = fab.read_equipment(equipment_id)
        assert productive["state"] == "PRODUCTIVE"
        assert_hours(
            productive["available_capacity_hours"], 717.00, "available_capacity_hours"
        )

        contained = fab.contain(
            env.raised["excursion"]["id"], "EQUIPMENT", chamber_id=env.chambers[1]["id"]
        )
        assert contained["containment_scope"] == "EQUIPMENT"

        down = fab.read_equipment(equipment_id)
        assert down["state"] == "DOWN"
        # The aborted run's full 3.00 h reservation came back.
        assert_hours(down["available_capacity_hours"], 720.00, "available_capacity_hours")
        assert fab.read_step_run(env.raised["run"]["id"])["status"] == "ABORTED"

    def test_maintenance_is_the_recovery_path_out_of_down(self, fab):
        """DOWN exits only through PM, closing PRODUCTIVE to DOWN to PM to IDLE.

        PRD: "`DOWN` is therefore not terminal — maintenance is the recovery
        path out of it."

        Design: Difficulty/non_linear_state_machine/equipment_state_cycles_productive_down_pm_idle
        """
        env = _out_of_spec_run_on_the_etch_chamber(fab)
        equipment_id = env.equipments[1]["id"]
        fab.contain(
            env.raised["excursion"]["id"], "EQUIPMENT", chamber_id=env.chambers[1]["id"]
        )

        in_pm = fab.pm_start(equipment_id, "Tool-level contamination purge")
        assert in_pm["state"] == "PM"
        assert_timestamp_equals(
            in_pm["pm_started_at"], "2026-08-01T00:00:00Z", "pm_started_at"
        )

        idle = fab.pm_complete(equipment_id)
        assert idle["state"] == "IDLE"
        assert_timestamp_equals(idle["purge_until"], "2026-08-02T00:00:00Z", "purge_until")
        assert_hours(idle["hours_since_pm"], 0.0, "hours_since_pm")

        assert fab.read_chamber(env.chambers[1]["id"])["qual_state"] == "UNQUALIFIED"
