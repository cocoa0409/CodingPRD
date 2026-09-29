"""Three quantities are conserved, and every compensating action restores them exactly.

Aborting a run puts the chamber's units back where they came from; cancelling a
loaded run puts the committed slot back into the available bucket; waiving a line
puts the money back without destroying the row that recorded it.  In each case the
identity is checked, not just the field that moved.
"""

from test_helpers import (
    ADMIN_ROOT,
    assert_chargeback_balance_conserved,
    assert_slot_ledger_conserved,
    assert_unit_ledger_conserved,
    list_chargeback_lines,
    read_cold_room,
    read_contract,
    read_customer,
    read_cycle,
    read_load,
    read_lot,
    read_vessel,
    setup_exhausted_spot_contract_world,
    setup_inspected_load,
    setup_running_cycle,
    terminate_cycle,
    waive_chargeback_line,
)
from test_helpers.fixtures import OPERATOR


# --------------------------------------------------------------------------- #
# the unit ledger: abort is the exact inverse of start
# --------------------------------------------------------------------------- #
def test_aborting_a_running_cycle_returns_every_unit_to_the_untreated_pool():
    """Starting the run moved 1000 units into the chamber; the abort moves the same
    1000 back, and no unit lands in the treated or disposed bucket.

    PRD 3.6: "A cycle at `RUNNING` advances `RUNNING → ABORTED`, which additionally
    returns the vessel `IN_USE → AVAILABLE` and compensates the unit ledger exactly:
    each referenced pallet moves its `units_in_vessel` back into `units_untreated` and
    retreats `IN_VESSEL → IN_COLD_STORAGE`."
    PRD 2.9: "The **unit ledger** on a pallet holds that `unit_count` always equals
    `units_untreated` plus `units_in_vessel` plus `units_treated` plus
    `units_disposed`, after every single request that touches the pallet."

    Design: Difficulty/compensating_invariant/abort_returns_units_to_the_untreated_pool
    """
    world = setup_running_cycle()
    assert_unit_ledger_conserved(world["lot"])
    assert world["lot"]["units_in_vessel"] == 1000

    terminate_cycle(
        world["cycle"]["id"],
        reason="intensifier seal failure mid-run",
        headers=OPERATOR,
    )
    lot = read_lot(world["lot"]["id"])

    assert read_cycle(world["cycle"]["id"])["state"] == "ABORTED"
    assert lot["units_untreated"] == 1000
    assert lot["units_in_vessel"] == 0
    assert lot["units_treated"] == 0
    assert lot["units_disposed"] == 0
    assert_unit_ledger_conserved(lot)


def test_the_aborted_run_leaves_the_pallet_stored_and_nothing_billable():
    """The pallet retreats to cold storage rather than into a terminal state, its
    room position is unaffected, and the run is not billable at all.

    PRD 3.6: "Because an aborted run never writes a control-point record, the cycle's
    `actual_cycle_seconds` stays null and nothing about it is billable."
    PRD 3.1: "That counter tracks how many cycles on this machine have reached either
    `COMPLETED_CLEAN` or `COMPLETED_DEVIATED`."

    Design: Difficulty/compensating_invariant/abort_returns_units_to_the_untreated_pool
    """
    world = setup_running_cycle()

    terminate_cycle(
        world["cycle"]["id"],
        reason="intensifier seal failure mid-run",
        headers=OPERATOR,
    )
    lot = read_lot(world["lot"]["id"])
    cycle = read_cycle(world["cycle"]["id"])
    vessel = read_vessel(world["vessel"]["id"])
    room = read_cold_room(world["room"]["id"])

    assert lot["custody_state"] == "IN_COLD_STORAGE"
    assert lot["release_state"] == "NOT_RELEASED"
    assert cycle["actual_cycle_seconds"] is None
    assert cycle["actual_tolling_fee_cents"] is None
    assert vessel["status"] == "AVAILABLE"
    assert vessel["cycles_run_count"] == 0
    assert room["occupied_pallets"] == 1
    assert room["capacity_state"] == "NORMAL"


# --------------------------------------------------------------------------- #
# the slot ledger: cancel returns the committed slot
# --------------------------------------------------------------------------- #
def test_cancelling_a_loaded_cycle_voids_its_load_and_frees_the_slot():
    """A VOIDED load belongs to no bucket at all, which is why the single committed
    slot returns to `available_slots` with no drift.

    PRD 3.6: "A cycle at `LOADED` advances `LOADED → CANCELLED` and unwinds its
    bookings: every load whose `disposition_state` is `PENDING` becomes `VOIDED`, each
    backing contract's `reserved_slots` is recomputed downward so `available_slots`
    rises by one per voided load, and any contract sitting at `EXHAUSTED` returns
    `EXHAUSTED → ACTIVE` once its recomputed `available_slots` is at least 1."
    PRD 2.9: "Loads that end up `VOIDED` or `REJECTED` belong to no bucket at all,
    which is precisely why a cancellation, an abort or a rejected deviation returns the
    slot to `available_slots` with zero drift."

    Design: Difficulty/compensating_invariant/cancel_returns_the_contract_slot_to_available
    """
    world = setup_exhausted_spot_contract_world()
    assert world["contract"]["status"] == "EXHAUSTED"
    assert_slot_ledger_conserved(world["contract"])

    terminate_cycle(world["cycle"]["id"], reason="customer pulled the shipment")
    contract = read_contract(world["contract"]["id"])
    load = read_load(world["load"]["id"])

    assert read_cycle(world["cycle"]["id"])["state"] == "CANCELLED"
    assert load["disposition_state"] == "VOIDED"
    assert load["allocated_fee_cents"] is None
    assert contract["reserved_slots"] == 0
    assert contract["consumed_slots"] == 0
    assert contract["available_slots"] == 1
    assert_slot_ledger_conserved(contract)


