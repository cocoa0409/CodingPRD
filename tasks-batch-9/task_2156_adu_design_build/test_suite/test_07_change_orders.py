"""Homeowner change orders, the markup tiers, and the contract ledger."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_change_order, assert_contract_ledger_consistent,
    change_order_payload,
    setup_intake_project, setup_feasibility_cleared_project, setup_permitted_project,
    setup_submitted_change_order, setup_approved_change_order, setup_committed_income_scenario,
    raise_change_order, send_change_order, decide_change_order,
    read_project, read_change_orders,
    PROJECT_MANAGER, FINANCE_ADVISOR,
)


def test_first_change_order_takes_the_ten_percent_tier(api):
    """PRD §3.6: "Third, the markup tier is selected from that "before" percentage: strictly
    below 5.00 percent the builder takes 10 percent; at 5.00 percent and strictly below 15.00
    percent the builder takes 15 percent; at 15.00 percent and above the builder takes 20
    percent."
    PRD §3.6: "Fourth, `builder_fee_cents` is this change order's `cost_delta_cents`
    multiplied by the selected rate, rounded once, half away from zero, to whole cents; on a
    credit this rounds away from zero too, so a computed fee of negative 1250.5 cents becomes
    negative 1251."

    Design: Difficulty/combinatorial_formula/change_order_markup_tier_evaluation_order
    """
    ctx = setup_permitted_project(api)

    approved = setup_approved_change_order(
        api, ctx, title="Upgrade to mini-split HVAC",
        scope_items=["Remove wall heater", "Install ductless mini-split"],
        cost_delta_cents=1_300_000, schedule_delta_days=6)

    assert_change_order(approved)
    assert approved["cumulative_change_pct_before"] == 0.0
    assert approved["builder_fee_cents"] == 130_000
    assert approved["cumulative_change_pct_after"] == 5.96
    assert read_project(api, ctx["project"]["id"])["contract_price_current_cents"] == 25_430_000


def test_second_change_order_reads_the_tier_from_the_before_percentage(api):
    """PRD §3.6: "The reconciliation looks circular — the markup feeds the price and the tier
    is keyed on a percentage — so its evaluation order is pinned, and the percentage is
    **always** measured against `contract_base_price_cents`, never against
    `contract_price_current_cents`."
    PRD §3.6: "Fifth, the project's `contract_price_current_cents` becomes
    `contract_base_price_cents` plus the cumulative prior plus this change order's
    `cost_delta_cents` plus its `builder_fee_cents`."

    Design: Difficulty/combinatorial_formula/change_order_markup_tier_evaluation_order
    """
    ctx = setup_permitted_project(api)
    setup_approved_change_order(
        api, ctx, title="Upgrade to mini-split HVAC",
        scope_items=["Remove wall heater", "Install ductless mini-split"],
        cost_delta_cents=1_300_000, schedule_delta_days=6)

    second = setup_approved_change_order(
        api, ctx, title="Add covered porch",
        scope_items=["Frame 6x10 porch", "Add porch roofing"],
        cost_delta_cents=1_000_000, schedule_delta_days=4)

    assert second["cumulative_change_pct_before"] == 5.96
    assert second["builder_fee_cents"] == 150_000, "the 15 percent tier, not 10 and not 20"
    assert second["cumulative_change_pct_after"] == 10.75

    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 26_580_000
    assert project["approved_change_days"] == 10
    assert project["approved_change_order_count"] == 2
    assert_contract_ledger_consistent(project, read_change_orders(api, project["id"]))


def test_revision_requested_change_order_returns_to_draft(api):
    """PRD §3.6: "Sending a change order for decision moves it `DRAFT → SUBMITTED`. The same
    homeowner action serves double duty in the revision loop: applied to a change order
    sitting in `REVISION_REQUESTED`, it moves the row **backwards** to `DRAFT` and clears
    `decided_by_user_id` to null rather than moving it forward."
    PRD §3.6: "`REQUEST_REVISION` moves the row `SUBMITTED → REVISION_REQUESTED` and has no
    fiscal consequences whatsoever."

    Design: Difficulty/non_linear_state_machine/change_order_revision_loop
    """
    ctx = setup_permitted_project(api)
    change_order = raise_change_order(
        api, ctx, title="Swap to quartz counters",
        scope_items=["Remove laminate counters", "Install quartz slab"],
        cost_delta_cents=900_000, schedule_delta_days=3)
    send_change_order(api, ctx, change_order["id"])
    bounced = decide_change_order(api, change_order["id"], "REQUEST_REVISION")
    assert bounced["status"] == "REVISION_REQUESTED"
    assert bounced["decided_by_user_id"] is not None

    back_to_draft = validate_success(
        api.submit_change_order(change_order["id"], ctx["homeowner_headers"]))

    assert back_to_draft["status"] == "DRAFT"
    assert back_to_draft["decided_by_user_id"] is None


def test_revision_loop_counts_four_mutations_and_moves_no_money(api):
    """PRD §3.6: "The full loop is therefore `DRAFT → SUBMITTED → REVISION_REQUESTED →
    DRAFT`, and it can run as many times as the parties need."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases
    by exactly 1 on every mutation of that row, whether the mutation was requested directly or
    arrived as a cascade from somewhere else."
    PRD §3.6: "The new row is created in `DRAFT` with `builder_fee_cents` at 0, both
    `cumulative_change_pct_before` and `cumulative_change_pct_after` at 0, `decided_by_user_id`
    null, and `authored_by_user_id` set to the acting `X-User-ID`; the project's `version`
    rises by 1."

    Design: Difficulty/non_linear_state_machine/change_order_revision_loop
    """
    ctx = setup_permitted_project(api)
    change_order = raise_change_order(
        api, ctx, title="Swap to quartz counters",
        scope_items=["Remove laminate counters", "Install quartz slab"],
        cost_delta_cents=900_000, schedule_delta_days=3)
    assert change_order["authored_by_user_id"] == ctx["property"]["id"]
    send_change_order(api, ctx, change_order["id"])
    decide_change_order(api, change_order["id"], "REQUEST_REVISION")

    looped = validate_success(
        api.submit_change_order(change_order["id"], ctx["homeowner_headers"]))

    assert looped["version"] == 4, "create, submit, request-revision and resubmission"
    assert looped["builder_fee_cents"] == 0

    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 24_000_000
    assert project["approved_change_order_count"] == 0


def test_approving_a_change_order_pushes_the_committed_scenario_into_shortfall(api):
    """PRD §2.9: "The **change-order funding chain** has three links. Approving a change order
    stamps the markup and percentages on the change order itself; because the change order
    became `APPROVED`, the project's current contract price, approved-change day count, and
    approved-change count are all recomputed; and because the contract price moved, the
    project's single committed financing scenario is repriced, which can push
    `financing_state` from `COMMITTED` to `SHORTFALL`."
    PRD §3.6: "Finally, because the contract price moved, the project's single `COMMITTED`
    financing scenario has its `required_funds_cents` and `funding_gap_cents` recomputed
    against the new price; if the recomputed `funding_gap_cents` is greater than 0, the
    project's `financing_state` moves `COMMITTED → SHORTFALL`."

    Design: Difficulty/transitive_cascade/change_order_funding_chain
    """
    ctx = setup_permitted_project(api)
    scenario = setup_committed_income_scenario(api, ctx)
    assert scenario["funding_gap_cents"] == 0

    approved = setup_approved_change_order(
        api, ctx, title="Add detached carport",
        scope_items=["Pour carport slab", "Frame and roof carport"],
        cost_delta_cents=4_000_000, schedule_delta_days=21)
    assert approved["status"] == "APPROVED"
    assert approved["builder_fee_cents"] == 400_000

    repriced = validate_success(api.get_financing_scenario(scenario["id"], FINANCE_ADVISOR))
    assert repriced["required_funds_cents"] == 32_360_465
    assert repriced["funding_gap_cents"] == 2_265_920
    assert repriced["available_cents"] == 30_094_545
    assert read_project(api, ctx["project"]["id"])["financing_state"] == "SHORTFALL"


def test_approving_a_change_order_moves_the_ledger_but_not_the_lifecycle(api):
    """PRD §3.6: "The project then takes the new `contract_price_current_cents`, grows
    `approved_change_days` by this row's `schedule_delta_days`, grows
    `approved_change_order_count` by 1, and raises its `version` by 1."
    PRD §2.9: "The two axes advance on unrelated triggers and never gate one another except
    where a rule below explicitly says so."

    Design: Difficulty/transitive_cascade/change_order_funding_chain
    """
    ctx = setup_permitted_project(api)
    setup_committed_income_scenario(api, ctx)

    approved = setup_approved_change_order(
        api, ctx, title="Add detached carport",
        scope_items=["Pour carport slab", "Frame and roof carport"],
        cost_delta_cents=4_000_000, schedule_delta_days=21)

    assert approved["cumulative_change_pct_after"] == 18.33
    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 28_400_000
    assert project["approved_change_days"] == 21
    assert project["approved_change_order_count"] == 1
    assert project["status"] == "PERMITTED", "the lifecycle axis is untouched"


def test_approval_on_a_project_short_of_permitted_reports_the_phase_error(api):
    """PRD §3.6: "Approval carries two gates beyond the state check. The project must be in
    `PERMITTED` or `UNDER_CONSTRUCTION` — approving against a project in any other lifecycle
    state is rejected with `ERR_PROJECT_PHASE_INVALID`. And the reconciliation below must not
    breach the cumulative change cap."
    PRD §2.7: "8. **State preconditions.** Whether the target resource is in a state from
    which the requested action has a declared transition, and the specific gating conditions
    numbered from there."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_change_order_approve
    """
    ctx = setup_feasibility_cleared_project(api)
    change_order = setup_submitted_change_order(
        api, ctx, title="Add second bathroom",
        scope_items=["Rough in second bath", "Tile and fixtures"],
        cost_delta_cents=5_500_000, schedule_delta_days=25)

    error = validate_error(
        api.decide_change_order(change_order["id"], {"decision": "APPROVE"}, PROJECT_MANAGER),
        ApiErrorId.ERR_PROJECT_PHASE_INVALID)

    assert error["error_id"] != ApiErrorId.ERR_CHANGE_CAP_EXCEEDED.value, (
        "the lifecycle-state gate is evaluated before the cumulative change cap")


def test_state_rejected_approval_persists_neither_fee_nor_price(api):
    """PRD §3.6: "Seventh and last, once the fee is known, the cap is checked: if
    `cumulative_change_pct_after` is **strictly greater** than 25.00 percent, the approval is
    rejected with `ERR_CHANGE_CAP_EXCEEDED` (HTTP 409) and nothing at all is persisted — not
    the fee, not the percentages, not the project price."
    PRD §3.6: "Approval carries two gates beyond the state check. The project must be in
    `PERMITTED` or `UNDER_CONSTRUCTION` — approving against a project in any other lifecycle
    state is rejected with `ERR_PROJECT_PHASE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_change_order_approve
    """
    ctx = setup_feasibility_cleared_project(api)
    change_order = setup_submitted_change_order(
        api, ctx, title="Add second bathroom",
        scope_items=["Rough in second bath", "Tile and fixtures"],
        cost_delta_cents=5_500_000, schedule_delta_days=25)

    validate_error(
        api.decide_change_order(change_order["id"], {"decision": "APPROVE"}, PROJECT_MANAGER),
        ApiErrorId.ERR_PROJECT_PHASE_INVALID)

    unchanged = validate_success(api.get_change_order(change_order["id"], PROJECT_MANAGER))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["builder_fee_cents"] == 0
    assert read_project(api, ctx["project"]["id"])["contract_price_current_cents"] == 24_000_000


def test_voiding_an_approved_change_order_restores_the_contract_ledger(api):
    """PRD §3.6: "On success the row moves `APPROVED → VOIDED`, its `builder_fee_cents`,
    `cumulative_change_pct_before`, and `cumulative_change_pct_after` all reset to 0, and the
    project's ledger is rebuilt over the change orders that remain `APPROVED`:
    `contract_price_current_cents` is recomputed, `approved_change_days` falls by the voided
    row's `schedule_delta_days`, and `approved_change_order_count` falls by 1."

    Design: Difficulty/compensating_invariant/contract_price_ledger_conserved_on_void
    """
    ctx = setup_permitted_project(api)
    setup_committed_income_scenario(api, ctx)
    approved = setup_approved_change_order(
        api, ctx, title="Add detached carport",
        scope_items=["Pour carport slab", "Frame and roof carport"],
        cost_delta_cents=4_000_000, schedule_delta_days=21)
    assert read_project(api, ctx["project"]["id"])["contract_price_current_cents"] == 28_400_000

    voided = validate_success(api.void_change_order(approved["id"], PROJECT_MANAGER))

    assert voided["status"] == "VOIDED"
    assert voided["builder_fee_cents"] == 0
    assert voided["cumulative_change_pct_before"] == 0
    assert voided["cumulative_change_pct_after"] == 0

    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 24_000_000
    assert project["approved_change_days"] == 0
    assert project["approved_change_order_count"] == 0
    assert_contract_ledger_consistent(project, read_change_orders(api, project["id"]))


def test_voiding_a_change_order_closes_the_funding_gap_again(api):
    """PRD §3.6: "The project's committed financing scenario is repriced the same way it was
    on approval, and when the recomputed `funding_gap_cents` is 0 the project's
    `financing_state` moves `SHORTFALL → COMMITTED`, closing the funding cycle."
    PRD §2.9: "Voiding an approved change order is the exact compensating action for approving
    it: the contract ledger is recomputed over the change orders that remain approved, and the
    funding axis can move back from `SHORTFALL` to `COMMITTED`."

    Design: Difficulty/compensating_invariant/contract_price_ledger_conserved_on_void
    """
    ctx = setup_permitted_project(api)
    scenario = setup_committed_income_scenario(api, ctx)
    approved = setup_approved_change_order(
        api, ctx, title="Add detached carport",
        scope_items=["Pour carport slab", "Frame and roof carport"],
        cost_delta_cents=4_000_000, schedule_delta_days=21)
    assert read_project(api, ctx["project"]["id"])["financing_state"] == "SHORTFALL"

    validate_success(api.void_change_order(approved["id"], PROJECT_MANAGER))

    restored = validate_success(api.get_financing_scenario(scenario["id"], FINANCE_ADVISOR))
    assert restored["required_funds_cents"] == 27_520_465
    assert restored["funding_gap_cents"] == 0

    project = read_project(api, ctx["project"]["id"])
    assert project["financing_state"] == "COMMITTED"
    assert project["status"] == "PERMITTED"


def test_rejecting_a_change_order_leaves_the_contract_untouched(api):
    """PRD §3.6: "`REJECT` moves the row `SUBMITTED → REJECTED`, which is terminal, and
    likewise leaves the project's `contract_price_current_cents`, `approved_change_days`, and
    `approved_change_order_count` completely untouched. Only `APPROVE` moves money."
    PRD §3.6: "in all three cases the change order must be in `SUBMITTED` or the answer is
    `ERR_CHANGE_ORDER_STATE_INVALID`, and in all three cases `decided_by_user_id` is set to
    the deciding `X-User-ID` and the change order's `version` rises by 1."

    Design: Corner/state_machines/change_order_reject_branch_leaves_contract_untouched
    """
    ctx = setup_permitted_project(api)
    change_order = setup_submitted_change_order(
        api, ctx, title="Upgrade siding", scope_items=["Swap fiber cement for cedar"],
        cost_delta_cents=2_000_000, schedule_delta_days=5)

    rejected = validate_success(
        api.decide_change_order(change_order["id"], {"decision": "REJECT"}, PROJECT_MANAGER))

    assert rejected["status"] == "REJECTED"
    assert rejected["builder_fee_cents"] == 0
    assert rejected["decided_by_user_id"] is not None

    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 24_000_000
    assert project["approved_change_days"] == 0
    assert project["approved_change_order_count"] == 0


def test_credit_change_order_rounds_the_markup_away_from_zero(api):
    """PRD §2.8: "The first, applied to every fee and every builder markup, rounds half away
    from zero to whole cents — so a computed fee of 1250.5 cents becomes 1251, and a computed
    credit of negative 1250.5 cents becomes negative 1251."
    PRD §3.6: "a `cost_delta_cents` figure that is signed so that negative values are credits,
    and a `schedule_delta_days` figure that is likewise signed and must lie between negative
    30 and 120 inclusive."

    Design: Corner/calculations/credit_change_order_rounds_fee_away_from_zero
    """
    ctx = setup_permitted_project(api)

    approved = setup_approved_change_order(
        api, ctx, title="Delete the second bath",
        scope_items=["Remove second bath rough-in"],
        cost_delta_cents=-1_200_000, schedule_delta_days=-5)

    assert approved["status"] == "APPROVED"
    assert approved["builder_fee_cents"] == -120_000
    assert approved["cumulative_change_pct_after"] == -5.5

    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 22_680_000
    assert project["approved_change_days"] == -5
    assert project["approved_change_order_count"] == 1


def test_change_order_without_substance_is_rejected(api):
    """PRD §3.6: "A change order must carry substance: one whose `scope_items` array is empty
    **and** whose `cost_delta_cents` is 0 **and** whose `schedule_delta_days` is 0 is rejected
    with `ERR_EMPTY_CHANGE_ORDER` (HTTP 422)."

    Design: Corner/validations/change_order_with_no_substance_returns_empty_change_order
    """
    ctx = setup_intake_project(api)

    validate_error(
        api.create_change_order(
            ctx["project"]["id"],
            change_order_payload(ctx["project"]["version"], title="Nothing at all",
                                 scope_items=[], cost_delta_cents=0, schedule_delta_days=0),
            ctx["homeowner_headers"]),
        ApiErrorId.ERR_EMPTY_CHANGE_ORDER)

    assert read_project(api, ctx["project"]["id"])["version"] == 1
    rows, meta = validate_paginated(api.list_change_orders(
        PROJECT_MANAGER, {"adu_project_id": ctx["project"]["id"]}))
    assert meta["total_count"] == 0


def test_change_orders_can_be_listed_by_the_row_they_supersede(api):
    """PRD §3.6: "An optional `supersedes_change_order_id` names an earlier change order this
    one replaces."
    PRD §3.6: "Change-order listings may be narrowed by `adu_project_id`, by
    `supersedes_change_order_id`, and by `status`."

    Design: Corner/endpoints/list_change_orders_filtered_by_supersedes_change_order_id
    """
    ctx = setup_intake_project(api)
    first = raise_change_order(api, ctx, title="Skylight over kitchen",
                               scope_items=["Cut and flash one skylight"],
                               cost_delta_cents=350_000, schedule_delta_days=2)
    second = raise_change_order(api, ctx, title="Two skylights instead of one",
                                scope_items=["Cut and flash two skylights"],
                                cost_delta_cents=620_000, schedule_delta_days=3,
                                supersedes_change_order_id=first["id"])

    rows, meta = validate_paginated(api.list_change_orders(
        PROJECT_MANAGER, {"supersedes_change_order_id": first["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]
    assert rows[0]["supersedes_change_order_id"] == first["id"]

    _, project_meta = validate_paginated(api.list_change_orders(
        PROJECT_MANAGER, {"adu_project_id": ctx["project"]["id"]}))
    assert project_meta["total_count"] == 2


def test_second_change_order_with_a_stale_project_version_is_rejected(api):
    """PRD §2.6: "Raising a change order against a project — `POST
    /adu-projects/{id}/change-orders` — also requires `expected_adu_project_version`. A change
    order is legitimate from any project state that is not final and may supersede an earlier
    one, so the create cannot be refused on state alone; the version check rejects a homeowner
    whose observed project version predates a price-moving approval or supersede. A mismatch
    is likewise rejected with `ERR_STALE_PROJECT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_change_order_create
    """
    ctx = setup_intake_project(api)
    stale_version = ctx["project"]["version"]

    first = validate_success(api.create_change_order(
        ctx["project"]["id"],
        change_order_payload(stale_version, title="Add a bay window",
                             scope_items=["Frame a bay window"],
                             cost_delta_cents=480_000, schedule_delta_days=2),
        ctx["homeowner_headers"]), 201)
    assert read_project(api, ctx["project"]["id"])["version"] == 2

    validate_error(
        api.create_change_order(
            ctx["project"]["id"],
            change_order_payload(stale_version, title="Add a skylight too",
                                 scope_items=["Cut one skylight"],
                                 cost_delta_cents=300_000, schedule_delta_days=1),
            ctx["homeowner_headers"]),
        ApiErrorId.ERR_STALE_PROJECT_VERSION)

    rows, meta = validate_paginated(api.list_change_orders(
        PROJECT_MANAGER, {"adu_project_id": ctx["project"]["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert read_project(api, ctx["project"]["id"])["version"] == 2


def test_markup_tier_two_applies_at_exactly_five_percent(api):
    """PRD §3.6: "The tier boundaries are strict in exactly this sense — a "before" percentage
    of exactly 5.00 selects the 15 percent rate, and exactly 15.00 selects the 20 percent
    rate."
    PRD §3.6: "Second, `cumulative_change_pct_before` is that cumulative prior divided by
    `contract_base_price_cents`, expressed as a percentage by multiplying by 100, rounded half
    away from zero to two decimal places."

    Design: Corner/cross_cutting_complexity_layers/markup_tier_boundary_at_exactly_five_percent
    """
    ctx = setup_permitted_project(api, project_overrides={"contract_base_price_cents": 22_000_000})
    first = setup_approved_change_order(
        api, ctx, title="Tankless water heater", scope_items=["Swap tank for tankless"],
        cost_delta_cents=1_000_000, schedule_delta_days=2)
    assert first["builder_fee_cents"] == 100_000
    assert first["cumulative_change_pct_after"] == 5.0

    second = setup_approved_change_order(
        api, ctx, title="Add pantry cabinetry", scope_items=["Build pantry"],
        cost_delta_cents=1_000_000, schedule_delta_days=2)

    assert second["cumulative_change_pct_before"] == 5.0
    assert second["builder_fee_cents"] == 150_000
    assert second["cumulative_change_pct_after"] == 10.23
    assert read_project(api, ctx["project"]["id"])["contract_price_current_cents"] == 24_250_000


def test_cumulative_cap_admits_exactly_twenty_five_percent_and_rejects_above_it(api):
    """PRD §3.6: "Seventh and last, once the fee is known, the cap is checked: if
    `cumulative_change_pct_after` is **strictly greater** than 25.00 percent, the approval is
    rejected with `ERR_CHANGE_CAP_EXCEEDED` (HTTP 409) and nothing at all is persisted — not
    the fee, not the percentages, not the project price. A result landing exactly on 25.00
    percent is allowed through."

    Design: Corner/cross_cutting_complexity_layers/change_order_cap_accepted_at_exactly_twenty_five_percent
    """
    ctx = setup_permitted_project(api, project_overrides={"contract_base_price_cents": 22_000_000})
    big = setup_submitted_change_order(
        api, ctx, title="Full kitchen upgrade",
        scope_items=["Custom cabinets", "Appliance package"],
        cost_delta_cents=5_000_000, schedule_delta_days=20)
    small = setup_submitted_change_order(
        api, ctx, title="One more sconce", scope_items=["Add a wall sconce"],
        cost_delta_cents=100_000, schedule_delta_days=0)

    approved = validate_success(
        api.decide_change_order(big["id"], {"decision": "APPROVE"}, PROJECT_MANAGER))
    assert approved["builder_fee_cents"] == 500_000
    assert approved["cumulative_change_pct_after"] == 25.0

    validate_error(
        api.decide_change_order(small["id"], {"decision": "APPROVE"}, PROJECT_MANAGER),
        ApiErrorId.ERR_CHANGE_CAP_EXCEEDED)

    unchanged = validate_success(api.get_change_order(small["id"], PROJECT_MANAGER))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["builder_fee_cents"] == 0

    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 27_500_000
    assert project["approved_change_order_count"] == 1
    assert project["approved_change_days"] == 20
