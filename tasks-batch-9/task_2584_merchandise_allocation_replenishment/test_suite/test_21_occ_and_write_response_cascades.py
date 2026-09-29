"""Optimistic concurrency on the two superseding creations, and the promise that
every write response already carries its own cascade.

The two version-guarded creations sit at the same rung of the validation ladder,
answer with different error ids, and both invalidate the very token that
authorised them. The second half of this module brackets four different writes
and compares each write's own response body against an immediate re-read.
"""
import pytest

from test_helpers import (
    ADMIN,
    ALLOCATOR,
    MANAGER,
    ApiErrorId,
    make_store_operator_headers,
    units_by_size,
    validate_error,
    validate_paginated,
    validate_success,
)

CURVE_4SZ = [
    {"size_code": "S", "share_bp": 2000},
    {"size_code": "M", "share_bp": 3500},
    {"size_code": "L", "share_bp": 3000},
    {"size_code": "XL", "share_bp": 1500},
]

STORE_0101 = {
    "store_code": "0101",
    "grade": "A",
    "grade_index_bp": 13000,
    "cluster_code": "URBAN",
    "freight_flat_usd": 41.00,
    "historical_sell_through_bp": 6500,
}

STORE_0102 = {
    "store_code": "0102",
    "grade": "B",
    "grade_index_bp": 10000,
    "cluster_code": "URBAN",
    "freight_flat_usd": 38.00,
    "historical_sell_through_bp": 5800,
}

PLAN_0101 = {
    "item_class": "APPAREL_TOP",
    "effective_from": "2026-07-01T00:00:00Z",
    "fixture_count": 4,
    "facings_per_fixture": 3,
    "units_per_facing": 4,
    "presentation_min_units": 6,
}

PLAN_0102 = {
    "item_class": "APPAREL_TOP",
    "effective_from": "2026-07-01T00:00:00Z",
    "fixture_count": 2,
    "facings_per_fixture": 3,
    "units_per_facing": 4,
    "presentation_min_units": 2,
}

POSITION_0101 = {
    "on_hand_units": 6,
    "size_on_hand": [{"size_code": "M", "units": 4}, {"size_code": "L", "units": 2}],
    "min_units": 12,
    "max_units": 48,
    "weekly_forecast_units": 9,
    "trailing_4wk_sales_units": 30,
}

POSITION_0102 = {
    "on_hand_units": 30,
    "size_on_hand": [
        {"size_code": "S", "units": 8},
        {"size_code": "M", "units": 10},
        {"size_code": "L", "units": 8},
        {"size_code": "XL", "units": 4},
    ],
    "min_units": 8,
    "max_units": 24,
    "weekly_forecast_units": 5,
    "trailing_4wk_sales_units": 16,
}

RECEIPT_30 = {
    "units_received": 30,
    "size_received": [
        {"size_code": "S", "units": 6},
        {"size_code": "M", "units": 11},
        {"size_code": "L", "units": 9},
        {"size_code": "XL", "units": 4},
    ],
    "receipt_date": "2026-08-01T00:00:00Z",
}


