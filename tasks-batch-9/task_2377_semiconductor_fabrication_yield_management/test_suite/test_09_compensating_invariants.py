"""Quantities that must come back to exactly where they started.

Each scenario debits a ledger, reverses the act that debited it, and pins the
restored value against the value observed before the reversal so that neither
drift nor double-counting can hide.
"""

from test_helpers import (
    ChamberSpec,
    EquipmentSpec,
    LotSpec,
    build_line,
    two_recipe_line_spec,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_ledger_restored,
    assert_lot_state,
    assert_nulls,
    assert_wafer_conservation,
)


# --------------------------------------------------------------------------
# The tool capacity ledger across a completed run and an aborted one
# --------------------------------------------------------------------------


def _fresh_litho_tool_two_lots(fab):
    """One litho tool at its full 720.00 hour ledger, with two released lots."""
    spec = two_recipe_line_spec(
        equipments=[EquipmentSpec("LITHO-1", "LITHO", 168.0, 0.0, 0.0)],
        chambers=[ChamberSpec("CH_L1", equipment_ix=0, recipe_ix=0)],
    )
    return build_line(fab, spec)


class TestCapacityLedgerRestoredOnAbort:
    def test_a_completed_run_converts_its_reservation_into_consumption(self, fab):
        """The reservation is credited back and the actual hours debited in its place.

        PRD: "The tool's `available_capacity_hours` has `reserved_hours`
        credited back and `actual_hours` debited, and its `hours_since_pm` has
        `actual_hours` added."

        Design: Difficulty/compensating_invariant/equipment_capacity_hours_restored_exactly_on_abort
        """
        env = _fresh_litho_tool_two_lots(fab)
        operator_id = env.operators[0]["id"]
        equipment_id = env.equipments[0]["id"]

        opening = fab.read_equipment(equipment_id)
        assert_hours(opening["available_capacity_hours"], 720.00, "available_capacity_hours")
        assert_hours(opening["hours_since_pm"], 0.0, "hours_since_pm")

        run = fab.track_in(env.lots[0]["id"], env.steps[0]["id"], operator_id)
        assert_hours(run["reserved_hours"], 2.00, "reserved_hours")
        reserved = fab.read_equipment(equipment_id)
        assert_hours(reserved["available_capacity_hours"], 718.00, "available_capacity_hours")
        assert_hours(reserved["hours_since_pm"], 0.0, "hours_since_pm")

        fab.set_clock("2026-08-01T02:00:00Z")
        closed = fab.track_out(run["id"], operator_id)

        assert closed["status"] == "COMPLETED"
        assert_hours(closed["actual_hours"], 2.00, "actual_hours")
        consumed = fab.read_equipment(equipment_id)
        assert_hours(consumed["available_capacity_hours"], 718.00, "available_capacity_hours")
        assert_hours(consumed["hours_since_pm"], 2.0, "hours_since_pm")

    def test_an_aborted_run_gives_the_whole_reservation_back(self, fab):
        """The ledger returns to the exact value it held before the second track-in.

        PRD: "The tool's `available_capacity_hours` has the *full*
        `reserved_hours` credited back, leaving no drift, while its
        `hours_since_pm` is untouched."

        Design: Difficulty/compensating_invariant/equipment_capacity_hours_restored_exactly_on_abort
        """
        env = _fresh_litho_tool_two_lots(fab)
        operator_id = env.operators[0]["id"]
        equipment_id = env.equipments[0]["id"]

        first_run = fab.track_in(env.lots[0]["id"], env.steps[0]["id"], operator_id)
        fab.set_clock("2026-08-01T02:00:00Z")
        fab.track_out(first_run["id"], operator_id)
        before = fab.read_equipment(equipment_id)

        second_run = fab.track_in(env.lots[1]["id"], env.steps[0]["id"], operator_id)
        assert_hours(second_run["reserved_hours"], 2.00, "reserved_hours")
        assert_hours(
            fab.read_equipment(equipment_id)["available_capacity_hours"],
            716.00,
            "available_capacity_hours",
        )

        fab.set_clock("2026-08-01T07:00:00Z")
        aborted = fab.abort_run(
            second_run["id"], operator_id, "Reticle mismatch found at the tool"
        )

        assert aborted["status"] == "ABORTED"
        assert_nulls(aborted, "actual_hours")
        after = fab.read_equipment(equipment_id)
        assert_hours(after["available_capacity_hours"], 718.00, "available_capacity_hours")
        assert_ledger_restored(
            before["available_capacity_hours"], after["available_capacity_hours"]
        )
        # Five hours of wall clock passed, and none of it was charged to the tool.
        assert_hours(after["hours_since_pm"], 2.0, "hours_since_pm")
        assert float(after["hours_since_pm"]) == float(before["hours_since_pm"])
        assert after["state"] == "IDLE"
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        assert_lot_state(fab.read_lot(env.lots[1]["id"]), current_step_seq=0)


