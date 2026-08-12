"""Queue A (depth) — contingency draw fee tiers and the conserved funding
envelope across a draw/return change-order pair.

Setup shape: project total 10000000c, unallocated contingency 1000000c,
FURNITURE budget line 9000000c, and a committed PO line of 40 x 200000c =
8000000c so utilization math is exact.
"""
from test_helpers import (
    api_client, validate_success,
    setup_change_order_scenario, apply_change_order_now,
    current_project_version, get_budget_line, get_project,
    assert_funding_envelope_conserved,
    make_owner_rep_headers, TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
OWNER_1 = make_owner_rep_headers("owner-1")


def _fee_tier_scenario():
    return setup_change_order_scenario(
        total_budget_cents=10_000_000,
        unallocated_contingency_cents=1_000_000,
        budgeted_cents=9_000_000,
        committed_line=(40, 200000),
        deltas=(("Owner adds king rooms", 500000),),
    )


def test_fee_tier_uses_prefee_utilization(api):
    """PRD §3.9: "Second, utilization is measured **pre-fee**: the project's
    `committed_cents` plus `actual_spend_cents` plus `POS`, divided by
    `total_budget_cents`. Third, the rate is 5 percent when utilization is at most
    0.80, 8 percent when utilization is above 0.80 and at most 0.95, and 12 percent
    above 0.95. Fourth, `fee_cents` is the rate multiplied by `POS`, rounded
    half-up to whole cents."
    committed 8000000 + actual 0 + POS 500000 over total 10000000 is u = 0.85,
    tier 8 percent, fee = 40000c; a post-fee reading is a contract violation.

    Design: Difficulty/combinatorial_formula/contingency_fee_prefee_utilization_tier
    """
    scenario = _fee_tier_scenario()
    change_order = scenario["change_orders"][0]

    applied = apply_change_order_now(
        change_order["id"], scenario["project_version"], OWNER_1
    )
    assert applied["status"] == "APPLIED"
    assert applied["fee_cents"] == 40000, (
        f"pre-fee utilization 0.85 selects the 8 percent tier; fee must be "
        f"40000, got {applied['fee_cents']}"
    )
    project = get_project(scenario["project"]["id"])
    assert project["sunk_fees_cents"] == 40000


def test_apply_moves_contingency_and_budget_by_pinned_amounts(api):
    """PRD §3.9: "An applied order mutates the envelope: each adjusted line's
    `budgeted_cents` shifts by its `delta_cents`; the project's
    `unallocated_contingency_cents` moves by `NEG` minus `POS` minus `fee_cents`;
    `sunk_fees_cents` grows by `fee_cents` and is never returned to contingency;
    the computed fee is stored on the order's `fee_cents`."
    After the +500000c draw at fee 40000c: budgeted 9500000c, unallocated
    1000000 - 500000 - 40000 = 460000c, sunk fees 40000c.

    Design: Difficulty/combinatorial_formula/contingency_fee_prefee_utilization_tier
    """
    scenario = _fee_tier_scenario()
    change_order = scenario["change_orders"][0]

    apply_change_order_now(change_order["id"], scenario["project_version"], OWNER_1)

    project = get_project(scenario["project"]["id"])
    budget_line = get_budget_line(scenario["budget_line"]["id"])
    assert budget_line["budgeted_cents"] == 9500000
    assert project["unallocated_contingency_cents"] == 460000
    assert project["sunk_fees_cents"] == 40000


# ── rule: compensating_invariant ───────────────────────────

def _draw_and_return_scenario():
    return setup_change_order_scenario(
        total_budget_cents=10_000_000,
        unallocated_contingency_cents=1_000_000,
        budgeted_cents=9_000_000,
        committed_line=(40, 200000),
        deltas=(("CO-A draw", 500000), ("CO-B return", -500000)),
    )


def _read_envelope(project_id, budget_line_id):
    project = get_project(project_id)
    budget_line = get_budget_line(budget_line_id)
    envelope = (
        budget_line["budgeted_cents"]
        + project["unallocated_contingency_cents"]
        + project["sunk_fees_cents"]
    )
    return project, budget_line, envelope


def test_funding_envelope_conserved_across_draw(api):
    """PRD §3.9: "An applied order mutates the envelope: each adjusted line's
    `budgeted_cents` shifts by its `delta_cents`; the project's
    `unallocated_contingency_cents` moves by `NEG` minus `POS` minus `fee_cents`;
    `sunk_fees_cents` grows by `fee_cents` and is never returned to contingency;
    the computed fee is stored on the order's `fee_cents`."
    The +500000c draw at fee 40000c leaves E = budgeted 9500000 + unallocated
    460000 + sunk 40000 = 10000000c — the envelope is unchanged.

    Design: Difficulty/compensating_invariant/funding_envelope_conserved_across_draw_and_return
    """
    scenario = _draw_and_return_scenario()
    project_id = scenario["project"]["id"]
    budget_line_id = scenario["budget_line"]["id"]
    co_a, _co_b = scenario["change_orders"]

    applied = apply_change_order_now(co_a["id"], scenario["project_version"], OWNER_1)
    assert applied["status"] == "APPLIED"
    assert applied["fee_cents"] == 40000

    project, budget_line, envelope = _read_envelope(project_id, budget_line_id)
    assert budget_line["budgeted_cents"] == 9500000
    assert project["unallocated_contingency_cents"] == 460000
    assert project["sunk_fees_cents"] == 40000
    assert envelope == 10_000_000
    assert_funding_envelope_conserved(project, [budget_line])


def test_funding_envelope_conserved_after_compensating_return(api):
    """PRD §3.9: "First, `POS` is the sum of the positive deltas and `NEG` the sum
    of the absolute values of the negative deltas across the adjustments."
    PRD §3.9: "An applied order mutates the envelope: each adjusted line's
    `budgeted_cents` shifts by its `delta_cents`; the project's
    `unallocated_contingency_cents` moves by `NEG` minus `POS` minus `fee_cents`;
    `sunk_fees_cents` grows by `fee_cents` and is never returned to contingency;
    the computed fee is stored on the order's `fee_cents`."
    The -500000c return has POS == 0 so fee == 0: budgeted restores to 9000000c,
    unallocated becomes 460000 + 500000 = 960000c, sunk stays 40000c, and
    E = 9000000 + 960000 + 40000 = 10000000c — identical before and after the
    draw/return pair.

    Design: Difficulty/compensating_invariant/funding_envelope_conserved_across_draw_and_return
    """
    scenario = _draw_and_return_scenario()
    project_id = scenario["project"]["id"]
    budget_line_id = scenario["budget_line"]["id"]
    co_a, co_b = scenario["change_orders"]

    apply_change_order_now(co_a["id"], scenario["project_version"], OWNER_1)
    applied_b = apply_change_order_now(
        co_b["id"], current_project_version(project_id), OWNER_1
    )
    assert applied_b["status"] == "APPLIED"
    assert applied_b["fee_cents"] == 0, (
        "a pure return has POS == 0, so the draw fee must be 0"
    )

    project, budget_line, envelope = _read_envelope(project_id, budget_line_id)
    assert budget_line["budgeted_cents"] == 9000000
    assert project["unallocated_contingency_cents"] == 960000
    assert project["sunk_fees_cents"] == 40000
    assert envelope == 10_000_000
    assert_funding_envelope_conserved(project, [budget_line])

    co_a_after = validate_success(api_client.get_change_order(co_a["id"], PA))
    co_b_after = validate_success(api_client.get_change_order(co_b["id"], PA))
    assert co_a_after["status"] == "APPLIED"
    assert co_a_after["fee_cents"] == 40000
    assert co_b_after["status"] == "APPLIED"
    assert co_b_after["fee_cents"] == 0
