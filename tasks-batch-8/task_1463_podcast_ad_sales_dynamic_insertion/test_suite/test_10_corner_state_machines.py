"""Corner queue B — state_machines section (11 non-stub instances)."""

from test_helpers import (
    ADOPS,
    FINANCE,
    INGESTION,
    ApiErrorId,
    add_line_item,
    create_ad_copy,
    create_advertiser,
    create_campaign,
    create_episode,
    create_invoice,
    create_show,
    deliver_downloads,
    end_campaign,
    get_ad_copy,
    get_campaign,
    get_episode,
    get_invoice,
    get_line_item,
    get_make_good,
    ingest_downloads,
    invoice_campaign,
    list_make_goods_for_campaign,
    make_advertiser_headers,
    publish_episode,
    review_ad_copy,
    set_clock,
    setup_measured_delivery,
    setup_selling_scenario,
    submit_ad_copy,
    transition_advertiser,
    transition_campaign,
    transition_episode,
    transition_invoice,
    transition_line_item,
    transition_make_good,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_episode_publish_before_due_rejected(api):
    """PRD §3.1: "an episode may move `SCHEDULED → PUBLISHED` only once the current clock time is at or after `publish_at`; earlier attempts are rejected with `ERR_EPISODE_NOT_DUE`."

    Design: Corner/state_machines/episode_publish_before_due_rejected
    """
    show = create_show(title="Due FM", content_category="NEWS", avg_downloads_30d=100)
    episode = create_episode(show["id"], title="E1",
                             publish_at="2026-08-10T00:00:00Z")
    # Startup clock is exactly 2026-08-01T00:00:00Z, before publish_at.
    resp = api.transition_episode(episode["id"], {"action": "PUBLISH"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_DUE)
    assert get_episode(episode["id"])["status"] == "SCHEDULED"
    # The gate is inclusive: at clock == publish_at the retry succeeds.
    set_clock("2026-08-10T00:00:00Z")
    resp = api.transition_episode(episode["id"], {"action": "PUBLISH"}, ADOPS)
    assert validate_success(resp)["status"] == "PUBLISHED"


def test_finalize_at_exact_window_close_rejected(api):
    """PRD §3.1: "Later, measurement is finalized — `PUBLISHED → MEASURED`, the episode's terminal state — only when the clock has moved strictly past `publish_at` plus `measurement_window_days`; attempting finalization at or before that instant fails with `ERR_MEASUREMENT_WINDOW_OPEN`."

    Design: Corner/state_machines/finalize_at_exact_window_close_rejected
    """
    show = create_show(title="Window FM", content_category="NEWS",
                       avg_downloads_30d=100)
    episode = create_episode(show["id"], title="E1",
                             publish_at="2026-08-01T00:00:00Z",
                             measurement_window_days=30)
    transition_episode(episode["id"], "PUBLISH")
    # publish_at + 30 days == 2026-08-31T00:00:00Z exactly: still rejected.
    set_clock("2026-08-31T00:00:00Z")
    resp = api.transition_episode(episode["id"], {"action": "FINALIZE_MEASUREMENT"},
                                  ADOPS)
    validate_error(resp, ApiErrorId.ERR_MEASUREMENT_WINDOW_OPEN)
    # One second strictly past the window close succeeds.
    set_clock("2026-08-31T00:00:01Z")
    resp = api.transition_episode(episode["id"], {"action": "FINALIZE_MEASUREMENT"},
                                  ADOPS)
    measured = validate_success(resp)
    assert measured["status"] == "MEASURED"
    assert measured["measured_download_count"] == 0


def test_download_ingest_into_scheduled_episode_rejected(api):
    """PRD §3.5: "The episode must be `PUBLISHED`; ingesting against a `SCHEDULED` or `MEASURED` episode fails with `ERR_EPISODE_NOT_PUBLISHED`."

    Design: Corner/state_machines/download_ingest_into_scheduled_episode_rejected
    """
    show = create_show(title="Sched FM", content_category="NEWS", avg_downloads_30d=100)
    episode = create_episode(show["id"], title="E1",
                             publish_at="2026-08-10T00:00:00Z")
    resp = api.create_downloads(
        {"episode_id": episode["id"], "listener_key_prefix": "S", "count": 1,
         "occurred_at": "2026-08-02T00:00:00Z", "user_agent_class": "HUMAN"},
        INGESTION,
    )
    validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_PUBLISHED)
    _downloads, meta = validate_paginated(
        api.list_episode_downloads(episode["id"], ADOPS)
    )
    assert meta["total_count"] == 0, "A rejected ingest must create no downloads"


def test_campaign_cancel_lockdown_from_terminal(api):
    """PRD §3.2: "A `DRAFT` campaign may instead be cancelled, moving `DRAFT → CANCELLED`, terminal."
    PRD §3.2: "activation attempted from any other state fails with `ERR_CAMPAIGN_NOT_ACTIVATABLE`."

    Design: Corner/state_machines/campaign_cancel_lockdown_from_terminal
    """
    advertiser = create_advertiser(name="CancelCo", category="FINTECH")
    campaign = create_campaign(advertiser["id"], name="CX",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    cancelled = transition_campaign(campaign["id"], "CANCEL")
    assert cancelled["status"] == "CANCELLED"
    resp = api.transition_campaign(campaign["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVATABLE)
    resp = api.transition_campaign(campaign["id"], {"action": "END"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVATABLE)
    assert get_campaign(campaign["id"])["status"] == "CANCELLED"


def test_line_item_end_is_terminal(api):
    """PRD §3.4: "Ending a line item — from `ACTIVE` or `PAUSED`, manually or because the campaign ended — moves it to terminal `ENDED` and releases the reservation or slot exactly as a pause does. Any transition the machine forbids, such as activating an `ENDED` item, fails with `ERR_LINE_ITEM_STATE`."

    Design: Corner/state_machines/line_item_end_is_terminal
    """
    ctx = setup_selling_scenario(
        advertiser_name="TermCo", category="FINTECH", booked_impressions=10,
        cpm_cents=1000, episode_publish_at="2026-08-05T00:00:00Z",
    )
    line_item = add_line_item(ctx, target="show", position="MID_ROLL",
                              reserved_impressions=10, priority=1)
    line_item = transition_line_item(line_item["id"], "END")
    assert line_item["status"] == "ENDED"
    resp = api.transition_line_item(line_item["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_LINE_ITEM_STATE)
    assert get_line_item(line_item["id"])["status"] == "ENDED"


def test_ad_copy_review_from_draft_rejected(api):
    """PRD §3.3: "Withdrawal is an owner-only privilege: the owning advertiser or its agency may withdraw a `DRAFT` copy, moving it to terminal `WITHDRAWN`; neither `AdOps` nor the `ShowProducer` may withdraw, and reviews or withdrawals attempted from states the machine forbids fail with `ERR_COPY_STATE`."

    Design: Corner/state_machines/ad_copy_review_from_draft_rejected
    """
    advertiser = create_advertiser(name="DraftCo", category="FINTECH")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CD",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    copy = create_ad_copy(campaign["id"], owner, kind="PRODUCED_AUDIO",
                          script_text="spot")
    # Review actions require SUBMITTED (or APPROVED for REQUEST_CHANGES).
    resp = api.review_ad_copy(copy["id"], {"action": "APPROVE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_COPY_STATE)
    copy = get_ad_copy(copy["id"])
    assert copy["status"] == "DRAFT"
    assert copy["revision"] == 1


def test_ad_copy_withdraw_terminal(api):
    """PRD §3.3: "Withdrawal is an owner-only privilege: the owning advertiser or its agency may withdraw a `DRAFT` copy, moving it to terminal `WITHDRAWN`; neither `AdOps` nor the `ShowProducer` may withdraw, and reviews or withdrawals attempted from states the machine forbids fail with `ERR_COPY_STATE`."
    PRD §3.3: "Submission from any other state fails with `ERR_COPY_STATE`."

    Design: Corner/state_machines/ad_copy_withdraw_terminal
    """
    advertiser = create_advertiser(name="WdCo", category="FINTECH")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CW",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    copy = create_ad_copy(campaign["id"], owner, kind="PRODUCED_AUDIO",
                          script_text="spot")
    withdrawn = review_ad_copy(copy["id"], "WITHDRAW", owner)
    assert withdrawn["status"] == "WITHDRAWN"
    resp = api.submit_ad_copy(copy["id"], owner)
    validate_error(resp, ApiErrorId.ERR_COPY_STATE)


def _setup_full_delivery_no_shortfall():
    """Booked 5, cpm 1000, 5 measured deliveries; campaign ENDED; invoice
    DRAFT; zero shortfall, so no make-good exists."""
    ctx = setup_measured_delivery(
        booked_impressions=5, cpm_cents=1000, downloads=5,
        reserved_impressions=5, category="FINTECH",
        end_campaign_too=True, create_invoice_too=True,
    )
    assert ctx["make_good"] is None, "Setup failed: no shortfall expected here"
    return ctx


def test_invoice_mark_paid_requires_issued(api):
    """PRD §3.7: "The invoice lifecycle itself runs `DRAFT → ISSUED → PAID`, with a dispute branch `ISSUED → DISPUTED`, and re-issuance `DISPUTED → ISSUED` permitted — re-issuing does not recompute any amounts, since the figures frozen at creation (plus a decline credit) are final. Any transition outside this machine fails with `ERR_INVOICE_STATE`."
    PRD §3.7: "Marking an invoice `PAID` performs the reconcile check of §3.2: if the campaign is `ENDED` and no make-good of the campaign is in `OFFERED` or `ACCEPTED`, the campaign advances to terminal `RECONCILED`, closing the loop from flight to settlement."

    Design: Corner/state_machines/invoice_mark_paid_requires_issued
    """
    ctx = _setup_full_delivery_no_shortfall()
    invoice_id = ctx["invoice"]["id"]
    resp = api.transition_invoice(invoice_id, {"action": "MARK_PAID"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVOICE_STATE)
    transition_invoice(invoice_id, "ISSUE")
    paid = transition_invoice(invoice_id, "MARK_PAID")
    assert paid["status"] == "PAID"
    # Invoice PAID + campaign ENDED + no open make-good -> auto RECONCILED.
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["status"] == "RECONCILED", (
        f"Campaign must reconcile once its invoice is PAID, got {campaign['status']}"
    )


def test_invoice_dispute_reissue_cycle_amounts_frozen(api):
    """PRD §3.7: "The invoice lifecycle itself runs `DRAFT → ISSUED → PAID`, with a dispute branch `ISSUED → DISPUTED`, and re-issuance `DISPUTED → ISSUED` permitted — re-issuing does not recompute any amounts, since the figures frozen at creation (plus a decline credit) are final."

    Design: Corner/state_machines/invoice_dispute_reissue_cycle_amounts_frozen
    """
    ctx = _setup_full_delivery_no_shortfall()
    invoice_id = ctx["invoice"]["id"]
    transition_invoice(invoice_id, "ISSUE")
    disputed = transition_invoice(invoice_id, "DISPUTE")
    assert disputed["status"] == "DISPUTED"
    reissued = transition_invoice(invoice_id, "ISSUE")
    assert reissued["status"] == "ISSUED"
    # 5 x 1000 x 1000 / 1000000 == 5; direct advertiser -> commission 0;
    # no make-good -> credit 0; nothing recomputes across the loop.
    invoice = get_invoice(invoice_id)
    assert invoice["gross_cents"] == 5
    assert invoice["agency_commission_cents"] == 0
    assert invoice["make_good_credit_cents"] == 0
    assert invoice["net_cents"] == 5


def _setup_offered_makegood():
    """Shortfall chain: booked 1000 cpm 2000, 800 measured deliveries, campaign
    ENDED, invoice DRAFT, MakeGood OFFERED granted 200."""
    ctx = setup_measured_delivery(
        booked_impressions=1000, cpm_cents=2000, downloads=800,
        reserved_impressions=500, category="FINTECH",
        end_campaign_too=True, create_invoice_too=True,
    )
    assert ctx["make_good"] is not None, "Setup failed: expected an OFFERED MakeGood"
    return ctx


def test_make_good_decline_terminal_blocks_accept(api):
    """PRD §3.7: "Answering a make-good that is no longer `OFFERED` fails with `ERR_MAKE_GOOD_STATE`. `DECLINED`, `FULFILLED`, and `EXPIRED` are terminal."

    Design: Corner/state_machines/make_good_decline_terminal_blocks_accept
    """
    ctx = _setup_offered_makegood()
    owner = make_advertiser_headers(ctx["advertiser"]["id"])
    declined = transition_make_good(ctx["make_good"]["id"], "DECLINE", owner)
    assert declined["status"] == "DECLINED"
    resp = api.transition_make_good(
        ctx["make_good"]["id"], {"action": "ACCEPT", "extension_days": 7}, owner,
    )
    validate_error(resp, ApiErrorId.ERR_MAKE_GOOD_STATE)
    assert get_campaign(ctx["campaign"]["id"])["status"] == "ENDED"


def test_suspended_advertiser_blocks_campaign_create(api):
    """PRD §3.2: "The advertiser must be `ACTIVE`, both at creation and at activation, or the request fails with `ERR_ADVERTISER_SUSPENDED`."

    Design: Corner/state_machines/suspended_advertiser_blocks_campaign_create
    """
    advertiser = create_advertiser(name="SuspCo", category="FINTECH")
    transition_advertiser(advertiser["id"], "SUSPEND")
    resp = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "CS",
            "flight_start": "2026-08-01T00:00:00Z",
            "flight_end": "2026-09-01T00:00:00Z",
            "booked_impressions": 10,
            "cpm_cents": 1000,
            "billing_model": "ACTUAL_DELIVERY",
        },
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_ADVERTISER_SUSPENDED)
    _campaigns, meta = validate_paginated(
        api.list_campaigns(ADOPS, params={"advertiser_id": advertiser["id"]})
    )
    assert meta["total_count"] == 0
