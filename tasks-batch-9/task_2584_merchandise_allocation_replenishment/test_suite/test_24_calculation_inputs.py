"""Calculation-input corners: which inputs a derived number is allowed to read.

Every scenario here pins the *input set* of a calculation rather than the formula
alone — the model a run's method must pair with, the target a need basis reads,
the promotional events that are candidates for a lift, the positions a cluster
scorecard includes, the ceilings a proration waterfall applies in order, the
curve a size split follows, and the fields a markdown depth or a consolidation
target is chosen from.
"""
import pytest

from test_helpers import (
    ADMIN,
    ALLOCATOR,
    MANAGER,
    ApiErrorId,
    api_client,
    get_success_data,
    units_by_size,
    validate_error,
)
from test_helpers.fixtures_calculation_corners import (
    action_at,
    all_actions,
    build_consolidation_choice_network,
    build_markdown_tier_network,
    build_model_resolution_network,
    build_need_target_network,
    build_promo_network,
    build_proration_network,
    build_scorecard_network,
    build_size_split_network,
    line_at,
    lines_meta,
    new_receipt,
    open_run,
    open_run_response,
    propose,
    snapshot_response,
    sweep,
    sweep_actions,
)


# --------------------------------------------------------------------------- #
# Replenishment model resolution
# --------------------------------------------------------------------------- #

def test_replenishment_model_resolves_from_the_override_then_the_item_type():
    """"When `replenishment_model_override` is null — its default — the resolved
    `replenishment_model` follows the type: a `BASIC` SKU resolves to `MIN_MAX`, a
    `SEASONAL` SKU to `DEMAND_DRIVEN`, and a `FASHION` SKU to `PUSH`." "When
    `replenishment_model_override` is supplied and non-null, that value becomes the
    resolved `replenishment_model` outright and the SKU's type is disregarded".

    Design: Corner/calculations/resolved_replenishment_model_from_override_then_item_type
    """
    net = build_model_resolution_network()
    items = net["items"]

    assert items["SKU-1001"]["replenishment_model"] == "DEMAND_DRIVEN"
    assert items["SKU-1001"]["replenishment_model_override"] is None
    assert items["SKU-2001"]["replenishment_model"] == "MIN_MAX"
    assert items["SKU-2001"]["replenishment_model_override"] is None
    assert items["SKU-3001"]["replenishment_model"] == "PUSH"
    assert items["SKU-3001"]["replenishment_model_override"] is None

    overridden = items["SKU-4001"]
    assert overridden["replenishment_model"] == "MIN_MAX"
    assert overridden["replenishment_model_override"] == "MIN_MAX"
    assert overridden["item_type"] == "FASHION"


def test_run_method_must_pair_with_the_resolved_model_of_the_receipts_sku():
    """"the run's declared method and the SKU's resolved model must correspond
    one-for-one: `MIN_MAX` pairs with `MIN_MAX_TOPUP`, `DEMAND_DRIVEN` pairs with
    `DEMAND_DRIVEN`, and `PUSH` pairs with `PUSH_SIZE_PROFILE`." "Any other pairing
    is refused with `ERR_METHOD_MODEL_MISMATCH` when the run is opened."

    Design: Corner/calculations/resolved_replenishment_model_from_override_then_item_type
    """
    net = build_model_resolution_network()
    wrong_method = {
        "ASN-C101": "MIN_MAX_TOPUP",
        "ASN-C102": "DEMAND_DRIVEN",
        "ASN-C103": "MIN_MAX_TOPUP",
        "ASN-C104": "PUSH_SIZE_PROFILE",
    }
    right_method = {
        "ASN-C101": "DEMAND_DRIVEN",
        "ASN-C102": "MIN_MAX_TOPUP",
        "ASN-C103": "PUSH_SIZE_PROFILE",
        "ASN-C104": "MIN_MAX_TOPUP",
    }

    for reference, receipt in net["receipts"].items():
        pristine_version = receipt["version"]
        refused = open_run_response(
            receipt["id"], wrong_method[reference], pristine_version
        )
        validate_error(refused, ApiErrorId.ERR_METHOD_MODEL_MISMATCH)

        untouched = get_success_data(api_client.get_receipt(receipt["id"], ALLOCATOR))
        assert untouched["status"] == "STAGED"
        assert untouched["version"] == pristine_version

        opened = get_success_data(
            open_run_response(receipt["id"], right_method[reference], pristine_version)
        )
        assert opened["method"] == right_method[reference]


