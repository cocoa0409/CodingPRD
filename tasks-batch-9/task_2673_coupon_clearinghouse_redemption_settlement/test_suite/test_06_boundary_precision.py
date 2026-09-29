"""Boundaries probed one step below, exactly on, and one step above.

The grace window, the watchlist threshold and the sampling threshold are each
inclusive, and each is worth a different amount of money on either side.
"""

from decimal import Decimal

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ANALYST,
    CLERK,
    IntakeStatus,
    ItemStatus,
    LotStatus,
    OfferStatus,
    RejectCode,
    RetailerStatus,
    ValuationVariant,
    api_errors as err,
    assert_fields,
    assert_money,
    assert_rate_equals,
    assert_sweep_counters,
    databar_payload,
    factories as f,
)

SOUP50_BARCODE = databar_payload("038000", 50, 2, "2026-12-31", 30)

GRACE_TERMS = {
    "face_value_cents": 50,
    "handling_fee_cents": 7,
    "expiration_date": "2026-08-10",
    "redemption_instructions": "Save 50c on two cans",
    "max_redemptions": 100000,
    "purchase_requirement_units": 2,
    "redemption_grace_days": 5,
    "digital_enabled": False,
    "clip_validity_days": 14,
}


@pytest.fixture
def grace_window(build):
    """An offer expiring 2026-08-10 with five grace days and a six-coupon shipment.

    The offer is activated while the clock still stands at 2026-08-01, so the
    activation itself is never the thing under test.
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods",
                             handling_fee_policy="CONTRACT_RATE",
                             dispute_window_days=45)
    ret = build.retailer(legal_name="Northgate Markets",
                         channel_capability="BOTH", payment_terms="NET_30",
                         base_fee_tier="STANDARD",
                         fraud_scoring_mode="ROLLING_WINDOW")
    offer = build.active_offer(mfr["id"], offer_code="SOUP50", **GRACE_TERMS)
    submission = build.verified_submission(ret["id"], 6, "2026-07-01",
                                           "2026-07-31")
    return {"manufacturer_id": mfr["id"], "retailer_id": ret["id"],
            "offer_id": offer["id"], "submission_id": submission["id"]}


def test_01_the_day_before_the_last_grace_day_still_sorts(api, grace_window):
    """2026-08-14 is inside a window that closes on 2026-08-15.

    "Every `Offer` whose status is `ACTIVE` and whose `expiration_date` is
    strictly earlier than the new clock's calendar date moves from `ACTIVE` to
    `EXPIRED`, processed in `created_at` ascending order."

    "On lot creation, the offer's status must be `ACTIVE` or `EXPIRED` — a
    `DRAFT`, `REGISTERED` or `WITHDRAWN` offer is not clearable — otherwise
    `ERR_OFFER_NOT_CLEARABLE` (422); because this sits above the grace-window
    check at level 20, a lot sorted against a withdrawn offer past its grace
    period reports the offer problem, not the date problem."

    Design: Difficulty/boundary_precision_check/lot_sort_on_final_grace_day_inclusive
    """
    sweep = validate_success(api.set_clock("2026-08-14T00:00:00Z"))
    assert_sweep_counters(sweep, "2026-08-14T00:00:00Z", expired_offer_count=1,
                          expired_clip_count=0, withdrawn_dispute_count=0)

    offer = validate_success(api.get_offer(grace_window["offer_id"], ANALYST))
    assert_fields(offer, {"status": OfferStatus.EXPIRED})

    lot = validate_success(api.create_lot(
        grace_window["submission_id"],
        f.lot_payload(grace_window["offer_id"],
                      grace_window["manufacturer_id"], 2), CLERK), 201)
    assert_fields(lot, {"status": LotStatus.SORTED, "counted_qty": 2})


def test_02_the_last_grace_day_itself_is_inside_the_window(api, grace_window):
    """Exactly expiration_date plus five days is accepted, not refused.

    "That last comparison is inclusive on the final grace day: a lot sorted
    exactly on the last grace day is accepted and one day later is refused with
    `ERR_SUBMISSION_PAST_GRACE`."

    Design: Difficulty/boundary_precision_check/lot_sort_on_final_grace_day_inclusive
    """
    sweep = validate_success(api.set_clock("2026-08-15T00:00:00Z"))
    assert_sweep_counters(sweep, "2026-08-15T00:00:00Z", expired_offer_count=1,
                          expired_clip_count=0, withdrawn_dispute_count=0)

    lot = validate_success(api.create_lot(
        grace_window["submission_id"],
        f.lot_payload(grace_window["offer_id"],
                      grace_window["manufacturer_id"], 2), CLERK), 201)
    assert_fields(lot, {"status": LotStatus.SORTED})

    submission = validate_success(
        api.get_submission(grace_window["submission_id"], CLERK))
    assert_fields(submission, {"sorted_lot_count": 1,
                               "intake_status": IntakeStatus.COUNT_VERIFIED})
    assert_money(submission, "declared_face_value_cents", 100)


def test_03_one_day_past_the_grace_window_is_refused(api, grace_window):
    """2026-08-16 leaves the shipment exactly as the sweep found it.

    "The submission must be `COUNT_VERIFIED`; the retailer must not be
    `SUSPENDED`; the offer's issuer must not be `SUSPENDED`; the supplied
    `manufacturer_id` must be exactly the offer's own issuer, or the bucket is
    refused with `ERR_OFFER_MANUFACTURER_MISMATCH`; the offer must be `ACTIVE` or
    `EXPIRED`, or the bucket is refused with `ERR_OFFER_NOT_CLEARABLE`; and the
    offer must still be inside its redemption window, meaning the clock's calendar
    date is on or before the offer's `expiration_date` plus its
    `redemption_grace_days`."

    Design: Difficulty/boundary_precision_check/lot_sort_on_final_grace_day_inclusive
    """
    validate_success(api.set_clock("2026-08-16T00:00:00Z"))

    refused = api.create_lot(
        grace_window["submission_id"],
        f.lot_payload(grace_window["offer_id"],
                      grace_window["manufacturer_id"], 2), CLERK)
    validate_error(refused, err.ERR_SUBMISSION_PAST_GRACE)

    submission = validate_success(
        api.get_submission(grace_window["submission_id"], CLERK))
    assert_fields(submission, {"sorted_lot_count": 0,
                               "intake_status": IntakeStatus.COUNT_VERIFIED})
    assert_money(submission, "declared_face_value_cents", 0)


def test_04_two_grace_days_running_admit_four_of_the_six_coupons(
        api, grace_window):
    """Sorting on 2026-08-14 and again on 2026-08-15 leaves intake open at four.

    "And at the end of every lot creation the system tests one thing: once the
    running sum of `counted_qty` over the submission's lots exactly equals the
    submission's `verified_count`, the submission advances `COUNT_VERIFIED` →
    `SORTED`, which closes it to any further lots."

    Design: Difficulty/boundary_precision_check/lot_sort_on_final_grace_day_inclusive
    """
    submission_id = grace_window["submission_id"]
    payload = f.lot_payload(grace_window["offer_id"],
                            grace_window["manufacturer_id"], 2)

    validate_success(api.set_clock("2026-08-14T00:00:00Z"))
    validate_success(api.create_lot(submission_id, payload, CLERK), 201)
    validate_success(api.set_clock("2026-08-15T00:00:00Z"))
    validate_success(api.create_lot(submission_id, payload, CLERK), 201)

    submission = validate_success(api.get_submission(submission_id, CLERK))
    assert_fields(submission, {"sorted_lot_count": 2,
                               "intake_status": IntakeStatus.COUNT_VERIFIED})
    assert_money(submission, "declared_face_value_cents", 200)


@pytest.fixture
def two_duplicate_pools(build):
    """Two retailers, one duplicate each, over pools of two and three coupons.

    The first retailer's pool of two lands the score exactly on the watchlist
    boundary; the second's pool of three lands one cent of rate below it.
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods",
                             handling_fee_policy="CONTRACT_RATE",
                             dispute_window_days=45)
    offer = build.active_offer(
        mfr["id"], offer_code="SOUP50", face_value_cents=50,
        handling_fee_cents=7, expiration_date="2026-12-31",
        redemption_instructions="Save 50c on two cans", max_redemptions=100000,
        purchase_requirement_units=2, redemption_grace_days=30,
        digital_enabled=False, clip_validity_days=14)
    first = build.retailer(legal_name="Northgate Markets",
                           channel_capability="BOTH", payment_terms="NET_30",
                           base_fee_tier="STANDARD",
                           fraud_scoring_mode="ROLLING_WINDOW")
    second = build.retailer(legal_name="Bayfront Grocers",
                            channel_capability="BOTH", payment_terms="NET_30",
                            base_fee_tier="STANDARD",
                            fraud_scoring_mode="ROLLING_WINDOW")

    build.purchase_record(first["id"], offer["id"], "POS-J1", "2026-07-05", 2)
    for ref in ("POS-K1", "POS-K2"):
        build.purchase_record(second["id"], offer["id"], ref, "2026-07-05", 2)

    submission_one = build.verified_submission(first["id"], 2, "2026-07-01",
                                               "2026-07-31")
    lot_one = build.lot(submission_one["id"], offer["id"], mfr["id"], 2)
    items_one = build.capture(lot_one["id"], [
        f.item_payload(SOUP50_BARCODE, "s3://img/j1.jpg", "2026-07-05",
                       serial_number="SN-A1", pos_transaction_ref="POS-J1",
                       claimed_units=1),
        f.item_payload(SOUP50_BARCODE, "s3://img/j2.jpg", "2026-07-05",
                       serial_number="SN-A1", pos_transaction_ref="POS-J1",
                       claimed_units=1),
    ])

    submission_two = build.verified_submission(second["id"], 3, "2026-07-01",
                                               "2026-07-31")
    lot_two = build.lot(submission_two["id"], offer["id"], mfr["id"], 3)
    items_two = build.capture(lot_two["id"], [
        f.item_payload(SOUP50_BARCODE, "s3://img/k1.jpg", "2026-07-05",
                       serial_number="SN-B1", pos_transaction_ref="POS-K1",
                       claimed_units=1),
        f.item_payload(SOUP50_BARCODE, "s3://img/k2.jpg", "2026-07-05",
                       serial_number="SN-B2", pos_transaction_ref="POS-K2",
                       claimed_units=1),
        f.item_payload(SOUP50_BARCODE, "s3://img/k3.jpg", "2026-07-05",
                       serial_number="SN-B2", pos_transaction_ref="POS-K2",
                       claimed_units=1),
    ])

    build.finalize(lot_one["id"])
    build.finalize(lot_two["id"])
    return {"first_id": first["id"], "second_id": second["id"],
            "items_one": items_one, "items_two": items_two}


