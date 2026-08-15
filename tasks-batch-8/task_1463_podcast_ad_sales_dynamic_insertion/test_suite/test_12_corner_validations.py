"""Corner queue B — validations section (11 non-stub instances)."""

from test_helpers import (
    ADOPS,
    FINANCE,
    INGESTION,
    ApiErrorId,
    add_line_item,
    create_ad_copy,
    create_advertiser,
    create_agency,
    create_campaign,
    create_episode,
    create_show,
    deliver_downloads,
    end_campaign,
    get_campaign,
    get_line_item,
    get_show,
    make_advertiser_headers,
    make_agency_headers,
    publish_episode,
    review_ad_copy,
    setup_selling_scenario,
    submit_ad_copy,
    transition_campaign,
    transition_show,
    validate_error,
    validate_paginated,
)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    show = create_show(title="Auth FM", content_category="NEWS", avg_downloads_30d=100)
    # Both X-User-ID and X-User-Role stripped: 401 even on a read endpoint.
    resp = api.get_show(show["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    resp = api.get_show(show["id"], None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_agency_mismatch_returns_forbidden(api):
    """PRD §2.1: "An agency acts on behalf of the advertisers it represents: the advertiser referenced by the request must have `agency_id` equal to `X-User-ID`. If the referenced advertiser is direct or represented by a different agency, the request is rejected with `ERR_AGENCY_MISMATCH` (HTTP 403)."

    Design: Corner/validations/agency_mismatch_returns_forbidden
    """
    ag1 = create_agency(name="AG1", commission_bps=1500)
    ag2 = create_agency(name="AG2", commission_bps=1000)
    advertiser = create_advertiser(name="RepCo", category="FINTECH",
                                   agency_id=ag1["id"])
    # AG2 attempts to create a campaign for an advertiser represented by AG1.
    resp = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "CX",
            "flight_start": "2026-08-01T00:00:00Z",
            "flight_end": "2026-09-01T00:00:00Z",
            "booked_impressions": 10,
            "cpm_cents": 1000,
            "billing_model": "ACTUAL_DELIVERY",
        },
        make_agency_headers(ag2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGENCY_MISMATCH)


def test_campaign_patch_on_active_rejected(api):
    """PRD §3.2: "Flight dates and booking terms may be edited while the campaign is `DRAFT` or `PAUSED` — never from `ACTIVE`, `ENDED`, `RECONCILED`, or `CANCELLED`, where the attempt fails with `ERR_CAMPAIGN_NOT_EDITABLE`."

    Design: Corner/validations/campaign_patch_on_active_rejected
    """
    ctx = setup_selling_scenario(
        with_episode=False, advertiser_name="EditCo", category="FINTECH",
        booked_impressions=10, cpm_cents=1000,
    )
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["status"] == "ACTIVE"
    # Even a version-correct PATCH fails on state grounds.
    resp = api.patch_campaign(
        campaign["id"],
        {"cpm_cents": 2000, "expected_campaign_version": campaign["version"]},
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_EDITABLE)
    assert get_campaign(campaign["id"])["cpm_cents"] == 1000


def test_flight_end_equal_start_rejected(api):
    """PRD §3.2: "`flight_end` must be strictly after `flight_start`; a non-positive window is rejected with `ERR_FLIGHT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/flight_end_equal_start_rejected
    """
    advertiser = create_advertiser(name="FltCo", category="FINTECH")
    resp = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "CF",
            "flight_start": "2026-08-01T00:00:00Z",
            "flight_end": "2026-08-01T00:00:00Z",
            "booked_impressions": 10,
            "cpm_cents": 1000,
            "billing_model": "ACTUAL_DELIVERY",
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_FLIGHT_WINDOW_INVALID)