def test_patching_the_override_re_resolves_the_model_for_the_next_run():
    """"Resolution runs when the SKU is created, whenever the SKU is patched, and
    again whenever an allocation run is opened against a receipt for that SKU."
    "When `replenishment_model_override` is supplied and non-null, that value
    becomes the resolved `replenishment_model` outright and the SKU's type is
    disregarded".

    Design: Corner/calculations/resolved_replenishment_model_from_override_then_item_type
    """
    net = build_model_resolution_network()
    seasonal = net["items"]["SKU-1001"]

    patched = get_success_data(
        api_client.patch_item(
            seasonal["id"], {"replenishment_model_override": "PUSH"}, ADMIN
        )
    )
    assert patched["item_type"] == "SEASONAL"
    assert patched["replenishment_model_override"] == "PUSH"
    assert patched["replenishment_model"] == "PUSH"

    receipt = new_receipt(
        net["program"]["id"], seasonal["id"], "ASN-C105", 6, {"M": 6}
    )
    validate_error(
        open_run_response(receipt["id"], "DEMAND_DRIVEN", receipt["version"]),
        ApiErrorId.ERR_METHOD_MODEL_MISMATCH,
    )
    opened = get_success_data(
        open_run_response(receipt["id"], "PUSH_SIZE_PROFILE", receipt["version"])
    )
    assert opened["method"] == "PUSH_SIZE_PROFILE"

    restored = get_success_data(
        api_client.patch_item(
            seasonal["id"], {"replenishment_model_override": None}, ADMIN
        )
    )
    assert restored["replenishment_model_override"] is None
    assert restored["replenishment_model"] == "DEMAND_DRIVEN"


# --------------------------------------------------------------------------- #
# Need targets under the three methods
# --------------------------------------------------------------------------- #

def test_need_targets_read_cover_weeks_max_units_and_the_push_fill_rate():
    """"`need_units` is the greater of zero and the target minus the pipeline."
    "Under `MIN_MAX_TOPUP` the target is simply the position's `max_units`, which
    makes it demand-independent". "Under `PUSH_SIZE_PROFILE` the target is the
    in-effect shelf plan's `capacity_units` multiplied by 80 percent, truncated
    down to a whole number of units; the push fill rate is fixed at 8000 basis
    points." "If the candidate set is empty, the lift in effect is 10000 basis
    points". "**a store allocated zero units gets no line at all**".

    Design: Corner/calculations/need_targets_apply_cover_weeks_push_fill_rate_and_default_lift
    """
    net = build_need_target_network()
    s1 = net["stores"]["0101"]
    s2 = net["stores"]["0102"]

    demand_run = open_run(net["receipts"]["ASN-C201"]["id"], "DEMAND_DRIVEN")
    demand_proposed = propose(demand_run["id"])
    topup_run = open_run(net["receipts"]["ASN-C202"]["id"], "MIN_MAX_TOPUP")
    topup_proposed = propose(topup_run["id"])
    push_run = open_run(net["receipts"]["ASN-C203"]["id"], "PUSH_SIZE_PROFILE")
    push_proposed = propose(push_run["id"])

    # Forecast 9 lifted by the neutral 10000 bp over a four-week cover, less a
    # pipeline of 13 units on hand.
    demand_line = line_at(demand_run["id"], s1["id"])
    assert demand_line["need_units"] == 23
    assert demand_line["units_proposed"] == 23
    assert units_by_size(demand_line["size_breakdown"]) == {
        "S": 4, "M": 9, "L": 7, "XL": 3
    }
    assert demand_line["capacity_capped_units"] == 0
    assert demand_line["presentation_gap_units"] == 0
    assert demand_proposed["unallocated_remainder_units"] == 7

    # max_units of 30 less 5 on hand: the forecast and the trailing sales are not
    # read at all under a top-up.
    topup_line = line_at(topup_run["id"], s1["id"])
    assert topup_line["need_units"] == 25
    assert topup_line["units_proposed"] == 25
    assert units_by_size(topup_line["size_breakdown"]) == {
        "S": 5, "M": 9, "L": 8, "XL": 3
    }
    assert topup_line["capacity_capped_units"] == 0
    assert topup_line["presentation_gap_units"] == 0
    assert topup_proposed["unallocated_remainder_units"] == 5

    # 80 percent of a 48-unit fixture is 38 units less 13 on hand; at store 0102
    # 80 percent of a 32-unit fixture is exactly the 25 units already on hand.
    push_line = line_at(push_run["id"], s1["id"])
    assert push_line["need_units"] == 25
    assert push_line["units_proposed"] == 25
    assert units_by_size(push_line["size_breakdown"]) == {
        "S": 5, "M": 9, "L": 8, "XL": 3
    }
    assert push_line["capacity_capped_units"] == 0
    assert push_line["presentation_gap_units"] == 0
    assert push_proposed["unallocated_remainder_units"] == 5
    assert line_at(push_run["id"], s2["id"]) is None
    assert lines_meta(push_run["id"])["total_count"] == 1
    assert push_proposed["eligible_store_count"] == 1


