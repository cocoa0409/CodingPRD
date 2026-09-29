"""What a freshly minted row looks like, and what a read of it must return.

Onboarding writes ledgers at zero, defaults at their declared values, and
computed fields either null or absent from the caller's reach entirely.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ANALYST,
    CLERK,
    UNKNOWN_UUID,
    CANONICAL_DATABAR_PAYLOAD,
    ChannelCapability,
    FeeTier,
    FraudScoringMode,
    HandlingFeePolicy,
    ManufacturerStatus,
    OfferStatus,
    PaymentTerms,
    RetailerStatus,
    api_errors as err,
    assert_bare_uuid,
    assert_fields,
    assert_freshly_created,
    assert_ids_in_order,
    assert_manufacturer_ledger,
    assert_money,
    assert_nulls,
    assert_ordered_descending,
    assert_page,
    assert_rate_equals,
    factories as f,
    make_manufacturer_headers,
)


def test_01_a_new_issuer_is_born_active_with_all_three_ledgers_at_zero(api):
    """Nothing funded, nothing disbursed, and a balance of 0 rather than null.

    "A newly created issuer is `ACTIVE` and its three ledger fields —
    `funded_total_cents`, `disbursed_total_cents` and `funding_balance_cents` —
    all start at 0."

    "Every stored resource carries a server-minted `id`: a UUID string with no
    type prefix and no domain-flavoured encoding."

    Design: Corner/entities/manufacturer_creation_returns_zeroed_funding_ledger
    """
    response = api.create_manufacturer(f.manufacturer_payload(
        legal_name="Kellwood Foods", gs1_company_prefix="038000",
        handling_fee_policy=HandlingFeePolicy.TIERED_RATE,
        dispute_window_days=60), ADMIN)
    envelope = response.json()
    data = validate_success(response, 201)

    assert envelope["response_type"] == "object", (
        "a single resource is returned with response_type object"
    )
    assert envelope["meta"]["api_request_id"].startswith("req_"), (
        "every response carries a server-generated api_request_id starting "
        f"with req_, got {envelope['meta']['api_request_id']!r}"
    )

    assert_fields(data, {
        "legal_name": "Kellwood Foods",
        "gs1_company_prefix": "038000",
        "handling_fee_policy": HandlingFeePolicy.TIERED_RATE,
        "dispute_window_days": 60,
        "status": ManufacturerStatus.ACTIVE,
    })
    assert_manufacturer_ledger(data, funded_total=0, disbursed_total=0)
    assert_money(data, "funding_balance_cents", 0)
    assert_freshly_created(data)
    assert_bare_uuid(data["id"])
    assert "_" not in data["id"], (
        "the id carries no type prefix, so it holds no underscore"
    )


def test_02_a_retailer_read_returns_both_score_variants_and_a_null_last_rescore(
        api, build):
    """Every stored field comes back, including the variant the mode did not select.

    "A newly created retailer is `ACTIVE`, its effective `handling_fee_tier` is
    initialised from `base_fee_tier`, all three fraud scores
    (`fraud_score_rolling_window`, `fraud_score_lifetime_weighted` and
    `fraud_score`) are `0.00`, all three component rates (`duplicate_rate`,
    `misredemption_rate` and `counterfeit_rate`) are `0.00`,
    `rejected_submission_count` and `unpaid_balance_cents` are 0, and
    `last_rescored_at` is null until the first rescore writes a logical-clock
    instant into it."

    Design: Corner/entities/retailer_retrieval_returns_every_stored_field
    """
    created = build.retailer(legal_name="Northgate Markets",
                            channel_capability=ChannelCapability.MAIL_ONLY,
                            payment_terms=PaymentTerms.NET_45,
                            base_fee_tier=FeeTier.PREFERRED,
                            fraud_scoring_mode=FraudScoringMode.LIFETIME_WEIGHTED)

    data = validate_success(api.get_retailer(created["id"], ANALYST))

    assert_fields(data, {
        "id": created["id"],
        "channel_capability": ChannelCapability.MAIL_ONLY,
        "payment_terms": PaymentTerms.NET_45,
        "base_fee_tier": FeeTier.PREFERRED,
        "fraud_scoring_mode": FraudScoringMode.LIFETIME_WEIGHTED,
        "handling_fee_tier": FeeTier.PREFERRED,
        "status": RetailerStatus.ACTIVE,
        "rejected_submission_count": 0,
    })
    for field in ("fraud_score_rolling_window", "fraud_score_lifetime_weighted",
                  "fraud_score", "duplicate_rate", "misredemption_rate",
                  "counterfeit_rate"):
        assert_rate_equals(data[field], "0.00", field)
    assert_money(data, "unpaid_balance_cents", 0)
    assert_nulls(data, ["last_rescored_at"])


def test_03_the_retailer_listing_returns_newest_first_and_filters_before_paging(
        api, build):
    """Three rows, a page of two, and a status filter that empties the set.

    "Two listings are documented exceptions and return newest first, ordered by
    `created_at` descending: the manufacturer listing and the retailer listing."

    "Both are echoed back in `meta`, alongside `total_count` (the number of rows
    matching the filter before the page window is applied) and `has_more` (true
    when `offset` plus the number of returned rows is still below
    `total_count`)."

    Design: Corner/entities/retailer_listing_paginates_newest_first
    """
    first = build.retailer(legal_name="Alder Grocery Cooperative")
    second = build.retailer(legal_name="Bayfront Grocers")
    third = build.retailer(legal_name="Cedarline Markets")

    rows, meta = validate_paginated(api.list_retailers(ADMIN, limit=2, offset=0))
    assert_page(meta, total_count=3, limit=2, offset=0, has_more=True)
    assert len(rows) == 2, "the first page holds the page size, not the whole set"
    assert_ids_in_order(rows, [third["id"], second["id"]])
    assert_ordered_descending(rows)

    tail, tail_meta = validate_paginated(
        api.list_retailers(ADMIN, limit=2, offset=2))
    assert_page(tail_meta, total_count=3, limit=2, offset=2, has_more=False)
    assert_ids_in_order(tail, [first["id"]])

    empty, empty_meta = validate_paginated(
        api.list_retailers(ADMIN, status=RetailerStatus.SUSPENDED))
    assert empty == [], "no retailer has been suspended, so the page is empty"
    assert_fields(empty_meta, {"total_count": 0, "has_more": False})


def test_04_an_unused_uuid_on_the_offer_route_returns_the_offer_not_found_code(
        api):
    """The 404 is collection-specific and arrives in the error envelope shape.

    "Path parameters are validated left to right: the `{id}` segment must resolve
    to an existing row of that collection before the body is examined, and an
    unresolvable segment yields the not-found code for that collection (§2.11)."

    "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/offer_retrieval_with_unknown_id_returns_offer_not_found
    """
    response = api.get_offer(UNKNOWN_UUID, CLERK)
    validate_error(response, err.ERR_OFFER_NOT_FOUND, expected_status=404)

    envelope = response.json()
    assert envelope["response_type"] == "error", (
        "a refusal is reported with response_type error"
    )
    assert isinstance(envelope["data"]["message"], str), (
        "the error carries a human-readable message string"
    )
    assert envelope["data"]["message"].strip() != "", (
        "the message must not be blank"
    )
    assert "barcode_payload" not in envelope["data"], (
        "no offer payload is returned alongside a not-found refusal"
    )


def test_05_each_offer_input_without_a_default_is_individually_required(
        api, build):
    """Dropping the face value, the family or the ceiling all fail the same way.

    "The body parses as JSON; every required field for that endpoint is present
    and non-null; no unknown field is present; every value matches its declared
    type; every enum value is in range; every integer is within its declared
    bounds; every date parses as an ISO 8601 value; and no computed or
    system-owned field is supplied by the caller."

    Design: Corner/entities/offer_creation_missing_required_fields_returns_invalid_request
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    headers = make_manufacturer_headers(mfr["id"])

    for dropped in ("face_value_cents", "barcode_family", "max_redemptions"):
        payload = f.offer_payload(mfr["id"], offer_code="SOUP50",
                                  max_redemptions=1000)
        payload.pop(dropped)
        refused = api.create_offer(payload, headers)
        validate_error(refused, err.ERR_INVALID_REQUEST, expected_status=400)

    rows, meta = validate_paginated(
        api.list_offers(headers, manufacturer_id=mfr["id"]))
    assert rows == [], "none of the three refused calls may create an offer"
    assert_fields(meta, {"total_count": 0})


