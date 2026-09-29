"""Resource birth, declared defaults, derived fields and the read surface.

Each test here fixes one resource at the moment it is written, or one shape of the read
surface. The recurring theme is that what a client supplies and what the platform stores
are two different sets: lifecycle fields are stamped, computed money figures start at
zero, omitted optional terms take their declared defaults, and two fields — an engagement
event's `channel` and an attributed sale's `match_type` — are derived from a neighbouring
row even when the request supplies something else.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    CATALOG_OPS,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CROSS_ADVERTISER_REFERENCE,
    ERR_VALIDATION,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    NON_EXISTENT_UUID,
    api_client,
    assert_append_only_record,
    assert_budget_plan_identity,
    assert_common_fields,
    build_active_advertiser,
    build_awarded_auction,
    build_delivering_world,
    build_draft_budget_plan,
    build_engagement_event,
    build_ranked_auction,
    build_second_active_advertiser,
    factories,
    reread_advertiser,
    shift_days,
    shift_hours,
    validate_error,
    validate_paginated,
    validate_success,
)

# --- Figures the recipes below are stated against --------------------------

PLAN_COMMITTED_CENTS = 2000000
PLAN_TRADE_FUND_SHARE_CENTS = 200000
PLAN_CASH_SHARE_CENTS = 1800000
PLAN_WINDOW = ("2026-08-01T00:00:00Z", "2026-10-01T00:00:00Z")

DEFAULT_MIN_STOCK_UNITS = 3
DEFAULT_SELF_SERVE_DAILY_CAP_CENTS = 500000

SALE_CENTS = 50000
SHOPPER_HASH = "sh_1"


# --- Advertiser birth and declared defaults --------------------------------


def test_advertiser_registration_stamps_draft_and_zeroes_every_computed_figure():
    """Registration writes the lifecycle fields itself; none of them is an input.

    PRD 3.1: "The advertiser is born with `onboarding_status` `DRAFT`,
    `suspension_reason` `NONE`, `kyc_document_count` 0, and `credit_exposure_cents` and
    `dispute_credit_balance_cents` both 0."

    PRD 2.4: "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation that touches the row, and `version`, an integer that
    starts at 1 when the row is created and increases by exactly 1 on every mutation of
    that row."

    Design: Corner/entities/advertiser_create_stamps_draft_onboarding_and_zeroed_computed_fields
    """
    advertiser = validate_success(
        api_client.create_advertiser(
            factories.advertiser_payload(
                legal_name="Nordvale Foods LLC",
                brand_code="NRDV",
                service_model="SELF_SERVE",
                credit_limit_cents=50000000,
                self_serve_daily_spend_cap_cents=5000000,
            ),
            NETWORK_ADMIN,
        ),
        expected_status=201,
    )

    assert advertiser["onboarding_status"] == "DRAFT"
    assert advertiser["suspension_reason"] == "NONE"
    assert advertiser["kyc_document_count"] == 0
    assert advertiser["credit_exposure_cents"] == 0
    assert advertiser["dispute_credit_balance_cents"] == 0
    assert advertiser["version"] == 1

    # The commercial terms the request did supply are stored verbatim, so the zeroes
    # above are the lifecycle fields standing apart from the inputs rather than a
    # wholesale failure to read the body.
    assert advertiser["brand_code"] == "NRDV"
    assert advertiser["legal_name"] == "Nordvale Foods LLC"
    assert advertiser["service_model"] == "SELF_SERVE"
    assert advertiser["credit_limit_cents"] == 50000000
    assert_common_fields(advertiser)


def test_omitted_advertiser_terms_take_their_declared_defaults():
    """The two optional commercial terms default to 500,000 cents and 0.0, not to null.

    PRD 3.1: "`managed_service_fee_pct` is a rate between 0.0 and 0.20 inclusive,
    defaulting to 0.0. `self_serve_daily_spend_cap_cents` defaults to 500,000 cents."

    PRD 3.1: "The service-model consistency rule binds both at registration and at
    amendment: a `SELF_SERVE` advertiser must carry a `managed_service_fee_pct` of
    exactly 0.0 and a null `account_manager_user_id`, while a `MANAGED` advertiser must
    carry a non-null `account_manager_user_id`."

    Design: Corner/entities/advertiser_optional_terms_omitted_apply_declared_defaults
    """
    payload = factories.advertiser_payload(
        legal_name="Caldera Beverages Inc",
        brand_code="CLDR",
        service_model="SELF_SERVE",
        credit_limit_cents=200000,
    )
    # Every optional term is left out of the body, so only the declared defaults can
    # supply the stored values.
    payload.pop("self_serve_daily_spend_cap_cents")
    assert "managed_service_fee_pct" not in payload
    assert "parent_advertiser_id" not in payload
    assert "account_manager_user_id" not in payload

    advertiser = validate_success(
        api_client.create_advertiser(payload, ACCOUNT_MANAGER), expected_status=201
    )

    assert (
        advertiser["self_serve_daily_spend_cap_cents"]
        == DEFAULT_SELF_SERVE_DAILY_CAP_CENTS
    )
    assert advertiser["managed_service_fee_pct"] == 0.0
    assert advertiser["credit_limit_cents"] == 200000
    assert advertiser["parent_advertiser_id"] is None
    assert advertiser["account_manager_user_id"] is None


# --- Catalog and plan derivations at creation time -------------------------


def test_product_created_below_the_default_stock_threshold_is_born_out_of_stock():
    """Eligibility is derived at creation, and the threshold it is measured against is 3.

    PRD 3.5: "`min_stock_units_for_serving` is at least 0 and defaults to 3."

    PRD 3.5: "The product's `eligibility_status` at creation is derived rather than
    supplied: `ELIGIBLE` when `in_stock_units` is at least
    `min_stock_units_for_serving`, and `OUT_OF_STOCK` otherwise. `restricted_reason`
    starts at `NONE` and `last_stock_change_at` starts null."

    Design: Corner/entities/catalog_product_eligibility_derived_from_default_min_stock_threshold
    """
    payload = factories.catalog_product_payload(
        sku="SKU-LOWSTOCK-1",
        category_code="FOOTWEAR",
        title="red shoes clearance",
        price_cents=5000,
        in_stock_units=2,
        margin_pct=0.4,
    )
    # The threshold is left out so the default of 3 is what the two units are compared
    # against.
    payload.pop("min_stock_units_for_serving")

    product = validate_success(
        api_client.create_catalog_product(payload, CATALOG_OPS), expected_status=201
    )

    assert product["min_stock_units_for_serving"] == DEFAULT_MIN_STOCK_UNITS
    assert product["in_stock_units"] == 2
    assert product["eligibility_status"] == "OUT_OF_STOCK"
    assert product["restricted_reason"] == "NONE"
    assert product["last_stock_change_at"] is None


def test_plan_creation_derives_the_cash_share_and_leaves_availability_at_the_commitment():
    """The trade-fund share splits the commitment; it does not reduce what is available.

    PRD 3.2: "`cash_share_cents` is `committed_total_cents` less
    `trade_fund_share_cents`."

    PRD 3.2: "`available_cents` is `committed_total_cents` plus `top_up_total_cents`,
    less `reserved_cents`, less `consumed_cents`; it may go negative only through
    over-delivery. No rounding occurs anywhere in this arithmetic."

    PRD 3.2: "The plan is born `DRAFT` with `revision_round` 0, a null `exhausted_at`,
    and a null `submitted_by_user_id` and `approved_by_user_id`."

    Design: Corner/entities/budget_plan_cash_share_and_available_computed_at_creation
    """
    world = build_active_advertiser()
    advertiser = reread_advertiser(world)

    plan = validate_success(
        api_client.create_budget_plan(
            factories.budget_plan_payload(
                advertiser["id"],
                advertiser["version"],
                committed_total_cents=PLAN_COMMITTED_CENTS,
                trade_fund_share_cents=PLAN_TRADE_FUND_SHARE_CENTS,
                window_start_at=PLAN_WINDOW[0],
                window_end_at=PLAN_WINDOW[1],
            ),
            ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    assert plan["plan_status"] == "DRAFT"
    assert plan["cash_share_cents"] == PLAN_CASH_SHARE_CENTS
    assert plan["reserved_cents"] == 0
    assert plan["consumed_cents"] == 0
    assert plan["top_up_total_cents"] == 0
    # Nothing is reserved or consumed yet, so availability is the whole commitment even
    # though 200,000 cents of it is earmarked as trade fund money.
    assert plan["available_cents"] == PLAN_COMMITTED_CENTS
    assert plan["revision_round"] == 0
    assert plan["exhausted_at"] is None
    assert plan["submitted_by_user_id"] is None
    assert plan["approved_by_user_id"] is None
    assert_budget_plan_identity(plan)


# --- The read surface ------------------------------------------------------


def test_reading_a_campaign_that_was_never_persisted_returns_campaign_not_found():
    """A well-formed identifier naming no row is a 404 on the campaign, not a 422.

    PRD 2.12: "10. On every endpoint referencing a campaign: the campaign named in the
    path or in `campaign_id` exists — otherwise `ERR_CAMPAIGN_NOT_FOUND`, 404."

    Design: Corner/entities/get_campaign_with_unknown_id_returns_campaign_not_found
    """
    validate_error(
        api_client.get_campaign(NON_EXISTENT_UUID, NETWORK_ADMIN),
        ERR_CAMPAIGN_NOT_FOUND,
        expected_status=404,
    )


def test_advertiser_listing_reports_the_unpaged_total_and_a_further_page():
    """`total_count` counts the matching rows; `has_more` compares it to the window.

    PRD 2.3: "The `meta` block of a collection response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before the window is applied)
    and `has_more` (true when `offset` plus the number of returned rows is strictly less
    than `total_count`)."

    PRD 2.3: "`limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of
    100. `offset` defaults to 0 when omitted, with a minimum of 0 and no upper bound."

    Design: Corner/entities/advertiser_list_pagination_reports_total_count_and_has_more
    """
    for legal_name, brand_code in (
        ("Nordvale Foods LLC", "NRDV"),
        ("Caldera Beverages Inc", "CLDR"),
        ("Halden Home Goods", "HLDN"),
    ):
        validate_success(
            api_client.create_advertiser(
                factories.advertiser_payload(
                    legal_name=legal_name,
                    brand_code=brand_code,
                    service_model="SELF_SERVE",
                    credit_limit_cents=200000,
                ),
                NETWORK_ADMIN,
            ),
            expected_status=201,
        )

    data, meta = validate_paginated(
        api_client.list_advertisers(NETWORK_ADMIN, limit=2, offset=0)
    )

    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    # 0 + 2 is strictly below 3, so a further page exists.
    assert meta["has_more"] is True

    # The last page carries the remaining row and closes `has_more`, since 2 + 1 is not
    # strictly below 3.
    tail, tail_meta = validate_paginated(
        api_client.list_advertisers(NETWORK_ADMIN, limit=2, offset=2)
    )
    assert len(tail) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False


# --- Refusals at the door --------------------------------------------------


def test_advertiser_registration_without_a_brand_code_is_refused_and_persists_nothing():
    """`brand_code` is required, and the refused request leaves the collection empty.

    PRD 3.1: "Registration requires `legal_name`, `brand_code`, `service_model` and
    `credit_limit_cents`."

    PRD 2.12: "5. On every creating, replacing and patching request: the body carries
    every required input field with its declared type, every enum-typed field carries a
    declared member of that enum, and every integer cent field meets its stated minimum —
    otherwise `ERR_VALIDATION`, 422."

    Design: Corner/entities/advertiser_create_missing_required_brand_code_returns_422
    """
    payload = factories.advertiser_payload(
        legal_name="Nordvale Foods LLC",
        service_model="SELF_SERVE",
        credit_limit_cents=200000,
    )
    payload.pop("brand_code")

    validate_error(
        api_client.create_advertiser(payload, NETWORK_ADMIN),
        ERR_VALIDATION,
        expected_status=422,
    )

    _, meta = validate_paginated(api_client.list_advertisers(NETWORK_ADMIN))
    assert meta["total_count"] == 0


def test_advertiser_registration_with_an_undeclared_service_model_is_refused():
    """An enum-typed field takes only its declared members; it is not coerced to a default.

    PRD 3.1: "`service_model` is either `SELF_SERVE` or `MANAGED` and defaults to
    `SELF_SERVE` when omitted."

    PRD 2.12: "5. On every creating, replacing and patching request: the body carries
    every required input field with its declared type, every enum-typed field carries a
    declared member of that enum, and every integer cent field meets its stated minimum —
    otherwise `ERR_VALIDATION`, 422."

    Design: Corner/entities/advertiser_create_invalid_enum_service_model_returns_422
    """
    validate_error(
        api_client.create_advertiser(
            factories.advertiser_payload(
                legal_name="Nordvale Foods LLC",
                brand_code="NRDV",
                service_model="HYBRID",
                credit_limit_cents=200000,
            ),
            NETWORK_ADMIN,
        ),
        ERR_VALIDATION,
        expected_status=422,
    )

    _, meta = validate_paginated(api_client.list_advertisers(NETWORK_ADMIN))
    assert meta["total_count"] == 0


def test_campaign_pointed_at_another_advertisers_plan_is_refused_as_a_cross_reference():
    """The plan exists, so the refusal is about ownership rather than about existence.

    PRD 3.3: "The funding plan must belong to the same advertiser named on the
    campaign."

    PRD 2.12: "67. On campaign creation, line item creation, product assignment
    creation, attributed sale ingestion and invoice creation: all cross-referenced rows
    resolve to the same advertiser — a campaign's funding plan belongs to the campaign's
    advertiser, a line item's campaign belongs to the acting advertiser, an attributed
    sale's engagement belongs to the same line item, and an invoice's fund account
    belongs to the invoice's advertiser — otherwise `ERR_CROSS_ADVERTISER_REFERENCE`,
    422."

    Design: Corner/entities/campaign_funded_by_another_advertisers_plan_returns_cross_advertiser_reference
    """
    # The plan owner is built first so the plan builder, which reads the advertiser it
    # bills, lands the money on the advertiser the campaign will not name.
    world = build_active_advertiser()
    build_second_active_advertiser(world)
    build_draft_budget_plan(
        world,
        committed_total_cents=PLAN_COMMITTED_CENTS,
        trade_fund_share_cents=0,
        window_start_at=PLAN_WINDOW[0],
        window_end_at=PLAN_WINDOW[1],
    )

    plan_owner = world["advertiser"]
    other_advertiser = world["other_advertiser"]
    assert world["plan"]["advertiser_id"] == plan_owner["id"]
    assert other_advertiser["id"] != plan_owner["id"]

    payload = factories.campaign_payload(
        other_advertiser["id"],
        world["plan"]["id"],
        name="Cross Owner Campaign",
        allocated_budget_cents=1000000,
        daily_cap_cents=200000,
    )
    # The campaign's own flight sits inside the plan's window and its cap sits inside
    # both the allocation and the advertiser's self-serve cap, so neither the window
    # check nor the cap check can be what refuses this request.
    assert payload["flight_start_at"] >= PLAN_WINDOW[0]
    assert payload["flight_end_at"] <= PLAN_WINDOW[1]
    assert payload["daily_cap_cents"] <= payload["allocated_budget_cents"]
    assert (
        payload["daily_cap_cents"] <= other_advertiser["self_serve_daily_spend_cap_cents"]
    )

    validate_error(
        api_client.create_campaign(payload, ACCOUNT_MANAGER),
        ERR_CROSS_ADVERTISER_REFERENCE,
        expected_status=422,
    )

    _, meta = validate_paginated(api_client.list_campaigns(NETWORK_ADMIN))
    assert meta["total_count"] == 0


# --- Fields derived from a neighbouring row --------------------------------


def test_engagement_channel_is_taken_from_the_slot_and_not_from_the_request():
    """An inconsistent supplied `channel` is corrected to the auctioned slot's channel.

    PRD 3.6: "`channel` must be supplied, but the persisted value is always derived from
    the slot the winning line item occupies rather than taken from the request, so an
    inconsistent supplied value is silently corrected to the slot's `channel`."

    PRD 3.6: "`billable_cents` is 0 at the moment the event is recorded and is populated
    when the auction settles; recording an engagement therefore moves neither
    `spend_cents` nor `delivered_spend_cents` on its own."

    PRD 2.4: "Two resources are deliberately append-only and therefore carry **only**
    `id` and `created_at` — they have no `updated_at` field and no `version` field, and
    no endpoint accepts a version expectation against them: the auction bid ledger rows
    and the engagement event rows."

    Design: Corner/entities/engagement_event_channel_is_copied_from_slot_and_input_ignored
    """
    world = build_delivering_world()
    build_awarded_auction(world)
    assert world["slot"]["channel"] == "ONSITE"
    assert world["auction"]["winning_line_item_id"] == world["line_item"]["id"]

    event = validate_success(
        api_client.create_engagement_event(
            factories.engagement_event_payload(
                world["line_item"]["id"],
                world["auction"]["id"],
                world["product"]["id"],
                event_type="IMPRESSION",
                occurred_at=shift_hours(world["clock"], 12),
                shopper_hash=SHOPPER_HASH,
                channel="OFFSITE",
            ),
            AUCTION_SERVICE,
        ),
        expected_status=201,
    )

    # The request said OFFSITE; the slot the winner occupies says ONSITE, and the slot
    # wins.
    assert event["channel"] == "ONSITE"
    assert event["event_type"] == "IMPRESSION"
    assert event["line_item_id"] == world["line_item"]["id"]
    assert event["billable_cents"] == 0
    assert_append_only_record(event)


def test_attributed_sale_match_type_comes_from_the_credited_engagement():
    """The supplied `match_type` is discarded; a credited click yields `CLICK_THROUGH`.

    PRD 3.7: "`match_type` must be supplied but the persisted value is always derived:
    it is `CLICK_THROUGH` when the credited engagement's `event_type` is `CLICK` and
    `VIEW_THROUGH` for an `IMPRESSION` or `OFFSITE_VIEW`. `restated` starts false.
    `attribution_model_applied` records which of the campaign's two models was in force
    when the credit was computed, and it is never taken from the request."

    PRD 3.7: "`within_window` is true when the sale's `occurred_at` is at or after the
    engagement's `occurred_at` **and** the elapsed interval between them is strictly
    less than the window length."

    PRD 3.7: "Under `LAST_TOUCH` the credit goes entirely to one engagement: the
    candidate with the greatest `occurred_at`, with ties broken by `event_type` in the
    fixed precedence `CLICK` first, then `OFFSITE_VIEW`, then `IMPRESSION`, and any
    remaining tie broken by ascending `created_at`. The credited engagement's row
    receives `attribution_weight` 1.0 and every other candidate's row receives 0.0."

    PRD 3.7: "In both variants `attributed_credit_cents` is `sale_cents` multiplied by
    the row's `attribution_weight`, rounded half-up to whole cents."

    Design: Corner/entities/attributed_sale_match_type_derived_from_engagement_event_type_input_ignored
    """
    world = build_delivering_world()
    assert world["campaign"]["attribution_model"] == "LAST_TOUCH"
    assert world["campaign"]["attribution_window_days"] == 14
    build_awarded_auction(world)

    # One shopper, one product, an impression and then a click. Under last-touch the
    # later click is the credited engagement.
    build_engagement_event(
        world,
        event_type="IMPRESSION",
        occurred_at=shift_hours(world["clock"], 12),
        shopper_hash=SHOPPER_HASH,
    )
    build_engagement_event(
        world,
        event_type="CLICK",
        occurred_at=shift_hours(world["clock"], 13),
        shopper_hash=SHOPPER_HASH,
    )
    click = world["engagement"]
    assert click["event_type"] == "CLICK"

    sale = validate_success(
        api_client.create_attributed_sale(
            factories.attributed_sale_payload(
                click["id"],
                world["product"]["id"],
                sale_cents=SALE_CENTS,
                occurred_at=shift_days(world["clock"], 1),
                retail_order_ref="RO-1001",
                match_type="VIEW_THROUGH",
            ),
            MEASUREMENT_ANALYST,
        ),
        expected_status=201,
    )

    # The request declared VIEW_THROUGH; the credited engagement is a click.
    assert sale["match_type"] == "CLICK_THROUGH"
    assert sale["attribution_model_applied"] == "LAST_TOUCH"
    # `line_item_id` is not supplied either — it is copied from the engagement.
    assert sale["line_item_id"] == world["line_item"]["id"]
    assert sale["within_window"] is True
    assert sale["restated"] is False
    assert sale["attribution_weight"] == 1.0
    assert sale["attributed_credit_cents"] == SALE_CENTS


def test_a_bid_ledger_row_reads_back_with_no_version_and_no_updated_at():
    """The ranking pass writes evidence, not a mutable row.

    PRD 3.6: "Bid rows carry only `id` and `created_at` from the common fields; they
    have no `updated_at` and no `version` and are never mutated after the award assigns
    their outcome."

    PRD 3.6: "Each bid row carries `auction_event_id`, `line_item_id`, `raw_bid_cents`
    copied from the line item's `bid_cents`, the `relevance_score` and
    `quality_adjusted_score` computed for this auction, a `rank`, an `outcome` and a
    `filter_reason`."

    PRD 3.6: "A candidate that survives all five clauses carries `filter_reason` `NONE`."

    Design: Corner/entities/auction_bid_ledger_row_is_immutable_and_exposes_no_version
    """
    world = build_delivering_world()
    build_ranked_auction(world)

    assert len(world["bids"]) == 1
    listed = world["bids"][0]

    bid = validate_success(api_client.get_auction_bid(listed["id"], MEASUREMENT_ANALYST))

    assert_append_only_record(bid)
    assert "version" not in bid
    assert "updated_at" not in bid
    assert bid["auction_event_id"] == world["auction"]["id"]
    assert bid["line_item_id"] == world["line_item"]["id"]
    assert bid["raw_bid_cents"] == world["line_item"]["bid_cents"]
    # The only candidate survives every clause of the filter chain, so it is ranked
    # first and carries no filter reason.
    assert bid["rank"] == 1
    assert bid["filter_reason"] == "NONE"
