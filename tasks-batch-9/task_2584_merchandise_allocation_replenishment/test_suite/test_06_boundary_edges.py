"""Boundary and precision edges: the ratio gate, the CORE share test and the stock bands."""
from test_helpers import (
    ALLOCATION_MANAGER_USER_ID,
    POSITION_SPECS_REBALANCE,
    ApiErrorId,
    actions_for,
    create_item,
    create_position,
    create_program,
    create_size_profile,
    create_store,
    create_fixture_plan,
    propose_transfer,
    refresh_position,
    run_detection,
    setup_rebalance_network,
    validate_error,
    validate_success,
)

EIGHT_SIZES_AT_1250_BP = [
    {"size_code": code, "share_bp": 1250}
    for code in ("XS", "S", "M", "L", "XL", "XXL", "XXXL", "4XL")
]


def _rebalance_against_a_threshold_of(threshold_bp):
    """A structurally identical six-unit rebalance 0102 -> 0101 — benefit 78.30 over a
    landed cost of 50.40, a ratio of exactly 15536 basis points — inside a program whose
    freight-worthiness floor is the supplied figure."""
    scenario = setup_rebalance_network(
        program_overrides={"transfer_min_ratio_bp": threshold_bp}
    )
    scenario["transfer"] = propose_transfer(scenario, units=6)
    return scenario


def test_a_threshold_exactly_equal_to_the_ratio_still_approves(
    api, allocation_manager_headers
):
    """PRD §3.8: "The **freight-worthiness gate** is conditional on `source_reason`: a
    `CONSOLIDATION` transfer skips it entirely, because a mandated sweep-up is exempt
    by design, while a `REBALANCE` transfer requires `benefit_ratio_bp` to be greater
    than or equal to the program's `transfer_min_ratio_bp`, with equality passing, and
    otherwise is refused with `ERR_BENEFIT_RATIO_BELOW_THRESHOLD`."

    A floor of 15536 sits exactly on the achieved ratio, so the gate passes and the
    reservation is booked against the donor.

    Design: Difficulty/boundary_precision_check/benefit_ratio_threshold_equality_passes_one_bp_below_fails
    """
    scenario = _rebalance_against_a_threshold_of(15536)
    assert scenario["transfer"]["benefit_ratio_bp"] == 15536

    approved = validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == ALLOCATION_MANAGER_USER_ID

    donor = refresh_position(scenario, "0102")
    assert donor["reserved_out_units"] == 6
    assert donor["available_units"] == 24


def test_a_threshold_one_basis_point_above_the_ratio_refuses(
    api, allocation_manager_headers
):
    """PRD §3.8: "Fourth and last, `benefit_ratio_bp` is `benefit_usd` divided by
    `landed_cost_usd`, multiplied by 10000, rounded half up to a whole number of basis
    points." PRD §2.10 rung 34: "Freight worthiness of a rebalancing transfer —
    `ERR_BENEFIT_RATIO_BELOW_THRESHOLD`, 409."

    78.30 over 50.40 rounds half up to 15536, so a floor of 15537 is the first value
    the transfer cannot clear, and the refused approve reserves nothing.

    Design: Difficulty/boundary_precision_check/benefit_ratio_threshold_equality_passes_one_bp_below_fails
    """
    scenario = _rebalance_against_a_threshold_of(15537)
    transfer = scenario["transfer"]
    assert transfer["benefit_ratio_bp"] == 15536

    validate_error(
        api.approve_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_BENEFIT_RATIO_BELOW_THRESHOLD.value,
        409,
    )

    unchanged = validate_success(
        api.get_transfer_recommendation(transfer["id"], allocation_manager_headers)
    )
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["approved_by_user_id"] is None

    donor = refresh_position(scenario, "0102")
    assert donor["reserved_out_units"] == 0
    assert donor["available_units"] == 30
    assert donor["stock_status"] == "OVERSTOCK"


