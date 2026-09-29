"""Deep transitive cascades: approval's five links and cancellation's four.

Each test translates one instance of the difficulty rule ``transitive_cascade``.
"""
from test_helpers import (
    approve_plan,
    assert_otb_conservation,
    cancel_commitment,
    commit_commitment,
    get_commitment,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    get_size_curve_cells,
    propose_commitment,
    propose_item,
    setup_canonical_approved_plan,
    setup_plan_scenario,
    setup_submitted_plan,
)


def test_approval_links_one_to_three_pin_the_budget_lock_months_and_set_posture():
    """The budget must exist before the months can lock, and before posture can derive.

    PRD: "`receipt_budget_cents` starts as null and stays null until the plan's first
    approval computes it." PRD: "**Link 2** is caused by link 1 pinning the budget: every
    plan month of the plan whose `status` is `DRAFT` advances `DRAFT → LOCKED_PLAN`".
    PRD: "**Link 3** is caused by link 2 creating the plan's first locked months: the
    plan's **posture** is recomputed and `open_ratio_bps` and `otb_posture` are written,
    advancing the plan's version by 1 a second time — so a single approval request raises
    the plan's `version` by 2 in total."

    Design: Difficulty/transitive_cascade/approve_cascade_budget_to_size_allocation
    """
    scenario = setup_submitted_plan()
    plan_id = scenario["plan_id"]
    before = get_plan(plan_id)
    assert before["status"] == "SUBMITTED"
    assert before["receipt_budget_cents"] is None
    assert get_month(scenario["m1"]["id"])["status"] == "DRAFT"
    assert get_month(scenario["m1"]["id"])["otb_planned_cents"] == 0
    cell_before = get_option_plan(scenario["option_plan"]["id"])
    assert cell_before["status"] == "OPEN"
    assert cell_before["option_slots_total"] is None
    assert cell_before["target_units_per_option"] is None

    approved = approve_plan(plan_id, approval_note="approved for buy")

    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "director-1"
    assert approved["receipt_budget_cents"] == 60_000_000
    assert approved["version"] == before["version"] + 2

    m1 = get_month(scenario["m1"]["id"])
    assert m1["status"] == "LOCKED_PLAN"
    assert m1["provisional_sell_through_bps"] == 6750
    assert m1["reserve_rate_bps"] == 350
    assert m1["markdown_reserve_cents"] == 700_000
    assert m1["otb_planned_cents"] == 18_200_000
    assert m1["otb_committed_cents"] == 0
    assert m1["otb_received_cents"] == 0
    assert m1["otb_open_cents"] == 18_200_000

    m2 = get_month(scenario["m2"]["id"])
    assert m2["status"] == "LOCKED_PLAN"
    assert m2["provisional_sell_through_bps"] == 7364
    assert m2["reserve_rate_bps"] == 350
    assert m2["markdown_reserve_cents"] == 770_000
    assert m2["otb_planned_cents"] == 21_970_000
    assert m2["otb_open_cents"] == 21_970_000

    assert approved["open_ratio_bps"] == 10000
    assert approved["otb_posture"] == "OPEN"


def test_approval_links_four_and_five_slot_the_cell_and_size_the_allocation():
    """Slotting depends on link 3's posture and link 1's budget; sizing depends on link 4.

    PRD: "**Link 4** is caused by link 3 leaving the posture at something other than
    `FROZEN`: every option plan of the plan whose `status` is `OPEN` advances `OPEN →
    SLOTTED`, provided that cell has at least one size-curve row." The tier share is
    60_000_000 x 3500 / 10000 == 21_000_000, the cluster share 21_000_000 x 11500 / 10000
    == 24_150_000, the per-option cost 6 x 40 x 2400 == 576_000 and 41 options are
    affordable, so "`option_slots_total` is then the larger of 2 and the smaller of the
    cell's `breadth_target` and that affordable count" == 14. PRD: "**Link 5** is caused by
    link 4 slotting the cells: for every cell slotted in link 4, the cluster-and-size
    allocation of §3.3 re-runs, writing `target_units_per_option` on the option plan and
    `raw_units_x10000` plus `allocated_units` on each of its size-curve rows."

    Design: Difficulty/transitive_cascade/approve_cascade_budget_to_size_allocation
    """
    scenario = setup_canonical_approved_plan()

    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["status"] == "SLOTTED"
    assert cell["option_slots_total"] == 14
    assert cell["option_slots_assigned"] == 0
    assert cell["option_slots_open"] == 14
    assert cell["target_units_per_option"] == 276

    rows = {row["size_label"]: row for row in get_size_curve_cells(cell["id"])}
    assert {label: row["raw_units_x10000"] for label, row in rows.items()} == {
        "XS": 220_800, "S": 607_200, "M": 938_400, "L": 717_600, "XL": 276_000,
    }
    assert {label: row["allocated_units"] for label, row in rows.items()} == {
        "XS": 21, "S": 61, "M": 94, "L": 72, "XL": 28,
    }
    assert sum(row["allocated_units"] for row in rows.values()) == 276
    assert sum(row["allocated_units"] for row in rows.values()) != 277


