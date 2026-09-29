"""The validation ladder's cross-entity rungs and the two computed reads.

Every test here turns on precedence or on a set-level predicate: which rung of
the ordered ladder decides a request that violates more than one rule, which
conjunct of a two-clause rule is actually doing the work, and whether a read
that derives money leaves the rows it derived it from untouched. Each expected
integer is the figure the PRD's pinned formulas produce for the authored
inputs.
"""
from test_helpers import (
    ADMIN_HEADERS,
    BUYER_HEADERS,
    CANONICAL,
    CANONICAL_M1_OTB_PLANNED_CENTS,
    CANONICAL_M2_OTB_PLANNED_CENTS,
    CANONICAL_RECEIPT_BUDGET_CENTS,
    CANONICAL_TARGET_UNITS_PER_OPTION,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    activate_item,
    actuals_post_payload,
    adopt_item,
    approve_decision,
    approve_plan,
    cancel_commitment,
    category_plan_payload,
    commit_commitment,
    create_category_plan,
    create_option_plan,
    create_vendor,
    create_vendor_authorization,
    get_commitment,
    get_cycle,
    get_decision,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    get_size_curve_cells,
    month_version,
    open_reforecast_cycle,
    open_season,
    option_plan_payload,
    plan_month_payload,
    post_actuals,
    propose_commitment,
    propose_decision,
    propose_item,
    receipt_commitment_payload,
    replace_size_curve,
    set_clock,
    setup_committed_commitment,
    setup_plan_scenario,
    setup_reference_spine,
    size_curve_payload,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

# A four-cell curve of 2500 basis points each: every cell's raw units are
# identical, so the remainder pass has nothing to reconcile.
FOUR_EVEN_CELLS = [
    {"size_label": "S", "size_sort_order": 1, "pct_bps": 2500},
    {"size_label": "M", "size_sort_order": 2, "pct_bps": 2500},
    {"size_label": "L", "size_sort_order": 3, "pct_bps": 2500},
    {"size_label": "XL", "size_sort_order": 4, "pct_bps": 2500},
]

# A two-cell curve, used where the curve's shape is irrelevant to the claim.
TWO_CELLS = [
    {"size_label": "S", "size_sort_order": 1, "pct_bps": 4000},
    {"size_label": "L", "size_sort_order": 2, "pct_bps": 6000},
]

CARRYOVER_ITEM = {
    "lifecycle_stage": "CARRYOVER",
    "unit_cost_cents": 2600,
    "retail_price_cents": 7900,
    "prior_season_sell_through_bps": 7100,
}


# ─── Vendor capacity: the category open-unit limb ──────

def test_authorization_open_unit_ceiling_is_an_aggregate_limb(api):
    """PRD 3.2: "The second is a **category open-unit** test: the system sums,
    over every commitment of the same vendor whose `commit_status` is
    `PROPOSED` or `COMMITTED` and whose month belongs to a plan in the
    authorization's category, that commitment's `units` less its
    `received_units` and less its `cancelled_units`, and rejects the candidate
    when that sum plus the candidate's `units` exceeds the authorization's
    `max_open_units`. Commitments that are `WITHDRAWN`, `CANCELLED` or `CLOSED`
    release their capacity and contribute nothing to either sum."

    PRD 2.8 (31): "Vendor capacity: the candidate passes both the
    overlapping-ship-window capacity test against `weekly_unit_capacity` and
    the category open-unit test against `max_open_units` —
    `ERR_VENDOR_CAPACITY_EXCEEDED` (409)".

    PRD 3.6: "Because a proposal had never entered the month's committed
    figure, withdrawal touches no month and no plan field whatsoever".

    Design: Corner/validations/authorization_open_unit_ceiling_is_an_aggregate_limb
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
        approve=True,
        vendor_overrides={"min_order_units": 1},
        max_open_units=900,
    )
    month_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    item = propose_item(scenario["option_plan"]["id"], vendor_id, **CARRYOVER_ITEM)

    # Three disjoint one-week windows in February, March and April: the
    # overlapping-window limb sees an empty set every time, so only the
    # category open-unit limb can ever bind.
    first = propose_commitment(
        month_id, item["id"], vendor_id, units=500, unit_cost_cents=2600,
        ship_window_start="2027-02-01T00:00:00Z",
        ship_window_end="2027-02-08T00:00:00Z",
    )
    assert first["units"] == 500
    second = propose_commitment(
        month_id, item["id"], vendor_id, units=400, unit_cost_cents=2600,
        ship_window_start="2027-03-01T00:00:00Z",
        ship_window_end="2027-03-08T00:00:00Z",
    )
    # 500 + 400 lands exactly on the ceiling of 900, and the rule rejects only
    # what exceeds it.
    assert second["units"] == 400
    assert second["commit_status"] == "PROPOSED"

    pinned_version = month_version(month_id)
    over = api.create_receipt_commitment(
        receipt_commitment_payload(
            month_id, item["id"], vendor_id, pinned_version,
            units=1, unit_cost_cents=2600,
            ship_window_start="2027-04-01T00:00:00Z",
            ship_window_end="2027-04-08T00:00:00Z",
        ),
        BUYER_HEADERS,
    )
    # 900 + 1 > 900: a single unit over the aggregate, with the weekly limb
    # carrying a load of zero against a capacity of 12000.
    validate_error(over, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)

    withdrawn = cancel_commitment(first["id"], "release units back to the authorization")
    assert withdrawn["commit_status"] == "WITHDRAWN"
    # Withdrawal touches no month field, so the version captured before the
    # rejected attempt is still the current one.
    assert month_version(month_id) == pinned_version

    retry = validate_success(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, item["id"], vendor_id, pinned_version,
                units=1, unit_cost_cents=2600,
                ship_window_start="2027-04-01T00:00:00Z",
                ship_window_end="2027-04-08T00:00:00Z",
            ),
            BUYER_HEADERS,
        ),
        201,
    )
    # The byte-identical retry succeeds at 400 + 1 <= 900, which attributes the
    # earlier rejection to the aggregate rather than to the payload.
    assert retry["units"] == 1
    assert retry["commit_status"] == "PROPOSED"

    month = get_month(month_id)
    # The ceiling was enforced on PROPOSED units alone: nothing was committed.
    assert month["otb_committed_cents"] == 0
    assert month["otb_open_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS


# ─── Restricted posture: the lifecycle-stage conjunct ──

def test_restricted_posture_blocks_new_items_but_not_carryover(api):
    """PRD 2.8 (17): "When the governing plan's `otb_posture` is `RESTRICTED`,
    the item's `lifecycle_stage` is not `NEW` —
    `ERR_POSTURE_RESTRICTED_NEW_ITEM` (409)".

    PRD 3.6: "a restricted plan may still flow goods on carryover, core and
    exit options, but it may not open new ones, and an attempt is refused with
    `ERR_POSTURE_RESTRICTED_NEW_ITEM`."

    PRD 3.4: "At 1500 basis points or above the posture is `OPEN`; at 500 or
    above but below 1500 it is `RESTRICTED`; below 500 it is `FROZEN`."

    Design: Corner/validations/restricted_posture_blocks_new_items_only
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
        approve=True,
        vendor_overrides={"min_order_units": 100},
    )
    month_id = scenario["m1"]["id"]
    plan_id = scenario["plan_id"]
    vendor_id = scenario["vendor"]["id"]
    option_plan_id = scenario["option_plan"]["id"]

    carryover = propose_item(option_plan_id, vendor_id, **CARRYOVER_ITEM)
    new_item = propose_item(
        option_plan_id, vendor_id, lifecycle_stage="NEW",
        unit_cost_cents=2600, retail_price_cents=7900,
        prior_season_sell_through_bps=0,
    )

    # 6300 units at 2600 consume 16,380,000 of the month's 18,200,000, leaving
    # an open ratio of exactly 1000 basis points.
    setup_committed_commitment(
        month_id, carryover["id"], vendor_id, units=6300, unit_cost_cents=2600,
        ship_window_start="2027-02-01T00:00:00Z",
        ship_window_end="2027-02-15T00:00:00Z",
    )
    month = get_month(month_id)
    assert month["otb_open_cents"] == 1_820_000
    plan = get_plan(plan_id)
    assert plan["open_ratio_bps"] == 1000
    assert plan["otb_posture"] == "RESTRICTED"

    pinned_version = month["version"]
    refused = api.create_receipt_commitment(
        receipt_commitment_payload(
            month_id, new_item["id"], vendor_id, pinned_version,
            units=200, unit_cost_cents=2600,
            ship_window_start="2027-02-01T00:00:00Z",
            ship_window_end="2027-02-15T00:00:00Z",
        ),
        BUYER_HEADERS,
    )
    # Not ERR_OTB_EXCEEDED: 200 * 2600 = 520,000 fits inside the remaining
    # 1,820,000. Not ERR_OTB_POSTURE_FROZEN either, which fires only on FROZEN.
    validate_error(refused, ApiErrorId.ERR_POSTURE_RESTRICTED_NEW_ITEM)

    accepted = validate_success(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, carryover["id"], vendor_id, pinned_version,
                units=200, unit_cost_cents=2600,
                ship_window_start="2027-02-01T00:00:00Z",
                ship_window_end="2027-02-15T00:00:00Z",
            ),
            BUYER_HEADERS,
        ),
        201,
    )
    # Same units, same cost, same month, same vendor: lifecycle_stage is the
    # only difference between the refused request and this one.
    assert accepted["commit_status"] == "PROPOSED"
    assert accepted["cost_cents"] == 520_000

    rows, meta = validate_paginated(
        api.list_receipt_commitments(
            BUYER_HEADERS,
            params={"plan_month_id": month_id, "commit_status": "PROPOSED"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["assortment_item_id"] == carryover["id"]


# ─── Ship window: inversion outranks lead-time feasibility

def test_lead_time_feasibility_boundary_day(api):
    """PRD 2.8 (34): "`ship_window_start` is no earlier than the logical clock
    plus the vendor's `lead_time_days` — `ERR_LEAD_TIME_INFEASIBLE` (422), on
    `POST /otb/receipt-commitments`."

    PRD 2.8 (33): "`ship_window_end` is strictly after `ship_window_start` —
    `ERR_SHIP_WINDOW_INVERTED` (422), on `POST /otb/receipt-commitments`."

    PRD 2.6: "The clock's startup value is exactly `2026-08-01T00:00:00Z`" —
    and that reading advanced by the vendor's 45 lead-time days is exactly
    2026-09-15.

    Design: Corner/validations/lead_time_feasibility_boundary_day
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
        approve=True,
        vendor_overrides={"min_order_units": 100},
    )
    month_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    assert scenario["vendor"]["lead_time_days"] == 45
    item = propose_item(scenario["option_plan"]["id"], vendor_id, **CARRYOVER_ITEM)

    too_early = api.create_receipt_commitment(
        receipt_commitment_payload(
            month_id, item["id"], vendor_id, month_version(month_id),
            units=100, unit_cost_cents=2600,
            ship_window_start="2026-09-14T00:00:00Z",
            ship_window_end="2026-09-28T00:00:00Z",
        ),
        BUYER_HEADERS,
    )
    # One day short of the lead time.
    validate_error(too_early, ApiErrorId.ERR_LEAD_TIME_INFEASIBLE)

    boundary = validate_success(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, item["id"], vendor_id, month_version(month_id),
                units=100, unit_cost_cents=2600,
                ship_window_start="2026-09-15T00:00:00Z",
                ship_window_end="2026-09-28T00:00:00Z",
            ),
            BUYER_HEADERS,
        ),
        201,
    )
    # The boundary day itself is feasible, because the comparison is "no
    # earlier than" rather than "strictly after".
    assert boundary["ship_window_start"].startswith("2026-09-15")
    assert boundary["commit_status"] == "PROPOSED"

    inverted = api.create_receipt_commitment(
        receipt_commitment_payload(
            month_id, item["id"], vendor_id, month_version(month_id),
            units=100, unit_cost_cents=2600,
            ship_window_start="2026-09-28T00:00:00Z",
            ship_window_end="2026-09-14T00:00:00Z",
        ),
        BUYER_HEADERS,
    )
    # With a start of 2026-09-28 the lead time is amply satisfied, so the
    # higher-priority inversion rule is the only one left to reject the window.
    validate_error(inverted, ApiErrorId.ERR_SHIP_WINDOW_INVERTED)

    rows, meta = validate_paginated(
        api.list_receipt_commitments(BUYER_HEADERS, params={"plan_month_id": month_id})
    )
    # The two rejected creates persisted nothing.
    assert meta["total_count"] == 1
    assert rows[0]["id"] == boundary["id"]


# ─── Four composite uniqueness keys, four error ids ─────

def test_four_uniqueness_keys_map_to_four_distinct_errors(api):
    """PRD 2.8 (22): "A category plan is unique per `category_id`,
    `season_code` and `fiscal_year` — `ERR_DUPLICATE_CATEGORY_PLAN` (409)".

    PRD 2.8 (23): "A plan month is unique per `category_plan_id` and
    `month_index` — `ERR_DUPLICATE_PLAN_MONTH` (409)".

    PRD 2.8 (24): "An option plan is unique per `category_plan_id`,
    `store_cluster_id` and `tier` — `ERR_DUPLICATE_OPTION_PLAN` (409)".

    PRD 2.8 (25): "A weekly actuals post is unique per `plan_month_id` and
    `week_index` — `ERR_DUPLICATE_ACTUALS_WEEK` (409)".

    Design: Corner/validations/four_uniqueness_keys_map_to_four_distinct_errors
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
        approve=True,
        open_season_month_indexes=(1,),
    )
    plan_id = scenario["plan_id"]
    month_id = scenario["m1"]["id"]
    category_id = scenario["category"]["id"]
    cluster_id = scenario["store_cluster"]["id"]
    assert get_month(month_id)["status"] == "IN_SEASON"

    week_one = post_actuals(
        month_id, week_index=1, actual_sales_cents=7_500_000,
        actual_receipts_cents=0, actual_units_received=0,
    )
    assert week_one["week_index"] == 1

    # Key 1: the money fields differ in every respect and still do not make the
    # row unique.
    validate_error(
        api.create_category_plan(
            category_plan_payload(
                category_id, planned_sales_cents=99_000_000,
                planned_margin_bps=5000, planned_turn_x100=300,
            ),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_CATEGORY_PLAN,
    )
    fall_plan = validate_success(
        api.create_category_plan(
            category_plan_payload(
                category_id, season_code="FALL", planned_sales_cents=99_000_000,
                planned_margin_bps=5000, planned_turn_x100=300,
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    # Same category and same fiscal year, legal once season_code differs.
    assert fall_plan["status"] == "DRAFT"

    # Key 2: fiscal_month_label, first_receipt_date and every money field
    # differ, and month_index alone still collides.
    validate_error(
        api.create_plan_month(
            plan_month_payload(
                plan_id, month_index=1, fiscal_month_label="2027-09",
                first_receipt_date="2027-09-05T00:00:00Z",
                bom_inventory_cents=11_000_000, planned_sales_cents=12_000_000,
                planned_markdown_cents=500_000, planned_eom_cents=11_000_000,
            ),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_PLAN_MONTH,
    )

    # Key 3: the same plan and the same cluster collide on tier BETTER and are
    # accepted on tier GOOD.
    validate_error(
        api.create_option_plan(
            option_plan_payload(
                plan_id, cluster_id, tier="BETTER", breadth_target=9,
                depth_units_per_option=4, assumed_unit_cost_cents=2000,
            ),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_OPTION_PLAN,
    )
    good_cell = validate_success(
        api.create_option_plan(
            option_plan_payload(
                plan_id, cluster_id, tier="GOOD", breadth_target=9,
                depth_units_per_option=4, assumed_unit_cost_cents=2000,
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert good_cell["tier"] == "GOOD"

    # Key 4: sales, receipts and units all differ from the accepted week 1.
    validate_error(
        api.create_actuals_post(
            actuals_post_payload(
                month_id, week_index=1, actual_sales_cents=6_000_000,
                actual_receipts_cents=1_000_000, actual_units_received=400,
            ),
            ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_ACTUALS_WEEK,
    )
    week_two = post_actuals(
        month_id, week_index=2, actual_sales_cents=7_500_000,
        actual_receipts_cents=0, actual_units_received=0,
    )
    assert week_two["week_index"] == 2

    rows, meta = validate_paginated(
        api.list_month_actuals_posts(month_id, ADMIN_HEADERS)
    )
    # No rejected duplicate left a row behind and no accepted post was
    # overwritten.
    assert meta["total_count"] == 2
    assert sorted(row["week_index"] for row in rows) == [1, 2]


# ─── The size curve is validated as a whole set ─────────

def test_size_curve_set_level_validation_and_atomic_replacement(api):
    """PRD 2.8 (26): "The submitted `cells` array is non-empty —
    `ERR_SIZE_CURVE_EMPTY` (422), on `PUT /otb/option-plans/{id}/size-curve`."

    PRD 2.8 (27): "The submitted cells' `pct_bps` values sum to exactly 10000,
    and `size_label` and `size_sort_order` are each unique within the submitted
    set — `ERR_SIZE_CURVE_NOT_BALANCED` (422)".

    PRD 2.8: "a request that violates three of them returns the code of the
    lowest-numbered one" — an empty array also sums to 0, and only the
    precedence decides which code comes back.

    PRD 3.3: "it does **not** write the option plan's
    `target_units_per_option`, which stays null for as long as the cell's
    `status` is `OPEN`."

    Design: Corner/validations/size_curve_set_is_validated_and_replaced_atomically
    """
    spine = setup_reference_spine()
    plan = create_category_plan(spine["category"]["id"])
    cell = create_option_plan(
        plan["id"], spine["store_cluster"]["id"], **dict(CANONICAL["option_plan"])
    )
    replace_size_curve(cell["id"], FOUR_EVEN_CELLS)

    baseline = get_size_curve_cells(cell["id"])
    # target_units = round_half_up(6 * 40 * 11500 / 10000) = 276, and every
    # cell's raw_units_x10000 is exactly 690000, so each rounds to 69 and the
    # four sum to 276 with no remainder pass.
    assert [row["size_label"] for row in baseline] == ["S", "M", "L", "XL"]
    assert [row["raw_units_x10000"] for row in baseline] == [690000] * 4
    assert [row["allocated_units"] for row in baseline] == [69, 69, 69, 69]

    # An empty array violates the balance rule too, and still surfaces the
    # emptiness code because that rung sits above it.
    validate_error(
        api.replace_size_curve(cell["id"], {"cells": []}, PLANNER_HEADERS),
        ApiErrorId.ERR_SIZE_CURVE_EMPTY,
    )

    # One basis point short of 10000, with every label and sort order distinct.
    validate_error(
        api.replace_size_curve(
            cell["id"],
            size_curve_payload([
                {"size_label": "S", "size_sort_order": 1, "pct_bps": 2500},
                {"size_label": "M", "size_sort_order": 2, "pct_bps": 2500},
                {"size_label": "L", "size_sort_order": 3, "pct_bps": 2500},
                {"size_label": "XL", "size_sort_order": 4, "pct_bps": 2499},
            ]),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_SIZE_CURVE_NOT_BALANCED,
    )

    # A perfect 10000 and sort orders 1..4, so only the repeated size_label can
    # be the cause — and it reports under the same balance code.
    validate_error(
        api.replace_size_curve(
            cell["id"],
            size_curve_payload([
                {"size_label": "S", "size_sort_order": 1, "pct_bps": 2500},
                {"size_label": "S", "size_sort_order": 2, "pct_bps": 2500},
                {"size_label": "L", "size_sort_order": 3, "pct_bps": 2500},
                {"size_label": "XL", "size_sort_order": 4, "pct_bps": 2500},
            ]),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_SIZE_CURVE_NOT_BALANCED,
    )

    # Again 10000 and four distinct labels, so only the repeated
    # size_sort_order can be the cause: one code, three set defects.
    validate_error(
        api.replace_size_curve(
            cell["id"],
            size_curve_payload([
                {"size_label": "S", "size_sort_order": 1, "pct_bps": 2500},
                {"size_label": "M", "size_sort_order": 1, "pct_bps": 2500},
                {"size_label": "L", "size_sort_order": 3, "pct_bps": 2500},
                {"size_label": "XL", "size_sort_order": 4, "pct_bps": 2500},
            ]),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_SIZE_CURVE_NOT_BALANCED,
    )

    rows, meta = validate_paginated(
        api.list_size_curve_cells(cell["id"], PLANNER_HEADERS)
    )
    # All four rejected replacements were atomic no-ops: the stored set is still
    # the baseline, not a partial write of any rejected array.
    assert meta["total_count"] == 4
    assert [row["size_label"] for row in rows] == ["S", "M", "L", "XL"]
    assert [row["allocated_units"] for row in rows] == [69, 69, 69, 69]

    after = get_option_plan(cell["id"])
    # None of these outcomes can be confused with the slotting cascade.
    assert after["status"] == "OPEN"
    assert after["target_units_per_option"] is None


# ─── Plan scope: two independent conjuncts ─────────────

def test_plan_scope_mismatch_has_two_independent_conjuncts(api):
    """PRD 2.8 (20): "Plan-scope agreement: the option plan behind the
    referenced assortment item and the referenced plan month belong to the same
    category plan, and the body's `vendor_id` equals the item's own `vendor_id`
    — `ERR_PLAN_SCOPE_MISMATCH` (422), on `POST /otb/receipt-commitments`."

    PRD 3.6: "Scope must agree: the cell behind the referenced item and the
    referenced month must belong to the same category plan, and the body's
    `vendor_id` must equal the item's own vendor, or the buy is refused with
    `ERR_PLAN_SCOPE_MISMATCH`."

    Design: Corner/validations/plan_scope_mismatch_has_two_independent_conjuncts
    """
    spine = setup_reference_spine(vendor_overrides={"min_order_units": 100})
    first_vendor_id = spine["vendor"]["id"]
    category_id = spine["category"]["id"]
    cluster_id = spine["store_cluster"]["id"]

    # A second vendor that is AUTHORIZED and holds an ACTIVE authorization for
    # the very same category, so neither vendor rung can mask clause 2.
    second_vendor = create_vendor(
        name="Borealis Knitwear", code="BRLS", lead_time_days=45,
        weekly_unit_capacity=12000, min_order_units=100, cancel_cutoff_days=14,
    )
    assert second_vendor["status"] == "AUTHORIZED"
    second_authorization = create_vendor_authorization(second_vendor["id"], category_id)
    assert second_authorization["status"] == "ACTIVE"

    scenario = setup_plan_scenario(
        spine=spine,
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
    )
    plan_a_id = scenario["plan_id"]
    month_id = scenario["m1"]["id"]
    item_a = propose_item(
        scenario["option_plan"]["id"], first_vendor_id, **CARRYOVER_ITEM
    )
    item_a2 = propose_item(
        scenario["option_plan"]["id"], second_vendor["id"], **CARRYOVER_ITEM
    )
    submit_plan(plan_a_id)
    approve_plan(plan_a_id)

    # A second plan of the SAME category, so the higher-priority
    # category-authorization rung still passes for the out-of-scope item.
    plan_b = create_category_plan(
        category_id, season_code="FALL", planned_sales_cents=120_000_000,
        planned_margin_bps=5500, planned_turn_x100=320,
    )
    cell_b = create_option_plan(
        plan_b["id"], cluster_id, tier="BETTER", breadth_target=10,
        depth_units_per_option=6, assumed_unit_cost_cents=2400,
    )
    item_b = propose_item(cell_b["id"], first_vendor_id, **CARRYOVER_ITEM)

    month = get_month(month_id)
    assert month["status"] == "LOCKED_PLAN"
    assert month["otb_open_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS

    def buy(assortment_item_id, vendor_id):
        return api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, assortment_item_id, vendor_id, month_version(month_id),
                units=100, unit_cost_cents=2600,
                ship_window_start="2026-10-01T00:00:00Z",
                ship_window_end="2026-10-08T00:00:00Z",
            ),
            BUYER_HEADERS,
        )

    # Clause 1 alone: the item hangs off the FALL plan while the month belongs
    # to the SPRING plan. Each candidate costs 260,000, well inside the open
    # balance, so the fiscal rung is satisfied throughout.
    validate_error(buy(item_b["id"], first_vendor_id), ApiErrorId.ERR_PLAN_SCOPE_MISMATCH)

    # Clause 2 alone: the item is in scope for the month, but the body names a
    # different vendor than the item's own.
    validate_error(
        buy(item_a["id"], second_vendor["id"]), ApiErrorId.ERR_PLAN_SCOPE_MISMATCH
    )

    # The control differs from that rejection in exactly one field, vendor_id.
    control = validate_success(buy(item_a["id"], first_vendor_id), 201)
    assert control["commit_status"] == "PROPOSED"

    # The second vendor is perfectly usable once it is quoted against the item
    # that actually names it, which rules out a one-vendor-per-plan rule.
    control_two = validate_success(buy(item_a2["id"], second_vendor["id"]), 201)
    assert control_two["vendor_id"] == second_vendor["id"]
    assert get_item(item_a2["id"])["vendor_id"] == second_vendor["id"]

    rows, meta = validate_paginated(
        api.list_receipt_commitments(BUYER_HEADERS, params={"plan_month_id": month_id})
    )
    # The two mismatched attempts persisted nothing.
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {control["id"], control_two["id"]}


# ─── A refused chase approval unwinds every effect ─────

def test_chase_approval_fails_the_last_check_and_unwinds_every_effect(api):
    """PRD 2.8 (39): "When and only when the decision's `action` is `CHASE`, the
    chase-or-cancel allocation funds at least one unit —
    `ERR_NO_FEASIBLE_RECEIPT_MONTH` (422), on
    `POST /otb/chase-cancel-decisions/{id}/approve`."

    PRD 3.8: "The candidate months are the plan's plan months whose `status` is
    `LOCKED_PLAN` or `IN_SEASON`, whose `otb_open_cents` is strictly greater
    than 0, and whose `first_receipt_date` falls no earlier than the logical
    clock advanced by the vendor's `lead_time_days` — a month that cannot
    physically be shipped into is not a candidate."

    PRD 3.8: "Only when `approved_units` resolves to 0 is the approval itself
    refused, with `ERR_NO_FEASIBLE_RECEIPT_MONTH`."

    Design: Corner/validations/chase_approval_fails_the_last_check_and_unwinds_every_effect
    """
    scenario = setup_plan_scenario(
        size_curve=TWO_CELLS,
        approve=True,
        open_season_month_indexes=(1,),
        vendor_overrides={"min_order_units": 100},
    )
    plan_id = scenario["plan_id"]
    month_one_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    option_plan_id = scenario["option_plan"]["id"]

    item_a = propose_item(option_plan_id, vendor_id, **CARRYOVER_ITEM)
    item_b = propose_item(option_plan_id, vendor_id, **CARRYOVER_ITEM)
    adopt_item(item_a["id"])
    activate_item(item_a["id"])
    adopt_item(item_b["id"])
    activated_b = activate_item(item_b["id"])
    assert activated_b["status"] == "IN_SEASON"
    assert activated_b["planned_units"] == CANONICAL_TARGET_UNITS_PER_OPTION

    cycle = open_reforecast_cycle(plan_id, reason_note="chase the opening weeks")
    assert cycle["status"] == "OPEN"

    # The baseline proves the whole chase machinery is wired: at the startup
    # clock the month's first_receipt_date of 2027-03-05 clears 2026-09-15, the
    # month can fund floor(18,200,000 / 2600) = 7000 units and the vendor's
    # headroom is 12000, so all 500 units are placed.
    decision_a = propose_decision(
        cycle["id"], item_a["id"], action="CHASE", requested_units=500,
        rationale="reorder the opening-week best seller",
    )
    approved_a = approve_decision(decision_a["id"], "funded")
    assert approved_a["status"] == "APPROVED"
    assert approved_a["approved_units"] == 500
    month_after_a = get_month(month_one_id)
    assert month_after_a["otb_committed_cents"] == 1_300_000
    assert month_after_a["otb_open_cents"] == 16_900_000

    decision_b = propose_decision(
        cycle["id"], item_b["id"], action="CHASE", requested_units=500,
        rationale="same chase, later in the round",
    )
    # Proposing into the cycle that had bubbled to DECIDED reopened it.
    assert get_cycle(cycle["id"])["status"] == "OPEN"

    clock = set_clock("2027-03-01T00:00:00Z")
    assert clock["expired_overlay_count"] == 0

    refused = api.approve_chase_cancel_decision(
        decision_b["id"], {"decision_note": "too late in the season"}, DIRECTOR_HEADERS
    )
    # 2027-03-01 advanced by 45 days is 2027-04-15, and neither month 1
    # (2027-03-05) nor month 2 (2027-04-02) reaches it, so the candidate set is
    # empty and the allocation would fund zero units. No earlier rung explains
    # this: the caller is a director other than the proposer, the decision was
    # PROPOSED, the cycle was OPEN, the item was IN_SEASON, and the month could
    # still afford floor(16,900,000 / 2600) = 6500 units against a request of
    # 500 with 12000 of weekly capacity and 40000 open units authorized.
    validate_error(refused, ApiErrorId.ERR_NO_FEASIBLE_RECEIPT_MONTH)

    decision = get_decision(decision_b["id"])
    # Untouched, rather than APPROVED-with-zero.
    assert decision["status"] == "PROPOSED"
    assert decision["approved_units"] is None
    # The bubble-up did not fire, because a PROPOSED decision still remains.
    assert get_cycle(cycle["id"])["status"] == "OPEN"

    item = get_item(item_b["id"])
    # Neither the transition to CHASED nor the planned_units increment survived.
    assert item["status"] == "IN_SEASON"
    assert item["planned_units"] == CANONICAL_TARGET_UNITS_PER_OPTION

    month = get_month(month_one_id)
    # The month's dollars are exactly what the first decision left.
    assert month["otb_committed_cents"] == 1_300_000
    assert month["otb_open_cents"] == 16_900_000

    _rows, meta = validate_paginated(
        api.list_receipt_commitments(
            BUYER_HEADERS, params={"assortment_item_id": item_b["id"]}
        )
    )
    assert meta["total_count"] == 0


# ─── The plan-level roll-up is a pure read ─────────────

def test_otb_summary_rolls_every_month_into_one_picture(api):
    """PRD 3.7: "Two computed reads expose this arithmetic without persisting
    anything."

    PRD 3.7: "The plan-level summary likewise accepts an optional `basis` and
    rolls the plan's months whose `status` is `LOCKED_PLAN` or `IN_SEASON` —
    the same month set the posture computation uses — into `category_plan_id`,
    the `basis` evaluated, `receipt_budget_cents`, the summed
    `otb_planned_cents`, `otb_committed_cents`, `otb_received_cents` and
    `otb_open_cents`, plus `open_ratio_bps`, `otb_posture`, `variance_status`,
    `sales_variance_bps` and `month_count`, the number of months that
    contributed."

    Design: Corner/endpoints/otb_summary_rolls_every_month_into_one_picture
    """
    scenario = setup_plan_scenario(
        size_curve=TWO_CELLS,
        approve=True,
        vendor_overrides={"min_order_units": 100},
    )
    plan_id = scenario["plan_id"]
    month_one_id = scenario["m1"]["id"]
    month_two_id = scenario["m2"]["id"]
    vendor_id = scenario["vendor"]["id"]

    item = propose_item(scenario["option_plan"]["id"], vendor_id, **CARRYOVER_ITEM)
    commitment = commit_commitment(
        propose_commitment(
            month_one_id, item["id"], vendor_id, units=400, unit_cost_cents=2600,
            ship_window_start="2026-10-01T00:00:00Z",
            ship_window_end="2026-10-15T00:00:00Z",
        )["id"]
    )
    assert commitment["open_cost_cents"] == 1_040_000

    plan = get_plan(plan_id)
    assert plan["receipt_budget_cents"] == CANONICAL_RECEIPT_BUDGET_CENTS
    assert get_month(month_two_id)["otb_planned_cents"] == CANONICAL_M2_OTB_PLANNED_CENTS

    plan_version_before = plan["version"]
    month_one_version_before = month_version(month_one_id)
    month_two_version_before = month_version(month_two_id)

    summary = validate_success(api.get_otb_summary(plan_id, PLANNER_HEADERS))
    assert summary["category_plan_id"] == plan_id
    # Both months are LOCKED_PLAN with no weekly actuals, so the default basis
    # is the planned one.
    assert summary["basis"] == "PLANNED_BASIS"
    assert summary["receipt_budget_cents"] == CANONICAL_RECEIPT_BUDGET_CENTS
    # 18,200,000 from month 1 plus 21,970,000 from month 2.
    assert summary["otb_planned_cents"] == 40_170_000
    assert summary["otb_committed_cents"] == 1_040_000
    assert summary["otb_received_cents"] == 0
    assert summary["otb_open_cents"] == 39_130_000
    # The conservation identity holds exactly on the roll-up.
    assert (
        summary["otb_open_cents"]
        + summary["otb_committed_cents"]
        + summary["otb_received_cents"]
        == summary["otb_planned_cents"]
    )
    # round_half_up(10000 * 39,130,000 / 40,170,000) = 9741, agreeing to the
    # basis point with the figure the commit cascade persisted on the plan.
    assert summary["open_ratio_bps"] == 9741
    assert summary["open_ratio_bps"] == plan["open_ratio_bps"]
    assert summary["otb_posture"] == "OPEN"
    assert summary["variance_status"] == "ON_PLAN"
    assert summary["sales_variance_bps"] == 0
    assert summary["month_count"] == 2

    # The read persisted nothing, so calling it twice returns identical numbers.
    again = validate_success(api.get_otb_summary(plan_id, PLANNER_HEADERS))
    rolled_up = (
        "category_plan_id", "basis", "receipt_budget_cents", "otb_planned_cents",
        "otb_committed_cents", "otb_received_cents", "otb_open_cents",
        "open_ratio_bps", "otb_posture", "variance_status", "sales_variance_bps",
        "month_count",
    )
    assert {key: again[key] for key in rolled_up} == {
        key: summary[key] for key in rolled_up
    }
    assert get_plan(plan_id)["version"] == plan_version_before
    assert month_version(month_one_id) == month_one_version_before
    assert month_version(month_two_id) == month_two_version_before


# ─── The month ledger serves either basis on demand ────

def test_otb_ledger_returns_either_basis_without_persisting(api):
    """PRD 3.7: "Passing `PLANNED_BASIS` or `PROJECTED_BASIS` in `basis` returns
    that variant on demand for the same month; omitting `basis` evaluates the
    month's own `active_basis`."

    PRD 3.7: "Two computed reads expose this arithmetic without persisting
    anything."

    PRD 3.4 on the planned variant: "The authored plan is taken at face value
    here and no week of actuals is read." The planned-basis read therefore
    re-derives the reserve from the authored month and reproduces the 700,000 the
    month carried at approval, while the projected-basis read rebuilds the month
    from the posted weeks.

    Design: Corner/endpoints/otb_ledger_returns_either_basis_without_persisting
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
        approve=True,
    )
    month_id = scenario["m1"]["id"]

    at_approval = get_month(month_id)
    # At approval the month is PLANNED_BASIS with a provisional sell-through of
    # round_half_up(10000 * 13,500,000 / 20,000,000) = 6750 and a rate of 350.
    assert at_approval["markdown_reserve_cents"] == 700_000
    assert at_approval["otb_planned_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS

    open_season(month_id)
    post_actuals(
        month_id, week_index=1, actual_sales_cents=7_000_000,
        actual_receipts_cents=5_000_000, actual_units_received=1900,
    )
    second_week = post_actuals(
        month_id, week_index=2, actual_sales_cents=8_000_000,
        actual_receipts_cents=4_000_000, actual_units_received=1500,
    )
    assert second_week["week_index"] == 2

    row = get_month(month_id)
    # The second post re-derived the reserve on projected figures.
    assert row["active_basis"] == "PROJECTED_BASIS"
    assert row["provisional_sell_through_bps"] == 6067
    assert row["markdown_reserve_cents"] == 1_335_000
    assert row["otb_planned_cents"] == 16_585_000
    row_version = row["version"]

    projected = validate_success(
        api.get_otb_ledger(month_id, PLANNER_HEADERS, params={"basis": "PROJECTED_BASIS"})
    )
    assert projected["plan_month_id"] == month_id
    assert projected["basis"] == "PROJECTED_BASIS"
    assert projected["weeks_posted"] == 2
    # Projected sales run at 7,000,000 + 8,000,000 + 15,000,000 / 2 * 2 =
    # 30,000,000, and 4500 basis points of that is 13,500,000.
    assert projected["projected_sales_cost_cents"] == 13_500_000
    # 20,000,000 + 9,000,000 of receipts less round_half_up(15,000,000 * 4500 /
    # 10000) = 6,750,000 of cost of sales.
    assert projected["projected_bom_cents"] == 22_250_000
    # round_half_up(10000 * 13,500,000 / 22,250,000) = 6067, and 6067 < 6500 so
    # the rate is 600.
    assert projected["provisional_sell_through_bps"] == 6067
    assert projected["reserve_rate_bps"] == 600
    assert projected["markdown_reserve_cents"] == 1_335_000
    # 22,000,000 + 13,500,000 + 2,000,000 + 1,335,000 - 22,250,000, with no
    # commitments to subtract.
    assert projected["otb_planned_cents"] == 16_585_000
    assert projected["otb_open_cents"] == 16_585_000

    planned = validate_success(
        api.get_otb_ledger(month_id, PLANNER_HEADERS, params={"basis": "PLANNED_BASIS"})
    )
    assert planned["basis"] == "PLANNED_BASIS"
    assert planned["bom_inventory_cents"] == 20_000_000
    assert planned["planned_sales_cost_cents"] == 13_500_000
    # The planned variant takes the authored month at face value and reads no
    # week of actuals, so its reserve rewinds to the 700,000 the month carried at
    # approval: 13,500,000 of cost of sales over a 20,000,000 denominator is
    # 6750 bps, the 350 bps band, and 350 bps of 20,000,000 is 700,000.
    assert planned["provisional_sell_through_bps"] == 6750
    assert planned["reserve_rate_bps"] == 350
    assert planned["markdown_reserve_cents"] == 700_000
    assert planned["markdown_reserve_cents"] == at_approval["markdown_reserve_cents"]
    # 22,000,000 + 13,500,000 + 2,000,000 + 700,000 - 20,000,000.
    assert planned["otb_planned_cents"] == 18_200_000
    assert planned["otb_open_cents"] == 18_200_000
    # The committed bucket is basis-independent.
    assert planned["otb_committed_cents"] == 0

    # The projected run rate reproduces the authored sales exactly, so the two
    # bases diverge only through the rebuilt opening inventory and the reserve
    # that the rebuilt denominator selects: 2,250,000 of extra BOM less the
    # 635,000 of extra reserve leaves 1,615,000.
    assert planned["otb_planned_cents"] - projected["otb_planned_cents"] == 1_615_000
    assert (
        projected["projected_bom_cents"] - planned["bom_inventory_cents"] == 2_250_000
    )
    assert (
        projected["markdown_reserve_cents"] - planned["markdown_reserve_cents"]
        == 635_000
    )

    after = get_month(month_id)
    # Two ledger reads on two different bases persisted nothing.
    assert after["active_basis"] == "PROJECTED_BASIS"
    assert after["otb_planned_cents"] == 16_585_000
    assert after["markdown_reserve_cents"] == 1_335_000
    assert after["version"] == row_version


# ─── A HOLD approval allocates nothing ─────────────────

def test_hold_decision_approves_zero_units_and_moves_nothing(api):
    """PRD 3.8: a decision "states `requested_units` of at least 0 — which must
    be exactly 0 when the action is `HOLD`".

    PRD 3.8: "A successful approval, on every one of the three branches below,
    advances the decision `PROPOSED → APPROVED` and writes the `approved_units`
    that branch computed — including the `HOLD` branch, whose `approved_units`
    is 0 and which is nonetheless approved rather than refused."

    PRD 3.8: "A `HOLD` decision allocates nothing: `approved_units` is 0, no
    commitment is created and none is reduced, and the item's `status` is
    unchanged."

    PRD 3.8: "As soon as an approval or a rejection leaves no decision of the
    cycle still `PROPOSED`, and provided the cycle holds at least one decision
    at all, the cycle bubbles `OPEN → DECIDED`".

    Design: Corner/endpoints/hold_decision_approves_zero_units_and_moves_nothing
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
        approve=True,
        open_season_month_indexes=(1,),
        vendor_overrides={"min_order_units": 100},
    )
    month_id = scenario["m1"]["id"]
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"], **CARRYOVER_ITEM
    )
    adopted = adopt_item(item["id"])
    assert adopted["planned_units"] == CANONICAL_TARGET_UNITS_PER_OPTION
    activate_item(item["id"])

    cycle = open_reforecast_cycle(
        scenario["plan_id"], reason_note="hold the decision for a week"
    )
    assert cycle["status"] == "OPEN"
    decision = propose_decision(
        cycle["id"], item["id"], action="HOLD", requested_units=0,
        rationale="wait one more week of selling",
    )
    assert decision["action"] == "HOLD"
    assert decision["requested_units"] == 0
    assert decision["approved_units"] is None

    before = get_month(month_id)
    assert before["otb_open_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS
    assert before["otb_committed_cents"] == 0

    approved = approve_decision(decision["id"], "hold confirmed")
    # The approval succeeds and records a zero allocation: the feasibility rung
    # is scoped to CHASE, so a HOLD is exempt from it.
    assert approved["status"] == "APPROVED"
    assert approved["approved_units"] == 0

    held = get_item(item["id"])
    # Neither the chase branch nor the cancel branch fired: both are gated on an
    # allocation above zero.
    assert held["status"] == "IN_SEASON"
    assert held["planned_units"] == CANONICAL_TARGET_UNITS_PER_OPTION

    # The bubble-up depends only on no PROPOSED decision remaining, not on any
    # units having moved.
    assert get_cycle(cycle["id"])["status"] == "DECIDED"

    after = get_month(month_id)
    assert after["otb_open_cents"] == before["otb_open_cents"]
    assert after["otb_committed_cents"] == 0
    assert after["otb_received_cents"] == 0
    # The approval touched no plan month, so no month version advanced.
    assert after["version"] == before["version"]

    _rows, meta = validate_paginated(
        api.list_receipt_commitments(BUYER_HEADERS, params={"plan_month_id": month_id})
    )
    assert meta["total_count"] == 0


# ─── The size-curve PUT replaces the whole set ─────────

def test_size_curve_put_replaces_the_whole_set(api):
    """PRD 3.3: "the size-curve replacement operation takes a `cells` array,
    deletes every existing size-curve row of that option plan, and persists the
    submitted set in its place, advancing the option plan's own version by 1."

    PRD 3.3: "The rule computes, first, the cell's total unit target for one
    option across the whole cluster: the option plan's `depth_units_per_option`
    multiplied by the cluster's `store_count`, multiplied by the cluster's
    `sales_index_bps` and divided by ten thousand, with the result rounded half
    up to a whole unit."

    PRD 2.3: "the size-curve-cell list of an option plan is ordered by
    `size_sort_order` ascending".

    Design: Corner/endpoints/size_curve_put_replaces_the_whole_set
    """
    spine = setup_reference_spine()
    plan = create_category_plan(spine["category"]["id"])
    cell = create_option_plan(
        plan["id"], spine["store_cluster"]["id"], **dict(CANONICAL["option_plan"])
    )
    replace_size_curve(cell["id"], FOUR_EVEN_CELLS)
    baseline = get_size_curve_cells(cell["id"])
    assert [row["size_label"] for row in baseline] == ["S", "M", "L", "XL"]
    assert [row["allocated_units"] for row in baseline] == [69, 69, 69, 69]
    version_before = get_option_plan(cell["id"])["version"]

    replace_size_curve(cell["id"], [
        {"size_label": "S", "size_sort_order": 1, "pct_bps": 3000},
        {"size_label": "M", "size_sort_order": 2, "pct_bps": 4000},
        {"size_label": "L", "size_sort_order": 3, "pct_bps": 3000},
    ])

    rows, meta = validate_paginated(
        api.list_size_curve_cells(cell["id"], PLANNER_HEADERS)
    )
    # Three cells, not seven and not four: the dropped XL row is gone rather
    # than orphaned.
    assert meta["total_count"] == 3
    assert [row["size_label"] for row in rows] == ["S", "M", "L"]
    # 276 * 3000 = 828000 ten-thousandths, and round_half_up(828000 / 10000) is
    # 83; 276 * 4000 = 1104000 rounds to 110.
    assert [row["raw_units_x10000"] for row in rows] == [828000, 1104000, 828000]
    assert [row["allocated_units"] for row in rows] == [83, 110, 83]
    # S and L keep their labels but not their numbers, which proves the
    # surviving rows were recomputed rather than carried over.
    assert baseline[0]["allocated_units"] == 69 and rows[0]["allocated_units"] == 83
    # 83 + 110 + 83 == 276 == the cell's unit target, so the delta is 0 and no
    # remainder pass runs; the total is invariant across the replacement because
    # the target never depends on pct_bps.
    assert sum(row["allocated_units"] for row in rows) == 276
    assert sum(row["allocated_units"] for row in baseline) == 276

    after = get_option_plan(cell["id"])
    assert after["version"] == version_before + 1


# ─── One cancel endpoint, two different meanings ───────

def test_cancel_means_two_different_things_by_commit_status(api):
    """PRD 3.6: "A commitment that is still `PROPOSED` is **withdrawn**: it
    advances `PROPOSED → WITHDRAWN`, its `fulfillment_status` moves to `VOID`,
    its `cancelled_units` is set equal to its `units` and its `open_cost_cents`
    to 0." — and "Because a proposal had never entered the month's committed
    figure, withdrawal touches no month and no plan field whatsoever".

    PRD 3.6: "It is permitted only while the logical clock is at or before the
    commitment's `ship_window_start` less the vendor's `cancel_cutoff_days`; a
    later attempt is refused with `ERR_CANCEL_CUTOFF_PASSED`."

    PRD 2.8 (35): "The cancellation cutoff has not passed —
    `ERR_CANCEL_CUTOFF_PASSED` (409), on
    `POST /otb/receipt-commitments/{id}/cancel` when the commitment's
    `commit_status` is `COMMITTED`."

    Design: Corner/endpoints/cancel_means_two_different_things_by_commit_status
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(CANONICAL["month_1"])],
        size_curve=TWO_CELLS,
        approve=True,
        vendor_overrides={"min_order_units": 100, "cancel_cutoff_days": 14},
    )
    month_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    item = propose_item(scenario["option_plan"]["id"], vendor_id, **CARRYOVER_ITEM)

    twin_kwargs = dict(
        units=400, unit_cost_cents=2600,
        ship_window_start="2027-02-01T00:00:00Z",
        ship_window_end="2027-02-15T00:00:00Z",
    )
    to_commit = propose_commitment(month_id, item["id"], vendor_id, **twin_kwargs)
    to_withdraw = propose_commitment(month_id, item["id"], vendor_id, **twin_kwargs)
    assert to_withdraw["open_cost_cents"] == 1_040_000

    committed = commit_commitment(to_commit["id"])
    assert committed["commit_status"] == "COMMITTED"

    midpoint = get_month(month_id)
    # The committed row consumed 400 * 2600 of the month's 18,200,000, and the
    # PROPOSED twin consumed nothing even though it carries the same open cost.
    assert midpoint["otb_committed_cents"] == 1_040_000
    assert midpoint["otb_open_cents"] == 17_160_000
    midpoint_version = midpoint["version"]

    # 2027-02-01 less the vendor's 14 cancel-cutoff days is 2027-01-18, so the
    # clock now stands one day past the cutoff.
    set_clock("2027-01-19T00:00:00Z")

    withdrawn = cancel_commitment(to_withdraw["id"], "buy no longer needed")
    # The PROPOSED branch is accepted at a clock reading past the cutoff,
    # because the cutoff rung is scoped to COMMITTED rows.
    assert withdrawn["commit_status"] == "WITHDRAWN"
    assert withdrawn["fulfillment_status"] == "VOID"
    assert withdrawn["cancelled_units"] == 400
    assert withdrawn["open_cost_cents"] == 0

    after_withdrawal = get_month(month_id)
    # Withdrawing a PROPOSED row touches no plan month field and bumps no plan
    # month version.
    assert after_withdrawal["otb_open_cents"] == 17_160_000
    assert after_withdrawal["otb_committed_cents"] == 1_040_000
    assert after_withdrawal["version"] == midpoint_version

    refused = api.cancel_receipt_commitment(
        to_commit["id"], {"cancel_reason": "same reason, different commit_status"},
        BUYER_HEADERS,
    )
    # Identical units, unit cost, ship window, item and vendor: only
    # commit_status differs between the two rows.
    validate_error(refused, ApiErrorId.ERR_CANCEL_CUTOFF_PASSED)

    still_committed = get_commitment(to_commit["id"])
    # WITHDRAWN and CANCELLED are distinct terminal values, and only the latter
    # is preceded by the cutoff check; the refused attempt released nothing.
    assert still_committed["commit_status"] == "COMMITTED"
    assert still_committed["open_cost_cents"] == 1_040_000
    assert still_committed["cancelled_units"] == 0

    final = get_month(month_id)
    assert final["otb_committed_cents"] == 1_040_000
    assert final["otb_open_cents"] == 17_160_000
    assert final["version"] == midpoint_version
