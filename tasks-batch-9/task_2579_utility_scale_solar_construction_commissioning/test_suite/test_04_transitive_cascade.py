"""One field measurement, four or five entities changed in the same request.

A string circuit that fails its retest and a pile that hits geotechnical refusal
both start chains that run outward through the block, the project's derived
readiness, the outstanding milestone claim and every live commissioning test.
The chains enter the block on different dimensions and end at different depths,
and no link is reachable without the one before it.
"""

from test_helpers.assertions import (
    assert_block_counters,
    assert_grading_area_state,
    assert_pile_disposition,
    assert_project_state,
    assert_string_test_failure,
)
from test_helpers.fixtures import (
    accepted_area,
    accepted_module_delivery,
    claim_milestone,
    create_block,
    create_circuit,
    create_pile,
    create_project,
    create_yard_zone,
    declare_mechanical_completion,
    read_block,
    read_commissioning_test,
    read_grading_area,
    read_pile,
    read_project,
    ready_project,
    record_drive_result,
    record_remediation,
    record_string_test,
    schedule_commissioning_test,
    set_clock,
    wire_circuit,
)
from test_helpers.test_users import EPC_PROJECT_MANAGER

# A fifteen-module string measured at 40 C expects 15 x 49.50 x (1 - 0.0028 x 15)
# == 711.32 V, with a three-percent allowance of 21.3396 V. 680.00 V is 31.32 V
# out and therefore fails, while the 705.00 V of the first test is 6.32 V out and
# passes.
DEVIATING_TEST = {
    "insulation_resistance_mohm": 55.0,
    "measured_voc_v": 680.00,
    "ambient_c": 40,
    "polarity_ok": True,
}


