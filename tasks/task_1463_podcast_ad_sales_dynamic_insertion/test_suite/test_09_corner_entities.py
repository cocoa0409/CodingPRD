"""Corner queue B — entities section (7 non-stub instances)."""

from test_helpers import (
    ADOPS,
    ApiErrorId,
    assert_episode,
    assert_show,
    create_ad_copy,
    create_advertiser,
    create_campaign,
    create_episode,
    create_show,
    get_show,
    ingest_downloads,
    make_advertiser_headers,
    transition_episode,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_show_creation_applies_defaults(api):
    """PRD §3.1: "The producer's brand-safety voice is captured in `blocked_advertiser_categories`, an array of advertiser categories banned from the show that defaults to an empty list when omitted."
    PRD §3.1: "A new show's `brand_safety_tier` starts at `CLEAR`, and with no episodes yet its `forecast_impressions` computes to zero and `reserved_impressions` to zero; `available_impressions` is always the forecast minus the reserved figure."
    PRD §2.5: "`version` is an integer starting at its initial value on creation and incrementing by one on every mutation of the resource, including mutations caused by cascaded recomputes originating elsewhere (for example, when a campaign's delivery counters are recomputed as a side effect of measurement finalization, the campaign's `version` advances and its `updated_at` refreshes)."

    Design: Corner/entities/show_creation_applies_defaults
    """
    resp = api.create_show(
        {"title": "Defaults FM", "content_category": "NEWS", "avg_downloads_30d": 5000},
        ADOPS,
    )
    show = validate_success(resp, expected_status=201)
    assert_show(show)
    assert show["blocked_advertiser_categories"] == [], (
        f"Omitted blocked categories must default to [], got "
        f"{show['blocked_advertiser_categories']}"
    )
    assert show["brand_safety_tier"] == "CLEAR"
    assert show["forecast_impressions"] == 0
    assert show["reserved_impressions"] == 0
    assert show["available_impressions"] == 0


def test_episode_creation_applies_defaults(api):
    """PRD §3.1: "Episodes are created under a show with a `title`, a scheduled `publish_at` instant, and two optional knobs: `measurement_window_days`, the number of days after publish during which downloads count toward final measurement (defaulting to 30, allowed from 1 to 90), and `slot_capacity`, the maximum number of distinct `ACTIVE` line items that may serve into one download of the episode (defaulting to 2, allowed from 1 to 5)."
    PRD §3.1: "A new episode is `SCHEDULED`, and its creation recomputes the owning show's forecast."
    PRD §3.5: "The episode's `provisional_download_count` is the running count of its provisionally qualified downloads."

    Design: Corner/entities/episode_creation_applies_defaults
    """
    show = create_show(title="Defaults 2", content_category="COMEDY",
                       avg_downloads_30d=100)
    resp = api.create_episode(
        {"show_id": show["id"], "title": "E1", "publish_at": "2026-08-05T00:00:00Z"},
        ADOPS,
    )
    episode = validate_success(resp, expected_status=201)
    assert_episode(episode)
    assert episode["measurement_window_days"] == 30
    assert episode["slot_capacity"] == 2
    assert episode["status"] == "SCHEDULED"
    assert episode["provisional_download_count"] == 0
    assert episode["slots_in_use"] == 0
    # The new episode sits inside the inclusive 30-day horizon, so the show's
    # forecast recomputes to floor(100 * 1 * 0.95) == 95.
    show = get_show(show["id"])
    assert show["forecast_impressions"] == 95, (
        f"Episode creation recomputes the forecast to 95, got "
        f"{show['forecast_impressions']}"
    )


def test_get_show_with_unknown_id_not_found(api):
    """PRD §2.8: "5. **Existence** — path identifiers are validated left-to-right, and body foreign keys (`show_id`, `episode_id`, `campaign_id`, `advertiser_id`, `agency_id`, `ad_copy_id`, `invoice_id`) must reference existing resources, else `ERR_NOT_FOUND`."

    Design: Corner/entities/get_show_with_unknown_id_not_found
    """
    resp = api.get_show("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADOPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_campaign_zero_booked_impressions_rejected(api):
    """PRD §3.2: "the contracted `booked_impressions` (strictly greater than zero), the rate `cpm_cents` in cents per thousand qualified impressions (strictly greater than zero), and a `billing_model` of `ACTUAL_DELIVERY` or `BOOKED_GROSS`, which selects the invoicing variant and is immutable after creation."
    PRD §2.8: "14. **Field shape** — malformed or missing required fields, enum values outside the declared sets, out-of-range integers, and duplicate-invoice attempts all surface as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/campaign_zero_booked_impressions_rejected
    """
    advertiser = create_advertiser(name="ZeroCo", category="FINTECH")
    resp = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "Z",
            "flight_start": "2026-08-01T00:00:00Z",
            "flight_end": "2026-09-01T00:00:00Z",
            "booked_impressions": 0,
            "cpm_cents": 1000,
            "billing_model": "ACTUAL_DELIVERY",
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_line_item_dual_target_rejected(api):
    """PRD §3.4: "`AdOps` creates one with the owning `campaign_id`; a target that is exactly one of `show_id` (run-of-show) or `episode_id` (episode-specific) — supplying both or neither fails with `ERR_TARGET_SCOPE_INVALID`; an `ad_format` of `HOST_READ` or `PRODUCED_SPOT`; a `position` of `PRE_ROLL`, `MID_ROLL`, or `POST_ROLL`, which feeds the billing position multiplier; a positive `reserved_impressions` quantity; an integer `priority` used as the serve-time ranking key; and the `ad_copy_id` of the creative to serve."

    Design: Corner/entities/line_item_dual_target_rejected
    """
    show = create_show(title="Scope FM", content_category="NEWS", avg_downloads_30d=1000)
    episode = create_episode(show["id"], title="E1", publish_at="2026-08-05T00:00:00Z")
    advertiser = create_advertiser(name="ScopeCo", category="FINTECH")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CS",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    copy = create_ad_copy(campaign["id"], owner, kind="PRODUCED_AUDIO",
                          script_text="spot")
    # Supplying BOTH show_id and episode_id violates exactly-one-target.
    resp = api.create_line_item(
        {
            "campaign_id": campaign["id"],
            "show_id": show["id"],
            "episode_id": episode["id"],
            "ad_format": "PRODUCED_SPOT",
            "position": "MID_ROLL",
            "reserved_impressions": 10,
            "priority": 1,
            "ad_copy_id": copy["id"],
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_TARGET_SCOPE_INVALID)
    # Supplying neither is equally invalid.
    resp = api.create_line_item(
        {
            "campaign_id": campaign["id"],
            "ad_format": "PRODUCED_SPOT",
            "position": "MID_ROLL",
            "reserved_impressions": 10,
            "priority": 1,
            "ad_copy_id": copy["id"],
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_TARGET_SCOPE_INVALID)


def test_download_computed_and_system_fields(api):
    """PRD §3.5: "Each batch creates `count` Download records whose `listener_key` values are minted as the prefix, a hyphen, and the record's zero-based index within the batch — the first is the prefix followed by `-0`, the last the prefix followed by the index one less than `count`."
    PRD §3.5: "Every download's `qualified_provisional` is set at ingest: true whenever `user_agent_class` is anything other than `BOT`."
    PRD §2.9: "Per-download `qualified_final` and per-impression `billable_final` stay null until that moment."
    PRD §2.5: "Three ingest-side resources are deliberately lighter: Download, Impression, and AttributionEvent carry only `id` and `created_at`."

    Design: Corner/entities/download_computed_and_system_fields
    """
    show = create_show(title="DL FM", content_category="NEWS", avg_downloads_30d=1000)
    episode = create_episode(show["id"], title="E1", publish_at="2026-08-01T00:00:00Z")
    transition_episode(episode["id"], "PUBLISH")
    ingest_downloads(episode["id"], "K", 2, occurred_at="2026-08-02T00:00:00Z",
                     user_agent_class="HUMAN")
    downloads, meta = validate_paginated(
        api.list_episode_downloads(episode["id"], ADOPS)
    )
    assert meta["total_count"] == 2
    keys = sorted(d["listener_key"] for d in downloads)
    assert keys == ["K-0", "K-1"], f"listener_key must be minted as prefix-i: {keys}"
    for row in downloads:
        assert row["qualified_provisional"] is True
        assert row["qualified_final"] is None, (
            "qualified_final stays null until measurement finalization"
        )
        assert "version" not in row and "updated_at" not in row, (
            "Download is an append-only record without version/updated_at"
        )


def test_host_read_copy_requires_show_rejected(api):
    """PRD §3.3: "A host-read script must name the `show_id` of the show whose host will read it; omitting it for that kind fails with `ERR_HOST_READ_REQUIRES_SHOW`."
    PRD §3.3: "New copy starts in `DRAFT` with `revision` set to 1, and `script_text` remains editable while the copy is `DRAFT` or `CHANGES_REQUESTED`."

    Design: Corner/entities/host_read_copy_requires_show_rejected
    """
    advertiser = create_advertiser(name="HostCo", category="CPG_FOOD")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CH",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    resp = api.create_ad_copy(
        {"campaign_id": campaign["id"], "kind": "HOST_READ_SCRIPT",
         "script_text": "host script"},
        owner,
    )
    validate_error(resp, ApiErrorId.ERR_HOST_READ_REQUIRES_SHOW)
    # PRODUCED_AUDIO carries no show binding and is accepted.
    resp = api.create_ad_copy(
        {"campaign_id": campaign["id"], "kind": "PRODUCED_AUDIO",
         "script_text": "produced spot"},
        owner,
    )
    copy = validate_success(resp, expected_status=201)
    assert copy["status"] == "DRAFT"
    assert copy["revision"] == 1