def test_the_gate_boundary_sits_between_15536_and_15537_on_identical_economics(
    api, allocation_manager_headers
):
    """PRD §3.8: "Creation also freezes the economics, and none of the four figures
    below is ever recomputed afterwards." And: "while a `REBALANCE` transfer requires
    `benefit_ratio_bp` to be greater than or equal to the program's
    `transfer_min_ratio_bp`, with equality passing, and otherwise is refused with
    `ERR_BENEFIT_RATIO_BELOW_THRESHOLD`."

    Three programs differing only in their floor — 15535, 15536 and 15537 — price the
    same move at the same 15536 basis points; the first two approve and only the third
    refuses, which is what makes the comparison inclusive rather than strict.

    Design: Difficulty/boundary_precision_check/benefit_ratio_threshold_equality_passes_one_bp_below_fails
    """
    below = _rebalance_against_a_threshold_of(15535)
    equal = _rebalance_against_a_threshold_of(15536)
    above = _rebalance_against_a_threshold_of(15537)

    ratios = {
        scenario["transfer"]["benefit_ratio_bp"]
        for scenario in (below, equal, above)
    }
    assert ratios == {15536}

    assert validate_success(
        api.approve_transfer(below["transfer"]["id"], allocation_manager_headers)
    )["status"] == "APPROVED"
    assert validate_success(
        api.approve_transfer(equal["transfer"]["id"], allocation_manager_headers)
    )["status"] == "APPROVED"
    validate_error(
        api.approve_transfer(above["transfer"]["id"], allocation_manager_headers),
        ApiErrorId.ERR_BENEFIT_RATIO_BELOW_THRESHOLD.value,
        409,
    )


def _two_profiles_that_differ_only_in_the_core_threshold(api, admin_headers):
    """One program, two eight-size curves at 1250 basis points each. TOP-8SZ-NONE keeps
    the default threshold of 1500 so no size is CORE; TOP-8SZ-ALL sets 1250 so every
    size is. Three positions: two empty ones at 0101, one on each SKU, and a 0102
    position on the all-CORE SKU that is one size short of full."""
    program = create_program()
    stores = {
        "0101": create_store(program["id"], "0101"),
        "0102": create_store(
            program["id"],
            "0102",
            grade="B",
            grade_index_bp=10000,
            freight_flat_usd=38.00,
            historical_sell_through_bp=5800,
        ),
    }
    for store in stores.values():
        create_fixture_plan(
            store["id"],
            fixture_count=2,
            facings_per_fixture=3,
            units_per_facing=4,
            presentation_min_units=8,
        )
    profile_none = create_size_profile(
        program["id"],
        profile_code="TOP-8SZ-NONE",
        size_curve=[dict(entry) for entry in EIGHT_SIZES_AT_1250_BP],
        core_size_min_share_bp=1500,
    )
    profile_all = create_size_profile(
        program["id"],
        profile_code="TOP-8SZ-ALL",
        size_curve=[dict(entry) for entry in EIGHT_SIZES_AT_1250_BP],
        core_size_min_share_bp=1250,
    )
    item_none = create_item(
        program["id"], profile_none["id"], sku_code="SKU-3001", style_code="ST-300"
    )
    item_all = create_item(
        program["id"], profile_all["id"], sku_code="SKU-3002", style_code="ST-300"
    )
    program = validate_success(api.activate_program(program["id"], admin_headers))

    policy = {
        "min_units": 4,
        "max_units": 20,
        "weekly_forecast_units": 3,
        "trailing_4wk_sales_units": 10,
    }
    empty_no_core = create_position(
        stores["0101"]["id"], item_none["id"], on_hand_units=0, size_on_hand=[], **policy
    )
    empty_all_core = create_position(
        stores["0101"]["id"], item_all["id"], on_hand_units=0, size_on_hand=[], **policy
    )
    one_size_short = create_position(
        stores["0102"]["id"],
        item_all["id"],
        on_hand_units=7,
        size_on_hand=[
            {"size_code": code, "units": 1}
            for code in ("XS", "S", "M", "L", "XL", "XXL", "XXXL")
        ],
        **policy,
    )
    return {
        "program": program,
        "stores": stores,
        "profile_none": profile_none,
        "profile_all": profile_all,
        "item_none": item_none,
        "item_all": item_all,
        "empty_no_core": empty_no_core,
        "empty_all_core": empty_all_core,
        "one_size_short": one_size_short,
    }


