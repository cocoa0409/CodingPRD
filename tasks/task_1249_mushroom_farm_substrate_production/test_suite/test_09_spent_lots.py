"""Spent substrate lots: reserve/release/sell/dispose, batch retirement."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_cycle_to_fruiting,
    create_buyer,
    create_room,
    create_scheduled_room_cycle,
    create_spawned_batch,
    get_first_spent_lot_for_cycle,
    get_success_data,
    place_room_cycle,
    report_and_confirm_contamination,
    setup_fruiting_cycle,
    setup_turned_over_cycle_with_spent_lot,
    validate_error,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
COMPOST = TEST_USERS["compost_supervisor_headers"]
SALES = TEST_USERS["sales_manager_headers"]
ANY = TEST_USERS["any_headers"]


def test_spent_lot_reserve_release_cycle(api):
    """PRD §3.8: "Reserving a lot for a buyer requires the lot to be
    `AVAILABLE` ... reservation records the buyer in `reserved_buyer_id`. A
    reservation can be released, returning the lot to `AVAILABLE` and
    clearing `reserved_buyer_id`."
    PRD §3.2: "the turnover produces a `SpentSubstrateLot` whose `tonnage` is
    the cycle's `allocated_tonnage` multiplied by 0.75 and rounded to 2
    decimal places — a 40.0-tonne allocation yields a 30.00-tonne lot."

    Design: Corner/state_machines/spent_lot_reserve_release_cycle
    """
    _variety, _batch, _room, _rc, lot = setup_turned_over_cycle_with_spent_lot()
    buyer = create_buyer(name="Compost Resale Co")

    get_success_data(api.reserve_spent_lot(lot["id"], {"buyer_id": buyer["id"]}, SALES))
    mid = get_success_data(api.get_spent_lot(lot["id"], ANY))
    assert mid["status"] == "RESERVED"
    assert mid["reserved_buyer_id"] == buyer["id"]

    get_success_data(api.release_spent_lot(lot["id"], SALES))
    end = get_success_data(api.get_spent_lot(lot["id"], ANY))
    assert end["status"] == "AVAILABLE"
    assert end["reserved_buyer_id"] is None
    assert end["tonnage"] == pytest.approx(30.0, abs=0.01)


def test_spent_lot_reserve_release_roundtrip_tonnage(api):
    """PRD §3.8: the lot's "tonnage is the cycle's `allocated_tonnage` times
    0.75 rounded to 2 decimal places."
    PRD §3.8: "A reservation can be released, returning the lot to
    `AVAILABLE` and clearing `reserved_buyer_id`."

    Design: Corner/state_machines/spent_lot_reserve_release_cycle
    """
    _variety, _batch, _room, _rc, lot = setup_turned_over_cycle_with_spent_lot()
    buyer = create_buyer()
    assert lot["tonnage"] == pytest.approx(30.0, abs=0.01)

    get_success_data(api.reserve_spent_lot(lot["id"], {"buyer_id": buyer["id"]}, SALES))
    get_success_data(api.release_spent_lot(lot["id"], SALES))
    after = get_success_data(api.get_spent_lot(lot["id"], ANY))
    assert after["status"] == "AVAILABLE"
    assert after["reserved_buyer_id"] is None
    assert after["tonnage"] == pytest.approx(30.0, abs=0.01)


def test_batch_retire_with_unresolved_lots_rejected(api):
    """PRD §3.1: "retirement requires the batch to be `EXHAUSTED` (otherwise
    `ERR_BATCH_NOT_EXHAUSTED`) and requires every room cycle of the batch to
    be in `CLOSED`, `CANCELLED`, or `ABORTED` and every spent substrate lot
    of the batch to be `SOLD` or `DISPOSED`, otherwise
    `ERR_UNRESOLVED_SPENT_LOTS`."

    Here the cycle is only TURNAROUND and the spent lot is still AVAILABLE.

    Design: Corner/state_machines/batch_retire_with_unresolved_lots_rejected
    """
    _variety, batch, _room, rc, lot = setup_turned_over_cycle_with_spent_lot()
    batch_mid = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert batch_mid["status"] == "EXHAUSTED", "full 40t allocation auto-exhausted the batch"

    resp = api.retire_batch(batch["id"], COMPOST)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SPENT_LOTS)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["status"] == "EXHAUSTED"


def test_batch_retire_blocked_until_lots_terminal(api):
    """PRD §3.1: "requires every room cycle of the batch to be in `CLOSED`,
    `CANCELLED`, or `ABORTED` and every spent substrate lot of the batch to
    be `SOLD` or `DISPOSED`, otherwise `ERR_UNRESOLVED_SPENT_LOTS`."

    Design: Corner/state_machines/batch_retire_with_unresolved_lots_rejected
    """
    _variety, batch, _room, rc, lot = setup_turned_over_cycle_with_spent_lot()
    resp = api.retire_batch(batch["id"], COMPOST)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SPENT_LOTS)
    assert get_success_data(api.get_substrate_batch(batch["id"], ANY))["status"] == "EXHAUSTED"


def test_batch_retire_after_full_lifecycle(api):
    """PRD §3.8: "disposing computes `disposal_cost_cents` as the lot's
    `tonnage` times 2500 cents per tonne in tipping fees, rounded to whole
    cents, moves the lot to `DISPOSED`, clears `reserved_buyer_id` if one was
    set, and adds the cost to the batch's `disposal_cost_cents`. Only once
    every spent lot of a batch has reached `SOLD` or `DISPOSED` — and every
    cycle of the batch is terminal — can the batch itself be retired."
    PRD §3.2: "certifying the cleanout moves the cycle `TURNAROUND → CLOSED`
    and returns the room's `occupancy_status` from `TURNAROUND` to `IDLE`."

    Design: Corner/state_machines/batch_retire_after_full_lifecycle
    """
    _variety, batch, room, rc, lot = setup_turned_over_cycle_with_spent_lot()

    get_success_data(api.certify_cleanout_room_cycle(rc["id"], FARM))
    get_success_data(api.dispose_spent_lot(lot["id"], FARM))

    lot_after = get_success_data(api.get_spent_lot(lot["id"], ANY))
    assert lot_after["status"] == "DISPOSED"
    # round(30.0 * 2500) == 75000.
    assert lot_after["disposal_cost_cents"] == 75000

    retired = validate_success(api.retire_batch(batch["id"], COMPOST), expected_status=200)
    assert retired["status"] == "RETIRED"
    assert retired["disposal_cost_cents"] == 75000, (
        "batch rollup sums disposal_cost_cents over DISPOSED lots"
    )

    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "CLOSED"
    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["occupancy_status"] == "IDLE"


def test_batch_retire_full_lifecycle_rolls_up_disposal_cost(api):
    """PRD §3.1: "The batch also carries two computed money ledgers:
    `spent_revenue_cents`, the sum of `sale_price_cents` over its `SOLD`
    spent lots, and `disposal_cost_cents`, the sum of `disposal_cost_cents`
    over its `DISPOSED` spent lots, both starting at 0."

    Design: Corner/state_machines/batch_retire_after_full_lifecycle
    """
    _variety, batch, room, rc, lot = setup_turned_over_cycle_with_spent_lot()
    get_success_data(api.certify_cleanout_room_cycle(rc["id"], FARM))
    get_success_data(api.dispose_spent_lot(lot["id"], FARM))
    retired = validate_success(api.retire_batch(batch["id"], COMPOST), expected_status=200)
    assert retired["status"] == "RETIRED"
    assert retired["disposal_cost_cents"] == 75000
    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["occupancy_status"] == "IDLE"


def test_batch_retire_not_exhausted_rejected(api):
    """PRD §3.1: "retirement requires the batch to be `EXHAUSTED` (otherwise
    `ERR_BATCH_NOT_EXHAUSTED`)."

    Design: Corner/errors/batch_retire_not_exhausted_rejected
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    assert batch["status"] == "SPAWNED"
    assert batch["remaining_tonnage"] == 40.0
    resp = api.retire_batch(batch["id"], COMPOST)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_EXHAUSTED)


