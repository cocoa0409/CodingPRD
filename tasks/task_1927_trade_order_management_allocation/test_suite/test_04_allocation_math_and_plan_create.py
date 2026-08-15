"""Average-price variants, allocation-method math, fairness gate, SoD, OCC (PRD §2.7, §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_plan,
    build_user_headers,
    create_plan_for_block,
    get_block,
    get_plan,
    list_allocations_for_plan,
    post_plan,
    propose_plan,
    record_fill,
    setup_filled_block,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["trader_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _alloc_by_order(plan_id):
    """Map order_id -> alloc_qty over the plan's lines."""
    return {line["order_id"]: line["alloc_qty"] for line in list_allocations_for_plan(plan_id)}


class TestAveragePriceVariants:
    def test_final_batch_average_frozen_per_plan(self, api):
        """PRD §3.7: "The proposal sets `covered_to_seq` to the greatest `fill_seq` present, computes `batch_qty` as the total quantity of the fills strictly inside the window from `covered_from_seq` exclusive to `covered_to_seq` inclusive, and freezes `batch_avg_price_cents` as the volume-weighted average over exactly those fills — the same weighted-average shape as §3.6, exact-decimal division rounded half-up to whole cents, but over the covered batch only."

        Design: Difficulty/dual_variant_calc/avg_price_provisional_vs_final_batch
        """
        scenario = setup_filled_block(
            order_qtys=(100, 300), fills=((100, 1000), (200, 2000))
        )
        block_id = scenario["block"]["id"]

        plan1 = create_plan_for_block(block_id, method="PRO_RATA")
        proposed1 = propose_plan(plan1["id"])
        assert proposed1["batch_qty"] == 300, f"Batch covers fills 1-2: 100+200, got {proposed1['batch_qty']}"
        # round_half_up((100*1000 + 200*2000) / 300) = round_half_up(1666.66...) = 1667
        assert proposed1["batch_avg_price_cents"] == 1667, (
            f"FINAL_BATCH average over fills 1-2 must be 1667, got {proposed1['batch_avg_price_cents']}"
        )
        approve_plan(plan1["id"])
        post_plan(plan1["id"])

        record_fill(block_id, 100, 2200, executed_at="2026-08-01T09:10:00Z")

        plan2 = create_plan_for_block(block_id, method="PRO_RATA")
        assert plan2["covered_from_seq"] == 2, (
            f"Second plan's lower bound is the watermark 2, got {plan2['covered_from_seq']}"
        )
        proposed2 = propose_plan(plan2["id"])
        assert proposed2["batch_qty"] == 100, f"Batch covers fill 3 only, got {proposed2['batch_qty']}"
        assert proposed2["batch_avg_price_cents"] == 2200, (
            f"FINAL_BATCH average over fill 3 alone must be 2200, got {proposed2['batch_avg_price_cents']}"
        )

    def test_provisional_block_average_runs_over_all_fills(self, api):
        """PRD §3.6: "The block's `filled_qty` becomes the sum of all fill quantities, and its `avg_fill_price_cents` becomes the volume-weighted average price over all fills recorded so far: each fill's quantity multiplied by its price, the products summed, the sum divided by the total filled quantity in exact decimal arithmetic, and the result rounded half-up to whole cents."
        PRD §3.7: "For a block with fills outside the batch, this final-batch average deliberately differs from the block's running average."

        Design: Difficulty/dual_variant_calc/avg_price_provisional_vs_final_batch
        """
        scenario = setup_filled_block(
            order_qtys=(100, 300), fills=((100, 1000), (200, 2000))
        )
        block_id = scenario["block"]["id"]

        plan1 = create_plan_for_block(block_id, method="PRO_RATA")
        proposed1 = propose_plan(plan1["id"])
        approve_plan(plan1["id"])
        post_plan(plan1["id"])
        record_fill(block_id, 100, 2200, executed_at="2026-08-01T09:10:00Z")
        plan2 = create_plan_for_block(block_id, method="PRO_RATA")
        proposed2 = propose_plan(plan2["id"])

        block = get_block(block_id)
        # (100*1000 + 200*2000 + 100*2200) / 400 = 720000 / 400 = 1800
        assert block["avg_fill_price_cents"] == 1800, (
            f"PROVISIONAL average over all fills must be 1800, got {block['avg_fill_price_cents']}"
        )
        assert block["filled_qty"] == 400
        assert block["avg_fill_price_cents"] != proposed1["batch_avg_price_cents"]
        assert block["avg_fill_price_cents"] != proposed2["batch_avg_price_cents"]
        assert proposed1["batch_avg_price_cents"] != proposed2["batch_avg_price_cents"]


