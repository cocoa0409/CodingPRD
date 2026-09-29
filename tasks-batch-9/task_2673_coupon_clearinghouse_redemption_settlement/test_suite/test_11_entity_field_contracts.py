"""Field-level contracts: what the server owns, what it bounds, what it copies.

Identity and audit columns are the server's alone, every declared bound bites at
its own edge, and the immutable basket carries no audit columns at all.
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
    OFFICER,
    SETTLEMENT_OFFICER_ID,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    CANONICAL_DATABAR_PAYLOAD,
    Channel,
    ClipStatus,
    IntakeStatus,
    ItemStatus,
    LotStatus,
    RedemptionEventStatus,
    RetailerStatus,
    SettlementStatus,
    StatementStatus,
    ValuationVariant,
    api_errors as err,
    assert_fields,
    assert_freshly_created,
    assert_holdback_pct,
    assert_immutable_identity,
    assert_money,
    assert_nulls,
    assert_purchase_record_exact_keys,
    assert_rate_equals,
    factories as f,
    make_manufacturer_headers,
)


def test_09_identity_and_audit_columns_are_the_servers_alone(api):
    """The caller may not seed status or id, and the first mutation moves version to 2.

    "Clients never supply an `id`, and no endpoint accepts one in a request body."

    "Most resources additionally carry `updated_at`, in the same format, and
    `version`, an integer that starts at 1 when the row is created and increments
    by exactly 1 on every mutation of that row."

    Design: Corner/entities/system_fields_minted_by_server_and_body_input_ignored
    """
    validate_error(api.create_retailer(
        {"legal_name": "Northgate Markets", "status": RetailerStatus.SUSPENDED},
        ADMIN), err.ERR_INVALID_REQUEST, expected_status=400)
    validate_error(api.create_retailer(
        {"legal_name": "Northgate Markets",
         "id": "11111111-1111-4111-8111-111111111111"}, ADMIN),
        err.ERR_INVALID_REQUEST, expected_status=400)

    created = validate_success(api.create_retailer(
        {"legal_name": "Northgate Markets"}, ADMIN), 201)
    assert_fields(created, {"status": RetailerStatus.ACTIVE})
    assert_freshly_created(created)
    assert created["id"] != "11111111-1111-4111-8111-111111111111", (
        "the refused body's id must not have been adopted"
    )

    validate_success(api.set_clock("2026-08-02T00:00:00Z"))
    suspended = validate_success(api.suspend_retailer(
        created["id"], f.suspend_payload("Under investigation"), ADMIN))
    assert_fields(suspended, {"status": RetailerStatus.SUSPENDED, "version": 2,
                              "id": created["id"],
                              "created_at": created["created_at"]})
    assert suspended["updated_at"] > suspended["created_at"], (
        "the mutation refreshes updated_at from the advanced clock while "
        "created_at stands still"
    )

    reread = validate_success(api.get_retailer(created["id"], ADMIN))
    assert_fields(reread, {"id": created["id"],
                           "created_at": created["created_at"],
                           "version": 2})


def test_10_every_declared_offer_bound_bites_at_its_own_edge(api, build):
    """An unknown family, a zero face value, 25 units, a zero ceiling, a lowercase code.

    "The body parses as JSON; every required field for that endpoint is present
    and non-null; no unknown field is present; every value matches its declared
    type; every enum value is in range; every integer is within its declared
    bounds; every date parses as an ISO 8601 value; and no computed or
    system-owned field is supplied by the caller."

    "Four further inputs are optional: `purchase_requirement_units`, the
    qualifying units a shopper must buy per cleared unit, at least 1 and at most
    24 and defaulting to 1; `redemption_grace_days`, the number of days after
    expiry during which a retailer may still open a lot against the offer, from 0
    to 365 and defaulting to 30; `digital_enabled`, defaulting to false; and
    `clip_validity_days`, from 1 to 365 and defaulting to 60."

    Design: Corner/entities/offer_enum_and_numeric_range_constraints_rejected
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    headers = make_manufacturer_headers(mfr["id"])

    bad_bodies = [
        f.offer_payload(mfr["id"], offer_code="SOUP50", max_redemptions=1000,
                        barcode_family="EAN13"),
        f.offer_payload(mfr["id"], offer_code="SOUP50", max_redemptions=1000,
                        face_value_cents=0),
        f.offer_payload(mfr["id"], offer_code="SOUP50", max_redemptions=1000,
                        purchase_requirement_units=25),
        f.offer_payload(mfr["id"], offer_code="SOUP50", max_redemptions=0),
        f.offer_payload(mfr["id"], offer_code="soup 50", max_redemptions=1000),
    ]
    for body in bad_bodies:
        validate_error(api.create_offer(body, headers), err.ERR_INVALID_REQUEST,
                       expected_status=400)

    rows, meta = validate_paginated(
        api.list_offers(headers, manufacturer_id=mfr["id"]))
    assert rows == [], "five refused creates left no offer row behind"
    assert_fields(meta, {"total_count": 0})


