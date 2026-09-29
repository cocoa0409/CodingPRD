"""Resource shapes, server-owned identity metadata and reference resolution.

Covers the persisted shape of the registry families on creation and on read: the
four server-owned properties of PRD §2.4, the pagination contract of §2.3, the
"derived state is never client-supplied" rule of §2.8, the request-shape and
reference-resolution rungs of the rejection ladder in §2.9, and the declared
creation defaults of §3.1, §3.2, §3.4 and §3.5.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# A pinned Wednesday, so every stamped instant in this module is predictable.
PINNED_CLOCK = "2026-08-05T09:00:00Z"


def instant_without_fraction(value: str) -> str:
    """The second-precision prefix of a stamped instant, dropping the millis."""
    assert isinstance(value, str) and len(value) >= 19, f"Expected an instant, got {value!r}"
    return value[:19]


def test_brand_create_returns_every_declared_field_with_its_computed_defaults(
    api, brand_administrator_headers
):
    """Registering a brand echoes every supplied field and mints the server-owned four.

    PRD §3.1: "A freshly registered brand starts with `status` `DRAFT` and `enforcement_spend_cents` at 0."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 for each mutating request that touches the row — even when that same request both recomputes derived fields and satisfies an optimistic-concurrency contract, the increment is exactly 1, not 2."
    Design: Corner/entities/brand_create_returns_every_declared_field_with_its_computed_defaults
    """
    fixtures.set_clock(api, PINNED_CLOCK)

    payload = factories.brand_payload(
        name="Acme Tools",
        owner_legal_entity="Acme Tools LLC",
        home_jurisdiction="US",
        authorized_msrp_cents=10000,
        enforcement_budget_cents=500000,
    )
    brand = validate_success(api.create_brand(payload, headers=brand_administrator_headers), 201)

    assertions.assert_common_fields(brand, expected_version=1)
    assert brand["name"] == "Acme Tools", f"Expected name 'Acme Tools', got {brand['name']!r}"
    assert brand["owner_legal_entity"] == "Acme Tools LLC", (
        f"Expected owner_legal_entity 'Acme Tools LLC', got {brand['owner_legal_entity']!r}")
    assert brand["home_jurisdiction"] == "US", (
        f"Expected home_jurisdiction 'US', got {brand['home_jurisdiction']!r}")
    assertions.assert_cents(brand["authorized_msrp_cents"], 10000, "authorized_msrp_cents")
    assertions.assert_cents(brand["enforcement_budget_cents"], 500000, "enforcement_budget_cents")
    assertions.assert_cents(brand["enforcement_spend_cents"], 0, "enforcement_spend_cents")
    assert brand["status"] == constants.BRAND_STATUS_DRAFT, (
        f"Expected status {constants.BRAND_STATUS_DRAFT}, got {brand['status']}")
    assert instant_without_fraction(brand["created_at"]) == instant_without_fraction(PINNED_CLOCK), (
        f"Expected created_at at the logical clock {PINNED_CLOCK}, got {brand['created_at']}")
    assert brand["created_at"] == brand["updated_at"], (
        f"Expected updated_at to equal created_at on a fresh row, got {brand['updated_at']}")

    read_back = validate_success(api.get_brand(brand["id"], headers=brand_administrator_headers), 200)
    assert read_back == brand, "A read must return exactly the row the create returned"


def test_brand_enforcement_budget_defaults_to_500000_when_omitted(api, brand_administrator_headers):
    """An omitted enforcement budget takes the declared 500000-cent default; 0 is accepted.

    PRD §3.1: "The administrator may also supply `enforcement_budget_cents`, the ceiling for cumulative test-buy spend on the brand; when omitted it defaults to 500000 cents, and when supplied it must be at least 0."
    Design: Corner/entities/brand_enforcement_budget_defaults_to_500000_when_omitted
    """
    fixtures.set_clock(api, PINNED_CLOCK)

    payload = factories.brand_payload(
        name="Acme Tools",
        owner_legal_entity="Acme Tools LLC",
        home_jurisdiction="US",
        authorized_msrp_cents=10000,
    )
    assert "enforcement_budget_cents" not in payload, (
        "This test must omit enforcement_budget_cents entirely")

    defaulted = validate_success(api.create_brand(payload, headers=brand_administrator_headers), 201)
    assertions.assert_cents(
        defaulted["enforcement_budget_cents"],
        constants.DEFAULT_ENFORCEMENT_BUDGET_CENTS,
        "enforcement_budget_cents",
    )
    assertions.assert_cents(defaulted["enforcement_spend_cents"], 0, "enforcement_spend_cents")
    assertions.assert_common_fields(defaulted, expected_version=1)

    zero_budget_payload = factories.brand_payload(enforcement_budget_cents=0)
    zero_budget = validate_success(
        api.create_brand(zero_budget_payload, headers=brand_administrator_headers), 201)
    assertions.assert_cents(zero_budget["enforcement_budget_cents"], 0, "enforcement_budget_cents")


def test_registration_get_returns_the_stored_row_unchanged(api, brand_administrator_headers):
    """A read of a trademark registration is a pure read: same fields, same version, same updated_at.

    PRD §3.1: "A `BrandAdministrator` records each registration or pending application against the brand by supplying `brand_id`, the registry-issued `registration_number` (1 to 40 characters), the issuing registry's `jurisdiction` as exactly two uppercase letters, the `nice_class` covered by the registration as an integer from 1 through 45, the `registration_date` and `expiry_date` as ISO 8601 calendar dates in `YYYY-MM-DD` form with the expiry strictly after the registration date, the boolean `principal_register` flag that is true when the mark sits on the principal rather than the supplemental register, and the initial `status`."
    PRD §2.4: "Creating a new resource returns HTTP 201; every other successful operation, including every action that advances a lifecycle and every read, returns HTTP 200."
    PRD §2.4: "A request that changes nothing on a row leaves that row's `version` and `updated_at` untouched."
    Design: Corner/entities/registration_get_returns_the_stored_row_unchanged
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)

    payload = factories.registration_payload(
        brand["id"],
        jurisdiction="US",
        nice_class=8,
        registration_date="2020-03-15",
        expiry_date="2034-03-15",
        principal_register=True,
        status=constants.REGISTRATION_STATUS_REGISTERED,
    )
    created = validate_success(
        api.create_registration(payload, headers=brand_administrator_headers), 201)

    assertions.assert_common_fields(created, expected_version=1)
    assert created["brand_id"] == brand["id"], (
        f"Expected brand_id {brand['id']}, got {created['brand_id']}")
    assert created["registration_number"] == payload["registration_number"], (
        f"Expected registration_number {payload['registration_number']}, "
        f"got {created['registration_number']}")
    assert created["jurisdiction"] == "US", f"Expected jurisdiction 'US', got {created['jurisdiction']!r}"
    assert created["nice_class"] == 8, f"Expected nice_class 8, got {created['nice_class']}"
    assert created["registration_date"] == "2020-03-15", (
        f"Expected registration_date '2020-03-15', got {created['registration_date']!r}")
    assert created["expiry_date"] == "2034-03-15", (
        f"Expected expiry_date '2034-03-15', got {created['expiry_date']!r}")
    assert created["principal_register"] is True, (
        f"Expected principal_register True, got {created['principal_register']!r}")
    assert created["status"] == constants.REGISTRATION_STATUS_REGISTERED, (
        f"Expected status REGISTERED, got {created['status']}")

    # Advancing the clock must not touch a row nobody has written to.
    fixtures.set_clock(api, "2026-09-01T09:00:00Z")
    read_back = validate_success(
        api.get_registration(created["id"], headers=brand_administrator_headers), 200)
    assert read_back == created, "A read must return the stored row byte for byte"
    assertions.assert_unchanged(created, read_back)


