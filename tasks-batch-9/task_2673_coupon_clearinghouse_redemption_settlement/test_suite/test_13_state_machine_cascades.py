"""Transitions whose real weight lands on rows the caller never named.

A withdrawal condemns buckets three levels down, a close forks on whether every
bucket died, and an appeal freezes cash without unwinding the intake behind it.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ANALYST,
    CLERK,
    FRAUD_ANALYST_2_ID,
    OFFICER,
    ClipStatus,
    DisputeStatus,
    EventRejectCode,
    FeeTier,
    HoldReason,
    IntakeStatus,
    ItemStatus,
    LotRejectReason,
    LotStatus,
    ManufacturerStatus,
    OfferStatus,
    RedemptionEventStatus,
    RejectCode,
    RetailerStatus,
    SettlementStatus,
    StatementStatus,
    api_errors as err,
    assert_fields,
    assert_millis_timestamp,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    assert_retailer_unpaid,
    assert_statement_waterfall,
    assert_sweep_counters,
    assert_version_unchanged,
    factories as f,
    make_manufacturer_headers,
)


def _contract_market(build, **overrides):
    """The contract-rate issuer and a STANDARD, NET_30 retailer, one unit per coupon."""
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
        redemption_instructions="Save 50c on one can",
        max_redemptions=100000,
        purchase_requirement_units=1,
    )
    terms.update(overrides)
    return build.market(**terms)


@pytest.fixture
def withdraw_world(api, build):
    """One shipment already validated and paid-for on paper, one still in sort.

    The first shipment holds a single cleared coupon, so its lot is `VALIDATED`
    at 50 and 7 and the shipment is closed. The second shipment holds two fully
    imaged buckets that nobody finalized, so both are `SORTED` with their coupons
    still in `CAPTURED` and the shipment sits on the retailer's intake stream.
    """
    market = _contract_market(build)
    build.purchase_record(market["retailer_id"], market["offer_id"], "POS-1",
                          "2026-07-05", 1)
    settled = build.verified_submission(market["retailer_id"], 1,
                                        "2026-07-01", "2026-07-15")
    settled_lot = build.lot(settled["id"], market["offer_id"],
                            market["manufacturer_id"], 1)
    build.capture(settled_lot["id"], [
        f.item_payload(market["barcode"], "s3://img/a1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-1", claimed_units=1)])
    build.finalize(settled_lot["id"])

    open_sub = build.verified_submission(market["retailer_id"], 2,
                                         "2026-07-16", "2026-07-31")
    sorted_lots = []
    for position in (1, 2):
        lot = build.lot(open_sub["id"], market["offer_id"],
                        market["manufacturer_id"], 1)
        build.capture(lot["id"], [
            f.item_payload(market["barcode"], f"s3://img/b{position}.jpg",
                           "2026-07-20", pos_transaction_ref="POS-1",
                           claimed_units=1)])
        sorted_lots.append(lot)
    return {
        "market": market,
        "offer": market["offer"],
        "settled_id": settled["id"],
        "settled_lot": validate_success(api.get_lot(settled_lot["id"], ANALYST)),
        "open_id": open_sub["id"],
        "sorted_ids": [lot["id"] for lot in sorted_lots],
    }


def test_01_withdrawal_condemns_the_sorted_buckets_and_spares_the_validated_one(
        api, withdraw_world):
    """Two buckets die unvalued with their coupons still in `CAPTURED`.

    "In the first hop, every submission lot pointing at this offer whose status
    is still `SORTED` is set to `LOT_REJECTED` with `reject_reason` set to
    `OFFER_WITHDRAWN`, processed in lot `created_at` ascending order; those lots
    are never valued, so their `gross_face_value_cents` and `handling_fee_cents`
    remain 0, and — importantly — every coupon item inside them stays in
    `CAPTURED`, because nothing is adjudicated by a withdrawal."

    "The manufacturer that owns the offer (its `manufacturer_id` matching the
    acting `X-User-ID`) may withdraw it from `REGISTERED`, `ACTIVE` or `EXPIRED`,
    supplying a `withdrawn_reason` of 1 to 200 characters that is stored on the
    offer; the offer becomes `WITHDRAWN`, which is terminal."

    Design: Corner/state_machines/offer_withdraw_cascades_only_sorted_lots_and_closes_that_submission
    """
    market = withdraw_world["market"]

    withdrawn = validate_success(api.withdraw_offer(
        market["offer_id"], "Trade dispute with the brand team",
        market["mfr_headers"]))
    assert_fields(withdrawn, {
        "status": OfferStatus.WITHDRAWN,
        "withdrawn_reason": "Trade dispute with the brand team",
    })

    for lot_id in withdraw_world["sorted_ids"]:
        condemned = validate_success(api.get_lot(lot_id, ANALYST))
        assert_fields(condemned, {
            "status": LotStatus.LOT_REJECTED,
            "reject_reason": LotRejectReason.OFFER_WITHDRAWN,
            "accepted_qty": 0,
        })
        assert_money(condemned, "gross_face_value_cents", 0)
        assert_money(condemned, "handling_fee_cents", 0)
        assert_nulls(condemned, ["adjudicated_by_user_id"])

    before = withdraw_world["settled_lot"]
    after = validate_success(api.get_lot(before["id"], ANALYST))
    assert_fields(after, {"status": LotStatus.VALIDATED, "accepted_qty": 1})
    assert_nulls(after, ["reject_reason"])
    assert_money(after, "gross_face_value_cents", 50)
    assert_money(after, "handling_fee_cents", 7)
    assert_version_unchanged(before, after)

    for lot_id in withdraw_world["sorted_ids"]:
        coupons, meta = validate_paginated(api.list_items(ANALYST, lot_id=lot_id))
        assert_fields(meta, {"total_count": 1})
        assert [row["status"] for row in coupons] == [ItemStatus.CAPTURED], (
            "a withdrawal adjudicates nothing, so the coupons stay in CAPTURED"
        )
        assert_nulls(coupons[0], ["reject_code"])


def test_02_the_all_rejected_shipment_closes_held_while_its_sibling_is_untouched(
        api, withdraw_world):
    """A total loss on one shipment, and not a cent moved on the other.

    "In the second hop, each submission that owned one of those lots recomputes
    `rejected_lot_count`, `declared_face_value_cents`,
    `settled_gross_face_value_cents` and `settled_handling_fee_cents`."

    "In the third hop, a submission that now has every one of its lots in
    `VALIDATED` or `LOT_REJECTED` advances its `intake_status` from `SORTED` to
    `CLOSED`; and if every one of its lots is `LOT_REJECTED`, its
    `settlement_status` becomes `HELD` with `hold_reason` set to `FRAUD_REVIEW`
    and the owning retailer's `rejected_submission_count` increments by 1."

    "Creating the lot also increments the submission's `sorted_lot_count` and
    recomputes its `declared_face_value_cents`, which is the sum over the
    submission's lots of each lot's `counted_qty` multiplied by that lot's offer
    face value — the notional value of the shipment before anyone has adjudicated
    anything."

    Design: Corner/state_machines/offer_withdraw_cascades_only_sorted_lots_and_closes_that_submission
    """
    market = withdraw_world["market"]
    validate_success(api.withdraw_offer(
        market["offer_id"], "Trade dispute with the brand team",
        market["mfr_headers"]))

    total_loss = validate_success(
        api.get_submission(withdraw_world["open_id"], CLERK))
    assert_fields(total_loss, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.HELD,
        "hold_reason": HoldReason.FRAUD_REVIEW,
        "sorted_lot_count": 2,
        "rejected_lot_count": 2,
    })
    assert_money(total_loss, "declared_face_value_cents", 100)
    assert_money(total_loss, "adjudicated_face_value_cents", 0)
    assert_money(total_loss, "settled_gross_face_value_cents", 0)
    assert_money(total_loss, "settled_handling_fee_cents", 0)

    spared = validate_success(
        api.get_submission(withdraw_world["settled_id"], CLERK))
    assert_fields(spared, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.PENDING,
        "rejected_lot_count": 0,
    })
    assert_nulls(spared, ["hold_reason"])
    assert_money(spared, "settled_gross_face_value_cents", 50)
    assert_money(spared, "settled_handling_fee_cents", 7)

    retailer = validate_success(api.get_retailer(market["retailer_id"], ANALYST))
    assert_fields(retailer, {"rejected_submission_count": 1,
                             "status": RetailerStatus.ACTIVE,
                             "handling_fee_tier": FeeTier.STANDARD})
    for field in ("duplicate_rate", "misredemption_rate", "counterfeit_rate",
                  "fraud_score"):
        assert_rate_equals(retailer[field], "0.00", field)

    offer = validate_success(api.get_offer(market["offer_id"], ADMIN))
    assert offer["accepted_redemption_count"] == 1, (
        "the cascade never rolls back units a validated bucket already cleared"
    )


@pytest.fixture
def disputable_statement(build):
    """A closed shipment of one cleared bucket and one condemned bucket, scheduled.

    The cleared bucket carries a coupon backed by basket `POS-A`; the condemned
    one carries a coupon quoting a reference no basket owns, so it rejects for
    `NO_PURCHASE_MATCH` and the whole bucket falls to `LOT_REJECTED`.
    """
    market = _contract_market(build)
    build.purchase_record(market["retailer_id"], market["offer_id"], "POS-A",
                          "2026-07-05", 1)
    submission = build.verified_submission(market["retailer_id"], 2,
                                           "2026-07-01", "2026-07-31")
    lot_a = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 1)
    build.capture(lot_a["id"], [
        f.item_payload(market["barcode"], "s3://img/a.jpg", "2026-07-05",
                       pos_transaction_ref="POS-A", claimed_units=1)])
    lot_b = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 1)
    coupon_b = build.capture(lot_b["id"], [
        f.item_payload(market["barcode"], "s3://img/b.jpg", "2026-07-05",
                       pos_transaction_ref="POS-NONE", claimed_units=1)])
    build.finalize(lot_a["id"])
    build.finalize(lot_b["id"])
    draft = build.issue_statement(submission["id"])
    scheduled = build.schedule(draft["id"])
    return {
        "market": market,
        "submission_id": submission["id"],
        "lot_a_id": lot_a["id"],
        "lot_b_id": lot_b["id"],
        "coupon_b_id": coupon_b[0]["id"],
        "statement_id": draft["id"],
        "statement": scheduled,
    }


def test_03_an_appeal_freezes_the_payment_and_leaves_the_intake_settled(
        api, disputable_statement):
    """The statement is `HELD`, the balance drops, and the shipment does not move.

    "And because money over contested paper must not move, any settlement
    statement over the lot's submission that is still in `DRAFT` or in `SCHEDULED`
    is put into `HELD` with `hold_reason` set to `DISPUTE_OPEN`."

    "On this dispute-driven path the submission itself is **not** touched: a
    submission whose statement was already `STATEMENT_ISSUED` stays
    `STATEMENT_ISSUED`, because the intake batch really is settled and only the
    payment is frozen."

    "The owning retailer's `unpaid_balance_cents` is nevertheless recomputed over
    its `SCHEDULED` statements only, so the held amount leaves the payable
    balance."

    Design: Corner/state_machines/dispute_filing_holds_the_scheduled_statement_but_not_the_submission
    """
    market = disputable_statement["market"]
    assert_statement_waterfall(disputable_statement["statement"], gross=50,
                               fee_total=7, offset=0, provisional_net=57,
                               holdback_pct="0.0000", holdback=0,
                               net_payable=57)
    assert_fields(disputable_statement["statement"], {
        "status": StatementStatus.SCHEDULED,
        "scheduled_pay_date": "2026-08-31",
    })
    before = validate_success(api.get_retailer(market["retailer_id"], ANALYST))
    assert_retailer_unpaid(before, 57)

    filed = validate_success(api.file_dispute(
        disputable_statement["lot_b_id"], "POS_DATA_LATE",
        "The POS extract was loaded a day late", market["ret_headers"]), 201)
    assert_fields(filed, {"status": DisputeStatus.UNDER_REVIEW,
                          "info_request_count": 0})
    assert_money(filed, "claimed_face_value_cents", 50)
    assert_millis_timestamp(filed["filed_at"], "filed_at")
    assert filed["filed_at"].startswith("2026-08-01"), (
        "filed_at is taken from the logical clock, which still reads 2026-08-01"
    )

    held = validate_success(
        api.get_statement(disputable_statement["statement_id"], OFFICER))
    assert_fields(held, {"status": StatementStatus.HELD,
                         "hold_reason": HoldReason.DISPUTE_OPEN,
                         "scheduled_pay_date": "2026-08-31"})
    assert_money(held, "net_payable_cents", 57)

    submission = validate_success(
        api.get_submission(disputable_statement["submission_id"], OFFICER))
    assert_fields(submission, {
        "settlement_status": SettlementStatus.STATEMENT_ISSUED})
    assert_nulls(submission, ["hold_reason"])

    after = validate_success(api.get_retailer(market["retailer_id"], ANALYST))
    assert_retailer_unpaid(after, 0)

    lot_b = validate_success(
        api.get_lot(disputable_statement["lot_b_id"], ANALYST))
    assert_fields(lot_b, {"status": LotStatus.DISPUTED,
                          "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED})
    coupon = validate_success(
        api.get_item(disputable_statement["coupon_b_id"], ANALYST))
    assert_fields(coupon, {"status": ItemStatus.REJECTED_MISREDEEMED,
                           "reject_code": RejectCode.NO_PURCHASE_MATCH})


@pytest.fixture
def two_shipments(build):
    """One retailer, two adjacent postmark windows, three buckets awaiting a verdict.

    The mixed shipment holds a bucket backed by basket `POS-1` and a bucket whose
    coupon quotes an unknown reference; the second shipment holds one bucket of
    the unbacked kind only. Nothing is finalized yet, so every close below is the
    test's own trigger.
    """
    market = _contract_market(build)
    build.purchase_record(market["retailer_id"], market["offer_id"], "POS-1",
                          "2026-07-05", 1)
    mixed = build.verified_submission(market["retailer_id"], 2,
                                      "2026-07-01", "2026-07-15")
    lot_clean = build.lot(mixed["id"], market["offer_id"],
                          market["manufacturer_id"], 1)
    build.capture(lot_clean["id"], [
        f.item_payload(market["barcode"], "s3://img/m1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-1", claimed_units=1)])
    lot_unbacked = build.lot(mixed["id"], market["offer_id"],
                             market["manufacturer_id"], 1)
    build.capture(lot_unbacked["id"], [
        f.item_payload(market["barcode"], "s3://img/m2.jpg", "2026-07-05",
                       pos_transaction_ref="POS-9", claimed_units=1)])

    total_loss = build.verified_submission(market["retailer_id"], 1,
                                           "2026-07-15", "2026-07-31")
    lot_lost = build.lot(total_loss["id"], market["offer_id"],
                         market["manufacturer_id"], 1)
    build.capture(lot_lost["id"], [
        f.item_payload(market["barcode"], "s3://img/r1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-9", claimed_units=1)])
    return {
        "market": market,
        "mixed_id": mixed["id"],
        "lot_clean_id": lot_clean["id"],
        "lot_unbacked_id": lot_unbacked["id"],
        "total_loss_id": total_loss["id"],
        "lot_lost_id": lot_lost["id"],
    }


def test_04_a_close_with_one_survivor_runs_no_part_of_the_fraud_branch(
        api, build, two_shipments):
    """`PENDING`, no counter, no score, and a retailer nobody has touched.

    "When the submission is in `SORTED` and every one of its lots has reached
    `VALIDATED` or `LOT_REJECTED`, the submission advances `SORTED` → `CLOSED`."

    "A submission that closes with at least one validated lot does none of that
    and stays `PENDING` on the settlement dimension, waiting for an officer."

    "Because the interval is half-open, exact adjacency is legal — an existing
    window ending 2026-07-31 and a new window starting 2026-07-31 do not overlap
    — while any genuine overlap is refused with `ERR_POSTMARK_WINDOW_OVERLAP`."

    Design: Corner/state_machines/submission_close_fraud_branch_fires_only_when_every_lot_is_rejected
    """
    market = two_shipments["market"]

    validate_success(api.finalize_lot(two_shipments["lot_clean_id"], ANALYST))
    still_open = validate_success(
        api.get_submission(two_shipments["mixed_id"], CLERK))
    assert still_open["intake_status"] == IntakeStatus.SORTED, (
        "one bucket is still SORTED, so the shipment cannot close yet"
    )

    condemned = validate_success(
        api.finalize_lot(two_shipments["lot_unbacked_id"], ANALYST))
    assert_fields(condemned, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED})

    closed = validate_success(
        api.get_submission(two_shipments["mixed_id"], CLERK))
    assert_fields(closed, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.PENDING,
        "sorted_lot_count": 2,
        "rejected_lot_count": 1,
    })
    assert_nulls(closed, ["hold_reason"])
    assert_money(closed, "settled_gross_face_value_cents", 50)
    assert_money(closed, "settled_handling_fee_cents", 7)

    retailer = validate_success(api.get_retailer(market["retailer_id"], ANALYST))
    assert_fields(retailer, {"rejected_submission_count": 0,
                             "status": RetailerStatus.ACTIVE,
                             "version": 1})
    assert_rate_equals(retailer["fraud_score"], "0.00", "fraud_score")
    assert_nulls(retailer, ["last_rescored_at"])

    untouched = validate_success(
        api.get_submission(two_shipments["total_loss_id"], CLERK))
    assert_fields(untouched, {"intake_status": IntakeStatus.SORTED,
                              "settlement_status": SettlementStatus.PENDING})


def test_05_the_all_rejected_close_holds_the_shipment_and_rescores_the_retailer(
        api, two_shipments):
    """A 66.67 score fires the cascade without moving the retailer off `ACTIVE`.

    "One further cascade runs **only** in the total-loss case, where
    `rejected_lot_count` equals `sorted_lot_count`: the submission's
    `settlement_status` is set to `HELD` with `hold_reason` `FRAUD_REVIEW`, the
    retailer's `rejected_submission_count` increments by 1, the retailer's fraud
    score is re-derived from scratch, and the resulting status and tier gate of
    §3.6 is applied."

    "Three component rates come out of that pool, each computed as the count of
    matching items multiplied by one hundred, divided by the pool size, rounded
    half up to two decimal places: `duplicate_rate` counts items in
    `REJECTED_DUPLICATE`, `misredemption_rate` counts items in
    `REJECTED_MISREDEEMED`, and `counterfeit_rate` counts items in
    `REJECTED_COUNTERFEIT`."

    "Separately and on the same boundary, the effective `handling_fee_tier`
    becomes `PROBATION` at `70.00` or above and reverts to the retailer's
    `base_fee_tier` below it — so the tier always returns to the contracted base
    and never to a remembered `PROBATION`."

    Design: Corner/state_machines/submission_close_fraud_branch_fires_only_when_every_lot_is_rejected
    """
    market = two_shipments["market"]
    validate_success(api.finalize_lot(two_shipments["lot_clean_id"], ANALYST))
    validate_success(api.finalize_lot(two_shipments["lot_unbacked_id"], ANALYST))

    lost = validate_success(api.finalize_lot(two_shipments["lot_lost_id"], ANALYST))
    assert_fields(lost, {"status": LotStatus.LOT_REJECTED,
                         "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED})

    held = validate_success(
        api.get_submission(two_shipments["total_loss_id"], CLERK))
    assert_fields(held, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.HELD,
        "hold_reason": HoldReason.FRAUD_REVIEW,
        "sorted_lot_count": 1,
        "rejected_lot_count": 1,
    })

    retailer = validate_success(api.get_retailer(market["retailer_id"], ANALYST))
    assert_fields(retailer, {"rejected_submission_count": 1,
                             "status": RetailerStatus.ACTIVE,
                             "handling_fee_tier": FeeTier.STANDARD})
    assert retailer["last_rescored_at"] is not None, (
        "the total-loss close re-derives the score, which writes last_rescored_at"
    )
    assert_rate_equals(retailer["misredemption_rate"], "66.67",
                       "misredemption_rate")
    assert_rate_equals(retailer["duplicate_rate"], "0.00", "duplicate_rate")
    assert_rate_equals(retailer["counterfeit_rate"], "0.00", "counterfeit_rate")
    assert_rate_equals(retailer["fraud_score"], "66.67", "fraud_score")

    mixed = validate_success(api.get_submission(two_shipments["mixed_id"], CLERK))
    assert_fields(mixed, {"settlement_status": SettlementStatus.PENDING})
    assert_nulls(mixed, ["hold_reason"])


def test_06_the_sla_sweep_spares_the_thirtieth_day_and_fires_on_the_thirty_first(
        api, build, disputable_statement):
    """2026-08-31 is exactly the allowance; only 2026-09-01 is past it.

    "Every `Dispute` whose status is `UNDER_REVIEW` or `INFO_REQUESTED`, and whose
    filing date plus the dispute service-level allowance of 30 days is strictly
    earlier than the new clock's calendar date, moves to `WITHDRAWN` and returns
    its lot to `LOT_REJECTED`; processed in `created_at` ascending order."

    "The dispute service-level allowance is 30 days from `filed_at`, and the sweep
    inside a clock advance moves every dispute still in `UNDER_REVIEW` or
    `INFO_REQUESTED` whose filing date plus 30 days is strictly earlier than the
    new calendar date to `WITHDRAWN`, returning its lot `DISPUTED` →
    `LOT_REJECTED` with `reject_reason` `DISPUTE_UPHELD` — the same outcome as an
    upheld decision, reached by silence."

    Design: Corner/state_machines/dispute_sla_sweep_withdraws_at_thirty_one_days_not_thirty
    """
    market = disputable_statement["market"]
    dispute = build.file_dispute(disputable_statement["lot_b_id"],
                                market["retailer_id"], "POS_DATA_LATE",
                                "The POS extract was loaded a day late")

    on_the_boundary = validate_success(api.set_clock("2026-08-31T00:00:00Z"))
    assert_sweep_counters(on_the_boundary, "2026-08-31T00:00:00Z",
                          expired_offer_count=0, expired_clip_count=0,
                          withdrawn_dispute_count=0)

    alive = validate_success(api.get_dispute(dispute["id"], ANALYST))
    assert_fields(alive, {"status": DisputeStatus.UNDER_REVIEW, "version": 1})

    one_day_later = validate_success(api.set_clock("2026-09-01T00:00:00Z"))
    assert_sweep_counters(one_day_later, "2026-09-01T00:00:00Z",
                          expired_offer_count=0, expired_clip_count=0,
                          withdrawn_dispute_count=1)

    swept = validate_success(api.get_dispute(dispute["id"], ANALYST))
    assert_fields(swept, {"status": DisputeStatus.WITHDRAWN})
    assert_nulls(swept, ["resolved_by_user_id", "resolution_note"])

    lot_b = validate_success(
        api.get_lot(disputable_statement["lot_b_id"], ANALYST))
    assert_fields(lot_b, {"status": LotStatus.LOT_REJECTED,
                          "reject_reason": LotRejectReason.DISPUTE_UPHELD})
    assert_money(lot_b, "gross_face_value_cents", 0)

    coupon = validate_success(
        api.get_item(disputable_statement["coupon_b_id"], ANALYST))
    assert_fields(coupon, {"status": ItemStatus.REJECTED_MISREDEEMED})


def test_07_a_lot_may_be_appealed_again_once_the_first_appeal_is_upheld(
        api, build, disputable_statement):
    """The loop runs rejected, disputed, rejected, disputed, reinstated.

    "The dispute becomes `UPHELD` and the lot returns `DISPUTED` →
    `LOT_REJECTED`, this time with `reject_reason` set to `DISPUTE_UPHELD`."

    "This closes a `LOT_REJECTED` → `DISPUTED` → `LOT_REJECTED` revision cycle,
    and the retailer may file again as long as the manufacturer's dispute window
    is still open."

    "Every coupon of the lot in `REJECTED_EXPIRED`, `REJECTED_COUNTERFEIT`,
    `REJECTED_DUPLICATE` or `REJECTED_MISREDEEMED` is moved to `REINSTATED`, with
    its `reject_code` cleared and its `duplicate_of_item_id` cleared, processed in
    coupon `created_at` ascending order."

    "The owning submission then recomputes `accepted_item_face_value_cents`,
    `rejected_item_face_value_cents`, `settled_gross_face_value_cents`,
    `settled_handling_fee_cents` and `rejected_lot_count`, while
    `adjudicated_face_value_cents` stays numerically identical — value moves from
    the rejected column to the accepted column and the conserved total does not
    budge."

    Design: Corner/state_machines/lot_can_be_disputed_again_after_the_first_dispute_closes
    """
    market = disputable_statement["market"]
    lot_id = disputable_statement["lot_b_id"]

    first = build.file_dispute(lot_id, market["retailer_id"], "POS_DATA_LATE",
                               "First filing")
    disputed = validate_success(api.get_lot(lot_id, ANALYST))
    assert_fields(disputed, {"status": LotStatus.DISPUTED})

    upheld = build.resolve_dispute(first["id"], "UPHELD",
                                   "POS extract still missing")
    assert_fields(upheld, {"status": DisputeStatus.UPHELD,
                           "resolved_by_user_id": FRAUD_ANALYST_2_ID})
    rejected_again = validate_success(api.get_lot(lot_id, ANALYST))
    assert_fields(rejected_again, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.DISPUTE_UPHELD})

    second = validate_success(api.file_dispute(
        lot_id, "POS_DATA_LATE", "Second filing with the extract attached",
        market["ret_headers"]), 201)
    assert_fields(second, {"status": DisputeStatus.UNDER_REVIEW})
    overturned = build.resolve_dispute(second["id"], "OVERTURNED",
                                       "Extract verified")
    assert_fields(overturned, {"status": DisputeStatus.OVERTURNED})

    reinstated = validate_success(api.get_lot(lot_id, ANALYST))
    assert_fields(reinstated, {"status": LotStatus.REINSTATED,
                               "accepted_qty": 1, "rejected_qty": 0})
    assert_nulls(reinstated, ["reject_reason"])
    assert_money(reinstated, "gross_face_value_cents", 50)
    assert_money(reinstated, "handling_fee_cents", 7)

    coupon = validate_success(
        api.get_item(disputable_statement["coupon_b_id"], ANALYST))
    assert_fields(coupon, {"status": ItemStatus.REINSTATED})
    assert_nulls(coupon, ["reject_code", "duplicate_of_item_id"])

    submission = validate_success(
        api.get_submission(disputable_statement["submission_id"], OFFICER))
    assert_fields(submission, {"rejected_lot_count": 0})
    assert_money(submission, "adjudicated_face_value_cents", 100)
    assert_money(submission, "accepted_item_face_value_cents", 100)
    assert_money(submission, "rejected_item_face_value_cents", 0)
    assert_money(submission, "settled_gross_face_value_cents", 100)
    assert_money(submission, "settled_handling_fee_cents", 14)

    offer = validate_success(api.get_offer(market["offer_id"], ADMIN))
    assert offer["accepted_redemption_count"] == 2, (
        "one unit cleared at finalization and one more at the reinstatement"
    )

    rows, meta = validate_paginated(api.list_disputes(ANALYST, lot_id=lot_id))
    assert_fields(meta, {"total_count": 2})
    assert sorted(row["status"] for row in rows) == [
        DisputeStatus.OVERTURNED, DisputeStatus.UPHELD], (
        "both appeals over the one lot survive as history"
    )


def test_08_the_sweep_and_the_matcher_agree_exactly_on_the_expiry_day(
        api, build):
    """A clip redeemed on 2026-08-06 matches; the same clip a day later is swept.

    "That last comparison is inclusive, so a clip redeemed on its own expiry date
    still matches — and because the clock's clip-expiry sweep uses a strict
    comparison in the other direction, the two rules agree exactly on the boundary
    day and there is no date on which a clip is both sweepable and matchable."

    "When the matcher returns a winner the event is created `MATCHED` with
    `matched_clip_id` set to the winner, that clip moves `CLIPPED` → `MATCHED`
    with its `matched_event_id` pointing back at the new event, and the offer's
    `accepted_redemption_count` increases by 1 — one unit per digital redemption,
    unlike the multi-unit lot clearances of §3.5."

    "When the pool is empty the event is still created, with status `UNMATCHED`, a
    null `matched_clip_id` and a `reject_code` of `NO_ELIGIBLE_CLIP`; no clip is
    consumed and `accepted_redemption_count` is unchanged."

    Design: Corner/state_machines/digital_event_records_unmatched_when_the_only_clip_has_expired
    """
    market = _contract_market(build, offer_code="SOUP50D",
                              digital_enabled=True, clip_validity_days=5,
                              redemption_instructions="Clip and save 50c")
    first = build.clip(market["offer_id"], "C1")
    second = build.clip(market["offer_id"], "C2")
    for clip in (first, second):
        assert_fields(clip, {"clipped_at": "2026-08-01",
                             "clip_expires_at": "2026-08-06",
                             "status": ClipStatus.CLIPPED})

    on_the_boundary = validate_success(api.set_clock("2026-08-06T00:00:00Z"))
    assert_sweep_counters(on_the_boundary, "2026-08-06T00:00:00Z",
                          expired_offer_count=0, expired_clip_count=0,
                          withdrawn_dispute_count=0)

    matched = validate_success(api.create_redemption_event(
        market["offer_id"], market["retailer_id"], "C1",
        market["ret_headers"]), 201)
    assert_fields(matched, {"status": RedemptionEventStatus.MATCHED,
                            "matched_clip_id": first["id"],
                            "redeemed_at": "2026-08-06"})
    assert_nulls(matched, ["reject_code"])
    assert_money(matched, "face_value_cents", 50)

    consumed = validate_success(api.get_clip(first["id"], ADMIN))
    assert_fields(consumed, {"status": ClipStatus.MATCHED,
                             "matched_event_id": matched["id"]})

    one_day_later = validate_success(api.set_clock("2026-08-07T00:00:00Z"))
    assert_sweep_counters(one_day_later, "2026-08-07T00:00:00Z",
                          expired_offer_count=0, expired_clip_count=1,
                          withdrawn_dispute_count=0)
    lapsed = validate_success(api.get_clip(second["id"], ADMIN))
    assert_fields(lapsed, {"status": ClipStatus.EXPIRED_UNUSED})
    assert_nulls(lapsed, ["matched_event_id"])

    unmatched = validate_success(api.create_redemption_event(
        market["offer_id"], market["retailer_id"], "C2",
        market["ret_headers"]), 201)
    assert_fields(unmatched, {"status": RedemptionEventStatus.UNMATCHED,
                              "reject_code": EventRejectCode.NO_ELIGIBLE_CLIP,
                              "redeemed_at": "2026-08-07"})
    assert_nulls(unmatched, ["matched_clip_id"])
    assert_money(unmatched, "face_value_cents", 50)

    offer = validate_success(api.get_offer(market["offer_id"], ADMIN))
    assert offer["accepted_redemption_count"] == 1, (
        "the matched event advanced the counter once and the unmatched one not at all"
    )


def test_09_suspension_is_terminal_and_takes_the_issuer_s_draft_offer_with_it(
        api, build):
    """No second suspend, no registration, and no new offer under a dead issuer.

    "Suspension is not, however, a passive gate: as a side effect, every offer of
    that issuer whose status is `DRAFT`, `REGISTERED` or `ACTIVE` is moved to
    `WITHDRAWN` with `withdrawn_reason` set to the literal value
    `MANUFACTURER_SUSPENDED`, processed in offer `created_at` ascending order, and
    each of those withdrawals runs the full offer-withdrawal cascade described in
    §3.2."

    "Attempting to suspend an issuer that is already `SUSPENDED` is refused with
    `ERR_INVALID_STATE_TRANSITION`."

    "The target row's current state admits the requested transition, judged
    against that entity's own transition table only — otherwise
    `ERR_INVALID_STATE_TRANSITION` (409)."

    "The manufacturer owning the affected offer or invoice must not have status
    `SUSPENDED` — otherwise `ERR_MANUFACTURER_SUSPENDED` (403)."

    Design: Corner/state_machines/manufacturer_suspended_is_terminal_and_blocks_offer_registration
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    headers = make_manufacturer_headers(mfr["id"])
    draft = build.offer(mfr["id"], offer_code="SOUP50", max_redemptions=1000)
    assert_fields(draft, {"status": OfferStatus.DRAFT, "version": 1})

    suspended = validate_success(api.suspend_manufacturer(
        mfr["id"], f.suspend_payload("Unfunded invoices past 90 days"), ADMIN))
    assert_fields(suspended, {"status": ManufacturerStatus.SUSPENDED,
                              "version": 2})

    cascaded = validate_success(api.get_offer(draft["id"], headers))
    assert_fields(cascaded, {"status": OfferStatus.WITHDRAWN,
                             "withdrawn_reason": "MANUFACTURER_SUSPENDED"})
    assert_nulls(cascaded, ["barcode_payload"])

    validate_error(api.suspend_manufacturer(
        mfr["id"], f.suspend_payload("Second attempt"), ADMIN),
        err.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    validate_error(api.register_offer(draft["id"], headers),
                   err.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    unregistered = validate_success(api.get_offer(draft["id"], headers))
    assert_fields(unregistered, {"status": OfferStatus.WITHDRAWN})
    assert_nulls(unregistered, ["barcode_payload"])

    validate_error(api.create_offer(
        f.offer_payload(mfr["id"], offer_code="SOUP60", max_redemptions=1000),
        headers), err.ERR_MANUFACTURER_SUSPENDED, expected_status=403)

    unchanged = validate_success(api.get_manufacturer(mfr["id"], ADMIN))
    assert_fields(unchanged, {"status": ManufacturerStatus.SUSPENDED,
                              "version": 2})
