"""Which refusal wins, and which ceilings are inclusive.

The same endpoint answers with two different codes depending on what can even
be evaluated; windows, redemption caps and funding totals all admit their exact
boundary and refuse the step past it without leaving partial work behind.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ANALYST,
    OFFICER,
    FeeTier,
    HoldReason,
    IntakeStatus,
    InvoiceStatus,
    ItemStatus,
    LotRejectReason,
    LotStatus,
    RetailerStatus,
    SettlementStatus,
    StatementStatus,
    COUNTERFEIT_DATABAR_PAYLOAD,
    api_errors as err,
    assert_fields,
    assert_manufacturer_ledger,
    assert_millis_timestamp,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    assert_sweep_counters,
    factories as f,
    make_manufacturer_headers,
    make_retailer_headers,
)


def test_01_the_state_check_answers_before_the_sample_readiness_check(
        api, build):
    """An under-imaged lot reports readiness; a finalized lot reports state.

    "The lot must be in `SORTED`; its `captured_item_count` must equal its
    `sample_size`, or the request is refused with `ERR_SAMPLE_INCOMPLETE` because a
    lot cannot be valued until the full sample has been imaged; and the retailer
    that owns the lot's submission must not be `SUSPENDED`."

    "The target row's current state admits the requested transition, judged
    against that entity's own transition table only — otherwise
    `ERR_INVALID_STATE_TRANSITION` (409)."

    "Because a single request can violate several rules at once, the order in
    which checks run is part of the contract: the **first** failing check decides
    the response, and later checks are not evaluated."

    Design: Corner/validations/state_check_outranks_the_sample_readiness_check_on_finalize
    """
    world = build.market()
    build.purchase_record(world["retailer_id"], world["offer_id"], "POS-1",
                          "2026-07-10", 5)
    submission = build.verified_submission(world["retailer_id"], 3)
    partial = build.lot(submission["id"], world["offer_id"],
                        world["manufacturer_id"], 2)
    ready = build.lot(submission["id"], world["offer_id"],
                      world["manufacturer_id"], 1)

    build.capture(partial["id"], f.item_batch(
        1, world["barcode"], "2026-07-10", pos_transaction_ref="POS-1"))
    build.capture(ready["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/ready.jpg", "2026-07-10",
        pos_transaction_ref="POS-1")])

    under_imaged = api.finalize_lot(partial["id"], ANALYST)
    validate_error(under_imaged, err.ERR_SAMPLE_INCOMPLETE,
                   expected_status=422)

    valued = validate_success(api.finalize_lot(ready["id"], ANALYST))
    assert_fields(valued, {"status": LotStatus.VALIDATED})
    assert_money(valued, "gross_face_value_cents", 50)
    assert_money(valued, "handling_fee_cents", 7)

    again = api.finalize_lot(ready["id"], ANALYST)
    validate_error(again, err.ERR_INVALID_STATE_TRANSITION,
                   expected_status=409)

    unchanged = validate_success(api.get_lot(ready["id"], ANALYST))
    assert unchanged["version"] == valued["version"], (
        "the refused second finalize wrote nothing, so the version stands "
        f"at {valued['version']}"
    )
    assert_fields(unchanged, {
        "status": LotStatus.VALIDATED,
        "captured_item_count": unchanged["sample_size"],
    })
    assert_money(unchanged, "handling_fee_cents", 7)


def test_02_the_dispute_window_admits_its_last_day_and_shuts_the_next(
        api, build):
    """Three days from adjudication is timely; the fourth is not.

    "The appeal must also be timely: the logical clock's calendar date must be on
    or before the lot's `adjudicated_at` date plus the issuing manufacturer's
    `dispute_window_days`, inclusive on the final day, and a late filing is
    refused with `ERR_DISPUTE_WINDOW_CLOSED`."

    "The lot must currently be in `LOT_REJECTED`, which by construction means no
    appeal over it is already live, since an open appeal parks the lot in
    `DISPUTED`."

    "A submission that closes with at least one validated lot does none of that
    and stays `PENDING` on the settlement dimension, waiting for an officer."

    Design: Corner/validations/dispute_window_closes_the_day_after_the_manufacturer_window
    """
    world = build.market(dispute_window_days=3)
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)
    submission = build.verified_submission(retailer_id, 3)

    condemned = []
    for label in ("r1", "r2"):
        lot = build.lot(submission["id"], world["offer_id"],
                        world["manufacturer_id"], 1)
        build.capture(lot["id"], [f.item_payload(
            COUNTERFEIT_DATABAR_PAYLOAD, f"s3://coupon-images/{label}.jpg",
            "2026-07-10", pos_transaction_ref="POS-1")])
        rejected = build.finalize(lot["id"])
        assert_fields(rejected, {
            "status": LotStatus.LOT_REJECTED,
            "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED,
        })
        condemned.append(lot)

    survivor = build.lot(submission["id"], world["offer_id"],
                         world["manufacturer_id"], 1)
    build.capture(survivor["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/v.jpg", "2026-07-10",
        pos_transaction_ref="POS-1")])
    build.finalize(survivor["id"])

    closed = validate_success(api.get_submission(submission["id"], ANALYST))
    assert_fields(closed, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.PENDING,
        "sorted_lot_count": 3,
        "rejected_lot_count": 2,
    })

    last_day = validate_success(api.set_clock("2026-08-04T09:00:00Z", ADMIN))
    assert_sweep_counters(last_day, "2026-08-04T09:00:00Z", 0, 0, 0)

    timely = validate_success(api.file_dispute(
        condemned[0]["id"], "IMAGE_QUALITY",
        "Databar was misread by the sorter.",
        make_retailer_headers(retailer_id)), 201)
    assert_fields(timely, {"lot_id": condemned[0]["id"]})
    assert_millis_timestamp(timely["filed_at"], "filed_at")
    assert timely["filed_at"].startswith("2026-08-04"), (
        "filed_at is taken from the logical clock, which now reads 2026-08-04"
    )

    one_day_late = validate_success(api.set_clock("2026-08-05T09:00:00Z", ADMIN))
    assert_sweep_counters(one_day_late, "2026-08-05T09:00:00Z", 0, 0, 0)

    refused = api.file_dispute(
        condemned[1]["id"], "IMAGE_QUALITY",
        "Same sorter fault as the first lot.",
        make_retailer_headers(retailer_id))
    validate_error(refused, err.ERR_DISPUTE_WINDOW_CLOSED,
                   expected_status=422)

    still_condemned = validate_success(
        api.get_lot(condemned[1]["id"], ANALYST))
    assert_fields(still_condemned, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED,
    })

    retailer = validate_success(api.get_retailer(retailer_id, ANALYST))
    assert_fields(retailer, {"status": RetailerStatus.ACTIVE,
                             "rejected_submission_count": 0})

    disputes, meta = validate_paginated(api.list_disputes(
        ANALYST, retailer_id=retailer_id, limit=10))
    assert meta["total_count"] == 1, (
        "only the timely appeal exists; the late one created nothing"
    )
    assert disputes[0]["id"] == timely["id"]


def test_03_a_totally_rejected_shipment_is_empty_not_merely_suspended(
        api, build):
    """Both shipments closed; only the one with a validated lot is settleable.

    "The submission must also have something to settle: at least one lot in
    `VALIDATED` or `REINSTATED`, or the request is refused with
    `ERR_EMPTY_SUBMISSION`, since a submission whose every lot was rejected has no
    value to pay out."

    "The retailer owning the affected submission chain must not have status
    `SUSPENDED` — otherwise `ERR_RETAILER_SUSPENDED` (403)."

    "This rule guards seven operations: submission creation, count verification,
    lot creation, item capture, lot finalization, dispute filing and
    digital-redemption reporting."

    Design: Corner/validations/all_rejected_submission_cannot_be_settled_but_its_sibling_can
    """
    world = build.market()
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)

    good = build.verified_submission(retailer_id, 1, "2026-07-01", "2026-07-15")
    good_lot = build.lot(good["id"], world["offer_id"],
                         world["manufacturer_id"], 1)
    build.capture(good_lot["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/good.jpg", "2026-07-10",
        pos_transaction_ref="POS-1")])

    bad = build.verified_submission(retailer_id, 1, "2026-07-15", "2026-07-31")
    bad_lot = build.lot(bad["id"], world["offer_id"],
                        world["manufacturer_id"], 1)
    build.capture(bad_lot["id"], [f.item_payload(
        COUNTERFEIT_DATABAR_PAYLOAD, "s3://coupon-images/bad.jpg",
        "2026-07-10", pos_transaction_ref="POS-1")])

    build.finalize(good_lot["id"])
    statement = build.issue_statement(good["id"])
    assert_money(statement, "gross_face_value_cents", 50)
    assert_money(statement, "handling_fee_total_cents", 7)
    assert_money(statement, "net_payable_cents", 57)

    condemned = validate_success(api.finalize_lot(bad_lot["id"], ANALYST))
    assert_fields(condemned, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED,
    })

    held = validate_success(api.get_submission(bad["id"], OFFICER))
    assert_fields(held, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.HELD,
        "hold_reason": HoldReason.FRAUD_REVIEW,
        "rejected_lot_count": 1,
        "sorted_lot_count": 1,
    })
    assert_money(held, "settled_gross_face_value_cents", 0)

    refused = api.issue_statement(bad["id"], held["version"], OFFICER)
    validate_error(refused, err.ERR_EMPTY_SUBMISSION, expected_status=422)

    suspended = validate_success(api.get_retailer(retailer_id, OFFICER))
    assert_fields(suspended, {
        "status": RetailerStatus.SUSPENDED,
        "handling_fee_tier": FeeTier.PROBATION,
        "rejected_submission_count": 1,
    })
    assert_rate_equals(suspended["counterfeit_rate"], "50.00",
                       "counterfeit_rate")
    assert_rate_equals(suspended["fraud_score"], "100.00", "fraud_score")

    rows, meta = validate_paginated(api.list_statements(
        OFFICER, retailer_id=retailer_id, limit=10))
    assert meta["total_count"] == 1, (
        "the refused issue created no second statement"
    )
    assert rows[0]["id"] == statement["id"]


def test_04_the_redemption_ceiling_admits_the_last_unit_and_stops_there(
        api, build):
    """A cap of two clears a two-unit lot and refuses the next single unit.

    "Before the lot is validated, the offer's `accepted_redemption_count` plus the
    units this lot would clear must not exceed the offer's `max_redemptions`, or
    the operation is refused with `ERR_MAX_REDEMPTIONS_EXCEEDED`; on success
    `accepted_redemption_count` increases by the cleared units and the offer's
    `version` is bumped."

    "On success one coupon item is created per element **in the supplied array
    order**, each in status `CAPTURED` with a null `reject_code`,
    `duplicate_of_item_id`, `matched_purchase_record_id` and `adjudicated_at`, and
    element number *k* receives a `created_at` of the logical clock plus *k*
    milliseconds — so `created_at` ascending is exactly the order of the request
    body, and the adjudication ladder's processing order is fully determined by how
    the clerk arranged the batch."

    Design: Corner/validations/redemption_ceiling_admits_the_exact_last_unit_and_refuses_the_next_lot
    """
    world = build.market(max_redemptions=2)
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)
    submission = build.verified_submission(retailer_id, 3)

    at_the_cap = build.lot(submission["id"], world["offer_id"],
                           world["manufacturer_id"], 2)
    one_too_many = build.lot(submission["id"], world["offer_id"],
                             world["manufacturer_id"], 1)
    build.capture(at_the_cap["id"], f.item_batch(
        2, world["barcode"], "2026-07-10", pos_transaction_ref="POS-1"))
    build.capture(one_too_many["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/extra.jpg", "2026-07-10",
        pos_transaction_ref="POS-1")])

    filled = validate_success(api.finalize_lot(at_the_cap["id"], ANALYST))
    assert_fields(filled, {
        "status": LotStatus.VALIDATED,
        "projected_accepted_units": 2,
    })
    assert_money(filled, "gross_face_value_cents", 100)
    assert_money(filled, "handling_fee_cents", 14)

    over = api.finalize_lot(one_too_many["id"], ANALYST)
    validate_error(over, err.ERR_MAX_REDEMPTIONS_EXCEEDED,
                   expected_status=422)

    offer = validate_success(
        api.get_offer(world["offer_id"], world["mfr_headers"]))
    assert_fields(offer, {"accepted_redemption_count": 2})

    rows, meta = validate_paginated(
        api.list_items(ANALYST, lot_id=one_too_many["id"], limit=10))
    assert meta["total_count"] == 1
    assert_fields(rows[0], {"status": ItemStatus.CAPTURED})
    assert_nulls(rows[0], ["reject_code", "adjudicated_at"])

    open_still = validate_success(api.get_submission(submission["id"], ANALYST))
    assert_fields(open_still, {"intake_status": IntakeStatus.SORTED})
    assert_money(open_still, "settled_gross_face_value_cents", 100)
    assert_money(open_still, "adjudicated_face_value_cents", 100)

    untouched = validate_success(api.get_lot(one_too_many["id"], ANALYST))
    assert_fields(untouched, {"status": LotStatus.SORTED})
    assert_nulls(untouched, ["adjudicated_at", "adjudicated_by_user_id"])


def test_05_funding_is_capped_cumulatively_across_two_wires(api, build):
    """Twenty is fine, the next thirty-nine is not, and thirty-eight completes it.

    "The invoice must be in `ISSUED` or `SHORT_FUNDED`, and the wire's
    `amount_cents` — a positive integer — must not push `funded_amount_cents` past
    `billed_total_cents`; overfunding is refused with
    `ERR_FUNDING_EXCEEDS_BILLED`."

    "**Branch B — short funding**: when the running total falls short,
    `funding_shortfall_cents` becomes `billed_total_cents` minus the new
    `funded_amount_cents`, the invoice moves to `SHORT_FUNDED`, the manufacturer's
    `funded_total_cents` grows by exactly the same `amount_cents` — and a
    three-hop cascade that branch A never runs freezes the whole downstream
    chain."

    "A newly created issuer is `ACTIVE` and its three ledger fields —
    `funded_total_cents`, `disbursed_total_cents` and `funding_balance_cents` — all
    start at 0."

    Design: Corner/validations/funding_cannot_overshoot_the_billed_total_across_two_wires
    """
    world = build.market()
    retailer_id = world["retailer_id"]
    manufacturer_id = world["manufacturer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-10", 5)
    submission = build.verified_submission(retailer_id, 1)
    lot = build.lot(submission["id"], world["offer_id"], manufacturer_id, 1)
    build.capture(lot["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/1.jpg", "2026-07-10",
        pos_transaction_ref="POS-1")])
    build.finalize(lot["id"])
    statement = build.issue_statement(submission["id"])

    invoice = build.invoice(manufacturer_id, "2026-07-01", "2026-07-31",
                            [statement["id"]])
    assert_money(invoice, "billed_face_value_cents", 50)
    assert_money(invoice, "billed_handling_fee_cents", 7)
    assert_money(invoice, "billed_clearing_fee_cents", 1)
    assert_money(invoice, "billed_total_cents", 58)
    assert_money(invoice, "funding_shortfall_cents", 58)

    headers = make_manufacturer_headers(manufacturer_id)
    partial = validate_success(api.fund_invoice(invoice["id"], 20, headers))
    assert_fields(partial, {"status": InvoiceStatus.SHORT_FUNDED})
    assert_money(partial, "funded_amount_cents", 20)
    assert_money(partial, "funding_shortfall_cents", 38)

    overshoot = api.fund_invoice(invoice["id"], 39, headers)
    validate_error(overshoot, err.ERR_FUNDING_EXCEEDS_BILLED,
                   expected_status=422)

    no_partial_credit = validate_success(
        api.get_invoice(invoice["id"], headers))
    assert_fields(no_partial_credit, {"status": InvoiceStatus.SHORT_FUNDED})
    assert_money(no_partial_credit, "funded_amount_cents", 20)

    completed = validate_success(api.fund_invoice(invoice["id"], 38, headers))
    assert_fields(completed, {"status": InvoiceStatus.FUNDED})
    assert_money(completed, "funded_amount_cents", 58)
    assert_money(completed, "funding_shortfall_cents", 0)

    issuer = validate_success(api.get_manufacturer(manufacturer_id, headers))
    assert_manufacturer_ledger(issuer, funded_total=58, disbursed_total=0)
    assert_money(issuer, "funding_balance_cents", 58)

    unmoved = validate_success(
        api.get_statement(statement["id"], OFFICER))
    assert_fields(unmoved, {"status": StatementStatus.DRAFT})
    assert_nulls(unmoved, ["hold_reason"])