def test_listing_list_paginates_with_total_count_and_has_more(api, enforcement_analyst_headers):
    """Three monitored listings page two at a time with an accurate total_count and has_more.

    PRD §2.3: "`total_count` is the number of rows matching the request's filters before the page window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the current window."
    PRD §2.3: "Because the system's clock only advances on demand (§2.5), two rows can legitimately share a `created_at` value; when they do, the tie is broken by persistence sequence ascending — the order in which the server actually stored the rows."
    PRD §3.4: "A new listing starts with `monitor_status` `NEW`, `enforcement_status` `NONE`, `violation_type` `NONE`, and `image_match_score`, `text_match_score`, `price_deviation_factor` and `match_score` all null until the first screening."
    Design: Corner/entities/listing_list_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    seller = fixtures.create_seller(api)

    created_ids = []
    for _ in range(3):
        listing = validate_success(
            api.create_listing(
                factories.listing_payload(brand["id"], seller["id"]),
                headers=enforcement_analyst_headers,
            ),
            201,
        )
        assertions.assert_common_fields(listing, expected_version=1)
        assert listing["monitor_status"] == constants.MONITOR_STATUS_NEW, (
            f"Expected monitor_status NEW, got {listing['monitor_status']}")
        assert listing["enforcement_status"] == constants.ENFORCEMENT_STATUS_NONE, (
            f"Expected enforcement_status NONE, got {listing['enforcement_status']}")
        assert listing["violation_type"] == constants.VIOLATION_TYPE_NONE, (
            f"Expected violation_type NONE, got {listing['violation_type']}")
        for score_field in ("image_match_score", "text_match_score",
                            "price_deviation_factor", "match_score"):
            assert listing[score_field] is None, (
                f"Expected {score_field} null before the first screening, got {listing[score_field]!r}")
        created_ids.append(listing["id"])

    first_page, first_meta = validate_paginated(
        api.list_listings(headers=enforcement_analyst_headers,
                          brand_id=brand["id"], limit=2, offset=0))
    assert first_meta["total_count"] == 3, (
        f"Expected total_count 3, got {first_meta['total_count']}")
    assert first_meta["limit"] == 2, f"Expected limit 2, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"Expected offset 0, got {first_meta['offset']}"
    assert first_meta["has_more"] is True, (
        f"Expected has_more True with one row beyond the window, got {first_meta['has_more']!r}")
    assert len(first_page) == 2, f"Expected 2 rows on the first page, got {len(first_page)}"
    assert [row["id"] for row in first_page] == created_ids[:2], (
        f"Expected persistence order {created_ids[:2]}, got {[row['id'] for row in first_page]}")

    second_page, second_meta = validate_paginated(
        api.list_listings(headers=enforcement_analyst_headers,
                          brand_id=brand["id"], limit=2, offset=2))
    assert second_meta["total_count"] == 3, (
        f"Expected total_count 3, got {second_meta['total_count']}")
    assert second_meta["has_more"] is False, (
        f"Expected has_more False on the last window, got {second_meta['has_more']!r}")
    assert [row["id"] for row in second_page] == created_ids[2:], (
        f"Expected the third row {created_ids[2:]}, got {[row['id'] for row in second_page]}")


def test_seller_get_with_unknown_id_returns_seller_not_found(api, enforcement_analyst_headers):
    """A path identifier that resolves to nothing is the seller family's own 404.

    PRD §2.9: "**Priority 4** — every identifier embedded in the path exists, validated strictly left to right, else the matching not-found error (404)."
    PRD §2.4: "References supplied in a request *body* are resolved after the path, in the field order declared for that endpoint, and each missing target yields the not-found error for its own entity family — `ERR_BRAND_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TEST_BUY_NOT_FOUND`, `ERR_EVIDENCE_PACKAGE_NOT_FOUND`, `ERR_TAKEDOWN_NOT_FOUND`, `ERR_COUNTER_NOTICE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CUSTOMS_RECORDATION_NOT_FOUND` or `ERR_INVESTIGATION_NOT_FOUND`, each with HTTP status 404."
    Design: Corner/entities/seller_get_with_unknown_id_returns_seller_not_found
    """
    fixtures.set_clock(api, PINNED_CLOCK)

    validate_error(
        api.get_seller(NON_EXISTENT_UUID, headers=enforcement_analyst_headers),
        ApiErrorId.SELLER_NOT_FOUND,
    )

    # A real seller alongside it proves the 404 is about the identifier, not the collection.
    seller = fixtures.create_seller(api)
    found = validate_success(api.get_seller(seller["id"], headers=enforcement_analyst_headers), 200)
    assert found["id"] == seller["id"], f"Expected {seller['id']}, got {found['id']}"

    validate_error(
        api.get_seller(NON_EXISTENT_UUID, headers=enforcement_analyst_headers),
        ApiErrorId.SELLER_NOT_FOUND,
    )
    rows, meta = validate_paginated(api.list_sellers(headers=enforcement_analyst_headers))
    assert meta["total_count"] == 1, (
        f"Expected the single real seller to be the only row, got total_count {meta['total_count']}")
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"


def test_listing_create_without_image_hash_returns_4xx(api, enforcement_analyst_headers):
    """The perceptual image hash is a required input, so omitting it is a malformed request.

    PRD §3.4: "An `EnforcementAnalyst` places a marketplace listing under monitoring for a brand by supplying `brand_id`, the `seller_id` of the storefront that owns it, the `marketplace_code` hosting it, the marketplace's own `listing_ref` (1 to 40 characters, unique together with `marketplace_code`; a repeat is refused with `ERR_INVALID_REQUEST`, HTTP 400), the `title_text` captured by the crawler (1 to 300 characters, not blank) which is the input to text matching, the `image_hash` perceptual hash of the hero image (1 to 80 characters, not blank) which is the input to image matching, the `price_cents` at which the listing is offered (at least 0), and the `nice_class` the listed product falls in as an integer from 1 through 45."
    PRD §2.9: "**Priority 3** — request shape: required fields present, enumerated values in range, integer amounts not negative, dates and timestamps ISO 8601, matcher sub-scores inside 0 through 1 inclusive, `effective_from` strictly earlier than `effective_to` when both are supplied, and `recorded_on` no later than `expires_on`; else `ERR_INVALID_REQUEST` (400)."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."
    Design: Corner/entities/listing_create_without_image_hash_returns_4XX
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    seller = fixtures.create_seller(api)

    payload = factories.listing_payload(brand["id"], seller["id"])
    del payload["image_hash"]

    validate_error(
        api.create_listing(payload, headers=enforcement_analyst_headers),
        ApiErrorId.INVALID_REQUEST,
    )

    rows, meta = validate_paginated(
        api.list_listings(headers=enforcement_analyst_headers, brand_id=brand["id"]))
    assert meta["total_count"] == 0, (
        f"A rejected create must persist nothing, got total_count {meta['total_count']}")
    assert rows == [], f"Expected no listing rows, got {rows}"

    # The same payload with the hash restored is accepted, isolating the missing field.
    payload["image_hash"] = "sha256:restored-hero-image-hash"
    accepted = validate_success(
        api.create_listing(payload, headers=enforcement_analyst_headers), 201)
    assert accepted["image_hash"] == "sha256:restored-hero-image-hash", (
        f"Expected the supplied image_hash to be echoed, got {accepted['image_hash']!r}")


