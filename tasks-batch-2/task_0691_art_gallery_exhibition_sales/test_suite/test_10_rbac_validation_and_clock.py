"""Cross-cutting global rules: validation ordering (existence beats state), RBAC
role denials, authentication, pagination bounds, body well-formedness, the payout
funds guard, and the logical-clock default."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_gallery, create_artist, create_artwork,
    make_unknown_role_headers,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]
ARTIST = TEST_USERS["artist_headers"]

NONEXISTENT = "00000000-0000-4000-8000-000000000000"


class TestValidationOrdering:
    def test_settle_nonexistent_sale_returns_not_found_not_invalid_state(self, api):
        """PRD §2.6: "(3) existence of every referenced resource in scope, failing
        with `ERR_NOT_FOUND`; (4) well-formedness of the request body ... ; (5) the
        target resource being in a legal state for the requested transition,
        failing with `ERR_INVALID_STATE`".
        PRD §2.5: "that check happens before any state, concurrency, or business
        rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_settle
        """
        create_gallery()  # gallery exists; the probed sale does not.
        resp = api.settle_sale(NONEXISTENT, SALES)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_void_nonexistent_sale_returns_not_found(self, api):
        """PRD §2.6: "When several conditions could reject the same request, they
        are evaluated in a fixed priority order so that the returned error is
        deterministic."
        PRD §2.5: "The first reference that does not resolve within scope yields
        `ERR_NOT_FOUND`, and that check happens before any state, concurrency, or
        business rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_settle
        """
        create_gallery()
        # Voiding requires a non-terminal state, but existence is checked first.
        resp = api.void_sale(NONEXISTENT, SALES)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestRbacAndAuth:
    def test_sales_associate_cannot_create_gallery(self, api):
        """PRD §2.1: "When the headers are well formed but the named role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN`."
        PRD §3.1: "Everything begins with a gallery, created by a `GalleryAdmin`".

        Design: Corner/rbac/sales_associate_cannot_create_gallery
        """
        resp = api.create_gallery(f.create_gallery_payload(name="Nope"), SALES)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_artist_cannot_post_payout(self, api):
        """PRD §2.1: "An `Artist` has read-only visibility".
        PRD §3.10: "a `GalleryAdmin` creates a payout by supplying the `artist_id`
        and a `requested_cents`".

        Design: Corner/rbac/artist_cannot_post_payout
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        resp = api.create_payout(
            f.create_payout_payload(artist["id"], 1000), ARTIST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
        the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        gallery = create_gallery()
        resp = api.get_gallery(gallery["id"], make_unknown_role_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestEntityCreationAndPagination:
    def test_create_gallery_returns_201_with_fields(self, api):
        """PRD §3.1: "Everything begins with a gallery, created by a `GalleryAdmin`
        who supplies a `name`, a two-letter uppercase `home_state_code` identifying
        the state the gallery sells from, and a `sales_tax_rate_bps` giving the
        default sales-tax rate in basis points (so 875 means 8.75%)".
        PRD §2.7: "At server startup the clock reads exactly `2026-04-01T00:00:00Z`".

        Design: Corner/entities/create_gallery_returns_201_with_all_fields
        """
        resp = api.create_gallery(f.create_gallery_payload(
            name="Fresh", home_state_code="CA", sales_tax_rate_bps=875), ADMIN)
        gallery = validate_success(resp, 201)
        assert gallery["home_state_code"] == "CA"
        assert gallery["sales_tax_rate_bps"] == 875
        assert gallery["clock_utc"] == "2026-04-01T00:00:00Z"

    def test_list_artworks_pagination_envelope(self, api):
        """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope, where `total_count` is
        the total number of matching items before pagination and `has_more`
        indicates whether items remain beyond the current page."

        Design: Corner/entities/list_artworks_pagination_envelope
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        create_artwork(gallery["id"], artist["id"], title="W1",
                       list_price_cents=100_000, insured_value_cents=100_000)
        create_artwork(gallery["id"], artist["id"], title="W2",
                       list_price_cents=100_000, insured_value_cents=100_000)
        resp = api.list_artworks(ADMIN, params={"gallery_id": gallery["id"],
                                                "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, "two artworks match before pagination"
        assert meta["has_more"] is True, "more items remain beyond a limit-1 page"

    def test_pagination_limit_out_of_bounds_rejected(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
        may not be below 1, and may not exceed 100. ... A `limit` below 1 or above
        100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`."

        Design: Corner/entities/pagination_limit_out_of_bounds_rejected
        """
        gallery = create_gallery()
        resp = api.list_artworks(ADMIN, params={"gallery_id": gallery["id"],
                                                "limit": 101, "offset": 0})
        validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)

    def test_exhibition_closes_before_opens_rejected(self, api):
        """PRD §3.3: "an `opens_utc` (the inclusive lower bound of the run window),
        and a `closes_utc` (the exclusive upper bound), where `closes_utc` must be
        strictly after `opens_utc`."

        Design: Corner/entities/exhibition_closes_before_opens_rejected
        """
        gallery = create_gallery()
        resp = api.create_exhibition(f.create_exhibition_payload(
            gallery["id"], title="Bad", wall_capacity=2,
            opens_utc="2026-05-10T00:00:00Z",
            closes_utc="2026-05-01T00:00:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_sale_missing_required_field_rejected(self, api):
        """PRD §2.6: "(4) well-formedness of the request body — required fields
        present, enum values legal, numeric constraints honored — failing with
        `ERR_INVALID_REQUEST`".
        PRD §3.4: "a `gross_amount_cents` (the negotiated price before discount,
        tax, and shipping, strictly greater than zero)".

        Design: Corner/entities/create_sale_missing_required_field_returns_invalid_request
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        artwork = create_artwork(gallery["id"], artist["id"], title="Rf W",
                                 list_price_cents=100_000, insured_value_cents=100_000)
        # Omit required gross_amount_cents.
        resp = api.create_sale({
            "gallery_id": gallery["id"], "artwork_id": artwork["id"],
            "buyer_name": "X", "buyer_state_code": "CA"}, SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestPayoutGuardAndClock:
    def test_payout_with_zero_payable_rejected(self, api):
        """PRD §3.10: "The payout is refused with `ERR_ARTIST_SUSPENDED` if the
        artist is `SUSPENDED`, and with `ERR_NO_PAYABLE_BALANCE` if the artist's
        `ledger_payable_cents` is 0 at creation."

        Design: Corner/validations/payout_with_zero_payable_rejected
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])  # no settled sales -> payable 0.
        resp = api.create_payout(
            f.create_payout_payload(artist["id"], 100_000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_PAYABLE_BALANCE.value)

    def test_clock_default_before_any_set(self, api):
        """PRD §2.7: "At server startup the clock reads exactly
        `2026-04-01T00:00:00Z`, and it stays at that default until a `GalleryAdmin`
        sets it; the system never falls back to real time."

        Design: Corner/cross_cutting_complexity_layers/scheduled_clock_default_before_set
        """
        resp = api.create_gallery(f.create_gallery_payload(name="Ck"), ADMIN)
        gallery = validate_success(resp, 201)
        assert gallery["clock_utc"] == "2026-04-01T00:00:00Z", \
            "a fresh gallery's clock reads the fixed default, not wall-clock"
