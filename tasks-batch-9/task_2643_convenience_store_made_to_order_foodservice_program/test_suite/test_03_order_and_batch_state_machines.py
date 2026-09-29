"""Non-linear movement: the order's two independent status axes, a finished
ticket that goes back on the make line, and a holding pan that re-enters the oven.
"""

from test_helpers import fixtures as X
from test_helpers.assertions import assert_batch_quantity_ledger
from test_helpers.test_users import KITCHEN_ASSOCIATE_2_HEADERS
from prd_bench_local_runner.testing import validate_success


def _hoagie_and_coffee_order(api):
    """A walk-in order spanning two stations, so placement cuts two tickets."""
    X.set_clock(api, "2026-08-01T11:00:00Z")
    store = X.create_store(api, is_fuel_site=False)
    X.transition_daypart(api, store["id"], "LUNCH")
    X.create_published_plan(api, store["id"], daypart="LUNCH")
    hoagie = X.create_hoagie(api)
    coffee = X.create_coffee(api, included_premium_count=0, is_catering_eligible=True)
    order = X.create_draft_order(api, store["id"], channel="TOUCHSCREEN")
    X.add_order_line(api, order["id"], hoagie["id"], 1)
    X.add_order_line(api, order["id"], coffee["id"], 1)
    return store, order


def test_authorizing_tender_moves_the_money_axis_and_leaves_the_kitchen_axis_alone(
    api, terminal
):
    """Money authorization is a money-axis event: the order reads PLACED on the
    kitchen axis and AUTHORIZED on the money axis simultaneously.

    PRD: "A new order opens with a `production_status` of `DRAFT` on the kitchen
    axis and a `settlement_status` of `UNPAID` on the money axis."

    Design: Difficulty/non_linear_state_machine/order_production_and_settlement_axes_advance_independently
    """
    _store, order = _hoagie_and_coffee_order(api)

    placed = validate_success(api.place_order(order["id"], {}, terminal))
    assert placed["production_status"] == "PLACED"
    assert placed["settlement_status"] == "UNPAID"

    authorized = validate_success(
        api.authorize_order(order["id"], {"tender_type": "CARD"}, terminal)
    )
    assert authorized["production_status"] == "PLACED"
    assert authorized["settlement_status"] == "AUTHORIZED"
    assert authorized["subtotal_gross_cents"] == 1148
    assert authorized["total_cents"] == 1148
    assert authorized["tender_type"] == "CARD"


def test_settling_mid_build_leaves_the_order_in_production_while_the_money_is_done(
    api, terminal, associate
):
    """A claimed ticket puts the kitchen axis in production; settling the tender
    then completes the money axis without disturbing it, so the order sits in the
    combination no single-axis reading can express.

    PRD: "where the order was still `PLACED`, it also advances the order `PLACED →
    IN_PRODUCTION` and increments the order's `version` by one."

    Design: Difficulty/non_linear_state_machine/order_production_and_settlement_axes_advance_independently
    """
    _store, order = _hoagie_and_coffee_order(api)
    validate_success(api.place_order(order["id"], {}, terminal))
    validate_success(api.authorize_order(order["id"], {"tender_type": "CARD"}, terminal))
    sandwich = X.find_ticket(api, order["id"], "SANDWICH")
    validate_success(api.start_kitchen_ticket(sandwich["id"], {}, associate))

    settled = validate_success(api.settle_order(order["id"], {}, terminal))
    assert settled["production_status"] == "IN_PRODUCTION"
    assert settled["settlement_status"] == "SETTLED"

    # Finishing only the first of two stations leaves the kitchen axis put.
    validate_success(api.complete_kitchen_ticket(sandwich["id"], {}, associate))
    mid = X.read_order(api, order["id"], terminal)
    assert mid["production_status"] == "IN_PRODUCTION"
    assert mid["settlement_status"] == "SETTLED"


