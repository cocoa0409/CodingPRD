"""Windows competing for the same resource, probed at their exact adjacency points."""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Exclusive territory grants: half-open adjacency and channel disjointness
# ---------------------------------------------------------------------------


def _three_exclusive_agreements_with_one_incumbent_grant():
    """Three rival exclusive agreements on one category, one of them already granted.

    The incumbent holds US / DEPARTMENT over the half-open window that ends 2026-07-01.
    """
    category = create_jersey_category()
    holders = []
    for index, name in enumerate(
        ("Harbor Athletic Ltd", "Cedar Field Apparel", "Northgate Outfitters")
    ):
        licensee = create_active_licensee(
            legal_name=name, contact_email="contracts%d@rivals.example" % index
        )
        agreement = create_draft_agreement(
            licensee["id"], category["id"], exclusivity_mode="EXCLUSIVE"
        )
        holders.append({"licensee": licensee, "agreement": agreement})

    incumbent = grant_territory(
        holders[0]["agreement"]["id"],
        territory_code="US",
        channel_class="DEPARTMENT",
        effective_from="2026-01-01",
        effective_to="2026-07-01",
    )
    assert incumbent["status"] == "GRANTED"
    return {"category": category, "holders": holders, "incumbent": incumbent}


def test_a_window_that_merely_touches_the_incumbent_is_granted(api, ops_headers):
    """PRD §3.3: "Windows that merely touch, where one window's `effective_to` equals the
    other's `effective_from`, do not overlap. A conflict is reported as
    `ERR_TERRITORY_EXCLUSIVITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/exclusive_territory_grants_half_open_adjacency_and_channel_disjointness
    """
    context = _three_exclusive_agreements_with_one_incumbent_grant()
    holders = context["holders"]

    adjacent = validate_success(
        api.create_territory_grant(
            holders[1]["agreement"]["id"],
            territory_grant_payload(
                territory_code="US",
                channel_class="DEPARTMENT",
                effective_from="2026-07-01",
                effective_to="2027-01-01",
            ),
            ops_headers,
        ),
        201,
    )
    assert adjacent["status"] == "GRANTED"
    assert adjacent["exclusivity_mode_snapshot"] == "EXCLUSIVE"
    assert adjacent["effective_from"] == "2026-07-01"

    # One day earlier the windows genuinely intersect.
    overlapping = api.create_territory_grant(
        holders[2]["agreement"]["id"],
        territory_grant_payload(
            territory_code="US",
            channel_class="DEPARTMENT",
            effective_from="2026-06-30",
            effective_to="2026-12-31",
        ),
        ops_headers,
    )
    validate_error(overlapping, ApiErrorId.TERRITORY_EXCLUSIVITY_CONFLICT.value, 409)

    listing = api.list_territory_grants(
        ops_headers, {"territory_code": "US", "status": "GRANTED"}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 2


def test_the_rejected_window_is_free_on_a_disjoint_channel_class(api, ops_headers):
    """PRD §3.3: "A `channel_class` of `ALL` intersects every channel class, and two distinct
    specific classes never intersect each other."

    Design: Difficulty/resource_temporal_overlap/exclusive_territory_grants_half_open_adjacency_and_channel_disjointness
    """
    context = _three_exclusive_agreements_with_one_incumbent_grant()
    challenger = context["holders"][2]["agreement"]["id"]

    refused = api.create_territory_grant(
        challenger,
        territory_grant_payload(
            territory_code="US",
            channel_class="DEPARTMENT",
            effective_from="2026-06-30",
            effective_to="2026-12-31",
        ),
        ops_headers,
    )
    validate_error(refused, ApiErrorId.TERRITORY_EXCLUSIVITY_CONFLICT.value, 409)

    listing = api.list_territory_grants(
        ops_headers, {"territory_code": "US", "status": "GRANTED"}
    )
    _, meta = validate_paginated(listing)
    # The refused request wrote nothing.
    assert meta["total_count"] == 1

    accepted = validate_success(
        api.create_territory_grant(
            challenger,
            territory_grant_payload(
                territory_code="US",
                channel_class="ECOMMERCE",
                effective_from="2026-06-30",
                effective_to="2026-12-31",
            ),
            ops_headers,
        ),
        201,
    )
    assert accepted["status"] == "GRANTED"
    assert accepted["channel_class"] == "ECOMMERCE"

    listing = api.list_territory_grants(
        ops_headers, {"territory_code": "US", "status": "GRANTED"}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# The retailer window buffer at exactly thirty days
# ---------------------------------------------------------------------------


def _licensee_with_one_department_account():
    """One AUTHORIZED department account whose closed window ends 2026-06-30."""
    licensee = create_active_licensee(legal_name="Riverbend Sportswear")
    incumbent = create_authorized_retailer_authorization(
        licensee["id"],
        retailer_name="Harborview Dept",
        channel_class="DEPARTMENT",
        authorized_from="2026-01-01",
        authorized_to="2026-06-30",
    )
    return {"licensee": licensee, "incumbent": incumbent}


def _same_account_request(licensee_id, authorized_from, authorized_to):
    return retailer_authorization_payload(
        licensee_version(licensee_id),
        retailer_name="Harborview Dept",
        channel_class="DEPARTMENT",
        sku_classes=["JERSEY"],
        authorized_from=authorized_from,
        authorized_to=authorized_to,
    )


def test_a_gap_of_exactly_thirty_days_still_conflicts(api, ops_headers):
    """PRD §3.6: "A gap of exactly thirty days still conflicts; a gap of thirty-one days
    does not. A different `retailer_name` or a different `channel_class` never conflicts."

    Design: Difficulty/resource_temporal_overlap/retailer_window_buffer_exactly_thirty_days_still_conflicts
    """
    context = _licensee_with_one_department_account()
    licensee_id = context["licensee"]["id"]
    version_before = licensee_version(licensee_id)

    # 2026-06-30 plus thirty days is 2026-07-30, and the comparison is inclusive.
    response = api.create_retailer_authorization(
        licensee_id, _same_account_request(licensee_id, "2026-07-30", "2026-12-31"), ops_headers
    )
    validate_error(response, ApiErrorId.RETAILER_WINDOW_CONFLICT.value, 409)

    assert licensee_version(licensee_id) == version_before
    listing = api.list_retailer_authorizations(
        ops_headers, {"licensee_id": licensee_id, "retailer_name": "Harborview Dept"}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 1


def test_a_gap_of_thirty_one_days_is_accepted(api, ops_headers):
    """PRD §3.6: "the request is refused when the requested start is at or before the other
    window's end plus thirty days *and* the other window's start is at or before the
    requested end plus thirty days."

    Design: Difficulty/resource_temporal_overlap/retailer_window_buffer_exactly_thirty_days_still_conflicts
    """
    context = _licensee_with_one_department_account()
    licensee_id = context["licensee"]["id"]

    accepted = validate_success(
        api.create_retailer_authorization(
            licensee_id,
            _same_account_request(licensee_id, "2026-07-31", "2026-12-31"),
            ops_headers,
        ),
        201,
    )
    assert accepted["status"] == "PENDING"
    assert accepted["authorized_from"] == "2026-07-31"
    assert accepted["approved_by_user_id"] is None

    listing = api.list_retailer_authorizations(
        ops_headers, {"licensee_id": licensee_id, "retailer_name": "Harborview Dept"}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Off-price capacity counts only the overlapping windows
# ---------------------------------------------------------------------------


def _licensee_with_two_off_price_accounts():
    """Two live off-price accounts whose windows overlap only in June."""
    licensee = create_active_licensee(legal_name="Stonepath Brands")
    alpha = create_authorized_retailer_authorization(
        licensee["id"],
        retailer_name="Outlet Alpha",
        channel_class="OFF_PRICE",
        closeout_allowed=True,
        authorized_from="2026-01-01",
        authorized_to="2026-06-30",
    )
    bravo = create_authorized_retailer_authorization(
        licensee["id"],
        retailer_name="Outlet Bravo",
        channel_class="OFF_PRICE",
        closeout_allowed=True,
        authorized_from="2026-06-01",
        authorized_to="2026-12-31",
    )
    return {"licensee": licensee, "alpha": alpha, "bravo": bravo}


def _off_price_request(licensee_id, retailer_name, authorized_from, authorized_to):
    return retailer_authorization_payload(
        licensee_version(licensee_id),
        retailer_name=retailer_name,
        channel_class="OFF_PRICE",
        sku_classes=["JERSEY"],
        authorized_from=authorized_from,
        authorized_to=authorized_to,
        closeout_allowed=True,
    )


def test_a_window_overlapping_both_incumbents_breaches_the_capacity(api, ops_headers):
    """PRD §3.6: "The off-price capacity rule counts only the same licensee's authorizations
    whose `channel_class` is `OFF_PRICE` and whose `status` is `PENDING` or `AUTHORIZED` and
    whose closed windows overlap the requested closed window; the total, including the row
    being created or approved, must be at most two concurrent off-price accounts."

    Design: Difficulty/resource_temporal_overlap/off_price_aggregate_capacity_counts_only_overlapping_windows
    """
    context = _licensee_with_two_off_price_accounts()
    licensee_id = context["licensee"]["id"]

    # 2026-06-15 to 2026-07-15 meets Alpha in June and Bravo from June onward.
    response = api.create_retailer_authorization(
        licensee_id,
        _off_price_request(licensee_id, "Outlet Charlie", "2026-06-15", "2026-07-15"),
        ops_headers,
    )
    validate_error(response, ApiErrorId.OFF_PRICE_CAPACITY_EXCEEDED.value, 409)

    assert get_authorization(context["alpha"]["id"])["status"] == "AUTHORIZED"
    assert get_authorization(context["bravo"]["id"])["status"] == "AUTHORIZED"
    listing = api.list_retailer_authorizations(
        ops_headers, {"licensee_id": licensee_id, "channel_class": "OFF_PRICE"}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 2


def test_a_window_overlapping_one_incumbent_is_within_the_capacity(api, ops_headers):
    """PRD §3.6: "Each such authorization is individually legal — only the collective count
    breaches — and no thirty-day buffer applies to this aggregate test, which uses plain
    closed-interval overlap."

    Design: Difficulty/resource_temporal_overlap/off_price_aggregate_capacity_counts_only_overlapping_windows
    """
    context = _licensee_with_two_off_price_accounts()
    licensee_id = context["licensee"]["id"]
    version_before = licensee_version(licensee_id)

    refused = api.create_retailer_authorization(
        licensee_id,
        _off_price_request(licensee_id, "Outlet Charlie", "2026-06-15", "2026-07-15"),
        ops_headers,
    )
    validate_error(refused, ApiErrorId.OFF_PRICE_CAPACITY_EXCEEDED.value, 409)

    # Alpha's window has closed by August, so only Bravo is counted here.
    accepted = validate_success(
        api.create_retailer_authorization(
            licensee_id,
            _off_price_request(licensee_id, "Outlet Delta", "2026-08-01", "2026-12-31"),
            ops_headers,
        ),
        201,
    )
    assert accepted["status"] == "PENDING"
    assert accepted["closeout_allowed"] is True

    # Only the accepted request touched the licensee.
    assert licensee_version(licensee_id) == version_before + 1
    listing = api.list_retailer_authorizations(
        ops_headers, {"licensee_id": licensee_id, "channel_class": "OFF_PRICE"}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 3
