"""Digit concatenation, recount tolerance, clip ceilings and basket ranking.

Four arithmetic surfaces where an implementation that reaches for the obvious
operand — the expiry inside a UPC payload, an unrounded variance, the nominal
clip validity, the first-created basket — lands on the wrong answer.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST,
    CLERK,
    CANONICAL_DATABAR_PAYLOAD,
    BarcodeFamily,
    ClipStatus,
    IntakeStatus,
    ItemStatus,
    LotStatus,
    OfferStatus,
    api_errors as err,
    assert_calendar_date,
    assert_fields,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    factories as f,
    make_manufacturer_headers,
    make_retailer_headers,
    upc_ext5_payload,
)


def test_01_the_upc_family_folds_units_and_grace_and_encodes_no_expiry(
        api, build):
    """Two expiries, one payload; the databar of the same terms carries YYMMDD.

    "The payload is built by exact digit concatenation, with no separators and no
    trimming of leading zeros, from five fixed-width components: the issuer's
    `gs1_company_prefix` exactly as stored (six digits); the `face_value_cents`
    rendered as a decimal string and left-padded with zeros to five characters;
    the `purchase_requirement_units` rendered and left-padded with zeros to two
    characters; the `redemption_grace_days` rendered and left-padded with zeros
    to three characters; and the `expiration_date` rendered as a six-digit
    year-month-day string using the last two digits of the year, so that
    2026-12-31 becomes `261231`."

    "For a `UPC_A_WITH_EXT5` offer the payload is the coupon number system digit
    `5`, followed by the six-digit prefix, then the five-digit face value, then
    the five-digit combined units-and-grace extension — seventeen digits in all."

    "Only the databar family carries the expiration date, so a `UPC_A_WITH_EXT5`
    coupon's expiry can only ever be checked against the offer row and never
    re-derived from the barcode."

    Design: Corner/calculations/upc_barcode_family_encodes_units_and_grace_but_drops_the_expiry
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    headers = make_manufacturer_headers(mfr["id"])

    terms = dict(face_value_cents=50, purchase_requirement_units=1,
                 redemption_grace_days=30)
    first_upc = build.offer(mfr["id"], offer_code="SOUP50",
                            barcode_family=BarcodeFamily.UPC_A_WITH_EXT5,
                            expiration_date="2026-12-31", **terms)
    later_upc = build.offer(mfr["id"], offer_code="SOUP51",
                            barcode_family=BarcodeFamily.UPC_A_WITH_EXT5,
                            expiration_date="2027-01-31", **terms)
    databar = build.offer(mfr["id"], offer_code="SOUP52",
                          barcode_family=BarcodeFamily.GS1_DATABAR,
                          expiration_date="2026-12-31", **terms)

    expected_upc = upc_ext5_payload("038000", 50, 1, 30)
    assert expected_upc == "50380000005001030", (
        "the ext5 component is the units times one thousand plus the grace "
        f"days, padded to five digits, got {expected_upc!r}"
    )

    registered_first = validate_success(
        api.register_offer(first_upc["id"], headers))
    assert_fields(registered_first, {
        "barcode_payload": expected_upc,
        "status": OfferStatus.REGISTERED,
        "version": 2,
    })
    assert len(registered_first["barcode_payload"]) == 17, (
        "a UPC_A_WITH_EXT5 payload is seventeen digits in all"
    )

    registered_later = validate_success(
        api.register_offer(later_upc["id"], headers))
    assert registered_later["barcode_payload"] == expected_upc, (
        "the two UPC offers differ only in expiration_date, and that date is "
        "not part of the payload, so both mint byte-identical barcodes"
    )
    assert_fields(registered_later,
                  {"status": OfferStatus.REGISTERED, "version": 2})

    registered_databar = validate_success(
        api.register_offer(databar["id"], headers))
    assert_fields(registered_databar, {
        "barcode_payload": CANONICAL_DATABAR_PAYLOAD,
        "status": OfferStatus.REGISTERED,
        "version": 2,
    })
    assert len(registered_databar["barcode_payload"]) == 25, (
        "the databar payload is twenty-five digits in all"
    )
    assert "261231" in registered_databar["barcode_payload"], (
        "only the databar family carries the six-digit expiry"
    )
    assert "261231" not in registered_first["barcode_payload"], (
        "the UPC family encodes no expiration date at all"
    )


