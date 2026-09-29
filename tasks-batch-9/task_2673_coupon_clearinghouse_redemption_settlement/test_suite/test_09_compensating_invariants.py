"""Two compensating actions and the quantities they must leave alone.

An overturned appeal moves face value between the accepted and rejected columns
without changing the adjudicated total; a reversed wire puts the issuer's ledger
back exactly where it was and re-freezes everything the money had released.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_2,
    FRAUD_ANALYST_2_ID,
    OFFICER,
    DisputeStatus,
    FeeTier,
    HoldReason,
    IntakeStatus,
    InvoiceStatus,
    ItemStatus,
    LotStatus,
    RetailerStatus,
    SettlementStatus,
    StatementStatus,
    api_errors as err,
    assert_fields,
    assert_manufacturer_ledger,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    assert_retailer_unpaid,
    factories as f,
)


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
def rejected_shipment(build):
    """A closed shipment holding one validated lot and one wholly rejected lot.

    Lot X's two coupons are backed by real baskets; lot Y's two quote register
    references no basket carries, so every coupon of lot Y is misredeemed and the
    lot is rejected outright.
    """
    market = _standard_market(build)
    for ref in ("POS-R1", "POS-R2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 4,
                                           "2026-07-01", "2026-07-31")
    lot_x = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 2)
    lot_y = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 2)
    build.capture(lot_x["id"], [
        f.item_payload(market["barcode"], f"s3://img/r{index}.jpg",
                       "2026-07-05", pos_transaction_ref=f"POS-R{index}",
                       claimed_units=1)
        for index in (1, 2)
    ])
    y_items = build.capture(lot_y["id"], [
        f.item_payload(market["barcode"], f"s3://img/r{index}.jpg",
                       "2026-07-05", pos_transaction_ref=f"POS-VOID{index - 2}",
                       claimed_units=1)
        for index in (3, 4)
    ])
    build.finalize(lot_x["id"])
    build.finalize(lot_y["id"])
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "offer_id": market["offer_id"],
        "submission_id": submission["id"],
        "lot_x_id": lot_x["id"],
        "lot_y_id": lot_y["id"],
        "item_y1_id": y_items[0]["id"],
        "item_y2_id": y_items[1]["id"],
    }


def test_01_rejection_splits_the_adjudicated_total_across_the_two_columns(
        api, build, rejected_shipment):
    """Two hundred cents adjudicated, a hundred accepted and a hundred rejected.

    "`Submission.adjudicated_face_value_cents` is the sum, over that submission's
    coupon items whose status is anything other than `CAPTURED`, of the item's
    offer face value multiplied by the item's `claimed_units`."

    "If nothing cleared at all — the recomputed `accepted_qty` is exactly 0 — the
    lot goes `SORTED` → `LOT_REJECTED` with `reject_reason` set to
    `ALL_ITEMS_REJECTED`."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    submission = validate_success(
        api.get_submission(rejected_shipment["submission_id"], ANALYST))

    assert_fields(submission, {"intake_status": IntakeStatus.CLOSED})
    assert_money(submission, "adjudicated_face_value_cents", 200)
    assert_money(submission, "accepted_item_face_value_cents", 100)
    assert_money(submission, "rejected_item_face_value_cents", 100)
    assert_money(submission, "settled_gross_face_value_cents", 100)
    assert_money(submission, "settled_handling_fee_cents", 14)
    assert (submission["accepted_item_face_value_cents"]
            + submission["rejected_item_face_value_cents"]
            == submission["adjudicated_face_value_cents"]), (
        "the accepted and rejected columns must always sum to the adjudicated "
        "total"
    )

    offer = validate_success(api.get_offer(rejected_shipment["offer_id"], ANALYST))
    assert_fields(offer, {"accepted_redemption_count": 2})

    build.rescore(rejected_shipment["retailer_id"])
    retailer = validate_success(
        api.get_retailer(rejected_shipment["retailer_id"], ANALYST))
    assert_rate_equals(retailer["misredemption_rate"], "50.00",
                       "misredemption_rate")
    assert_rate_equals(retailer["fraud_score"], "50.00", "fraud_score")