def test_finishing_the_last_ticket_lifts_the_kitchen_axis_without_touching_the_money(
    api, terminal, associate
):
    """With the money axis already settled, the final completion carries the order
    through assembly to ready on the kitchen axis alone.

    PRD: "When after this completion no ticket of the order remains in `QUEUED` or
    `IN_PROGRESS`, the order advances `IN_PRODUCTION → ASSEMBLED` and its `version`
    increments"

    Design: Difficulty/non_linear_state_machine/order_production_and_settlement_axes_advance_independently
    """
    _store, order = _hoagie_and_coffee_order(api)
    validate_success(api.place_order(order["id"], {}, terminal))
    validate_success(api.authorize_order(order["id"], {"tender_type": "CARD"}, terminal))
    sandwich = X.find_ticket(api, order["id"], "SANDWICH")
    beverage = X.find_ticket(api, order["id"], "BEVERAGE")
    # Both tickets are claimed while the money axis still reads AUTHORIZED, since
    # "the owning order's `settlement_status` must be `AUTHORIZED`" to claim one.
    validate_success(api.start_kitchen_ticket(sandwich["id"], {}, associate))
    validate_success(
        api.start_kitchen_ticket(beverage["id"], {}, KITCHEN_ASSOCIATE_2_HEADERS)
    )
    validate_success(api.settle_order(order["id"], {}, terminal))
    validate_success(api.complete_kitchen_ticket(sandwich["id"], {}, associate))

    validate_success(
        api.complete_kitchen_ticket(beverage["id"], {}, KITCHEN_ASSOCIATE_2_HEADERS)
    )

    final = X.read_order(api, order["id"], terminal)
    assert final["production_status"] == "READY"
    assert final["settlement_status"] == "SETTLED"


def _assembled_preorder(api):
    """A pre-order for a 13:00 window, built and finished while the clock reads 11:00.

    Because the window has not opened, the finished order rests in ASSEMBLED
    instead of running on to READY, which is the state rework has to walk back.
    """
    X.set_clock(api, "2026-08-01T11:00:00Z")
    store = X.create_store(api, is_fuel_site=False)
    X.transition_daypart(api, store["id"], "LUNCH")
    X.create_published_plan(api, store["id"], daypart="LUNCH")
    hoagie = X.create_hoagie(api)
    order = X.create_draft_preorder(
        api, store["id"], "2026-08-01T13:00:00Z", "2026-08-01T13:30:00Z"
    )
    X.add_order_line(api, order["id"], hoagie["id"], 1)
    X.place_order(api, order["id"])
    X.authorize_order(api, order["id"], "APP_WALLET")
    ticket = X.find_ticket(api, order["id"], "SANDWICH")
    X.start_ticket(api, ticket["id"])
    X.complete_ticket(api, ticket["id"])
    return store, order, ticket


def test_reopening_a_finished_ticket_returns_it_to_the_make_line_with_rework_counted(
    api, lead
):
    """Done is not the end of a ticket: a shift lead sends it back, the ticket
    re-enters progress, and the identity of the associate who finished it stays on
    the record.

    PRD: "A `ShiftLead`, and only a `ShiftLead`, may send a finished ticket back to
    the make line with a `reason`, driving it `DONE → IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/kitchen_ticket_done_reopens_and_pulls_order_back_from_assembled
    """
    _store, order, ticket = _assembled_preorder(api)
    before = X.read_order(api, order["id"])
    assert before["production_status"] == "ASSEMBLED"

    reopened = validate_success(
        api.reopen_kitchen_ticket(ticket["id"], {"reason": "COLD_SANDWICH_REMAKE"}, lead)
    )

    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["rework_count"] == 1
    assert reopened["completed_by_user_id"] == "assoc-1"


def test_rework_walks_the_order_back_from_assembled_and_books_food_cost_with_no_waste_row(
    api, lead
):
    """The reopen drags the order off assembly, counts rework on the order too, and
    charges the wasted ingredients to the store's rework figure — a food-cost
    charge that leaves the case-waste ledger untouched.

    PRD: "the store's `rework_waste_cents_mtd` increases by the sum, over the
    reopened ticket's lines, of the menu item's `unit_food_cost_cents` multiplied by
    the line's `qty`"

    Design: Difficulty/non_linear_state_machine/kitchen_ticket_done_reopens_and_pulls_order_back_from_assembled
    """
    store, order, ticket = _assembled_preorder(api)

    validate_success(
        api.reopen_kitchen_ticket(ticket["id"], {"reason": "COLD_SANDWICH_REMAKE"}, lead)
    )

    after_order = X.read_order(api, order["id"])
    assert after_order["production_status"] == "IN_PRODUCTION"
    assert after_order["rework_count"] == 1

    after_store = X.read_store(api, store["id"])
    assert after_store["rework_waste_cents_mtd"] == 300
    assert after_store["waste_cost_cents_mtd"] == 0


