"""Two quantities that must still add up after the compensating move.

Pounds of copper are split across three buckets, and cancelling an order sends a
queued lot's mass back to the uncommitted bucket rather than to scrap, so the
heat returns to exactly the mass it arrived with. Deposit dollars are split three
ways too, and two reels charged the same 450.00 come back under different refund
schedules: the split differs, the total never does.
"""

from test_helpers import (
    BILLING,
    CLERK,
    advance_lot_to_drawn,
    advance_lot_to_tested,
    assert_credit_exposure_identity,
    assert_deposit_ledger_identity,
    assert_lot_dimensions,
    assert_money,
    assert_order_dimensions,
    assert_rod_mass_conserved,
    create_lot,
    create_reel,
    create_reel_return_payload,
    create_shipment_payload,
    current_order_version,
    get_success_data,
    load_reel_payload,
    read_customer,
    read_lot,
    read_order,
    read_reel,
    read_rod_lot,
    release_lot,
    set_clock,
    setup_baseline,
    validate_success,
)

MASS_ORDER = {"order_number": "SO-MASS", "ordered_kft": 12.000}
DEPOSIT_ORDER = {"order_number": "SO-DEP", "ordered_kft": 10.000}
FULL_HEAT = {"purchase_weight_lbs": 20000.00}
SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T12:00:00Z",
}
STEEL_REEL = {
    "reel_serial": "R-DEP-STEEL", "reel_type": "STEEL_RETURNABLE",
    "deposit_usd": 450.00,
}


def _mass_world(api):
    """A full heat carrying two queued lots, 138.60 lbs and 99.00 lbs.

    Returns ``(world, lot_a, lot_b, versions)`` where ``versions`` is the heat's
    version after arrival, after the first allocation and after the second.
    """
    world = setup_baseline(api, order_overrides=MASS_ORDER, rod_overrides=FULL_HEAT)
    versions = [world["rod_lot"]["version"]]
    lot_a = create_lot(api, world, lot_code="LOT-MASS-A", planned_length_ft=7000)
    versions.append(read_rod_lot(api, world["rod_lot"]["id"])["version"])
    lot_b = create_lot(
        api, world, lot_code="LOT-MASS-B", planned_length_ft=5000, **SECOND_LINE_WINDOW
    )
    versions.append(read_rod_lot(api, world["rod_lot"]["id"])["version"])
    return world, lot_a, lot_b, versions


def _deposit_world(api):
    """Two reels of different type, each charged 450.00, both invoiced and awaiting
    return 120 days after they shipped.

    Returns ``(world, wood_reel, steel_reel, shipments)``.
    """
    world = setup_baseline(api, order_overrides=DEPOSIT_ORDER, rod_overrides=FULL_HEAT)
    order = world["order"]
    assert_money(order["quoted_total_usd"], 1089.16, "1067.80 plus a 21.36 surcharge")
    get_success_data(api.price_lock_customer_order(order["id"], BILLING))

    reels = []
    for lot_code, lot_overrides, reel_overrides in (
        ("LOT-DEP-A", {}, {"reel_serial": "R-DEP-WOOD"}),
        ("LOT-DEP-B", SECOND_LINE_WINDOW, STEEL_REEL),
    ):
        lot = create_lot(
            api, world, lot_code=lot_code, planned_length_ft=5000, **lot_overrides
        )
        advance_lot_to_tested(api, lot["id"])
        release_lot(api, lot["id"], 5000)
        reel = create_reel(api, **reel_overrides)
        reel = get_success_data(
            api.load_reel(reel["id"], load_reel_payload(lot["id"], 5000), CLERK)
        )
        reels.append((lot, reel))

    set_clock(api, "2026-08-05T10:00:00Z")
    shipments = []
    for lot, reel in reels:
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(
                    order["id"], lot["id"], reel["id"], 5000,
                    current_order_version(api, order["id"]), ship_date="2026-08-05",
                ),
                CLERK,
            ),
            201,
        )
        shipments.append(shipment)
    for shipment in shipments:
        invoice = get_success_data(api.invoice_shipment(shipment["id"], BILLING))
        assert_money(invoice["invoice_amount_usd"], 544.58, "half the order, invoiced")

    set_clock(api, "2026-12-03T12:00:00Z")
    return world, reels[0][1], reels[1][1], shipments


def _return_reel(api, reel, shipment):
    return get_success_data(
        api.create_reel_return(
            reel["id"],
            create_reel_return_payload(shipment["id"], "2026-12-03", "GOOD"),
            CLERK,
        )
    )