def test_invoice_create_before_campaign_end_rejected(api):
    """PRD §3.7: "Creation requires the campaign to be `ENDED` — against any other status the request fails with `ERR_CAMPAIGN_NOT_ENDED` — and requires every episode that produced impressions for the campaign to be `MEASURED`, else `ERR_MEASUREMENT_PENDING`."

    Design: Corner/validations/invoice_create_before_campaign_end_rejected
    """
    ctx = setup_selling_scenario(
        with_episode=False, advertiser_name="EarlyCo", category="FINTECH",
        booked_impressions=10, cpm_cents=1000,
    )
    assert ctx["campaign"]["status"] == "ACTIVE"
    resp = api.create_invoice({"campaign_id": ctx["campaign"]["id"]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ENDED)


def test_invoice_create_with_unmeasured_episode_rejected(api):
    """PRD §3.7: "Creation requires the campaign to be `ENDED` — against any other status the request fails with `ERR_CAMPAIGN_NOT_ENDED` — and requires every episode that produced impressions for the campaign to be `MEASURED`, else `ERR_MEASUREMENT_PENDING`."

    Design: Corner/validations/invoice_create_with_unmeasured_episode_rejected
    """
    ctx = setup_selling_scenario(
        advertiser_name="PendCo", category="FINTECH", booked_impressions=5,
        cpm_cents=1000, episode_publish_at="2026-08-01T00:00:00Z",
    )
    add_line_item(ctx, target="show", position="MID_ROLL", reserved_impressions=5,
                  priority=1)
    publish_episode(ctx)
    deliver_downloads(ctx, 5, prefix="P")
    # Campaign ends while the impression-producing episode is still PUBLISHED.
    end_campaign(ctx)
    resp = api.create_invoice({"campaign_id": ctx["campaign"]["id"]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_MEASUREMENT_PENDING)


def test_line_item_activate_with_unapproved_copy_rejected(api):
    """PRD §3.4: "The referenced ad copy must be `APPROVED`, else `ERR_COPY_NOT_APPROVED`."

    Design: Corner/validations/line_item_activate_with_unapproved_copy_rejected
    """
    ctx = setup_selling_scenario(
        advertiser_name="CgCo", category="FINTECH", booked_impressions=10,
        cpm_cents=1000, with_episode=False,
    )
    # The campaign is ACTIVE on the strength of copy 1 (APPROVED); the line
    # item references copy 2, which is only SUBMITTED.
    copy2 = create_ad_copy(ctx["campaign"]["id"], ctx["owner_headers"],
                           kind="PRODUCED_AUDIO", script_text="pending")
    copy2 = submit_ad_copy(copy2["id"], ctx["owner_headers"])
    line_item = add_line_item(ctx, target="show", position="MID_ROLL",
                              reserved_impressions=10, priority=1,
                              ad_copy=copy2, activate=False)
    resp = api.transition_line_item(line_item["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_COPY_NOT_APPROVED)
    assert get_line_item(line_item["id"])["status"] == "DRAFT"


def test_copy_campaign_mismatch_alone_rejected(api):
    """PRD §3.4: "The referenced copy must belong to the same campaign — a copy attached to another campaign fails with `ERR_COPY_CAMPAIGN_MISMATCH` (HTTP 409, since the copy exists but is misattached) — and the `ad_format` must match the copy's `kind` (`HOST_READ` pairs with `HOST_READ_SCRIPT`, `PRODUCED_SPOT` with `PRODUCED_AUDIO`), else `ERR_INVALID_REQUEST`."

    Design: Corner/validations/copy_campaign_mismatch_alone_rejected
    """
    show = create_show(title="Mismatch FM", content_category="NEWS",
                       avg_downloads_30d=10000)
    advertiser = create_advertiser(name="MmCo", category="FINTECH")
    owner = make_advertiser_headers(advertiser["id"])
    c1 = create_campaign(advertiser["id"], name="C1",
                         flight_start="2026-08-01T00:00:00Z",
                         flight_end="2026-09-01T00:00:00Z",
                         booked_impressions=10, cpm_cents=1000)
    c2 = create_campaign(advertiser["id"], name="C2",
                         flight_start="2026-08-01T00:00:00Z",
                         flight_end="2026-09-01T00:00:00Z",
                         booked_impressions=10, cpm_cents=1000)
    copy = create_ad_copy(c1["id"], owner, kind="PRODUCED_AUDIO", script_text="spot")
    # Brand safety is satisfied (no blocked categories), so the referential
    # violation surfaces alone.
    resp = api.create_line_item(
        {
            "campaign_id": c2["id"],
            "show_id": show["id"],
            "ad_format": "PRODUCED_SPOT",
            "position": "MID_ROLL",
            "reserved_impressions": 10,
            "priority": 1,
            "ad_copy_id": copy["id"],
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_COPY_CAMPAIGN_MISMATCH)


def test_suspended_show_blocks_line_item_create(api):
    """PRD §3.4: "The target show's `brand_safety_tier` must not be `SUSPENDED`, else `ERR_SHOW_SUSPENDED`. (This screen also applies at line-item creation.)"

    Design: Corner/validations/suspended_show_blocks_line_item_create
    """
    show = create_show(title="Susp FM", content_category="NEWS",
                       avg_downloads_30d=10000)
    transition_show(show["id"], "SUSPENDED")
    advertiser = create_advertiser(name="SfCo", category="FINTECH")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CS",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    copy = create_ad_copy(campaign["id"], owner, kind="PRODUCED_AUDIO",
                          script_text="spot")
    resp = api.create_line_item(
        {
            "campaign_id": campaign["id"],
            "show_id": show["id"],
            "ad_format": "PRODUCED_SPOT",
            "position": "MID_ROLL",
            "reserved_impressions": 10,
            "priority": 1,
            "ad_copy_id": copy["id"],
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_SHOW_SUSPENDED)
    _items, meta = validate_paginated(
        api.list_line_items(ADOPS, params={"campaign_id": campaign["id"]})
    )
    assert meta["total_count"] == 0, "Rejected create must persist no line item"


def test_promo_event_without_code_rejected(api):
    """PRD §3.6: "Conversion signals arrive through the `Ingestion` identity as attribution events naming the `campaign_id`, a `kind` of `PROMO_CODE` or `PIXEL`, the client-reported `occurred_at` instant, and a `promo_code` that is required exactly when the kind is `PROMO_CODE` and must be absent otherwise — a presence mismatch fails with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/promo_event_without_code_rejected
    """
    advertiser = create_advertiser(name="PcCo", category="FINTECH")
    campaign = create_campaign(advertiser["id"], name="CP",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    resp = api.create_attribution_event(
        {"campaign_id": campaign["id"], "kind": "PROMO_CODE",
         "occurred_at": "2026-08-10T00:00:00Z"},
        INGESTION,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_insufficient_inventory_after_exact_fit(api):
    """PRD §3.4: "**Inventory sufficiency** (run-of-show items): the item's `reserved_impressions` must not exceed the show's `available_impressions` — equality is allowed — else `ERR_INSUFFICIENT_INVENTORY`."

    Design: Corner/validations/insufficient_inventory_after_exact_fit
    """
    ctx = setup_selling_scenario(
        advertiser_name="ExCo", category="FINTECH", content_category="BUSINESS",
        show_avg=1000, booked_impressions=950, cpm_cents=1000,
        episode_publish_at="2026-08-05T00:00:00Z",
    )
    # Exact fit: reserved 950 against available 950 — equality is allowed.
    li1 = add_line_item(ctx, target="show", position="MID_ROLL",
                        reserved_impressions=950, priority=1)
    assert li1["status"] == "ACTIVE"
    show = get_show(ctx["show"]["id"])
    assert show["available_impressions"] == 0
    li2 = add_line_item(ctx, target="show", position="POST_ROLL",
                        reserved_impressions=1, priority=2, activate=False)
    resp = api.transition_line_item(li2["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
    assert get_line_item(li2["id"])["status"] == "DRAFT"
    assert get_show(ctx["show"]["id"])["available_impressions"] == 0
