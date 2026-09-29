"""Transitions refused because of a *different* row's state, then allowed once it moves.

Each test translates one instance of the difficulty rule
``cross_entity_state_dependency``.
"""
from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    BUYER_HEADERS,
    PLANNER_HEADERS,
    approve_plan,
    close_cycle,
    commit_commitment,
    get_commitment,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    get_success_data,
    open_reforecast_cycle,
    propose_commitment,
    propose_item,
    setup_canonical_approved_plan,
    setup_draft_plan,
    setup_single_month_approved_plan,
    set_vendor_status,
    submit_plan,
    validate_error,
    validate_success,
)


def _core_option_on_a_draft_plan():
    scenario = setup_draft_plan()
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-CORE-C1", color_code="WHITE",
                        lifecycle_stage="CORE", unit_cost_cents=2500,
                        retail_price_cents=6500, prior_season_sell_through_bps=6000)
    return scenario, item


def test_adopt_is_refused_while_the_option_plan_is_still_open(api):
    """The item is in a state adopt is declared for; the cell it points at is not.

    PRD: adoption "advances the item `PROPOSED -> ADOPTED` and requires that the cell holding
    the slot is `SLOTTED` (otherwise `ERR_OPTION_PLAN_NOT_SLOTTED`)". Nothing about the item
    explains the refusal -- it is `PROPOSED`, exactly the state the transition starts from --
    so `ERR_INVALID_STATE` would be the wrong answer, and the item cannot slot its own cell.

    Design: Difficulty/cross_entity_state_dependency/item_adopt_requires_slotted_option_plan
    """
    scenario, item = _core_option_on_a_draft_plan()
    assert item["status"] == "PROPOSED"
    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["status"] == "OPEN"
    assert cell["option_slots_total"] is None

    resp = api.adopt_assortment_item(item["id"], {}, BUYER_HEADERS)

    validate_error(resp, ApiErrorId.ERR_OPTION_PLAN_NOT_SLOTTED, expected_status=409)
    after = get_item(item["id"])
    assert after["status"] == "PROPOSED"
    assert after["planned_units"] is None
    assert after["sell_through_bps"] is None
    assert after["sell_through_basis"] is None
    # PRD: a newly proposed item carries "`effective_overlay_multiplier_bps` at 10000".
    assert after["effective_overlay_multiplier_bps"] == 10000
    assert after["version"] == item["version"]


def test_approving_a_third_row_slots_the_cell_and_the_identical_adopt_succeeds(api):
    """Approval of the plan slots the cell, and only then does the item's own call go through.

    PRD: cascade B promotes "every `OPEN` option plan of that plan to `SLOTTED` with its slot
    counts written". PRD then pins what adoption inherits: "the item's `planned_units` is set to
    the cell's `target_units_per_option`" and, for a `CORE` stage, the carryover branch applies
    -- "the item's own `prior_season_sell_through_bps` multiplied by the cluster's
    `demographic_index_bps`, divided by ten thousand" gives 6000 * 10500 / 10000 == 6300, with
    the tier benchmark and sales index ignored. The slot counters "move as a conserved pair".

    Design: Difficulty/cross_entity_state_dependency/item_adopt_requires_slotted_option_plan
    """
    scenario, item = _core_option_on_a_draft_plan()
    submit_plan(scenario["plan_id"])
    approve_plan(scenario["plan_id"])

    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["status"] == "SLOTTED"
    assert cell["option_slots_total"] == 14
    assert cell["option_slots_assigned"] == 0
    assert cell["option_slots_open"] == 14
    assert cell["target_units_per_option"] == 276

    resp = api.adopt_assortment_item(item["id"], {}, BUYER_HEADERS)
    validate_success(resp, expected_status=200)

    adopted = get_item(item["id"])
    assert adopted["status"] == "ADOPTED"
    assert adopted["planned_units"] == 276
    assert adopted["effective_overlay_multiplier_bps"] == 10000
    assert adopted["sell_through_basis"] == "CARRYOVER_BASIS"
    assert adopted["sell_through_bps"] == 6300

    after_cell = get_option_plan(cell["id"])
    assert after_cell["option_slots_total"] == 14
    assert after_cell["option_slots_assigned"] == 1
    assert after_cell["option_slots_open"] == 13
    assert after_cell["version"] == cell["version"] + 1


