"""Two valuation variants on a lot, and two fraud-score variants on a retailer.

Both pairs run over identical stored rows and disagree — the lot pair about the
inclusion basis, the retailer pair about time weighting.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ANALYST,
    ItemStatus,
    RejectCode,
    RetailerStatus,
    ValuationVariant,
    assert_fields,
    assert_lot_valuation,
    assert_money,
    assert_rate_equals,
    assert_valuation_shape,
    databar_payload,
    factories as f,
)

SOUP50_BARCODE = databar_payload("038000", 50, 2, "2026-12-31", 30)
THRIFT100_BARCODE = databar_payload("072250", 100, 1, "2027-12-31", 30)


@pytest.fixture
def two_lot_shipment(build):
    """A 63-coupon shipment split into a sampled lot of 60 and a full lot of 3.

    Five baskets back POS-A1 through POS-A5 at two qualifying units each; the
    sixth coupon quotes POS-A6, for which no basket was ever ingested.
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods",
                             handling_fee_policy="CONTRACT_RATE",
                             dispute_window_days=45)
    ret = build.retailer(legal_name="Northgate Markets", channel_capability="BOTH",
                         payment_terms="NET_30", base_fee_tier="PREFERRED",
                         fraud_scoring_mode="ROLLING_WINDOW")
    offer = build.active_offer(
        mfr["id"], offer_code="SOUP50", face_value_cents=50,
        handling_fee_cents=7, expiration_date="2026-12-31",
        redemption_instructions="Save 50c on two cans",
        max_redemptions=100000, purchase_requirement_units=2,
        redemption_grace_days=30, digital_enabled=False, clip_validity_days=14)
    for index in range(1, 6):
        build.purchase_record(ret["id"], offer["id"], f"POS-A{index}",
                              "2026-07-05", 2)
    submission = build.verified_submission(ret["id"], 63, "2026-07-01",
                                           "2026-07-31")
    lot_a = build.lot(submission["id"], offer["id"], mfr["id"], 60)
    lot_b = build.lot(submission["id"], offer["id"], mfr["id"], 3)
    items = build.capture(lot_a["id"], [
        f.item_payload(SOUP50_BARCODE, f"s3://img/a{index}.jpg", "2026-07-05",
                       pos_transaction_ref=f"POS-A{index}", claimed_units=1)
        for index in range(1, 7)
    ])
    return {
        "manufacturer": mfr, "retailer": ret, "offer": offer,
        "submission_id": submission["id"], "lot_a": lot_a, "lot_b": lot_b,
        "items": items,
    }


def test_01_sampled_lot_projects_the_whole_bucket_from_a_four_decimal_rate(
        api, build, two_lot_shipment):
    """The 60-coupon bucket extrapolates its six imaged coupons to 50 units.

    "Worked through: a bucket of 60 coupons with a `sample_size` of 6, five
    cleared coupons each claiming one unit and one coupon rejected as
    misredeemed, against an offer whose face value is 50 cents, gives a rate of
    0.8333, `projected_accepted_units` of 50, and `gross_face_value_cents` of
    2500 — where the same stored rows run through full-count would give 5
    projected units and 250 cents."

    "Lot A's 50 units price at 402.5, which rounds to 403; lot B's 13 units
    price at 104.65, which rounds to 105; and `settled_handling_fee_cents` is
    508."

    Design: Difficulty/dual_variant_calc/lot_valuation_full_count_vs_sampled_extrapolation
    """
    lot_a = two_lot_shipment["lot_a"]
    assert_fields(lot_a, {
        "valuation_variant": ValuationVariant.SAMPLED_EXTRAPOLATION,
        "sample_size": 6,
    })

    finalized = validate_success(api.finalize_lot(lot_a["id"], ANALYST))

    assert_lot_valuation(finalized, status="VALIDATED", accepted_qty=5,
                         rejected_qty=1, projected_accepted_units=50,
                         gross_face_value_cents=2500, handling_fee_cents=403)