# --------------------------------------------------------------------------- #
# Promotional lift candidacy
# --------------------------------------------------------------------------- #

def test_promotional_lift_reads_one_event_out_of_seven_for_each_store():
    """"Candidates are then ordered by three keys applied strictly in sequence:
    specificity rank descending first, so a `STORE`-scope event outranks a
    `CLUSTER`-scope event which outranks a `PROGRAM`-scope event". "**Exactly one**
    event is selected — the first in that order — and its `lift_factor_bp` is the
    lift in effect; lifts never compound, never sum and never multiply together."
    "a `DRAFT` or `SCHEDULED` event never contributes lift no matter how perfectly
    its window straddles the clock".

    Design: Corner/calculations/promo_lift_input_set_excludes_five_kinds_of_ineligible_event
    """
    net = build_promo_network()
    s1 = net["stores"]["0101"]
    s2 = net["stores"]["0102"]

    run = open_run(net["receipt"]["id"], "DEMAND_DRIVEN")
    proposed = propose(run["id"])

    # Store 0101 reads only its own ACTIVE store-scope event at 13000 bp: forecast
    # 9 lifted to 12 units a week over four weeks, less 10 units on hand.
    urban_line = line_at(run["id"], s1["id"])
    assert urban_line["need_units"] == 38
    # Store 0102 sits outside the URBAN cluster event, so its own store-scope
    # event at 20000 bp wins: forecast 5 lifted to 10 units a week over four
    # weeks, less 6 units on hand.
    suburban_line = line_at(run["id"], s2["id"])
    assert suburban_line["need_units"] == 34

    assert proposed["eligible_store_count"] == 2
    assert urban_line["units_proposed"] == 22
    assert suburban_line["units_proposed"] == 18
    assert proposed["unallocated_remainder_units"] == 0
    assert units_by_size(urban_line["size_breakdown"]) == {
        "S": 4, "M": 8, "L": 7, "XL": 3
    }
    assert units_by_size(suburban_line["size_breakdown"]) == {
        "S": 3, "M": 7, "L": 6, "XL": 2
    }
    assert urban_line["capacity_capped_units"] == 0
    assert suburban_line["capacity_capped_units"] == 0


# --------------------------------------------------------------------------- #
# Cluster scorecard population
# --------------------------------------------------------------------------- #

