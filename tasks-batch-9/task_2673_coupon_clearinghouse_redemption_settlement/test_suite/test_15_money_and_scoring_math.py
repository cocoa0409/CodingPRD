"""Where the rounding point sits, and which row the rate is taken over.

Banded fees priced per lot, one clearing-fee rounding over the summed face,
terms read off the retailer, a fraud pool that ignores unadjudicated coupons,
and a projection that keeps dividing by the sample it was drawn from.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST,
    FRAUD_ANALYST_2_ID,
    OFFICER,
    DisputeStatus,
    FeeTier,
    HandlingFeePolicy,
    IntakeStatus,
    InvoiceStatus,
    ItemStatus,
    LotRejectReason,
    LotStatus,
    PaymentTerms,
    RetailerStatus,
    StatementStatus,
    SettlementStatus,
    ValuationVariant,
    COUNTERFEIT_DATABAR_PAYLOAD,
    assert_fields,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    assert_retailer_unpaid,
    factories as f,
)


def test_01_the_tiered_band_is_chosen_by_this_lot_alone(api, build):
    """Ninety-nine units bill 792 and one more unit bills only 700.

    "The per-unit basis comes from the issuing manufacturer's
    `handling_fee_policy`: under `CONTRACT_RATE` it is simply the offer's
    `handling_fee_cents`, while under `TIERED_RATE` it is banded by **this lot's**
    unit count and not by the submission's — 8 cents per unit for up to 99 units,
    7 cents per unit for 100 through 499 units, and 6 cents per unit at 500 units
    and above."

    "The lot's `handling_fee_cents` is the unit count multiplied by the per-unit
    basis multiplied by the tier multiplier, rounded half up to a whole number of
    cents **at the lot level**."

    "In the same way, `settled_gross_face_value_cents` is the plain integer sum of
    `gross_face_value_cents` over the submission's `VALIDATED` and `REINSTATED`
    lots, and it is the billable gross a statement will copy."

    Design: Corner/calculations/tiered_handling_fee_band_flips_between_ninetynine_and_one_hundred_units
    """
    world = build.market(handling_fee_policy=HandlingFeePolicy.TIERED_RATE,
                         purchase_requirement_units=1)
    retailer_id = world["retailer_id"]
    barcode = world["barcode"]
    assert world["retailer"]["handling_fee_tier"] == FeeTier.STANDARD, (
        "a STANDARD retailer carries the 1.00 multiplier, so the band rate is "
        "visible in the fee unmodified"
    )

    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)
    submission = build.verified_submission(retailer_id, 40)
    under_the_band = build.lot(submission["id"], world["offer_id"],
                               world["manufacturer_id"], 20)
    over_the_band = build.lot(submission["id"], world["offer_id"],
                              world["manufacturer_id"], 20)

    build.capture(under_the_band["id"], f.item_batch(
        19, barcode, "2026-07-10", pos_transaction_ref="POS-1",
        claimed_units=5) + [f.item_payload(
            barcode, "s3://coupon-images/20.jpg", "2026-07-10",
            pos_transaction_ref="POS-1", claimed_units=4)])
    build.capture(over_the_band["id"], f.item_batch(
        20, barcode, "2026-07-10", pos_transaction_ref="POS-1",
        claimed_units=5, uri_stem="s3://coupon-images/q"))

    ninety_nine = validate_success(
        api.finalize_lot(under_the_band["id"], ANALYST))
    assert_fields(ninety_nine, {
        "status": LotStatus.VALIDATED,
        "accepted_qty": 99,
        "valuation_variant": ValuationVariant.FULL_COUNT,
        "projected_accepted_units": 99,
    })
    assert_money(ninety_nine, "gross_face_value_cents", 4950)
    assert_money(ninety_nine, "handling_fee_cents", 792)

    one_hundred = validate_success(
        api.finalize_lot(over_the_band["id"], ANALYST))
    assert_fields(one_hundred, {
        "status": LotStatus.VALIDATED,
        "accepted_qty": 100,
        "projected_accepted_units": 100,
    })
    assert_money(one_hundred, "gross_face_value_cents", 5000)
    assert_money(one_hundred, "handling_fee_cents", 700)

    assert one_hundred["handling_fee_cents"] < ninety_nine["handling_fee_cents"], (
        "the band rate applies to every unit in the lot, so the hundredth unit "
        "lowers the whole bill rather than costing its own 8 cents"
    )
    assert ninety_nine["handling_fee_cents"] != 693, (
        "the offer's own handling_fee_cents of 7 is never read under TIERED_RATE"
    )

    closed = validate_success(api.get_submission(submission["id"], ANALYST))
    assert_fields(closed, {
        "intake_status": IntakeStatus.CLOSED,
        "rejected_lot_count": 0,
        "sorted_lot_count": 2,
    })
    assert_money(closed, "settled_gross_face_value_cents", 9950)
    assert_money(closed, "settled_handling_fee_cents", 1492)

    offer = validate_success(
        api.get_offer(world["offer_id"], world["mfr_headers"]))
    assert offer["accepted_redemption_count"] == 199, (
        "the counter advances by the units each lot cleared, 99 then 100"
    )


def test_02_the_clearing_fee_rounds_once_over_the_summed_face_value(api, build):
    """Two 150-cent statements bill 5 cents of clearing fee, not 2 plus 2.

    "`billed_face_value_cents` is the sum of `gross_face_value_cents` over the
    named statements; `billed_handling_fee_cents` is the sum of their
    `handling_fee_total_cents`."

    "`billed_clearing_fee_cents` is the clearinghouse's own cut: 1.5 percent
    charged on the **summed face value only** and never on the handling fee,
    rounded half up to whole cents — and that single rounding point is over the
    sum, not per statement."

    "`funded_amount_cents` starts at 0 and `funding_shortfall_cents` starts equal
    to `billed_total_cents`, which is the general identity: the shortfall is
    always the billed total minus the funded amount, floored at zero."

    Design: Corner/calculations/invoice_clearing_fee_rounds_once_over_the_summed_face_value
    """
    world = build.market(purchase_requirement_units=1)
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 3)

    statements = []
    for index, (start, end) in enumerate(
            (("2026-07-01", "2026-07-15"), ("2026-07-15", "2026-07-31"))):
        submission = build.verified_submission(retailer_id, 1, start, end)
        lot = build.lot(submission["id"], world["offer_id"],
                        world["manufacturer_id"], 1)
        build.capture(lot["id"], [f.item_payload(
            world["barcode"], f"s3://coupon-images/{index}.jpg", "2026-07-10",
            pos_transaction_ref="POS-1", claimed_units=3)])
        build.finalize(lot["id"])
        statement = build.issue_statement(submission["id"])
        assert_fields(statement, {"status": StatementStatus.DRAFT})
        assert_money(statement, "gross_face_value_cents", 150)
        assert_money(statement, "handling_fee_total_cents", 21)
        assert_money(statement, "provisional_net_cents", 171)
        assert_money(statement, "net_payable_cents", 171)
        assert_rate_equals(statement["holdback_pct"], "0.0000", "holdback_pct")
        assert_nulls(statement, ["manufacturer_invoice_id"])
        statements.append(statement)

    invoice = validate_success(api.create_invoice(f.invoice_payload(
        world["manufacturer_id"], "2026-07-01", "2026-07-31",
        [statements[0]["id"], statements[1]["id"]]), OFFICER), 201)

    assert_money(invoice, "billed_face_value_cents", 300)
    assert_money(invoice, "billed_handling_fee_cents", 42)
    assert_money(invoice, "billed_clearing_fee_cents", 5)
    assert invoice["billed_clearing_fee_cents"] != 4, (
        "rounding 2.25 twice would give 2 plus 2; the single rounding point is "
        "over the summed face value of 300, whose 1.5 percent is 4.5"
    )
    assert_money(invoice, "billed_total_cents", 347)
    assert_money(invoice, "funded_amount_cents", 0)
    assert_money(invoice, "funding_shortfall_cents", 347)
    assert_fields(invoice, {"status": InvoiceStatus.ISSUED})

    billed, meta = validate_paginated(api.list_statements(
        OFFICER, manufacturer_invoice_id=invoice["id"], limit=10))
    assert meta["total_count"] == 2, (
        "both named statements are now reachable through the invoice filter"
    )
    for row in billed:
        assert_fields(row, {"manufacturer_invoice_id": invoice["id"],
                            "status": StatementStatus.DRAFT})


def test_03_the_pay_date_comes_from_the_terms_and_rolls_forward_once(api, build):
    """Two identical shipments, two payment terms, one weekend roll.

    "The term is 15 days for `NET_15`, 30 days for `NET_30` and 45 days for
    `NET_45`."

    "After adding the term, a weekend result rolls **forward** to the following
    Monday — a Saturday advances by two days, a Sunday by one — and the roll is
    applied once and never iterated."

    "From a clock of 2026-08-01, `NET_30` lands on 2026-08-31, a Monday, with no
    roll; `NET_15` from the same clock lands on 2026-08-16, a Sunday, and rolls to
    2026-08-17."

    Design: Corner/calculations/payment_terms_map_and_single_weekend_roll_forward
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    offer = build.active_offer(mfr["id"], offer_code="SOUP50",
                              purchase_requirement_units=1)

    statements = {}
    for label, terms, name in (("short", PaymentTerms.NET_15, "Alder Grocery"),
                               ("long", PaymentTerms.NET_45, "Bayfront Grocers")):
        retailer = build.retailer(legal_name=name, payment_terms=terms)
        build.purchase_record(retailer["id"], offer["id"], "POS-1",
                              "2026-07-10", 5)
        submission = build.verified_submission(retailer["id"], 1,
                                               "2026-07-01", "2026-07-31")
        lot = build.lot(submission["id"], offer["id"], mfr["id"], 1)
        build.capture(lot["id"], [f.item_payload(
            offer["barcode_payload"], f"s3://coupon-images/{label}.jpg",
            "2026-07-10", pos_transaction_ref="POS-1")])
        build.finalize(lot["id"])
        statement = build.issue_statement(submission["id"])
        statements[label] = (retailer, statement)

    rolled = validate_success(
        api.schedule_statement(statements["short"][1]["id"], OFFICER))
    assert_fields(rolled, {
        "scheduled_pay_date": "2026-08-17",
        "status": StatementStatus.SCHEDULED,
    })
    assert_money(rolled, "net_payable_cents", 57)

    unrolled = validate_success(
        api.schedule_statement(statements["long"][1]["id"], OFFICER))
    assert_fields(unrolled, {
        "scheduled_pay_date": "2026-09-15",
        "status": StatementStatus.SCHEDULED,
    })
    assert_money(unrolled, "net_payable_cents", 57)

    assert rolled["scheduled_pay_date"] != "2026-08-16", (
        "fifteen days from the 2026-08-01 clock is a Sunday, which rolls one "
        "day forward rather than staying put"
    )

    for label in ("short", "long"):
        retailer_id = statements[label][0]["id"]
        current = validate_success(api.get_retailer(retailer_id, OFFICER))
        assert_retailer_unpaid(current, 57)


