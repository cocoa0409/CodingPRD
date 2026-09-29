"""State axes that genuinely cycle, and cycles that are bounded by a threshold.

Sample custody loops between the rack and the floor without limit; the retouch
rework loop is traversable exactly twice before it forks to a terminal state.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN, COORDINATOR, PRODUCER, QC_REVIEWER


def _matched_sample_on_the_rack(api):
    """Style TOP1001 with its only sample received, matched and moved to the rack."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    style = fx.create_style(api, vendor["id"], profile["id"], style_number="TOP1001")
    sample = fx.create_sample(api, vendor["id"], declared_style_number="TOP1001")
    fx.receive_sample(api, sample["id"])
    fx.match_sample(api, sample["id"], style["id"])
    fx.custody_move(api, sample["id"], "IN_STUDIO")
    return {"vendor": vendor, "style": style, "sample": sample}


def _loop_the_rack(api, sample_id):
    """Walk the box to the floor, back to the rack, out again, then into the queue."""
    responses = []
    for target in ("ON_SET", "IN_STUDIO", "ON_SET", "RETURN_PENDING"):
        responses.append(
            api.custody_move_sample(
                sample_id, f.custody_move_payload(target), COORDINATOR
            )
        )
    return responses


def test_custody_walks_the_rack_and_the_floor_as_a_genuine_cycle(api):
    """Four consecutive moves are all accepted and end in the return queue.

    PRD: "`ON_SET → IN_STUDIO` walks it back to the rack and carries no match requirement, which makes the custody axis cyclic between the rack and the floor."

    Design: Difficulty/non_linear_state_machine/sample_custody_loops_rack_to_set_and_back_without_touching_match_axis
    """
    world = _matched_sample_on_the_rack(api)

    responses = _loop_the_rack(api, world["sample"]["id"])

    for response in responses:
        validate_success(response)
    final = validate_success(responses[-1])
    assert final["custody_state"] == "RETURN_PENDING"


def test_the_match_axis_is_untouched_by_the_custody_loop(api):
    """Looping custody never disturbs the answer to "what is this box?".

    PRD: "Neither axis waits for the other except where a rule explicitly names the other, so a box can sit `RECEIVED` while still `UNMATCHED`, and it can be reconciled while parked on the rack."

    Design: Difficulty/non_linear_state_machine/sample_custody_loops_rack_to_set_and_back_without_touching_match_axis
    """
    world = _matched_sample_on_the_rack(api)

    _loop_the_rack(api, world["sample"]["id"])

    sample = validate_success(api.get_sample(world["sample"]["id"], COORDINATOR))
    assert sample["match_state"] == "MATCHED"
    assert sample["matched_style_id"] == world["style"]["id"]


def test_looping_custody_leaves_the_vendor_ledger_and_the_style_alone(api):
    """Every state in the loop is an outstanding state, so no counter moves.

    PRD: "A vendor's `outstanding_sample_count` is the number of that vendor's samples whose `custody_state` is `RECEIVED`, `IN_STUDIO`, `ON_SET` or `RETURN_PENDING`."

    Design: Difficulty/non_linear_state_machine/sample_custody_loops_rack_to_set_and_back_without_touching_match_axis
    """
    world = _matched_sample_on_the_rack(api)

    _loop_the_rack(api, world["sample"]["id"])

    vendor = validate_success(api.get_vendor(world["vendor"]["id"], ADMIN))
    style = validate_success(api.get_style(world["style"]["id"], PRODUCER))
    assert vendor["outstanding_sample_count"] == 1
    assert vendor["late_return_count"] == 0
    assert style["content_state"] == "SAMPLE_READY"


def _task_submitted_after_two_rework_loops(api):
    """One captured item of a two-item style, its task rejected twice and resubmitted."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT", "BACK"]})
    fx.build_style_on_the_rack(api, world, style_kw={"priority_tier": "B"})
    fx.build_planned_session(
        api,
        world,
        item_specs=[
            {"asset_kind": "ON_MODEL", "angle_code": "FRONT"},
            {"asset_kind": "ON_MODEL", "angle_code": "BACK"},
        ],
    )
    fx.build_shooting_session(api, world)
    fx.build_ingested_asset(api, world, item_index=0)
    fx.build_queued_task(api, world)
    task = fx.claim_next(api, world.retoucher_id)
    world.tasks = [task]
    for _ in range(2):
        fx.submit_task(api, task["id"], world.retoucher_id)
        fx.qc_reject(api, task["id"])
    fx.submit_task(api, task["id"], world.retoucher_id)
    return world


def test_the_third_rejection_forks_to_abandoned_instead_of_looping_again(api):
    """Two loops are the whole allowance; the third REJECT gives up on the file.

    PRD: "Once `rework_count` has already reached two, the studio gives up: the task moves `SUBMITTED → ABANDONED`, which is terminal, the asset moves `QC_PENDING → REJECTED`, which is likewise terminal, and the provider's `assigned_asset_count` falls by one."

    Design: Difficulty/non_linear_state_machine/retouch_rework_cycle_bounded_by_max_rework_then_forks_to_abandoned
    """
    world = _task_submitted_after_two_rework_loops(api)

    task = validate_success(
        api.qc_decision(world.task_id, f.qc_decision_payload("REJECT"), QC_REVIEWER)
    )

    assert task["task_state"] == "ABANDONED"
    assert task["rework_count"] == 2


def test_abandoning_the_task_rejects_the_asset_and_frees_the_provider(api):
    """The terminal fork settles the file and releases the retouch house's load.

    PRD: "While the task's `rework_count` is below two, rejection recycles the work: the task moves `SUBMITTED → REWORK`, `rework_count` rises by one, `rework_started_at` is stamped from the logical clock, and the asset moves `QC_PENDING → IN_RETOUCH` for the same retoucher to fix."

    Design: Difficulty/non_linear_state_machine/retouch_rework_cycle_bounded_by_max_rework_then_forks_to_abandoned
    """
    world = _task_submitted_after_two_rework_loops(api)

    validate_success(
        api.qc_decision(world.task_id, f.qc_decision_payload("REJECT"), QC_REVIEWER)
    )

    assert world.read_asset()["asset_state"] == "REJECTED"
    assert world.read_provider()["assigned_asset_count"] == 0


def test_the_final_rejection_puts_the_shot_back_on_the_floors_list(api):
    """Losing the last live file reverts the item and leaves the style scheduled.

    PRD: "The rejection also propagates downward — the shot-list item's `live_asset_count` falls by one and, if that leaves it at 0, the item reverts `CAPTURED → ASSIGNED` and the style reverts `SHOT → SCHEDULED`, putting the shot back on the floor's to-do list."

    Design: Difficulty/non_linear_state_machine/retouch_rework_cycle_bounded_by_max_rework_then_forks_to_abandoned
    """
    world = _task_submitted_after_two_rework_loops(api)

    validate_success(
        api.qc_decision(world.task_id, f.qc_decision_payload("REJECT"), QC_REVIEWER)
    )

    item = world.read_item(0)
    assert item["item_state"] == "ASSIGNED"
    assert item["live_asset_count"] == 0
    assert world.read_style()["content_state"] == "SCHEDULED"