def test_05_a_pool_of_two_with_one_duplicate_lands_on_the_watchlist_boundary(
        api, build, two_duplicate_pools):
    """Exactly 70.00 is inside the watchlist band, because the test is at least.

    "The weights do not sum to one and the clamp is the only ceiling, which is
    what makes the thresholds reachable — a `duplicate_rate` of 50.00 on its own
    yields exactly 70.00, precisely the watchlist boundary."

    "Separately and on the same boundary, the effective `handling_fee_tier`
    becomes `PROBATION` at `70.00` or above and reverts to the retailer's
    `base_fee_tier` below it — so the tier always returns to the contracted base
    and never to a remembered `PROBATION`."

    Design: Difficulty/boundary_precision_check/fraud_rate_rounds_before_weighting_at_watchlist_threshold
    """
    items = two_duplicate_pools["items_one"]
    accepted = validate_success(api.get_item(items[0]["id"], ANALYST))
    assert_fields(accepted, {"status": ItemStatus.ACCEPTED})
    duplicate = validate_success(api.get_item(items[1]["id"], ANALYST))
    assert_fields(duplicate, {
        "status": ItemStatus.REJECTED_DUPLICATE,
        "reject_code": RejectCode.DUPLICATE_SERIAL,
        "duplicate_of_item_id": items[0]["id"],
    })

    retailer = build.rescore(two_duplicate_pools["first_id"])

    assert_rate_equals(retailer["duplicate_rate"], "50.00", "duplicate_rate")
    assert_rate_equals(retailer["misredemption_rate"], "0.00",
                       "misredemption_rate")
    assert_rate_equals(retailer["counterfeit_rate"], "0.00", "counterfeit_rate")
    assert_rate_equals(retailer["fraud_score"], "70.00", "fraud_score")
    assert_fields(retailer, {"status": RetailerStatus.WATCHLIST,
                             "handling_fee_tier": "PROBATION",
                             "last_rescored_at": "2026-08-01T00:00:00.000Z"})


