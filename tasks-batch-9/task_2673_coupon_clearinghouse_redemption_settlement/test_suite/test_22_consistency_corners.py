"""Every cascaded field is already current in the very next read.

One finalize, then the first read of the parent submission, the first read of
the offer and one statement issuance — no waits, no retries, no second read of
the same resource — and every rolled-up number is already in place.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ANALYST,
    OFFICER,
    FRAUD_ANALYST_ID,
    IntakeStatus,
    LotStatus,
    SettlementStatus,
    StatementStatus,
    ValuationVariant,
    assert_fields,
    assert_lot_valuation,
    assert_millis_timestamp,
    assert_money,
    assert_nulls,
    assert_statement_waterfall,
    factories as f,
)


def test_01_every_cascaded_money_field_is_current_in_the_same_response(
        api, build):
    """The finalize body, the next parent read and the offer counter all agree.

    "Both branches write `adjudicated_by_user_id` from the acting `X-User-ID`
    and `adjudicated_at` from the logical clock — this is the
    segregation-of-duties wall that will later bar this same analyst from
    resolving a dispute over this lot — then recompute the owning submission's
    derived money fields and evaluate whether the submission can close."

    "Closing recomputes `adjudicated_face_value_cents`,
    `accepted_item_face_value_cents`, `rejected_item_face_value_cents`,
    `settled_gross_face_value_cents`, `settled_handling_fee_cents`,
    `rejected_lot_count` (the count of the submission's lots in `LOT_REJECTED`)
    and `valuation_method`, which is `FULL_COUNT` unless at least one of the
    submission's lots resolved to `SAMPLED_EXTRAPOLATION`, in which case it is
    `SAMPLED_EXTRAPOLATION`."

    "Before the lot is validated, the offer's `accepted_redemption_count` plus
    the units this lot would clear must not exceed the offer's `max_redemptions`, or
    the operation is refused with `ERR_MAX_REDEMPTIONS_EXCEEDED`; on success
    `accepted_redemption_count` increases by the cleared units and the offer's
    `version` is bumped."

    "**Step one**: `gross_face_value_cents` is the sum of
    `gross_face_value_cents` over the submission's lots in `VALIDATED` or
    `REINSTATED` — already-rounded lot values, summed as integers."

    Design: Corner/consistency_model/every_cascaded_money_field_is_already_current_in_the_same_response
    """
    world = build.market()
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-01", 5)
    submission = build.verified_submission(retailer_id, 2)
    lot = build.lot(submission["id"], world["offer_id"],
                    world["manufacturer_id"], 2)
    build.capture(lot["id"], f.item_batch(
        2, world["barcode"], "2026-07-05", pos_transaction_ref="POS-1"))

    finalized = validate_success(api.finalize_lot(lot["id"], ANALYST))
    assert_lot_valuation(finalized, LotStatus.VALIDATED, 2, 0, 2, 100, 14)
    assert_fields(finalized, {
        "adjudicated_by_user_id": FRAUD_ANALYST_ID,
        "valuation_variant": ValuationVariant.FULL_COUNT,
    })
    assert_nulls(finalized, ["reject_reason"])
    assert_millis_timestamp(finalized["adjudicated_at"], "adjudicated_at")
    assert finalized["adjudicated_at"].startswith("2026-08-01"), (
        "the finalize body already carries the logical-clock stamp"
    )

    parent = validate_success(api.get_submission(submission["id"], OFFICER))
    assert_fields(parent, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.PENDING,
        "rejected_lot_count": 0,
        "sorted_lot_count": 1,
        "valuation_method": ValuationVariant.FULL_COUNT,
    })
    assert_money(parent, "settled_gross_face_value_cents", 100)
    assert_money(parent, "settled_handling_fee_cents", 14)
    assert_money(parent, "accepted_item_face_value_cents", 100)
    assert_money(parent, "rejected_item_face_value_cents", 0)
    assert_money(parent, "adjudicated_face_value_cents", 100)

    offer = validate_success(
        api.get_offer(world["offer_id"], world["mfr_headers"]))
    assert_fields(offer, {"accepted_redemption_count": 2})

    statement = validate_success(api.issue_statement(
        submission["id"], parent["version"], OFFICER), 201)
    assert_fields(statement, {
        "status": StatementStatus.DRAFT,
        "retailer_id": retailer_id,
        "submission_id": submission["id"],
    })
    assert_statement_waterfall(statement, gross=100, fee_total=14, offset=0,
                               provisional_net=114, holdback_pct="0.00",
                               holdback=0, net_payable=114)
