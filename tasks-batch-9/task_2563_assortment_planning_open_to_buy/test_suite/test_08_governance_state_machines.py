"""Cyclic and multi-dimensional state machines.

Each test translates one instance of the difficulty rule ``non_linear_state_machine``.
"""
from test_helpers import (
    activate_item,
    adopt_item,
    approve_decision,
    approve_plan,
    close_cycle,
    close_item,
    commit_commitment,
    get_commitment,
    get_cycle,
    get_decision,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    cancel_commitment,
    get_success_data,
    open_reforecast_cycle,
    post_receipt,
    propose_commitment,
    propose_decision,
    propose_item,
    reject_decision,
    reject_plan,
    setup_in_season_plan,
    setup_plan_scenario,
    setup_single_month_approved_plan,
    ship_commitment,
    submit_plan,
    validate_success,
)


def test_revision_loop_unwinds_the_approval_and_consumes_no_reforecast_round():
    """DRAFT -> SUBMITTED -> DRAFT is free and resets the structural work.

    PRD: "Rejection unwinds the previous approval's structural work: every plan month of
    the plan whose `status` is `LOCKED_PLAN` reverts `LOCKED_PLAN → DRAFT` and has
    `otb_planned_cents`, `otb_open_cents`, `markdown_reserve_cents`,
    `provisional_sell_through_bps` and `reserve_rate_bps` all reset to 0, and every option
    plan of the plan whose `status` is `SLOTTED` reverts `SLOTTED → OPEN` with
    `option_slots_total`, `option_slots_open` and `target_units_per_option` all reset to
    null. The revision loop `SUBMITTED → DRAFT → SUBMITTED` may repeat without limit and
    never consumes a reforecast round."

    Design: Difficulty/non_linear_state_machine/category_plan_revision_and_reforecast_loop
    """
    scenario = setup_plan_scenario()
    plan_id = scenario["plan_id"]

    submit_plan(plan_id, submission_note="round 1")
    plan = get_plan(plan_id)
    assert plan["status"] == "SUBMITTED"
    assert plan["reforecast_round"] == 0

    reject_plan(plan_id, rejection_reason="markdown plan too thin")

    plan = get_plan(plan_id)
    assert plan["status"] == "DRAFT"
    assert plan["reforecast_round"] == 0

    month = get_month(scenario["m1"]["id"])
    assert month["status"] == "DRAFT"
    assert month["otb_planned_cents"] == 0
    assert month["otb_open_cents"] == 0
    assert month["markdown_reserve_cents"] == 0
    assert month["provisional_sell_through_bps"] == 0
    assert month["reserve_rate_bps"] == 0

    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["status"] == "OPEN"
    assert cell["option_slots_total"] is None
    assert cell["option_slots_open"] is None
    assert cell["target_units_per_option"] is None

    # The loop may be walked again from DRAFT, still without consuming a round.
    submit_plan(plan_id, submission_note="round 2")
    approve_plan(plan_id)
    plan = get_plan(plan_id)
    assert plan["status"] == "APPROVED"
    assert plan["reforecast_round"] == 0
    assert plan["receipt_budget_cents"] == 60_000_000
    assert get_month(scenario["m1"]["id"])["status"] == "LOCKED_PLAN"
    assert get_option_plan(scenario["option_plan"]["id"])["option_slots_total"] == 14


def test_governance_loop_re_enters_approved_through_the_same_edge():
    """APPROVED -> REFORECAST_OPEN -> SUBMITTED -> APPROVED costs exactly one round.

    PRD: "Either way the plan advances `APPROVED → REFORECAST_OPEN`, its
    `reforecast_round` rises by 1" and PRD: "the governance loop closes: `DRAFT →
    SUBMITTED → APPROVED → REFORECAST_OPEN → SUBMITTED → APPROVED`, with the plan
    re-entering `APPROVED` through the very same approval transition and cascade described
    in §3.4." A cycle "opened and then judged to need no correction whatsoever can also be
    closed directly from `OPEN`", and opening a round does not unwind the month locks.

    Design: Difficulty/non_linear_state_machine/category_plan_revision_and_reforecast_loop
    """
    scenario = setup_plan_scenario(approve=True)
    plan_id, month_id = scenario["plan_id"], scenario["m1"]["id"]

    plan = get_plan(plan_id)
    assert plan["status"] == "APPROVED"
    assert plan["receipt_budget_cents"] == 60_000_000
    assert get_month(month_id)["status"] == "LOCKED_PLAN"

    cycle = open_reforecast_cycle(plan_id,
                                 reason_note="director asked for a mid-season rebuild")
    plan = get_plan(plan_id)
    assert plan["status"] == "REFORECAST_OPEN"
    assert plan["reforecast_round"] == 1
    assert cycle["status"] == "OPEN"
    assert cycle["round_index"] == 1
    assert cycle["trigger_reason"] == "DIRECTOR_REQUEST"

    month = get_month(month_id)
    assert month["status"] == "LOCKED_PLAN"
    assert month["otb_planned_cents"] == 18_200_000

    close_cycle(cycle["id"])
    assert get_cycle(cycle["id"])["status"] == "CLOSED"

    submit_plan(plan_id, submission_note="reforecast round 1 rebuild")
    plan = get_plan(plan_id)
    assert plan["status"] == "SUBMITTED"
    assert plan["reforecast_round"] == 1

    approve_plan(plan_id, approval_note="re-approved")
    plan = get_plan(plan_id)
    assert plan["status"] == "APPROVED"
    assert plan["receipt_budget_cents"] == 60_000_000
    assert plan["reforecast_round"] == 1