def test_spent_lot_sell_at_exact_floor(api):
    """PRD §3.8: "the agreed `sale_price_cents` must be at least the lot's
    `tonnage` times 1500 cents per tonne, rounded to whole cents — a price
    below that floor is rejected with `ERR_PRICE_BELOW_FLOOR`. A sale records
    `sale_price_cents`, moves the lot to `SOLD`, and adds the price to the
    batch's `spent_revenue_cents`."

    Sale at exactly round(30.0 * 1500) = 45000 cents succeeds (floor is
    inclusive >=) and rolls up to the batch.

    Design: Corner/calculations/spent_lot_sell_at_exact_floor
    """
    _variety, batch, _room, _rc, lot = setup_turned_over_cycle_with_spent_lot()
    buyer = create_buyer(name="Compost Resale Co")
    get_success_data(api.reserve_spent_lot(lot["id"], {"buyer_id": buyer["id"]}, SALES))

    sold = validate_success(
        api.sell_spent_lot(lot["id"], {"sale_price_cents": 45000}, SALES),
        expected_status=200,
    )
    assert sold["status"] == "SOLD"
    assert sold["sale_price_cents"] == 45000

    batch_after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert batch_after["spent_revenue_cents"] == 45000


def test_spent_lot_sell_below_floor_rejected(api):
    """PRD §3.8: "the agreed `sale_price_cents` must be at least the lot's
    `tonnage` times 1500 cents per tonne, rounded to whole cents — a price
    below that floor is rejected with `ERR_PRICE_BELOW_FLOOR`."

    Selling a 30.0 t lot for 44999 cents (one cent under the 45000 floor)
    fails.

    Design: Corner/validations/spent_lot_sell_below_floor_rejected
    """
    _variety, _batch, _room, _rc, lot = setup_turned_over_cycle_with_spent_lot()
    buyer = create_buyer(name="Compost Resale Co")
    get_success_data(api.reserve_spent_lot(lot["id"], {"buyer_id": buyer["id"]}, SALES))

    resp = api.sell_spent_lot(lot["id"], {"sale_price_cents": 44999}, SALES)
    validate_error(resp, ApiErrorId.ERR_PRICE_BELOW_FLOOR)
    after = get_success_data(api.get_spent_lot(lot["id"], ANY))
    assert after["status"] == "RESERVED"