def test_representative_effective_to_omitted_means_open_ended(api, brand_administrator_headers):
    """An omitted effective_to persists as null and keeps the designation window open forever.

    PRD §3.2: "The designation window is **half-open**: it includes `effective_from` and excludes `effective_to`, and an omitted or null `effective_to` means the window never closes."
    PRD §3.2: "The new row starts `DESIGNATED` with `revoked_at` null, and its own `id` becomes a valid `X-User-ID` for the `AuthorizedRepresentative` role."
    PRD §3.2: "Two designations of the same enrolment conflict only when all three of the following hold: both are still `DESIGNATED`, their power sets intersect, and their windows overlap in the half-open sense — that is, the first window's start lies strictly before the second's end and the second's start lies strictly before the first's end."
    PRD §3.2: "A conflict is refused with `ERR_REPRESENTATIVE_WINDOW_OVERLAP` (HTTP 409)."
    Design: Corner/entities/representative_effective_to_omitted_means_open_ended
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    enrollment = fixtures.create_enrollment(api, brand["id"], registration["id"])
    enrollment = fixtures.activate_enrollment(api, enrollment["id"])

    payload = factories.representative_payload(
        enrollment["id"],
        authority_scope=constants.SCOPE_BOTH,
        effective_from="2026-08-01T00:00:00Z",
        power_of_attorney_ref="POA-OPEN-ENDED",
    )
    del payload["effective_to"]

    representative = validate_success(
        api.create_representative(payload, headers=brand_administrator_headers), 201)

    assertions.assert_common_fields(representative, expected_version=1)
    assert representative["enrollment_id"] == enrollment["id"], (
        f"Expected enrollment_id {enrollment['id']}, got {representative['enrollment_id']}")
    assert representative["authority_scope"] == constants.SCOPE_BOTH, (
        f"Expected authority_scope BOTH, got {representative['authority_scope']}")
    assert instant_without_fraction(representative["effective_from"]) == "2026-08-01T00:00:00", (
        f"Expected effective_from 2026-08-01T00:00:00Z, got {representative['effective_from']}")
    assert representative["effective_to"] is None, (
        f"An omitted effective_to must persist as null, got {representative['effective_to']!r}")
    assert representative["power_of_attorney_ref"] == "POA-OPEN-ENDED", (
        f"Expected power_of_attorney_ref POA-OPEN-ENDED, got {representative['power_of_attorney_ref']!r}")
    assert representative["designation_status"] == constants.DESIGNATION_STATUS_DESIGNATED, (
        f"Expected designation_status DESIGNATED, got {representative['designation_status']}")
    assert representative["revoked_at"] is None, (
        f"Expected revoked_at null on a live designation, got {representative['revoked_at']!r}")

    # Because the window never closes, even a window years later intersects it.
    far_future = factories.representative_payload(
        enrollment["id"],
        authority_scope=constants.SCOPE_SUBMIT_TAKEDOWN,
        effective_from="2030-01-01T00:00:00Z",
        effective_to="2031-01-01T00:00:00Z",
        power_of_attorney_ref="POA-FAR-FUTURE",
    )
    validate_error(
        api.create_representative(far_future, headers=brand_administrator_headers),
        ApiErrorId.REPRESENTATIVE_WINDOW_OVERLAP,
    )


def test_brand_create_ignores_client_supplied_system_fields(api, brand_administrator_headers):
    """Client-supplied id, version, created_at, spend and posture are ignored, not rejected.

    PRD §2.4: "`id` is a server-minted UUID with no type prefix; clients never supply it."
    PRD §2.8: "A client-supplied value for any of them is ignored outright, not rejected."
    PRD §3.1: "A freshly registered brand starts with `status` `DRAFT` and `enforcement_spend_cents` at 0."
    PRD §3.1: "`enforcement_spend_cents` is a ledger mirror, not an input."
    Design: Corner/entities/brand_create_ignores_client_supplied_system_fields_input_ignored
    """
    fixtures.set_clock(api, PINNED_CLOCK)

    smuggled_id = "11111111-1111-4111-8111-111111111111"
    payload = factories.brand_payload(
        name="Acme Tools",
        owner_legal_entity="Acme Tools LLC",
        home_jurisdiction="US",
        authorized_msrp_cents=10000,
        enforcement_budget_cents=500000,
    )
    payload["id"] = smuggled_id
    payload["version"] = 47
    payload["created_at"] = "2000-01-01T00:00:00.000Z"
    payload["enforcement_spend_cents"] = 999999
    payload["status"] = constants.BRAND_STATUS_ENROLLED

    brand = validate_success(api.create_brand(payload, headers=brand_administrator_headers), 201)

    assertions.assert_common_fields(brand, expected_version=1)
    assert brand["id"] != smuggled_id, "A client-supplied id must be ignored, not honoured"
    assert instant_without_fraction(brand["created_at"]) == instant_without_fraction(PINNED_CLOCK), (
        f"Expected created_at read from the logical clock, got {brand['created_at']}")
    assertions.assert_cents(brand["enforcement_spend_cents"], 0, "enforcement_spend_cents")
    assert brand["status"] == constants.BRAND_STATUS_DRAFT, (
        f"A client-supplied posture must be ignored; expected DRAFT, got {brand['status']}")

    # The smuggled id addresses nothing, and the minted one addresses the new row.
    validate_error(
        api.get_brand(smuggled_id, headers=brand_administrator_headers),
        ApiErrorId.BRAND_NOT_FOUND,
    )
    read_back = validate_success(api.get_brand(brand["id"], headers=brand_administrator_headers), 200)
    assert read_back == brand, "The minted id must address the row the create returned"


def test_enrollment_create_with_unknown_marketplace_code_returns_4xx(api, brand_administrator_headers):
    """marketplace_code is a closed enumeration, so an unknown code is a malformed request.

    PRD §3.2: "A `BrandAdministrator` submits the enrolment with `brand_id`, the `asserted_registration_id` naming the registration offered as the enrolment's legal basis, the `marketplace_code` the enrolment covers — one of `AMZ`, `EBY` or `WLM` — the `requested_nice_class` the brand asks the marketplace registry to cover as an integer from 1 through 45, and the `expected_brand_version` described in §2.7."
    PRD §2.9: "**Priority 3** — request shape: required fields present, enumerated values in range, integer amounts not negative, dates and timestamps ISO 8601, matcher sub-scores inside 0 through 1 inclusive, `effective_from` strictly earlier than `effective_to` when both are supplied, and `recorded_on` no later than `expires_on`; else `ERR_INVALID_REQUEST` (400)."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."
    Design: Corner/entities/enrollment_create_with_unknown_marketplace_code_returns_4XX
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])

    payload = factories.enrollment_payload(
        brand["id"], registration["id"], brand["version"], marketplace_code="ZZZ")
    validate_error(
        api.create_enrollment(payload, headers=brand_administrator_headers),
        ApiErrorId.INVALID_REQUEST,
    )

    rows, meta = validate_paginated(
        api.list_enrollments(headers=brand_administrator_headers, brand_id=brand["id"]))
    assert meta["total_count"] == 0, (
        f"A rejected enrolment create must persist nothing, got total_count {meta['total_count']}")
    assert rows == [], f"Expected no enrolment rows, got {rows}"

    unchanged_brand = fixtures.read_brand(api, brand["id"])
    assertions.assert_unchanged(brand, unchanged_brand)
    assert unchanged_brand["status"] == constants.BRAND_STATUS_DRAFT, (
        f"The brand posture must stay DRAFT, got {unchanged_brand['status']}")

    # The same request with a declared code is accepted, isolating the enumeration.
    payload["marketplace_code"] = constants.MARKETPLACE_AMZ
    enrollment = validate_success(
        api.create_enrollment(payload, headers=brand_administrator_headers), 201)
    assert enrollment["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected enrollment_status SUBMITTED, got {enrollment['enrollment_status']}")