def test_cluster_scorecard_includes_fewer_positions_than_the_cluster_holds():
    """"The included population is every store position whose store belongs to the
    given `program_id`, whose store's `cluster_code` matches the requested cluster,
    whose store's `status` is either `ACTIVE` or `REMODEL`, and whose SKU's
    `lifecycle_state` is anything other than `MARKDOWN`." "Under `UNIT_WEIGHTED`,
    numerators and denominators are summed across the whole cluster first, divided
    once, and truncated once." "`allocation_accuracy_bp` is **identical under both
    bases**, because it is always unit-weighted."

    Design: Corner/calculations/cluster_scorecard_included_set_is_narrower_than_the_cluster
    """
    net = build_scorecard_network()
    program_id = net["program"]["id"]

    # URBAN holds an ACTIVE store, a REMODEL store and a marked-down SKU.
    urban = get_success_data(snapshot_response(program_id, "URBAN"))
    assert urban["basis"] == "UNIT_WEIGHTED"
    assert urban["as_of_date"].startswith("2026-08-01T00:00:00")
    assert urban["store_count"] == 2
    assert urban["included_position_count"] == 2
    assert urban["in_stock_pct_bp"] == 6666
    assert urban["sell_through_pct_bp"] == 7500
    assert urban["allocation_accuracy_bp"] == 1334

    # SUBURBAN holds one ACTIVE store; the CLOSING store never enters.
    suburban = get_success_data(snapshot_response(program_id, "SUBURBAN"))
    assert suburban["store_count"] == 1
    assert suburban["included_position_count"] == 1
    assert suburban["in_stock_pct_bp"] == 10000
    assert suburban["sell_through_pct_bp"] == 4545
    assert suburban["allocation_accuracy_bp"] == 0


def test_a_cluster_whose_population_is_empty_is_refused_not_scored_at_zero():
    """"If that population is empty the request is refused with
    `ERR_NO_CLUSTER_POSITIONS`." "The included population is every store position
    whose store belongs to the given `program_id`, whose store's `cluster_code`
    matches the requested cluster, whose store's `status` is either `ACTIVE` or
    `REMODEL`, and whose SKU's `lifecycle_state` is anything other than
    `MARKDOWN`."

    Design: Corner/calculations/cluster_scorecard_included_set_is_narrower_than_the_cluster
    """
    net = build_scorecard_network()
    program_id = net["program"]["id"]

    get_success_data(snapshot_response(program_id, "URBAN"))
    get_success_data(snapshot_response(program_id, "SUBURBAN"))

    # OUTLET has exactly one store and it has been taken to CLOSING.
    validate_error(
        snapshot_response(program_id, "OUTLET"), ApiErrorId.ERR_NO_CLUSTER_POSITIONS
    )
    # MALL has no stores at all.
    validate_error(
        snapshot_response(program_id, "MALL"), ApiErrorId.ERR_NO_CLUSTER_POSITIONS
    )

    listed = api_client.list_performance_snapshots(
        MANAGER, params={"program_id": program_id, "limit": 100}
    )
    assert listed.json()["meta"]["total_count"] == 2


# --------------------------------------------------------------------------- #
# Proration waterfall
# --------------------------------------------------------------------------- #

def nonzero_sizes(entries):
    """Collapse a size array to the sizes that actually carry units."""
    return {
        entry["size_code"]: entry["units"]
        for entry in (entries or [])
        if entry["units"]
    }


def test_proration_applies_floor_share_then_capacity_then_ranked_remainder():
    """"**Step one** gives each store a proportional floor share: the pool
    multiplied by that store's need, divided by the total need across the set,
    truncated down to a whole number of units." "**Step two** applies the need
    ceiling, taking the lesser of the floor share and the store's own need."
    "**Step three** applies the fixture capacity ceiling: the store's headroom is
    the greater of zero and the in-effect shelf plan's `capacity_units` less the
    position's `available_units` less its `in_transit_units`, and the store's
    allocation becomes the lesser of its step-two figure and that headroom." "the
    set is ordered by three keys applied strictly in sequence: residual need
    descending, where residual need is the store's need less its current
    allocation; then grade rank ascending, so an `A` store beats a `B` store beats
    a `C` store beats a `D` store; and finally `store_code` ascending in
    lexicographic order."

    Design: Corner/calculations/proration_floor_share_then_capacity_ceiling_then_ranked_remainder
    """
    net = build_proration_network()
    run = net["run"]
    codes = ["0101", "0102", "0103", "0104", "0105", "0106"]
    lines = {
        code: line_at(run["id"], net["stores"][code]["id"]) for code in codes
    }
    for code in codes:
        assert lines[code] is not None, f"store {code} received no line"
        assert lines[code]["need_units"] == 4

    # Twelve units over six equal needs is a floor share of two apiece; only the
    # three-by-one-by-three fixture at 0106 cannot hold its second unit.
    assert lines["0106"]["units_proposed"] == 1
    assert lines["0106"]["capacity_capped_units"] == 1
    for code in ["0101", "0102", "0103", "0104", "0105"]:
        assert lines[code]["capacity_capped_units"] == 0

    # The single leftover unit goes to the grade A store with the lowest code.
    assert lines["0101"]["units_proposed"] == 3
    for code in ["0102", "0103", "0104", "0105"]:
        assert lines[code]["units_proposed"] == 2
    assert run["unallocated_remainder_units"] == 0
    assert run["eligible_store_count"] == 6
    assert run["units_proposed"] == 12

    assert lines["0101"]["presentation_gap_units"] == 1
    for code in ["0102", "0103", "0104", "0105"]:
        assert lines[code]["presentation_gap_units"] == 2
    assert lines["0106"]["presentation_gap_units"] == 0

    assert nonzero_sizes(lines["0101"]["size_breakdown"]) == {"M": 2, "L": 1}
    for code in ["0102", "0103", "0104", "0105"]:
        assert nonzero_sizes(lines[code]["size_breakdown"]) == {"M": 1, "L": 1}
    assert nonzero_sizes(lines["0106"]["size_breakdown"]) == {"M": 1}


