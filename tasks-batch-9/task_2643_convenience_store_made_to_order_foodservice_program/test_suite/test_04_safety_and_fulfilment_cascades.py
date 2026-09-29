"""Single writes with long consequences: a failed probe reading that empties a
case and lands on the inspection summary, and a last ticket that sells a pan out.
"""

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_batch_quantity_ledger,
    assert_store_readiness,
    assert_waste_log,
)
from test_helpers.test_users import FOOD_SAFETY_LEAD_HEADERS, SHIFT_LEAD_HEADERS
from prd_bench_local_runner.testing import validate_paginated, validate_success


def _two_holding_pans_in_one_case(api):
    """Forty pretzels in slot 1 and twenty in slot 2 of the same bakery case.

    Neither pan carries reservations, so both are exposed to an impairment sweep.
    """
    X.set_clock(api, "2026-08-01T08:00:00Z")
    store = X.create_store(api, is_fuel_site=False)
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    batch_a = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=1, planned_qty=40, bake_start_at="2026-08-01T08:00:00Z",
    )
    batch_b = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=2, planned_qty=20, bake_start_at="2026-08-01T08:00:00Z",
    )
    return store, unit, batch_a, batch_b


def test_an_out_of_band_probe_reading_impairs_the_unit_and_counts_a_strike(api, associate):
    """A 120-degree reading against a 135-to-185 band is recorded as failing, takes
    the unit out of service and raises its consecutive-failure count to one.

    PRD: "A unit in `OPERATIONAL` goes `OPERATIONAL → IMPAIRED`, and its
    `consecutive_out_of_range_count` increases by one, reaching 1."

    Design: Difficulty/transitive_cascade/out_of_range_temperature_log_cascades_five_levels_to_store_ledger
    """
    store, unit, _batch_a, _batch_b = _two_holding_pans_in_one_case(api)
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 2

    log = validate_success(api.create_temperature_log(unit["id"], {"reading_f": 120}, associate), 201)
    assert log["in_range"] is False

    after_unit = X.read_holding_unit(api, unit["id"])
    assert after_unit["status"] == "IMPAIRED"
    assert after_unit["consecutive_out_of_range_count"] == 1


def test_impairment_sweeps_every_unreserved_pan_in_the_unit_and_writes_both_off(
    api, associate
):
    """The single reading fans out sideways: both sibling pans are written off in
    full and each gets its own waste record on both valuation bases.

    PRD: "Every production batch in that unit whose status is `HOLDING` and whose
    `reserved_qty` is zero goes `HOLDING → DISCARDED`"

    Design: Difficulty/transitive_cascade/out_of_range_temperature_log_cascades_five_levels_to_store_ledger
    """
    _store, unit, batch_a, batch_b = _two_holding_pans_in_one_case(api)

    validate_success(api.create_temperature_log(unit["id"], {"reading_f": 120}, associate), 201)

    after_a = X.read_batch(api, batch_a["id"])
    after_b = X.read_batch(api, batch_b["id"])
    assert after_a["status"] == "DISCARDED"
    assert after_a["remaining_qty"] == 0
    assert after_a["discarded_qty"] == 40
    assert after_b["status"] == "DISCARDED"
    assert after_b["remaining_qty"] == 0
    assert after_b["discarded_qty"] == 20
    assert_batch_quantity_ledger(after_a)
    assert_batch_quantity_ledger(after_b)

    rows_a, _ = validate_paginated(api.list_batch_waste_logs(batch_a["id"], SHIFT_LEAD_HEADERS))
    rows_b, _ = validate_paginated(api.list_batch_waste_logs(batch_b["id"], SHIFT_LEAD_HEADERS))
    assert_waste_log(
        rows_a[0],
        {"reason": "UNIT_IMPAIRED", "qty": 40, "food_cost_cents": 1600,
         "retail_value_cents": 7960},
    )
    assert_waste_log(
        rows_b[0],
        {"reason": "UNIT_IMPAIRED", "qty": 20, "food_cost_cents": 800,
         "retail_value_cents": 3980},
    )


def test_the_sweep_lands_on_the_store_ledger_and_frees_both_hot_case_slots(api, associate):
    """Both write-offs accumulate onto the store's waste money and each releases
    the slot its pan held, emptying the case.

    PRD: "Each swept batch adds its food-cost valuation to the store's
    `waste_cost_cents_mtd`, decrements the store's `hot_case_slots_used` by one,
    increments the store's `version`, and increments its own `version` by one."

    Design: Difficulty/transitive_cascade/out_of_range_temperature_log_cascades_five_levels_to_store_ledger
    """
    store, unit, _batch_a, _batch_b = _two_holding_pans_in_one_case(api)

    validate_success(api.create_temperature_log(unit["id"], {"reading_f": 120}, associate), 201)

    after_store = X.read_store(api, store["id"])
    assert after_store["waste_cost_cents_mtd"] == 2400
    assert after_store["hot_case_slots_used"] == 0


