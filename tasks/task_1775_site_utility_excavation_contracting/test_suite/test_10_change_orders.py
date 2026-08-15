"""Change orders: pinned pricing, fiscal caps, OCC, supersede, and the
amount-gated review delegation."""

from test_helpers import (
    PM_SECOND,
    PROJECT_MANAGER,
    ApiErrorId,
    change_order_payload,
    create_change_order,
    create_project,
    create_unforeseen_condition,
    create_utility_owner,
    get_change_order,
    get_condition,
    get_project,
    make_project_manager_headers,
    make_utility_owner_rep_headers,
    submit_change_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_provisional_and_final_variants_reconcile(api):
    """PRD §3.8: "The estimate-based `provisional_price_cents` is the direct
    cost plus the markup, and it must not exceed the project's
    `single_co_cap_cents`, with a price exactly at the cap allowed — a breach
    at creation or at submission is `ERR_PRICE_CAP_EXCEEDED`."
    PRD §3.8: "Completing an `APPROVED` order takes the actuals —
    `actual_labor_hours`, `actual_labor_rate_cents`, `actual_equipment_hours`,
    `actual_equipment_rate_cents`, and `actual_material_cost_cents` — and
    prices them through the identical procedure used for the estimate,
    producing the time-and-materials `final_price_cents`. The
    `price_delta_cents` is the final price minus the provisional price, and
    the project's `approved_co_total_cents` shifts by exactly that delta: the
    order's contribution to the ledger swaps from its provisional value to its
    final value, so an underrun reduces the committed total."
    PRD §3.8: "Approval moves money and condition alike: the project's
    `approved_co_total_cents` rises by the `provisional_price_cents`, and a
    condition still `OPEN` moves to `MITIGATING`."

    Design: Difficulty/dual_variant_calc/co_price_provisional_vs_final_reconciliation
    """
    project = create_project(name="P-CO", contract_ref="C-100",
                             soil_class_default="SOIL_C")
    owner = create_utility_owner(name="City Water")
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock at 8 ft"
    )

    co = create_change_order(project, owner, condition)
    assert co["direct_cost_cents"] == 250_000       # 150000 + 80000 + 20000
    assert co["markup_cents"] == 37_500             # 250000 * 0.15
    assert co["provisional_price_cents"] == 287_500

    submit_change_order(co["id"])
    approved = validate_success(
        api.review_change_order(
            co["id"], "APPROVE", make_project_manager_headers(PM_SECOND)
        )
    )
    assert approved["status"] == "APPROVED"
    assert get_project(project["id"])["approved_co_total_cents"] == 287_500
    assert get_condition(condition["id"])["status"] == "MITIGATING"

    completed = validate_success(
        api.complete_change_order(
            co["id"],
            {
                "actual_labor_hours": 12.0, "actual_labor_rate_cents": 15_000,
                "actual_equipment_hours": 4.0,
                "actual_equipment_rate_cents": 20_000,
                "actual_material_cost_cents": 25_000,
            },
            PROJECT_MANAGER,
        )
    )
    # FINAL variant over actuals: direct 285000, markup 42750.
    assert completed["status"] == "COMPLETED"
    assert completed["final_price_cents"] == 327_750
    assert completed["price_delta_cents"] == 40_250
    # The ledger swaps the provisional contribution for the final one.
    assert get_project(project["id"])["approved_co_total_cents"] == 327_750