def test_the_three_metal_buckets_hold_after_every_allocation(api):
    """Each allocation moves the same figure out of one bucket and into another, and
    the arrival mass still equals the sum of the three after each write.

    PRD 2.8: "Every received rod lot records the mass it arrived with, and that
    arrival mass is thereafter split across exactly three buckets: mass still
    uncommitted, mass committed to production lots that have neither been scrapped
    nor cancelled, and mass written off as scrap."

    PRD 3.1: "The three buckets move in lockstep, always by the same figure — the
    `consumed_rod_lbs` recorded on the production lot involved. Scheduling a lot
    subtracts that figure from `remaining_lbs` and adds it to `committed_lbs`."

    PRD 3.6: "The mass the lot will draw is computed first, because two later checks
    depend on it: `consumed_rod_lbs` is `planned_length_ft` divided by 1000,
    multiplied by the SKU's `conductor_lbs_per_kft`, rounded half up to two
    decimals."

    Design: Difficulty/compensating_invariant/rod_metal_mass_conserved_across_allocation_and_cancellation
    """
    world = setup_baseline(api, order_overrides=MASS_ORDER, rod_overrides=FULL_HEAT)
    arrived = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(arrived["remaining_lbs"], 20000.00, "the whole heat is uncommitted")
    assert_money(arrived["committed_lbs"], 0.00, "nothing committed")
    assert_money(arrived["scrapped_lbs"], 0.00, "nothing written off")
    assert_rod_mass_conserved(arrived)

    lot_a = create_lot(api, world, lot_code="LOT-MASS-A", planned_length_ft=7000)
    assert_money(lot_a["consumed_rod_lbs"], 138.60, "7.0 kft at 19.8 lbs per kft")
    after_a = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(after_a["remaining_lbs"], 19861.40, "20000.00 less 138.60")
    assert_money(after_a["committed_lbs"], 138.60, "the first lot's mass")
    assert_rod_mass_conserved(after_a)

    lot_b = create_lot(
        api, world, lot_code="LOT-MASS-B", planned_length_ft=5000, **SECOND_LINE_WINDOW
    )
    assert_money(lot_b["consumed_rod_lbs"], 99.00, "5.0 kft at 19.8 lbs per kft")
    after_b = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(after_b["remaining_lbs"], 19762.40, "19861.40 less 99.00")
    assert_money(after_b["committed_lbs"], 237.60, "138.60 plus 99.00")
    assert_money(after_b["scrapped_lbs"], 0.00, "scheduling never writes off metal")
    assert_rod_mass_conserved(after_b)
    assert arrived["version"] < after_a["version"] < after_b["version"], (
        "each movement of the ledger is a distinct write on the heat"
    )


def test_the_cancellation_returns_every_pound_to_the_uncommitted_bucket(api):
    """Cancelling the order sends both queued lots' mass back to `remaining_lbs`
    exactly — not to `scrapped_lbs` — so the heat is byte-for-byte the mass it
    arrived with and no quarantine alarm can fire.

    PRD 3.5: "For each such lot, its `consumed_rod_lbs` moves out of the rod lot's
    `committed_lbs` and back into that rod lot's `remaining_lbs`, never into
    `scrapped_lbs`, because a queued lot has not been drawn; the rod lot's
    `version` is incremented by one for each movement."

    PRD 3.5: "Throughout, the arrival mass still equals the sum of the three
    buckets, and `remaining_lbs` returns to exactly the value it held before the lot
    was scheduled."

    PRD 2.8: "Mass on a lot that was cancelled while still queued was never drawn at
    all, so it returns to the uncommitted bucket and is never recorded as scrap.
    Only the first kind of loss can trigger a quarantine."

    Design: Difficulty/compensating_invariant/rod_metal_mass_conserved_across_allocation_and_cancellation
    """
    world, lot_a, lot_b, versions = _mass_world(api)

    cancelled = get_success_data(
        api.cancel_customer_order(
            world["order"]["id"], BILLING, {"reason": "contractor pulled the project"}
        )
    )
    assert_order_dimensions(cancelled, "QUOTED", "CANCELLED")

    restored = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(restored["remaining_lbs"], 20000.00, "the pre-allocation value")
    assert_money(restored["committed_lbs"], 0.00, "nothing is committed any more")
    assert_money(restored["scrapped_lbs"], 0.00, "the compensation is not the scrap path")
    assert restored["status"] == "RECEIVED", (
        "with a scrap percentage of 0.00 no quarantine cascade can fire"
    )
    assert_rod_mass_conserved(restored)
    assert restored["version"] > versions[2] > versions[1] > versions[0], (
        "arrival, two allocations and the compensation are four distinct writes"
    )

    for lot in (lot_a, lot_b):
        closed = read_lot(api, lot["id"])
        assert_lot_dimensions(closed, "SCRAP_CLOSED", "PENDING")
        assert_money(
            closed["consumed_rod_lbs"], lot["consumed_rod_lbs"],
            "the lot keeps the record of what it returned",
        )