def test_04_only_adjudicated_coupons_enter_the_pool_and_the_score_clamps(
        api, build):
    """Three counterfeits out of four adjudicated, weighted 2.00, capped at 100.

    "The evidence pool is every adjudicated coupon of that retailer: the coupon
    items reachable from the retailer through its submissions and their lots,
    restricted to items whose status is **not** `CAPTURED`."

    "The `duplicate_rate` is multiplied by 1.40, the `misredemption_rate` by 1.00
    and the `counterfeit_rate` by 2.00; the three products are added; the total is
    rounded half up to two decimal places; and the result is clamped so that it
    can never exceed `100.00`."

    "At `90.00` or above the retailer's target status is `SUSPENDED`."

    Design: Corner/calculations/fraud_pool_excludes_captured_items_and_clamps_the_weighted_score
    """
    world = build.market(purchase_requirement_units=1)
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)

    submission = build.verified_submission(retailer_id, 7)
    adjudicated = build.lot(submission["id"], world["offer_id"],
                            world["manufacturer_id"], 4)
    never_finalized = build.lot(submission["id"], world["offer_id"],
                                world["manufacturer_id"], 3)

    build.capture(adjudicated["id"], f.item_batch(
        3, COUNTERFEIT_DATABAR_PAYLOAD, "2026-07-10",
        pos_transaction_ref="POS-1") + [f.item_payload(
            world["barcode"], "s3://coupon-images/4.jpg", "2026-07-10",
            pos_transaction_ref="POS-1")])
    build.capture(never_finalized["id"], f.item_batch(
        3, world["barcode"], "2026-07-10", pos_transaction_ref="POS-1",
        uri_stem="s3://coupon-images/g"))

    valued = validate_success(api.finalize_lot(adjudicated["id"], ANALYST))
    assert_fields(valued, {
        "status": LotStatus.VALIDATED,
        "accepted_qty": 1,
        "rejected_qty": 3,
    })
    assert_money(valued, "gross_face_value_cents", 50)
    assert_money(valued, "handling_fee_cents", 7)

    before = validate_success(api.get_retailer(retailer_id, ANALYST))
    scored = validate_success(
        api.fraud_rescore(retailer_id, before["version"], ANALYST))

    assert_rate_equals(scored["counterfeit_rate"], "75.00", "counterfeit_rate")
    assert_rate_equals(scored["duplicate_rate"], "0.00", "duplicate_rate")
    assert_rate_equals(scored["misredemption_rate"], "0.00",
                       "misredemption_rate")
    assert_rate_equals(scored["fraud_score"], "100.00", "fraud_score")
    assert str(scored["counterfeit_rate"]) != "42.86", (
        "the three coupons of the unfinalized lot are still CAPTURED, so the "
        "denominator is the 4 adjudicated coupons and not all 7"
    )
    assert str(scored["fraud_score"]) != "150.00", (
        "the weighted total of 150.00 is clamped, not stored raw"
    )
    assert_fields(scored, {
        "status": RetailerStatus.SUSPENDED,
        "handling_fee_tier": FeeTier.PROBATION,
        "version": before["version"] + 1,
    })

    untouched = validate_success(
        api.get_lot(never_finalized["id"], ANALYST))
    assert_fields(untouched, {"status": LotStatus.SORTED})
    assert_nulls(untouched, ["adjudicated_at", "adjudicated_by_user_id"])

    still_open = validate_success(api.get_submission(submission["id"], ANALYST))
    assert_fields(still_open, {"intake_status": IntakeStatus.SORTED})