def test_the_core_size_threshold_is_inclusive_at_the_exact_share(
    api, planning_admin_headers
):
    """PRD §3.2: "A size is CORE when its `share_bp` is greater than or equal to that
    threshold — the comparison is inclusive, so a size sitting exactly on the threshold
    is CORE." And: "Two counts are computed and exposed: `size_count`, the number of
    entries in the curve, and `core_size_count`, the number of entries whose `share_bp`
    reaches the threshold, which may legitimately be 0."

    The same eight shares of 1250 basis points yield zero CORE sizes against a
    threshold of 1500 and all eight against a threshold of 1250.

    Design: Difficulty/boundary_precision_check/core_size_share_threshold_inclusive_and_zero_core_sizes_is_complete
    """
    scenario = _two_profiles_that_differ_only_in_the_core_threshold(
        api, planning_admin_headers
    )

    none_profile = validate_success(
        api.get_size_profile(scenario["profile_none"]["id"], planning_admin_headers)
    )
    assert none_profile["size_count"] == 8
    assert none_profile["core_size_min_share_bp"] == 1500
    assert none_profile["core_size_count"] == 0

    all_profile = validate_success(
        api.get_size_profile(scenario["profile_all"]["id"], planning_admin_headers)
    )
    assert all_profile["size_count"] == 8
    assert all_profile["core_size_min_share_bp"] == 1250
    assert all_profile["core_size_count"] == 8


def test_an_empty_position_with_no_core_sizes_is_declared_assortment_complete(
    api, planning_admin_headers, allocator_headers
):
    """PRD §3.3: "Evaluation order for the status itself is pinned and the first
    matching branch wins: if the store's `status` is `CLOSED` **or** the position's
    `consolidated_out` is true, the position is `EXITED`; otherwise, if
    `broken_size_count` is 0 the position is `COMPLETE`, which includes the degenerate
    case of a SKU whose curve has no CORE sizes at all; otherwise, if
    `broken_size_count` is exactly 1 the position is `SIZE_OUT_RISK`; otherwise
    `broken_size_count` is 2 or more and the position is `BROKEN`."

    Two identically empty positions in the same store split on their curve alone: the
    no-CORE SKU is COMPLETE while still STOCKOUT, and the all-CORE SKU is BROKEN with
    all eight sizes counted.

    Design: Difficulty/boundary_precision_check/core_size_share_threshold_inclusive_and_zero_core_sizes_is_complete
    """
    scenario = _two_profiles_that_differ_only_in_the_core_threshold(
        api, planning_admin_headers
    )

    no_core = validate_success(
        api.get_store_position(scenario["empty_no_core"]["id"], allocator_headers)
    )
    assert no_core["broken_size_count"] == 0
    assert no_core["assortment_status"] == "COMPLETE"
    assert no_core["stock_status"] == "STOCKOUT"

    all_core = validate_success(
        api.get_store_position(scenario["empty_all_core"]["id"], allocator_headers)
    )
    assert all_core["broken_size_count"] == 8
    assert all_core["assortment_status"] == "BROKEN"
    assert all_core["stock_status"] == "STOCKOUT"


def test_one_missing_core_size_is_size_out_risk_because_broken_starts_at_two(
    api, planning_admin_headers, allocator_headers
):
    """PRD §3.3: "The second dimension is `assortment_status`, and it rests on
    `broken_size_count`: the number of the SKU's **CORE** sizes for which the position's
    `size_on_hand` shows zero units, where a size code entirely absent from
    `size_on_hand` counts as zero." And: "Third, in every other case: if
    `broken_store_count` is at least 1 the SKU becomes `BROKEN`; otherwise, if
    `size_out_store_count` is at least 1 the SKU becomes `SIZE_OUT_WATCH`; otherwise the
    SKU becomes `ACTIVE`."

    Seven of eight CORE sizes present is exactly one short, which is SIZE_OUT_RISK and
    not BROKEN; the SKU carries one of each count and BROKEN wins the pinned order.

    Design: Difficulty/boundary_precision_check/core_size_share_threshold_inclusive_and_zero_core_sizes_is_complete
    """
    scenario = _two_profiles_that_differ_only_in_the_core_threshold(
        api, planning_admin_headers
    )

    short_one = validate_success(
        api.get_store_position(scenario["one_size_short"]["id"], allocator_headers)
    )
    assert short_one["broken_size_count"] == 1
    assert short_one["assortment_status"] == "SIZE_OUT_RISK"

    all_core_item = validate_success(
        api.get_item(scenario["item_all"]["id"], allocator_headers)
    )
    assert all_core_item["broken_store_count"] == 1
    assert all_core_item["size_out_store_count"] == 1
    assert all_core_item["lifecycle_state"] == "BROKEN"

    no_core_item = validate_success(
        api.get_item(scenario["item_none"]["id"], allocator_headers)
    )
    assert no_core_item["broken_store_count"] == 0
    assert no_core_item["size_out_store_count"] == 0
    assert no_core_item["lifecycle_state"] == "ACTIVE"