def test_02_a_variance_of_exactly_two_percent_is_accepted_either_way(
        api, build):
    """98 of 100 passes, 97 is refused and writes nothing, 102 passes too.

    "The variance is then computed as the absolute difference between the
    verified count and the `declared_count`, multiplied by one hundred, divided
    by the `declared_count`, and rounded half up to two decimal places — which
    also means the `declared_count` must be at least 1 for the variance to be
    computable, so a submission declared with zero coupons can never be
    count-verified."

    "On failure the request is rejected with `ERR_COUNT_VARIANCE_EXCEEDED` and
    the submission stays `RECEIVED`, so the clerk can recount and try again."

    Design: Corner/calculations/count_variance_of_exactly_two_percent_is_accepted
    """
    retailer = build.retailer(legal_name="Northgate Markets")
    accepted = build.submission(retailer["id"], 100, "2026-07-01", "2026-07-15")
    refused_then_retried = build.submission(
        retailer["id"], 100, "2026-07-15", "2026-07-31")

    on_tolerance = validate_success(
        api.verify_count(accepted["id"], 98, CLERK))
    assert_fields(on_tolerance, {
        "verified_count": 98,
        "intake_status": IntakeStatus.COUNT_VERIFIED,
    })
    assert_rate_equals(on_tolerance["count_variance_pct"], "2.00",
                       "count_variance_pct")

    over_tolerance = api.verify_count(refused_then_retried["id"], 97, CLERK)
    validate_error(over_tolerance, err.ERR_COUNT_VARIANCE_EXCEEDED,
                   expected_status=422)

    untouched = validate_success(
        api.get_submission(refused_then_retried["id"], CLERK))
    assert_fields(untouched, {
        "intake_status": IntakeStatus.RECEIVED,
        "verified_count": 0,
        "version": 1,
    })
    assert_rate_equals(untouched["count_variance_pct"], "0.00",
                       "count_variance_pct")

    overcounted = validate_success(
        api.verify_count(refused_then_retried["id"], 102, CLERK))
    assert_fields(overcounted, {
        "verified_count": 102,
        "intake_status": IntakeStatus.COUNT_VERIFIED,
    })
    assert_rate_equals(overcounted["count_variance_pct"], "2.00",
                       "count_variance_pct")


