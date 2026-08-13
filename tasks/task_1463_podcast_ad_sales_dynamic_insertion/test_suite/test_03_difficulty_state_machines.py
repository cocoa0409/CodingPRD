"""Difficulty queue A — non_linear_state_machine (2 instances, 4 tests)."""

from test_helpers import (
    ADOPS,
    add_line_item,
    assert_instant_equal,
    create_ad_copy,
    create_advertiser,
    create_campaign,
    create_episode,
    create_invoice,
    create_show,
    deliver_downloads,
    end_campaign,
    finalize_episode_measurement,
    get_ad_copy,
    get_campaign,
    get_make_good,
    ingest_downloads,
    invoice_campaign,
    list_make_goods_for_campaign,
    make_advertiser_headers,
    make_show_producer_headers,
    publish_episode,
    review_ad_copy,
    set_clock,
    setup_selling_scenario,
    submit_ad_copy,
    transition_campaign,
    transition_episode,
    transition_make_good,
)


def _setup_host_read_copy():
    """Show + direct advertiser + DRAFT campaign + DRAFT HOST_READ_SCRIPT copy
    bound to the show."""
    show = create_show(title="Loopcast", content_category="COMEDY",
                       avg_downloads_30d=5000)
    advertiser = create_advertiser(name="LoopBrand", category="CPG_FOOD")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CL",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=100, cpm_cents=1000)
    copy = create_ad_copy(campaign["id"], owner, kind="HOST_READ_SCRIPT",
                          script_text="v1 script", show_id=show["id"])
    return {"show": show, "advertiser": advertiser, "owner": owner,
            "campaign": campaign, "copy": copy,
            "producer": make_show_producer_headers(show["id"])}


def _setup_reopen_cycle():
    """Campaign taken ACTIVE -> PAUSED -> ACTIVE -> ENDED with 800 measured
    deliveries against 1000 booked; invoice DRAFT; MakeGood OFFERED (200).
    A second episode (publish 2026-08-25) remains SCHEDULED for the reopen leg."""
    show = create_show(title="Cycle Show", content_category="SPORTS",
                       avg_downloads_30d=10000)
    ep1 = create_episode(show["id"], title="E1", publish_at="2026-08-01T00:00:00Z",
                         measurement_window_days=30, slot_capacity=2)
    ep2 = create_episode(show["id"], title="E2", publish_at="2026-08-25T00:00:00Z",
                         measurement_window_days=30, slot_capacity=2)
    ctx = setup_selling_scenario(
        with_episode=False, advertiser_name="CycleCo", category="AUTOMOTIVE",
        booked_impressions=1000, cpm_cents=5000,
    )
    ctx["show"] = show
    ctx["episode"] = ep1
    ctx["episode2"] = ep2
    # Cyclic pause/resume before any delivery.
    paused = transition_campaign(ctx["campaign"]["id"], "PAUSE")
    assert paused["status"] == "PAUSED", "Setup failed: campaign did not pause"
    resumed = transition_campaign(ctx["campaign"]["id"], "ACTIVATE")
    assert resumed["status"] == "ACTIVE", "Setup failed: campaign did not resume"
    ctx["resumed_status"] = resumed["status"]
    ctx["line_item"] = add_line_item(ctx, target="show", position="MID_ROLL",
                                     reserved_impressions=1000, priority=10)
    publish_episode(ctx)
    deliver_downloads(ctx, 800, prefix="P")
    finalize_episode_measurement(ctx)
    end_campaign(ctx)
    invoice_campaign(ctx)
    assert ctx["make_good"] is not None, "Setup failed: expected an OFFERED MakeGood"
    return ctx


# =========================================================================
# ad_copy_revision_loop_cycles
# =========================================================================