def test_takedown_create_with_unknown_evidence_package_returns_not_found(
    api, enforcement_analyst_headers
):
    """A body reference to a package that does not exist is the package family's own 404.

    PRD §2.9: "**Priority 5** — every reference supplied in the body exists, validated in the field order declared by that endpoint's input list, else the matching not-found error (404)."
    PRD §2.4: "References supplied in a request *body* are resolved after the path, in the field order declared for that endpoint, and each missing target yields the not-found error for its own entity family — `ERR_BRAND_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TEST_BUY_NOT_FOUND`, `ERR_EVIDENCE_PACKAGE_NOT_FOUND`, `ERR_TAKEDOWN_NOT_FOUND`, `ERR_COUNTER_NOTICE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CUSTOMS_RECORDATION_NOT_FOUND` or `ERR_INVESTIGATION_NOT_FOUND`, each with HTTP status 404."
    Design: Corner/entities/takedown_create_with_unknown_evidence_package_returns_not_found
    """
    ctx = fixtures.setup_substantiated_claim(api, clock=PINNED_CLOCK)
    claim_before = fixtures.read_claim(api, ctx["claim"]["id"])

    payload = factories.takedown_payload(
        ctx["enrollment"]["id"], ctx["claim"]["id"], NON_EXISTENT_UUID)
    validate_error(
        api.create_takedown(payload, headers=enforcement_analyst_headers),
        ApiErrorId.EVIDENCE_PACKAGE_NOT_FOUND,
    )

    rows, meta = validate_paginated(
        api.list_takedowns(headers=enforcement_analyst_headers, claim_id=ctx["claim"]["id"]))
    assert meta["total_count"] == 0, (
        f"A rejected draft must persist nothing, got total_count {meta['total_count']}")
    assert rows == [], f"Expected no takedown rows, got {rows}"

    claim_after = fixtures.read_claim(api, ctx["claim"]["id"])
    assertions.assert_unchanged(claim_before, claim_after)
    assert claim_after["status"] == constants.CLAIM_STATUS_SUBSTANTIATED, (
        f"Expected the claim to stay SUBSTANTIATED, got {claim_after['status']}")