def test_03_the_offer_grace_ceiling_beats_the_nominal_clip_validity(api, build):
    """Sixty validity days on both offers, and neither clip lives that long.

    "`clip_expires_at`, the inclusive upper bound, is computed once at creation
    and never recomputed afterwards, even if the offer is later amended."

    "That second ceiling is the interesting half — a clip can never outlive the
    offer's redemption grace period, so clipping a nearly-expired offer yields a
    clip that dies far sooner than `clip_validity_days` alone would suggest, and
    the matcher will then pass it over even though its nominal validity has not
    elapsed."

    "One consumer may hold only so many live clips on one offer at a time, and
    the limit is 2."

    Design: Corner/calculations/clip_expiry_is_capped_by_the_offer_grace_not_the_validity_days
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    retailer = build.retailer(legal_name="Northgate Markets")
    headers = make_retailer_headers(retailer["id"])

    terms = dict(digital_enabled=True, clip_validity_days=60,
                 expiration_date="2026-08-10")
    no_grace = build.active_offer(mfr["id"], offer_code="SOUP50",
                                  redemption_grace_days=0, **terms)
    month_of_grace = build.active_offer(mfr["id"], offer_code="SOUP51",
                                        redemption_grace_days=30, **terms)

    pinned_to_expiry = validate_success(
        api.create_clip(no_grace["id"], "C1", headers), 201)
    assert_fields(pinned_to_expiry, {
        "clipped_at": "2026-08-01",
        "clip_expires_at": "2026-08-10",
        "consumer_ref": "C1",
        "status": ClipStatus.CLIPPED,
    })
    assert_nulls(pinned_to_expiry, ["matched_event_id"])
    assert_calendar_date(pinned_to_expiry["clip_expires_at"], "clip_expires_at")

    pinned_to_grace = validate_success(
        api.create_clip(month_of_grace["id"], "C1", headers), 201)
    assert_fields(pinned_to_grace, {
        "clipped_at": "2026-08-01",
        "clip_expires_at": "2026-09-09",
        "consumer_ref": "C1",
        "status": ClipStatus.CLIPPED,
    })
    assert_nulls(pinned_to_grace, ["matched_event_id"])

    for clip in (pinned_to_expiry, pinned_to_grace):
        assert clip["clip_expires_at"] != "2026-09-30", (
            "sixty validity days from the 2026-08-01 clock would reach "
            "2026-09-30, but the offer ceiling is the earlier date and wins"
        )

    both, meta = validate_paginated(
        api.list_clips(headers, consumer_ref="C1", limit=10))
    assert meta["total_count"] == 2, (
        "the concurrency limit is counted per offer and consumer pair, so one "
        "live clip on each of two offers is legal"
    )
    assert {row["id"] for row in both} == {
        pinned_to_expiry["id"], pinned_to_grace["id"]}


def test_04_the_earliest_qualifying_basket_wins_over_the_larger_earlier_created(
        api, build):
    """Both baskets clear the three-unit bar; transaction_date picks the winner.

    "First the system computes how many qualifying units the coupon needs: the
    coupon's `claimed_units` multiplied by the offer's
    `purchase_requirement_units`."

    "If at least one basket qualifies, the qualifying baskets are ranked by
    `transaction_date` ascending with `created_at` ascending as the tie-break —
    the basket `id` is never consulted — and the earliest one is recorded as
    `matched_purchase_record_id` while the coupon proceeds to clear."

    "Baskets are never consumed: one basket may back more than one coupon,
    because the clearinghouse only requires that a qualifying transaction
    existed."

    Design: Corner/calculations/misredemption_match_picks_the_earliest_qualifying_basket
    """
    world = build.market(purchase_requirement_units=1)
    retailer_id = world["retailer_id"]
    offer_id = world["offer_id"]

    larger_but_later = build.purchase_record(
        retailer_id, offer_id, "POS-1", "2026-07-20", 5)
    earlier = build.purchase_record(
        retailer_id, offer_id, "POS-1", "2026-07-10", 3)

    submission = build.verified_submission(retailer_id, 1)
    lot = build.lot(submission["id"], offer_id, world["manufacturer_id"], 1)
    build.capture(lot["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/1.jpg", "2026-07-12",
        pos_transaction_ref="POS-1", claimed_units=3)])

    valued = validate_success(api.finalize_lot(lot["id"], ANALYST))
    assert_fields(valued, {
        "status": LotStatus.VALIDATED,
        "accepted_qty": 3,
        "rejected_qty": 0,
        "projected_accepted_units": 3,
    })
    assert_money(valued, "gross_face_value_cents", 150)
    assert_money(valued, "handling_fee_cents", 21)

    rows, meta = validate_paginated(
        api.list_items(ANALYST, lot_id=lot["id"], limit=10))
    assert meta["total_count"] == 1
    cleared = rows[0]
    assert_fields(cleared, {
        "status": ItemStatus.ACCEPTED,
        "claimed_units": 3,
        "matched_purchase_record_id": earlier["id"],
    })
    assert_nulls(cleared, ["reject_code"])
    assert cleared["matched_purchase_record_id"] != larger_but_later["id"], (
        "the 2026-07-20 basket was created first and holds more units, but "
        "ranking is by transaction_date ascending"
    )

    for basket, units in ((larger_but_later, 5), (earlier, 3)):
        still_there = validate_success(
            api.get_purchase_record(basket["id"], ANALYST))
        assert_fields(still_there, {"qualifying_units": units,
                                    "pos_transaction_ref": "POS-1"})
