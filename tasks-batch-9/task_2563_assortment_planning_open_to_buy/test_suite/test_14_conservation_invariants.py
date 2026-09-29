"""Quantities that must still add up after every write on the round trip.

Each test translates one instance of the difficulty rule ``compensating_invariant``.
"""
from test_helpers import (
    BUYER_HEADERS,
    ApiErrorId,
    adopt_item,
    assert_otb_conservation,
    assert_slot_conservation,
    cancel_commitment,
    close_item,
    commit_commitment,
    get_commitment,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    get_success_data,
    post_receipt,
    propose_commitment,
    propose_item,
    setup_single_month_approved_plan,
    ship_commitment,
    validate_error,
)


def _month_bought_out_to_the_last_cent():
    """One PROPOSED commitment whose cost is exactly the month's whole open balance."""
    scenario = setup_single_month_approved_plan()
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-CARRY-W", color_code="NAVY",
                        lifecycle_stage="CARRYOVER", unit_cost_cents=2600,
                        retail_price_cents=6900, prior_season_sell_through_bps=7100)
    commitment = propose_commitment(scenario["m1"]["id"], item["id"],
                                    scenario["vendor"]["id"], units=7000,
                                    unit_cost_cents=2600)
    assert commitment["cost_cents"] == 18_200_000
    return scenario, item, commitment


def test_the_commit_moves_the_whole_balance_and_the_ship_moves_no_money_at_all(api):
    """Two of the five states in the walk: the identity holds, and shipping is money-neutral.

    PRD §2.11 identity aside, PRD pins the two writes: on commit "the month's
    `otb_committed_cents` and `otb_open_cents` are recomputed", and "If that recomputation lands
    the plan in `FROZEN`, every assortment item under that plan whose `status` is `PROPOSED` is
    demoted `PROPOSED -> DEFERRED`". For the ship, PRD says a `VendorRep` "marks an order
    shipped, advancing `AWAITING_SHIP -> SHIPPED`; this requires the commitment's `commit_status`
    to be `COMMITTED`, and beyond that guard the financial dimension is neither read nor
    written".

    Design: Difficulty/compensating_invariant/plan_month_otb_dollar_conservation
    """
    scenario, item, commitment = _month_bought_out_to_the_last_cent()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]

    state0 = get_month(month_id)
    assert state0["otb_planned_cents"] == 18_200_000
    assert state0["otb_open_cents"] == 18_200_000
    assert state0["otb_committed_cents"] == 0
    assert state0["otb_received_cents"] == 0
    assert_otb_conservation(state0)

    committed = commit_commitment(commitment["id"])
    assert committed["open_cost_cents"] == 18_200_000
    assert committed["received_cost_cents"] == 0
    state1 = get_month(month_id)
    assert state1["otb_open_cents"] == 0
    assert state1["otb_committed_cents"] == 18_200_000
    assert state1["otb_received_cents"] == 0
    assert_otb_conservation(state1)
    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 0
    assert plan["otb_posture"] == "FROZEN"
    assert get_item(item["id"])["status"] == "DEFERRED"

    version_before_ship = state1["version"]
    shipped = ship_commitment(commitment["id"], vendor_id)
    assert shipped["fulfillment_status"] == "SHIPPED"
    assert shipped["commit_status"] == "COMMITTED"
    state2 = get_month(month_id)
    assert state2["otb_open_cents"] == 0
    assert state2["otb_committed_cents"] == 18_200_000
    assert state2["otb_received_cents"] == 0
    assert state2["version"] == version_before_ship
    assert_otb_conservation(state2)