# --------------------------------------------------------------------------- #
# Markdown depth tiers
# --------------------------------------------------------------------------- #

MARKDOWN_TIER_CASES = [
    # One broken size out of five core sizes is a 2000 bp ratio: below the first
    # edge, so the depth is an explicit zero.
    ("SKU-3001", "0102", 1, 0, "SIZE_OUT", 8),
    # One broken size out of four core sizes lands exactly on 2500 bp.
    ("SKU-1001", "0101", 1, 1500, "SIZE_OUT", 9),
    # A six-size curve whose narrow sizes are not core also has four core sizes.
    ("SKU-2001", "0103", 1, 1500, "SIZE_OUT", 6),
    # Two of four lands exactly on 5000 bp.
    ("SKU-1001", "0102", 2, 3000, "BROKEN_ASSORTMENT", 7),
    # Three of four lands exactly on 7500 bp, the top tier's lower edge.
    ("SKU-1001", "0103", 3, 4500, "BROKEN_ASSORTMENT", 4),
]


@pytest.mark.parametrize(
    "sku_code,store_code,broken_size_count,markdown_pct_bp,trigger_reason,units",
    MARKDOWN_TIER_CASES,
    ids=[f"{case[0]}@{case[1]}-{case[3]}bp" for case in MARKDOWN_TIER_CASES],
)
def test_markdown_depth_tier_sits_on_each_lower_inclusive_edge(
    sku_code, store_code, broken_size_count, markdown_pct_bp, trigger_reason, units
):
    """"otherwise the broken ratio is the position's `broken_size_count` multiplied
    by 10000, divided by `core_size_count`, truncated down to a whole number of
    basis points." "a broken ratio below 2500 gives 0, a ratio from 2500 up to but
    not including 5000 gives 1500, a ratio from 5000 up to but not including 7500
    gives 3000, and a ratio of 7500 or above gives 4500". "A size is CORE when its
    `share_bp` is greater than or equal to that threshold — the comparison is
    inclusive, so a size sitting exactly on the threshold is CORE." "a
    `trigger_reason` that is `SIZE_OUT` when the position's `assortment_status` was
    `SIZE_OUT_RISK` and `BROKEN_ASSORTMENT` when it was `BROKEN`".
    "`units_at_detection`, copied from the position's `available_units`".

    Design: Corner/calculations/markdown_depth_tiers_at_every_lower_inclusive_edge
    """
    net = build_markdown_tier_network()
    sweep(net["program"]["id"])

    action = action_at(
        net["items"][sku_code]["id"], net["stores"][store_code]["id"]
    )
    assert action is not None, f"{sku_code} at {store_code} raised no action"
    assert action["broken_size_count"] == broken_size_count
    assert action["markdown_pct_bp"] == markdown_pct_bp
    assert action["trigger_reason"] == trigger_reason
    assert action["units_at_detection"] == units
    assert action["action_type"] == "MARKDOWN"
    assert action["consolidation_target_store_id"] is None


