"""Validation-ladder corners: long chains that peel one refusal at a time.

The first scenario repairs a transfer creation one field at a time and watches the
refusal move down the priority order. The second contrasts the freight-worthiness
gate on a discretionary rebalance with the mandated sweep-up that skips it. The
third feeds a receipt that exactly matches total network need through every rung
from proposal to cluster scorecard without a single refusal.
"""
import pytest

from test_helpers import (
    ALLOCATOR,
    MANAGER,
    ApiErrorId,
    api_client,
    get_success_data,
    make_store_operator_headers,
    validate_error,
)
from test_helpers.fixtures_calculation_corners import (
    action_at,
    build_exact_fill_network,
    build_freight_gate_network,
    build_ladder_network,
    commit,
    line_at,
    lines_meta,
    lock,
    open_run,
    position_version,
    propose,
    snapshot_response,
    sweep,
    transfer_response,
    unlock,
)

# A syntactically valid identifier that resolves to nothing.
FABRICATED_ID = "11111111-1111-4111-8111-111111111111"


def nonzero_sizes(entries):
    """Collapse a size array to the sizes that actually carry units."""
    return {
        entry["size_code"]: entry["units"]
        for entry in (entries or [])
        if entry["units"]
    }


def test_transfer_creation_reports_the_lowest_numbered_rung_it_violates():
    """"All validation in this service is **strictly ordered**." "Checks are
    evaluated in ascending priority and the **first** violated check determines the
    response; later checks are never reached, so a request that violates three rules
    always reports the lowest-numbered one." "1. Headers present and `X-User-Role`
    recognised — `ERR_UNAUTHENTICATED`, 401." "2. Role authorised for the endpoint —
    `ERR_FORBIDDEN_ROLE`, 403." "4. Request body and query shape: every required
    field present, every enum value inside its declared set, every integer inside
    its declared range". "6. Every foreign key in the request body resolves — the
    matching not-found error for the referenced entity, 404." "7. Program cohesion
    across referenced entities — `ERR_CROSS_PROGRAM_REFERENCE`, 422." "9. The
    program is `ACTIVE`, for the decision endpoints listed in §2.6 —
    `ERR_PROGRAM_LOCKED`, 409." "11. The supplied parent version matches the
    parent's current `version`, on the two creations described in §2.7 —
    `ERR_STALE_RECEIPT_VERSION` or `ERR_STALE_POSITION_VERSION`, 412." "21. A
    transfer's donor and receiver differ — `ERR_SAME_STORE_TRANSFER`, 422." "26.
    Store status eligibility for transfers and allocation — `ERR_STORE_NOT_ELIGIBLE`,
    409." "29. The transfer size split found at least one candidate size —
    `ERR_TRANSFER_SIZE_INFEASIBLE`, 422." "33. The donor position holds enough
    uncommitted stock — `ERR_INSUFFICIENT_DONOR_UNITS`, 409."

    Design: Corner/validations/transfer_create_ladder_from_missing_auth_down_thirteen_priorities
    """
    net = build_ladder_network()
    program_id = net["program"]["id"]
    stores = net["stores"]
    item_id = net["item"]["id"]
    donor = net["positions"]["0101"]
    donor_v1 = donor["version"]

    def payload(from_store_id, to_store_id, referenced_item_id, units, version):
        return {
            "program_id": program_id,
            "from_store_id": from_store_id,
            "to_store_id": to_store_id,
            "item_id": referenced_item_id,
            "units": units,
            "expected_from_position_version": version,
        }

    # Rung 1: no headers at all, on a body that also breaks five later rungs.
    broken_body = payload(FABRICATED_ID, FABRICATED_ID, item_id, 0, donor_v1)
    validate_error(
        api_client.create_transfer_recommendation(broken_body, {}),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    # Rung 2: the identical body from a role that may not propose transfers.
    validate_error(
        api_client.create_transfer_recommendation(
            broken_body, make_store_operator_headers(stores["0101"]["id"])
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )

    # Rung 4: the identical body from an authorised role — a units count of zero
    # is outside its declared range.
    validate_error(
        api_client.create_transfer_recommendation(broken_body, ALLOCATOR),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    # Rung 6, on the store reference.
    validate_error(
        api_client.create_transfer_recommendation(
            payload(FABRICATED_ID, FABRICATED_ID, item_id, 6, donor_v1), ALLOCATOR
        ),
        ApiErrorId.ERR_STORE_NOT_FOUND,
    )

    # Rung 6, on the SKU reference, with both stores now resolving.
    validate_error(
        api_client.create_transfer_recommendation(
            payload(
                stores["0101"]["id"], stores["0102"]["id"], FABRICATED_ID, 6, donor_v1
            ),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_ITEM_NOT_FOUND,
    )

    # Rung 7: every reference resolves, but the receiver belongs to another
    # program.
    validate_error(
        api_client.create_transfer_recommendation(
            payload(
                stores["0101"]["id"],
                net["other_store"]["id"],
                item_id,
                6,
                donor_v1,
            ),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE,
    )

    # Rung 9: a locked program answers before the same-store and donor-stock
    # rungs this body also breaks.
    lock(program_id, "priority ladder freeze")
    validate_error(
        api_client.create_transfer_recommendation(
            payload(stores["0101"]["id"], stores["0101"]["id"], item_id, 999, donor_v1),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_PROGRAM_LOCKED,
    )
    unlock(program_id)

    # Rung 11: patching the donor position moves its version on, so the token
    # captured at setup is now stale.
    get_success_data(
        api_client.patch_store_position(donor["id"], {"min_units": 9}, ALLOCATOR)
    )
    validate_error(
        api_client.create_transfer_recommendation(
            payload(stores["0101"]["id"], stores["0103"]["id"], item_id, 999, donor_v1),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_STALE_POSITION_VERSION,
    )
    donor_v2 = position_version(donor["id"])
    assert donor_v2 != donor_v1

    # Rung 21: donor and receiver are the same store.
    validate_error(
        api_client.create_transfer_recommendation(
            payload(stores["0101"]["id"], stores["0101"]["id"], item_id, 999, donor_v2),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_SAME_STORE_TRANSFER,
    )

    # Rung 26: store 0103 is CLOSING and may not receive.
    validate_error(
        api_client.create_transfer_recommendation(
            payload(stores["0101"]["id"], stores["0103"]["id"], item_id, 999, donor_v2),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_STORE_NOT_ELIGIBLE,
    )

    # Rung 29: store 0104 already holds every core size, so the rebalance split
    # finds no candidate size.
    validate_error(
        api_client.create_transfer_recommendation(
            payload(stores["0101"]["id"], stores["0104"]["id"], item_id, 999, donor_v2),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_TRANSFER_SIZE_INFEASIBLE,
    )

    # Rung 33: an eligible receiver with holes to fill, but 999 units is far
    # beyond the donor's twenty.
    validate_error(
        api_client.create_transfer_recommendation(
            payload(stores["0101"]["id"], stores["0102"]["id"], item_id, 999, donor_v2),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_INSUFFICIENT_DONOR_UNITS,
    )

    # Nothing has been claimed against the donor by any of the refusals.
    untouched = get_success_data(
        api_client.get_store_position(donor["id"], ALLOCATOR)
    )
    assert untouched["reserved_out_units"] == 0

    created = get_success_data(
        transfer_response(
            program_id, stores["0101"]["id"], stores["0102"]["id"], item_id, 6, donor_v2
        )
    )
    assert created["status"] == "PROPOSED"
    assert created["source_reason"] == "REBALANCE"
    assert nonzero_sizes(created["size_split"]) == {"S": 4, "XL": 2}
    assert created["landed_cost_usd"] == pytest.approx(51.63, abs=0.01)
    assert created["benefit_usd"] == pytest.approx(69.86, abs=0.01)
    assert created["benefit_ratio_bp"] == 13531


def _swept_up_transfer(net):
    """Run the sweep, execute the consolidation it raises and return the
    recommendation the execution created."""
    sweep(net["program"]["id"])
    action = action_at(net["item"]["id"], net["stores"]["0101"]["id"])
    assert action is not None
    assert action["action_type"] == "CONSOLIDATION"
    assert action["consolidation_target_store_id"] == net["stores"]["0102"]["id"]
    assert action["units_at_detection"] == 4
    get_success_data(api_client.execute_assortment_action(action["id"], MANAGER))
    raised = get_success_data(
        api_client.list_transfer_recommendations(
            ALLOCATOR, {"assortment_action_id": action["id"], "limit": 50}
        )
    )
    assert len(raised) == 1
    return action, raised[0]


def test_a_swept_up_consolidation_is_approved_below_the_freight_threshold():
    """"A `CONSOLIDATION` action creates a transfer recommendation with
    `source_reason` of `CONSOLIDATION`, `from_store_id` set to the action's own
    `store_id`, `to_store_id` set to the action's `consolidation_target_store_id`,
    `units` set to `units_at_detection`" "and `proposed_by_user_id` set to the
    literal string `system`". "For a `CONSOLIDATION` transfer, described in §3.9, the
    goal is to sweep a door out: the candidate sizes are every size the donor holds
    more than zero units of, whatever those sizes happen to be, and each candidate's
    weight is the donor's own on-hand unit count for that size." "Step one is
    freight: the donor store's `freight_flat_usd` plus 85 cents per unit moved, that
    sum rounded half up to two decimals, and the result taken as the greater of
    itself and a floor of 45 dollars". "a `freight_cost_usd` below 50.00 attracts
    1200 basis points". "Step three is `landed_cost_usd`, the exact sum of the
    two-decimal `freight_cost_usd` and the two-decimal `handling_fee_usd`, with no
    further rounding." "The **freight-worthiness gate** is conditional on
    `source_reason`: a `CONSOLIDATION` transfer skips it entirely, because a mandated
    sweep-up is exempt by design". "Segregation of duties is structurally unbreakable
    for `CONSOLIDATION` transfers, whose `proposed_by_user_id` is the literal string
    `system`."

    Design: Corner/validations/freight_worthiness_gate_applies_to_rebalance_and_skips_consolidation
    """
    net = build_freight_gate_network()
    action, transfer = _swept_up_transfer(net)

    assert transfer["source_reason"] == "CONSOLIDATION"
    assert transfer["from_store_id"] == net["stores"]["0101"]["id"]
    assert transfer["to_store_id"] == net["stores"]["0102"]["id"]
    assert transfer["units"] == action["units_at_detection"]
    assert transfer["proposed_by_user_id"] == "system"
    assert transfer["assortment_action_id"] == action["id"]
    # The consolidation branch sweeps whatever the donor holds, weighted by the
    # donor's own on-hand counts.
    assert nonzero_sizes(transfer["size_split"]) == {"M": 3, "L": 1}
    assert transfer["freight_cost_usd"] == pytest.approx(45.00, abs=0.01)
    assert transfer["handling_fee_usd"] == pytest.approx(5.40, abs=0.01)
    assert transfer["landed_cost_usd"] == pytest.approx(50.40, abs=0.01)
    assert transfer["benefit_usd"] == pytest.approx(46.57, abs=0.01)
    assert transfer["benefit_ratio_bp"] == 9240

    # The program demands a 2.00x ratio, and this transfer returns 0.92x — the
    # gate is not consulted at all.
    assert net["program"]["transfer_min_ratio_bp"] == 20000
    approved = get_success_data(
        api_client.approve_transfer(transfer["id"], MANAGER)
    )
    assert approved["status"] == "APPROVED"
    assert approved["benefit_ratio_bp"] == 9240


def test_a_discretionary_rebalance_is_refused_below_the_freight_threshold():
    """"For a `REBALANCE` transfer the goal is to fill holes: the candidate sizes are
    the SKU's **CORE** sizes for which the receiving position shows zero units on
    hand and the donor position shows more than zero, and each candidate's weight is
    its `share_bp` from the size curve." "Rounding happens **per size line**: for
    each entry of `size_split`, that entry's `units` multiplied by the realised
    per-unit margin is rounded half up to two decimals, and `benefit_usd` is the sum
    of those rounded per-size figures." "Fourth and last, `benefit_ratio_bp` is
    `benefit_usd` divided by `landed_cost_usd`, multiplied by 10000, rounded half up
    to a whole number of basis points." "while a `REBALANCE` transfer requires
    `benefit_ratio_bp` to be greater than or equal to the program's
    `transfer_min_ratio_bp`, with equality passing, and otherwise is refused with
    `ERR_BENEFIT_RATIO_BELOW_THRESHOLD`." "Creation also freezes the economics, and
    none of the four figures below is ever recomputed afterwards."

    Design: Corner/validations/freight_worthiness_gate_applies_to_rebalance_and_skips_consolidation
    """
    net = build_freight_gate_network()
    _swept_up_transfer(net)

    donor = net["positions"]["0102"]
    rebalance = get_success_data(
        transfer_response(
            net["program"]["id"],
            net["stores"]["0102"]["id"],
            net["stores"]["0101"]["id"],
            net["item"]["id"],
            6,
            position_version(donor["id"]),
        )
    )
    assert rebalance["source_reason"] == "REBALANCE"
    # The receiver holds no S and no XL, so only those two core sizes are
    # candidates, weighted 2000 and 1500 by the curve.
    assert nonzero_sizes(rebalance["size_split"]) == {"S": 4, "XL": 2}
    assert rebalance["landed_cost_usd"] == pytest.approx(50.40, abs=0.01)
    assert rebalance["benefit_usd"] == pytest.approx(78.30, abs=0.01)
    assert rebalance["benefit_ratio_bp"] == 15536

    validate_error(
        api_client.approve_transfer(rebalance["id"], MANAGER),
        ApiErrorId.ERR_BENEFIT_RATIO_BELOW_THRESHOLD,
    )

    # The refusal changed nothing: the economics stand as frozen at creation and
    # no units were claimed.
    unchanged = get_success_data(
        api_client.get_transfer_recommendation(rebalance["id"], ALLOCATOR)
    )
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["benefit_ratio_bp"] == 15536
    assert unchanged["landed_cost_usd"] == pytest.approx(50.40, abs=0.01)
    receiver = get_success_data(
        api_client.get_store_position(net["positions"]["0101"]["id"], ALLOCATOR)
    )
    assert receiver["in_transit_units"] == 0


EXPECTED_SPLIT = {
    "0101": (26, {"S": 5, "M": 10, "L": 8, "XL": 3}),
    "0103": (10, {"S": 2, "M": 4, "L": 3, "XL": 1}),
    "0104": (8, {"S": 1, "M": 3, "L": 3, "XL": 1}),
}


def _committed_network():
    """Open, propose and commit the run that spreads the exact-fill receipt."""
    net = build_exact_fill_network()
    run = open_run(net["receipt"]["id"])
    propose(run["id"])
    net["run"] = commit(run["id"])
    net["lines"] = {
        code: line_at(run["id"], net["stores"][code]["id"]) for code in EXPECTED_SPLIT
    }
    return net


def test_a_receipt_matching_total_network_need_clears_every_proposal_rung():
    """"An allocation line is materialised for each store whose final allocation is
    greater than zero; **a store allocated zero units gets no line at all**."
    "`need_units` is the greater of zero and the target minus the pipeline." "The
    pipeline under this basis is the position's `available_units` plus its
    `in_transit_units` plus its `on_order_units`". "Note that this split follows the
    size curve **only** and is deliberately not constrained by the receipt's
    `size_received` mix, because the DC substitutes sizes at pick time." "Whatever is
    still unplaced when the loop finishes becomes the run's
    `unallocated_remainder_units`". "Every line's `units_allocated` is set equal to
    its `units_proposed` and its `fulfillment_status` is set to `PENDING`." "The
    receipt's `units_committed` and `units_unallocated` are recomputed, and if
    `units_unallocated` reaches 0 the receipt is driven `ALLOCATING → ALLOCATED`."

    Design: Corner/validations/exact_fill_receipt_satisfies_every_rung_from_propose_to_scorecard
    """
    net = _committed_network()
    run = net["run"]

    # Store 0102's pipeline already covers its four-week target, so it is not in
    # the proration candidate set and gets no line.
    meta = lines_meta(run["id"])
    assert meta["total_count"] == 3
    assert line_at(run["id"], net["stores"]["0102"]["id"]) is None
    assert run["eligible_store_count"] == 3

    for code, (units, breakdown) in EXPECTED_SPLIT.items():
        line = net["lines"][code]
        assert line is not None
        assert line["units_proposed"] == units
        assert line["need_units"] == units
        assert line["capacity_capped_units"] == 0
        assert nonzero_sizes(line["size_breakdown"]) == breakdown
        assert line["units_allocated"] == line["units_proposed"]
        assert line["fulfillment_status"] == "PENDING"

    assert run["status"] == "COMMITTED"
    assert run["units_proposed"] == 44
    assert run["units_committed"] == 44
    assert run["unallocated_remainder_units"] == 0

    receipt = get_success_data(
        api_client.get_receipt(net["receipt"]["id"], ALLOCATOR)
    )
    assert receipt["status"] == "ALLOCATED"
    assert receipt["units_committed"] == 44
    assert receipt["units_unallocated"] == 0

    program = get_success_data(
        api_client.get_program(net["program"]["id"], ALLOCATOR)
    )
    assert program["total_units_received"] == 44
    assert program["total_units_committed"] == 44
    assert program["open_reserve_units"] == 0


EXPECTED_ON_HAND = {
    "0101": (32, {"S": 5, "M": 14, "L": 10, "XL": 3}),
    "0103": (12, {"S": 2, "M": 5, "L": 4, "XL": 1}),
    "0104": (8, {"S": 1, "M": 3, "L": 3, "XL": 1}),
}


def _fulfilled_network():
    """Carry every committed line through release and store confirmation."""
    net = _committed_network()
    for line in net["lines"].values():
        get_success_data(api_client.ship_line(line["id"], MANAGER))
    for code, line in net["lines"].items():
        get_success_data(
            api_client.confirm_line_receipt(
                line["id"], make_store_operator_headers(net["stores"][code]["id"])
            )
        )
    return net


def test_release_and_store_confirmation_land_the_exact_fill_without_a_refusal():
    """"The release adds the line's `units_allocated` to the destination position's
    `in_transit_units` and re-derives that position's `stock_status`". "A
    `StoreOperator` confirms physical receipt of a line, taking it `SHIPPED →
    RECEIVED`, and the acting `X-User-ID` must equal the line's `store_id`". "the
    line's `units_allocated` are added to the position's `on_hand_units` and the
    line's `size_breakdown` is merged into the position's `size_on_hand`; the same
    quantity is removed from the position's `in_transit_units`". "otherwise, when
    `available_units` is greater than or equal to `min_units` and less than or equal
    to `max_units` it is `IN_STOCK`". "otherwise, if `broken_size_count` is 0 the
    position is `COMPLETE`". "`broken_store_count` becomes the number of that SKU's
    positions whose `assortment_status` is `BROKEN`, and `size_out_store_count`
    becomes the number whose `assortment_status` is `SIZE_OUT_RISK`." "and when the
    broken count returns to 0 with no size-out positions remaining, it moves `BROKEN
    → ACTIVE`."

    Design: Corner/validations/exact_fill_receipt_satisfies_every_rung_from_propose_to_scorecard
    """
    net = _committed_network()

    # Three of the four positions open the season size-broken.
    opening = get_success_data(api_client.get_item(net["item"]["id"], ALLOCATOR))
    assert opening["broken_store_count"] == 3
    assert opening["lifecycle_state"] == "BROKEN"

    for code, line in net["lines"].items():
        shipped = get_success_data(api_client.ship_line(line["id"], MANAGER))
        assert shipped["fulfillment_status"] == "SHIPPED"

    # Release moves the goods into the pipeline and nowhere else yet.
    for code, (units, _breakdown) in EXPECTED_SPLIT.items():
        staged = get_success_data(
            api_client.get_store_position(net["positions"][code]["id"], ALLOCATOR)
        )
        assert staged["in_transit_units"] == units
        assert staged["on_hand_units"] == net["positions"][code]["on_hand_units"]

    for code, line in net["lines"].items():
        landed = get_success_data(
            api_client.confirm_line_receipt(
                line["id"], make_store_operator_headers(net["stores"][code]["id"])
            )
        )
        assert landed["fulfillment_status"] == "RECEIVED"

    for code, (on_hand, size_on_hand) in EXPECTED_ON_HAND.items():
        position = get_success_data(
            api_client.get_store_position(net["positions"][code]["id"], ALLOCATOR)
        )
        assert position["on_hand_units"] == on_hand
        assert nonzero_sizes(position["size_on_hand"]) == size_on_hand
        assert position["in_transit_units"] == 0
        assert position["broken_size_count"] == 0
        assert position["assortment_status"] == "COMPLETE"
        assert position["stock_status"] == "IN_STOCK"

    # The untouched store was already whole, so all four positions now agree.
    bystander = get_success_data(
        api_client.get_store_position(net["positions"]["0102"]["id"], ALLOCATOR)
    )
    assert bystander["assortment_status"] == "COMPLETE"
    assert bystander["stock_status"] == "IN_STOCK"

    healed = get_success_data(api_client.get_item(net["item"]["id"], ALLOCATOR))
    assert healed["broken_store_count"] == 0
    assert healed["size_out_store_count"] == 0
    assert healed["lifecycle_state"] == "ACTIVE"


def test_the_landed_exact_fill_scores_both_clusters_on_the_unit_weighted_basis():
    """"The included population is every store position whose store belongs to the
    given `program_id`, whose store's `cluster_code` matches the requested cluster,
    whose store's `status` is either `ACTIVE` or `REMODEL`, and whose SKU's
    `lifecycle_state` is anything other than `MARKDOWN`." "Otherwise `store_count` is
    the number of distinct stores contributing at least one included position and
    `included_position_count` is the number of included positions." "A position's
    **covered** units are the lesser of its `available_units` and its `min_units`.
    Its **sold** units are its `trailing_4wk_sales_units`. Its **base** is its sold
    units plus its `available_units`." "Under `UNIT_WEIGHTED`, numerators and
    denominators are summed across the whole cluster first, divided once, and
    truncated once." "`allocation_accuracy_bp` is **identical under both bases**,
    because it is always unit-weighted." "Otherwise it is 10000 less the deviation
    multiplied by 10000 and divided by total sold with the quotient truncated down,
    and that result floored at 0 so the figure never goes negative."

    Design: Corner/validations/exact_fill_receipt_satisfies_every_rung_from_propose_to_scorecard
    """
    net = _fulfilled_network()

    urban = get_success_data(
        snapshot_response(net["program"]["id"], "URBAN", "UNIT_WEIGHTED")
    )
    assert urban["basis"] == "UNIT_WEIGHTED"
    assert urban["store_count"] == 2
    assert urban["included_position_count"] == 2
    assert urban["in_stock_pct_bp"] == 10000
    assert urban["sell_through_pct_bp"] == 4693
    assert urban["allocation_accuracy_bp"] == 5653

    suburban = get_success_data(
        snapshot_response(net["program"]["id"], "SUBURBAN", "UNIT_WEIGHTED")
    )
    assert suburban["store_count"] == 2
    assert suburban["included_position_count"] == 2
    assert suburban["in_stock_pct_bp"] == 10000
    assert suburban["sell_through_pct_bp"] == 3548
    assert suburban["allocation_accuracy_bp"] == 3637