def test_spent_lot_disposal_only_reserve_rejected(api):
    """PRD §3.8: "Lots born of a quarantine-cascade abort carry
    `disposal_only` true" and "Reserving a lot for a buyer requires ... the
    lot not to be `disposal_only` (otherwise `ERR_SPENT_LOT_DISPOSAL_ONLY`)."

    Design: Corner/validations/spent_lot_disposal_only_reserve_rejected
    """
    _variety, _batch, room, rc = setup_fruiting_cycle()
    report_and_confirm_contamination(room, rc, severity=4)
    lot = get_first_spent_lot_for_cycle(rc["id"])
    assert lot["disposal_only"] is True

    buyer = create_buyer(name="Compost Resale Co")
    resp = api.reserve_spent_lot(lot["id"], {"buyer_id": buyer["id"]}, SALES)
    validate_error(resp, ApiErrorId.ERR_SPENT_LOT_DISPOSAL_ONLY)
    after = get_success_data(api.get_spent_lot(lot["id"], ANY))
    assert after["status"] == "AVAILABLE"
    assert after["reserved_buyer_id"] is None


def test_spent_lot_sell_from_available_rejected(api):
    """PRD §3.8: "Selling requires the lot to be `RESERVED` (otherwise
    `ERR_SPENT_LOT_INVALID_STATE`)."

    Reservation is a mandatory intermediate step.

    Design: Corner/errors/spent_lot_sell_from_available_rejected
    """
    _variety, _batch, _room, _rc, lot = setup_turned_over_cycle_with_spent_lot()
    resp = api.sell_spent_lot(lot["id"], {"sale_price_cents": 50000}, SALES)
    validate_error(resp, ApiErrorId.ERR_SPENT_LOT_INVALID_STATE)