def test_the_sweep_raises_one_ordered_action_per_degraded_position():
    """"The sweep scans every store position of the program looking for degraded
    assortment health and raises exactly one `PENDING` **assortment action** per
    newly degraded position." "The actions the sweep returns are ordered by the
    store's `store_code` ascending and then by the SKU's `sku_code` ascending".
    "if `broken_size_count` is 0 the position is `COMPLETE`". "if
    `broken_store_count` is at least 1 the SKU becomes `BROKEN`; otherwise, if
    `size_out_store_count` is at least 1 the SKU becomes `SIZE_OUT_WATCH`".

    Design: Corner/calculations/markdown_depth_tiers_at_every_lower_inclusive_edge
    """
    net = build_markdown_tier_network()
    items = net["items"]
    stores = net["stores"]

    raised = sweep_actions(net["program"]["id"])
    store_code_of = {store["id"]: code for code, store in stores.items()}
    sku_code_of = {item["id"]: code for code, item in items.items()}
    assert [
        (store_code_of[action["store_id"]], sku_code_of[action["item_id"]])
        for action in raised
    ] == [
        ("0101", "SKU-1001"),
        ("0102", "SKU-1001"),
        ("0102", "SKU-3001"),
        ("0103", "SKU-1001"),
        ("0103", "SKU-2001"),
    ]

    # Store 0104 holds every core size of SKU-2001, so its position is COMPLETE
    # and no action is raised for it.
    assert action_at(items["SKU-2001"]["id"], stores["0104"]["id"]) is None

    broken_sku = get_success_data(api_client.get_item(items["SKU-1001"]["id"], ALLOCATOR))
    assert broken_sku["broken_store_count"] == 2
    assert broken_sku["size_out_store_count"] == 1
    assert broken_sku["lifecycle_state"] == "BROKEN"
    for sku_code in ["SKU-2001", "SKU-3001"]:
        watched = get_success_data(api_client.get_item(items[sku_code]["id"], ALLOCATOR))
        assert watched["broken_store_count"] == 0
        assert watched["size_out_store_count"] == 1
        assert watched["lifecycle_state"] == "SIZE_OUT_WATCH"


# --------------------------------------------------------------------------- #
# Size split inputs
# --------------------------------------------------------------------------- #

def test_size_split_follows_the_curve_and_not_the_receipts_own_size_mix():
    """"The split gives each size a floor share — the line's proposed units
    multiplied by that size's `share_bp`, divided by 10000, truncated down to a
    whole number — and then distributes the leftover units, being the proposed
    units less the sum of the floor shares, one at a time in passes." "Note that
    this split follows the size curve **only** and is deliberately not constrained
    by the receipt's `size_received` mix". "The sum of the `units` entries in
    `size_breakdown` must equal the line's `units_proposed` exactly."

    Design: Corner/calculations/size_split_follows_the_curve_not_the_receipt_and_breaks_ties_lexicographically
    """
    net = build_size_split_network()

    run = open_run(net["receipts"]["ASN-C701"]["id"], "DEMAND_DRIVEN")
    propose(run["id"])
    line = line_at(run["id"], net["stores"]["0101"]["id"])

    # The receipt landed sixteen units of M and nothing else.
    assert line["units_proposed"] == 16
    breakdown = nonzero_sizes(line["size_breakdown"])
    assert breakdown == {"S": 3, "M": 6, "L": 5, "XL": 1, "XXL": 1}
    assert sum(breakdown.values()) == 16
    assert line["capacity_capped_units"] == 0


def test_size_split_leftover_pass_breaks_a_share_tie_on_size_code():
    """"Within a pass, sizes are ordered by `share_bp` descending and then by
    `size_code` ascending lexicographically", "each size may receive at most one
    leftover unit per pass**; passes repeat until nothing is left." "The sum of the
    `units` entries in `size_breakdown` must equal the line's `units_proposed`
    exactly."

    Design: Corner/calculations/size_split_follows_the_curve_not_the_receipt_and_breaks_ties_lexicographically
    """
    net = build_size_split_network()

    run = open_run(net["receipts"]["ASN-C702"]["id"], "DEMAND_DRIVEN")
    propose(run["id"])
    line = line_at(run["id"], net["stores"]["0102"]["id"])

    # S and M both carry 3000 bp, and the single leftover unit goes to M.
    assert line["units_proposed"] == 10
    breakdown = nonzero_sizes(line["size_breakdown"])
    assert breakdown == {"S": 3, "M": 4, "L": 2, "XL": 1}
    assert sum(breakdown.values()) == 10
    assert line["capacity_capped_units"] == 0