def test_completing_the_remade_ticket_re_enters_assembly_with_the_rework_count_kept(
    api, lead, associate
):
    """The cycle closes: finishing the reworked ticket returns the order to
    assembly, and the rework counters do not reset on the way through.

    PRD: "A reopen increases the ticket's own `rework_count` by one and the order's
    `rework_count` by one, increments the order's `version`, and increments the
    ticket's `version`."

    Design: Difficulty/non_linear_state_machine/kitchen_ticket_done_reopens_and_pulls_order_back_from_assembled
    """
    _store, order, ticket = _assembled_preorder(api)
    validate_success(
        api.reopen_kitchen_ticket(ticket["id"], {"reason": "COLD_SANDWICH_REMAKE"}, lead)
    )

    validate_success(api.complete_kitchen_ticket(ticket["id"], {}, associate))

    final_order = X.read_order(api, order["id"])
    assert final_order["production_status"] == "ASSEMBLED"
    assert final_order["rework_count"] == 1
    final_ticket = validate_success(api.get_kitchen_ticket(ticket["id"], associate))
    assert final_ticket["status"] == "DONE"
    assert final_ticket["rework_count"] == 1


def _pretzel_pan_on_hold_at_eight(api):
    """Forty pretzels baked and pulled at 08:00, so the case clock reads 12:00."""
    X.set_clock(api, "2026-08-01T08:00:00Z")
    store = X.create_store(api, is_fuel_site=False)
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    batch = X.create_holding_batch(
        api,
        store["id"],
        pretzel["id"],
        unit["id"],
        slot_index=1,
        planned_qty=40,
        bake_start_at="2026-08-01T08:00:00Z",
    )
    return store, unit, pretzel, batch


def test_topping_off_a_holding_pan_sends_it_back_to_baking_and_clears_the_hold_clock(
    api, associate
):
    """Adding twelve units to a case that is already holding raises the cumulative
    bake to 52 and wipes the expiry — the case clock does not carry over.

    PRD: "The top-off adds the `additional_qty` to both `baked_qty` and
    `remaining_qty`, and it clears the hold clock by setting `hold_started_at` and
    `hold_expires_at` back to null"

    Design: Difficulty/non_linear_state_machine/production_batch_top_off_bake_cycles_holding_back_to_baking
    """
    _store, _unit, _pretzel, batch = _pretzel_pan_on_hold_at_eight(api)
    assert batch["hold_expires_at"] == "2026-08-01T12:00:00Z"

    topped = validate_success(
        api.bake_production_batch(batch["id"], {"additional_qty": 12}, associate)
    )

    assert topped["status"] == "BAKING"
    assert topped["baked_qty"] == 52
    assert topped["remaining_qty"] == 52
    assert topped["hold_started_at"] is None
    assert topped["hold_expires_at"] is None


def test_a_top_off_never_consumes_a_second_hot_case_slot(api, associate):
    """The pan never vacated its slot, so the store's occupied-slot count stays at
    one across the backward transition and the second pull.

    PRD: "Critically, the store's `hot_case_slots_used` is *unchanged* by a top-off,
    because the batch already occupies its slot and never gave it up."

    Design: Difficulty/non_linear_state_machine/production_batch_top_off_bake_cycles_holding_back_to_baking
    """
    store, _unit, _pretzel, batch = _pretzel_pan_on_hold_at_eight(api)
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 1

    validate_success(api.bake_production_batch(batch["id"], {"additional_qty": 12}, associate))
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 1

    X.set_clock(api, "2026-08-01T08:30:00Z")
    validate_success(api.pull_production_batch(batch["id"], {}, associate))
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 1


def test_the_second_pull_restarts_the_hold_window_from_the_new_pull_instant(api, associate):
    """Pulling the topped-off pan half an hour later dates the expiry from that
    later pull, and the whole enlarged quantity is on the case with nothing
    reserved, sold or written off.

    PRD: "The pull sets `hold_started_at` to the current logical-clock instant and
    `hold_expires_at` to that instant advanced by the item's `hold_minutes`"

    Design: Difficulty/non_linear_state_machine/production_batch_top_off_bake_cycles_holding_back_to_baking
    """
    _store, _unit, _pretzel, batch = _pretzel_pan_on_hold_at_eight(api)
    validate_success(api.bake_production_batch(batch["id"], {"additional_qty": 12}, associate))
    X.set_clock(api, "2026-08-01T08:30:00Z")

    pulled = validate_success(api.pull_production_batch(batch["id"], {}, associate))

    assert pulled["hold_started_at"] == "2026-08-01T08:30:00Z"
    assert pulled["hold_expires_at"] == "2026-08-01T12:30:00Z"
    assert pulled["status"] == "HOLDING"
    assert pulled["baked_qty"] == 52
    assert pulled["remaining_qty"] == 52
    assert pulled["reserved_qty"] == 0
    assert pulled["sold_qty"] == 0
    assert pulled["discarded_qty"] == 0
    assert_batch_quantity_ledger(pulled)
