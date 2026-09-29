"""Cascades four entity levels deep, and the rows they must leave alone.

One finalize walks coupon to lot to submission to retailer; one short wire walks
invoice to statements to submissions to the retailer's payable balance.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ANALYST,
    OFFICER,
    FRAUD_ANALYST_ID,
    HoldReason,
    IntakeStatus,
    InvoiceStatus,
    ItemStatus,
    LotStatus,
    RejectCode,
    RetailerStatus,
    SettlementStatus,
    StatementStatus,
    ValuationVariant,
    assert_fields,
    assert_manufacturer_ledger,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    assert_retailer_unpaid,
    databar_payload,
    factories as f,
)

GOOD_BARCODE = databar_payload("038000", 50, 2, "2026-12-31", 30)
WRONG_GRACE_BARCODE = databar_payload("038000", 50, 2, "2026-12-31", 31)


def _standard_market(build):
    """The contract-rate issuer and the STANDARD, NET_30 retailer they settle."""
    return build.market(
        gs1_company_prefix="038000",
        handling_fee_policy="CONTRACT_RATE",
        dispute_window_days=45,
        channel_capability="BOTH",
        payment_terms="NET_30",
        base_fee_tier="STANDARD",
        fraud_scoring_mode="ROLLING_WINDOW",
        offer_code="SOUP50",
        face_value_cents=50,
        handling_fee_cents=7,
        expiration_date="2026-12-31",
        redemption_instructions="Save 50c on two cans",
        max_redemptions=100000,
        purchase_requirement_units=2,
        digital_enabled=False,
        clip_validity_days=14,
    )


@pytest.fixture
def one_bad_coupon(build):
    """Three coupons in one lot, the third carrying a payload off by one digit.

    Every coupon has a qualifying basket, so the only rejection the ladder can
    reach is the byte comparison of the scanned payload.
    """
    market = _standard_market(build)
    records = {}
    for index in (1, 2, 3):
        ref = f"POS-F{index}"
        records[ref] = build.purchase_record(
            market["retailer_id"], market["offer_id"], ref, "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 3,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 3)
    items = build.capture(lot["id"], [
        f.item_payload(GOOD_BARCODE, "s3://img/f1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-F1", claimed_units=1),
        f.item_payload(GOOD_BARCODE, "s3://img/f2.jpg", "2026-07-05",
                       pos_transaction_ref="POS-F2", claimed_units=1),
        f.item_payload(WRONG_GRACE_BARCODE, "s3://img/f3.jpg", "2026-07-05",
                       pos_transaction_ref="POS-F3", claimed_units=1),
    ])
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "offer_id": market["offer_id"],
        "submission_id": submission["id"],
        "lot_id": lot["id"],
        "items": items,
        "records": records,
    }


def test_01_the_mismatched_payload_is_the_only_rejection_the_ladder_reaches(
        api, build, one_bad_coupon):
    """One finalize writes three coupon statuses, two cleared and one counterfeit.

    "The coupon's `scanned_barcode` is compared byte for byte against the offer's
    `barcode_payload`, with no normalisation of any kind."

    "If they differ, the coupon becomes `REJECTED_COUNTERFEIT` with `reject_code`
    `BARCODE_MISMATCH`."

    Design: Difficulty/transitive_cascade/coupon_item_reject_depth_four_money_rollup
    """
    items = one_bad_coupon["items"]

    build.finalize(one_bad_coupon["lot_id"])

    first = validate_success(api.get_item(items[0]["id"], ANALYST))
    assert_fields(first, {
        "status": ItemStatus.ACCEPTED,
        "reject_code": None,
        "matched_purchase_record_id": one_bad_coupon["records"]["POS-F1"]["id"],
    })

    second = validate_success(api.get_item(items[1]["id"], ANALYST))
    assert_fields(second, {"status": ItemStatus.ACCEPTED})

    third = validate_success(api.get_item(items[2]["id"], ANALYST))
    assert_fields(third, {
        "status": ItemStatus.REJECTED_COUNTERFEIT,
        "reject_code": RejectCode.BARCODE_MISMATCH,
    })


def test_02_the_lot_prices_the_cleared_units_and_not_the_counted_ones(
        api, build, one_bad_coupon):
    """Two cleared units cost 14 cents in handling, not the 21 three would.

    "If at least one coupon cleared — that is, the recomputed `accepted_qty` is at
    least 1 — the lot goes `SORTED` → `VALIDATED`."

    "The unit count is the lot's `projected_accepted_units`."

    Design: Difficulty/transitive_cascade/coupon_item_reject_depth_four_money_rollup
    """
    lot = build.finalize(one_bad_coupon["lot_id"])

    assert_fields(lot, {
        "status": LotStatus.VALIDATED,
        "accepted_qty": 2,
        "rejected_qty": 1,
        "valuation_variant": ValuationVariant.FULL_COUNT,
        "projected_accepted_units": 2,
        "adjudicated_by_user_id": FRAUD_ANALYST_ID,
    })
    assert_money(lot, "gross_face_value_cents", 100)
    assert_money(lot, "handling_fee_cents", 14)
    assert lot["handling_fee_cents"] != 21, (
        "21 is the fee a lot priced from its counted_qty of 3 would charge"
    )


def test_03_the_offer_counter_advances_by_the_cleared_units_only(
        api, build, one_bad_coupon):
    """The side branch off the lot credits two units, never three.

    "Before the lot is validated, the offer's `accepted_redemption_count` plus the
    units this lot would clear must not exceed the offer's `max_redemptions`, or
    the operation is refused with `ERR_MAX_REDEMPTIONS_EXCEEDED`; on success
    `accepted_redemption_count` increases by the cleared units and the offer's
    `version` is bumped."

    Design: Difficulty/transitive_cascade/coupon_item_reject_depth_four_money_rollup
    """
    build.finalize(one_bad_coupon["lot_id"])

    offer = validate_success(api.get_offer(one_bad_coupon["offer_id"], ANALYST))
    assert_fields(offer, {"accepted_redemption_count": 2})


def test_04_the_submission_totals_arrive_already_current_on_the_close(
        api, build, one_bad_coupon):
    """Level three splits 150 conserved cents into 100 accepted and 50 rejected.

    "`Submission.adjudicated_face_value_cents` is the sum, over that submission's
    coupon items whose status is anything other than `CAPTURED`, of the item's
    offer face value multiplied by the item's `claimed_units`."

    "A submission that closes with at least one validated lot does none of that
    and stays `PENDING` on the settlement dimension, waiting for an officer."

    Design: Difficulty/transitive_cascade/coupon_item_reject_depth_four_money_rollup
    """
    build.finalize(one_bad_coupon["lot_id"])

    submission = validate_success(
        api.get_submission(one_bad_coupon["submission_id"], ANALYST))

    assert_money(submission, "declared_face_value_cents", 150)
    assert_money(submission, "adjudicated_face_value_cents", 150)
    assert_money(submission, "accepted_item_face_value_cents", 100)
    assert_money(submission, "rejected_item_face_value_cents", 50)
    assert_money(submission, "settled_gross_face_value_cents", 100)
    assert_money(submission, "settled_handling_fee_cents", 14)
    assert_fields(submission, {
        "rejected_lot_count": 0,
        "valuation_method": ValuationVariant.FULL_COUNT,
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.PENDING,
    })


def test_05_the_retailer_rate_reads_the_statuses_the_finalize_just_wrote(
        api, build, one_bad_coupon):
    """One counterfeit in three adjudicated coupons weights up to 66.66.

    "Three component rates come out of that pool, each computed as the count of
    matching items multiplied by one hundred, divided by the pool size, rounded
    half up to two decimal places: `duplicate_rate` counts items in
    `REJECTED_DUPLICATE`, `misredemption_rate` counts items in
    `REJECTED_MISREDEEMED`, and `counterfeit_rate` counts items in
    `REJECTED_COUNTERFEIT`."

    "The `duplicate_rate` is multiplied by 1.40, the `misredemption_rate` by 1.00
    and the `counterfeit_rate` by 2.00; the three products are added; the total is
    rounded half up to two decimal places; and the result is clamped so that it
    can never exceed `100.00`."

    Design: Difficulty/transitive_cascade/coupon_item_reject_depth_four_money_rollup
    """
    build.finalize(one_bad_coupon["lot_id"])
    current = validate_success(
        api.get_retailer(one_bad_coupon["retailer_id"], ANALYST))

    rescored = validate_success(api.fraud_rescore(
        one_bad_coupon["retailer_id"], current["version"], ANALYST))

    assert_rate_equals(rescored["counterfeit_rate"], "33.33", "counterfeit_rate")
    assert_rate_equals(rescored["duplicate_rate"], "0.00", "duplicate_rate")
    assert_rate_equals(rescored["misredemption_rate"], "0.00",
                       "misredemption_rate")
    assert_rate_equals(rescored["fraud_score"], "66.66", "fraud_score")
    assert_fields(rescored, {
        "status": RetailerStatus.ACTIVE,
        "handling_fee_tier": "STANDARD",
        "last_rescored_at": "2026-08-01T00:00:00.000Z",
    })


@pytest.fixture
def three_statements_two_billed(build):
    """Three scheduled statements of 114, only the first two billed onto one invoice.

    The third statement is deliberately left off the invoice so the cascade has a
    row it must not touch.
    """
    market = _standard_market(build)
    chains = []
    windows = (("2026-07-01", "2026-07-11", "2026-07-05", ("POS-G1", "POS-G2")),
               ("2026-07-11", "2026-07-21", "2026-07-15", ("POS-G3", "POS-G4")),
               ("2026-07-21", "2026-07-31", "2026-07-25", ("POS-G5", "POS-G6")))
    for start, end, day, refs in windows:
        for ref in refs:
            build.purchase_record(market["retailer_id"], market["offer_id"],
                                  ref, day, 2)
        submission = build.verified_submission(market["retailer_id"], 2,
                                               start, end)
        lot = build.lot(submission["id"], market["offer_id"],
                        market["manufacturer_id"], 2)
        build.capture(lot["id"], [
            f.item_payload(market["barcode"], f"s3://img/{ref.lower()}.jpg",
                           day, pos_transaction_ref=ref, claimed_units=1)
            for ref in refs
        ])
        build.finalize(lot["id"])
        statement = build.issue_statement(submission["id"])
        build.schedule(statement["id"])
        chains.append({"submission_id": submission["id"],
                       "statement_id": statement["id"]})
    invoice = build.invoice(market["manufacturer_id"], "2026-07-01",
                           "2026-07-31",
                           [chains[0]["statement_id"], chains[1]["statement_id"]])
    return {"market": market, "retailer_id": market["retailer_id"],
            "manufacturer_id": market["manufacturer_id"],
            "chains": chains, "invoice": invoice, "invoice_id": invoice["id"]}


def test_06_the_invoice_bills_only_the_two_statements_it_names(
        api, three_statements_two_billed):
    """200 face plus 28 fee plus a 3-cent clearing cut is 231 billed.

    "`billed_face_value_cents` is the sum of `gross_face_value_cents` over the
    named statements; `billed_handling_fee_cents` is the sum of their
    `handling_fee_total_cents`."

    "`billed_total_cents` is the face value plus the handling fee plus the
    clearing fee."

    Design: Difficulty/transitive_cascade/invoice_short_fund_depth_four_conditional_hold_cascade
    """
    invoice = three_statements_two_billed["invoice"]
    assert_money(invoice, "billed_face_value_cents", 200)
    assert_money(invoice, "billed_handling_fee_cents", 28)
    assert_money(invoice, "billed_clearing_fee_cents", 3)
    assert_money(invoice, "billed_total_cents", 231)

    retailer = validate_success(api.get_retailer(
        three_statements_two_billed["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 342)


def test_07_the_short_wire_freezes_the_billed_statements_and_no_others(
        api, build, three_statements_two_billed):
    """Two statements drop to HELD while the unbilled third stays SCHEDULED.

    "Hop one: every statement of this invoice that is `SCHEDULED` moves to `HELD`
    with `hold_reason` `FUNDING_SHORTFALL`, processed in statement `created_at`
    ascending order."

    Design: Difficulty/transitive_cascade/invoice_short_fund_depth_four_conditional_hold_cascade
    """
    chains = three_statements_two_billed["chains"]
    untouched_before = validate_success(
        api.get_statement(chains[2]["statement_id"], OFFICER))

    invoice = build.fund(three_statements_two_billed["invoice"], 200)
    assert_fields(invoice, {"status": InvoiceStatus.SHORT_FUNDED})
    assert_money(invoice, "funded_amount_cents", 200)
    assert_money(invoice, "funding_shortfall_cents", 31)

    for chain in chains[:2]:
        held = validate_success(api.get_statement(chain["statement_id"], OFFICER))
        assert_fields(held, {"status": StatementStatus.HELD,
                             "hold_reason": HoldReason.FUNDING_SHORTFALL})
        submission = validate_success(
            api.get_submission(chain["submission_id"], OFFICER))
        assert_fields(submission, {
            "settlement_status": SettlementStatus.HELD,
            "hold_reason": HoldReason.FUNDING_SHORTFALL,
        })

    untouched = validate_success(
        api.get_statement(chains[2]["statement_id"], OFFICER))
    assert_fields(untouched, {"status": StatementStatus.SCHEDULED})
    assert_nulls(untouched, ["hold_reason"])
    assert untouched["version"] == untouched_before["version"], (
        "a statement the invoice never named is not a row the cascade may touch"
    )

    spared = validate_success(
        api.get_submission(chains[2]["submission_id"], OFFICER))
    assert_fields(spared,
                  {"settlement_status": SettlementStatus.STATEMENT_ISSUED})
    assert_nulls(spared, ["hold_reason"])


def test_08_the_payable_balance_falls_to_exactly_the_unbilled_statement(
        api, build, three_statements_two_billed):
    """342 becomes 114, the one statement still on the payment calendar.

    "`Retailer.unpaid_balance_cents` is the sum of `net_payable_cents` over that
    retailer's settlement statements whose status is `SCHEDULED` — and only
    `SCHEDULED`."

    "A statement moved to `HELD` is not payable and therefore drops out of the
    balance; a statement that has reached `PAID` has already left it."

    Design: Difficulty/transitive_cascade/invoice_short_fund_depth_four_conditional_hold_cascade
    """
    build.fund(three_statements_two_billed["invoice"], 200)

    retailer = validate_success(
        api.get_retailer(three_statements_two_billed["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 114)
    assert retailer["unpaid_balance_cents"] not in (0, 342), (
        "0 is what sweeping every statement of the retailer would give and 342 "
        "is what sweeping none would give"
    )

    manufacturer = validate_success(api.get_manufacturer(
        three_statements_two_billed["manufacturer_id"], OFFICER))
    assert_manufacturer_ledger(manufacturer, funded_total=200,
                               disbursed_total=0)


def test_09_no_scheduled_pay_date_moves_anywhere_in_the_cascade(
        api, build, three_statements_two_billed):
    """All three statements keep the 2026-08-31 date scheduling gave them.

    "A statement whose payment date passed while funding was short becomes
    immediately releasable rather than sliding another term into the future."

    "Neither the submission's postmark window nor the statement's own creation
    timestamp is an input."

    Design: Difficulty/transitive_cascade/invoice_short_fund_depth_four_conditional_hold_cascade
    """
    chains = three_statements_two_billed["chains"]
    before = [validate_success(api.get_statement(chain["statement_id"], OFFICER))
              for chain in chains]
    for statement in before:
        assert_fields(statement, {"scheduled_pay_date": "2026-08-31"})

    build.fund(three_statements_two_billed["invoice"], 200)

    after = [validate_success(api.get_statement(chain["statement_id"], OFFICER))
             for chain in chains]
    for statement in after:
        assert_fields(statement, {"scheduled_pay_date": "2026-08-31"})