def test_the_freed_slot_walks_the_contracts_status_back_to_active():
    """The derived status oscillates back the moment the ledger has a slot again, and
    the pallet — which never entered the chamber — is untouched.

    PRD 3.3: "Each time a compensating action gives a slot back — a cycle cancelled or
    aborted, or a deviation adjudicated as a rejection — the ledger is recomputed again
    and a contract sitting at `EXHAUSTED` returns `EXHAUSTED → ACTIVE` as soon as the
    recomputed `available_slots` is at least 1, again incrementing its `version`."
    PRD 3.6: "A cycle still at `SCHEDULED` simply advances `SCHEDULED → CANCELLED`,
    incrementing its `version`; nothing was reserved, so nothing needs unwinding."

    Design: Difficulty/compensating_invariant/cancel_returns_the_contract_slot_to_available
    """
    world = setup_exhausted_spot_contract_world()

    terminate_cycle(world["cycle"]["id"], reason="customer pulled the shipment")
    contract = read_contract(world["contract"]["id"])
    lot = read_lot(world["lot"]["id"])

    assert contract["status"] == "ACTIVE"
    assert contract["committed_slots"] == 1
    assert lot["custody_state"] == "IN_COLD_STORAGE"
    assert lot["units_untreated"] == 1000
    assert_unit_ledger_conserved(lot)


# --------------------------------------------------------------------------- #
# the chargeback balance: waive reverses the money, not the record
# --------------------------------------------------------------------------- #
def test_waiving_the_line_lowers_the_balance_by_exactly_its_amount():
    """The 6788-cent line raised by a 3000 ppm load comes straight back off the
    balance, leaving no pending money at all.

    PRD 3.9: "Waiving advances the line `PENDING → WAIVED`, stamps
    `waived_by_user_id` with the acting `X-User-ID`, and lowers the charged customer's
    `chargeback_balance_cents` by exactly the line's `amount_cents`, which itself stays
    intact on the row for audit."
    PRD 2.9: "The **chargeback balance** on a customer holds that
    `chargeback_balance_cents` always equals the sum of `amount_cents` over that
    customer's chargeback lines whose `status` is `PENDING`, whatever the line's
    `basis`."

    Design: Difficulty/compensating_invariant/waive_reverses_the_chargeback_balance_exactly
    """
    world = setup_inspected_load()
    lines = list_chargeback_lines(customer_id=world["customer"]["id"])
    assert len(lines) == 1
    assert lines[0]["amount_cents"] == 6788
    assert read_customer(world["customer"]["id"])["chargeback_balance_cents"] == 6788

    waive_chargeback_line(lines[0]["id"])
    customer = read_customer(world["customer"]["id"])

    assert customer["chargeback_balance_cents"] == 0
    assert_chargeback_balance_conserved(
        customer, list_chargeback_lines(customer_id=customer["id"])
    )


def test_the_waived_line_keeps_its_amount_and_its_provenance_for_audit():
    """`amount_cents` still reads 6788 on the WAIVED row, the waiving administrator is
    stamped, and the line still names the load it came from.

    PRD 2.9: "Waiving a line is the compensating action of its creation: it lowers the
    balance by exactly that line's `amount_cents` and leaves the line's own
    `amount_cents` untouched for audit."
    PRD 3.9: "A `PACKAGE_LEAKER` line comes from a load's package inspection and
    carries `cycle_load_id`, with `contract_id` and `deviation_id` null."

    Design: Difficulty/compensating_invariant/waive_reverses_the_chargeback_balance_exactly
    """
    world = setup_inspected_load()
    line_id = list_chargeback_lines(customer_id=world["customer"]["id"])[0]["id"]

    waived = waive_chargeback_line(line_id)

    assert waived["status"] == "WAIVED"
    assert waived["amount_cents"] == 6788
    assert waived["waived_by_user_id"] == ADMIN_ROOT
    assert waived["basis"] == "PACKAGE_LEAKER"
    assert waived["cycle_load_id"] == world["load"]["id"]
    assert waived["contract_id"] is None
    assert waived["deviation_id"] is None


def test_the_loads_own_record_of_the_charge_survives_the_waiver():
    """Reversing the money does not rewrite the measurement: the load still reads
    3000 ppm and still records the 6788 cents it generated.

    PRD 3.8: "Their sum is stored as `chargeback_cents`, and a chargeback line is
    minted with `basis` of `PACKAGE_LEAKER`, `amount_cents` equal to that sum,
    `customer_id` taken from the pallet behind the load, `cycle_load_id` naming this
    load, and `status` of `PENDING`; the customer's `chargeback_balance_cents` is
    recomputed upward accordingly."
    PRD 2.9: "Waived lines are excluded from the sum but are never deleted."

    Design: Difficulty/compensating_invariant/waive_reverses_the_chargeback_balance_exactly
    """
    world = setup_inspected_load()
    line_id = list_chargeback_lines(customer_id=world["customer"]["id"])[0]["id"]

    waive_chargeback_line(line_id)
    load = read_load(world["load"]["id"])

    assert load["leaker_ppm"] == 3000
    assert load["chargeback_cents"] == 6788
    assert len(list_chargeback_lines(customer_id=world["customer"]["id"])) == 1