def test_a_lot_that_has_been_drawn_keeps_its_pounds_committed(api):
    """The compensation only reaches lots still at `QUEUED`: the drawn lot is skipped,
    its mass stays committed, and the three buckets still sum to the arrival mass
    even though `remaining_lbs` cannot come all the way back.

    PRD 3.5: "Every production lot belonging to the cancelled order whose process
    dimension is `QUEUED`, processed in ascending `created_at` order, has its process
    dimension set to `SCRAP_CLOSED` while its quality dimension is left at `PENDING`
    — nothing was ever produced, so nothing is scrapped — and its `version`
    incremented by one."

    PRD 2.7: "A hop never revisits a record it has already moved within the same
    request, and a record that fails a hop's own precondition is simply skipped
    rather than causing the request to fail."

    PRD 3.6: "Drawing advances the lot `QUEUED` → `DRAWN` on the process dimension."

    Design: Difficulty/compensating_invariant/rod_metal_mass_conserved_across_allocation_and_cancellation
    """
    world, lot_a, lot_b, _ = _mass_world(api)
    advance_lot_to_drawn(api, lot_a["id"])
    assert_lot_dimensions(read_lot(api, lot_a["id"]), "DRAWN", "PENDING")

    get_success_data(
        api.cancel_customer_order(
            world["order"]["id"], BILLING, {"reason": "contractor pulled the project"}
        )
    )

    assert_lot_dimensions(read_lot(api, lot_a["id"]), "DRAWN", "PENDING")
    assert_lot_dimensions(read_lot(api, lot_b["id"]), "SCRAP_CLOSED", "PENDING")

    partial = read_rod_lot(api, world["rod_lot"]["id"])
    assert_money(partial["committed_lbs"], 138.60, "the drawn lot's mass stays out")
    assert_money(partial["remaining_lbs"], 19861.40, "only the queued lot's 99.00 came back")
    assert_money(partial["scrapped_lbs"], 0.00, "and still nothing is scrapped")
    assert_rod_mass_conserved(partial)
    assert partial["remaining_lbs"] != 20000.00, (
        "the invariant holds without the uncommitted bucket being restored in full"
    )


def test_the_deposit_ledger_holds_while_two_deposits_are_outstanding(api):
    """Two reels ship and two invoices land: the lifetime charge and the outstanding
    balance are both 900.00 with nothing yet credited or forfeited, and exposure is
    the invoiced money plus the deposits.

    PRD 2.9: "The deposit ledger obeys a strict invariant: after every reel return,
    the lifetime total of deposits charged to an account must equal the sum of
    deposits still outstanding, deposit value credited back to the account, and
    deposit value forfeited."

    PRD 3.8: "The holding account's `deposit_charged_total_usd` and
    `reel_deposit_balance_usd` are each increased by the reel's `deposit_usd`, after
    which `credit_exposure_usd` is recomputed and the account's standing
    re-evaluated."

    PRD 3.9: "The account's `open_ar_usd` is increased by `invoice_amount_usd`,
    `credit_exposure_usd` is recomputed, and the account auto-transitions `ACTIVE` →
    `CREDIT_HOLD` when the recomputed exposure is strictly greater than
    `credit_limit_usd`."

    Design: Difficulty/compensating_invariant/reel_deposit_money_conserved_across_two_refund_variants
    """
    world, wood, steel, _ = _deposit_world(api)

    assert_money(wood["deposit_usd"], 450.00, "the wood reel's deposit")
    assert_money(steel["deposit_usd"], 450.00, "and the steel reel's, identical")

    account = read_customer(api, world["customer"]["id"])
    assert_money(account["deposit_charged_total_usd"], 900.00, "two deposits charged")
    assert_money(account["reel_deposit_balance_usd"], 900.00, "both still outstanding")
    assert_money(account["credit_memo_balance_usd"], 0.00, "nothing credited back")
    assert_money(account["forfeited_deposit_total_usd"], 0.00, "nothing forfeited")
    assert_deposit_ledger_identity(account)

    assert_money(account["open_ar_usd"], 1089.16, "544.58 twice over")
    assert_money(account["credit_exposure_usd"], 1989.16, "1089.16 plus 900.00")
    assert_credit_exposure_identity(account)
    assert_order_dimensions(read_order(api, world["order"]["id"]), "INVOICED", "FULFILLED")


