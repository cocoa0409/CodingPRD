"""Operations refused because of a row the request never names.

A statement's release turns on its invoice, its scheduling turns on disputes
three hops away, and a lot's finalization turns on its retailer's standing.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ANALYST,
    CLERK,
    OFFICER,
    OFFICER_2,
    DisputeStatus,
    HoldReason,
    IntakeStatus,
    InvoiceStatus,
    ItemStatus,
    LotRejectReason,
    LotStatus,
    RetailerStatus,
    SETTLEMENT_OFFICER_ID,
    SETTLEMENT_OFFICER_2_ID,
    SettlementStatus,
    StatementStatus,
    api_errors as err,
    assert_fields,
    assert_manufacturer_ledger,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    assert_retailer_unpaid,
    assert_statement_waterfall,
    factories as f,
)


def _standard_market(build, **overrides):
    """The contract-rate issuer and the STANDARD, NET_30 retailer they settle."""
    terms = dict(
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
    terms.update(overrides)
    return build.market(**terms)


@pytest.fixture
def payable_statement(build):
    """A scheduled statement of 114 billed onto an invoice nobody has funded.

    The officer so-1 both issues and schedules it, so a self-release later has a
    wall to hit.
    """
    market = _standard_market(build)
    for ref in ("POS-L1", "POS-L2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 2,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 2)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], f"s3://img/{ref.lower()}.jpg",
                       "2026-07-05", pos_transaction_ref=ref, claimed_units=1)
        for ref in ("POS-L1", "POS-L2")
    ])
    build.finalize(lot["id"])
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
    }


def test_01_an_unfunded_invoice_blocks_the_release_before_the_calendar_does(
        api, payable_statement):
    """Both the funding gate and the pay-date gate are open, and funding answers.

    "It must carry a non-null `manufacturer_invoice_id` whose invoice is in status
    `FUNDED`; an unfunded, short-funded, reversed or merely-issued invoice blocks
    release with `ERR_INVOICE_NOT_FUNDED`."

    "The relative precedence of these three is fixed by §2.11: the funding gate
    outranks the pay-date gate, so an early release attempt against an unfunded
    invoice reports the funding problem."

    Design: Difficulty/cross_entity_state_dependency/statement_release_gated_on_invoice_funded
    """
    assert_money(payable_statement["statement"], "net_payable_cents", 114)
    assert_fields(payable_statement["statement"],
                  {"scheduled_pay_date": "2026-08-31"})
    assert_fields(payable_statement["invoice"], {"status": InvoiceStatus.ISSUED})

    refused = api.release_payment(payable_statement["statement_id"], OFFICER_2)
    validate_error(refused, err.ERR_INVOICE_NOT_FUNDED)

    statement = validate_success(
        api.get_statement(payable_statement["statement_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.SCHEDULED})


def test_02_a_short_wire_puts_the_statement_itself_out_of_reach(
        api, build, payable_statement):
    """Once the statement is HELD its own state answers, not the invoice's.

    "The statement must be in `SCHEDULED`."

    "Hop one: every statement of this invoice that is `SCHEDULED` moves to `HELD`
    with `hold_reason` `FUNDING_SHORTFALL`, processed in statement `created_at`
    ascending order."

    Design: Difficulty/cross_entity_state_dependency/statement_release_gated_on_invoice_funded
    """
    build.fund(payable_statement["invoice"], 50)

    held = validate_success(
        api.get_statement(payable_statement["statement_id"], OFFICER))
    assert_fields(held, {"status": StatementStatus.HELD,
                         "hold_reason": HoldReason.FUNDING_SHORTFALL})

    refused = api.release_payment(payable_statement["statement_id"], OFFICER_2)
    validate_error(refused, err.ERR_INVALID_STATE_TRANSITION)


def test_03_a_funded_invoice_leaves_only_the_calendar_in_the_way(
        api, build, payable_statement):
    """116 cents arrive, the statement returns to SCHEDULED, and the date refuses.

    "The logical clock's calendar date must have reached `scheduled_pay_date` —
    the comparison is inclusive, so release on the pay date itself is legal, and
    an earlier date is refused with `ERR_PAY_DATE_NOT_REACHED`."

    Design: Difficulty/cross_entity_state_dependency/statement_release_gated_on_invoice_funded
    """
    build.fund(payable_statement["invoice"], 50)
    invoice = build.fund(payable_statement["invoice"], 66)
    assert_fields(invoice, {"status": InvoiceStatus.FUNDED})

    statement = validate_success(
        api.get_statement(payable_statement["statement_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.SCHEDULED})

    refused = api.release_payment(payable_statement["statement_id"], OFFICER_2)
    validate_error(refused, err.ERR_PAY_DATE_NOT_REACHED)


def test_04_the_officer_who_issued_the_statement_may_not_release_it(
        api, build, payable_statement):
    """On the pay date itself the only rung left is the duties wall.

    "And the acting `X-User-ID` must differ from the statement's
    `issued_by_user_id`, so two distinct `SettlementOfficer` user identities are
    required to move money; a self-release is refused with `ERR_SOD_VIOLATION`."

    Design: Difficulty/cross_entity_state_dependency/statement_release_gated_on_invoice_funded
    """
    build.fund(payable_statement["invoice"], 116)
    validate_success(api.set_clock("2026-08-31T00:00:00Z"))

    refused = api.release_payment(payable_statement["statement_id"], OFFICER)
    validate_error(refused, err.ERR_SOD_VIOLATION)

    statement = validate_success(
        api.get_statement(payable_statement["statement_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.SCHEDULED,
                              "issued_by_user_id": SETTLEMENT_OFFICER_ID})
    assert_nulls(statement, ["released_by_user_id"])


def test_05_the_second_officer_on_the_pay_date_moves_the_money(
        api, build, payable_statement):
    """Cash leaves, the ledgers move by 114, and the invoice reconciles.

    "Release sets the statement to `PAID` — a terminal state — records
    `released_by_user_id` as the acting user, moves the submission's
    `settlement_status` `STATEMENT_ISSUED` → `PAID` and clears its `hold_reason`,
    increases the manufacturer's `disbursed_total_cents` by the statement's
    `net_payable_cents` with `funding_balance_cents` recomputed and the
    manufacturer's `version` bumped, and decreases the retailer's
    `unpaid_balance_cents` by the same `net_payable_cents` with the retailer's
    `version` bumped."

    "An invoice with three statements therefore reconciles on the third release
    and not before, and the check is over all statements of the invoice, not
    merely the ones settled in this request."

    Design: Difficulty/cross_entity_state_dependency/statement_release_gated_on_invoice_funded
    """
    build.fund(payable_statement["invoice"], 116)
    validate_success(api.set_clock("2026-08-31T00:00:00Z"))

    paid = validate_success(
        api.release_payment(payable_statement["statement_id"], OFFICER_2))
    assert_fields(paid, {"status": StatementStatus.PAID,
                         "issued_by_user_id": SETTLEMENT_OFFICER_ID,
                         "released_by_user_id": SETTLEMENT_OFFICER_2_ID})

    submission = validate_success(
        api.get_submission(payable_statement["submission_id"], OFFICER))
    assert_fields(submission, {"settlement_status": SettlementStatus.PAID,
                               "intake_status": IntakeStatus.CLOSED})
    assert_nulls(submission, ["hold_reason"])

    manufacturer = validate_success(
        api.get_manufacturer(payable_statement["manufacturer_id"], OFFICER))
    assert_manufacturer_ledger(manufacturer, funded_total=116,
                               disbursed_total=114)
    assert_money(manufacturer, "funding_balance_cents", 2)

    retailer = validate_success(
        api.get_retailer(payable_statement["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 0)

    invoice = validate_success(
        api.get_invoice(payable_statement["invoice_id"], OFFICER))
    assert_fields(invoice, {"status": InvoiceStatus.RECONCILED})


@pytest.fixture
def disputed_shipment(build):
    """A DRAFT statement of 111 over a shipment one of whose lots is under appeal.

    Lot X clears; lot Y's coupons quote register references no basket carries, so
    it is rejected and appealed before any statement exists.
    """
    market = _standard_market(build)
    for ref in ("POS-M1", "POS-M2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 4,
                                           "2026-07-01", "2026-07-31")
    lot_x = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 2)
    lot_y = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 2)
    build.capture(lot_x["id"], [
        f.item_payload(market["barcode"], f"s3://img/{ref.lower()}.jpg",
                       "2026-07-05", pos_transaction_ref=ref, claimed_units=1)
        for ref in ("POS-M1", "POS-M2")
    ])
    build.capture(lot_y["id"], [
        f.item_payload(market["barcode"], f"s3://img/y{index}.jpg",
                       "2026-07-05", pos_transaction_ref=f"POS-GHOST{index}",
                       claimed_units=1)
        for index in (1, 2)
    ])
    build.finalize(lot_x["id"])
    build.finalize(lot_y["id"])
    build.rescore(market["retailer_id"])
    dispute = build.file_dispute(
        lot_y["id"], market["retailer_id"], reason_code="POS_DATA_LATE",
        narrative="The register export landed after the sort deadline.")
    statement = build.issue_statement(submission["id"])
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "submission_id": submission["id"],
        "lot_y_id": lot_y["id"],
        "dispute_id": dispute["id"],
        "statement": statement,
        "statement_id": statement["id"],
    }


def test_06_an_open_appeal_three_hops_away_blocks_the_calendar(
        api, disputed_shipment):
    """The statement is minted cleanly and then refused a place in the queue.

    "The statement must be in `DRAFT`, and no dispute in `UNDER_REVIEW` or
    `INFO_REQUESTED` may reference any lot of the statement's submission, or the
    request is refused with `ERR_DISPUTE_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/statement_schedule_gated_on_no_open_dispute
    """
    lot = validate_success(api.get_lot(disputed_shipment["lot_y_id"], ANALYST))
    assert_fields(lot, {"status": LotStatus.DISPUTED})

    retailer = validate_success(
        api.get_retailer(disputed_shipment["retailer_id"], OFFICER))
    assert_rate_equals(retailer["misredemption_rate"], "50.00",
                       "misredemption_rate")
    assert_rate_equals(retailer["fraud_score"], "50.00", "fraud_score")
    assert_fields(retailer, {"status": RetailerStatus.ACTIVE})

    assert_statement_waterfall(disputed_shipment["statement"], gross=100,
                               fee_total=14, offset=0, provisional_net=114,
                               holdback_pct="0.03", holdback=3, net_payable=111)

    refused = api.schedule_statement(disputed_shipment["statement_id"], OFFICER)
    validate_error(refused, err.ERR_DISPUTE_OPEN)

    statement = validate_success(
        api.get_statement(disputed_shipment["statement_id"], OFFICER))
    assert_fields(statement, {"status": StatementStatus.DRAFT})
    assert_nulls(statement, ["scheduled_pay_date"])


def test_07_upholding_the_appeal_releases_the_gate_without_moving_a_cent(
        api, build, disputed_shipment):
    """The same call now schedules, and the money is byte-identical either side.

    "The dispute becomes `UPHELD` and the lot returns `DISPUTED` →
    `LOT_REJECTED`, this time with `reject_reason` set to `DISPUTE_UPHELD`."

    "Scheduling then moves the statement `DRAFT` → `SCHEDULED`, moves the
    submission's `settlement_status` `PENDING` → `STATEMENT_ISSUED`, and increases
    the retailer's `unpaid_balance_cents` by the statement's `net_payable_cents`,
    bumping the retailer's `version`."

    Design: Difficulty/cross_entity_state_dependency/statement_schedule_gated_on_no_open_dispute
    """
    resolved = build.resolve_dispute(
        disputed_shipment["dispute_id"], "UPHELD",
        resolution_note="The register export never covered these coupons.")
    assert_fields(resolved, {"status": DisputeStatus.UPHELD})

    lot = validate_success(api.get_lot(disputed_shipment["lot_y_id"], ANALYST))
    assert_fields(lot, {"status": LotStatus.LOT_REJECTED,
                        "reject_reason": LotRejectReason.DISPUTE_UPHELD})

    scheduled = validate_success(
        api.schedule_statement(disputed_shipment["statement_id"], OFFICER))
    assert_fields(scheduled, {"status": StatementStatus.SCHEDULED,
                              "scheduled_pay_date": "2026-08-31"})
    assert_money(scheduled, "net_payable_cents", 111)
    assert_money(scheduled, "gross_face_value_cents", 100)

    retailer = validate_success(
        api.get_retailer(disputed_shipment["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 111)

    submission = validate_success(
        api.get_submission(disputed_shipment["submission_id"], OFFICER))
    assert_fields(submission,
                  {"settlement_status": SettlementStatus.STATEMENT_ISSUED})


@pytest.fixture
def suspended_owner(build):
    """A lot whose sample is complete, owned by a retailer under suspension.

    Nothing about the lot or its coupons is left to do; only the retailer's
    standing stands between it and a valuation.
    """
    market = _standard_market(build)
    for ref in ("POS-N1", "POS-N2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 2,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 2)
    items = build.capture(lot["id"], [
        f.item_payload(market["barcode"], f"s3://img/{ref.lower()}.jpg",
                       "2026-07-05", pos_transaction_ref=ref, claimed_units=1)
        for ref in ("POS-N1", "POS-N2")
    ])
    suspended = build.suspend_retailer(market["retailer_id"],
                                       "Fraud referral opened")
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "submission_id": submission["id"],
        "lot_id": lot["id"],
        "items": items,
        "suspended": suspended,
    }


def test_08_a_ready_lot_is_refused_because_its_retailer_is_suspended(
        api, suspended_owner):
    """The 403 leaves the lot and every coupon exactly as capture left them.

    "Finalizing a lot is the analyst's decision to close the bucket and put a
    number on it."

    "The lot must be in `SORTED`; its `captured_item_count` must equal its
    `sample_size`, or the request is refused with `ERR_SAMPLE_INCOMPLETE` because a
    lot cannot be valued until the full sample has been imaged; and the retailer
    that owns the lot's submission must not be `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/lot_finalize_gated_on_retailer_not_suspended
    """
    assert_fields(suspended_owner["suspended"],
                  {"status": RetailerStatus.SUSPENDED,
                   "handling_fee_tier": "PROBATION"})

    refused = api.finalize_lot(suspended_owner["lot_id"], ANALYST)
    validate_error(refused, err.ERR_RETAILER_SUSPENDED)

    lot = validate_success(api.get_lot(suspended_owner["lot_id"], ANALYST))
    assert_fields(lot, {"status": LotStatus.SORTED,
                        "captured_item_count": 2,
                        "sample_size": 2})
    assert_money(lot, "gross_face_value_cents", 0)
    assert_money(lot, "handling_fee_cents", 0)
    assert_nulls(lot, ["adjudicated_by_user_id"])

    for item in suspended_owner["items"]:
        stored = validate_success(api.get_item(item["id"], ANALYST))
        assert_fields(stored, {"status": ItemStatus.CAPTURED})


def test_09_the_suspension_answers_capture_before_the_full_sample_does(
        api, suspended_owner):
    """A third image into an already-complete lot still reports the suspension.

    "While a retailer is `SUSPENDED`, seven operations are blocked with
    `ERR_RETAILER_SUSPENDED`: opening a submission, verifying its count, sorting
    it into lots, capturing images into a lot, finalizing a lot, filing a dispute
    and reporting a digital redemption."

    Design: Difficulty/cross_entity_state_dependency/lot_finalize_gated_on_retailer_not_suspended
    """
    refused = api.capture_items(suspended_owner["lot_id"], [
        f.item_payload(suspended_owner["market"]["barcode"],
                       "s3://img/n3.jpg", "2026-07-05",
                       pos_transaction_ref="POS-N3", claimed_units=1)
    ], CLERK)
    validate_error(refused, err.ERR_RETAILER_SUSPENDED)

    lot = validate_success(api.get_lot(suspended_owner["lot_id"], ANALYST))
    assert_fields(lot, {"captured_item_count": 2})


def test_10_reinstatement_restores_the_tier_and_the_lot_prices_at_full_rate(
        api, build, suspended_owner):
    """14 cents, the STANDARD rate, not the 11 a probation multiplier would pay.

    "Reinstatement, also taking a `reason`, is available only from `SUSPENDED`:
    the retailer returns to `ACTIVE` and its `handling_fee_tier` is restored to
    `base_fee_tier`, again leaving `fraud_score` untouched — which means the very
    next rescore may push it straight back to `WATCHLIST` or `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/lot_finalize_gated_on_retailer_not_suspended
    """
    reinstated = build.reinstate_retailer(suspended_owner["retailer_id"],
                                          "Referral closed with no finding")
    assert_fields(reinstated, {"status": RetailerStatus.ACTIVE,
                               "handling_fee_tier": "STANDARD"})

    lot = build.finalize(suspended_owner["lot_id"])
    assert_fields(lot, {"status": LotStatus.VALIDATED, "accepted_qty": 2})
    assert_money(lot, "gross_face_value_cents", 100)
    assert_money(lot, "handling_fee_cents", 14)
    assert lot["handling_fee_cents"] != 11, (
        "11 is what the 0.80 probation multiplier would have paid; the tier is "
        "read at finalization and the retailer is back on STANDARD"
    )

    submission = validate_success(
        api.get_submission(suspended_owner["submission_id"], ANALYST))
    assert_fields(submission, {"intake_status": IntakeStatus.CLOSED})
    assert_money(submission, "settled_gross_face_value_cents", 100)
