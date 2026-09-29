"""Which scope a uniqueness rule is taken over, and what answers first.

Codes that stay occupied after withdrawal, prefixes that are global, an
authorisation ladder that refuses before it looks, a per-retailer channel gate,
and two aggregate limits that refuse a whole request rather than trimming it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    CLERK,
    UNKNOWN_UUID,
    CANONICAL_DATABAR_PAYLOAD,
    Channel,
    ChannelCapability,
    IntakeStatus,
    OfferStatus,
    SettlementStatus,
    api_errors as err,
    assert_fields,
    assert_money,
    databar_payload,
    factories as f,
    make_manufacturer_headers,
    make_retailer_headers,
)


def test_01_a_withdrawn_code_stays_taken_and_the_prefix_is_global(api, build):
    """SOUP50 is never recycled, soup50 is not a code at all, 038000 is claimed.

    "Creating one requires the issuing `manufacturer_id`, an `offer_code` of 1 to
    24 characters drawn from uppercase alphanumerics and the hyphen and unique
    within that issuer (compared case-sensitively against every offer of that
    issuer, **including** ones already `WITHDRAWN`, so a code is never recycled),
    a `face_value_cents` between 1 and 100000 that is what the manufacturer
    reimburses per cleared unit, a `handling_fee_cents` between 0 and 1000 that is
    the contractual per-unit fee basis, an `expiration_date` as a calendar date, a
    `redemption_instructions` free-text block of 1 to 500 characters carrying the
    retailer-facing clearing instructions printed on the coupon, a
    `barcode_family` of either `GS1_DATABAR` or `UPC_A_WITH_EXT5`, and a
    `max_redemptions` between 1 and 100000000 that ceilings the cumulative cleared
    units across every lot and every digital redemption of the offer."

    "The administrator supplies the issuer's registered `legal_name` — between 1
    and 200 characters and never blank — together with its `gs1_company_prefix`,
    which must be exactly six characters, all digits, and which no other issuer
    may already hold; two issuers sharing a prefix would mint colliding barcode
    payloads, which is why the collision is refused with
    `ERR_DUPLICATE_GS1_PREFIX` rather than tolerated."

    Design: Corner/validations/offer_code_uniqueness_survives_withdrawal_and_prefix_uniqueness_is_global
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    headers = make_manufacturer_headers(mfr["id"])
    retired = build.offer(mfr["id"], offer_code="SOUP50")
    build.register(retired)
    withdrawn = build.withdraw(retired)
    assert_fields(withdrawn, {"status": OfferStatus.WITHDRAWN})

    recycled = api.create_offer(f.offer_payload(
        mfr["id"], offer_code="SOUP50", face_value_cents=75,
        handling_fee_cents=8, max_redemptions=1000), headers)
    validate_error(recycled, err.ERR_DUPLICATE_OFFER_CODE, expected_status=409)

    lowercase = api.create_offer(f.offer_payload(
        mfr["id"], offer_code="soup50", face_value_cents=75,
        handling_fee_cents=8, max_redemptions=1000), headers)
    validate_error(lowercase, err.ERR_INVALID_REQUEST, expected_status=400)

    rival = api.create_manufacturer(f.manufacturer_payload(
        legal_name="Rival Brands", gs1_company_prefix="038000"), ADMIN)
    validate_error(rival, err.ERR_DUPLICATE_GS1_PREFIX, expected_status=409)

    offers, meta = validate_paginated(
        api.list_offers(headers, manufacturer_id=mfr["id"]))
    assert meta["total_count"] == 1, (
        "neither refused creation left an offer behind"
    )
    assert offers[0]["id"] == retired["id"]

    issuers, issuer_meta = validate_paginated(api.list_manufacturers(ADMIN))
    assert issuer_meta["total_count"] == 1, (
        "the prefix collision refused the second issuer outright"
    )


