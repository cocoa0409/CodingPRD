"""Gram mass and cabinet slots are conserved across the compensating actions."""

from test_helpers.assertions import assert_cabinet_slots_conserved, assert_lot_mass_conserved
from test_helpers.fixtures import (
    cancel_shipment,
    citrus_released_lot,
    create_cabinet,
    create_shipment,
    read_cabinet,
    read_lot,
    read_retention_sample,
    read_shipment,
    store_retention_sample,
    withdraw_retention_sample,
)

RETENTION_FROM = "2026-08-01T00:00:00Z"
RETENTION_UNTIL = "2026-11-01T00:00:00Z"


def _lot_with_cabinet(api, cabinet_code, capacity_slots=4):
    scenario = citrus_released_lot(api, batch_size_g=500)
    scenario["cabinet"] = create_cabinet(api, cabinet_code=cabinet_code,
                                         capacity_slots=capacity_slots,
                                         storage_temp_c=-20)
    return scenario


def test_two_allocations_draw_the_lot_down_to_two_hundred_and_thirty_grams(api):
    """500 g becomes 380 g after retention and 230 g after the shipment.

    The PRD raises `allocated_g` on each allocation — storing an aliquot
    "raises the lot's `allocated_g` by `quantity_g` and lowers its
    `available_g` accordingly", and a shipment "raises the lot's `allocated_g`
    by `shipped_g`" — with `batch_size_g` staying the sum of the two.

    Design: Difficulty/compensating_invariant/lot_gram_mass_conserved_across_shipment_cancel_and_retention_withdraw
    """
    scenario = _lot_with_cabinet(api, "CAB-03")
    assert scenario["lot"]["available_g"] == 500
    assert scenario["lot"]["allocated_g"] == 0
    assert_lot_mass_conserved(scenario["lot"])

    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, RETENTION_FROM, RETENTION_UNTIL)
    after_retention = read_lot(api, scenario["lot"]["id"])
    assert after_retention["available_g"] == 380
    assert_lot_mass_conserved(after_retention)

    create_shipment(api, scenario["lot"]["id"], 150, "US")
    after_shipment = read_lot(api, scenario["lot"]["id"])
    assert after_shipment["available_g"] == 230
    assert after_shipment["allocated_g"] == 270
    assert_lot_mass_conserved(after_shipment)


def test_cancelling_the_shipment_returns_exactly_its_grams(api):
    """The cancellation restores 380 g and 120 g allocated, with no drift.

    The PRD says "Cancellation records the reason and releases the grams: the
    row drops out of the lot's allocation so `available_g` rises by
    `shipped_g`", so the lot lands back on precisely its pre-shipment figures.

    Design: Difficulty/compensating_invariant/lot_gram_mass_conserved_across_shipment_cancel_and_retention_withdraw
    """
    scenario = _lot_with_cabinet(api, "CAB-03")
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, RETENTION_FROM, RETENTION_UNTIL)
    shipment = create_shipment(api, scenario["lot"]["id"], 150, "US")

    cancel_shipment(api, shipment["id"], "Customer deferred the evaluation")

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["available_g"] == 380
    assert lot["allocated_g"] == 120
    assert_lot_mass_conserved(lot)
    assert read_shipment(api, shipment["id"])["status"] == "CANCELLED"