def test_02_filing_the_appeal_moves_the_lot_without_moving_any_value(
        api, build, rejected_shipment):
    """The lot becomes DISPUTED and the conserved total stays at two hundred.

    "The lot moves `LOT_REJECTED` → `DISPUTED`."

    "It is the conserved quantity of adjudication: reinstating rejected items
    after an overturned dispute shifts value between `accepted_item_face_value_cents`
    and `rejected_item_face_value_cents` but leaves `adjudicated_face_value_cents`
    numerically unchanged."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    build.file_dispute(
        rejected_shipment["lot_y_id"], rejected_shipment["retailer_id"],
        reason_code="POS_DATA_LATE",
        narrative="The POS extract omitted two baskets.")

    lot = validate_success(api.get_lot(rejected_shipment["lot_y_id"], ANALYST))
    assert_fields(lot, {"status": LotStatus.DISPUTED})

    submission = validate_success(
        api.get_submission(rejected_shipment["submission_id"], ANALYST))
    assert_money(submission, "adjudicated_face_value_cents", 200)
    assert_money(submission, "accepted_item_face_value_cents", 100)
    assert_money(submission, "rejected_item_face_value_cents", 100)


@pytest.fixture
def appealed_shipment(build, rejected_shipment):
    """The rejected lot under appeal, awaiting a second analyst's decision."""
    dispute = build.file_dispute(
        rejected_shipment["lot_y_id"], rejected_shipment["retailer_id"],
        reason_code="POS_DATA_LATE",
        narrative="The POS extract omitted two baskets.")
    return dict(rejected_shipment, dispute=dispute, dispute_id=dispute["id"])


def test_03_the_overturn_reinstates_every_coupon_and_reprices_the_lot(
        api, build, appealed_shipment):
    """Lot Y ends at 100 and 14 — exactly what a clean finalization would give.

    "Every coupon of the lot in `REJECTED_EXPIRED`, `REJECTED_COUNTERFEIT`,
    `REJECTED_DUPLICATE` or `REJECTED_MISREDEEMED` is moved to `REINSTATED`, with
    its `reject_code` cleared and its `duplicate_of_item_id` cleared, processed in
    coupon `created_at` ascending order."

    "The lot becomes `REINSTATED` and its `reject_reason` is cleared."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    build.resolve_dispute(
        appealed_shipment["dispute_id"], "OVERTURNED",
        resolution_note="Register journal produced; both baskets confirmed.",
        headers=ANALYST_2)

    for item_id in (appealed_shipment["item_y1_id"],
                    appealed_shipment["item_y2_id"]):
        item = validate_success(api.get_item(item_id, ANALYST))
        assert_fields(item, {"status": ItemStatus.REINSTATED})
        assert_nulls(item, ["reject_code", "duplicate_of_item_id"])

    lot = validate_success(api.get_lot(appealed_shipment["lot_y_id"], ANALYST))
    assert_fields(lot, {"status": LotStatus.REINSTATED, "accepted_qty": 2,
                        "rejected_qty": 0})
    assert_nulls(lot, ["reject_reason"])
    assert_money(lot, "gross_face_value_cents", 100)
    assert_money(lot, "handling_fee_cents", 14)


def test_04_value_crosses_the_columns_and_the_adjudicated_total_does_not_budge(
        api, build, appealed_shipment):
    """Two hundred before, two hundred after, but the split goes from 100/100 to 200/0.

    "The owning submission then recomputes `accepted_item_face_value_cents`,
    `rejected_item_face_value_cents`, `settled_gross_face_value_cents`,
    `settled_handling_fee_cents` and `rejected_lot_count`, while
    `adjudicated_face_value_cents` stays numerically identical — value moves from
    the rejected column to the accepted column and the conserved total does not
    budge."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    submission_id = appealed_shipment["submission_id"]
    before = validate_success(api.get_submission(submission_id, ANALYST))
    assert_money(before, "adjudicated_face_value_cents", 200)

    build.resolve_dispute(
        appealed_shipment["dispute_id"], "OVERTURNED",
        resolution_note="Register journal produced; both baskets confirmed.",
        headers=ANALYST_2)

    after = validate_success(api.get_submission(submission_id, ANALYST))
    assert_money(after, "adjudicated_face_value_cents", 200)
    assert_money(after, "accepted_item_face_value_cents", 200)
    assert_money(after, "rejected_item_face_value_cents", 0)
    assert (after["accepted_item_face_value_cents"]
            + after["rejected_item_face_value_cents"]
            == after["adjudicated_face_value_cents"]), (
        "the identity has to hold on the far side of the compensation too"
    )
    assert_fields(after, {"rejected_lot_count": 0})