class TestAllocationMethodVariants:
    def test_pro_rata_split_tracks_order_quantities(self, api):
        """PRD §3.7: "Under PRO_RATA, each member's ideal share is the batch quantity multiplied by the member's `order_qty` and divided by the total of all members' quantities, kept as an exact decimal."
        PRD §3.7: "Every member's base allocation is its ideal rounded down to a whole unit; the leftover units — the batch quantity minus the sum of the bases — are dealt out one unit at a time to members ranked by fractional part descending, ties broken first by larger `order_qty` and then by earlier `created_at`."

        Design: Difficulty/dual_variant_calc/allocation_method_pro_rata_vs_equal_split
        """
        scenario = setup_filled_block(order_qtys=(100, 300), fills=((400, 1500),))
        o1, o2 = scenario["orders"]
        plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
        proposed = propose_plan(plan["id"])

        by_order = _alloc_by_order(plan["id"])
        assert by_order[o1["id"]] == 100, f"PRO_RATA ideal 400*100/400=100, got {by_order[o1['id']]}"
        assert by_order[o2["id"]] == 300, f"PRO_RATA ideal 400*300/400=300, got {by_order[o2['id']]}"
        assert proposed["max_deviation_bp"] == 0, (
            f"Exact pro-rata split has zero deviation, got {proposed['max_deviation_bp']}"
        )

    def test_equal_split_halves_regardless_of_order_quantities(self, api):
        """PRD §3.7: "Under EQUAL_SPLIT, each member's ideal is the batch quantity divided by the member count, also exact — so unequal member quantities yield different per-account results under the two methods over identical fills."
        PRD §3.7: "Fairness is measured against the PRO_RATA ideal always — even when the plan's method is EQUAL_SPLIT."
        PRD §3.7: "The plan's `max_deviation_bp` is the largest per-member deviation."

        Design: Difficulty/dual_variant_calc/allocation_method_pro_rata_vs_equal_split
        """
        scenario = setup_filled_block(order_qtys=(100, 300), fills=((400, 1500),))
        o1, o2 = scenario["orders"]
        plan = create_plan_for_block(scenario["block"]["id"], method="EQUAL_SPLIT")
        proposed = propose_plan(plan["id"])

        by_order = _alloc_by_order(plan["id"])
        assert by_order[o1["id"]] == 200, f"EQUAL_SPLIT ideal 400/2=200, got {by_order[o1['id']]}"
        assert by_order[o2["id"]] == 200, f"EQUAL_SPLIT ideal 400/2=200, got {by_order[o2['id']]}"
        # |200 - 100| / 100 * 10000 = 10000 against the PRO_RATA ideal of the small order
        assert proposed["max_deviation_bp"] == 10000, (
            f"Max deviation against pro-rata ideals must be 10000, got {proposed['max_deviation_bp']}"
        )


class TestRemainderDistribution:
    def test_largest_remainder_units_break_ties_by_created_at(self, api):
        """PRD §3.7: "The split is deterministic. Member orders are the block's orders still `BLOCKED` at propose time, ranked by `created_at` ascending."
        PRD §3.7: "Every member's base allocation is its ideal rounded down to a whole unit; the leftover units — the batch quantity minus the sum of the bases — are dealt out one unit at a time to members ranked by fractional part descending, ties broken first by larger `order_qty` and then by earlier `created_at`."
        PRD §3.7: "A member's final `alloc_qty` is its base plus one if it received a leftover unit, and each line's `alloc_price_cents` is the plan's frozen `batch_avg_price_cents`."

        Design: Difficulty/combinatorial_formula/remainder_distribution_largest_fraction
        """
        scenario = setup_filled_block(order_qtys=(4, 4, 2), fills=((7, 1000),))
        o1, o2, o3 = scenario["orders"]
        plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
        proposed = propose_plan(plan["id"])

        # Ideals 2.8 / 2.8 / 1.4 -> bases 2 / 2 / 1; two leftover units go to the two
        # 0.8-fraction members; the fraction and quantity tie breaks by created_at.
        by_order = _alloc_by_order(plan["id"])
        assert by_order[o1["id"]] == 3, f"o1 (created first of the tied 4s) gets a unit, got {by_order[o1['id']]}"
        assert by_order[o2["id"]] == 3, f"o2 gets the other unit, got {by_order[o2['id']]}"
        assert by_order[o3["id"]] == 1, f"o3 keeps its base, got {by_order[o3['id']]}"
        assert sum(by_order.values()) == 7 == proposed["batch_qty"]

    def test_fairness_deviation_is_max_over_members(self, api):
        """PRD §3.7: "Per member: if the pro-rata ideal is zero, the deviation is zero when the member received nothing and 99999 basis points — the deviation cap — when it received something; otherwise the deviation is the absolute gap between the member's `alloc_qty` and its pro-rata ideal, divided by that ideal, scaled by ten thousand, and rounded half-up to integer basis points."
        PRD §3.7: "The plan's `max_deviation_bp` is the largest per-member deviation."

        Design: Difficulty/combinatorial_formula/remainder_distribution_largest_fraction
        """
        scenario = setup_filled_block(order_qtys=(4, 4, 2), fills=((7, 1000),))
        plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
        proposed = propose_plan(plan["id"])

        # Deviations: round_half_up(0.2/2.8*10000) = 714 (twice);
        # round_half_up(0.4/1.4*10000) = 2857 -> max is 2857.
        assert proposed["max_deviation_bp"] == 2857, (
            f"Max deviation must be 2857, got {proposed['max_deviation_bp']}"
        )