def test_the_inspection_summary_at_the_far_end_reports_one_impaired_unit_at_risk(
    api, associate
):
    """Five levels down from the reading, the readiness verdict shows one impaired
    unit, no lock-outs, full logging compliance and the combined retail exposure.

    PRD: "otherwise it is `AT_RISK` when at least one corrective action is open, or
    at least one unit is impaired, or the compliance percentage is below 90"

    Design: Difficulty/transitive_cascade/out_of_range_temperature_log_cascades_five_levels_to_store_ledger
    """
    store, unit, _batch_a, _batch_b = _two_holding_pans_in_one_case(api)

    validate_success(api.create_temperature_log(unit["id"], {"reading_f": 120}, associate), 201)

    readiness = validate_success(api.get_store_readiness(store["id"], FOOD_SAFETY_LEAD_HEADERS))
    assert_store_readiness(
        readiness,
        {
            "units_impaired_count": 1,
            "units_locked_out_count": 0,
            "temp_log_compliance_pct": 100,
            "retail_waste_exposure_cents": 11940,
            "readiness_status": "AT_RISK",
        },
    )


def _order_reserving_a_whole_pan(api):
    """An order taking all forty pretzels plus a coffee, with the coffee in progress.

    The pan is fully reserved, so the only thing standing between it and
    exhaustion is the one open beverage ticket.
    """
    X.set_clock(api, "2026-08-01T11:00:00Z")
    store = X.create_store(api, is_fuel_site=False)
    X.transition_daypart(api, store["id"], "LUNCH")
    X.create_published_plan(api, store["id"], daypart="LUNCH")
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    coffee = X.create_coffee(api, included_premium_count=0, is_catering_eligible=True)
    batch = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=1, planned_qty=40, bake_start_at="2026-08-01T11:00:00Z",
    )
    order = X.create_draft_order(api, store["id"], channel="TOUCHSCREEN")
    pretzel_line = X.add_order_line(api, order["id"], pretzel["id"], 40)
    X.add_order_line(api, order["id"], coffee["id"], 1)
    placed = X.place_order(api, order["id"])
    X.authorize_order(api, order["id"], "CASH")
    ticket = X.find_ticket(api, order["id"], "BEVERAGE")
    X.start_ticket(api, ticket["id"])
    return store, batch, order, pretzel_line, ticket, placed


def test_placement_reserves_the_whole_pan_against_the_par_baked_line(api):
    """Committing the order moves all forty case units into reservation, leaving
    nothing available, and stamps the fulfilling pan onto the line.

    PRD: "The five counters mean, respectively, the cumulative units ever baked into
    the batch, the units available on the case right now, the units held for placed
    orders that have not yet gone ready"

    Design: Difficulty/transitive_cascade/last_ticket_completion_cascades_order_to_ready_and_batch_to_sold_out
    """
    _store, batch, _order, pretzel_line, _ticket, placed = _order_reserving_a_whole_pan(api)

    assert placed["production_status"] == "PLACED"
    before = X.read_batch(api, batch["id"])
    assert before["reserved_qty"] == 40
    assert before["remaining_qty"] == 0
    assert_batch_quantity_ledger(before)

    line = X.read_order_line(api, pretzel_line["id"])
    assert line["fulfillment_batch_id"] == batch["id"]
    assert line["reserved_qty"] == 40


def test_finishing_the_last_ticket_runs_the_order_all_the_way_to_ready(api, associate):
    """One completion carries the order through assembly and straight on to ready,
    because a walk-in order has no window to wait for, while the money axis stays
    exactly where authorization left it.

    PRD: "An order entering `ASSEMBLED` advances immediately to `READY` when either
    the `channel` is `TOUCHSCREEN`, or the current logical clock has reached the
    order's `pickup_window_start`."

    Design: Difficulty/transitive_cascade/last_ticket_completion_cascades_order_to_ready_and_batch_to_sold_out
    """
    _store, _batch, order, _line, ticket, _placed = _order_reserving_a_whole_pan(api)

    done = validate_success(api.complete_kitchen_ticket(ticket["id"], {}, associate))
    assert done["status"] == "DONE"

    after = X.read_order(api, order["id"])
    assert after["production_status"] == "READY"
    assert after["settlement_status"] == "AUTHORIZED"
    assert after["subtotal_gross_cents"] == 8209
    assert after["total_cents"] == 8209


def test_going_ready_converts_reservations_to_sales_and_sells_the_pan_out(api, associate):
    """The reserved units become sold units, the line releases its hold, and the
    exhausted pan ends SOLD_OUT rather than DISCARDED, giving its slot back.

    PRD: "For every batch touched this way, if both its `remaining_qty` and its
    `reserved_qty` are now zero the batch advances `HOLDING → SOLD_OUT`"

    Design: Difficulty/transitive_cascade/last_ticket_completion_cascades_order_to_ready_and_batch_to_sold_out
    """
    store, batch, _order, pretzel_line, ticket, _placed = _order_reserving_a_whole_pan(api)

    validate_success(api.complete_kitchen_ticket(ticket["id"], {}, associate))

    after_batch = X.read_batch(api, batch["id"])
    assert after_batch["status"] == "SOLD_OUT"
    assert after_batch["sold_qty"] == 40
    assert after_batch["reserved_qty"] == 0
    assert after_batch["remaining_qty"] == 0
    assert after_batch["discarded_qty"] == 0
    assert_batch_quantity_ledger(after_batch)

    line = X.read_order_line(api, pretzel_line["id"])
    assert line["reserved_qty"] == 0
    assert line["fulfillment_batch_id"] == batch["id"]

    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 0