def test_final_variant_equals_provisional_when_actuals_match(api):
    """PRD §3.8: "Completing an `APPROVED` order takes the actuals —
    `actual_labor_hours`, `actual_labor_rate_cents`, `actual_equipment_hours`,
    `actual_equipment_rate_cents`, and `actual_material_cost_cents` — and
    prices them through the identical procedure used for the estimate,
    producing the time-and-materials `final_price_cents`. The
    `price_delta_cents` is the final price minus the provisional price, and
    the project's `approved_co_total_cents` shifts by exactly that delta: the
    order's contribution to the ledger swaps from its provisional value to its
    final value, so an underrun reduces the committed total."

    Design: Difficulty/dual_variant_calc/co_price_provisional_vs_final_reconciliation
    """
    project = create_project(name="P-CO2", contract_ref="C-101",
                             soil_class_default="SOIL_C")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock"
    )
    co = create_change_order(project, owner, condition)
    submit_change_order(co["id"])
    validate_success(
        api.review_change_order(
            co["id"], "APPROVE", make_project_manager_headers(PM_SECOND)
        )
    )

    completed = validate_success(
        api.complete_change_order(
            co["id"],
            {
                "actual_labor_hours": 10.0, "actual_labor_rate_cents": 15_000,
                "actual_equipment_hours": 4.0,
                "actual_equipment_rate_cents": 20_000,
                "actual_material_cost_cents": 20_000,
            },
            PROJECT_MANAGER,
        )
    )
    # Identical actuals: the two variants price the same and the delta is 0.
    assert completed["final_price_cents"] == 287_500
    assert completed["price_delta_cents"] == 0
    assert get_project(project["id"])["approved_co_total_cents"] == 287_500


def test_pinned_rounding_order_per_line_then_per_slice(api):
    """PRD §3.8: "Pricing follows a pinned rounding order so that stored
    totals are exact sums of rounded components. The labor cost line is the
    labor hours multiplied by the labor rate in cents per hour, rounded half
    up to a whole cent; the equipment cost line is computed the same way from
    the equipment hours and rate. The `direct_cost_cents` is the sum of those
    two rounded lines plus the material cost. The markup is marginal over the
    direct cost in three tiers: fifteen percent of the portion of the direct
    cost up to and including 2,500,000 cents — twenty-five thousand dollars;
    ten percent of the portion above 2,500,000 cents and up to and including
    10,000,000 cents — one hundred thousand dollars; and five percent of any
    portion above 10,000,000 cents. Each tier slice is rounded half up to a
    whole cent, and the `markup_cents` is the sum of the three rounded
    slices."

    Design: Difficulty/combinatorial_formula/co_price_pinned_rounding_order
    """
    project = create_project(name="P-RND", contract_ref="C-300",
                             soil_class_default="SOIL_B")
    owner = create_utility_owner(
        name="Gas Co", owner_type="GAS", min_notice_hours=72,
        max_shutdown_hours=4,
    )
    condition = create_unforeseen_condition(
        project, condition_type="CONTAMINATED_SOIL",
        description="stained soil at sta 12+00",
    )

    co = create_change_order(
        project, owner, condition,
        labor_hours=3.5, labor_rate_cents=10_001,
        equipment_hours=1.5, equipment_rate_cents=7_777,
        material_cost_cents=1_001,
    )
    # round_half_up(3.5*10001) == 35004; round_half_up(1.5*7777) == 11666.
    assert co["direct_cost_cents"] == 47_671
    # Single tier slice: round_half_up(47671 * 0.15) == round_half_up(7150.65).
    assert co["markup_cents"] == 7_151
    # Sum-then-round would yield 54821; the pinned order yields 54822.
    assert co["provisional_price_cents"] == 54_822


def test_markup_marginal_tiers_across_boundary(api):
    """PRD §3.8: "The markup is marginal over the direct cost in three tiers:
    fifteen percent of the portion of the direct cost up to and including
    2,500,000 cents — twenty-five thousand dollars; ten percent of the portion
    above 2,500,000 cents and up to and including 10,000,000 cents — one
    hundred thousand dollars; and five percent of any portion above
    10,000,000 cents. Each tier slice is rounded half up to a whole cent, and
    the `markup_cents` is the sum of the three rounded slices."

    Design: Difficulty/combinatorial_formula/co_price_pinned_rounding_order
    """
    project = create_project(name="P-RND2", contract_ref="C-301",
                             soil_class_default="SOIL_B")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock mass"
    )

    co = create_change_order(
        project, owner, condition,
        labor_hours=200.0, labor_rate_cents=10_000,
        equipment_hours=100.0, equipment_rate_cents=10_000,
        material_cost_cents=0,
    )
    assert co["direct_cost_cents"] == 3_000_000
    # slice1 2500000*0.15 == 375000; slice2 500000*0.10 == 50000.
    assert co["markup_cents"] == 425_000
    assert co["provisional_price_cents"] == 3_425_000