def test_02_the_same_code_under_another_issuer_mints_its_own_barcode(api, build):
    """Uniqueness is scoped to the issuer; the payloads differ in six digits.

    "Two sibling rules over disjoint endpoints: `offer_code` must be unique within
    its manufacturer on offer creation, otherwise `ERR_DUPLICATE_OFFER_CODE`
    (409); and `gs1_company_prefix` must be globally unique on manufacturer
    creation, otherwise `ERR_DUPLICATE_GS1_PREFIX` (409)."

    "For a `GS1_DATABAR` offer the payload is the family code `811`, followed by
    the six-digit prefix, then the five-digit face value, then the two-digit
    purchase requirement, then the six-digit expiry, then the three-digit grace —
    twenty-five digits in all."

    Design: Corner/validations/same_offer_code_under_a_second_manufacturer_passes_and_mints_its_own_barcode
    """
    first = build.manufacturer(gs1_company_prefix="038000",
                               legal_name="Kellwood Foods")
    second = build.manufacturer(gs1_company_prefix="041000",
                                legal_name="Rival Brands")
    incumbent = build.active_offer(first["id"], offer_code="SOUP50")

    challenger = validate_success(api.create_offer(f.offer_payload(
        second["id"], offer_code="SOUP50", max_redemptions=1000),
        make_manufacturer_headers(second["id"])), 201)
    assert_fields(challenger, {
        "offer_code": "SOUP50",
        "manufacturer_id": second["id"],
        "status": OfferStatus.DRAFT,
    })

    registered = validate_success(api.register_offer(
        challenger["id"], make_manufacturer_headers(second["id"])))
    expected = databar_payload("041000", 50, 1, "2026-12-31", 30)
    assert_fields(registered, {
        "status": OfferStatus.REGISTERED,
        "barcode_payload": expected,
    })
    assert expected == "8110410000005001261231030", (
        f"the prefix digits are the only difference, got {expected!r}"
    )

    unchanged = validate_success(api.get_offer(incumbent["id"], ADMIN))
    assert_fields(unchanged, {"barcode_payload": CANONICAL_DATABAR_PAYLOAD})
    assert (unchanged["barcode_payload"][:3]
            == registered["barcode_payload"][:3]), (
        "both payloads open with the same family code"
    )
    assert (unchanged["barcode_payload"][9:]
            == registered["barcode_payload"][9:]), (
        "the two offers share every term but the issuer prefix"
    )


def test_03_the_ladder_answers_authentication_then_role_then_existence(api):
    """One request breaks three rules and the answer walks the ladder in order.

    "`X-User-ID` and `X-User-Role` are present and non-blank and the role is one
    of the six names — otherwise `ERR_UNAUTHENTICATED` (401)."

    "The role appears in the target endpoint's authorised-role list — otherwise
    `ERR_FORBIDDEN_ROLE` (403)."

    "Path parameters are validated left to right: the `{id}` segment must resolve
    to an existing row of that collection before the body is examined, and an
    unresolvable segment yields the not-found code for that collection (§2.11)."

    Design: Corner/validations/auth_ladder_returns_401_then_403_before_existence_on_an_unknown_offer
    """
    anonymous = api.activate_offer(UNKNOWN_UUID, {})
    validate_error(anonymous, err.ERR_UNAUTHENTICATED, expected_status=401)

    wrong_role = api.activate_offer(
        UNKNOWN_UUID, make_retailer_headers("ret-unknown"))
    validate_error(wrong_role, err.ERR_FORBIDDEN_ROLE, expected_status=403)
    assert "ERR_OFFER_NOT_FOUND" not in wrong_role.text, (
        "a caller the endpoint does not admit learns nothing about whether the "
        "path id exists"
    )

    authorised = api.activate_offer(UNKNOWN_UUID, ADMIN)
    validate_error(authorised, err.ERR_OFFER_NOT_FOUND, expected_status=404)