def test_06_the_four_optional_offer_terms_fall_back_to_their_declared_defaults(
        api, build):
    """One unit, thirty grace days, digital off, and sixty-day clips.

    "Four further inputs are optional: `purchase_requirement_units`, the
    qualifying units a shopper must buy per cleared unit, at least 1 and at most
    24 and defaulting to 1; `redemption_grace_days`, the number of days after
    expiry during which a retailer may still open a lot against the offer, from 0
    to 365 and defaulting to 30; `digital_enabled`, defaulting to false; and
    `clip_validity_days`, from 1 to 365 and defaulting to 60."

    "A newly created offer sits in `DRAFT` with a null `barcode_payload`, an
    `accepted_redemption_count` of 0 and a null `withdrawn_reason`."

    Design: Corner/entities/offer_creation_omitting_optional_terms_applies_declared_defaults
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")

    data = validate_success(api.create_offer(
        f.offer_payload(mfr["id"], offer_code="SOUP50", max_redemptions=1000),
        make_manufacturer_headers(mfr["id"])), 201)

    assert_fields(data, {
        "purchase_requirement_units": 1,
        "redemption_grace_days": 30,
        "digital_enabled": False,
        "clip_validity_days": 60,
        "status": OfferStatus.DRAFT,
        "accepted_redemption_count": 0,
    })
    assert_nulls(data, ["barcode_payload", "withdrawn_reason"])
    assert_freshly_created(data)


def test_07_a_retailer_onboarded_with_only_a_name_takes_every_default(api):
    """BOTH channels, NET_30, STANDARD, ROLLING_WINDOW — and the tier seeded from base.

    "`channel_capability` records which intake channels the retailer is
    contracted for and is `MAIL_ONLY`, `ELECTRONIC_ONLY` or `BOTH`, defaulting to
    `BOTH`."

    "`fraud_scoring_mode` chooses which of the two fraud-score variants the
    clearinghouse treats as authoritative for this retailer and is either
    `ROLLING_WINDOW` or `LIFETIME_WEIGHTED`, defaulting to `ROLLING_WINDOW`."

    Design: Corner/entities/retailer_creation_omitting_optional_fields_applies_declared_defaults
    """
    data = validate_success(api.create_retailer(
        {"legal_name": "Northgate Markets"}, ADMIN), 201)

    assert_fields(data, {
        "legal_name": "Northgate Markets",
        "channel_capability": ChannelCapability.BOTH,
        "payment_terms": PaymentTerms.NET_30,
        "base_fee_tier": FeeTier.STANDARD,
        "fraud_scoring_mode": FraudScoringMode.ROLLING_WINDOW,
        "handling_fee_tier": FeeTier.STANDARD,
        "status": RetailerStatus.ACTIVE,
        "rejected_submission_count": 0,
    })
    assert_rate_equals(data["fraud_score"], "0.00", "fraud_score")
    assert_money(data, "unpaid_balance_cents", 0)
    assert_nulls(data, ["last_rescored_at"])
    assert_freshly_created(data)


def test_08_a_caller_cannot_hand_the_clearinghouse_a_barcode_or_a_counter(
        api, build):
    """Both computed fields are refused on input and the payload appears at register.

    "The body parses as JSON; every required field for that endpoint is present
    and non-null; no unknown field is present; every value matches its declared
    type; every enum value is in range; every integer is within its declared
    bounds; every date parses as an ISO 8601 value; and no computed or
    system-owned field is supplied by the caller."

    "Registration advances the offer `DRAFT` → `REGISTERED` and, in the same
    call, mints `barcode_payload` once and for all; it is never recomputed
    afterwards."

    Design: Corner/entities/offer_computed_fields_input_ignored_and_minted_at_register
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    headers = make_manufacturer_headers(mfr["id"])

    for field, value in (("barcode_payload", CANONICAL_DATABAR_PAYLOAD),
                         ("accepted_redemption_count", 5)):
        payload = f.offer_payload(mfr["id"], offer_code="SOUP50",
                                  max_redemptions=1000)
        payload[field] = value
        validate_error(api.create_offer(payload, headers),
                       err.ERR_INVALID_REQUEST, expected_status=400)

    draft = validate_success(api.create_offer(
        f.offer_payload(mfr["id"], offer_code="SOUP50", max_redemptions=1000),
        headers), 201)
    assert_nulls(draft, ["barcode_payload"])
    assert_fields(draft, {"accepted_redemption_count": 0})

    registered = validate_success(api.register_offer(draft["id"], headers))
    assert_fields(registered, {
        "status": OfferStatus.REGISTERED,
        "barcode_payload": CANONICAL_DATABAR_PAYLOAD,
        "accepted_redemption_count": 0,
        "version": 2,
    })
    assert len(registered["barcode_payload"]) == 25, (
        "the databar payload is twenty-five digits in all"
    )