def test_the_sweep_reads_the_depth_ladder_at_both_of_its_ends(
    api, planning_admin_headers, allocation_manager_headers
):
    """PRD §3.9: "If the SKU's size profile has a `core_size_count` of 0, the broken
    ratio is taken as 0 basis points; otherwise the broken ratio is the position's
    `broken_size_count` multiplied by 10000, divided by `core_size_count`, truncated
    down to a whole number of basis points." And: "The resulting `markdown_pct_bp` is
    then read off four tiers, each lower-inclusive and upper-exclusive: a broken ratio
    below 2500 gives 0, a ratio from 2500 up to but not including 5000 gives 1500, a
    ratio from 5000 up to but not including 7500 gives 3000, and a ratio of 7500 or
    above gives 4500." And: "One short-circuit applies before any of that: if the
    degraded position's `available_units` is 0 there is nothing to move, and the
    candidate set is empty by definition."

    Eight of eight broken is a ratio of 10000 and takes the deepest tier; one of eight
    is 1250 and takes no depth at all. The COMPLETE position belongs to a different SKU,
    so neither action can consolidate and the undegraded position raises nothing.

    Design: Difficulty/boundary_precision_check/core_size_share_threshold_inclusive_and_zero_core_sizes_is_complete
    """
    scenario = _two_profiles_that_differ_only_in_the_core_threshold(
        api, planning_admin_headers
    )
    run_detection(scenario["program"]["id"])

    raised = actions_for(scenario["program"]["id"])
    assert len(raised) == 2

    by_store = {action["store_id"]: action for action in raised}
    deepest = by_store[scenario["stores"]["0101"]["id"]]
    assert deepest["item_id"] == scenario["item_all"]["id"]
    assert deepest["trigger_reason"] == "BROKEN_ASSORTMENT"
    assert deepest["action_type"] == "MARKDOWN"
    assert deepest["consolidation_target_store_id"] is None
    assert deepest["broken_size_count"] == 8
    assert deepest["units_at_detection"] == 0
    assert deepest["markdown_pct_bp"] == 4500

    shallowest = by_store[scenario["stores"]["0102"]["id"]]
    assert shallowest["trigger_reason"] == "SIZE_OUT"
    assert shallowest["action_type"] == "MARKDOWN"
    assert shallowest["broken_size_count"] == 1
    assert shallowest["units_at_detection"] == 7
    assert shallowest["markdown_pct_bp"] == 0

    assert all(action["item_id"] != scenario["item_none"]["id"] for action in raised)


def _network_sitting_on_every_stock_band_edge():
    """0101 holds 4 units against a floor of 12 (LOW), 0102 holds 30 against a ceiling
    of 24 (OVERSTOCK), 0103 holds exactly its floor of 5 (IN_STOCK), and a second SKU at
    0103 is empty with a floor of 0. A six-unit rebalance out of 0102 is PROPOSED."""
    position_specs = {
        code: dict(spec) for code, spec in POSITION_SPECS_REBALANCE.items()
    }
    position_specs["0103"] = dict(position_specs["0103"], min_units=5)
    scenario = setup_rebalance_network(
        program_overrides={"transfer_min_ratio_bp": 0},
        position_specs=position_specs,
    )
    second_item = create_item(
        scenario["program"]["id"],
        scenario["size_profile"]["id"],
        sku_code="SKU-1002",
        style_code="ST-100",
    )
    scenario["second_item"] = second_item
    scenario["zero_floor_position"] = create_position(
        scenario["stores"]["0103"]["id"],
        second_item["id"],
        on_hand_units=0,
        size_on_hand=[],
        min_units=0,
        max_units=20,
        weekly_forecast_units=2,
        trailing_4wk_sales_units=4,
    )
    scenario["transfer"] = propose_transfer(scenario, units=6)
    return scenario