def _cycle_with_in_season_item():
    """An OPEN director-requested cycle over one IN_SEASON carryover option."""
    scenario = setup_in_season_plan()
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"],
        sku_code="DRSS-HOLD-01", color_code="OLIVE", lifecycle_stage="CARRYOVER",
        unit_cost_cents=2500, retail_price_cents=6900,
        prior_season_sell_through_bps=7100,
    )
    adopt_item(item["id"])
    activate_item(item["id"])
    cycle = open_reforecast_cycle(
        scenario["plan_id"], reason_note="assess the month before committing dollars"
    )
    return scenario, item, cycle


def test_cycle_bubbles_to_decided_when_no_proposed_decision_remains():
    """An approved HOLD is enough to bubble the parent cycle, and it moves nothing.

    PRD: "As soon as an approval or a rejection leaves no decision of the cycle still
    `PROPOSED`, and provided the cycle holds at least one decision at all, the cycle
    bubbles `OPEN → DECIDED` and its version advances by 1 — the parent's state is derived
    from the aggregate state of its children." PRD: "A `HOLD` decision allocates nothing:
    `approved_units` is 0, no commitment is created and none is reduced, and the item's
    `status` is unchanged."

    Design: Difficulty/non_linear_state_machine/reforecast_cycle_decided_reopen_loop
    """
    scenario, item, cycle = _cycle_with_in_season_item()

    assert cycle["status"] == "OPEN"
    assert cycle["round_index"] == 1
    assert cycle["trigger_reason"] == "DIRECTOR_REQUEST"
    assert cycle["snapshot_sales_variance_bps"] == 0

    decision = propose_decision(
        cycle["id"], item["id"], action="HOLD", requested_units=0,
        rationale="hold one more week of reads",
    )
    assert decision["status"] == "PROPOSED"
    assert decision["proposed_by_user_id"] == "planner-1"
    assert get_cycle(cycle["id"])["status"] == "OPEN"

    approved = approve_decision(decision["id"], decision_note="hold confirmed")
    assert approved["status"] == "APPROVED"
    assert approved["approved_units"] == 0
    assert get_cycle(cycle["id"])["status"] == "DECIDED"

    assert get_item(item["id"])["status"] == "IN_SEASON"
    assert get_item(item["id"])["planned_units"] == 276
    month = get_month(scenario["m1"]["id"])
    assert month["otb_committed_cents"] == 0
    assert month["otb_open_cents"] == 18_200_000