def test_05_the_two_lots_each_round_their_own_fee_after_the_reinstatement(
        api, build, appealed_shipment):
    """Fourteen plus fourteen is twenty-eight, and the gross doubles to 200.

    "In the same way, `settled_gross_face_value_cents` is the plain integer sum of
    `gross_face_value_cents` over the submission's `VALIDATED` and `REINSTATED`
    lots, and it is the billable gross a statement will copy."

    "That per-lot rounding is the whole point, and the submission's
    `settled_handling_fee_cents` is a plain integer sum of already-rounded lot
    fees over the submission's lots in `VALIDATED` or `REINSTATED`; lots in
    `SORTED`, `LOT_REJECTED` or `DISPUTED` contribute nothing."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    build.resolve_dispute(
        appealed_shipment["dispute_id"], "OVERTURNED",
        resolution_note="Register journal produced; both baskets confirmed.",
        headers=ANALYST_2)

    submission = validate_success(
        api.get_submission(appealed_shipment["submission_id"], ANALYST))
    assert_money(submission, "settled_gross_face_value_cents", 200)
    assert_money(submission, "settled_handling_fee_cents", 28)


def test_06_the_offer_counter_advances_by_the_newly_cleared_units_only(
        api, build, appealed_shipment):
    """Four cleared units, not the six a recount-from-zero double count would give.

    "The offer's `accepted_redemption_count` advances by the newly cleared units
    and the offer's `version` is bumped."

    "Each reinstated coupon re-enters the accepted set at its full original
    `claimed_units`."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    before = validate_success(api.get_offer(appealed_shipment["offer_id"], ANALYST))
    assert_fields(before, {"accepted_redemption_count": 2})

    build.resolve_dispute(
        appealed_shipment["dispute_id"], "OVERTURNED",
        resolution_note="Register journal produced; both baskets confirmed.",
        headers=ANALYST_2)

    after = validate_success(api.get_offer(appealed_shipment["offer_id"], ANALYST))
    assert_fields(after, {"accepted_redemption_count": 4})
    assert after["accepted_redemption_count"] != 6, (
        "6 is what advancing by every cleared unit of both lots a second time "
        "would produce"
    )
    assert after["version"] > before["version"], (
        "the reinstatement has to bump the offer's version"
    )