def _occ_network(api, reference="ASN-R401"):
    """Program FA26 ACTIVE, stores 0101 and 0102 with their shelf plans, SKU-1001
    on the four-size curve, a thin position at 0101 and a full one at 0102, and a
    30-unit receipt still `STAGED`."""
    validate_success(
        api.set_current_utc({"current_utc": "2026-08-01T00:00:00Z"}, ADMIN)
    )
    program = validate_success(
        api.create_program(
            {"name": "FA26 Core Tops", "season_code": "FA26", "banner_code": "NORTH"},
            ADMIN,
        ),
        201,
    )
    store_one = validate_success(
        api.create_store(dict(STORE_0101, program_id=program["id"]), ADMIN), 201
    )
    store_two = validate_success(
        api.create_store(dict(STORE_0102, program_id=program["id"]), ADMIN), 201
    )
    validate_success(
        api.create_fixture_plan(dict(PLAN_0101, store_id=store_one["id"]), ADMIN), 201
    )
    validate_success(
        api.create_fixture_plan(dict(PLAN_0102, store_id=store_two["id"]), ADMIN), 201
    )
    profile = validate_success(
        api.create_size_profile(
            {
                "program_id": program["id"],
                "profile_code": "TOP-4SZ",
                "item_class": "APPAREL_TOP",
                "size_curve": [dict(entry) for entry in CURVE_4SZ],
            },
            ADMIN,
        ),
        201,
    )
    item = validate_success(
        api.create_item(
            {
                "program_id": program["id"],
                "sku_code": "SKU-1001",
                "style_code": "ST-100",
                "item_class": "APPAREL_TOP",
                "item_type": "SEASONAL",
                "size_profile_id": profile["id"],
                "unit_cost_usd": 14.20,
                "retail_price_usd": 36.50,
            },
            ADMIN,
        ),
        201,
    )
    program = validate_success(api.activate_program(program["id"], ADMIN))
    position_one = validate_success(
        api.create_store_position(
            dict(POSITION_0101, store_id=store_one["id"], item_id=item["id"]), ALLOCATOR
        ),
        201,
    )
    position_two = validate_success(
        api.create_store_position(
            dict(POSITION_0102, store_id=store_two["id"], item_id=item["id"]), ALLOCATOR
        ),
        201,
    )
    receipt = validate_success(
        api.create_receipt(
            dict(
                RECEIPT_30,
                program_id=program["id"],
                item_id=item["id"],
                reference=reference,
            ),
            ALLOCATOR,
        ),
        201,
    )
    return {
        "program": program,
        "store_one": store_one,
        "store_two": store_two,
        "size_profile": profile,
        "item": item,
        "position_one": position_one,
        "position_two": position_two,
        "receipt": receipt,
    }


def _run_payload(expected_receipt_version, **overrides):
    payload = {
        "method": "DEMAND_DRIVEN",
        "need_basis": "FORWARD_LOOKING",
        "expected_receipt_version": expected_receipt_version,
    }
    payload.update(overrides)
    return payload


def test_a_recount_invalidates_the_receipt_token_and_a_lock_hides_the_staleness(api):
    """PRD §3.4 on a recount: "On success the receipt's `version` advances by one,
    which is also what makes a recount visible to the stale-version check on run
    creation." PRD §2.7: a run creation "requires `expected_receipt_version` in the
    request body, carrying the client's last observed `version` of that receipt.
    This field is not optional. If it does not equal the receipt's current
    `version`, the creation is rejected with `ERR_STALE_RECEIPT_VERSION` and HTTP
    412." The ladder in §2.10 orders the two refusals — "9. The program is
    `ACTIVE`, for the decision endpoints listed in §2.6 — `ERR_PROGRAM_LOCKED`,
    409." before "11. The supplied parent version matches the parent's current
    `version`, on the two creations described in §2.7 —
    `ERR_STALE_RECEIPT_VERSION` or `ERR_STALE_POSITION_VERSION`, 412." — and
    "Checks are evaluated in ascending priority and the **first** violated check
    determines the response", so while the program is `LOCKED` the identical stale
    request is reported as a lock rather than as a stale token.

    Design: Corner/complexity_layers/both_occ_rules_reject_a_stale_parent_token_and_a_successful_write_invalidates_its_own_token
    """
    network = _occ_network(api)
    program_id = network["program"]["id"]
    receipt = network["receipt"]
    stale_token = receipt["version"]

    recounted = validate_success(
        api.adjust_receipt(
            receipt["id"],
            {
                "units_received": 34,
                "size_received": [
                    {"size_code": "S", "units": 7},
                    {"size_code": "M", "units": 12},
                    {"size_code": "L", "units": 10},
                    {"size_code": "XL", "units": 5},
                ],
                "adjustment_reason": "DC recount",
            },
            ALLOCATOR,
        )
    )
    assert recounted["version"] == stale_token + 1
    assert recounted["status"] == "STAGED"

    stale = api.create_allocation_run(
        receipt["id"], _run_payload(stale_token), ALLOCATOR
    )
    validate_error(stale, ApiErrorId.ERR_STALE_RECEIPT_VERSION)
    assert stale.status_code == 412
    _, no_runs = validate_paginated(
        api.list_allocation_runs(ALLOCATOR, {"receipt_id": receipt["id"]})
    )
    assert no_runs["total_count"] == 0

    validate_success(
        api.lock_program(program_id, MANAGER, {"reason": "month-end freeze"})
    )
    locked = api.create_allocation_run(
        receipt["id"], _run_payload(stale_token), ALLOCATOR
    )
    validate_error(locked, ApiErrorId.ERR_PROGRAM_LOCKED)
    assert locked.status_code == 409

    validate_success(api.unlock_program(program_id, MANAGER))
    refreshed = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))
    assert refreshed["version"] == stale_token + 1

    run = validate_success(
        api.create_allocation_run(
            receipt["id"], _run_payload(refreshed["version"]), ALLOCATOR
        ),
        201,
    )
    assert run["status"] == "DRAFT"
    assert validate_success(api.get_receipt(receipt["id"], ALLOCATOR))[
        "status"
    ] == "ALLOCATING"