def test_06_the_component_rate_is_rounded_before_it_is_weighted(
        api, build, two_duplicate_pools):
    """One duplicate in three gives 46.66, one cent under the other order.

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

    Design: Difficulty/boundary_precision_check/fraud_rate_rounds_before_weighting_at_watchlist_threshold
    """
    items = two_duplicate_pools["items_two"]
    duplicate = validate_success(api.get_item(items[2]["id"], ANALYST))
    assert_fields(duplicate, {
        "status": ItemStatus.REJECTED_DUPLICATE,
        "duplicate_of_item_id": items[1]["id"],
    })

    retailer = build.rescore(two_duplicate_pools["second_id"])

    assert_rate_equals(retailer["duplicate_rate"], "33.33", "duplicate_rate")
    assert_rate_equals(retailer["fraud_score"], "46.66", "fraud_score")
    assert Decimal(str(retailer["fraud_score"])) != Decimal("46.67"), (
        "46.67 is what weighting the unrounded 33.3333 would give; the rate is "
        "rounded to two decimals before the 1.40 multiplier is applied"
    )
    assert_fields(retailer, {"status": RetailerStatus.ACTIVE,
                             "handling_fee_tier": "STANDARD"})


def test_07_both_variants_agree_while_every_coupon_is_fresh(
        api, build, two_duplicate_pools):
    """Same-day evidence sits in the window and in bucket zero, so the two match.

    "The `ROLLING_WINDOW` variant applies a hard cut-off: only items whose
    `adjudicated_at` falls on or after the logical clock minus 90 days enter the
    pool, each with weight one, and anything older is invisible — a retailer with
    a terrible history and a clean last 90 days scores `0.00`."

    "Decay is a step, never an interpolation: an item 179 days old carries weight
    1.0 and an item 180 days old carries weight 0.5."

    Design: Difficulty/boundary_precision_check/fraud_rate_rounds_before_weighting_at_watchlist_threshold
    """
    first = build.rescore(two_duplicate_pools["first_id"])
    second = build.rescore(two_duplicate_pools["second_id"])

    for retailer in (first, second):
        assert_rate_equals(retailer["fraud_score_rolling_window"],
                           str(retailer["fraud_score_lifetime_weighted"]),
                           "fraud_score_rolling_window")
    assert_rate_equals(first["fraud_score_lifetime_weighted"], "70.00",
                       "fraud_score_lifetime_weighted")
    assert_rate_equals(second["fraud_score_lifetime_weighted"], "46.66",
                       "fraud_score_lifetime_weighted")