def test_a_new_decision_reopens_a_decided_cycle_and_reject_bubbles_it_again():
    """DECIDED -> OPEN fires from a child create, with no endpoint on the cycle.

    PRD: "Proposing into a cycle that has already bubbled to `DECIDED` reopens it,
    advancing the cycle `DECIDED → OPEN` and advancing its version by 1; that reopening
    requires the parent plan to still be in `REFORECAST_OPEN`, and the `OPEN → DECIDED →
    OPEN` loop may repeat for as many decision rounds as one reforecast round needs." PRD:
    "A rejection sets `status` to `REJECTED` and `approved_units` to 0, changes no plan
    month and no item field at all". The cycle then closes from `DECIDED`, and PRD: "Once
    every cycle of the plan is `CLOSED` or `ABANDONED`, the planner may resubmit the plan"
    — closing does not itself re-approve it.

    Design: Difficulty/non_linear_state_machine/reforecast_cycle_decided_reopen_loop
    """
    scenario, item, cycle = _cycle_with_in_season_item()
    first = propose_decision(cycle["id"], item["id"], action="HOLD", requested_units=0,
                             rationale="hold one more week of reads")
    approve_decision(first["id"], decision_note="hold confirmed")
    decided = get_cycle(cycle["id"])
    assert decided["status"] == "DECIDED"

    second = propose_decision(cycle["id"], item["id"], action="HOLD", requested_units=0,
                              rationale="second read still inconclusive")
    reopened = get_cycle(cycle["id"])
    assert reopened["status"] == "OPEN"
    assert reopened["round_index"] == 1
    assert reopened["version"] > decided["version"]
    assert get_plan(scenario["plan_id"])["reforecast_round"] == 1

    rejected = reject_decision(second["id"], decision_note="no further hold needed")
    assert rejected["status"] == "REJECTED"
    assert rejected["approved_units"] == 0
    assert get_decision(second["id"])["status"] == "REJECTED"
    assert get_cycle(cycle["id"])["status"] == "DECIDED"

    close_cycle(cycle["id"])
    assert get_cycle(cycle["id"])["status"] == "CLOSED"
    assert get_plan(scenario["plan_id"])["status"] == "REFORECAST_OPEN"

    month = get_month(scenario["m1"]["id"])
    assert month["status"] == "IN_SEASON"
    assert month["otb_planned_cents"] == 18_200_000


def _proposed_commitment(units=400, unit_cost_cents=2500):
    """A single-month approved plan carrying one PROPOSED commitment."""
    scenario = setup_single_month_approved_plan()
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"],
        sku_code="DRSS-PAR-01", color_code="RED", lifecycle_stage="CARRYOVER",
        unit_cost_cents=unit_cost_cents, retail_price_cents=6900,
        prior_season_sell_through_bps=7100,
    )
    commitment = propose_commitment(
        scenario["m1"]["id"], item["id"], scenario["vendor"]["id"],
        units=units, unit_cost_cents=unit_cost_cents,
    )
    return scenario, item, commitment


def test_commit_and_ship_advance_the_two_dimensions_independently():
    """The financial and physical dimensions move one at a time on the same row.

    PRD: "Committing a proposal advances `PROPOSED → COMMITTED` on the financial dimension
    and leaves `fulfillment_status` untouched at `AWAITING_SHIP`." PRD: "A `VendorRep`
    whose `X-User-ID` equals the commitment's `vendor_id` marks an order shipped, advancing
    `AWAITING_SHIP → SHIPPED`; this requires the commitment's `commit_status` to be
    `COMMITTED`, and beyond that guard the financial dimension is neither read nor
    written." Shipping moves no money, so the month's figures are unchanged.

    Design: Difficulty/non_linear_state_machine/receipt_commitment_parallel_state_dimensions
    """
    scenario, _item, commitment = _proposed_commitment()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]

    assert commitment["commit_status"] == "PROPOSED"
    assert commitment["fulfillment_status"] == "AWAITING_SHIP"
    assert commitment["cost_cents"] == 1_000_000
    assert commitment["open_cost_cents"] == 1_000_000

    committed = commit_commitment(commitment["id"])
    assert committed["commit_status"] == "COMMITTED"
    assert committed["fulfillment_status"] == "AWAITING_SHIP"
    month = get_month(month_id)
    assert month["otb_committed_cents"] == 1_000_000
    assert month["otb_received_cents"] == 0
    assert month["otb_open_cents"] == 17_200_000

    shipped = ship_commitment(commitment["id"], vendor_id)
    assert shipped["fulfillment_status"] == "SHIPPED"
    assert shipped["commit_status"] == "COMMITTED"
    month = get_month(month_id)
    assert month["otb_committed_cents"] == 1_000_000
    assert month["otb_open_cents"] == 17_200_000


