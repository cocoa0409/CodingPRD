"""Air, reconciliation, viewership measurement, and channel-day snapshots
(PRD §3.7, §2.5)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    create_channel,
    setup_validated_loop,
    setup_published_loop,
    setup_locked_loop,
    setup_exhausted_campaign_loop,
    setup_two_day_score_scenario,
    create_active_campaign,
    create_active_house_ad,
    setup_platform,
    run_decision_run,
    publish_loop,
    go_live,
    post_viewership_event,
    post_content_watch,
    post_impressions,
    compute_snapshot,
    assert_viewership_event,
    get_break,
    get_campaign,
    get_decision,
    get_snapshot,
)

ADMIN = TEST_USERS["admin_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_viewership_event_immutable_no_version_field(api):
    """PRD §2.5: "One deliberate exception exists: a viewership event is an
    append-only record and carries only `id` and `created_at`. Both `updated_at` and
    `version` are absent from it — events are never modified after ingestion."

    Design: Corner/entities/viewership_event_immutable_no_version_field
    """
    channel = create_channel(name="Ch Ev")
    platform = setup_platform(name="P1", active=False)
    event = post_viewership_event(
        channel["id"], "SESSION_START", platform["id"],
        occurred_at="2026-09-01T00:00:00Z",
    )
    assert_viewership_event(event)
    fetched = get_success_data(api.get_viewership_event(event["id"], ADMIN))
    assert_viewership_event(fetched)
    assert fetched["id"] == event["id"]


def test_mark_aired_requires_published_loop(api):
    """PRD §3.7: "Once the parent loop is `PUBLISHED`, a `ChannelProgrammer` marks a
    decided break as aired (`DECIDED` → `AIRED`), incrementing the break's
    `version`." While the parent loop is merely LOCKED the trigger is not valid;
    PRD §2.10: "State-transition legality: the trigger must be valid from the
    resource's current state, including terminal-state lockdown, else
    `ERR_INVALID_STATE_TRANSITION`".

    Design: Corner/state_machines/mark_aired_requires_published_loop
    """
    ctx = setup_locked_loop(
        channel_name="Ch MA", break_durations=(30,), content_runtime=570
    )
    resp = api.break_mark_aired(ctx["breaks"][0]["id"], PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_break(ctx["breaks"][0]["id"])["break_status"] == "DECIDED"


def test_reconcile_revives_exhausted_campaign_on_down_adjustment(api):
    """PRD §3.7: "The campaign's `spent_cents` is then adjusted by the delta between
    reconciled and committed cost — which may be negative — and an `EXHAUSTED`
    campaign that drops below its total budget with its `flight_end_date` on or
    after the current logical date returns to `ACTIVE`." Zero matched impressions
    reconcile the 500-cent commit down to 0.

    Design: Corner/cross_cutting_layers/reconcile_revives_exhausted_campaign_on_down_adjustment
    """
    ctx = setup_exhausted_campaign_loop()
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    go_live(ctx["channel"]["id"])
    publish_loop(ctx["loop"]["id"], ctx["channel"]["id"])
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["campaign_status"] == "EXHAUSTED"
    assert campaign["spent_cents"] == 500
    get_success_data(api.break_mark_aired(ctx["breaks"][0]["id"], PROGRAMMER))

    get_success_data(api.break_reconcile(ctx["breaks"][0]["id"], ADOPS))
    decision = get_decision(ctx["decisions"][0]["id"])
    assert decision["decision_status"] == "RECONCILED"
    assert decision["actual_impressions"] == 0
    assert decision["reconciled_cost_cents"] == 0
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["spent_cents"] == 0
    assert campaign["campaign_status"] == "ACTIVE", "auto-revived, flight valid"
    assert get_break(ctx["breaks"][0]["id"])["break_status"] == "RECONCILED"


def test_fill_rate_zero_capacity_day(api):
    """PRD §3.7: "`capacity_seconds` sums the break durations on that loop, and is 0
    when no loop was published for the date" and the fill rates are "each exactly
    0.0000 when `capacity_seconds` is 0"; "`ecpm_cents` is `direct_revenue_cents`
    multiplied by 1000 and divided by `direct_sold_impressions`, rounded half-up —
    and is exactly 0, not null and not an error, when there are no direct-sold
    impressions."

    Design: Corner/calculations/fill_rate_zero_capacity_day
    """
    channel = create_channel(name="Ch ZC")
    snap = compute_snapshot(channel["id"], "2026-09-01")
    assert snap["capacity_seconds"] == 0
    assert snap["direct_fill_rate"] == pytest.approx(0.0, abs=1e-9)
    assert snap["effective_fill_rate"] == pytest.approx(0.0, abs=1e-9)
    assert snap["ecpm_cents"] == 0
    assert snap["performance_score"] == 0


def test_peak_concurrent_viewers_chronological_replay(api):
    """PRD §3.7: "`peak_concurrent_viewers` replays the channel-day's
    `SESSION_START` events as +1 and `SESSION_END` events as −1, ordered by
    `occurred_at_utc` ascending with ties broken by `created_at` ascending". The two
    SESSION_END rows were ingested before the five SESSION_START rows but replay
    after them by timestamp, so the peak is 5.

    Design: Corner/calculations/peak_concurrent_viewers_chronological_replay
    """
    channel = create_channel(name="Ch PK")
    platform = setup_platform(name="P1", active=False)
    for i in (1, 2):
        post_viewership_event(
            channel["id"], "SESSION_END", platform["id"],
            occurred_at="2026-09-01T00:10:00Z", session=f"e{i}",
        )
    for i in range(1, 6):
        post_viewership_event(
            channel["id"], "SESSION_START", platform["id"],
            occurred_at="2026-09-01T00:00:00Z", session=f"v{i}",
        )
    snap = compute_snapshot(channel["id"], "2026-09-01")
    assert snap["peak_concurrent_viewers"] == 5
    assert snap["capacity_seconds"] == 0


def test_snapshot_recompute_reconciles_derived_fields(api):
    """PRD §3.7: "One snapshot exists per (channel, date): recomputation upserts the
    same record, increments its `version`, and restamps `computed_at`." and
    "`watch_seconds` sums the `watch_seconds` of `CONTENT_WATCH` events in the
    window."

    Design: Corner/cross_cutting_layers/snapshot_recompute_reconciles_derived_fields
    """
    channel = create_channel(name="Ch DR2")
    platform = setup_platform(name="P1", active=False)
    content = get_success_data(
        api.create_content_asset(
            factories.create_content_asset_payload(title="M"), TEST_USERS["licensing_headers"]
        )
    )
    post_content_watch(channel["id"], platform["id"], content["id"], 100,
                       "2026-09-01T01:00:00Z", session="s1")
    first = compute_snapshot(channel["id"], "2026-09-01")
    assert first["watch_seconds"] == 100

    post_content_watch(channel["id"], platform["id"], content["id"], 100,
                       "2026-09-01T02:00:00Z", session="s2")
    post_content_watch(channel["id"], platform["id"], content["id"], 50,
                       "2026-09-01T03:00:00Z", session="s3")
    second = compute_snapshot(channel["id"], "2026-09-01")
    assert second["id"] == first["id"], "recompute upserts the same record"
    assert second["watch_seconds"] == 250
    assert second["version"] == first["version"] + 1


def _setup_house_substitution_loop(api):
    """90s break decided as 30 DIRECT + 30 HOUSE + 30 slate, then PUBLISHED.
    (Entry runtime 510 tiles 600 with the 90s break.)"""
    ctx = setup_validated_loop(
        channel_name="Ch A", break_durations=(90,), content_runtime=510
    )
    campaign, creative = create_active_campaign(
        cpm_cents=500, total_budget_cents=5000, daily_budget_cents=5000
    )
    house = create_active_house_ad(name="House Promo", priority_weight=5,
                                   daily_impression_cap=1)
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert len(decisions) == 2, "Setup failed: expected one DIRECT and one HOUSE row"
    get_success_data(api.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    go_live(ctx["channel"]["id"])
    publish_loop(ctx["loop"]["id"], ctx["channel"]["id"])
    ctx.update({"campaign": campaign, "creative": creative, "house": house,
                "decisions": decisions})
    return ctx


def test_fill_rate_variants_diverge_on_house_substitution(api):
    """PRD §3.7: "`direct_fill_rate` is `direct_seconds` divided by
    `capacity_seconds`, and `effective_fill_rate` is the sum of `direct_seconds` and
    `house_seconds` divided by `capacity_seconds` — each a scale-4 fixed-point value
    rounded half-up". With 30 DIRECT + 30 HOUSE + 30 slate in a 90s pod the direct
    rate is 0.3333 while the effective rate is 0.6667.

    Design: Difficulty/dual_variant_calc/r1_direct_vs_effective_fill_rate_diverge_on_house_substitution
    """
    ctx = _setup_house_substitution_loop(api)
    snap = compute_snapshot(ctx["channel"]["id"], "2026-09-01")
    assert snap["capacity_seconds"] == 90
    assert snap["direct_seconds"] == 30
    assert snap["house_seconds"] == 30
    assert snap["direct_fill_rate"] == pytest.approx(0.3333, abs=1e-4)
    assert snap["effective_fill_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert snap["direct_fill_rate"] != snap["effective_fill_rate"], (
        "same break, same moment — the divergence is house substitution"
    )


def test_fill_variant_decision_accounting_direct_vs_house(api):
    """PRD §3.6: "A direct row's `committed_cost_cents` is the campaign's
    `cpm_cents` multiplied by `expected_impressions` and divided by 1000, rounded
    half-up to whole cents; a house row's is 0." The DIRECT row (cpm 500 over 1000
    expected impressions) costs 500 cents; the HOUSE row costs nothing.

    Design: Difficulty/dual_variant_calc/r1_direct_vs_effective_fill_rate_diverge_on_house_substitution
    """
    ctx = _setup_house_substitution_loop(api)
    by_type = {row["fill_type"]: row for row in ctx["decisions"]}
    direct = get_decision(by_type["DIRECT"]["id"])
    house = get_decision(by_type["HOUSE"]["id"])
    assert direct["creative_id"] == ctx["creative"]["id"]
    assert direct["committed_cost_cents"] == 500
    assert direct["expected_impressions"] == 1000
    assert house["house_ad_id"] == ctx["house"]["id"]
    assert house["committed_cost_cents"] == 0
    assert house["expected_impressions"] == 0


def test_performance_score_below_watch_threshold(api):
    """PRD §3.7: "The snapshot's `performance_score` condenses three of these
    signals into a 0-to-100 figure: the `direct_fill_rate` multiplied by 80 and
    rounded half-up to a whole number, plus a 20-point bonus when the day's
    `watch_seconds` reach at least 60,000". At 59,999 watch seconds with a 0.5000
    direct fill and zero direct-sold impressions the score is 40.

    Design: Difficulty/combinatorial_formula/r2_weighted_score_threshold_bands_nonlinear
    """
    ctx = setup_two_day_score_scenario()
    post_content_watch(ctx["channel"]["id"], ctx["platform"]["id"],
                       ctx["content"]["id"], 59999, "2026-09-01T01:00:00Z", session="s1")
    snap = compute_snapshot(ctx["channel"]["id"], "2026-09-01")
    assert snap["watch_seconds"] == 59999
    assert snap["direct_fill_rate"] == pytest.approx(0.5, abs=1e-4)
    assert snap["ecpm_cents"] == 0, "zero impressions -> pinned 0, not an error"
    assert snap["performance_score"] == 40


def test_performance_score_at_watch_threshold_grants_bonus(api):
    """PRD §3.7: "plus a 20-point bonus when the day's `watch_seconds` reach at
    least 60,000, plus a further 20-point bonus when `ecpm_cents` reaches at least
    2,000, with the total capped at 100 and each bonus contributing nothing below
    its threshold." At exactly 60,000 watch seconds the same 0.5000-fill day scores
    60.

    Design: Difficulty/combinatorial_formula/r2_weighted_score_threshold_bands_nonlinear
    """
    ctx = setup_two_day_score_scenario()
    post_content_watch(ctx["channel"]["id"], ctx["platform"]["id"],
                       ctx["content"]["id"], 60000, "2026-09-02T01:00:00Z", session="s2")
    snap = compute_snapshot(ctx["channel"]["id"], "2026-09-02")
    assert snap["watch_seconds"] == 60000
    assert snap["direct_fill_rate"] == pytest.approx(0.5, abs=1e-4)
    assert snap["performance_score"] == 60