# --------------------------------------------------------------------------
# The wafer pool across a split and its rejoin
# --------------------------------------------------------------------------


def _released_lot_of_twenty_five_wafers(fab):
    """A 25-wafer lot released against a committed plan."""
    return build_line(
        fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 25, "STANDARD")])
    )


class TestWaferPoolConservation:
    def test_a_split_moves_wafers_without_creating_or_destroying_any(self, fab):
        """20 in the parent plus 5 in the child still totals the original 25.

        PRD: "After every split and every rejoin, the parent's `wafer_count` plus
        the sum of `wafer_count` over its non-scrapped children equals the
        parent's `origin_wafer_count`."

        Design: Difficulty/compensating_invariant/wafer_inventory_conserved_across_split_and_rejoin
        """
        env = _released_lot_of_twenty_five_wafers(fab)
        parent_id = env.lots[0]["id"]
        assert_fields(env.lots[0], wafer_count=25, origin_wafer_count=25)
        assert fab.read_plan(env.plan["id"])["released_wafer_starts"] == 25

        child = fab.split_lot(parent_id, 5, "LOT-001-E1", "HOT")

        assert_fields(
            child,
            wafer_count=5,
            origin_wafer_count=5,
            lot_type="ENGINEERING_SPLIT",
            parent_lot_id=parent_id,
        )
        assert_lot_state(
            child, flow_state="RELEASED", hold_state="ENGINEERING_HOLD", current_step_seq=0
        )

        parent = fab.read_lot(parent_id)
        assert_fields(parent, wafer_count=20, origin_wafer_count=25)
        assert_wafer_conservation(parent, child)
        # An engineering split never draws on the plan's authorisation.
        assert fab.read_plan(env.plan["id"])["released_wafer_starts"] == 25

    def test_a_rejoin_folds_the_wafers_back_and_empties_the_child(self, fab):
        """The parent returns to 25 and the plan ledger never moved at all.

        PRD: "On success the parent's `wafer_count` is increased by the child's
        `wafer_count`, the child's `wafer_count` is set to 0, the child's
        `hold_state` returns to `NONE` and its `flow_state` becomes `COMPLETED`,
        and both the child's and the parent's `version` increment by 1."

        Design: Difficulty/compensating_invariant/wafer_inventory_conserved_across_split_and_rejoin
        """
        env = _released_lot_of_twenty_five_wafers(fab)
        parent_id = env.lots[0]["id"]
        child = fab.split_lot(parent_id, 5, "LOT-001-E1", "HOT")
        starts_after_split = fab.read_plan(env.plan["id"])["released_wafer_starts"]

        rejoined = fab.rejoin_lot(child["id"])

        assert rejoined["wafer_count"] == 0
        assert_lot_state(rejoined, flow_state="COMPLETED", hold_state="NONE")

        parent = fab.read_lot(parent_id)
        assert_fields(parent, wafer_count=25, origin_wafer_count=25, rework_count=0)
        assert_wafer_conservation(parent, rejoined)
        assert fab.read_plan(env.plan["id"])["released_wafer_starts"] == 25
        assert (
            fab.read_plan(env.plan["id"])["released_wafer_starts"] == starts_after_split
        )