def test_claim_create_with_two_bad_foreign_keys_returns_brand_not_found(
    api, enforcement_analyst_headers
):
    """With brand_id and listing_id both dangling, the earlier declared field decides the 404.

    PRD §3.5: "An `EnforcementAnalyst` opens a claim by supplying `brand_id`, the `listing_id` of the flagged listing the claim is filed against, the `asserted_registration_id` offered as the claim's legal basis, and the `claimed_violation_type` the brand asserts — one of `COUNTERFEIT`, `COPYRIGHT` or `TRADEMARK` — which also selects the evidence-item set the eventual package must cover."
    PRD §2.9: "**Priority 5** — every reference supplied in the body exists, validated in the field order declared by that endpoint's input list, else the matching not-found error (404)."
    PRD §2.4: "References supplied in a request *body* are resolved after the path, in the field order declared for that endpoint, and each missing target yields the not-found error for its own entity family — `ERR_BRAND_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TEST_BUY_NOT_FOUND`, `ERR_EVIDENCE_PACKAGE_NOT_FOUND`, `ERR_TAKEDOWN_NOT_FOUND`, `ERR_COUNTER_NOTICE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CUSTOMS_RECORDATION_NOT_FOUND` or `ERR_INVESTIGATION_NOT_FOUND`, each with HTTP status 404."
    Design: Corner/entities/claim_create_with_two_bad_foreign_keys_returns_brand_not_found
    """
    ctx = fixtures.setup_flagged_listing(api, clock=PINNED_CLOCK)
    listing_before = fixtures.read_listing(api, ctx["listing"]["id"])

    payload = factories.claim_payload(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, ctx["registration"]["id"],
        claimed_violation_type=constants.VIOLATION_TYPE_COUNTERFEIT)
    validate_error(
        api.create_claim(payload, headers=enforcement_analyst_headers),
        ApiErrorId.BRAND_NOT_FOUND,
    )

    rows, meta = validate_paginated(api.list_claims(headers=enforcement_analyst_headers))
    assert meta["total_count"] == 0, (
        f"A rejected claim create must persist nothing, got total_count {meta['total_count']}")
    assert rows == [], f"Expected no claim rows, got {rows}"

    listing_after = fixtures.read_listing(api, ctx["listing"]["id"])
    assertions.assert_unchanged(listing_before, listing_after)
    assert listing_after["enforcement_status"] == constants.ENFORCEMENT_STATUS_NONE, (
        f"Expected enforcement_status to stay NONE, got {listing_after['enforcement_status']}")