@pytest.fixture
def three_bucket_sizes(build):
    """A 120-coupon shipment waiting for buckets of 39, 40 and 41 coupons.

    The three counts add to the verified count exactly, so the third bucket also
    closes intake.
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods",
                             handling_fee_policy="CONTRACT_RATE",
                             dispute_window_days=45)
    ret = build.retailer(legal_name="Northgate Markets",
                         channel_capability="BOTH", payment_terms="NET_30",
                         base_fee_tier="STANDARD",
                         fraud_scoring_mode="ROLLING_WINDOW")
    offer = build.active_offer(
        mfr["id"], offer_code="SOUP50", face_value_cents=50,
        handling_fee_cents=7, expiration_date="2026-12-31",
        redemption_instructions="Save 50c on two cans", max_redemptions=100000,
        purchase_requirement_units=2, redemption_grace_days=30,
        digital_enabled=False, clip_validity_days=14)
    submission = build.verified_submission(ret["id"], 120, "2026-07-01",
                                           "2026-07-31")
    return {"manufacturer_id": mfr["id"], "offer_id": offer["id"],
            "retailer_id": ret["id"], "submission_id": submission["id"]}


def test_08_a_bucket_of_forty_still_demands_every_coupon_imaged(
        api, three_bucket_sizes):
    """39 and 40 both keep the full-count variant with sample_size unreduced.

    "When the `counted_qty` is at most 40, the whole bucket is imaged:
    `sample_size` equals `counted_qty` and `valuation_variant` is `FULL_COUNT`."

    Design: Difficulty/boundary_precision_check/sample_threshold_forty_inclusive_vs_fortyone
    """
    submission_id = three_bucket_sizes["submission_id"]

    below = validate_success(api.create_lot(
        submission_id,
        f.lot_payload(three_bucket_sizes["offer_id"],
                      three_bucket_sizes["manufacturer_id"], 39), CLERK), 201)
    assert_fields(below, {"sample_size": 39,
                          "valuation_variant": ValuationVariant.FULL_COUNT})

    boundary = validate_success(api.create_lot(
        submission_id,
        f.lot_payload(three_bucket_sizes["offer_id"],
                      three_bucket_sizes["manufacturer_id"], 40), CLERK), 201)
    assert_fields(boundary, {"sample_size": 40,
                             "valuation_variant": ValuationVariant.FULL_COUNT})
    assert boundary["sample_size"] != 4, (
        "4 is the sample a strict comparison would hand a bucket of 40"
    )


def test_09_one_coupon_more_flips_the_bucket_to_five_images(
        api, three_bucket_sizes):
    """41 coupons demand 5 images, the ceiling of 4.1, not 41 and not 4.

    "The threshold is inclusive on the full-count side, and the step at the
    boundary is dramatic: a bucket of 40 coupons stays `FULL_COUNT` and demands 40
    images, while a bucket of 41 coupons flips to `SAMPLED_EXTRAPOLATION` and
    demands only 5 (the ceiling of 4.1)."

    Design: Difficulty/boundary_precision_check/sample_threshold_forty_inclusive_vs_fortyone
    """
    above = validate_success(api.create_lot(
        three_bucket_sizes["submission_id"],
        f.lot_payload(three_bucket_sizes["offer_id"],
                      three_bucket_sizes["manufacturer_id"], 41), CLERK), 201)

    assert_fields(above, {
        "sample_size": 5,
        "valuation_variant": ValuationVariant.SAMPLED_EXTRAPOLATION,
        "counted_qty": 41,
        "captured_item_count": 0,
    })


def test_10_the_three_buckets_close_intake_on_the_verified_count(
        api, three_bucket_sizes):
    """39 plus 40 plus 41 is 120, so the last bucket carries the shipment to SORTED.

    "Creating the lot also increments the submission's `sorted_lot_count` and
    recomputes its `declared_face_value_cents`, which is the sum over the
    submission's lots of each lot's `counted_qty` multiplied by that lot's offer
    face value — the notional value of the shipment before anyone has adjudicated
    anything."

    Design: Difficulty/boundary_precision_check/sample_threshold_forty_inclusive_vs_fortyone
    """
    submission_id = three_bucket_sizes["submission_id"]
    for counted in (39, 40, 41):
        validate_success(api.create_lot(
            submission_id,
            f.lot_payload(three_bucket_sizes["offer_id"],
                          three_bucket_sizes["manufacturer_id"], counted),
            CLERK), 201)

    submission = validate_success(api.get_submission(submission_id, CLERK))
    assert_fields(submission, {"sorted_lot_count": 3,
                               "intake_status": IntakeStatus.SORTED})
    assert_money(submission, "declared_face_value_cents", 6000)
    assert_rate_equals(submission["count_variance_pct"], "0.00",
                       "count_variance_pct")