# --------------------------------------------------------------------------- #
# Consolidation target selection
# --------------------------------------------------------------------------- #

def test_consolidation_target_filter_runs_before_the_three_ranking_keys():
    """"the candidate consolidation targets are the other positions of the **same
    SKU** that satisfy all of the following: they belong to a different store;
    their own `assortment_status` is `COMPLETE`; their store's `status` is `ACTIVE`;
    and their headroom — the greater of zero and their in-effect shelf plan's
    `capacity_units` less their `available_units` less their `in_transit_units` —
    is greater than or equal to the degraded position's `available_units`".
    "Surviving candidates are ordered by three keys applied strictly in sequence:
    the candidate store's `historical_sell_through_bp` descending; then grade rank
    ascending, with `A` ahead of `B` ahead of `C` ahead of `D`; and finally the
    candidate store's `store_code` ascending." "Because the eligibility filter runs
    before the ranking, the highest sell-through store in the network can still
    lose to a lower one simply for having no fixture headroom."

    Design: Corner/calculations/consolidation_target_eligibility_filter_runs_before_the_ranking
    """
    net = build_consolidation_choice_network()
    stores = net["stores"]
    sweep(net["program"]["id"])

    action = action_at(net["items"]["SKU-1001"]["id"], stores["0101"]["id"])
    assert action is not None
    assert action["action_type"] == "CONSOLIDATION"
    # 0107 has the top sell-through but is in REMODEL; 0102 comes next but has
    # only two units of headroom against a four-unit move.
    assert action["consolidation_target_store_id"] == stores["0105"]["id"]
    assert action["markdown_pct_bp"] is None
    assert action["broken_size_count"] == 2
    assert action["units_at_detection"] == 4
    assert action["trigger_reason"] == "BROKEN_ASSORTMENT"
    assert action["status"] == "PENDING"


def test_an_empty_position_short_circuits_the_candidate_set_to_a_markdown():
    """"One short-circuit applies before any of that: if the degraded position's
    `available_units` is 0 there is nothing to move, and the candidate set is empty
    by definition." "When the candidate set is empty, the action's `action_type` is
    `MARKDOWN` and `consolidation_target_store_id` stays null." "a broken ratio
    below 2500 gives 0, a ratio from 2500 up to but not including 5000 gives 1500, a
    ratio from 5000 up to but not including 7500 gives 3000, and a ratio of 7500 or
    above gives 4500". "`units_at_detection`, copied from the position's
    `available_units`". "The actions the sweep returns are ordered by the store's
    `store_code` ascending and then by the SKU's `sku_code` ascending".

    Design: Corner/calculations/consolidation_target_eligibility_filter_runs_before_the_ranking
    """
    net = build_consolidation_choice_network()
    stores = net["stores"]
    items = net["items"]
    sweep(net["program"]["id"])

    action = action_at(items["SKU-2001"]["id"], stores["0101"]["id"])
    assert action is not None
    assert action["action_type"] == "MARKDOWN"
    assert action["consolidation_target_store_id"] is None
    # Every one of the four core sizes is missing from an empty position.
    assert action["markdown_pct_bp"] == 4500
    assert action["units_at_detection"] == 0

    pending = all_actions(status="PENDING")
    sku_code_of = {item["id"]: code for code, item in items.items()}
    assert [action["store_id"] for action in pending] == [
        stores["0101"]["id"],
        stores["0101"]["id"],
    ]
    assert [sku_code_of[action["item_id"]] for action in pending] == [
        "SKU-1001",
        "SKU-2001",
    ]

    transfers = api_client.list_transfer_recommendations(
        MANAGER, params={"program_id": net["program"]["id"], "limit": 100}
    )
    assert transfers.json()["meta"]["total_count"] == 0