def test_the_run_creation_that_succeeds_invalidates_the_token_that_authorised_it(api):
    """PRD §3.6: opening a run "advances the receipt's `version` by one", so by
    PRD §2.7 — "If it does not equal the receipt's current `version`, the creation
    is rejected with `ERR_STALE_RECEIPT_VERSION` and HTTP 412." — the token that
    authorised a successful creation is stale for the very next call, and a client
    caching one version succeeds exactly once. PRD §2.10 puts the version check at
    "11. The supplied parent version matches the parent's current `version`, on the
    two creations described in §2.7 — `ERR_STALE_RECEIPT_VERSION` or
    `ERR_STALE_POSITION_VERSION`, 412." ahead of "20. A run's declared method
    corresponds to the SKU's resolved replenishment model —
    `ERR_METHOD_MODEL_MISMATCH`, 422.", and PRD §3.2 fixes the pairing: "a
    `SEASONAL` SKU to `DEMAND_DRIVEN`" with "`DEMAND_DRIVEN` pairs with
    `DEMAND_DRIVEN`". PRD §3.6 also states the hazard the rule exists to make
    deterministic: "If any sibling run on the same receipt is sitting in `DRAFT` or
    `PROPOSED`, that sibling is driven to `CANCELLED`, the new run's
    `supersedes_run_id` is set to the superseded sibling's identifier". PRD §3.4:
    "A newly booked receipt opens in `STAGED` with `units_committed` at 0".

    Design: Corner/complexity_layers/both_occ_rules_reject_a_stale_parent_token_and_a_successful_write_invalidates_its_own_token
    """
    network = _occ_network(api, reference="ASN-R402")
    receipt = network["receipt"]
    first_token = receipt["version"]

    run_one = validate_success(
        api.create_allocation_run(receipt["id"], _run_payload(first_token), ALLOCATOR),
        201,
    )
    assert run_one["status"] == "DRAFT"

    replayed = api.create_allocation_run(
        receipt["id"], _run_payload(first_token), ALLOCATOR
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_RECEIPT_VERSION)
    assert replayed.status_code == 412

    second_token = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))["version"]
    assert second_token == first_token + 1

    wrong_method = api.create_allocation_run(
        receipt["id"],
        _run_payload(second_token, method="MIN_MAX_TOPUP"),
        ALLOCATOR,
    )
    validate_error(wrong_method, ApiErrorId.ERR_METHOD_MODEL_MISMATCH)
    assert wrong_method.status_code == 422

    run_two = validate_success(
        api.create_allocation_run(
            receipt["id"],
            _run_payload(second_token, need_basis="HISTORICAL_SELL_THROUGH"),
            ALLOCATOR,
        ),
        201,
    )
    assert run_two["supersedes_run_id"] == run_one["id"]
    assert run_two["need_basis"] == "HISTORICAL_SELL_THROUGH"
    assert validate_success(api.get_allocation_run(run_one["id"], ALLOCATOR))[
        "status"
    ] == "CANCELLED"

    final_receipt = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))
    assert final_receipt["version"] == second_token + 1
    assert final_receipt["status"] == "ALLOCATING"
    assert final_receipt["units_committed"] == 0
    assert final_receipt["units_unallocated"] == final_receipt["units_received"]


