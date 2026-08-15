"""Response envelope, pagination, list filters, FK reverse reachability,
and read-after-write consistency (PRD §2.2, §2.3, §3)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    create_channel,
    create_available_content,
    create_loop,
    tile_loop,
    create_active_campaign,
    factories,
    get_success_data,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]
LICENSING = TEST_USERS["licensing_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]


def test_response_envelope_shape_success_and_error(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`." and "The `response_type` is either
    "object" for a single resource or "array" for a list of resources." For errors:
    "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/endpoints/response_envelope_shape_success_and_error
    """
    create_channel(name="Ch Env")
    resp = api.list_channels(ADMIN)
    body = resp.json()
    assert resp.status_code == 200
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert body["response_type"] == "array"

    missing = api.get_channel("00000000-0000-0000-0000-000000000000", ADMIN)
    err = validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
    raw = missing.json()
    assert raw["response_type"] == "error"
    assert err["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err["message"], str) and err["message"]


def test_list_pagination_defaults_and_bounds(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; when omitted it defaults to 10, and it is bounded below by 1 and above
    by 100. The `offset` parameter specifies how many items to skip and defaults to
    0." and "Paginated list responses carry the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_pagination_defaults_and_bounds
    """
    ids = []
    for name in ("A", "B", "C"):
        campaign = get_success_data(
            api.create_ad_campaign(
                factories.create_ad_campaign_payload(
                    advertiser_name=name, iab_category=f"IAB-{len(ids) + 1}",
                    cpm_cents=100, total_budget_cents=5000, daily_budget_cents=5000,
                ),
                ADOPS,
            )
        )
        ids.append(campaign["id"])

    data, meta = validate_paginated(api.list_ad_campaigns(ADOPS))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(data) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0

    data, meta = validate_paginated(api.list_ad_campaigns(ADOPS, params={"limit": 2}))
    assert len(data) == 2
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_ad_campaigns(ADOPS, params={"limit": 2, "offset": 2})
    )
    assert len(data) == 1
    assert meta["has_more"] is False


def test_list_filter_by_campaign_status(api):
    """PRD §3.5: "Campaigns may be listed filtered by `campaign_status` or
    `iab_category`, and fetched by `campaign_id`."

    Design: Corner/endpoints/list_filter_by_campaign_status
    """
    draft = get_success_data(
        api.create_ad_campaign(
            factories.create_ad_campaign_payload(
                advertiser_name="Drafty", iab_category="IAB-1", cpm_cents=100,
                total_budget_cents=5000, daily_budget_cents=5000,
            ),
            ADOPS,
        )
    )
    active, _creative = create_active_campaign(
        advertiser_name="Live", iab_category="IAB-2", cpm_cents=100,
        total_budget_cents=5000, daily_budget_cents=5000,
    )
    data, meta = validate_paginated(
        api.list_ad_campaigns(ADOPS, params={"campaign_status": "ACTIVE"})
    )
    listed_ids = [row["id"] for row in data]
    assert listed_ids == [active["id"]], (
        f"only the ACTIVE campaign may be listed, got {listed_ids}"
    )
    assert draft["id"] not in listed_ids
    assert meta["total_count"] == 1


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §3.3: "Entries may be listed filtered by `loop_id` or `content_id`" and
    "Loops may be listed filtered by `channel_id`, `loop_status`, `broadcast_date`,
    or `supersedes_loop_id`"; PRD §3.2: "Grants may be listed filtered by
    `channel_id`, `content_id`, or `grant_status`".

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
    """
    channel = create_channel(name="Ch FK")
    content = create_available_content(runtime_seconds=540, title="M540")
    loop = create_loop(channel["id"])
    entries, _ = tile_loop(loop["id"], content["id"], break_durations=())
    entry = entries[0]

    data, _ = validate_paginated(
        api.list_playlist_entries(PROGRAMMER, params={"loop_id": loop["id"]})
    )
    assert [row["id"] for row in data] == [entry["id"]]

    data, _ = validate_paginated(
        api.list_playlist_loops(PROGRAMMER, params={"channel_id": channel["id"]})
    )
    assert [row["id"] for row in data] == [loop["id"]]

    data, meta = validate_paginated(
        api.list_rights_grants(LICENSING, params={"content_id": content["id"]})
    )
    assert data == [], "no grants were created for this content"
    assert meta["total_count"] == 0


def test_mutations_visible_immediately(api):
    """PRD §3.2: "Assets may be listed filtered by `content_status` or `genre`, and
    fetched individually by `content_id`." A created asset is retrievable in the
    next request and a status mutation is visible in the following list call.

    Design: Corner/consistency_model/mutations_visible_immediately
    """
    get_success_data(
        api.create_distributor_platform(
            factories.create_distributor_platform_payload(name="Seed"), ADMIN
        )
    )
    content = get_success_data(
        api.create_content_asset(
            factories.create_content_asset_payload(title="Immediate"), LICENSING
        )
    )
    fetched = get_success_data(api.get_content_asset(content["id"], LICENSING))
    assert fetched["title"] == "Immediate"
    assert fetched["runtime_seconds"] == 540

    get_success_data(api.content_mark_available(content["id"], LICENSING))
    data, _ = validate_paginated(
        api.list_content_assets(LICENSING, params={"content_status": "AVAILABLE"})
    )
    assert content["id"] in [row["id"] for row in data], (
        "mutation must be visible in the following list call"
    )