def test_05_the_serial_goes_to_the_coupon_adjudicated_first(api, build):
    """Captured first, adjudicated second, and therefore the duplicate.

    "Only an already-cleared coupon can own a serial: items still in `CAPTURED`
    and items already rejected never win."

    "Otherwise the pool is ranked by `adjudicated_at` ascending, with `created_at`
    ascending as the tie-break, and the earliest such item wins; the item's `id`
    is never consulted as a tie-break."

    "The consequence worth internalising is that the outcome follows adjudication
    order rather than capture order: capture coupon X and then coupon Y, but
    adjudicate Y first, and X becomes the duplicate."

    Design: Corner/calculations/duplicate_owner_is_the_first_adjudicated_not_the_first_captured
    """
    world = build.market(purchase_requirement_units=1)
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)

    submission = build.verified_submission(retailer_id, 2)
    first_lot = build.lot(submission["id"], world["offer_id"],
                          world["manufacturer_id"], 1)
    second_lot = build.lot(submission["id"], world["offer_id"],
                           world["manufacturer_id"], 1)

    captured_first = build.capture(first_lot["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/a.jpg", "2026-07-10",
        serial_number="SER-1", pos_transaction_ref="POS-1")])[0]
    captured_second = build.capture(second_lot["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/b.jpg", "2026-07-10",
        serial_number="SER-1", pos_transaction_ref="POS-1")])[0]

    owner = validate_success(
        api.adjudicate_item(captured_second["id"], ANALYST))
    assert_fields(owner, {"status": ItemStatus.ACCEPTED})
    assert_nulls(owner, ["reject_code", "duplicate_of_item_id"])

    loser = validate_success(
        api.adjudicate_item(captured_first["id"], ANALYST))
    assert_fields(loser, {
        "status": ItemStatus.REJECTED_DUPLICATE,
        "reject_code": "DUPLICATE_SERIAL",
        "duplicate_of_item_id": captured_second["id"],
    })
    assert loser["duplicate_of_item_id"] != captured_first["id"], (
        "the earlier-captured coupon points at the later-captured one, because "
        "the later one was adjudicated first and owns the serial"
    )

    validated = validate_success(api.finalize_lot(second_lot["id"], ANALYST))
    assert_fields(validated, {
        "status": LotStatus.VALIDATED,
        "accepted_qty": 1,
    })
    assert_money(validated, "gross_face_value_cents", 50)
    assert_money(validated, "handling_fee_cents", 7)

    rejected = validate_success(api.finalize_lot(first_lot["id"], ANALYST))
    assert_fields(rejected, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED,
        "accepted_qty": 0,
    })
    assert_money(rejected, "gross_face_value_cents", 0)
    assert_money(rejected, "handling_fee_cents", 0)

    closed = validate_success(api.get_submission(submission["id"], ANALYST))
    assert_fields(closed, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.PENDING,
        "sorted_lot_count": 2,
        "rejected_lot_count": 1,
    })
    assert_money(closed, "settled_gross_face_value_cents", 50)
    assert_money(closed, "settled_handling_fee_cents", 7)

    retailer = validate_success(api.get_retailer(retailer_id, ANALYST))
    assert_fields(retailer, {"status": RetailerStatus.ACTIVE,
                             "rejected_submission_count": 0})
    assert_rate_equals(retailer["fraud_score"], "0.00", "fraud_score")
    assert_nulls(retailer, ["last_rescored_at"])