def test_07_a_rescore_after_the_overturn_clears_every_rate_to_zero(
        api, build, appealed_shipment):
    """Reinstated coupons stay in the denominator but leave every numerator.

    "`REINSTATED` items are part of the pool and count toward the denominator, but
    they count toward none of the three numerators — which is why an overturned
    dispute lowers every rate rather than merely moving value around."

    "Separately and on the same boundary, the effective `handling_fee_tier`
    becomes `PROBATION` at `70.00` or above and reverts to the retailer's
    `base_fee_tier` below it — so the tier always returns to the contracted base
    and never to a remembered `PROBATION`."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    build.resolve_dispute(
        appealed_shipment["dispute_id"], "OVERTURNED",
        resolution_note="Register journal produced; both baskets confirmed.",
        headers=ANALYST_2)
    build.rescore(appealed_shipment["retailer_id"])

    retailer = validate_success(
        api.get_retailer(appealed_shipment["retailer_id"], ANALYST))
    assert_rate_equals(retailer["misredemption_rate"], "0.00",
                       "misredemption_rate")
    assert_rate_equals(retailer["duplicate_rate"], "0.00", "duplicate_rate")
    assert_rate_equals(retailer["counterfeit_rate"], "0.00", "counterfeit_rate")
    assert_rate_equals(retailer["fraud_score"], "0.00", "fraud_score")
    assert_fields(retailer, {"status": RetailerStatus.ACTIVE,
                             "handling_fee_tier": FeeTier.STANDARD})


def test_08_the_analyst_who_rejected_the_lot_cannot_be_the_one_who_clears_it(
        api, build, appealed_shipment):
    """fa-1 finalized lot Y, so only a second identity may resolve the appeal.

    "The segregation-of-duties wall applies here and outranks every other
    readiness check on this operation: the acting `X-User-ID` must differ from the
    disputed lot's `adjudicated_by_user_id`, so two distinct analyst identities
    are required to take a lot from rejection to resolution, and a self-review is
    refused with `ERR_SOD_VIOLATION`."

    "Whichever way it goes, resolution writes `resolution_note` and sets
    `resolved_by_user_id` to the acting `X-User-ID`."

    Design: Difficulty/compensating_invariant/dispute_overturn_conserves_adjudicated_face_value
    """
    dispute_id = appealed_shipment["dispute_id"]

    refused = api.resolve_dispute(
        dispute_id, "OVERTURNED", "I signed off on the rejection myself.",
        ANALYST)
    validate_error(refused, err.ERR_SOD_VIOLATION)

    still_open = validate_success(api.get_dispute(dispute_id, ANALYST))
    assert_fields(still_open, {"status": DisputeStatus.UNDER_REVIEW})

    resolved = build.resolve_dispute(
        dispute_id, "OVERTURNED",
        resolution_note="Register journal produced; both baskets confirmed.",
        headers=ANALYST_2)
    assert_fields(resolved, {"status": DisputeStatus.OVERTURNED,
                             "resolved_by_user_id": FRAUD_ANALYST_2_ID})


@pytest.fixture
def funded_invoice(build):
    """A fully funded 116-cent invoice over one scheduled, unreleased statement.

    Nothing has been disbursed, so the reversal guard against paid statements
    passes and the issuer's ledger stands at 116 funded and 0 disbursed.
    """
    market = _standard_market(build)
    for ref in ("POS-S1", "POS-S2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 2,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 2)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], f"s3://img/s{index}.jpg",
                       "2026-07-05", pos_transaction_ref=f"POS-S{index}",
                       claimed_units=1)
        for index in (1, 2)
    ])
    build.finalize(lot["id"])
    statement = build.issue_statement(submission["id"])
    scheduled = build.schedule(statement["id"])
    invoice = build.invoice(market["manufacturer_id"], "2026-07-01",
                            "2026-07-31", [statement["id"]])
    funded = build.fund(invoice, 116)
    return {
        "market": market,
        "manufacturer_id": market["manufacturer_id"],
        "retailer_id": market["retailer_id"],
        "submission_id": submission["id"],
        "statement_id": statement["id"],
        "scheduled": scheduled,
        "invoice_id": invoice["id"],
        "funded": funded,
    }


def test_09_the_reversal_returns_the_issuer_ledger_to_its_pre_funding_numbers(
        api, build, funded_invoice):
    """116 funded and 116 available become 0 and 0, with nothing disbursed either way.

    "The reversal restores `funded_total_cents`, and therefore
    `funding_balance_cents`, to exactly its pre-funding value — that exact
    restoration is the point of the operation, and it is why the decrement uses
    the invoice's accumulated `funded_amount_cents` rather than any single wire
    amount."

    "`Manufacturer.funding_balance_cents` always equals `funded_total_cents` minus
    `disbursed_total_cents`."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_manufacturer_ledger_exactly
    """
    manufacturer_id = funded_invoice["manufacturer_id"]

    assert_fields(funded_invoice["funded"], {"status": InvoiceStatus.FUNDED})
    assert_money(funded_invoice["funded"], "funded_amount_cents", 116)
    assert_money(funded_invoice["funded"], "funding_shortfall_cents", 0)
    before = validate_success(api.get_manufacturer(manufacturer_id, OFFICER))
    assert_manufacturer_ledger(before, funded_total=116, disbursed_total=0)
    assert_money(before, "funding_balance_cents", 116)

    build.reverse_funding(funded_invoice["invoice_id"],
                          "Wire recalled by the issuing bank")

    after = validate_success(api.get_manufacturer(manufacturer_id, OFFICER))
    assert_manufacturer_ledger(after, funded_total=0, disbursed_total=0)
    assert_money(after, "funding_balance_cents", 0)
    assert (after["funding_balance_cents"]
            == after["funded_total_cents"] - after["disbursed_total_cents"]), (
        "the balance identity has to survive the compensation"
    )


def test_10_the_invoice_returns_to_a_full_shortfall_but_not_to_issued(
        api, build, funded_invoice):
    """Zero funded, 116 short again, and REVERSED rather than ISSUED.

    "Reversal decreases the manufacturer's `funded_total_cents` by the invoice's
    entire `funded_amount_cents`, recomputes `funding_balance_cents` and bumps the
    manufacturer's `version`; resets the invoice's `funded_amount_cents` to 0 and
    `funding_shortfall_cents` back to the full `billed_total_cents`; sets the
    invoice to `REVERSED`, which is terminal and admits no further funding; moves
    every `SCHEDULED` statement of the invoice to `HELD` with `hold_reason`
    `FUNDING_SHORTFALL` and each such statement's submission to `HELD`; and
    recomputes each affected retailer's `unpaid_balance_cents`."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_manufacturer_ledger_exactly
    """
    reversed_invoice = build.reverse_funding(
        funded_invoice["invoice_id"], "Wire recalled by the issuing bank")

    assert_fields(reversed_invoice, {"status": InvoiceStatus.REVERSED})
    assert_money(reversed_invoice, "funded_amount_cents", 0)
    assert_money(reversed_invoice, "funding_shortfall_cents", 116)
    assert_money(reversed_invoice, "billed_total_cents", 116)
    assert reversed_invoice["status"] != InvoiceStatus.ISSUED, (
        "the compensation is terminal, not a rewind to the pre-funding status"
    )


def test_11_everything_the_money_had_released_is_frozen_again(
        api, build, funded_invoice):
    """The statement, its shipment and the retailer's payable all go back on hold.

    "Reversal decreases the manufacturer's `funded_total_cents` by the invoice's
    entire `funded_amount_cents`, recomputes `funding_balance_cents` and bumps the
    manufacturer's `version`; resets the invoice's `funded_amount_cents` to 0 and
    `funding_shortfall_cents` back to the full `billed_total_cents`; sets the
    invoice to `REVERSED`, which is terminal and admits no further funding; moves
    every `SCHEDULED` statement of the invoice to `HELD` with `hold_reason`
    `FUNDING_SHORTFALL` and each such statement's submission to `HELD`; and
    recomputes each affected retailer's `unpaid_balance_cents`."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_manufacturer_ledger_exactly
    """
    assert_fields(funded_invoice["scheduled"],
                  {"scheduled_pay_date": "2026-08-31"})
    before = validate_success(
        api.get_retailer(funded_invoice["retailer_id"], OFFICER))
    assert_retailer_unpaid(before, 114)

    build.reverse_funding(funded_invoice["invoice_id"],
                          "Wire recalled by the issuing bank")

    statement = validate_success(
        api.get_statement(funded_invoice["statement_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.HELD,
                              "hold_reason": HoldReason.FUNDING_SHORTFALL,
                              "scheduled_pay_date": "2026-08-31"})

    submission = validate_success(
        api.get_submission(funded_invoice["submission_id"], OFFICER))
    assert_fields(submission, {"intake_status": IntakeStatus.CLOSED,
                               "settlement_status": SettlementStatus.HELD,
                               "hold_reason": HoldReason.FUNDING_SHORTFALL})

    retailer = validate_success(
        api.get_retailer(funded_invoice["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 0)


def test_12_a_second_reversal_is_refused_because_reversed_is_terminal(
        api, build, funded_invoice):
    """The compensation is one-shot; a replay finds no funding left to unwind.

    "This covers every from-state guard in the system: registering an offer that
    is not `DRAFT`, activating an offer that is not `REGISTERED`, withdrawing an
    already-`WITHDRAWN` offer, verifying the count of a submission whose
    `intake_status` is not `RECEIVED`, adding lots to a submission whose
    `intake_status` is not `COUNT_VERIFIED`, capturing items into a lot that is
    not `SORTED`, adjudicating an item that is not `CAPTURED`, finalizing a lot
    that is not `SORTED`, scheduling a statement that is not `DRAFT`, releasing a
    statement that is not `SCHEDULED`, funding an invoice that is neither `ISSUED`
    nor `SHORT_FUNDED`, reversing an invoice that is neither `FUNDED` nor
    `SHORT_FUNDED`, requesting information on a dispute that is not
    `UNDER_REVIEW`, resubmitting a dispute that is not `INFO_REQUESTED`, resolving
    a dispute that is not `UNDER_REVIEW`, and every attempt to move a row out of a
    terminal state or to repeat an already-applied trigger."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_manufacturer_ledger_exactly
    """
    invoice_id = funded_invoice["invoice_id"]
    build.reverse_funding(invoice_id, "Wire recalled by the issuing bank")

    refused = api.reverse_funding(invoice_id, "Duplicate recall notice", ADMIN)
    validate_error(refused, err.ERR_INVALID_STATE_TRANSITION)

    invoice = validate_success(api.get_invoice(invoice_id, OFFICER))
    assert_fields(invoice, {"status": InvoiceStatus.REVERSED})
    assert_money(invoice, "funded_amount_cents", 0)


def test_13_a_reversed_invoice_cannot_be_re_funded_into_a_double_credit(
        api, build, funded_invoice):
    """Neither refusal moves a cent, so the restored ledger cannot drift back up.

    "The invoice must be in `ISSUED` or `SHORT_FUNDED`, and the wire's
    `amount_cents` — a positive integer — must not push `funded_amount_cents` past
    `billed_total_cents`; overfunding is refused with `ERR_FUNDING_EXCEEDS_BILLED`."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_manufacturer_ledger_exactly
    """
    invoice_id = funded_invoice["invoice_id"]
    build.reverse_funding(invoice_id, "Wire recalled by the issuing bank")

    validate_error(api.reverse_funding(invoice_id, "Duplicate recall notice",
                                       ADMIN),
                   err.ERR_INVALID_STATE_TRANSITION)
    validate_error(api.fund_invoice(invoice_id, 116,
                                    funded_invoice["market"]["mfr_headers"]),
                   err.ERR_INVALID_STATE_TRANSITION)

    manufacturer = validate_success(
        api.get_manufacturer(funded_invoice["manufacturer_id"], OFFICER))
    assert_manufacturer_ledger(manufacturer, funded_total=0, disbursed_total=0)

    invoice = validate_success(api.get_invoice(invoice_id, OFFICER))
    assert_money(invoice, "funded_amount_cents", 0)
    assert_money(invoice, "funding_shortfall_cents", 116)