def test_11_the_postmark_interval_must_be_ordered_and_the_channel_in_range(
        api, build):
    """A zero-width window is refused as firmly as a reversed one.

    "Opening a submission requires the `retailer_id`, the `channel` (either
    `MAIL` or `ELECTRONIC`), the `declared_count` the retailer claims to have sent
    (from 0 to 1000000), and the two bounds of the postmark interval this shipment
    occupies: `postmark_window_start`, the inclusive lower bound, and
    `postmark_window_end`, the exclusive upper bound."

    "A freshly opened submission is `RECEIVED` on the intake dimension and
    `PENDING` on the settlement dimension, with `verified_count` 0,
    `count_variance_pct` `0.00`, a null `hold_reason` and every money field 0."

    Design: Corner/entities/submission_window_ordering_and_channel_enum_rejected
    """
    retailer = build.retailer(legal_name="Northgate Markets")

    bad_bodies = [
        f.submission_payload(retailer["id"], 10, "2026-07-01", "2026-07-31",
                             channel="FAX"),
        f.submission_payload(retailer["id"], 10, "2026-07-01", "2026-07-01"),
        f.submission_payload(retailer["id"], 10, "2026-07-31", "2026-07-01"),
        f.submission_payload(retailer["id"], -1, "2026-07-01", "2026-07-31"),
    ]
    for body in bad_bodies:
        validate_error(api.create_submission(body, CLERK),
                       err.ERR_INVALID_REQUEST, expected_status=400)

    accepted = validate_success(api.create_submission(f.submission_payload(
        retailer["id"], 10, "2026-07-01", "2026-07-31"), CLERK), 201)

    assert_fields(accepted, {
        "channel": Channel.MAIL,
        "declared_count": 10,
        "intake_status": IntakeStatus.RECEIVED,
        "settlement_status": SettlementStatus.PENDING,
        "verified_count": 0,
        "sorted_lot_count": 0,
    })
    assert_rate_equals(accepted["count_variance_pct"], "0.00",
                       "count_variance_pct")
    assert_nulls(accepted, ["hold_reason"])
    assert_money(accepted, "declared_face_value_cents", 0)
    assert_money(accepted, "settled_gross_face_value_cents", 0)
    assert_money(accepted, "settled_handling_fee_cents", 0)