def test_withdrawing_the_aliquot_restores_the_full_batch(api):
    """After both compensations the lot is back at 500 g with nothing allocated.

    The PRD says withdrawal makes the aliquot leave "the lot's allocation so
    `available_g` rises by its `quantity_g`", stamping `withdrawn_at` from the
    logical clock, so the two reversals together return the whole batch.

    Design: Difficulty/compensating_invariant/lot_gram_mass_conserved_across_shipment_cancel_and_retention_withdraw
    """
    scenario = _lot_with_cabinet(api, "CAB-03")
    aliquot = store_retention_sample(api, scenario["lot"]["id"],
                                     scenario["cabinet"]["id"], 120,
                                     RETENTION_FROM, RETENTION_UNTIL)
    shipment = create_shipment(api, scenario["lot"]["id"], 150, "US")
    cancel_shipment(api, shipment["id"], "Customer deferred the evaluation")

    withdraw_retention_sample(api, aliquot["id"],
                              "Retention released after customer sign-off")

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["available_g"] == 500
    assert lot["allocated_g"] == 0
    assert lot["batch_size_g"] == 500
    assert_lot_mass_conserved(lot)

    withdrawn = read_retention_sample(api, aliquot["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_at"] is not None


def test_the_lot_never_leaves_released_while_grams_remain(api):
    """Availability never reaches zero, so the disposition stays RELEASED.

    The PRD drives "`RELEASED → CONSUMED` ... the moment any allocation drives
    the lot's `available_g` to exactly 0", which never happens here: the low
    point is 230 g.

    Design: Difficulty/compensating_invariant/lot_gram_mass_conserved_across_shipment_cancel_and_retention_withdraw
    """
    scenario = _lot_with_cabinet(api, "CAB-03")
    aliquot = store_retention_sample(api, scenario["lot"]["id"],
                                     scenario["cabinet"]["id"], 120,
                                     RETENTION_FROM, RETENTION_UNTIL)
    shipment = create_shipment(api, scenario["lot"]["id"], 150, "US")
    assert read_lot(api, scenario["lot"]["id"])["disposition_status"] == "RELEASED"

    cancel_shipment(api, shipment["id"], "Customer deferred the evaluation")
    withdraw_retention_sample(api, aliquot["id"],
                              "Retention released after customer sign-off")

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["disposition_status"] == "RELEASED"


def test_a_full_cabinet_reports_no_free_slots(api):
    """Three plus one slots fill a four-slot cabinet exactly.

    The PRD computes `slots_available` as "`capacity_slots` less the
    `slot_count` of every `STORED` aliquot in that cabinet whose storage
    interval covers the current logical clock".

    Design: Difficulty/compensating_invariant/cabinet_slot_count_conserved_across_two_withdrawals
    """
    scenario = _lot_with_cabinet(api, "CAB-04")
    assert scenario["cabinet"]["slots_available"] == 4

    big = store_retention_sample(api, scenario["lot"]["id"],
                                 scenario["cabinet"]["id"], 120,
                                 RETENTION_FROM, RETENTION_UNTIL)
    small = store_retention_sample(api, scenario["lot"]["id"],
                                   scenario["cabinet"]["id"], 50,
                                   RETENTION_FROM, RETENTION_UNTIL)

    assert big["slot_count"] == 3
    assert small["slot_count"] == 1
    cabinet = read_cabinet(api, scenario["cabinet"]["id"])
    assert cabinet["slots_available"] == 0
    assert_cabinet_slots_conserved(cabinet, 4)


def test_the_first_withdrawal_returns_the_whole_ceil_derived_slot_count(api):
    """Withdrawing the 120 g aliquot frees three slots, not two or 120.

    The PRD says of withdrawal that "the row leaves the cabinet's occupancy
    calculation so `slots_available` rises by that aliquot's `slot_count`",
    which is the ceiling figure 3.

    Design: Difficulty/compensating_invariant/cabinet_slot_count_conserved_across_two_withdrawals
    """
    scenario = _lot_with_cabinet(api, "CAB-04")
    big = store_retention_sample(api, scenario["lot"]["id"],
                                 scenario["cabinet"]["id"], 120,
                                 RETENTION_FROM, RETENTION_UNTIL)
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           50, RETENTION_FROM, RETENTION_UNTIL)

    withdraw_retention_sample(api, big["id"],
                              "Aliquot consumed by the stability panel")

    cabinet = read_cabinet(api, scenario["cabinet"]["id"])
    assert cabinet["slots_available"] == 3
    assert_cabinet_slots_conserved(cabinet, 1)
    assert read_retention_sample(api, big["id"])["slot_count"] == 3


def test_the_second_withdrawal_restores_the_empty_cabinet_figure(api):
    """Both withdrawals together bring the cabinet back to four free slots.

    Withdrawn aliquots "never occupy slots", so once both rows are `WITHDRAWN`
    the cabinet reports exactly its `capacity_slots` again and the lot's grams
    are all back.

    Design: Difficulty/compensating_invariant/cabinet_slot_count_conserved_across_two_withdrawals
    """
    scenario = _lot_with_cabinet(api, "CAB-04")
    big = store_retention_sample(api, scenario["lot"]["id"],
                                 scenario["cabinet"]["id"], 120,
                                 RETENTION_FROM, RETENTION_UNTIL)
    small = store_retention_sample(api, scenario["lot"]["id"],
                                   scenario["cabinet"]["id"], 50,
                                   RETENTION_FROM, RETENTION_UNTIL)

    withdraw_retention_sample(api, big["id"],
                              "Aliquot consumed by the stability panel")
    withdraw_retention_sample(api, small["id"], "Retention period closed")

    cabinet = read_cabinet(api, scenario["cabinet"]["id"])
    assert cabinet["slots_available"] == 4
    assert_cabinet_slots_conserved(cabinet, 0)

    assert read_retention_sample(api, small["id"])["status"] == "WITHDRAWN"
    assert read_retention_sample(api, small["id"])["slot_count"] == 1

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["available_g"] == 500
    assert lot["allocated_g"] == 0