def test_a_reservation_that_lands_exactly_on_the_ceiling_reads_in_stock(
    api, allocation_manager_headers
):
    """PRD §3.3: "The first is `stock_status`, derived purely from `available_units`
    against the min-max policy, evaluated in this order: when `available_units` is 0 the
    position is `STOCKOUT`; otherwise, when `available_units` is greater than 0 and
    strictly less than `min_units` it is `LOW`; otherwise, when `available_units` is
    greater than or equal to `min_units` and less than or equal to `max_units` it is
    `IN_STOCK`; otherwise, `available_units` exceeds `max_units` and the position is
    `OVERSTOCK`." And: "`available_units` is `on_hand_units` minus `reserved_out_units`,
    and it, not the raw on-hand count, is what every downstream decision reads."

    Reserving six of thirty units drops available to exactly the ceiling of 24, and the
    upper test being inclusive is what makes the door IN_STOCK rather than OVERSTOCK.

    Design: Difficulty/boundary_precision_check/stock_status_band_edges_at_min_at_max_and_at_zero
    """
    scenario = _network_sitting_on_every_stock_band_edge()

    before = refresh_position(scenario, "0102")
    assert before["available_units"] == 30
    assert before["max_units"] == 24
    assert before["stock_status"] == "OVERSTOCK"

    validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )

    after = refresh_position(scenario, "0102")
    assert after["on_hand_units"] == 30
    assert after["reserved_out_units"] == 6
    assert after["available_units"] == 24
    assert after["stock_status"] == "IN_STOCK"


def test_the_floor_is_inclusive_while_an_empty_shelf_is_stockout_before_any_range_test(
    api, allocator_headers
):
    """PRD §3.3: "The first is `stock_status`, derived purely from `available_units`
    against the min-max policy, evaluated in this order: when `available_units` is 0 the
    position is `STOCKOUT`; otherwise, when `available_units` is greater than 0 and
    strictly less than `min_units` it is `LOW`; otherwise, when `available_units` is
    greater than or equal to `min_units` and less than or equal to `max_units` it is
    `IN_STOCK`; otherwise, `available_units` exceeds `max_units` and the position is
    `OVERSTOCK`."

    Available 5 against a floor of 5 is IN_STOCK because the LOW test is a strict less
    than, and available 0 against a floor of 0 is STOCKOUT because the zero test is
    evaluated before either range test could call it IN_STOCK.

    Design: Difficulty/boundary_precision_check/stock_status_band_edges_at_min_at_max_and_at_zero
    """
    scenario = _network_sitting_on_every_stock_band_edge()

    on_the_floor = refresh_position(scenario, "0103")
    assert on_the_floor["available_units"] == 5
    assert on_the_floor["min_units"] == 5
    assert on_the_floor["stock_status"] == "IN_STOCK"

    at_zero = validate_success(
        api.get_store_position(scenario["zero_floor_position"]["id"], allocator_headers)
    )
    assert at_zero["available_units"] == 0
    assert at_zero["min_units"] == 0
    assert at_zero["max_units"] == 20
    assert at_zero["stock_status"] == "STOCKOUT"


def test_the_reservation_moves_one_band_and_leaves_the_assortment_dimension_alone(
    api, allocation_manager_headers
):
    """PRD §3.3: "A position carries **two health dimensions that move completely
    independently of one another**, and it is essential not to collapse them." And:
    "`reserved_out_units` is the sum of `units` over transfer recommendations for this
    SKU whose `from_store_id` is this store and whose `status` is `APPROVED` or
    `DISPATCHED` — stock the store still physically holds but has already promised
    away."

    An approve is a reservation and not a shipment: the receiving door stays LOW with
    nothing in transit and still BROKEN on two sizes, while the donor keeps a COMPLETE
    assortment even as its stock band moves.

    Design: Difficulty/boundary_precision_check/stock_status_band_edges_at_min_at_max_and_at_zero
    """
    scenario = _network_sitting_on_every_stock_band_edge()

    validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )

    receiver = refresh_position(scenario, "0101")
    assert receiver["available_units"] == 4
    assert receiver["in_transit_units"] == 0
    assert receiver["stock_status"] == "LOW"
    assert receiver["broken_size_count"] == 2
    assert receiver["assortment_status"] == "BROKEN"

    donor = refresh_position(scenario, "0102")
    assert donor["broken_size_count"] == 0
    assert donor["assortment_status"] == "COMPLETE"