def test_resubmission_from_changes_requested_bumps_revision(api):
    """PRD §3.3: "Submission moves copy `DRAFT → SUBMITTED`; resubmission out of `CHANGES_REQUESTED` moves it back to `SUBMITTED` and increments `revision` by exactly one."

    Design: Difficulty/non_linear_state_machine/ad_copy_revision_loop_cycles
    """
    ctx = _setup_host_read_copy()
    copy_id = ctx["copy"]["id"]
    submitted = submit_ad_copy(copy_id, ctx["owner"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision"] == 1
    review_ad_copy(copy_id, "REQUEST_CHANGES", ctx["producer"], note="tighten CTA")
    resubmitted = submit_ad_copy(copy_id, ctx["owner"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision"] == 2, (
        f"Resubmission must increment revision to 2, got {resubmitted['revision']}"
    )


def test_approved_copy_can_be_revoked_back_into_the_loop(api):
    """PRD §3.3: "Approval moves `SUBMITTED → APPROVED`. Requesting changes moves `SUBMITTED → CHANGES_REQUESTED`, and may also be applied to an already-`APPROVED` copy — a **revocation** that moves `APPROVED → CHANGES_REQUESTED` and immediately pauses every `ACTIVE` line item referencing that copy, releasing their reservations and episode slots."

    Design: Difficulty/non_linear_state_machine/ad_copy_revision_loop_cycles
    """
    ctx = _setup_host_read_copy()
    copy_id = ctx["copy"]["id"]
    submit_ad_copy(copy_id, ctx["owner"])
    review_ad_copy(copy_id, "REQUEST_CHANGES", ctx["producer"], note="tighten CTA")
    submit_ad_copy(copy_id, ctx["owner"])
    approved = review_ad_copy(copy_id, "APPROVE", ctx["producer"])
    assert approved["status"] == "APPROVED"
    revoked = review_ad_copy(copy_id, "REQUEST_CHANGES", ctx["producer"],
                             note="legal follow-up")
    assert revoked["status"] == "CHANGES_REQUESTED", (
        "APPROVED is not terminal; the machine loops back to CHANGES_REQUESTED"
    )


# =========================================================================
# campaign_pause_resume_and_makegood_reopen_cycle
# =========================================================================

def test_makegood_accept_reopens_ended_campaign_and_extends_flight(api):
    """PRD §3.7: "**Acceptance** requires `extension_days` between 1 and 30 (missing or out of range fails with `ERR_INVALID_REQUEST`) and reopens the campaign: the campaign moves `ENDED → ACTIVE`, its `flight_end` is extended by `extension_days`, and the make-good snapshots `baseline_delivered_impressions` as the campaign's `delivered_impressions` at the moment of acceptance."
    PRD §3.2: "Activation moves a campaign `DRAFT → ACTIVE` or resumes it `PAUSED → ACTIVE`; either requires the advertiser to be `ACTIVE` and at least one of the campaign's ad copies to be `APPROVED`, failing with `ERR_ADVERTISER_SUSPENDED` or `ERR_NO_APPROVED_COPY` respectively, and activation attempted from any other state fails with `ERR_CAMPAIGN_NOT_ACTIVATABLE`."

    Design: Difficulty/non_linear_state_machine/campaign_pause_resume_and_makegood_reopen_cycle
    """
    ctx = _setup_reopen_cycle()
    assert ctx["resumed_status"] == "ACTIVE", (
        "Campaign must have accepted the PAUSED -> ACTIVE resume before first END"
    )
    assert ctx["campaign"]["status"] == "ENDED"
    accepted = transition_make_good(
        ctx["make_good"]["id"], "ACCEPT", ctx["owner_headers"], extension_days=14,
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["baseline_delivered_impressions"] == 800
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["status"] == "ACTIVE", "Acceptance reopens the campaign ENDED -> ACTIVE"
    # 2026-09-01 + 14 days == 2026-09-15T00:00:00Z
    assert_instant_equal(campaign["flight_end"], "2026-09-15T00:00:00Z")


def test_second_end_evaluates_fulfillment_at_exact_tie(api):
    """PRD §3.7: "Fulfillment is then judged when the campaign next ends: the bonus delivered is the campaign's `delivered_impressions` minus `baseline_delivered_impressions`, and if that bonus is greater than or equal to `granted_impressions` — an exact tie fulfills — the make-good moves `ACCEPTED → FULFILLED`, otherwise `ACCEPTED → EXPIRED`."
    PRD §3.2: "if the campaign's invoice is `PAID` and no make-good of the campaign is in `OFFERED` or `ACCEPTED`, the campaign does not rest in `ENDED` but advances directly to `RECONCILED`."

    Design: Difficulty/non_linear_state_machine/campaign_pause_resume_and_makegood_reopen_cycle
    """
    ctx = _setup_reopen_cycle()
    transition_make_good(
        ctx["make_good"]["id"], "ACCEPT", ctx["owner_headers"], extension_days=14,
    )
    # Deliver the make-good bonus on the reopened flight.
    set_clock("2026-08-25T00:00:00Z")
    transition_episode(ctx["episode2"]["id"], "PUBLISH")
    ctx["episode"] = ctx["episode2"]
    ctx["campaign"] = get_campaign(ctx["campaign"]["id"])
    add_line_item(ctx, target="show", position="MID_ROLL",
                  reserved_impressions=100, priority=10)
    deliver_downloads(ctx, 200, prefix="Q", occurred_at="2026-08-26T00:00:00Z")
    finalize_episode_measurement(ctx, clock="2026-09-25T00:00:00Z")
    end_campaign(ctx)
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["delivered_impressions"] == 1000, (
        f"800 baseline + 200 bonus == 1000, got {campaign['delivered_impressions']}"
    )
    make_good = get_make_good(ctx["make_good"]["id"])
    assert make_good["status"] == "FULFILLED", (
        "bonus 200 >= granted 200 is an exact-tie fulfillment"
    )
    # Invoice was never marked PAID, so the campaign rests in ENDED.
    assert campaign["status"] == "ENDED"