def test_listing_screen_scores_are_server_owned(api, enforcement_analyst_headers):
    """Screening figures cannot be smuggled in: they stay null until the server derives them.

    PRD §3.4: "A new listing starts with `monitor_status` `NEW`, `enforcement_status` `NONE`, `violation_type` `NONE`, and `image_match_score`, `text_match_score`, `price_deviation_factor` and `match_score` all null until the first screening."
    PRD §2.8: "A client-supplied value for any of them is ignored outright, not rejected."
    PRD §3.4: "First, the **price deviation factor** is derived and never supplied."
    PRD §3.4: "With a reference of 10000 cents and a price of 3000 cents, an image sub-score of 0.92 and a text sub-score of 0.88 with no boost accumulate 0.414 plus 0.308 plus 0.14, giving a `match_score` of 0.8620, a `FLAGGED` verdict and a `COUNTERFEIT` classification."
    Design: Corner/entities/listing_screen_scores_are_server_owned_input_ignored
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api, authorized_msrp_cents=10000)
    seller = fixtures.create_seller(api)

    create_payload = factories.listing_payload(brand["id"], seller["id"], price_cents=3000)
    create_payload["image_match_score"] = 0.99
    create_payload["text_match_score"] = 0.99
    create_payload["price_deviation_factor"] = 0.1000
    create_payload["match_score"] = 0.9900
    create_payload["monitor_status"] = constants.MONITOR_STATUS_FLAGGED
    create_payload["violation_type"] = constants.VIOLATION_TYPE_COUNTERFEIT
    create_payload["enforcement_status"] = constants.ENFORCEMENT_STATUS_REMOVED

    listing = validate_success(
        api.create_listing(create_payload, headers=enforcement_analyst_headers), 201)

    assertions.assert_common_fields(listing, expected_version=1)
    for score_field in ("image_match_score", "text_match_score",
                        "price_deviation_factor", "match_score"):
        assert listing[score_field] is None, (
            f"Expected {score_field} null on a never-screened listing, got {listing[score_field]!r}")
    assert listing["monitor_status"] == constants.MONITOR_STATUS_NEW, (
        f"A client-supplied monitor_status must be ignored; expected NEW, got {listing['monitor_status']}")
    assert listing["violation_type"] == constants.VIOLATION_TYPE_NONE, (
        f"Expected violation_type NONE, got {listing['violation_type']}")
    assert listing["enforcement_status"] == constants.ENFORCEMENT_STATUS_NONE, (
        f"Expected enforcement_status NONE, got {listing['enforcement_status']}")

    screen_payload = factories.screen_payload(0.92, 0.88)
    screen_payload["price_deviation_factor"] = 0.1000
    screen_payload["match_score"] = 0.9900
    screened = validate_success(
        api.screen_listing(listing["id"], screen_payload, headers=enforcement_analyst_headers), 200)

    expected_deviation = assertions.price_deviation_factor(10000, 3000)
    assertions.assert_listing_screening(
        screened,
        image=0.92,
        text=0.88,
        deviation=expected_deviation,
        expected_match=assertions.match_score(0.92, 0.88, expected_deviation),
        expected_monitor=constants.MONITOR_STATUS_FLAGGED,
        expected_violation=constants.VIOLATION_TYPE_COUNTERFEIT,
    )
    assertions.assert_score_4dp(screened["price_deviation_factor"], 0.7000, "price_deviation_factor")
    assertions.assert_score_4dp(screened["match_score"], 0.8620, "match_score")
    assertions.assert_common_fields(screened, expected_version=2)