def test_04_the_channel_gate_reads_the_retailer_not_the_body(api, build):
    """The same MAIL body is refused for one retailer and accepted for another.

    "The chosen channel must be permitted by the retailer's `channel_capability`:
    a `MAIL` submission requires `MAIL_ONLY` or `BOTH`, an `ELECTRONIC` submission
    requires `ELECTRONIC_ONLY` or `BOTH`, and anything else is refused with
    `ERR_CHANNEL_NOT_SUPPORTED`."

    "`channel_capability` records which intake channels the retailer is contracted
    for and is `MAIL_ONLY`, `ELECTRONIC_ONLY` or `BOTH`, defaulting to `BOTH`."

    "A freshly opened submission is `RECEIVED` on the intake dimension and
    `PENDING` on the settlement dimension, with `verified_count` 0,
    `count_variance_pct` `0.00`, a null `hold_reason` and every money field 0."

    Design: Corner/validations/channel_capability_gates_intake_only_for_the_contracted_channels
    """
    electronic_only = build.retailer(
        legal_name="Wireline Grocers",
        channel_capability=ChannelCapability.ELECTRONIC_ONLY)
    both = build.retailer(legal_name="Northgate Markets")

    refused = api.create_submission(f.submission_payload(
        electronic_only["id"], 5, "2026-07-01", "2026-07-31", Channel.MAIL),
        CLERK)
    validate_error(refused, err.ERR_CHANNEL_NOT_SUPPORTED, expected_status=422)

    accepted = validate_success(api.create_submission(f.submission_payload(
        electronic_only["id"], 5, "2026-07-01", "2026-07-31",
        Channel.ELECTRONIC), CLERK), 201)
    assert_fields(accepted, {
        "channel": Channel.ELECTRONIC,
        "intake_status": IntakeStatus.RECEIVED,
        "settlement_status": SettlementStatus.PENDING,
        "postmark_window_start": "2026-07-01",
        "postmark_window_end": "2026-07-31",
    })

    same_body = validate_success(api.create_submission(f.submission_payload(
        both["id"], 5, "2026-07-01", "2026-07-31", Channel.MAIL), CLERK), 201)
    assert_fields(same_body, {
        "channel": Channel.MAIL,
        "intake_status": IntakeStatus.RECEIVED,
    })

    contracted = validate_success(api.get_retailer(both["id"], ADMIN))
    assert_fields(contracted,
                  {"channel_capability": ChannelCapability.BOTH})


def test_05_both_aggregate_limits_refuse_the_request_whole(api, build):
    """A legal one-coupon lot and a legal three-image batch, both refused.

    "Finally, the running sum of `counted_qty` across the submission's existing
    lots plus the new lot's `counted_qty` must not exceed the submission's
    `verified_count`, or the request is refused with `ERR_LOT_COUNT_OVERFLOW` — a
    clerk cannot sort more coupons than were counted."

    "The batch is refused as a whole and never partially applied: if
    `captured_item_count` plus the number of supplied elements would exceed the
    lot's `sample_size`, the call fails with `ERR_LOT_CAPTURE_COMPLETE`."

    "Creating the lot also increments the submission's `sorted_lot_count` and
    recomputes its `declared_face_value_cents`, which is the sum over the
    submission's lots of each lot's `counted_qty` multiplied by that lot's offer
    face value — the notional value of the shipment before anyone has adjudicated
    anything."

    Design: Corner/validations/lot_and_capture_aggregates_are_refused_whole_not_partially
    """
    world = build.market()
    submission = build.verified_submission(world["retailer_id"], 10)
    build.lot(submission["id"], world["offer_id"], world["manufacturer_id"], 6)

    overflow = api.create_lot(submission["id"], f.lot_payload(
        world["offer_id"], world["manufacturer_id"], 5), CLERK)
    validate_error(overflow, err.ERR_LOT_COUNT_OVERFLOW, expected_status=422)

    small = build.lot(submission["id"], world["offer_id"],
                      world["manufacturer_id"], 4)

    build.capture(small["id"], f.item_batch(2, world["barcode"], "2026-07-05"))
    over_sample = api.capture_items(small["id"], f.item_batch(
        3, world["barcode"], "2026-07-05",
        uri_stem="s3://coupon-images/late"), CLERK)
    validate_error(over_sample, err.ERR_LOT_CAPTURE_COMPLETE,
                   expected_status=409)

    untrimmed = validate_success(api.get_lot(small["id"], CLERK))
    assert_fields(untrimmed, {"captured_item_count": 2, "sample_size": 4})

    rows, meta = validate_paginated(
        api.list_items(CLERK, lot_id=small["id"], limit=10))
    assert meta["total_count"] == 2, (
        "not one coupon of the refused batch survived, though two slots were free"
    )
    assert len(rows) == 2

    intact = validate_success(api.get_submission(submission["id"], CLERK))
    assert_fields(intact, {"sorted_lot_count": 2,
                           "intake_status": IntakeStatus.SORTED})
    assert_money(intact, "declared_face_value_cents", 500)