def test_the_donor_position_token_is_checked_before_the_same_store_refusal(api):
    """PRD §2.7: creating a transfer recommendation "requires
    `expected_from_position_version` in the request body, carrying the client's last
    observed `version` of the **donor** position — the position identified by the
    donor store and the item being moved. This field is not optional either. If it
    does not equal that donor position's current `version`, the creation is rejected
    with `ERR_STALE_POSITION_VERSION` and HTTP 412." PRD §3.3: a patch of the
    replenishment policy "re-derives the position's stock dimension, leaves its
    assortment dimension entirely alone because the two are independent, and
    advances `version` by one", which is what makes the client's cached token
    stale. The ladder places "11. The supplied parent version matches the parent's
    current `version`, on the two creations described in §2.7 —
    `ERR_STALE_RECEIPT_VERSION` or `ERR_STALE_POSITION_VERSION`, 412." before
    "21. A transfer's donor and receiver differ — `ERR_SAME_STORE_TRANSFER`, 422.",
    and "Checks are evaluated in ascending priority and the **first** violated
    check determines the response", so a self-transfer carrying a stale token is
    reported as stale and the identical self-transfer carrying a fresh token is
    reported as a same-store move. The two rules answer with different error ids at
    the same rung and the same status.

    Design: Corner/complexity_layers/both_occ_rules_reject_a_stale_parent_token_and_a_successful_write_invalidates_its_own_token
    """
    network = _occ_network(api, reference="ASN-R403")
    program_id = network["program"]["id"]
    donor_store = network["store_two"]["id"]
    receiving_store = network["store_one"]["id"]
    item_id = network["item"]["id"]
    donor = network["position_two"]
    stale_token = donor["version"]

    repolicied = validate_success(
        api.patch_store_position(donor["id"], {"min_units": 10}, ALLOCATOR)
    )
    assert repolicied["version"] == stale_token + 1
    assert repolicied["min_units"] == 10
    assert repolicied["assortment_status"] == donor["assortment_status"]

    def _transfer(to_store, token, units=6):
        return api.create_transfer_recommendation(
            {
                "program_id": program_id,
                "from_store_id": donor_store,
                "to_store_id": to_store,
                "item_id": item_id,
                "units": units,
                "expected_from_position_version": token,
            },
            ALLOCATOR,
        )

    stale_move = _transfer(receiving_store, stale_token)
    validate_error(stale_move, ApiErrorId.ERR_STALE_POSITION_VERSION)
    assert stale_move.status_code == 412

    stale_self_move = _transfer(donor_store, stale_token)
    validate_error(stale_self_move, ApiErrorId.ERR_STALE_POSITION_VERSION)
    assert stale_self_move.status_code == 412

    fresh_token = validate_success(api.get_store_position(donor["id"], ALLOCATOR))[
        "version"
    ]
    fresh_self_move = _transfer(donor_store, fresh_token)
    validate_error(fresh_self_move, ApiErrorId.ERR_SAME_STORE_TRANSFER)
    assert fresh_self_move.status_code == 422

    accepted = validate_success(_transfer(receiving_store, fresh_token), 201)
    assert accepted["status"] == "PROPOSED"
    assert accepted["source_reason"] == "REBALANCE"
    assert units_by_size(accepted["size_split"]) == {"S": 4, "XL": 2}
    assert accepted["freight_cost_usd"] == pytest.approx(45.00, abs=0.01)
    assert accepted["handling_fee_usd"] == pytest.approx(5.40, abs=0.01)
    assert accepted["landed_cost_usd"] == pytest.approx(50.40, abs=0.01)
    assert accepted["benefit_usd"] == pytest.approx(78.30, abs=0.01)
    assert accepted["benefit_ratio_bp"] == 15536

    _, meta = validate_paginated(
        api.list_transfer_recommendations(ALLOCATOR, {"program_id": program_id})
    )
    assert meta["total_count"] == 1


def _draft_run(api, network):
    """Open a DEMAND_DRIVEN / FORWARD_LOOKING run against the 30-unit receipt."""
    return validate_success(
        api.create_allocation_run(
            network["receipt"]["id"],
            _run_payload(network["receipt"]["version"]),
            ALLOCATOR,
        ),
        201,
    )


