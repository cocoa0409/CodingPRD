"""Difficulty queue A — priority_pair_validation_conflict (2 instances, 4 tests)."""

from test_helpers import (
    ADOPS,
    ApiErrorId,
    add_line_item,
    create_ad_copy,
    create_advertiser,
    create_campaign,
    create_episode,
    create_show,
    get_line_item,
    get_show,
    setup_selling_scenario,
    submit_ad_copy,
    transition_campaign,
    validate_error,
    validate_paginated,
    review_ad_copy,
    make_advertiser_headers,
)


def _setup_state_vs_fiscal():
    """Show avg 1000 with one episode in horizon (forecast 950); LI1 (950)
    ACTIVATED to exact fit; LI2 (1) DRAFT; campaign then manually PAUSED."""
    ctx = setup_selling_scenario(
        advertiser_name="TightCo", category="FINTECH", content_category="BUSINESS",
        show_avg=1000, booked_impressions=950, cpm_cents=1000,
        episode_publish_at="2026-08-05T00:00:00Z",
    )
    li1 = add_line_item(ctx, target="show", position="MID_ROLL",
                        reserved_impressions=950, priority=10)
    li2 = add_line_item(ctx, target="show", position="POST_ROLL",
                        reserved_impressions=1, priority=5, activate=False)
    transition_campaign(ctx["campaign"]["id"], "PAUSE")
    ctx["li1"] = li1
    ctx["li2"] = li2
    return ctx


def _setup_safety_vs_referential():
    """Show blocking GAMBLING; GAMBLING advertiser with campaigns C1 (owns the
    APPROVED copy) and C2 (the line-item target)."""
    show = create_show(title="Family First", content_category="COMEDY",
                       avg_downloads_30d=5000,
                       blocked_advertiser_categories=["GAMBLING"])
    advertiser = create_advertiser(name="BetNow", category="GAMBLING")
    owner = make_advertiser_headers(advertiser["id"])
    c1 = create_campaign(advertiser["id"], name="C1",
                         flight_start="2026-08-01T00:00:00Z",
                         flight_end="2026-09-01T00:00:00Z",
                         booked_impressions=100, cpm_cents=1000)
    c2 = create_campaign(advertiser["id"], name="C2",
                         flight_start="2026-08-01T00:00:00Z",
                         flight_end="2026-09-01T00:00:00Z",
                         booked_impressions=100, cpm_cents=1000)
    copy = create_ad_copy(c1["id"], owner, kind="PRODUCED_AUDIO", script_text="spot")
    copy = submit_ad_copy(copy["id"], owner)
    copy = review_ad_copy(copy["id"], "APPROVE", ADOPS)
    return {"show": show, "advertiser": advertiser, "c1": c1, "c2": c2, "copy": copy}


# =========================================================================
# state_beats_fiscal_on_line_item_activation
# =========================================================================

def test_activation_reports_campaign_not_active_not_inventory(api):
    """PRD §2.8: "Every request is validated against an ordered pipeline; the first failing check wins and short-circuits all later checks."
    PRD §2.8: "7. **State legality** — the resource's current state must permit the requested operation under its state machine (for example `ERR_CAMPAIGN_NOT_ACTIVATABLE`, `ERR_LINE_ITEM_STATE`, `ERR_COPY_STATE`, `ERR_INVOICE_STATE`, `ERR_MAKE_GOOD_STATE`, `ERR_CAMPAIGN_NOT_EDITABLE`, `ERR_CAMPAIGN_NOT_ENDED`, `ERR_CAMPAIGN_NOT_ACTIVE`, `ERR_EPISODE_NOT_PUBLISHED`)."
    PRD §2.8: "12. **Inventory sufficiency** — run-of-show reservation feasibility (`ERR_INSUFFICIENT_INVENTORY`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_line_item_activation
    """
    ctx = _setup_state_vs_fiscal()
    # The request violates both the state gate (campaign PAUSED) and the fiscal
    # gate (reserved 1 > available 0); the earlier state category must win.
    resp = api.transition_line_item(ctx["li2"]["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)


def test_failed_activation_leaves_line_item_and_pool_untouched(api):
    """PRD §3.4: "Activation — `DRAFT → ACTIVE`, and identically resumption `PAUSED → ACTIVE` — runs the full sales-integrity gate, in the pipeline order of §2.8:"
    PRD §3.4: "The owning campaign must be `ACTIVE`, else `ERR_CAMPAIGN_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_line_item_activation
    """
    ctx = _setup_state_vs_fiscal()
    resp = api.transition_line_item(ctx["li2"]["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)
    line_item = get_line_item(ctx["li2"]["id"])
    assert line_item["status"] == "DRAFT", (
        f"Rejected activation must leave the line item DRAFT, got {line_item['status']}"
    )
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 950
    assert show["available_impressions"] == 0


# =========================================================================
# safety_beats_referential_on_line_item_create
# =========================================================================

def test_create_reports_brand_safety_not_copy_mismatch(api):
    """PRD §2.8: "Every request is validated against an ordered pipeline; the first failing check wins and short-circuits all later checks."
    PRD §2.8: "8. **Brand safety** — suspended-show and blocked-category screening (`ERR_SHOW_SUSPENDED`, `ERR_BRAND_SAFETY_CONFLICT`)."
    PRD §2.8: "9. **Cross-reference integrity** — target scoping, host-read show binding, copy-to-campaign attachment, format matching, and promo-code presence (`ERR_TARGET_SCOPE_INVALID`, `ERR_HOST_READ_REQUIRES_SHOW`, `ERR_COPY_CAMPAIGN_MISMATCH`, `ERR_INVALID_REQUEST`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_line_item_create
    """
    ctx = _setup_safety_vs_referential()
    # The request violates both brand safety (GAMBLING blocked by the show) and
    # referential integrity (the copy belongs to C1, not C2); brand safety is
    # the earlier category and must win.
    resp = api.create_line_item(
        {
            "campaign_id": ctx["c2"]["id"],
            "show_id": ctx["show"]["id"],
            "ad_format": "PRODUCED_SPOT",
            "position": "MID_ROLL",
            "reserved_impressions": 10,
            "priority": 10,
            "ad_copy_id": ctx["copy"]["id"],
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_BRAND_SAFETY_CONFLICT)


def test_rejected_create_persists_no_line_item(api):
    """PRD §3.4: "The campaign advertiser's `category` must not appear in the target show's `blocked_advertiser_categories`, else `ERR_BRAND_SAFETY_CONFLICT`. (Also screened at creation.)"

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_line_item_create
    """
    ctx = _setup_safety_vs_referential()
    resp = api.create_line_item(
        {
            "campaign_id": ctx["c2"]["id"],
            "show_id": ctx["show"]["id"],
            "ad_format": "PRODUCED_SPOT",
            "position": "MID_ROLL",
            "reserved_impressions": 10,
            "priority": 10,
            "ad_copy_id": ctx["copy"]["id"],
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_BRAND_SAFETY_CONFLICT)
    line_items, meta = validate_paginated(
        api.list_line_items(ADOPS, params={"campaign_id": ctx["c2"]["id"]})
    )
    assert meta["total_count"] == 0, (
        f"Rejected create must persist nothing, found {meta['total_count']} line items"
    )
    assert line_items == []