def test_the_completing_receipt_couples_both_dimensions_in_one_request():
    """A partial receipt moves only the physical dimension; the last one closes both.

    PRD: "When `received_units` plus the delta is still strictly below `units`, the delta is
    added to `received_units` and the dimension lands in `PARTIALLY_RECEIVED`". PRD: "When
    `received_units` plus the delta exactly equals `units`, the order is complete:
    `received_units` is set to `units`, `fulfillment_status` becomes `RECEIVED`, and this is
    the **first coupling point between the two dimensions** — `commit_status`
    simultaneously advances `COMMITTED → CLOSED`, with `open_cost_cents` zeroed ... while
    `otb_open_cents` is left unchanged, because the cost simply moved between two buckets
    that are both subtracted from the same planned figure."

    Design: Difficulty/non_linear_state_machine/receipt_commitment_parallel_state_dimensions
    """
    scenario, _item, commitment = _proposed_commitment()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]
    commit_commitment(commitment["id"])
    ship_commitment(commitment["id"], vendor_id)

    partial = post_receipt(commitment["id"], vendor_id, 150)
    assert partial["fulfillment_status"] == "PARTIALLY_RECEIVED"
    assert partial["commit_status"] == "COMMITTED"
    assert partial["received_units"] == 150
    assert partial["received_cost_cents"] == 375_000
    assert partial["open_cost_cents"] == 625_000
    month = get_month(month_id)
    assert month["otb_committed_cents"] == 625_000
    assert month["otb_received_cents"] == 375_000
    assert month["otb_open_cents"] == 17_200_000

    final = post_receipt(commitment["id"], vendor_id, 250)
    assert final["fulfillment_status"] == "RECEIVED"
    assert final["commit_status"] == "CLOSED"
    assert final["received_units"] == 400
    assert final["received_cost_cents"] == 1_000_000
    assert final["open_cost_cents"] == 0
    month = get_month(month_id)
    assert month["otb_committed_cents"] == 0
    assert month["otb_received_cents"] == 1_000_000
    assert month["otb_open_cents"] == 17_200_000


def _fork_scenario():
    """One IN_SEASON month, two IN_SEASON options, one 800-unit COMMITTED buy on B,
    and an OPEN cycle ready to fork."""
    scenario = setup_single_month_approved_plan(open_season_month_indexes=(1,))
    option_plan_id, vendor_id = scenario["option_plan"]["id"], scenario["vendor"]["id"]
    item_a = propose_item(option_plan_id, vendor_id, sku_code="DRSS-CHASE-A",
                          color_code="IVORY", lifecycle_stage="NEW",
                          unit_cost_cents=2500, retail_price_cents=6900,
                          prior_season_sell_through_bps=0)
    item_b = propose_item(option_plan_id, vendor_id, sku_code="DRSS-CANCEL-B",
                          color_code="NAVY", lifecycle_stage="CARRYOVER",
                          unit_cost_cents=2500, retail_price_cents=6900,
                          prior_season_sell_through_bps=7100)
    for item in (item_a, item_b):
        adopt_item(item["id"])
        activate_item(item["id"])
    commitment_b = propose_commitment(
        scenario["m1"]["id"], item_b["id"], vendor_id, units=800, unit_cost_cents=2500
    )
    commit_commitment(commitment_b["id"])
    cycle = open_reforecast_cycle(scenario["plan_id"],
                                 reason_note="chase the winner, cancel the dog")
    return scenario, item_a, item_b, commitment_b, cycle


def test_chase_branch_adds_units_and_generates_a_committed_receipt(api, buyer_headers):
    """The CHASE fork buys more and debits the month.

    PRD: "The units taken from the month are the smallest of the units still to place, the
    units the month can fund, and that headroom." M1 can fund floor(16_200_000 / 2500) ==
    6480 units and the vendor has 12000 - 800 == 11200 free, so all 1000 are placed. PRD:
    "the server creates one receipt commitment for that month ... `origin`
    `CHASE_DECISION`, `commit_status` `COMMITTED` and `fulfillment_status`
    `AWAITING_SHIP`" and "On an approved `CHASE` with `approved_units` above 0 the item
    advances `IN_SEASON → CHASED` and its `planned_units` rises by `approved_units`."

    Design: Difficulty/non_linear_state_machine/assortment_item_chase_cancel_fork_join
    """
    scenario, item_a, item_b, _commitment_b, cycle = _fork_scenario()
    month_id = scenario["m1"]["id"]

    assert get_item(item_a["id"])["sell_through_bps"] == 6325
    assert get_item(item_b["id"])["sell_through_bps"] == 7455
    cell = get_option_plan(scenario["option_plan"]["id"])
    assert (cell["option_slots_total"], cell["option_slots_assigned"],
            cell["option_slots_open"]) == (14, 2, 12)
    assert get_month(month_id)["otb_open_cents"] == 16_200_000

    decision_a = propose_decision(cycle["id"], item_a["id"], action="CHASE",
                                  requested_units=1000,
                                  rationale="sell-through running ahead of plan")
    decision_b = propose_decision(cycle["id"], item_b["id"], action="CANCEL",
                                  requested_units=200,
                                  rationale="carryover colour stalled")
    approved_a = approve_decision(decision_a["id"], decision_note="chase approved")

    assert approved_a["approved_units"] == 1000
    chased = get_item(item_a["id"])
    assert chased["status"] == "CHASED"
    assert chased["planned_units"] == 1276

    resp = api.list_receipt_commitments(
        buyer_headers, params={"assortment_item_id": item_a["id"], "limit": 50}
    )
    validate_success(resp)
    generated = get_success_data(resp)
    assert len(generated) == 1
    chase_commitment = generated[0]
    assert chase_commitment["origin"] == "CHASE_DECISION"
    assert chase_commitment["commit_status"] == "COMMITTED"
    assert chase_commitment["fulfillment_status"] == "AWAITING_SHIP"
    assert chase_commitment["units"] == 1000
    assert chase_commitment["unit_cost_cents"] == 2500
    assert chase_commitment["cost_cents"] == 2_500_000
    assert chase_commitment["ship_window_start"].startswith("2027-03-05T00:00:00")
    assert chase_commitment["ship_window_end"].startswith("2027-03-19T00:00:00")

    month = get_month(month_id)
    assert month["otb_committed_cents"] == 4_500_000
    assert month["otb_open_cents"] == 13_700_000
    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 7527
    assert plan["otb_posture"] == "OPEN"
    # decision_b is still PROPOSED, so the cycle has not bubbled.
    assert get_decision(decision_b["id"])["status"] == "PROPOSED"
    assert get_cycle(cycle["id"])["status"] == "OPEN"