def test_a_patch_and_a_proposal_publish_their_derived_state_in_their_own_response(api):
    """PRD §1: "most write endpoints run one or more pinned calculations whose
    rounding placement, ranking keys, tie-breaks and empty-set fallbacks are all
    observable in the response". PRD §3.3: a policy patch "re-derives the position's
    stock dimension, leaves its assortment dimension entirely alone because the two
    are independent, and advances `version` by one", where "when `available_units`
    is greater than or equal to `min_units` and less than or equal to `max_units` it
    is `IN_STOCK`" and "`available_units` is `on_hand_units` minus
    `reserved_out_units`". PRD §3.6: "Proposing also sets three roll-ups on the run
    itself: `units_proposed` is the sum of the lines' proposed units and is 0 while
    the run is `DRAFT`; `eligible_store_count` is the number of stores that entered
    the proration candidate set at proposal time", and each line "records its owning
    `run_id` and destination `store_id`, the `need_units` computed for that store,
    the `units_proposed` the waterfall placed there, the `capacity_capped_units`
    from step three, and a `presentation_gap_units` figure". PRD §2.4: "Version
    increments are part of the observable contract, not an implementation detail."

    Design: Corner/consistency_model/every_write_response_already_carries_its_own_cascade_with_no_re_read_needed
    """
    network = _occ_network(api, reference="ASN-R501")
    run = _draft_run(api, network)
    position = network["position_one"]

    patched = validate_success(
        api.patch_store_position(position["id"], {"min_units": 5}, ALLOCATOR)
    )
    assert patched["min_units"] == 5
    assert patched["available_units"] == 6
    assert patched["stock_status"] == "IN_STOCK"
    assert patched["assortment_status"] == "BROKEN"
    assert patched["version"] == position["version"] + 1
    assert validate_success(api.get_store_position(position["id"], ALLOCATOR)) == patched

    proposed = validate_success(api.propose_run(run["id"], ALLOCATOR))
    assert proposed["status"] == "PROPOSED"
    assert proposed["units_proposed"] == 30
    assert proposed["eligible_store_count"] == 1
    assert proposed["unallocated_remainder_units"] == 0
    assert proposed["units_committed"] == 0
    assert validate_success(api.get_allocation_run(run["id"], ALLOCATOR)) == proposed

    lines, meta = validate_paginated(
        api.list_allocation_lines(
            ALLOCATOR, {"run_id": run["id"], "store_id": network["store_one"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    line = validate_success(api.get_allocation_line(lines[0]["id"], ALLOCATOR))
    assert line == lines[0]
    assert line["need_units"] == 30
    assert line["units_proposed"] == 30
    assert line["units_allocated"] == 0
    assert line["capacity_capped_units"] == 0
    assert line["presentation_gap_units"] == 0
    assert line["fulfillment_status"] == "PENDING"
    assert units_by_size(line["size_breakdown"]) == {"S": 6, "M": 11, "L": 9, "XL": 4}

    _, other_store = validate_paginated(
        api.list_allocation_lines(
            ALLOCATOR, {"run_id": run["id"], "store_id": network["store_two"]["id"]}
        )
    )
    assert other_store["total_count"] == 0


def test_commit_ship_and_confirm_settle_every_entity_before_they_return(api):
    """PRD §3.7 on the commit: "Every line's `units_allocated` is set equal to its
    `units_proposed` and its `fulfillment_status` is set to `PENDING`." and "The
    receipt's `units_committed` and `units_unallocated` are recomputed, and if
    `units_unallocated` reaches 0 the receipt is driven `ALLOCATING → ALLOCATED`. The
    program's `total_units_committed` and `open_reserve_units` are recomputed." PRD
    §3.7 on the release: "The release adds the line's `units_allocated` to the
    destination position's `in_transit_units` and re-derives that position's
    `stock_status`". PRD §3.7 on the confirmation: "the line's `units_allocated` are
    added to the position's `on_hand_units` and the line's `size_breakdown` is
    merged into the position's `size_on_hand`; the same quantity is removed from the
    position's `in_transit_units`; if `on_hand_units` becomes greater than zero, the
    position's `consolidated_out` flag is cleared back to false; the position's
    `broken_size_count`, `stock_status` and `assortment_status` are all re-derived;
    the SKU's `broken_store_count` and `size_out_store_count` are recomputed and its
    `lifecycle_state` is re-derived". PRD §3.3: "if `broken_size_count` is 0 the
    position is `COMPLETE`" and "if `broken_store_count` is at least 1 the SKU
    becomes `BROKEN`; otherwise, if `size_out_store_count` is at least 1 the SKU
    becomes `SIZE_OUT_WATCH`; otherwise the SKU becomes `ACTIVE`". PRD §2.9:
    "`open_reserve_units` is `total_units_received` minus `total_units_committed`".

    Design: Corner/consistency_model/every_write_response_already_carries_its_own_cascade_with_no_re_read_needed
    """
    network = _occ_network(api, reference="ASN-R502")
    run = _draft_run(api, network)
    position_id = network["position_one"]["id"]
    store_headers = make_store_operator_headers(network["store_one"]["id"])

    validate_success(api.patch_store_position(position_id, {"min_units": 5}, ALLOCATOR))
    validate_success(api.propose_run(run["id"], ALLOCATOR))
    line_id = validate_paginated(
        api.list_allocation_lines(ALLOCATOR, {"run_id": run["id"]})
    )[0][0]["id"]

    committed = validate_success(api.commit_run(run["id"], MANAGER))
    assert committed["status"] == "COMMITTED"
    assert committed["units_committed"] == 30
    assert validate_success(api.get_allocation_run(run["id"], MANAGER)) == committed

    receipt_after_commit = validate_success(
        api.get_receipt(network["receipt"]["id"], MANAGER)
    )
    assert receipt_after_commit["units_committed"] == 30
    assert receipt_after_commit["units_unallocated"] == 0
    assert receipt_after_commit["status"] == "ALLOCATED"

    program_after_commit = validate_success(
        api.get_program(network["program"]["id"], MANAGER)
    )
    assert program_after_commit["total_units_received"] == 30
    assert program_after_commit["total_units_committed"] == 30
    assert program_after_commit["open_reserve_units"] == 0

    shipped = validate_success(api.ship_line(line_id, MANAGER))
    assert shipped["fulfillment_status"] == "SHIPPED"
    assert shipped["units_allocated"] == 30
    position_in_transit = validate_success(api.get_store_position(position_id, ALLOCATOR))
    assert position_in_transit["in_transit_units"] == 30
    assert position_in_transit["on_hand_units"] == 6
    assert position_in_transit["available_units"] == 6
    assert validate_success(api.get_item(network["item"]["id"], ALLOCATOR))[
        "lifecycle_state"
    ] == "BROKEN"

    received = validate_success(api.confirm_line_receipt(line_id, store_headers))
    assert received["fulfillment_status"] == "RECEIVED"
    assert validate_success(api.get_allocation_line(line_id, MANAGER)) == received

    landed = validate_success(api.get_store_position(position_id, ALLOCATOR))
    assert landed["on_hand_units"] == 36
    assert landed["in_transit_units"] == 0
    assert landed["available_units"] == 36
    assert units_by_size(landed["size_on_hand"]) == {"S": 6, "M": 15, "L": 11, "XL": 4}
    assert landed["broken_size_count"] == 0
    assert landed["stock_status"] == "IN_STOCK"
    assert landed["assortment_status"] == "COMPLETE"
    assert landed["consolidated_out"] is False

    item_after = validate_success(api.get_item(network["item"]["id"], ALLOCATOR))
    assert item_after["broken_store_count"] == 0
    assert item_after["size_out_store_count"] == 0
    assert item_after["lifecycle_state"] == "ACTIVE"

    assert validate_success(api.get_store_position(position_id, MANAGER)) == landed
    assert validate_success(api.get_store_position(position_id, store_headers)) == landed
    rows, _ = validate_paginated(
        api.list_store_positions(ADMIN, {"item_id": network["item"]["id"]})
    )
    assert [row for row in rows if row["id"] == position_id] == [landed]