def test_a_partial_receipt_only_moves_buckets_and_the_cancel_releases_the_remainder(api):
    """The last two states: no bucket may double count, and only unreceived dollars come back.

    PRD on a partial receipt: "the month's `otb_committed_cents` and `otb_received_cents` are
    recomputed" -- the open balance is not among them. PRD on cancelling a `COMMITTED` row:
    "Link 1 sets `commit_status` to `CANCELLED`, sets `cancelled_units` to `units` less
    `received_units`, zeroes `open_cost_cents`, and moves `fulfillment_status` to `VOID` when --
    and only when -- `received_units` is 0", and "after link 2 the conservation identity of
    §2.11 holds exactly on that month". Link 4 then restores the `CARRYOVER` option.

    Design: Difficulty/compensating_invariant/plan_month_otb_dollar_conservation
    """
    scenario, item, commitment = _month_bought_out_to_the_last_cent()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]
    commit_commitment(commitment["id"])
    ship_commitment(commitment["id"], vendor_id)

    post_receipt(commitment["id"], vendor_id, 3000)
    partial = get_commitment(commitment["id"])
    assert partial["received_units"] == 3000
    assert partial["received_cost_cents"] == 7_800_000
    assert partial["open_cost_cents"] == 10_400_000
    assert partial["fulfillment_status"] == "PARTIALLY_RECEIVED"
    assert partial["commit_status"] == "COMMITTED"

    state3 = get_month(month_id)
    assert state3["otb_committed_cents"] == 10_400_000
    assert state3["otb_received_cents"] == 7_800_000
    assert state3["otb_open_cents"] == 0
    assert_otb_conservation(state3)

    cancel_commitment(commitment["id"],
                      cancel_reason="vendor quality hold on the balance")
    cancelled = get_commitment(commitment["id"])
    assert cancelled["commit_status"] == "CANCELLED"
    assert cancelled["cancelled_units"] == 4000
    assert cancelled["open_cost_cents"] == 0
    assert cancelled["received_cost_cents"] == 7_800_000
    assert cancelled["fulfillment_status"] == "PARTIALLY_RECEIVED"

    state4 = get_month(month_id)
    assert state4["otb_committed_cents"] == 0
    assert state4["otb_received_cents"] == 7_800_000
    assert state4["otb_open_cents"] == 10_400_000
    assert state4["otb_planned_cents"] == 18_200_000
    assert_otb_conservation(state4)

    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 5714
    assert plan["otb_posture"] == "OPEN"
    assert get_item(item["id"])["status"] == "PROPOSED"


ITEM_SPECS = (
    {"sku_code": "DRSS-I1", "color_code": "NAVY", "lifecycle_stage": "CARRYOVER",
     "unit_cost_cents": 2500, "retail_price_cents": 6900,
     "prior_season_sell_through_bps": 7100},
    {"sku_code": "DRSS-I2", "color_code": "BLACK", "lifecycle_stage": "CORE",
     "unit_cost_cents": 2500, "retail_price_cents": 6500,
     "prior_season_sell_through_bps": 6000},
    {"sku_code": "DRSS-I3", "color_code": "CORAL", "lifecycle_stage": "NEW",
     "unit_cost_cents": 2500, "retail_price_cents": 7500,
     "prior_season_sell_through_bps": 0},
    {"sku_code": "DRSS-I4", "color_code": "OLIVE", "lifecycle_stage": "CARRYOVER",
     "unit_cost_cents": 2500, "retail_price_cents": 6900,
     "prior_season_sell_through_bps": 6800},
)
SLOT_HOLDING_STATUSES = {"ADOPTED", "IN_SEASON", "CHASED", "CANCELLED_IN_SEASON"}


def _cell_with_four_proposed_options():
    scenario = setup_single_month_approved_plan()
    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["option_slots_total"] == 14
    assert cell["option_slots_assigned"] == 0
    assert cell["option_slots_open"] == 14
    assert_slot_conservation(cell)
    items = [propose_item(cell["id"], scenario["vendor"]["id"], **spec)
             for spec in ITEM_SPECS]
    # Creation reserves nothing; only adoption does.
    assert_slot_conservation(get_option_plan(cell["id"]))
    assert get_option_plan(cell["id"])["option_slots_assigned"] == 0
    return scenario, cell, items