def test_cancel_branch_releases_units_and_both_branches_join_on_close(
    api, buyer_headers
):
    """The CANCEL fork credits the same month, and CLOSED joins both branches.

    PRD: "from each row the system takes the smaller of the units still to remove and that
    row's open units, adds the taken amount to the row's `cancelled_units`" and "On an
    approved `CANCEL` with `approved_units` above 0 the item advances `IN_SEASON →
    CANCELLED_IN_SEASON` and its `planned_units` falls by `approved_units`." PRD: "Closing
    is accepted from any of four states — `ADOPTED`, `IN_SEASON`, `CHASED` or
    `CANCELLED_IN_SEASON` — and it is the single join point at which all of them converge
    on `CLOSED` ... The slot release is identical on every one of the four inbound paths."

    Design: Difficulty/non_linear_state_machine/assortment_item_chase_cancel_fork_join
    """
    scenario, item_a, item_b, commitment_b, cycle = _fork_scenario()
    month_id, plan_id = scenario["m1"]["id"], scenario["plan_id"]

    decision_a = propose_decision(cycle["id"], item_a["id"], action="CHASE",
                                  requested_units=1000,
                                  rationale="sell-through running ahead of plan")
    decision_b = propose_decision(cycle["id"], item_b["id"], action="CANCEL",
                                  requested_units=200,
                                  rationale="carryover colour stalled")
    approve_decision(decision_a["id"], decision_note="chase approved")
    approved_b = approve_decision(decision_b["id"], decision_note="cancel approved")

    assert approved_b["approved_units"] == 200
    cancelled_item = get_item(item_b["id"])
    assert cancelled_item["status"] == "CANCELLED_IN_SEASON"
    assert cancelled_item["planned_units"] == 76

    row_b = get_commitment(commitment_b["id"])
    assert row_b["cancelled_units"] == 200
    assert row_b["commit_status"] == "COMMITTED"
    assert row_b["open_cost_cents"] == 1_500_000

    month = get_month(month_id)
    assert month["otb_committed_cents"] == 4_000_000
    assert month["otb_open_cents"] == 14_200_000
    assert get_plan(plan_id)["open_ratio_bps"] == 7802
    assert get_cycle(cycle["id"])["status"] == "DECIDED"

    # Clear the financial loose ends so both options may close.
    resp = api.list_receipt_commitments(
        buyer_headers, params={"assortment_item_id": item_a["id"], "limit": 50}
    )
    validate_success(resp)
    chase_commitment = get_success_data(resp)[0]
    cancel_commitment(chase_commitment["id"],
                      cancel_reason="clearing the board before close")
    assert get_month(month_id)["otb_open_cents"] == 16_700_000
    assert get_plan(plan_id)["open_ratio_bps"] == 9176

    cancel_commitment(commitment_b["id"],
                      cancel_reason="clearing the board before close")
    row_b = get_commitment(commitment_b["id"])
    assert row_b["cancelled_units"] == 800
    assert row_b["commit_status"] == "CANCELLED"
    assert row_b["fulfillment_status"] == "VOID"
    month = get_month(month_id)
    assert month["otb_committed_cents"] == 0
    assert month["otb_open_cents"] == 18_200_000

    close_item(item_a["id"])
    close_item(item_b["id"])
    assert get_item(item_a["id"])["status"] == "CLOSED"
    assert get_item(item_b["id"])["status"] == "CLOSED"

    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["option_slots_total"] == 14
    assert cell["option_slots_assigned"] == 0
    assert cell["option_slots_open"] == 14