def test_02_the_unbacked_coupon_is_the_only_rejection_in_the_sample(
        api, build, two_lot_shipment):
    """The sixth coupon quotes a register reference no basket ever carried.

    "If that pool is empty — which includes the case where the coupon's
    `pos_transaction_ref` is null, since a null reference joins no basket at all
    and therefore earns no free pass — the coupon becomes `REJECTED_MISREDEEMED`
    with `reject_code` `NO_PURCHASE_MATCH` and `matched_purchase_record_id` left
    null."

    Design: Difficulty/dual_variant_calc/lot_valuation_full_count_vs_sampled_extrapolation
    """
    lot_a = two_lot_shipment["lot_a"]
    items = two_lot_shipment["items"]

    validate_success(api.finalize_lot(lot_a["id"], ANALYST))

    first = validate_success(api.get_item(items[0]["id"], ANALYST))
    assert_fields(first, {"status": ItemStatus.ACCEPTED, "reject_code": None})

    sixth = validate_success(api.get_item(items[5]["id"], ANALYST))
    assert_fields(sixth, {
        "status": ItemStatus.REJECTED_MISREDEEMED,
        "reject_code": RejectCode.NO_PURCHASE_MATCH,
        "matched_purchase_record_id": None,
    })


def test_03_valuation_read_reports_both_variants_2250_cents_apart(
        api, build, two_lot_shipment):
    """One computed read prices the same adjudicated rows 250 against 2500.

    "Worked through: a bucket of 60 coupons with a `sample_size` of 6, five
    cleared coupons each claiming one unit and one coupon rejected as
    misredeemed, against an offer whose face value is 50 cents, gives a rate of
    0.8333, `projected_accepted_units` of 50, and `gross_face_value_cents` of
    2500 — where the same stored rows run through full-count would give 5
    projected units and 250 cents."

    Design: Difficulty/dual_variant_calc/lot_valuation_full_count_vs_sampled_extrapolation
    """
    submission_id = two_lot_shipment["submission_id"]
    validate_success(api.finalize_lot(two_lot_shipment["lot_a"]["id"], ANALYST))

    valuation = validate_success(api.get_valuation(submission_id, ANALYST))

    assert_valuation_shape(valuation)
    assert_money(valuation, "full_count_gross_face_value_cents", 250)
    assert_money(valuation, "sampled_gross_face_value_cents", 2500)
    delta = (valuation["sampled_gross_face_value_cents"]
             - valuation["full_count_gross_face_value_cents"])
    assert delta == 2250, (
        f"the two variants must differ by exactly 2250 cents, got {delta}"
    )


@pytest.fixture
def two_era_retailer(build):
    """A retailer with one duplicate in 2026 and four clean coupons in 2027.

    The 2026 pair is 243 days behind the advanced clock, so it falls outside the
    90-day rolling window but inside the first lifetime decay bucket.
    """
    mfr = build.manufacturer(gs1_company_prefix="072250",
                             legal_name="Thrift Brands",
                             handling_fee_policy="CONTRACT_RATE",
                             dispute_window_days=45)
    ret = build.retailer(legal_name="Valley Grocers", channel_capability="BOTH",
                         payment_terms="NET_15", base_fee_tier="STANDARD",
                         fraud_scoring_mode="ROLLING_WINDOW")
    offer = build.active_offer(
        mfr["id"], offer_code="THRIFT100", face_value_cents=100,
        handling_fee_cents=8, expiration_date="2027-12-31",
        redemption_instructions="Save $1 on one", max_redemptions=100000,
        purchase_requirement_units=1, redemption_grace_days=30,
        digital_enabled=False, clip_validity_days=14)

    for ref in ("POS-B1", "POS-B2"):
        build.purchase_record(ret["id"], offer["id"], ref, "2026-07-10", 1)
    first = build.verified_submission(ret["id"], 2, "2026-07-01", "2026-07-15")
    lot_one = build.lot(first["id"], offer["id"], mfr["id"], 2)
    early_items = build.capture(lot_one["id"], [
        f.item_payload(THRIFT100_BARCODE, "s3://img/b1.jpg", "2026-07-10",
                       serial_number="SN-1", pos_transaction_ref="POS-B1",
                       claimed_units=1),
        f.item_payload(THRIFT100_BARCODE, "s3://img/b2.jpg", "2026-07-10",
                       serial_number="SN-1", pos_transaction_ref="POS-B2",
                       claimed_units=1),
    ])
    build.finalize(lot_one["id"])

    build.set_clock("2027-04-01T00:00:00Z")

    for ref in ("POS-B3", "POS-B4", "POS-B5", "POS-B6"):
        build.purchase_record(ret["id"], offer["id"], ref, "2027-03-20", 1)
    second = build.verified_submission(ret["id"], 4, "2027-03-01", "2027-03-31")
    lot_two = build.lot(second["id"], offer["id"], mfr["id"], 4)
    build.capture(lot_two["id"], [
        f.item_payload(THRIFT100_BARCODE, f"s3://img/b{index}.jpg", "2027-03-20",
                       serial_number=f"SN-{index - 1}",
                       pos_transaction_ref=f"POS-B{index}", claimed_units=1)
        for index in range(3, 7)
    ])
    build.finalize(lot_two["id"])

    return {"retailer_id": ret["id"], "early_items": early_items}