def _claimed_plant(api):
    """A READY plant with a scheduled capacity test and an outstanding MC claim."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rows = ready_project(api, name="Red Butte")
    rows["test"] = schedule_commissioning_test(
        api,
        rows["project"]["id"],
        test_type="CAPACITY",
        correction_variant="WEATHER_CORRECTED",
        scheduled_at="2026-08-11T15:00:00Z",
    )
    claim_milestone(api, rows["project"]["id"], "MECHANICAL_COMPLETION")
    assert_project_state(
        read_project(api, rows["project"]["id"]), milestone_state="MC_CLAIMED"
    )
    return rows


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/string_test_failure_cascades_to_auto_rejected_mc_claim_and_suspended_test
# ---------------------------------------------------------------------------
def test_the_first_two_hops_fail_the_circuit_and_force_the_block_into_rework(api):
    """A voltage deviation fails the circuit, and the block's electrical side follows.

    PRD 3.5: "Because the block now contains a failed circuit, its
    `electrical_status` is forced from `WIRED` or `TESTED` to `REWORK`; that is
    the second hop of the string-test-failure cascade."

    Design: Difficulty/transitive_cascade/string_test_failure_cascades_to_auto_rejected_mc_claim_and_suspended_test
    """
    rows = _claimed_plant(api)

    failed = record_string_test(api, rows["circuit"]["id"], **DEVIATING_TEST)

    assert_string_test_failure(failed, "VOC_DEVIATION")
    assert_block_counters(
        read_block(api, rows["block"]["id"]),
        electrical_status="REWORK",
        mechanical_status="MECH_COMPLETE",
        mc_ready=False,
        circuits_failed_count=1,
    )


def test_the_third_hop_takes_project_readiness_out_of_ready(api):
    """Losing the only ready block drops the project's derived verdict to BLOCKED.

    PRD 3.5: "`mc_readiness` is `READY` when the project has at least one block,
    when `blocks_mc_ready_count` equals `blocks_total`, and when every grading
    area of the project has `status` `ACCEPTED`; in every other case it is
    `BLOCKED`."

    Design: Difficulty/transitive_cascade/string_test_failure_cascades_to_auto_rejected_mc_claim_and_suspended_test
    """
    rows = _claimed_plant(api)

    record_string_test(api, rows["circuit"]["id"], **DEVIATING_TEST)

    assert_project_state(
        read_project(api, rows["project"]["id"]),
        mc_readiness="BLOCKED",
        blocks_mc_ready_count=0,
    )


def test_the_fourth_hop_withdraws_the_outstanding_claim_with_the_sentinel_reason(api):
    """No owner acts, yet the claim reverts and records the automatic reason.

    PRD 3.9: "Separately — and without any owner action — an outstanding claim is
    withdrawn automatically when a pile refusal or a string-circuit failure takes
    `mc_readiness` out of `READY`, in which case `last_milestone_rejection_reason`
    is set to the sentinel `AUTO_MC_READINESS_LOST` rather than to any
    client-supplied text."

    Design: Difficulty/transitive_cascade/string_test_failure_cascades_to_auto_rejected_mc_claim_and_suspended_test
    """
    rows = _claimed_plant(api)
    claimed = read_project(api, rows["project"]["id"])
    assert claimed["mc_claimed_by_user_id"] == EPC_PROJECT_MANAGER["X-User-ID"]

    record_string_test(api, rows["circuit"]["id"], **DEVIATING_TEST)

    after = read_project(api, rows["project"]["id"])
    assert_project_state(after, milestone_state="PRECONSTRUCTION")
    assert after["last_milestone_rejection_reason"] == "AUTO_MC_READINESS_LOST"
    assert after["mc_claimed_by_user_id"] is None


def test_the_fifth_hop_suspends_the_live_test_and_the_chain_stops_there(api):
    """The scheduled test is suspended, while the accepted civil work is untouched.

    PRD 3.5: "and every commissioning test of the project at `SCHEDULED` or
    `IN_PROGRESS` is driven to `SUSPENDED` with `suspend_reason`
    `MC_READINESS_LOST`."

    Design: Difficulty/transitive_cascade/string_test_failure_cascades_to_auto_rejected_mc_claim_and_suspended_test
    """
    rows = _claimed_plant(api)

    record_string_test(api, rows["circuit"]["id"], **DEVIATING_TEST)

    suspended = read_commissioning_test(api, rows["test"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspend_reason"] == "MC_READINESS_LOST"
    assert_grading_area_state(read_grading_area(api, rows["area"]["id"]), status="ACCEPTED")


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/pile_refusal_cascades_to_blocked_readiness_and_suspended_test
# ---------------------------------------------------------------------------
def _two_pile_plant(api):
    """A READY plant whose block plans two piles and holds a third still PLANNED."""
    set_clock(api, "2026-08-01T00:00:00Z")
    project = create_project(api, name="Gypsum Wells")
    area = accepted_area(api, project["id"])
    zone = create_yard_zone(api, project["id"], zone_code="Y1", pallet_capacity=100)
    accepted_module_delivery(api, project["id"], zone["id"])

    block = create_block(
        api,
        project["id"],
        area["id"],
        block_code="B1",
        dc_capacity_kw=130,
        planned_pile_count=2,
        planned_string_count=1,
    )
    first = create_pile(api, block["id"], row_index=1, position_index=1, design_embedment_mm=3000)
    second = create_pile(api, block["id"], row_index=1, position_index=2, design_embedment_mm=3000)
    third = create_pile(api, block["id"], row_index=1, position_index=3, design_embedment_mm=3000)
    record_drive_result(api, first["id"], actual_embedment_mm=3000, plumb_deviation_mm=4.0, blow_count=40, refusal=False)
    record_drive_result(api, second["id"], actual_embedment_mm=3050, plumb_deviation_mm=6.0, blow_count=45, refusal=False)

    declare_mechanical_completion(api, block["id"], modules_installed_qty=50, max_torque_tube_deviation_mm=18.0)
    circuit = create_circuit(api, block["id"], circuit_code="C1", modules_in_series=15)
    wire_circuit(api, circuit["id"], combiner_position="CB1-01")
    record_string_test(api, circuit["id"], insulation_resistance_mohm=55.0, measured_voc_v=705.00, ambient_c=40, polarity_ok=True)

    test = schedule_commissioning_test(
        api,
        project["id"],
        test_type="CAPACITY",
        correction_variant="AS_MEASURED",
        scheduled_at="2026-08-12T15:00:00Z",
    )
    assert_project_state(read_project(api, project["id"]), mc_readiness="READY", blocks_mc_ready_count=1)
    return {"project": project, "area": area, "block": block, "pile": third, "test": test}


def test_a_refused_drive_is_selected_by_the_relief_embedment_floor(api):
    """2600 mm falls under the 2700 mm relief floor, so the pile is REFUSED.

    PRD 3.4: "When `refusal` is reported true, the crew is entitled to relief: if
    `actual_embedment_mm` is strictly below the ninety-percent floor the pile
    becomes `REFUSED`; otherwise, if the plumb check passes the pile becomes
    `ACCEPTED`; otherwise it becomes `OUT_OF_TOLERANCE`."

    Design: Difficulty/transitive_cascade/pile_refusal_cascades_to_blocked_readiness_and_suspended_test
    """
    rows = _two_pile_plant(api)

    driven = record_drive_result(
        api, rows["pile"]["id"], actual_embedment_mm=2600, plumb_deviation_mm=3.0, blow_count=120, refusal=True
    )

    assert_pile_disposition(driven, "REFUSED")
    assert driven["refusal_flag"] is True


def test_the_refusal_forces_the_mechanical_dimension_to_hold(api):
    """The block's mechanical side is pushed to HOLD while its electrical side stands.

    PRD 3.4: "A `REFUSED` pile increments `piles_refused_count`, and because the
    block now contains at least one refused pile its `mechanical_status` is forced
    to `HOLD` from whichever of `PLANNED`, `PILES_COMPLETE` or `MECH_COMPLETE` it
    held; that is the second hop of the pile-refusal cascade."

    Design: Difficulty/transitive_cascade/pile_refusal_cascades_to_blocked_readiness_and_suspended_test
    """
    rows = _two_pile_plant(api)

    record_drive_result(
        api, rows["pile"]["id"], actual_embedment_mm=2600, plumb_deviation_mm=3.0, blow_count=120, refusal=True
    )

    assert_block_counters(
        read_block(api, rows["block"]["id"]),
        mechanical_status="HOLD",
        electrical_status="TESTED",
        mc_ready=False,
        piles_refused_count=1,
        piles_accepted_count=2,
    )


def test_readiness_collapses_and_suspends_the_test_but_no_claim_is_withdrawn(api):
    """With no claim outstanding the chain ends at the suspended test.

    PRD 3.4: "In the same pass, every commissioning test of the project sitting at
    `SCHEDULED` or `IN_PROGRESS` is driven to `SUSPENDED` with `suspend_reason`
    set to `MC_READINESS_LOST`."

    Design: Difficulty/transitive_cascade/pile_refusal_cascades_to_blocked_readiness_and_suspended_test
    """
    rows = _two_pile_plant(api)

    record_drive_result(
        api, rows["pile"]["id"], actual_embedment_mm=2600, plumb_deviation_mm=3.0, blow_count=120, refusal=True
    )

    project = read_project(api, rows["project"]["id"])
    assert_project_state(project, mc_readiness="BLOCKED", blocks_mc_ready_count=0, milestone_state="PRECONSTRUCTION")
    assert project["last_milestone_rejection_reason"] is None

    suspended = read_commissioning_test(api, rows["test"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspend_reason"] == "MC_READINESS_LOST"


def test_remediation_leaves_the_hold_but_does_not_restore_readiness(api):
    """A successful remediation returns the block to PILES_COMPLETE, not to ready.

    PRD 3.4: "A block on `HOLD` whose `piles_refused_count` returns to 0 leaves
    the hold, and where it lands depends on the pile arithmetic: if
    `piles_accepted_count` is at least `planned_pile_count` the mechanical
    dimension goes to `PILES_COMPLETE`, and if it is still short of the planned
    count the block returns to `PLANNED` instead."

    Design: Difficulty/transitive_cascade/pile_refusal_cascades_to_blocked_readiness_and_suspended_test
    """
    rows = _two_pile_plant(api)
    record_drive_result(
        api, rows["pile"]["id"], actual_embedment_mm=2600, plumb_deviation_mm=3.0, blow_count=120, refusal=True
    )

    record_remediation(api, rows["pile"]["id"], "PREDRILL", 2800, 8.0)

    assert_pile_disposition(read_pile(api, rows["pile"]["id"]), "ACCEPTED")
    assert_block_counters(
        read_block(api, rows["block"]["id"]),
        mechanical_status="PILES_COMPLETE",
        piles_refused_count=0,
        mc_ready=False,
    )
    assert_project_state(read_project(api, rows["project"]["id"]), mc_readiness="BLOCKED")