def test_each_adoption_moves_the_slot_pair_and_a_repeat_moves_nothing(api):
    """Assigned and open move as a conserved pair, and a refused adopt is the control.

    PRD: "The cell's slot counters move as a conserved pair -- `option_slots_assigned` rises by 1
    and `option_slots_open` falls by 1, while `option_slots_total` is untouched". The three
    adoptions price the items through both sell-through variants (7100 * 10500 / 10000 == 7455,
    6000 * 10500 / 10000 == 6300 and, on the new-item basis, 5500 * 11500 * 10000 / 1e8 == 6325),
    which the slot ledger is indifferent to. The repeat adopt is refused per PRD rule 9 --
    "`ERR_INVALID_STATE` (409)" -- and must consume no slot.

    Design: Difficulty/compensating_invariant/option_slot_count_conservation
    """
    _scenario, cell, items = _cell_with_four_proposed_options()

    for index, expected_sell_through in enumerate((7455, 6300, 6325)):
        adopted = adopt_item(items[index]["id"])
        assert adopted["status"] == "ADOPTED"
        assert adopted["planned_units"] == 276
        assert adopted["sell_through_bps"] == expected_sell_through
        current = get_option_plan(cell["id"])
        assert current["option_slots_total"] == 14
        assert current["option_slots_assigned"] == index + 1
        assert current["option_slots_open"] == 13 - index
        assert_slot_conservation(current)

    before_repeat = get_option_plan(cell["id"])
    repeat = api.adopt_assortment_item(items[2]["id"], {}, BUYER_HEADERS)
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    after_repeat = get_option_plan(cell["id"])
    assert after_repeat["option_slots_assigned"] == 3
    assert after_repeat["option_slots_open"] == 11
    assert after_repeat["version"] == before_repeat["version"]
    assert_slot_conservation(after_repeat)


def test_closing_an_option_returns_a_slot_that_a_fourth_option_can_really_use(api):
    """The released slot is genuinely reusable and the pinned total is never recomputed.

    PRD: "every option plan of the plan whose `status` is `OPEN` or `SLOTTED`" is only touched by
    plan closure, and PRD defines the ledger declaratively -- "A cell's `option_slots_assigned`
    is by definition the number of its items whose `status` is `ADOPTED`, `IN_SEASON`, `CHASED`
    or `CANCELLED_IN_SEASON`" -- so a `CLOSED` item stops holding its slot while
    `option_slots_total` and `target_units_per_option`, written once by the slotting cascade,
    stay at 14 and 276. The fourth adoption proves the freed capacity is real rather than a
    decrement.

    Design: Difficulty/compensating_invariant/option_slot_count_conservation
    """
    _scenario, cell, items = _cell_with_four_proposed_options()
    for index in range(3):
        adopt_item(items[index]["id"])

    closed = close_item(items[0]["id"])
    assert closed["status"] == "CLOSED"
    # The close releases the slot without blanking the item's computed history.
    assert closed["planned_units"] == 276
    assert closed["sell_through_bps"] == 7455

    after_close = get_option_plan(cell["id"])
    assert after_close["option_slots_total"] == 14
    assert after_close["option_slots_assigned"] == 2
    assert after_close["option_slots_open"] == 12
    assert after_close["target_units_per_option"] == 276
    assert_slot_conservation(after_close)

    reused = adopt_item(items[3]["id"])
    assert reused["status"] == "ADOPTED"
    assert reused["sell_through_bps"] == 7140
    final = get_option_plan(cell["id"])
    assert final["option_slots_total"] == 14
    assert final["option_slots_assigned"] == 3
    assert final["option_slots_open"] == 11
    assert_slot_conservation(final)

    rows = get_success_data(
        api.list_assortment_items(BUYER_HEADERS,
                                  params={"option_plan_id": cell["id"], "limit": 50}))
    holding = [row for row in rows if row["status"] in SLOT_HOLDING_STATUSES]
    assert len(holding) == final["option_slots_assigned"]
    assert {row["status"] for row in rows if row["id"] == items[0]["id"]} == {"CLOSED"}