def test_04_rolling_window_scores_zero_while_lifetime_weighted_scores_fourteen(
        api, build, two_era_retailer):
    """One rescore stores both variants, 14 points apart on the same rows.

    "Rolling window sees only the four recent items, finds a `duplicate_rate` of
    `0.00` and scores `0.00`."

    "Lifetime weighted sees a weighted duplicate mass of 0.5 against a weighted
    pool of 5.0, giving a `duplicate_rate` of `10.00`, a weighted total of 14.00
    and therefore a score of `14.00`."

    Design: Difficulty/dual_variant_calc/retailer_fraud_score_rolling_window_vs_lifetime_weighted
    """
    retailer_id = two_era_retailer["retailer_id"]
    current = validate_success(api.get_retailer(retailer_id, ANALYST))

    rescored = validate_success(
        api.fraud_rescore(retailer_id, current["version"], ANALYST))

    assert_rate_equals(rescored["fraud_score_rolling_window"], "0.00",
                       "fraud_score_rolling_window")
    assert_rate_equals(rescored["fraud_score_lifetime_weighted"], "14.00",
                       "fraud_score_lifetime_weighted")


def test_05_the_scoring_mode_decides_which_variant_drives_status_and_tier(
        api, build, two_era_retailer):
    """A ROLLING_WINDOW retailer banks the clean recent quarter.

    "The same stored rows, 14 points apart, and only the retailer's
    `fraud_scoring_mode` decides which number lands in `fraud_score` — and
    therefore which number drives status and tier."

    "The three component rates stored on the retailer are the components of
    whichever variant `fraud_scoring_mode` selects, so `misredemption_rate` —
    which later feeds the settlement holdback — is consistent with the
    authoritative score."

    Design: Difficulty/dual_variant_calc/retailer_fraud_score_rolling_window_vs_lifetime_weighted
    """
    retailer_id = two_era_retailer["retailer_id"]
    current = validate_success(api.get_retailer(retailer_id, ANALYST))

    rescored = validate_success(
        api.fraud_rescore(retailer_id, current["version"], ANALYST))

    assert_rate_equals(rescored["fraud_score"], "0.00", "fraud_score")
    assert_rate_equals(rescored["duplicate_rate"], "0.00", "duplicate_rate")
    assert_fields(rescored, {
        "status": RetailerStatus.ACTIVE,
        "handling_fee_tier": "STANDARD",
        "last_rescored_at": "2027-04-01T00:00:00.000Z",
    })


def test_06_the_second_coupon_on_a_shared_serial_is_the_duplicate(
        api, build, two_era_retailer):
    """Of two coupons on serial SN-1, the later-adjudicated one is rejected.

    "Otherwise the system looks for an earlier cleared instance of the same
    serial, and if it finds one the coupon becomes `REJECTED_DUPLICATE` with
    `reject_code` `DUPLICATE_SERIAL` and `duplicate_of_item_id` pointing at the
    instance that owns the serial."

    Design: Difficulty/dual_variant_calc/retailer_fraud_score_rolling_window_vs_lifetime_weighted
    """
    first_id = two_era_retailer["early_items"][0]["id"]
    second_id = two_era_retailer["early_items"][1]["id"]

    first = validate_success(api.get_item(first_id, ANALYST))
    second = validate_success(api.get_item(second_id, ANALYST))

    assert_fields(first, {"status": ItemStatus.ACCEPTED})
    assert_fields(second, {
        "status": ItemStatus.REJECTED_DUPLICATE,
        "reject_code": RejectCode.DUPLICATE_SERIAL,
        "duplicate_of_item_id": first_id,
    })