@pytest.fixture
def single_coupon_chain(build):
    """One imaged coupon in a one-coupon lot, backed by one POS basket.

    The offer requires one qualifying unit per cleared unit, so the single basket
    under POS-1 is exactly enough to clear the coupon.
    """
    market = build.market(
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
    record = build.purchase_record(market["retailer_id"], market["offer_id"],
                                   "POS-1", "2026-07-05", 1)
    submission = build.verified_submission(market["retailer_id"], 1,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 1)
    items = build.capture(lot["id"], [
        f.item_payload(market["barcode"], "s3://img/1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-1", claimed_units=1)])
    return {"market": market, "record": record, "record_id": record["id"],
            "submission_id": submission["id"], "lot_id": lot["id"],
            "item_id": items[0]["id"], "retailer_id": market["retailer_id"]}


def test_12_a_matched_basket_is_named_by_the_coupon_and_never_consumed(
        api, single_coupon_chain):
    """The basket carries no version to bump, and adjudication leaves it untouched.

    "Both `updated_at` and `version` are absent from a `PurchaseDataRecord`
    payload."

    "Baskets are never consumed: one basket may back more than one coupon,
    because the clearinghouse only requires that a qualifying transaction
    existed."

    Design: Corner/entities/purchase_data_record_is_immutable_and_reusable
    """
    record_id = single_coupon_chain["record_id"]

    before = validate_success(api.get_purchase_record(record_id, ANALYST))
    assert_purchase_record_exact_keys(before)
    assert_immutable_identity(before)
    assert_fields(before, {"pos_transaction_ref": "POS-1",
                           "transaction_date": "2026-07-05",
                           "qualifying_units": 1})

    item = validate_success(
        api.adjudicate_item(single_coupon_chain["item_id"], ANALYST))
    assert_fields(item, {"status": ItemStatus.ACCEPTED,
                         "matched_purchase_record_id": record_id})
    assert_nulls(item, ["reject_code"])

    after = validate_success(api.get_purchase_record(record_id, ANALYST))
    assert after == before, (
        "the matcher references the basket without rewriting any part of it"
    )


def test_13_the_nested_lot_route_resolves_its_parent_before_the_body(api, build):
    """An unknown submission and an unknown offer together report the submission.

    "Path parameters are validated left to right: the `{id}` segment must resolve
    to an existing row of that collection before the body is examined, and an
    unresolvable segment yields the not-found code for that collection (§2.11)."

    "A new lot is created in status `SORTED` with `captured_item_count`,
    `accepted_qty`, `rejected_qty`, `projected_accepted_units`,
    `gross_face_value_cents` and `handling_fee_cents` all 0, a null
    `reject_reason`, and a null `adjudicated_by_user_id` and `adjudicated_at`."

    Design: Corner/entities/lot_creation_requires_existing_submission_path_then_offer_body
    """
    market = build.market(gs1_company_prefix="038000", offer_code="SOUP50",
                          face_value_cents=50, handling_fee_cents=7,
                          expiration_date="2026-12-31", max_redemptions=100000)
    submission = build.verified_submission(market["retailer_id"], 1,
                                           "2026-07-01", "2026-07-31")

    both_unknown = api.create_lot(
        UNKNOWN_UUID,
        f.lot_payload(UNKNOWN_UUID_ALT, market["manufacturer_id"], 1), CLERK)
    validate_error(both_unknown, err.ERR_SUBMISSION_NOT_FOUND,
                   expected_status=404)

    body_unknown = api.create_lot(
        submission["id"],
        f.lot_payload(UNKNOWN_UUID_ALT, market["manufacturer_id"], 1), CLERK)
    validate_error(body_unknown, err.ERR_OFFER_NOT_FOUND, expected_status=404)

    created = validate_success(api.create_lot(
        submission["id"],
        f.lot_payload(market["offer_id"], market["manufacturer_id"], 1),
        CLERK), 201)
    assert_fields(created, {
        "submission_id": submission["id"],
        "offer_id": market["offer_id"],
        "status": LotStatus.SORTED,
        "sample_size": 1,
        "valuation_variant": ValuationVariant.FULL_COUNT,
        "captured_item_count": 0,
        "accepted_qty": 0,
        "rejected_qty": 0,
        "projected_accepted_units": 0,
    })
    assert_nulls(created, ["reject_reason", "adjudicated_by_user_id",
                           "adjudicated_at"])

    rows, meta = validate_paginated(
        api.list_lots(CLERK, submission_id=submission["id"]))
    assert len(rows) == 1, "the two refused calls created nothing"
    assert_fields(meta, {"total_count": 1})


def test_14_the_from_state_guard_outranks_the_sample_size_guard_on_capture(
        api, build, single_coupon_chain):
    """A full, validated lot refuses a further image as a state error, not a size one.

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

    "The ordering reflects clearinghouse priorities — identity and authority
    first, then referential integrity, then the anti-fraud and regulatory-safety
    checks that protect manufacturers from paying for coupons they never
    authorised, then temporal and contractual windows, then ordinary constraint
    checks, and finally the fiscal checks, which are the cheapest to retry and
    therefore lose every conflict."

    Design: Corner/entities/coupon_item_capture_requires_lot_still_sorted
    """
    lot_id = single_coupon_chain["lot_id"]
    build.finalize(lot_id)

    refused = api.capture_items(lot_id, [
        f.item_payload(CANONICAL_DATABAR_PAYLOAD, "s3://img/2.jpg",
                       "2026-07-06", pos_transaction_ref="POS-1",
                       claimed_units=1)], CLERK)
    validate_error(refused, err.ERR_INVALID_STATE_TRANSITION,
                   expected_status=409)

    lot = validate_success(api.get_lot(lot_id, CLERK))
    assert_fields(lot, {"status": LotStatus.VALIDATED,
                        "captured_item_count": 1,
                        "accepted_qty": 1})
    assert_money(lot, "gross_face_value_cents", 50)
    assert_money(lot, "handling_fee_cents", 7)

    rows, meta = validate_paginated(api.list_items(CLERK, lot_id=lot_id))
    assert len(rows) == 1, "the refused batch created no coupon item"
    assert_fields(meta, {"total_count": 1})


def test_15_the_statement_copies_the_retailer_it_never_asked_for(
        api, build, single_coupon_chain):
    """retailer_id is not a body field, yet the statement is filterable by it.

    "The statement is created in `DRAFT` with `retailer_id` copied from the
    submission, `issued_by_user_id` set to the acting `X-User-ID` — the second
    segregation-of-duties wall — a null `manufacturer_invoice_id`, a null
    `scheduled_pay_date` and a null `hold_reason`."

    "Settlement statements may be filtered by `submission_id`, `retailer_id`,
    `manufacturer_invoice_id` and `status`."

    Design: Corner/entities/settlement_statement_retailer_id_copied_from_submission_and_filterable
    """
    submission_id = single_coupon_chain["submission_id"]
    retailer_id = single_coupon_chain["retailer_id"]
    build.finalize(single_coupon_chain["lot_id"])

    closed = validate_success(api.get_submission(submission_id, OFFICER))
    assert_fields(closed, {"intake_status": IntakeStatus.CLOSED,
                           "settlement_status": SettlementStatus.PENDING})

    statement = validate_success(api.issue_statement(
        submission_id, closed["version"], OFFICER), 201)

    assert_fields(statement, {"retailer_id": retailer_id,
                              "submission_id": submission_id,
                              "status": StatementStatus.DRAFT,
                              "issued_by_user_id": SETTLEMENT_OFFICER_ID})
    assert_money(statement, "gross_face_value_cents", 50)
    assert_money(statement, "handling_fee_total_cents", 7)
    assert_money(statement, "prior_chargeback_offset_cents", 0)
    assert_money(statement, "provisional_net_cents", 57)
    assert_holdback_pct(statement["holdback_pct"], "0.0000")
    assert_money(statement, "misredemption_holdback_cents", 0)
    assert_money(statement, "net_payable_cents", 57)
    assert_nulls(statement, ["manufacturer_invoice_id", "scheduled_pay_date",
                             "hold_reason", "released_by_user_id"])

    by_retailer, retailer_meta = validate_paginated(
        api.list_statements(OFFICER, retailer_id=retailer_id))
    assert_fields(retailer_meta, {"total_count": 1})
    assert by_retailer[0]["id"] == statement["id"], (
        "the statement is reachable through the retailer foreign key"
    )

    by_submission, submission_meta = validate_paginated(
        api.list_statements(OFFICER, submission_id=submission_id))
    assert_fields(submission_meta, {"total_count": 1})
    assert by_submission[0]["id"] == statement["id"], (
        "and through the submission foreign key it was issued against"
    )


def test_16_the_match_writes_both_halves_of_the_clip_and_event_pair(api, build):
    """Each side names the other, and each side is reachable from the other.

    "When the matcher returns a winner the event is created `MATCHED` with
    `matched_clip_id` set to the winner, that clip moves `CLIPPED` → `MATCHED`
    with its `matched_event_id` pointing back at the new event, and the offer's
    `accepted_redemption_count` increases by 1 — one unit per digital redemption,
    unlike the multi-unit lot clearances of §3.5."

    "Both records are read-only once written: clips and events can be listed and
    fetched, filtered by their offer, their consumer, their status and their
    counterpart identifier — the reverse-reachability channel that lets a
    `FraudAnalyst` walk from a suspect event back to the clip it consumed — but
    neither is ever updated or deleted."

    Design: Corner/entities/digital_clip_and_redemption_event_cross_references_agree
    """
    market = build.market(gs1_company_prefix="038000", offer_code="SOUP50D",
                          face_value_cents=50, handling_fee_cents=7,
                          expiration_date="2026-12-31", max_redemptions=100000,
                          digital_enabled=True,
                          redemption_instructions="Clip and save 50c")
    clip = build.clip(market["offer_id"], "consumer-771")
    assert_fields(clip, {"clipped_at": "2026-08-01",
                         "clip_expires_at": "2026-09-30",
                         "status": ClipStatus.CLIPPED})

    event = validate_success(api.create_redemption_event(
        market["offer_id"], market["retailer_id"], "consumer-771",
        market["ret_headers"]), 201)
    assert_fields(event, {"status": RedemptionEventStatus.MATCHED,
                          "matched_clip_id": clip["id"],
                          "redeemed_at": "2026-08-01"})
    assert_money(event, "face_value_cents", 50)
    assert_nulls(event, ["reject_code"])

    consumed = validate_success(api.get_clip(clip["id"], ANALYST))
    assert_fields(consumed, {"status": ClipStatus.MATCHED,
                             "matched_event_id": event["id"],
                             "clip_expires_at": "2026-09-30"})

    offer = validate_success(api.get_offer(market["offer_id"], ANALYST))
    assert_fields(offer, {"accepted_redemption_count": 1})

    clips, clip_meta = validate_paginated(
        api.list_clips(ANALYST, matched_event_id=event["id"]))
    assert_fields(clip_meta, {"total_count": 1})
    assert clips[0]["id"] == clip["id"], (
        "the event's identifier finds exactly the clip it consumed"
    )

    events, event_meta = validate_paginated(
        api.list_redemption_events(ANALYST, matched_clip_id=clip["id"]))
    assert_fields(event_meta, {"total_count": 1})
    assert events[0]["id"] == event["id"], (
        "and the clip's identifier finds exactly the event that consumed it"
    )