def test_cross_project_reference_beats_price_cap(api):
    """PRD §2.10: "Ninth come cross-entity integrity and cross-entity state
    gates: a body reference that resolves into a different project's scope is
    `ERR_CROSS_PROJECT_REFERENCE`; … Eleventh and last come the fiscal caps:
    `ERR_PRICE_CAP_EXCEEDED` for a change order priced over the per-order cap
    and `ERR_CONTINGENCY_EXCEEDED` for an approval that would overrun the
    project's contingency pool."
    PRD §2.11: "a change order's unforeseen condition must belong to the
    change order's project; and an unforeseen condition that names a pipe
    segment must name one inside its own project. Any breach is rejected with
    `ERR_CROSS_PROJECT_REFERENCE`."

    Design: Difficulty/priority_pair_validation_conflict/co_create_referential_beats_fiscal
    """
    p1 = create_project(name="P1-PR2", contract_ref="C-1000",
                        soil_class_default="SOIL_B")
    p2 = create_project(name="P2-PR2", contract_ref="C-1001",
                        soil_class_default="SOIL_B")
    owner = create_utility_owner(
        name="Gas Co", owner_type="GAS", min_notice_hours=72,
        max_shutdown_hours=4,
    )
    condition_p2 = create_unforeseen_condition(
        p2, condition_type="VOID", description="void under slab"
    )

    # The condition belongs to p2 AND the price (11125000) is over p1's cap —
    # the referential violation must win.
    response = api.create_change_order(
        change_order_payload(
            p1["id"], condition_p2["id"], owner["id"], p1["version"],
            labor_hours=1000.0, labor_rate_cents=10_000,
            equipment_hours=0.0, equipment_rate_cents=1,
            material_cost_cents=0,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE, 422)

    _, meta = validate_paginated(
        api.list_change_orders(PROJECT_MANAGER, params={"project_id": p1["id"]})
    )
    assert meta["total_count"] == 0, "rejected create must not persist"
    assert get_project(p1["id"])["version"] == p1["version"]


def test_cross_project_reference_fires_with_clean_price(api):
    """PRD §2.11: "References must stay inside one project scope. A pothole
    verification's locate ticket must belong to the same project as the
    pothole; a trench safety plan's pipe segment must belong to the same
    project as the plan; a shutdown window's pipe segment must belong to the
    window's project, and the window's `utility_owner_id` must match the owner
    recorded on that segment; a change order's unforeseen condition must
    belong to the change order's project; and an unforeseen condition that
    names a pipe segment must name one inside its own project. Any breach is
    rejected with `ERR_CROSS_PROJECT_REFERENCE`."

    Design: Difficulty/priority_pair_validation_conflict/co_create_referential_beats_fiscal
    """
    p1 = create_project(name="P1-PR3", contract_ref="C-1002",
                        soil_class_default="SOIL_B")
    p2 = create_project(name="P2-PR3", contract_ref="C-1003",
                        soil_class_default="SOIL_B")
    owner = create_utility_owner()
    condition_p2 = create_unforeseen_condition(
        p2, condition_type="ROCK", description="rock"
    )

    # Cheap price isolates the referential violation.
    response = api.create_change_order(
        change_order_payload(
            p1["id"], condition_p2["id"], owner["id"], p1["version"],
            labor_hours=1.0, labor_rate_cents=15_000,
            equipment_hours=0.0, equipment_rate_cents=1,
            material_cost_cents=0,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE, 422)


def test_price_cap_enforced_on_clean_reference(api):
    """PRD §3.8: "The estimate-based `provisional_price_cents` is the direct
    cost plus the markup, and it must not exceed the project's
    `single_co_cap_cents`, with a price exactly at the cap allowed — a breach
    at creation or at submission is `ERR_PRICE_CAP_EXCEEDED`."

    Design: Corner/validations/price_cap_enforced_on_clean_reference
    """
    project = create_project(name="P-CAP", contract_ref="C-414",
                             soil_class_default="SOIL_B")
    owner = create_utility_owner(
        name="Gas Co", owner_type="GAS", min_notice_hours=72,
        max_shutdown_hours=4,
    )
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock"
    )

    # Direct 10000000 + markup 1125000 = 11125000 > cap 5000000.
    response = api.create_change_order(
        change_order_payload(
            project["id"], condition["id"], owner["id"], project["version"],
            labor_hours=1000.0, labor_rate_cents=10_000,
            equipment_hours=0.0, equipment_rate_cents=1,
            material_cost_cents=0,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_PRICE_CAP_EXCEEDED, 422)
    assert get_project(project["id"])["version"] == project["version"]


def test_contingency_exceeded_at_approve(api):
    """PRD §3.8: "Either way, the reviewer's identity must differ from
    `submitted_by_user_id` (`ERR_SOD_VIOLATION`), the condition must still be
    `OPEN` or `MITIGATING` (`ERR_CONDITION_NOT_OPEN`), and an approval must
    keep the project's books inside its pool: the existing
    `approved_co_total_cents` plus this order's `provisional_price_cents` may
    not exceed `contingency_cents`, with equality allowed, else
    `ERR_CONTINGENCY_EXCEEDED`."

    Design: Corner/validations/contingency_exceeded_at_approve
    """
    project = create_project(name="P-CTX", contract_ref="C-415",
                             soil_class_default="SOIL_B",
                             contingency_cents=300_000)
    owner = create_utility_owner()
    condition1 = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock A"
    )
    condition2 = create_unforeseen_condition(
        project, condition_type="VOID", description="void B"
    )

    co1 = create_change_order(project, owner, condition1)
    submit_change_order(co1["id"])
    validate_success(
        api.review_change_order(
            co1["id"], "APPROVE", make_project_manager_headers(PM_SECOND)
        )
    )
    assert get_project(project["id"])["approved_co_total_cents"] == 287_500

    co2 = create_change_order(project, owner, condition2)
    submit_change_order(co2["id"])

    # 287500 + 287500 = 575000 > contingency 300000.
    response = api.review_change_order(
        co2["id"], "APPROVE", make_project_manager_headers(PM_SECOND)
    )
    validate_error(response, ApiErrorId.ERR_CONTINGENCY_EXCEEDED, 409)
    assert get_change_order(co2["id"])["status"] == "SUBMITTED"
    assert get_project(project["id"])["approved_co_total_cents"] == 287_500


def test_change_order_create_with_stale_version_rejected(api):
    """PRD §2.9: "If the project's current `version` has advanced beyond the
    supplied value — for example because another writer has just booked a
    window, an operation that legitimately succeeds and bumps the project's
    version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). For
    the change-order create the guard has a specific purpose: a create against
    a fresh project version legitimately supersedes an open change order for
    the same condition, and the stale-version rejection ensures that supersede
    never fires from an outdated view of the project."

    Design: Corner/complexity_layers/co_create_stale_version_rejected
    """
    project = create_project(name="P-OCC2", contract_ref="C-801",
                             soil_class_default="SOIL_B")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock"
    )

    co1 = create_change_order(
        project, owner, condition,
        labor_hours=1.0, labor_rate_cents=15_000,
        equipment_hours=0.0, equipment_rate_cents=1, material_cost_cents=0,
        expected_project_version=project["version"],
    )
    assert get_project(project["id"])["version"] == 2

    response = api.create_change_order(
        change_order_payload(
            project["id"], condition["id"], owner["id"], project["version"],
            labor_hours=2.0, labor_rate_cents=15_000,
            equipment_hours=0.0, equipment_rate_cents=1, material_cost_cents=0,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    # The failed create must not supersede the open order.
    assert get_change_order(co1["id"])["status"] == "DRAFT"
    assert get_project(project["id"])["version"] == 2


def test_fresh_create_supersedes_open_change_order(api):
    """PRD §3.8: "Creation is also a supersede event: any existing change
    order of the same condition in `DRAFT` or `SUBMITTED` moves to
    `SUPERSEDED`, and because creation increments the project's `version` by
    one, the stale-version guard is what prevents a supersede from ever firing
    off an outdated view of the project."
    PRD §3.8: "The new order starts `DRAFT` at `revision` 1."

    Design: Corner/complexity_layers/co_supersede_replaces_open_draft
    """
    project = create_project(name="P-SUP", contract_ref="C-802",
                             soil_class_default="SOIL_B")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock"
    )

    co1 = create_change_order(
        project, owner, condition,
        labor_hours=1.0, labor_rate_cents=15_000,
        equipment_hours=0.0, equipment_rate_cents=1, material_cost_cents=0,
        expected_project_version=project["version"],
    )
    submit_change_order(co1["id"])
    assert get_change_order(co1["id"])["status"] == "SUBMITTED"

    co2 = create_change_order(
        project, owner, condition,
        labor_hours=5.0, labor_rate_cents=15_000,
        equipment_hours=1.0, equipment_rate_cents=20_000,
        material_cost_cents=5_000,
    )
    assert co2["status"] == "DRAFT"
    assert co2["revision"] == 1
    # direct 100000 (75000 + 20000 + 5000); markup 15% == 15000.
    assert co2["provisional_price_cents"] == 115_000

    assert get_change_order(co1["id"])["status"] == "SUPERSEDED"
    # Two successful OCC-guarded creates: version advanced twice from create.
    assert get_project(project["id"])["version"] == project["version"] + 2


def test_large_change_order_requires_owner_rep(api):
    """PRD §3.8: "Review is amount-gated. When the `provisional_price_cents`
    is 2,500,000 cents or more, only a `UtilityOwnerRep` whose `X-User-ID`
    equals the change order's `utility_owner_id` may decide; below that
    threshold the decision belongs to a `ProjectManager`."
    PRD §3.8: "Approval moves money and condition alike: the project's
    `approved_co_total_cents` rises by the `provisional_price_cents`, and a
    condition still `OPEN` moves to `MITIGATING`."

    Design: Corner/rbac/big_co_requires_owner_rep
    """
    project = create_project(name="P-RB5", contract_ref="C-704",
                             soil_class_default="SOIL_B")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock mass"
    )
    co = create_change_order(
        project, owner, condition,
        labor_hours=200.0, labor_rate_cents=10_000,
        equipment_hours=100.0, equipment_rate_cents=10_000,
        material_cost_cents=0,
    )
    assert co["provisional_price_cents"] == 3_425_000  # >= 2,500,000
    submit_change_order(co["id"])

    response = api.review_change_order(
        co["id"], "APPROVE", make_project_manager_headers(PM_SECOND)
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    approved = validate_success(
        api.review_change_order(
            co["id"], "APPROVE", make_utility_owner_rep_headers(owner["id"])
        )
    )
    assert approved["status"] == "APPROVED"
    assert get_project(project["id"])["approved_co_total_cents"] == 3_425_000
    assert get_condition(condition["id"])["status"] == "MITIGATING"


def test_small_change_order_owner_rep_denied(api):
    """PRD §3.8: "Review is amount-gated. When the `provisional_price_cents`
    is 2,500,000 cents or more, only a `UtilityOwnerRep` whose `X-User-ID`
    equals the change order's `utility_owner_id` may decide; below that
    threshold the decision belongs to a `ProjectManager`."

    Design: Corner/rbac/small_co_owner_rep_denied
    """
    project = create_project(name="P-RB6", contract_ref="C-705",
                             soil_class_default="SOIL_B")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock"
    )
    co = create_change_order(project, owner, condition)
    assert co["provisional_price_cents"] == 287_500  # below 2,500,000
    submit_change_order(co["id"])

    response = api.review_change_order(
        co["id"], "APPROVE", make_utility_owner_rep_headers(owner["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    approved = validate_success(
        api.review_change_order(
            co["id"], "APPROVE", make_project_manager_headers(PM_SECOND)
        )
    )
    assert approved["status"] == "APPROVED"