def test_the_flat_step_return_halves_its_deposit_and_the_ledger_still_balances(api):
    """At 120 days out the wood schedule refunds half and forfeits half, and the
    900.00 charged now splits three ways across outstanding, credited and
    forfeited without a cent going missing.

    PRD 3.9: "A `WOOD_RETURNABLE` reel returned in `GOOD` condition follows a flat
    step schedule recorded as `FLAT_STEP`: the whole `deposit_usd` is refunded when
    `days_out` is at most 90; half the deposit, rounded half up to two decimals, is
    refunded when `days_out` is greater than 90 and at most 180; and nothing is
    refunded once `days_out` exceeds 180."

    PRD 3.9: "In the first hop the holding account's `reel_deposit_balance_usd` is
    decreased by the reel's `deposit_usd`, then its `credit_memo_balance_usd` is
    increased by `refund_usd`, then its `forfeited_deposit_total_usd` is increased by
    `forfeited_usd`."

    PRD 2.9: "Refunds and forfeitures therefore always sum to the deposit that was
    charged, and a return never leaves value unaccounted for."

    Design: Difficulty/compensating_invariant/reel_deposit_money_conserved_across_two_refund_variants
    """
    world, wood, _, shipments = _deposit_world(api)

    settlement = _return_reel(api, wood, shipments[0])

    assert settlement["days_out"] == 120, "2026-08-05 out to 2026-12-03 back"
    assert settlement["refund_variant_applied"] == "FLAT_STEP"
    assert_money(settlement["refund_usd"], 225.00, "half of 450.00, past 90 days")
    assert_money(settlement["forfeited_usd"], 225.00, "and half kept back")

    account = read_customer(api, world["customer"]["id"])
    assert_money(account["deposit_charged_total_usd"], 900.00, "the charge is untouched")
    assert_money(account["reel_deposit_balance_usd"], 450.00, "one reel is still out")
    assert_money(account["credit_memo_balance_usd"], 225.00, "the refund")
    assert_money(account["forfeited_deposit_total_usd"], 225.00, "the forfeiture")
    assert_deposit_ledger_identity(account)
    assert_money(account["credit_exposure_usd"], 1314.16, "1089.16 plus 450.00 less 225.00")
    assert_credit_exposure_identity(account)


def test_two_refund_variants_split_the_same_charge_differently(api):
    """The steel reel out for the same 120 days refunds 234.00 against the wood
    reel's 225.00, so the identical 900.00 charged settles 459.00 credited against
    441.00 forfeited — a different split of the same conserved total.

    PRD 3.9: "A `STEEL_RETURNABLE` reel returned in `GOOD` condition follows a daily
    decay schedule recorded as `DAILY_DECAY`: the refund percentage is the greater of
    thirty percent and one minus four thousandths multiplied by `days_out`, and
    `refund_usd` is `deposit_usd` multiplied by that percentage, rounded half up to
    two decimals; the percentage itself is never rounded before it multiplies the
    deposit."

    PRD 3.9: "To make the difference concrete, at 120 days out a deposit of 450.00
    refunds 234.00 under the steel schedule against 225.00 under the wood schedule."

    PRD 3.9: "After every return the invariant of §2.9 must hold exactly:
    `deposit_charged_total_usd` equals `reel_deposit_balance_usd` plus
    `credit_memo_balance_usd` plus `forfeited_deposit_total_usd`."

    Design: Difficulty/compensating_invariant/reel_deposit_money_conserved_across_two_refund_variants
    """
    world, wood, steel, shipments = _deposit_world(api)
    flat = _return_reel(api, wood, shipments[0])

    decayed = _return_reel(api, steel, shipments[1])

    assert decayed["days_out"] == 120, "the same time on the road"
    assert decayed["refund_variant_applied"] == "DAILY_DECAY"
    assert_money(decayed["refund_usd"], 234.00, "450.00 times 0.52")
    assert_money(decayed["forfeited_usd"], 216.00, "450.00 less 234.00")
    assert decayed["refund_usd"] > flat["refund_usd"], (
        "the same deposit and the same days out refund more on steel than on wood"
    )

    account = read_customer(api, world["customer"]["id"])
    assert_money(account["deposit_charged_total_usd"], 900.00, "never reversed")
    assert_money(account["reel_deposit_balance_usd"], 0.00, "both reels are back")
    assert_money(account["credit_memo_balance_usd"], 459.00, "225.00 plus 234.00")
    assert_money(account["forfeited_deposit_total_usd"], 441.00, "225.00 plus 216.00")
    assert_deposit_ledger_identity(account)
    assert_money(account["credit_exposure_usd"], 630.16, "1089.16 less 459.00")
    assert account["status"] == "ACTIVE"

    for reel in (wood, steel):
        back = read_reel(api, reel["id"])
        assert back["status"] == "AVAILABLE"
        assert back["cycle_count"] == 1, "one completed ship-and-return cycle"
        assert back["loaded_length_ft"] == 0