def _proposed_commitment_on_an_authorized_vendor():
    scenario = setup_canonical_approved_plan()
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-CARRY-X", color_code="BLACK",
                        lifecycle_stage="CARRYOVER", unit_cost_cents=2500,
                        retail_price_cents=6900, prior_season_sell_through_bps=7100)
    commitment = propose_commitment(scenario["m1"]["id"], item["id"],
                                    scenario["vendor"]["id"], units=400,
                                    unit_cost_cents=2500)
    assert commitment["commit_status"] == "PROPOSED"
    assert commitment["cost_cents"] == 1_000_000
    return scenario, commitment


def _authorizations_of(api, vendor_id):
    return get_success_data(
        api.list_vendor_authorizations(ADMIN_HEADERS,
                                       params={"vendor_id": vendor_id, "limit": 20}))


def test_commit_is_refused_while_the_vendor_it_names_is_suspended(api):
    """Suspending the supplier makes an untouched proposal illegal to commit.

    PRD: "An `AUTHORIZED` vendor may be moved to `SUSPENDED`, which additionally revokes every
    one of that vendor's authorizations" and "a commit attempted against a `PENDING` or
    `SUSPENDED` vendor is rejected with `ERR_VENDOR_NOT_AUTHORIZED`". Two rules are violated at
    once, and per PRD the ladder is walked in ascending priority order, so priority 13's
    `ERR_VENDOR_NOT_AUTHORIZED` (409) must win over priority 19's
    `ERR_VENDOR_NOT_AUTHORIZED_FOR_CATEGORY` (422) that the revoked authorization also trips.

    Design: Difficulty/cross_entity_state_dependency/commitment_commit_requires_authorized_vendor
    """
    scenario, commitment = _proposed_commitment_on_an_authorized_vendor()
    vendor_id, month_id = scenario["vendor"]["id"], scenario["m1"]["id"]

    suspended = set_vendor_status(vendor_id, "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"
    assert [row["status"] for row in _authorizations_of(api, vendor_id)] == ["REVOKED"]
    assert get_commitment(commitment["id"])["commit_status"] == "PROPOSED"

    resp = api.commit_receipt_commitment(commitment["id"], {}, BUYER_HEADERS)

    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_AUTHORIZED, expected_status=409)
    assert get_commitment(commitment["id"])["commit_status"] == "PROPOSED"
    month = get_month(month_id)
    assert month["otb_committed_cents"] == 0
    assert month["otb_open_cents"] == 18_200_000
    assert get_plan(scenario["plan_id"])["open_ratio_bps"] == 10000


def test_reinstating_the_vendor_restores_the_authorization_and_the_same_commit_lands(api):
    """Reinstatement is the exact mirror of suspension, and the byte-identical commit succeeds.

    PRD: "A `SUSPENDED` vendor may be reinstated to `AUTHORIZED`, and reinstatement is the exact
    mirror of suspension -- every vendor authorization of that vendor whose `status` is
    `REVOKED` is restored to `ACTIVE`". PRD then pins the commit's own effects: the month's
    "`otb_committed_cents` and `otb_open_cents` are recomputed" and the plan's "`open_ratio_bps`
    and `otb_posture` are recomputed", giving 10000 * (17,200,000 + 21,970,000) / 40,170,000
    == 9751.

    Design: Difficulty/cross_entity_state_dependency/commitment_commit_requires_authorized_vendor
    """
    scenario, commitment = _proposed_commitment_on_an_authorized_vendor()
    vendor_id, month_id = scenario["vendor"]["id"], scenario["m1"]["id"]

    set_vendor_status(vendor_id, "SUSPENDED")
    reinstated = set_vendor_status(vendor_id, "AUTHORIZED")
    assert reinstated["status"] == "AUTHORIZED"
    restored = _authorizations_of(api, vendor_id)
    assert [row["status"] for row in restored] == ["ACTIVE"]
    assert restored[0]["id"] == scenario["authorization"]["id"]

    committed = commit_commitment(commitment["id"])
    assert committed["commit_status"] == "COMMITTED"
    assert committed["fulfillment_status"] == "AWAITING_SHIP"
    assert committed["open_cost_cents"] == 1_000_000

    month = get_month(month_id)
    assert month["otb_committed_cents"] == 1_000_000
    assert month["otb_open_cents"] == 17_200_000
    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 9751
    assert plan["otb_posture"] == "OPEN"


