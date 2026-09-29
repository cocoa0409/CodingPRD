"""State machines that are not chains: two axes, a counted loop, and a fork.

A submission moves on two independent dimensions at once; a dispute cycles until
a counter is exhausted; one funding call reaches two different target states.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ANALYST,
    ANALYST_2,
    OFFICER,
    DisputeStatus,
    HoldReason,
    IntakeStatus,
    InvoiceStatus,
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


def _accepted_pair(build, market, refs, window_start, window_end,
                   transaction_date="2026-07-05", redeemed_at="2026-07-05"):
    """A verified two-coupon shipment whose single lot validates at 100 and 14."""
    for ref in refs:
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              transaction_date, 2)
    submission = build.verified_submission(market["retailer_id"], 2,
                                           window_start, window_end)
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 2)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], f"s3://img/{ref.lower()}.jpg",
                       redeemed_at, pos_transaction_ref=ref, claimed_units=1)
        for ref in refs
    ])
    finalized = build.finalize(lot["id"])
    return submission, finalized


@pytest.fixture
def invoiced_chain(build):
    """One closed shipment, a scheduled statement of 114, and an unfunded 116.

    The invoice is raised but no wire has arrived, so the submission sits at
    CLOSED on intake and STATEMENT_ISSUED on settlement.
    """
    market = _standard_market(build)
    submission, _lot = _accepted_pair(build, market, ("POS-D1", "POS-D2"),
                                      "2026-07-01", "2026-07-31")
    statement = build.issue_statement(submission["id"])
    scheduled = build.schedule(statement["id"])
    invoice = build.invoice(market["manufacturer_id"], "2026-07-01",
                            "2026-07-31", [statement["id"]])
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "manufacturer_id": market["manufacturer_id"],
        "submission_id": submission["id"],
        "statement": scheduled,
        "statement_id": statement["id"],
        "invoice": invoice,
        "invoice_id": invoice["id"],
        "mfr_headers": market["mfr_headers"],
    }


def test_01_a_short_wire_moves_settlement_and_leaves_intake_where_it_was(
        api, build, invoiced_chain):
    """The settlement axis drops to HELD while the intake axis stays CLOSED.

    "Hop two: because each of those statements changed status, its submission's
    `settlement_status` moves `STATEMENT_ISSUED` → `HELD`, also with
    `hold_reason` `FUNDING_SHORTFALL`."

    "The two dimensions never read one another during intake — verifying a count
    leaves `settlement_status` entirely untouched — and a fully finished
    submission is one that has reached `CLOSED` on the first dimension and `PAID`
    on the second."

    Design: Difficulty/non_linear_state_machine/submission_parallel_intake_and_settlement_dimensions
    """
    invoice = build.fund(invoiced_chain["invoice"], 50)
    assert_fields(invoice, {"status": InvoiceStatus.SHORT_FUNDED})
    assert_money(invoice, "funding_shortfall_cents", 66)

    submission = validate_success(
        api.get_submission(invoiced_chain["submission_id"], OFFICER))
    assert_fields(submission, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.HELD,
        "hold_reason": HoldReason.FUNDING_SHORTFALL,
    })

    statement = validate_success(
        api.get_statement(invoiced_chain["statement_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.HELD})

    retailer = validate_success(
        api.get_retailer(invoiced_chain["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 0)


def test_02_topping_up_returns_the_settlement_axis_with_intake_untouched(
        api, build, invoiced_chain):
    """Two moves on one axis leave the other axis pinned at CLOSED throughout.

    "A second wire on a `SHORT_FUNDED` invoice that brings `funded_amount_cents`
    exactly to `billed_total_cents` sets `funding_shortfall_cents` to 0, moves
    the invoice `SHORT_FUNDED` → `FUNDED`, adds that wire's `amount_cents` to
    `funded_total_cents`, and runs the same three hops in reverse: every
    statement of the invoice that is `HELD` with `hold_reason`
    `FUNDING_SHORTFALL` returns to `SCHEDULED` with its `hold_reason` cleared,
    each such statement's submission returns to `STATEMENT_ISSUED` with its
    `hold_reason` cleared, and each affected retailer's `unpaid_balance_cents` is
    recomputed."

    Design: Difficulty/non_linear_state_machine/submission_parallel_intake_and_settlement_dimensions
    """
    build.fund(invoiced_chain["invoice"], 50)
    topped_up = build.fund(invoiced_chain["invoice"], 66)

    assert_fields(topped_up, {"status": InvoiceStatus.FUNDED})
    assert_money(topped_up, "funding_shortfall_cents", 0)

    submission = validate_success(
        api.get_submission(invoiced_chain["submission_id"], OFFICER))
    assert_fields(submission, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.STATEMENT_ISSUED,
    })
    assert_nulls(submission, ["hold_reason"])

    statement = validate_success(
        api.get_statement(invoiced_chain["statement_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.SCHEDULED})

    retailer = validate_success(
        api.get_retailer(invoiced_chain["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 114)


def test_03_the_hold_cycle_never_recomputes_the_scheduled_pay_date(
        api, build, invoiced_chain):
    """2026-08-31 survives the drop into HELD and the return to SCHEDULED.

    "A statement whose payment date passed while funding was short becomes
    immediately releasable rather than sliding another term into the future."

    "From a clock of 2026-08-01, `NET_30` lands on 2026-08-31, a Monday, with no
    roll; `NET_15` from the same clock lands on 2026-08-16, a Sunday, and rolls
    to 2026-08-17."

    Design: Difficulty/non_linear_state_machine/submission_parallel_intake_and_settlement_dimensions
    """
    statement_id = invoiced_chain["statement_id"]
    assert_fields(invoiced_chain["statement"],
                  {"scheduled_pay_date": "2026-08-31"})

    build.fund(invoiced_chain["invoice"], 50)
    held = validate_success(api.get_statement(statement_id, OFFICER))
    assert_fields(held, {"scheduled_pay_date": "2026-08-31"})

    build.fund(invoiced_chain["invoice"], 66)
    released = validate_success(api.get_statement(statement_id, OFFICER))
    assert_fields(released, {"scheduled_pay_date": "2026-08-31"})


@pytest.fixture
def appealed_lot(build):
    """A shipment with one clean lot and one wholly unbacked lot under appeal.

    Lot Y's two coupons quote register references no basket ever carried, so the
    lot is rejected outright and the retailer files against it.
    """
    market = _standard_market(build)
    for ref in ("POS-D1", "POS-D2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 4,
                                           "2026-07-01", "2026-07-31")
    lot_x = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 2)
    lot_y = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 2)
    build.capture(lot_x["id"], [
        f.item_payload(market["barcode"], f"s3://img/x{index}.jpg",
                       "2026-07-05", pos_transaction_ref=f"POS-D{index}",
                       claimed_units=1)
        for index in (1, 2)
    ])
    build.capture(lot_y["id"], [
        f.item_payload(market["barcode"], f"s3://img/y{index}.jpg",
                       "2026-07-05", pos_transaction_ref=f"POS-NONE{index}",
                       claimed_units=1)
        for index in (1, 2)
    ])
    build.finalize(lot_x["id"])
    rejected = build.finalize(lot_y["id"])
    build.rescore(market["retailer_id"])
    dispute = build.file_dispute(
        lot_y["id"], market["retailer_id"], reason_code="POS_DATA_LATE",
        narrative="Register data was uploaded late; the baskets exist.")
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "submission_id": submission["id"],
        "lot_y_id": lot_y["id"],
        "rejected_lot": rejected,
        "dispute": dispute,
        "dispute_id": dispute["id"],
        "ret_headers": market["ret_headers"],
    }


def test_04_filing_moves_the_lot_to_disputed_and_prices_the_claim(
        api, appealed_lot):
    """Two rejected coupons at one unit each put 100 cents under appeal.

    "Filing creates the dispute in `UNDER_REVIEW` with `info_request_count` 0, a
    null `resolution_note` and a null `resolved_by_user_id`, `retailer_id` copied
    from the lot's submission, `filed_at` taken from the logical clock, and
    `claimed_face_value_cents` copied from the lot's rejected face value — the
    sum, over the lot's coupons in any of the four rejected statuses, of the
    offer's `face_value_cents` multiplied by that coupon's `claimed_units`."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_capped_at_two_rounds
    """
    dispute = appealed_lot["dispute"]
    assert_fields(dispute, {
        "status": DisputeStatus.UNDER_REVIEW,
        "info_request_count": 0,
        "retailer_id": appealed_lot["retailer_id"],
    })
    assert_nulls(dispute, ["resolution_note", "resolved_by_user_id"])
    assert_money(dispute, "claimed_face_value_cents", 100)

    lot = validate_success(api.get_lot(appealed_lot["lot_y_id"], ANALYST))
    assert_fields(lot, {"status": LotStatus.DISPUTED})

    retailer = validate_success(
        api.get_retailer(appealed_lot["retailer_id"], ANALYST))
    assert_rate_equals(retailer["fraud_score"], "50.00", "fraud_score")
    assert_fields(retailer, {"status": RetailerStatus.ACTIVE})


def test_05_the_information_round_counter_never_falls_on_the_return_leg(
        api, appealed_lot):
    """Two full turns of the cycle leave the counter standing at 2.

    "An analyst may bounce the appeal back for more evidence, supplying an
    `info_request_note`; that moves the dispute `UNDER_REVIEW` →
    `INFO_REQUESTED` and increments `info_request_count` by 1."

    "The retailer answers by resubmitting with a fresh `narrative`, which is
    appended to the existing `narrative` and returns the dispute
    `INFO_REQUESTED` → `UNDER_REVIEW`; only the retailer named on the dispute may
    resubmit."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_capped_at_two_rounds
    """
    dispute_id = appealed_lot["dispute_id"]
    retailer_headers = appealed_lot["ret_headers"]

    first_request = validate_success(api.request_dispute_info(
        dispute_id, "Send the POS journal for 2026-07-05.", ANALYST_2))
    assert_fields(first_request, {"status": DisputeStatus.INFO_REQUESTED,
                                  "info_request_count": 1})

    first_answer = validate_success(api.resubmit_dispute(
        dispute_id, "Journal attached.", retailer_headers))
    assert_fields(first_answer, {"status": DisputeStatus.UNDER_REVIEW,
                                 "info_request_count": 1})

    second_request = validate_success(api.request_dispute_info(
        dispute_id, "The journal is unreadable; resend.", ANALYST_2))
    assert_fields(second_request, {"status": DisputeStatus.INFO_REQUESTED,
                                   "info_request_count": 2})

    second_answer = validate_success(api.resubmit_dispute(
        dispute_id, "Clean copy attached.", retailer_headers))
    assert_fields(second_answer, {"status": DisputeStatus.UNDER_REVIEW,
                                  "info_request_count": 2})


def test_06_the_third_request_is_refused_and_the_dispute_stays_under_review(
        api, appealed_lot):
    """The loop ends by counter exhaustion, not by reaching a new state.

    "That closes one turn of an `UNDER_REVIEW` → `INFO_REQUESTED` →
    `UNDER_REVIEW` cycle, and the cycle is capped at two information requests per
    dispute: a third attempt, when `info_request_count` has already reached 2, is
    refused with `ERR_INFO_ROUND_LIMIT`, which terminates the negotiation and
    forces the analyst to decide on what is in front of them."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_capped_at_two_rounds
    """
    dispute_id = appealed_lot["dispute_id"]
    retailer_headers = appealed_lot["ret_headers"]

    validate_success(api.request_dispute_info(
        dispute_id, "Send the POS journal for 2026-07-05.", ANALYST_2))
    validate_success(api.resubmit_dispute(
        dispute_id, "Journal attached.", retailer_headers))
    validate_success(api.request_dispute_info(
        dispute_id, "The journal is unreadable; resend.", ANALYST_2))
    validate_success(api.resubmit_dispute(
        dispute_id, "Clean copy attached.", retailer_headers))

    refused = api.request_dispute_info(
        dispute_id, "One more round please.", ANALYST_2)
    validate_error(refused, err.ERR_INFO_ROUND_LIMIT)

    dispute = validate_success(api.get_dispute(dispute_id, ANALYST_2))
    assert_fields(dispute, {"status": DisputeStatus.UNDER_REVIEW,
                            "info_request_count": 2})


@pytest.fixture
def two_invoices(build):
    """One issuer, two scheduled statements of 114, two invoices of 116 each.

    The two shipments occupy adjacent half-open postmark windows and the two
    invoices sit on billing periods far enough apart to clear the buffer.
    """
    market = _standard_market(build)
    first, _lot1 = _accepted_pair(build, market, ("POS-E1", "POS-E2"),
                                 "2026-07-01", "2026-07-16")
    second, _lot2 = _accepted_pair(build, market, ("POS-E3", "POS-E4"),
                                  "2026-07-16", "2026-07-31",
                                  transaction_date="2026-07-20",
                                  redeemed_at="2026-07-20")
    statement_one = build.issue_statement(first["id"])
    build.schedule(statement_one["id"])
    statement_two = build.issue_statement(second["id"])
    build.schedule(statement_two["id"])
    invoice_one = build.invoice(market["manufacturer_id"], "2026-07-01",
                               "2026-07-31", [statement_one["id"]])
    invoice_two = build.invoice(market["manufacturer_id"], "2026-08-03",
                               "2026-08-31", [statement_two["id"]])
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "manufacturer_id": market["manufacturer_id"],
        "submission_two_id": second["id"],
        "statement_one_id": statement_one["id"],
        "statement_two_id": statement_two["id"],
        "invoice_one": invoice_one,
        "invoice_two": invoice_two,
    }


def test_07_the_full_payment_branch_lands_funded_and_touches_no_statement(
        api, build, two_invoices):
    """116 against 116 closes the invoice and leaves the statement scheduled.

    "The invoice's statements were already `SCHEDULED`; full funding simply makes
    them releasable."

    Design: Difficulty/non_linear_state_machine/manufacturer_invoice_fund_branch_fork
    """
    assert_money(two_invoices["invoice_one"], "billed_total_cents", 116)
    assert_money(two_invoices["invoice_two"], "billed_total_cents", 116)

    funded = build.fund(two_invoices["invoice_one"], 116)

    assert_fields(funded, {"status": InvoiceStatus.FUNDED})
    assert_money(funded, "funding_shortfall_cents", 0)

    statement = validate_success(
        api.get_statement(two_invoices["statement_one_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.SCHEDULED})
    assert_nulls(statement, ["hold_reason"])


def test_08_the_short_payment_branch_runs_a_three_hop_freeze(
        api, build, two_invoices):
    """100 against 116 leaves a 16-cent gap and freezes the whole chain.

    "Hop one: every statement of this invoice that is `SCHEDULED` moves to `HELD`
    with `hold_reason` `FUNDING_SHORTFALL`, processed in statement `created_at`
    ascending order."

    "Hop three: because those statements are no longer `SCHEDULED`, each affected
    retailer's `unpaid_balance_cents` is recomputed over that retailer's
    `SCHEDULED` statements only, so the held amounts drop out of the payable
    balance, and each such retailer's `version` is bumped."

    Design: Difficulty/non_linear_state_machine/manufacturer_invoice_fund_branch_fork
    """
    short_funded = build.fund(two_invoices["invoice_two"], 100)

    assert_fields(short_funded, {"status": InvoiceStatus.SHORT_FUNDED})
    assert_money(short_funded, "funding_shortfall_cents", 16)

    statement = validate_success(
        api.get_statement(two_invoices["statement_two_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.HELD,
                              "hold_reason": HoldReason.FUNDING_SHORTFALL})

    submission = validate_success(
        api.get_submission(two_invoices["submission_two_id"], OFFICER))
    assert_fields(submission, {"settlement_status": SettlementStatus.HELD,
                               "hold_reason": HoldReason.FUNDING_SHORTFALL})

    retailer = validate_success(
        api.get_retailer(two_invoices["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 114)


def test_09_both_branches_credit_the_issuer_ledger_by_the_wire_amount(
        api, build, two_invoices):
    """216 cents arrived across the two wires, whatever the branch did next.

    "A short payment is real money received; it is simply not enough money."

    Design: Difficulty/non_linear_state_machine/manufacturer_invoice_fund_branch_fork
    """
    build.fund(two_invoices["invoice_one"], 116)
    build.fund(two_invoices["invoice_two"], 100)

    manufacturer = validate_success(
        api.get_manufacturer(two_invoices["manufacturer_id"], OFFICER))
    assert_manufacturer_ledger(manufacturer, funded_total=216,
                               disbursed_total=0)
