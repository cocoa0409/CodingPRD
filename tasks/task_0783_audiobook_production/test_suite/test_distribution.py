"""Distribution channels, listings, buffer gaps, and territory rules."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    admin_headers, make_narrator_headers,
    create_listing_payload, create_channel_payload,
    onboard_author, onboard_narrator, new_title, new_channel,
    setup_published_title, setup_published_with_listing, add_sales_event,
)


def test_listing_within_buffer_gap_rejected(api):
    """PRD §3.6: "a new listing is only accepted if its `effective_from` is
    strictly later than the latest `effective_until` among the existing
    non-`WITHDRAWN` listings on that same title-and-channel pair, plus a mandatory
    buffer of `DISTRIBUTION_GAP_DAYS`, which is 1 day. In other words, with a
    prior listing ending 2026-05-31, the earliest allowed next `effective_from`
    is 2026-06-02. A listing that violates this buffer gap is rejected with
    `ERR_LISTING_GAP_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/listing_closed_interval_buffer_gap
    """
    ctx = setup_published_with_listing(
        api, effective_from="2026-05-01", effective_until="2026-05-31"
    )
    payload = create_listing_payload(
        ctx["title"]["id"], ctx["channel"]["id"], territory="US",
        effective_from="2026-06-01", effective_until="2026-06-30",
    )
    resp = api.create_listing(payload, admin_headers())
    validate_error(resp, ApiErrorId.ERR_LISTING_GAP_CONFLICT.value)


def test_listing_after_buffer_gap_accepted(api):
    """PRD §3.6: "with a prior listing ending 2026-05-31, the earliest allowed
    next `effective_from` is 2026-06-02."

    Design: Difficulty/resource_temporal_overlap/listing_closed_interval_buffer_gap
    """
    ctx = setup_published_with_listing(
        api, effective_from="2026-05-01", effective_until="2026-05-31"
    )
    payload = create_listing_payload(
        ctx["title"]["id"], ctx["channel"]["id"], territory="US",
        effective_from="2026-06-02", effective_until="2026-06-30",
    )
    data = validate_success(api.create_listing(payload, admin_headers()), 201)
    assert data["status"] == "ACTIVE"


def test_listing_on_unpublished_title_rejected(api):
    """PRD §3.6: "Listing requires the title to be in `PUBLISHED`; a listing
    against a title that is not published is refused with `ERR_TITLE_NOT_PUBLISHED`."

    Design: Corner/validations/listing_on_unpublished_title_returns_not_published
    """
    author = onboard_author(api)
    title = new_title(api, author["id"])  # DRAFT
    channel = new_channel(api, supported_territories=["US"])
    payload = create_listing_payload(
        title["id"], channel["id"], territory="US",
        effective_from="2026-03-01", effective_until="2026-04-01",
    )
    resp = api.create_listing(payload, admin_headers())
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_PUBLISHED.value)


def test_listing_territory_not_supported_by_channel(api):
    """PRD §3.6: "The chosen `territory` must be served by the channel — it must
    appear in the channel's `supported_territories`". "A territory that the
    channel does not serve, or that lies outside the title's grant, is rejected
    with `ERR_TERRITORY_NOT_SUPPORTED`."

    Design: Corner/validations/listing_territory_not_supported_by_channel
    """
    ctx = setup_published_title(api)  # WORLD-territory title, PUBLISHED
    channel = new_channel(api, supported_territories=["UK"])
    payload = create_listing_payload(
        ctx["title"]["id"], channel["id"], territory="US",
        effective_from="2026-03-01", effective_until="2026-04-01",
    )
    resp = api.create_listing(payload, admin_headers())
    validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_SUPPORTED.value)


def test_withdraw_withdrawn_listing_rejected(api):
    """PRD §3.6: "The operator withdraws an `ACTIVE` listing, moving it
    `ACTIVE → WITHDRAWN`; a withdraw attempt on a listing that is not `ACTIVE` is
    refused with `ERR_LISTING_NOT_ACTIVE`."

    Design: Corner/errors/error_withdraw_non_active_listing_returns_not_active
    """
    ctx = setup_published_with_listing(api)
    validate_success(api.withdraw_listing(ctx["listing"]["id"], admin_headers()), 200)
    resp = api.withdraw_listing(ctx["listing"]["id"], admin_headers())
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE.value)


def test_narrator_cannot_create_channel(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/narrator_cannot_create_channel_returns_unauthorized
    """
    narrator = onboard_narrator(api)
    resp = api.create_channel(create_channel_payload(), make_narrator_headers(narrator["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_list_sales_events_by_listing_returns_children(api):
    """PRD §3.7: "Sales events are immutable once written and can be listed and
    filtered by `listing_id`."

    Design: Corner/endpoints/list_sales_events_by_listing_returns_children
    """
    ctx = setup_published_with_listing(api)
    event = add_sales_event(
        api, ctx["listing"]["id"], units_sold=3, unit_price_cents=1000,
        occurred_at="2026-03-15T00:00:00Z",
    )
    resp = api.list_sales_events(admin_headers(), params={"listing_id": ctx["listing"]["id"]})
    data = validate_success(resp, 200)
    ids = [se["id"] for se in data]
    assert event["id"] in ids
    for se in data:
        assert se["listing_id"] == ctx["listing"]["id"]