def test_06_a_reinstated_sample_still_divides_by_its_original_size(api, build):
    """Five of five instead of nought of five, and the projection climbs to 41.

    "First the unit accept rate is the `accepted_qty` divided by the
    `sample_size`, rounded half up to **four** decimal places."

    "The denominator of that rate is the `sample_size`, not the
    `captured_item_count` and not the number of items actually adjudicated."

    "The lot's `accepted_qty` and `rejected_qty` are recomputed, and both lot
    valuation and the lot handling fee are re-run from §3.5 — still dividing by
    the original `sample_size`, which is why a reinstatement raises the
    projection."

    "The owning submission then recomputes `accepted_item_face_value_cents`,
    `rejected_item_face_value_cents`, `settled_gross_face_value_cents`,
    `settled_handling_fee_cents` and `rejected_lot_count`, while
    `adjudicated_face_value_cents` stays numerically identical — value moves from
    the rejected column to the accepted column and the conserved total does not
    budge."

    Design: Corner/calculations/reinstated_sampled_lot_reprojects_against_the_original_sample_size
    """
    world = build.market(purchase_requirement_units=1)
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)

    submission = build.verified_submission(retailer_id, 42)
    sampled = build.lot(submission["id"], world["offer_id"],
                        world["manufacturer_id"], 41)
    clean = build.lot(submission["id"], world["offer_id"],
                      world["manufacturer_id"], 1)

    build.capture(sampled["id"], f.item_batch(
        2, COUNTERFEIT_DATABAR_PAYLOAD, "2026-07-10") + f.item_batch(
            3, world["barcode"], "2026-07-10",
            uri_stem="s3://coupon-images/n"))
    build.capture(clean["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/clean.jpg", "2026-07-10",
        pos_transaction_ref="POS-1")])

    lost = validate_success(api.finalize_lot(sampled["id"], ANALYST))
    assert_fields(lost, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED,
        "sample_size": 5,
        "captured_item_count": 5,
        "valuation_variant": ValuationVariant.SAMPLED_EXTRAPOLATION,
        "accepted_qty": 0,
        "rejected_qty": 5,
        "projected_accepted_units": 0,
    })
    assert_money(lost, "gross_face_value_cents", 0)
    assert_money(lost, "handling_fee_cents", 0)
    build.finalize(clean["id"])

    dispute = build.file_dispute(sampled["id"], retailer_id)
    resolved = build.resolve_dispute(
        dispute["id"], DisputeStatus.OVERTURNED,
        "Re-scan confirms all five coupons are valid redemptions.")
    assert_fields(resolved, {
        "status": DisputeStatus.OVERTURNED,
        "resolved_by_user_id": FRAUD_ANALYST_2_ID,
    })
    assert_money(resolved, "claimed_face_value_cents", 250)

    reinstated = validate_success(api.get_lot(sampled["id"], ANALYST))
    assert_fields(reinstated, {
        "status": LotStatus.REINSTATED,
        "accepted_qty": 5,
        "rejected_qty": 0,
        "sample_size": 5,
        "projected_accepted_units": 41,
    })
    assert_nulls(reinstated, ["reject_reason"])
    assert_money(reinstated, "gross_face_value_cents", 2050)
    assert_money(reinstated, "handling_fee_cents", 287)

    conserved = validate_success(api.get_submission(submission["id"], ANALYST))
    assert_money(conserved, "settled_gross_face_value_cents", 2100)
    assert_money(conserved, "settled_handling_fee_cents", 294)
    assert_money(conserved, "adjudicated_face_value_cents", 300)
    assert_money(conserved, "accepted_item_face_value_cents", 300)
    assert_money(conserved, "rejected_item_face_value_cents", 0)
    assert_fields(conserved, {"rejected_lot_count": 0})

    rows, meta = validate_paginated(
        api.list_items(ANALYST, lot_id=sampled["id"], limit=10))
    assert meta["total_count"] == 5, (
        "the lot filter reaches only the sampled lot's own coupons"
    )
    for row in rows:
        assert_fields(row, {"status": ItemStatus.REINSTATED})
        assert_nulls(row, ["reject_code"])