def _frozen_plan_with_two_commitments():
    """Two COMMITTED buys drain both months until the plan freezes and defers its
    proposals."""
    scenario = setup_plan_scenario(approve=True)
    option_plan_id, vendor_id = scenario["option_plan"]["id"], scenario["vendor"]["id"]
    item_x = propose_item(option_plan_id, vendor_id, sku_code="DRSS-CARRY-X",
                          color_code="BLACK", lifecycle_stage="CARRYOVER",
                          unit_cost_cents=2600, retail_price_cents=6900,
                          prior_season_sell_through_bps=7100)
    item_c = propose_item(option_plan_id, vendor_id, sku_code="DRSS-CORE-C",
                          color_code="WHITE", lifecycle_stage="CORE",
                          unit_cost_cents=2500, retail_price_cents=6500,
                          prior_season_sell_through_bps=6000)
    item_n = propose_item(option_plan_id, vendor_id, sku_code="DRSS-NEW-N",
                          color_code="CORAL", lifecycle_stage="NEW",
                          unit_cost_cents=2500, retail_price_cents=7900,
                          prior_season_sell_through_bps=0)
    rc1 = propose_commitment(scenario["m1"]["id"], item_x["id"], vendor_id,
                             units=7000, unit_cost_cents=2600)
    commit_commitment(rc1["id"])
    rc2 = propose_commitment(scenario["m2"]["id"], item_x["id"], vendor_id,
                             units=8000, unit_cost_cents=2500,
                             ship_window_start="2027-04-02T00:00:00Z",
                             ship_window_end="2027-04-16T00:00:00Z")
    commit_commitment(rc2["id"])
    return scenario, (item_x, item_c, item_n), rc1, rc2


def test_cancel_cascade_releases_the_month_and_conditionally_restores_deferrals():
    """Cancelling out of FROZEN restores carryover and core options but not new ones.

    PRD: "Link 2, caused by link 1 zeroing the open cost, drops the month's
    `otb_committed_cents` by the released amount and raises the month's `otb_open_cents` by
    that same amount through a full recomputation of the month ... Link 3, caused by link 2
    changing the open balance, recomputes the plan's `open_ratio_bps` and `otb_posture` ...
    Link 4, caused by link 3 moving the posture out of `FROZEN`, restores deferred options
    — but **conditionally**: every assortment item under that plan whose `status` is
    `DEFERRED` and whose `lifecycle_stage` is `CARRYOVER` or `CORE` advances `DEFERRED →
    PROPOSED`, while items whose stage is `NEW` or `EXIT` remain `DEFERRED`".

    Design: Difficulty/transitive_cascade/cancel_cascade_release_to_deferred_restore
    """
    scenario, (item_x, item_c, item_n), rc1, rc2 = _frozen_plan_with_two_commitments()
    m1_id, m2_id, plan_id = scenario["m1"]["id"], scenario["m2"]["id"], scenario["plan_id"]

    assert get_commitment(rc1["id"])["commit_status"] == "COMMITTED"
    assert get_commitment(rc1["id"])["cost_cents"] == 18_200_000
    assert get_commitment(rc2["id"])["cost_cents"] == 20_000_000
    assert get_month(m1_id)["otb_open_cents"] == 0
    assert get_month(m2_id)["otb_open_cents"] == 1_970_000
    frozen = get_plan(plan_id)
    assert frozen["open_ratio_bps"] == 490
    assert frozen["otb_posture"] == "FROZEN"
    for item in (item_x, item_c, item_n):
        assert get_item(item["id"])["status"] == "DEFERRED"

    cancel_commitment(rc2["id"], cancel_reason="April flow pushed to fall")

    row = get_commitment(rc2["id"])
    assert row["commit_status"] == "CANCELLED"
    assert row["cancelled_units"] == 8000
    assert row["open_cost_cents"] == 0
    assert row["fulfillment_status"] == "VOID"

    m2 = get_month(m2_id)
    assert m2["otb_committed_cents"] == 0
    assert m2["otb_open_cents"] == 21_970_000
    assert m2["otb_planned_cents"] == 21_970_000
    assert m2["otb_received_cents"] == 0
    assert_otb_conservation(m2)

    plan = get_plan(plan_id)
    assert plan["open_ratio_bps"] == 5469
    assert plan["otb_posture"] == "OPEN"

    assert get_item(item_x["id"])["status"] == "PROPOSED"
    assert get_item(item_c["id"])["status"] == "PROPOSED"
    assert get_item(item_n["id"])["status"] == "DEFERRED"


def test_second_cancel_runs_links_one_to_three_but_not_the_conditional_fourth():
    """With the posture already OPEN the fourth link does not fire at all.

    PRD names link 4 as "caused by link 3 moving the posture out of `FROZEN`" — a cancel
    that does not cross that boundary restores nothing, and "items whose stage is `NEW` or
    `EXIT` remain `DEFERRED` and must be re-proposed as fresh rows if the merchant still
    wants them." PRD: "after link 2 the conservation identity of §2.11 holds exactly on that
    month."

    Design: Difficulty/transitive_cascade/cancel_cascade_release_to_deferred_restore
    """
    scenario, (item_x, item_c, item_n), rc1, rc2 = _frozen_plan_with_two_commitments()
    m1_id, m2_id, plan_id = scenario["m1"]["id"], scenario["m2"]["id"], scenario["plan_id"]
    cancel_commitment(rc2["id"], cancel_reason="April flow pushed to fall")
    assert get_plan(plan_id)["otb_posture"] == "OPEN"

    cancel_commitment(rc1["id"], cancel_reason="March flow pushed too")

    assert get_commitment(rc1["id"])["commit_status"] == "CANCELLED"
    m1 = get_month(m1_id)
    assert m1["otb_committed_cents"] == 0
    assert m1["otb_open_cents"] == 18_200_000
    assert_otb_conservation(m1)
    assert_otb_conservation(get_month(m2_id))

    plan = get_plan(plan_id)
    assert plan["open_ratio_bps"] == 10000
    assert plan["otb_posture"] == "OPEN"

    assert get_item(item_n["id"])["status"] == "DEFERRED"
    assert get_item(item_x["id"])["status"] == "PROPOSED"
    assert get_item(item_c["id"])["status"] == "PROPOSED"
