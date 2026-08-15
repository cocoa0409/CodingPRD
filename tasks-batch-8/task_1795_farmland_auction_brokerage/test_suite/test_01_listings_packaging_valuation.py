"""Listing assembly, packaging gates, OCC on the listing, and soil-adjusted
valuation reads (PRD §2.7, §2.8, §3.2, §3.3)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_comparable_sale,
    assert_listing,
    assert_money,
    create_disclosure_payload,
    create_rights_payload,
    create_tract_payload,
    create_listing_payload,
    get_success_data,
    is_valid_uuid,
    make_agent_headers,
    make_buyer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


# ────────────────────────── creation & reads ─────────────────────────

def test_listing_created_in_draft_with_agent_from_caller(api):
    """PRD §3.2: "The listing is born in `DRAFT`, and its `agent_id` is set from
    the creating agent's `X-User-ID`, which thereafter defines ownership of the
    listing for every agent-gated operation."

    Design: Corner/entities/listing_create_success_defaults_initial_state
    """
    seller, agent = fx.make_parties()
    res = api.create_listing(
        create_listing_payload(seller["id"]), make_agent_headers(agent["id"])
    )
    listing = validate_success(res, 201)
    assert_listing(listing)
    assert listing["status"] == "DRAFT"
    assert listing["agent_id"] == agent["id"], (
        "agent_id is system-set from the caller's X-User-ID, not from input"
    )
    assert listing["seller_id"] == seller["id"]


def test_tract_create_missing_soil_productivity_rejected(api):
    """PRD §2.8: "**Request schema** — required fields present, types correct,
    enum values valid, ranges respected: acreage figures positive, soil
    productivity greater than zero and at most 100, tillable acres not exceeding
    gross acres, monetary amounts positive where required, dates parseable; a
    survey waiver without consent and a qualification expiry not in the future
    also fail here, all as `ERR_VALIDATION`."

    Design: Corner/entities/tract_create_missing_required_field_returns_invalid_request
    """
    seller, agent = fx.make_parties()
    headers = make_agent_headers(agent["id"])
    listing = fx.create_draft_listing(agent, seller)
    payload = create_tract_payload(listing["id"], listing["version"])
    del payload["soil_productivity_index"]
    res = api.create_tract(payload, headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)
    tracts, meta = validate_paginated(
        api.list_tracts(listing["id"], headers)
    )
    assert tracts == [] and meta["total_count"] == 0, (
        "a schema-rejected request must not create the tract"
    )


def test_get_listing_unknown_id_not_found(api):
    """PRD §2.8: "**Existence** — path identifiers are resolved left to right,
    then body reference identifiers (`seller_id`, `listing_id`, `tract_id`,
    `auction_id`, `closing_id`, and each element of `tract_ids`) are resolved;
    the first missing identifier yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_listing_not_found_returns_not_found
    """
    agent = fx.create_agent()
    res = api.get_listing(NON_EXISTENT_UUID, make_agent_headers(agent["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_comparable_sale_has_no_version_or_updated_at(api):
    """PRD §2.4: "A `ComparableSale` is immutable once created and carries only
    `id` and `created_at`; both `updated_at` and `version` are absent from it."

    Design: Corner/entities/comparable_sale_immutable_record
    """
    comp = fx.post_comparable()
    assert_comparable_sale(comp)


def test_listings_filter_by_seller_paginates(api):
    """PRD §3.2: "Listings may be browsed with optional `seller_id`, `agent_id`,
    and `status` filters plus the standard `limit` and `offset` parameters."
    PRD §2.3: "List responses carry the following fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/listings_filter_and_pagination_envelope
    """
    seller, agent = fx.make_parties()
    seller2 = fx.create_seller(full_name="Seller Two", email="s2@x.com")
    headers = make_agent_headers(agent["id"])
    for title, strategy in (("LA", "WHOLE"), ("LB", "SPLIT"), ("LC", "COMBINATION")):
        fx.create_draft_listing(agent, seller, title=title, packaging_strategy=strategy)
    fx.create_draft_listing(agent, seller2, title="LD")

    page1, meta1 = validate_paginated(
        api.list_listings(headers, params={"seller_id": seller["id"], "limit": 2, "offset": 0})
    )
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert len(page1) == 2
    assert all(row["seller_id"] == seller["id"] for row in page1)

    page2, meta2 = validate_paginated(
        api.list_listings(headers, params={"seller_id": seller["id"], "limit": 2, "offset": 2})
    )
    assert meta2["has_more"] is False and len(page2) == 1
    assert page2[0]["seller_id"] == seller["id"]


def test_request_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request with a missing or unrecognized header is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    seller, agent = fx.make_parties()
    listing = fx.create_draft_listing(agent, seller)
    res = api.get_listing(listing["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


# ────────────────────────── RBAC on assembly ─────────────────────────

def test_buyer_role_cannot_create_tract(api):
    """PRD §2.1: "a caller whose role is not permitted, or who fails the
    ownership check on the target resource, is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD §3.2: "Tracts are added to a `DRAFT` listing by its agent".

    Design: Corner/rbac/rbac_buyer_cannot_create_tract
    """
    seller, agent = fx.make_parties()
    buyer = fx.create_qualified_buyer()
    listing = fx.create_draft_listing(agent, seller)
    res = api.create_tract(
        create_tract_payload(listing["id"], listing["version"]),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_other_agent_cannot_package_listing(api):
    """PRD §3.2: "The caller must be the listing's agent, else `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_non_owner_agent_cannot_package
    """
    seller, agent = fx.make_parties()
    agent2 = fx.create_agent(full_name="Agent Two", license_number="LIC-002")
    fx.post_single_ia_comparable()
    listing = fx.create_draft_listing(agent, seller)
    fx.add_tract(agent, listing["id"])
    res = api.package_listing(listing["id"], make_agent_headers(agent2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


# ────────────────────────── OCC on listing version ───────────────────

def test_second_tract_with_stale_listing_version_rejected(api):
    """PRD §2.7: "Because every tract creation — and every other mutation of the
    listing — increments `Listing.version`, a caller whose last-read version has
    since advanced is acting on a stale view of the tract set and the acreage
    reconciliation; the request is rejected with `ERR_STALE_LISTING_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_listing_version_rejected
    """
    seller, agent = fx.make_parties()
    headers = make_agent_headers(agent["id"])
    listing = fx.create_draft_listing(agent, seller, packaging_strategy="SPLIT")
    first = get_success_data(
        api.create_tract(
            create_tract_payload(
                listing["id"],
                listing["version"],
                gross_acres=60,
                tillable_acres=60,
                min_price=400000,
            ),
            headers,
        )
    )
    assert is_valid_uuid(first["id"])
    # Second add reuses the pre-first-add version: stale by one mutation.
    res = api.create_tract(
        create_tract_payload(
            listing["id"],
            listing["version"],
            tract_number=2,
            gross_acres=40,
            tillable_acres=40,
            soil_productivity_index=75,
            min_price=300000,
        ),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_LISTING_VERSION)


# ────────────────────────── packaging gates ──────────────────────────

def test_tract_acreage_running_sum_and_package_equality(api):
    """PRD §3.2: "Acreage is reconciled incrementally: the sum of existing
    tracts' gross acres plus the new tract's `gross_acres` must not exceed the
    listing's `total_gross_acres`, else `ERR_ACREAGE_MISMATCH`."
    PRD §3.2: "First, acreage: at least one tract must exist, and the tract
    acreage must reconcile to `total_gross_acres` exactly — a listing with no
    tracts, or one whose tract sum is short of or over the total, fails with
    `ERR_ACREAGE_MISMATCH`."

    Design: Corner/validations/acreage_running_sum_and_package_equality
    """
    seller, agent = fx.make_parties()
    headers = make_agent_headers(agent["id"])
    fx.post_single_ia_comparable()
    listing = fx.create_draft_listing(
        agent, seller, packaging_strategy="SPLIT", reserve_price_total=500000
    )
    fx.add_tract(agent, listing["id"], gross_acres=60, tillable_acres=60, min_price=300000)
    over = api.create_tract(
        create_tract_payload(
            listing["id"],
            fx.listing_version(listing["id"], headers),
            tract_number=2,
            gross_acres=50,
            tillable_acres=50,
            soil_productivity_index=75,
            min_price=200000,
        ),
        headers,
    )
    validate_error(over, ApiErrorId.ERR_ACREAGE_MISMATCH)  # 60 + 50 > 100
    short = api.package_listing(listing["id"], headers)
    validate_error(short, ApiErrorId.ERR_ACREAGE_MISMATCH)  # 60 != 100 exactly


def test_package_reserve_below_floor_rejected(api):
    """PRD §3.2: "Second, the reserve floor: `reserve_price_total` must be at
    least 85% of the sum of the `PROVISIONAL` valuations (per §3.3) across all
    tracts; if any tract's comparable set is empty the check aborts with
    `ERR_NO_COMPARABLES`, and a reserve below the floor is rejected with
    `ERR_RESERVE_BELOW_FLOOR`."

    Design: Corner/validations/reserve_below_floor_rejected_at_package
    """
    seller, agent = fx.make_parties()
    fx.post_single_ia_comparable()  # provisional valuation of the tract: 900000
    listing = fx.create_draft_listing(agent, seller, reserve_price_total=700000)
    fx.add_tract(agent, listing["id"], min_price=600000)
    res = api.package_listing(listing["id"], make_agent_headers(agent["id"]))
    # floor is 0.85 x 900000 = 765000; reserve 700000 is below it
    validate_error(res, ApiErrorId.ERR_RESERVE_BELOW_FLOOR)


def test_market_without_declared_rights_rejected(api):
    """PRD §3.4: "The caller must be the listing's agent, and every tract must
    carry at least one `DECLARED` rights disposition — a tract without one fails
    the attempt with `ERR_RIGHTS_NOT_DECLARED`."

    Design: Corner/validations/market_without_rights_returns_rights_not_declared
    """
    seller, agent = fx.make_parties()
    headers = make_agent_headers(agent["id"])
    fx.post_single_ia_comparable()
    listing = fx.create_draft_listing(agent, seller)
    fx.add_tract(agent, listing["id"])
    fx.package_listing(agent, listing["id"])
    res = api.market_listing(listing["id"], headers)
    validate_error(res, ApiErrorId.ERR_RIGHTS_NOT_DECLARED)


def test_duplicate_disclosure_rejected(api):
    """PRD §3.4: "The listing's agent creates it with `tract_id`, `tenant_name`,
    `lease_start_date`, `lease_end_date`, and a positive `annual_rent`; creation
    is permitted only while the listing is `DRAFT` or `PACKAGED` — later
    attempts fail the listing state gate with `ERR_INVALID_LISTING_STATE` — and
    each tract supports at most one disclosure, with a second attempt rejected
    as `ERR_DUPLICATE_RECORD`."

    Design: Corner/validations/duplicate_disclosure_rejected
    """
    seller, agent = fx.make_parties()
    listing = fx.create_draft_listing(agent, seller)
    tract = fx.add_tract(agent, listing["id"])
    fx.create_lease_disclosure(agent, tract["id"])
    res = api.create_disclosure(
        create_disclosure_payload(
            tract["id"], tenant_name="Tenant B",
            lease_end_date="2026-11-01T00:00:00Z", annual_rent=12000,
        ),
        make_agent_headers(agent["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RECORD)


def test_rights_create_while_auction_open_returns_rights_locked(api):
    """PRD §3.4: "While any auction of the listing is `OPEN` or `EXTENDED`,
    rights creation is blocked outright with `ERR_RIGHTS_LOCKED`."
    PRD §2.8: "The server evaluates every request against a fixed validation
    pipeline, and the ordering is observable: a request that would fail two
    checks surfaces the earlier one."

    Design: Corner/validations/rights_create_while_auction_open_returns_rights_locked
    """
    env = fx.setup_open_auction(method="LIVE")
    # A DECLARED disposition already exists (locked by the open), so the
    # duplicate-record gate would also fire; the state gate surfaces first.
    res = api.create_rights(
        create_rights_payload(
            env["tracts"][0]["id"], mineral_rights="RESERVED", wind_rights="RESERVED"
        ),
        make_agent_headers(env["agent"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_RIGHTS_LOCKED)


# ────────────────────────── valuation variants ───────────────────────

def test_valuation_provisional_variant_values(api):
    """PRD §3.3: "The `PROVISIONAL` variant applies no further adjustment: the
    per-acre value is the unweighted mean of the base figures across the whole
    comparable set, with no per-comparable rounding, and the tract's
    `estimated_value` is that mean multiplied by the tract's `gross_acres`,
    rounded half-up to whole dollars."

    Design: Difficulty/dual_variant_calc/valuation_provisional_vs_appraisal_diverge
    """
    seller, agent = fx.make_parties()
    fx.post_standard_ia_comparables()
    listing = fx.create_draft_listing(agent, seller, reserve_price_total=750000)
    tract = fx.add_tract(agent, listing["id"])
    data = validate_success(
        api.get_valuation(tract["id"], make_agent_headers(agent["id"]), variant="PROVISIONAL"),
        200,
    )
    # bases: 9000, 8000, 8000 -> mean 8333.33 per acre over 100 acres
    assert data["tract_id"] == tract["id"]
    assert data["variant"] == "PROVISIONAL"
    assert data["comparable_count"] == 3
    assert_money(data["value_per_acre"], 8333.33, "value_per_acre")
    assert data["estimated_value"] == 833333


def test_valuation_appraisal_variant_diverges(api):
    """PRD §3.3: "The `APPRAISAL` variant adjusts each comparable's base figure
    by two factors before averaging: a tillable factor of 0.85 plus 0.30 times
    the tract's tillable share — its `tillable_acres` divided by its
    `gross_acres` — and a recency factor of 1.0 when the comparable's
    `sale_date` falls on or after the instant twelve months before the logical
    clock, and 0.97 otherwise."
    PRD §3.3: "For identical comparable data the two variants generally produce
    different values; both are legitimate, and the packaging reserve-floor check
    of §3.2 always uses the `PROVISIONAL` variant implicitly, once per tract."

    Design: Difficulty/dual_variant_calc/valuation_provisional_vs_appraisal_diverge
    """
    seller, agent = fx.make_parties()
    fx.post_standard_ia_comparables()
    listing = fx.create_draft_listing(agent, seller, reserve_price_total=750000)
    tract = fx.add_tract(agent, listing["id"])
    headers = make_agent_headers(agent["id"])
    prov = validate_success(api.get_valuation(tract["id"], headers, variant="PROVISIONAL"), 200)
    appr = validate_success(api.get_valuation(tract["id"], headers, variant="APPRAISAL"), 200)
    # tillable factor 1.12 on all comps; 0.97 recency discount on the oldest:
    # adjusted bases 10080, 8960, 8691.20 -> mean 9243.73 per acre
    assert_money(appr["value_per_acre"], 9243.73, "value_per_acre")
    assert appr["estimated_value"] == 924373
    assert appr["estimated_value"] != prov["estimated_value"], (
        "same comparable data, two variants, different dollars"
    )


def test_comparable_window_inclusive_boundary_and_empty_state_set(api):
    """PRD §3.3: "The comparable set for a tract is every `ComparableSale` whose
    `state_code` matches the state code of the tract's listing and whose
    `sale_date` falls inside the trailing twenty-four-month window — from the
    instant twenty-four months before the logical clock up to the logical clock
    itself, both ends inclusive. If that set is empty, the read fails with
    `ERR_NO_COMPARABLES`."

    Design: Corner/calculations/comparable_window_boundary_inclusive_and_empty_set
    """
    seller, agent = fx.make_parties()
    headers = make_agent_headers(agent["id"])
    # Boundary comp: exactly 24 months before the default clock (inclusive);
    # the one-second-older comp is outside the window.
    fx.post_comparable(
        county="Lancaster", state_code="NE", sale_date="2024-08-01T00:00:00Z",
        sale_price_total=800000,
    )
    fx.post_comparable(
        county="Lancaster", state_code="NE", sale_date="2024-07-31T23:59:59Z",
        sale_price_total=500000,
    )
    ne_listing = fx.create_draft_listing(
        agent, seller, title="LNE", county="Lancaster", state_code="NE",
        reserve_price_total=700000,
    )
    ne_tract = fx.add_tract(
        agent, ne_listing["id"], tillable_acres=100, min_price=600000
    )
    ks_listing = fx.create_draft_listing(
        agent, seller, title="LKS", county="Riley", state_code="KS",
        total_gross_acres=50, reserve_price_total=300000,
    )
    ks_tract = fx.add_tract(
        agent, ks_listing["id"], gross_acres=50, tillable_acres=50, min_price=200000
    )

    ne = validate_success(
        api.get_valuation(ne_tract["id"], headers, variant="PROVISIONAL"), 200
    )
    assert ne["comparable_count"] == 1, "boundary comp included, older one excluded"
    assert ne["estimated_value"] == 800000

    res = api.get_valuation(ks_tract["id"], headers, variant="PROVISIONAL")
    validate_error(res, ApiErrorId.ERR_NO_COMPARABLES)
