"""Authentication, role admission, and the eleven entity-specific not-found codes."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_case,
    create_case_payload,
    create_package,
    file_document,
    make_bpo_vendor_headers,
    review_document_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
AGENT = TEST_USERS["listing_agent_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]
ANALYST2 = TEST_USERS["second_analyst_headers"]
UNDERWRITER = TEST_USERS["mi_underwriter_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

MISSING_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_a_request_without_a_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must carry two
    headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the
    capacity in which that principal is acting. If either header is absent, present but
    empty, or `X-User-Role` carries a string that is not one of the seven role names
    below, the request is refused with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/errors/unauthenticated_missing_user_id_header_returns_401
    """
    headers = {"X-User-Role": "Negotiator", "Content-Type": "application/json"}

    validate_error(
        api.create_case(
            create_case_payload(property_address="50 Bramble Ct, Reno NV"), headers
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    _, meta = validate_paginated(api.list_cases(NEG))
    assert meta["total_count"] == 0, "an unauthenticated write must persist nothing"


def test_unknown_case_id_is_case_not_found(api):
    """PRD §2.5: "Where a path carries more than one identifier, the identifiers are
    resolved strictly left to right, and the first one that fails to resolve determines
    the error."
    PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/case_not_found_returns_404
    """
    validate_error(api.get_case(MISSING_ID, NEG), ApiErrorId.ERR_CASE_NOT_FOUND.value)


def test_unknown_package_id_is_package_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/package_not_found_returns_404
    """
    validate_error(
        api.submit_hardship_package(MISSING_ID, NEG),
        ApiErrorId.ERR_PACKAGE_NOT_FOUND.value,
    )


def test_unknown_document_id_is_document_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/document_not_found_returns_404
    """
    validate_error(
        api.review_document(MISSING_ID, review_document_payload("VERIFY"), ANALYST),
        ApiErrorId.ERR_DOCUMENT_NOT_FOUND.value,
    )


def test_unknown_listing_id_is_listing_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/listing_not_found_returns_404
    """
    validate_error(
        api.record_price_reduction(MISSING_ID, {"new_list_price_cents": 24_000_000}, AGENT),
        ApiErrorId.ERR_LISTING_NOT_FOUND.value,
    )


def test_unknown_offer_id_is_offer_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/offer_not_found_returns_404
    """
    validate_error(
        api.submit_offer(MISSING_ID, NEG), ApiErrorId.ERR_OFFER_NOT_FOUND.value
    )


def test_unknown_valuation_id_is_valuation_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/valuation_not_found_returns_404
    """
    vendor_headers = make_bpo_vendor_headers("1f2e3d4c-5b6a-4798-8899-aabbccddeeff")

    validate_error(
        api.record_valuation_value(MISSING_ID, {"value_cents": 25_200_000}, vendor_headers),
        ApiErrorId.ERR_VALUATION_NOT_FOUND.value,
    )


def test_unknown_dispute_id_is_dispute_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/dispute_not_found_returns_404
    """
    validate_error(
        api.adjudicate_dispute(MISSING_ID, {"resolution": "DENIED"}, ANALYST2),
        ApiErrorId.ERR_DISPUTE_NOT_FOUND.value,
    )


def test_unknown_lien_id_is_lien_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/lien_not_found_returns_404
    """
    validate_error(
        api.send_lien_demand(MISSING_ID, {"demand_cents": 100_000}, NEG),
        ApiErrorId.ERR_LIEN_NOT_FOUND.value,
    )


def test_unknown_mi_claim_id_is_mi_claim_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/mi_claim_not_found_returns_404
    """
    validate_error(
        api.decide_mi_claim(MISSING_ID, {"outcome": "DECLINE"}, UNDERWRITER),
        ApiErrorId.ERR_MI_CLAIM_NOT_FOUND.value,
    )


def test_unknown_approval_letter_id_is_approval_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/approval_not_found_returns_404
    """
    validate_error(
        api.close_approval_letter(MISSING_ID, NEG),
        ApiErrorId.ERR_APPROVAL_NOT_FOUND.value,
    )


def test_unknown_extension_request_id_is_extension_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_CASE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_LIEN_NOT_FOUND`, `ERR_MI_CLAIM_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, and
    `ERR_EXTENSION_NOT_FOUND`. All eleven answer with HTTP 404."

    Design: Corner/errors/extension_not_found_returns_404
    """
    validate_error(
        api.decide_extension_request(MISSING_ID, {"outcome": "DENY"}, ANALYST2),
        ApiErrorId.ERR_EXTENSION_NOT_FOUND.value,
    )


def test_a_negotiator_may_not_review_the_documentation_it_filed(api):
    """PRD §2.1: "Once the headers are accepted, the role is checked against the set of
    roles the addressed endpoint admits; a role outside that set yields
    `ERR_UNAUTHORIZED` and HTTP 403."
    PRD §3.2: "A `ServicerAnalyst` reviews a filed document by supplying an `outcome` —
    one of `VERIFY`, `REJECT` or `REVOKE` — and, optionally, a free-text `note`."

    Design: Corner/rbac/negotiator_cannot_review_seller_documents
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    package = create_package(case["id"])
    document = file_document(package["id"], "HARDSHIP_LETTER")

    validate_error(
        api.review_document(document["id"], review_document_payload("VERIFY"), NEG),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    documents = validate_success(api.list_package_documents(package["id"], NEG), 200)
    assert documents[0]["status"] == "PENDING"
    stored_package = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored_package["verified_document_count"] == 0


def test_the_platform_admin_may_not_open_a_case(api):
    """PRD §2.1: "**`PlatformAdmin`** — the operations role. It registers vendor firms and
    drives the logical clock. It holds no business decision rights on any case; it may
    read across the system but may not decide anything on a file."
    PRD §2.1: "Once the headers are accepted, the role is checked against the set of
    roles the addressed endpoint admits; a role outside that set yields
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/platform_admin_cannot_create_a_case
    """
    validate_error(
        api.create_case(
            create_case_payload(property_address="55 Gorsehill Ln, Reno NV"), ADMIN
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    _, meta = validate_paginated(api.list_cases(NEG))
    assert meta["total_count"] == 0