def _locked_month_under_a_reforecasting_plan():
    scenario = setup_single_month_approved_plan()
    cycle = open_reforecast_cycle(scenario["plan_id"],
                                 reason_note="rebuild March before selling")
    return scenario, cycle


def test_open_season_is_refused_while_the_parent_plan_is_reforecasting(api):
    """The month is in the only state open-season starts from; its parent plan is not APPROVED.

    PRD: a locked month opening for the season "is permitted only while the parent category
    plan's `status` is `APPROVED`; a month may not open for selling while its plan sits in
    `DRAFT`, `SUBMITTED`, `REFORECAST_OPEN` or `CLOSED`, and an attempt is refused with
    `ERR_CATEGORY_PLAN_NOT_APPROVED`." Opening a reforecast round moves only the parent -- PRD:
    "the plan advances `APPROVED -> REFORECAST_OPEN`" -- leaving the month at `LOCKED_PLAN`.

    Design: Difficulty/cross_entity_state_dependency/open_season_requires_approved_category_plan
    """
    scenario, cycle = _locked_month_under_a_reforecasting_plan()
    month_id = scenario["m1"]["id"]
    assert get_month(month_id)["status"] == "LOCKED_PLAN"
    assert get_plan(scenario["plan_id"])["status"] == "REFORECAST_OPEN"
    assert cycle["status"] == "OPEN"
    version_before = get_month(month_id)["version"]

    resp = api.open_season(month_id, {}, PLANNER_HEADERS)

    validate_error(resp, ApiErrorId.ERR_CATEGORY_PLAN_NOT_APPROVED, expected_status=409)
    month = get_month(month_id)
    assert month["status"] == "LOCKED_PLAN"
    assert month["active_basis"] == "PLANNED_BASIS"
    assert month["version"] == version_before


def test_submitted_is_refused_too_and_only_re_approval_opens_the_month(api):
    """The guard demands exactly APPROVED, so SUBMITTED fails with the very same code.

    PRD: the empty cycle uses the liveness escape -- "A cycle that was opened and then judged to
    need no correction whatsoever can also be closed directly from `OPEN`" -- and then the
    governance loop closes: "`DRAFT -> SUBMITTED -> APPROVED -> REFORECAST_OPEN -> SUBMITTED ->
    APPROVED`". Re-approval leaves the already-locked month alone because cascade-B link 2 only
    promotes months "whose `status` is `DRAFT`", and the third open-season attempt then advances
    it `LOCKED_PLAN -> IN_SEASON` with "`active_basis` remains `PLANNED_BASIS` until the first
    week of actuals lands against it".

    Design: Difficulty/cross_entity_state_dependency/open_season_requires_approved_category_plan
    """
    scenario, cycle = _locked_month_under_a_reforecasting_plan()
    month_id, plan_id = scenario["m1"]["id"], scenario["plan_id"]

    closed = close_cycle(cycle["id"])
    assert closed["status"] == "CLOSED"

    submit_plan(plan_id, submission_note="round 1 rebuild")
    assert get_plan(plan_id)["status"] == "SUBMITTED"
    refused = api.open_season(month_id, {}, PLANNER_HEADERS)
    validate_error(refused, ApiErrorId.ERR_CATEGORY_PLAN_NOT_APPROVED, expected_status=409)
    assert get_month(month_id)["status"] == "LOCKED_PLAN"

    approve_plan(plan_id, approval_note="re-approved")
    plan = get_plan(plan_id)
    assert plan["status"] == "APPROVED"
    assert plan["receipt_budget_cents"] == 60_000_000
    still_locked = get_month(month_id)
    assert still_locked["status"] == "LOCKED_PLAN"
    assert still_locked["otb_planned_cents"] == 18_200_000

    opened = api.open_season(month_id, {}, PLANNER_HEADERS)
    validate_success(opened, expected_status=200)
    month = get_month(month_id)
    assert month["status"] == "IN_SEASON"
    assert month["active_basis"] == "PLANNED_BASIS"
    assert month["otb_planned_cents"] == 18_200_000

    after = get_plan(plan_id)
    assert after["status"] == "APPROVED"
    assert after["reforecast_round"] == 1
