"""Corner queue B — rbac section (3 non-stub instances)."""

from test_helpers import (
    ADOPS,
    ApiErrorId,
    create_ad_copy,
    create_advertiser,
    create_campaign,
    create_show,
    get_ad_copy,
    get_campaign,
    make_advertiser_headers,
    make_show_producer_headers,
    submit_ad_copy,
    validate_error,
)


def test_advertiser_role_cannot_create_shows(api):
    """PRD §2.1: "A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST | `/adnet/shows` | Create a show | AdOps"

    Design: Corner/rbac/advertiser_role_cannot_create_shows
    """
    advertiser = create_advertiser(name="RoleCo", category="FINTECH")
    resp = api.create_show(
        {"title": "Nope", "content_category": "NEWS", "avg_downloads_30d": 1},
        make_advertiser_headers(advertiser["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_show_producer_cannot_review_produced_audio(api):
    """PRD §3.3: "Review splits by creative kind: `HOST_READ_SCRIPT` is reviewed by the `ShowProducer` of the copy's show, while `PRODUCED_AUDIO` is reviewed by `AdOps`."

    Design: Corner/rbac/show_producer_cannot_review_produced_audio
    """
    show = create_show(title="Prod FM", content_category="COMEDY",
                       avg_downloads_30d=100)
    advertiser = create_advertiser(name="PrCo", category="FINTECH")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CP",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    copy = create_ad_copy(campaign["id"], owner, kind="PRODUCED_AUDIO",
                          script_text="spot")
    copy = submit_ad_copy(copy["id"], owner)
    resp = api.review_ad_copy(copy["id"], {"action": "APPROVE"},
                              make_show_producer_headers(show["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_ad_copy(copy["id"])["status"] == "SUBMITTED"


def test_advertiser_cannot_patch_foreign_campaign(api):
    """PRD §2.1: "When `X-User-Role` is `Advertiser`, `X-User-ID` is the `id` of the acting `Advertiser` entity. An advertiser may act only on its own campaigns, ad copies, and make-good decisions: any operation whose target resolves to a campaign compares the campaign's `advertiser_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/advertiser_cannot_patch_foreign_campaign
    """
    adv_a = create_advertiser(name="OwnerA", category="FINTECH")
    adv_b = create_advertiser(name="OwnerB", category="AUTOMOTIVE")
    campaign = create_campaign(adv_a["id"], name="CA",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    # Reads are open to all roles; advertiser B learns the current version.
    observed = get_campaign(campaign["id"])
    resp = api.patch_campaign(
        campaign["id"],
        {"cpm_cents": 9999, "expected_campaign_version": observed["version"]},
        make_advertiser_headers(adv_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_campaign(campaign["id"])["cpm_cents"] == 1000