def test_unfair_allocation_gate_blocks_approve(api):
    """PRD §3.7: "Approval belongs to `ComplianceOfficer`, with two gates evaluated segregation of duties first: the approver's `X-User-ID` must differ from the plan's `created_by_user_id` — the trader who built the plan cannot approve it — or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) fires; and `max_deviation_bp` must be at most 200 basis points, two percent of the pro-rata ideal, or `ERR_UNFAIR_ALLOCATION` (HTTP 422) fires."

    Design: Corner/validations/unfair_allocation_gate_at_approve
    """
    scenario = setup_filled_block(order_qtys=(100, 300), fills=((400, 1500),))
    plan = create_plan_for_block(scenario["block"]["id"], method="EQUAL_SPLIT")
    proposed = propose_plan(plan["id"])
    assert proposed["max_deviation_bp"] == 10000

    res = api.approve_plan(plan["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_UNFAIR_ALLOCATION)
    assert get_plan(plan["id"])["status"] == "PROPOSED", (
        "A rejected approval must leave the plan PROPOSED"
    )


def test_same_user_cannot_create_and_approve_plan(api):
    """PRD §3.7: "Approval belongs to `ComplianceOfficer`, with two gates evaluated segregation of duties first: the approver's `X-User-ID` must differ from the plan's `created_by_user_id` — the trader who built the plan cannot approve it — or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) fires; and `max_deviation_bp` must be at most 200 basis points, two percent of the pro-rata ideal, or `ERR_UNFAIR_ALLOCATION` (HTTP 422) fires."
    PRD §2.8: "5. Segregation of duties at plan approval (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."

    Design: Corner/validations/sod_dual_hat_approve_rejected
    """
    scenario = setup_filled_block(order_qtys=(100,), fills=((100, 1000),))
    plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA", creator_user_id="user-7")
    propose_plan(plan["id"], trader_user_id="user-7")

    dual_hat = build_user_headers("user-7", "ComplianceOfficer")
    res = api.approve_plan(plan["id"], dual_hat)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_plan(plan["id"])["status"] == "PROPOSED"


def test_plan_create_stale_block_version_rejected(api):
    """PRD §2.7: "If that value does not match the block's current `version` — because another writer has created a plan for the same block (which legitimately supersedes the prior non-terminal plan), recorded a fill (changing the fill set the plan would cover), or attached or detached an order — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "Crucially, creation supersedes any existing plan of the same block still in `DRAFT`, `PROPOSED`, or `APPROVED`: the older plan becomes `SUPERSEDED`, any PROPOSED allocation lines it held are deleted, and `PLAN_SUPERSEDED` is written."
    PRD §2.4: "Version increments attach to the resource being mutated, and certain operations deliberately bump a related resource's version as well: attaching or detaching an order increments the block's `version`; creating an allocation plan increments the block's `version`; posting a plan increments both the plan's and the block's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_plan_create_stale_version
    """
    scenario = setup_filled_block(order_qtys=(100,), fills=((100, 1000),))
    block_id = scenario["block"]["id"]

    observed_version = get_block(block_id)["version"]
    plan1 = validate_success(
        api.create_allocation_plan(
            block_id,
            {"method": "PRO_RATA", "expected_block_version": observed_version},
            build_user_headers("trader-1", "Trader"),
        ),
        201,
    )
    after_first = get_block(block_id)["version"]
    assert after_first == observed_version + 1, (
        f"Plan create increments block version by exactly one, got {observed_version} -> {after_first}"
    )

    stale = api.create_allocation_plan(
        block_id,
        {"method": "EQUAL_SPLIT", "expected_block_version": observed_version},
        build_user_headers("trader-2", "Trader"),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    fresh = validate_success(
        api.create_allocation_plan(
            block_id,
            {"method": "EQUAL_SPLIT", "expected_block_version": after_first},
            build_user_headers("trader-2", "Trader"),
        ),
        201,
    )
    assert get_block(block_id)["version"] == after_first + 1
    superseded = get_plan(plan1["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"The prior non-terminal plan must be SUPERSEDED by the fresh create, got {superseded['status']}"
    )
    assert fresh["status"] == "DRAFT"
