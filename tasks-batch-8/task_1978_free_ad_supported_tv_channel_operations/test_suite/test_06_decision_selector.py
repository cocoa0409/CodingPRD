"""The server-side ad-insertion selector: eligibility, ranking, separation,
house waterfall, pacing, and break-level OCC (PRD §3.6, §2.8)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    create_channel,
    create_available_content,
    create_active_grant,
    create_loop,
    setup_channel_with_grant,
    setup_validated_loop,
    create_active_campaign,
    create_active_house_ad,
    run_decision_run,
    advance_clock,
    make_adops_headers,
    make_reviewer_headers,
    get_break,
    get_decision,
)

PROGRAMMER = TEST_USERS["programmer_headers"]
LICENSING = TEST_USERS["licensing_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_selector_ranks_higher_cpm_first(api):
    """PRD §3.6: "Among eligible creatives, ranking is by the campaign's `cpm_cents`
    descending, then the campaign's `priority` descending, then the creative's
    `created_at` ascending, then the campaign's `created_at` ascending." The cpm-600
    creative wins the single slot over the cpm-400 one.

    Design: Corner/calculations/selector_ranks_higher_cpm_first
    """
    ctx = setup_validated_loop(
        channel_name="Ch RK", break_durations=(30,), content_runtime=570
    )
    lo, cr_lo = create_active_campaign(
        advertiser_name="Lo", brand="Lo Brand", iab_category="IAB-7", cpm_cents=400
    )
    hi, cr_hi = create_active_campaign(
        advertiser_name="Hi", brand="Hi Brand", iab_category="IAB-8", cpm_cents=600
    )
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert len(decisions) == 1, "single-slot break produces exactly one row"
    assert decisions[0]["creative_id"] == cr_hi["id"], "higher cpm wins slot 0"
    assert decisions[0]["committed_cost_cents"] == 600, (
        "round_half_up(600 * 1000 / 1000) per PRD §3.6 committed-cost rule"
    )
    assert decisions[0]["fill_type"] == "DIRECT"


def test_selector_tie_break_uses_created_at_not_id(api):
    """PRD §3.6: "Among eligible creatives, ranking is by the campaign's `cpm_cents`
    descending, then the campaign's `priority` descending, then the creative's
    `created_at` ascending, then the campaign's `created_at` ascending. Ids never
    participate in this ranking." Identical cpm and priority: the creative created
    earlier under the logical clock wins.

    Design: Corner/calculations/selector_tie_break_uses_created_at_not_id
    """
    ctx = setup_validated_loop(
        channel_name="Ch TB", break_durations=(30,), content_runtime=570
    )
    campaigns = {}
    for tag, iab in (("a", "IAB-7"), ("b", "IAB-8")):
        campaigns[tag] = get_success_data(
            api_client.create_ad_campaign(
                factories.create_ad_campaign_payload(
                    advertiser_name=tag.upper(), iab_category=iab, cpm_cents=500
                ),
                make_adops_headers("ops-1"),
            )
        )
    advance_clock("2026-08-01T00:00:01Z")
    cr_a = get_success_data(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(campaigns["a"]["id"], brand="A Brand",
                                                 iab_category="IAB-7"),
            make_adops_headers("ops-1"),
        )
    )
    advance_clock("2026-08-01T00:00:02Z")
    cr_b = get_success_data(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(campaigns["b"]["id"], brand="B Brand",
                                                 iab_category="IAB-8"),
            make_adops_headers("ops-1"),
        )
    )
    for cr in (cr_a, cr_b):
        get_success_data(api_client.creative_approve(cr["id"], make_reviewer_headers("rev-1")))
    for tag in ("a", "b"):
        get_success_data(
            api_client.campaign_activate(campaigns[tag]["id"], make_adops_headers("ops-1"))
        )
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert len(decisions) == 1
    assert decisions[0]["creative_id"] == cr_a["id"], (
        "earlier created_at wins the tie; ids never participate"
    )
    assert decisions[0]["creative_id"] != cr_b["id"]


def test_selector_empty_pool_falls_back_to_slate(api):
    """PRD §3.6: "Any slot still unfilled after both passes is slate." and "Slate
    slots are implicit: no decision row is ever created for them." With no campaigns
    and no house ads the 60s break flips to DECIDED with all-slate accounting.

    Design: Corner/calculations/selector_empty_pool_falls_back_to_slate
    """
    ctx = setup_validated_loop(channel_name="Ch ES", break_durations=(60,))
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert decisions == [], "no decision rows are created for slate"
    brk = get_break(ctx["breaks"][0]["id"])
    assert brk["break_status"] == "DECIDED"
    assert brk["direct_seconds"] == 0
    assert brk["house_seconds"] == 0
    assert brk["slate_seconds"] == 60


def _setup_two_break_geometry(api, channel, separation_window=None):
    """Loop 2026-09-01 tiled as c120, break(60), c600, break(60), c60 -> 900s.
    Breaks land at [120, 180) and [780, 840): gap == 600 exactly."""
    contents = {}
    for tag, runtime in (("c120", 120), ("c600", 600), ("c60", 60)):
        contents[tag] = create_available_content(runtime_seconds=runtime, title=tag)
        create_active_grant(channel["id"], contents[tag]["id"], max_plays=5)
    loop = create_loop(channel["id"], "2026-09-01")
    get_success_data(
        api.loop_add_entry(loop["id"], {"content_id": contents["c120"]["id"]}, PROGRAMMER)
    )
    b1 = get_success_data(
        api.loop_add_ad_break(loop["id"], {"duration_seconds": 60}, PROGRAMMER)
    )
    get_success_data(
        api.loop_add_entry(loop["id"], {"content_id": contents["c600"]["id"]}, PROGRAMMER)
    )
    b2 = get_success_data(
        api.loop_add_ad_break(loop["id"], {"duration_seconds": 60}, PROGRAMMER)
    )
    get_success_data(
        api.loop_add_entry(loop["id"], {"content_id": contents["c60"]["id"]}, PROGRAMMER)
    )
    loop = get_success_data(api.loop_validate(loop["id"], PROGRAMMER))
    return loop, b1, b2


def test_competitive_separation_within_window_blocks_same_category(api):
    """PRD §3.6: "Adjacency is measured on the walk: for two breaks where the
    earlier break ends at e1 — its start offset plus its duration — and the later
    starts at s2, the gap is s2 minus e1; the breaks are adjacent when the gap is at
    or below the channel's `ad_separation_window_seconds`, and a gap exactly equal
    to the window counts as adjacent." Here the gap is exactly 600 with a 600
    window, so IAB-9 is excluded from the second break. (Each creative is 60s and
    spans its whole 60s break, so only IAB-9 sits on the first break.)

    Design: Corner/calculations/competitive_separation_within_window_blocks_same_category
    """
    channel = create_channel(name="Ch SP", loop_duration=900)
    loop, b1, b2 = _setup_two_break_geometry(api, channel)
    c1, cr1 = create_active_campaign(
        advertiser_name="Acme", brand="Acme One", iab_category="IAB-9",
        cpm_cents=500, creative_duration_seconds=60,
    )
    c3, cr3 = create_active_campaign(
        advertiser_name="Beta", brand="Beta Three", iab_category="IAB-7",
        cpm_cents=400, creative_duration_seconds=60,
    )
    db1 = run_decision_run(b1["id"])
    assert db1[0]["creative_id"] == cr1["id"], "higher cpm IAB-9 placed on b1"

    db2 = run_decision_run(b2["id"])
    assert db2[0]["creative_id"] == cr3["id"], (
        "IAB-9 excluded on b2 because gap 600 <= window 600; IAB-7 fills it"
    )
    assert get_break(b1["id"])["start_offset_seconds"] == 120
    assert get_break(b2["id"])["start_offset_seconds"] == 780


def test_competitive_separation_beyond_window_allows_same_category(api):
    """PRD §3.6: "the breaks are adjacent when the gap is at or below the channel's
    `ad_separation_window_seconds`, and a gap exactly equal to the window counts as
    adjacent." With the window at 599 the gap of 600 is beyond it, so the second
    break may take the same IAB category — the highest-cpm creative wins.

    Design: Corner/calculations/competitive_separation_beyond_window_allows_same_category
    """
    channel = create_channel(
        name="Ch SQ", loop_duration=900, ad_separation_window_seconds=599
    )
    loop, b1, b2 = _setup_two_break_geometry(api, channel)
    c1, cr1 = create_active_campaign(
        advertiser_name="Acme", brand="Acme One", iab_category="IAB-9", cpm_cents=500
    )
    c2, cr2 = create_active_campaign(
        advertiser_name="Acme2", brand="Acme Two", iab_category="IAB-9", cpm_cents=450
    )
    run_decision_run(b1["id"])
    db2 = run_decision_run(b2["id"])
    assert db2, "Setup failed: a placement is expected beyond the window"
    assert db2[0]["creative_id"] == cr1["id"], (
        "gap 600 > window 599: not adjacent, so IAB-9 stays eligible"
    )
    assert db2[0]["fill_type"] == "DIRECT"


def test_house_ad_waterfall_follows_priority_weight(api):
    """PRD §3.6: "House candidates rank by `priority_weight` descending and then
    `created_at` ascending, and each house placement occupies exactly one slot."
    With no direct demand the weight-9 house ad takes slot 0 and the 60s pod fills
    entirely with house placements.

    Design: Corner/calculations/house_ad_waterfall_follows_priority_weight
    """
    ctx = setup_validated_loop(channel_name="Ch HW", break_durations=(60,))
    h_lo = create_active_house_ad(name="Low", priority_weight=1, daily_impression_cap=5)
    h_hi = create_active_house_ad(name="High", priority_weight=9, daily_impression_cap=5)
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert len(decisions) == 2, "both slots fill from the house waterfall"
    assert decisions[0]["house_ad_id"] == h_hi["id"], "highest weight first"
    assert decisions[0]["slot_index"] == 0
    assert all(row["fill_type"] == "HOUSE" for row in decisions)
    brk = get_break(ctx["breaks"][0]["id"])
    assert brk["house_seconds"] == 60
    assert brk["slate_seconds"] == 0


def test_house_ad_daily_cap_boundary_exact(api):
    """PRD §3.6: "its placements on D so far must be strictly below its
    `daily_impression_cap`." With cap 1 the house ad fills slot 0 (placements 0 < 1)
    but not slot 1 (placements 1 == cap); the second slot goes slate.

    Design: Corner/calculations/house_ad_daily_cap_boundary_exact
    """
    ctx = setup_validated_loop(channel_name="Ch HC", break_durations=(60,))
    h1 = create_active_house_ad(name="Capped", priority_weight=5, daily_impression_cap=1)
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert len(decisions) == 1, "the cap admits exactly one placement"
    assert decisions[0]["house_ad_id"] == h1["id"]
    assert decisions[0]["slot_index"] == 0
    brk = get_break(ctx["breaks"][0]["id"])
    assert brk["house_seconds"] == 30
    assert brk["slate_seconds"] == 30


def test_campaign_daily_pacing_exact_fit_then_exclusion(api):
    """PRD §3.6: "the campaign's daily spend on D — the sum of `committed_cost_cents`
    over that campaign's provisional or committed decisions on loops whose
    `broadcast_date` is D, including reservations already made earlier in this run —
    plus the candidate's committed cost must not exceed `daily_budget_cents`." With
    500-cost slots against a 500 daily cap, the first break takes one slot
    (500 == cap is allowed) and the second break is excluded entirely.

    Design: Corner/calculations/campaign_daily_pacing_exact_fit_then_exclusion
    """
    ctx = setup_validated_loop(
        channel_name="Ch PC", break_durations=(60, 60), content_runtime=480
    )
    c1, cr1 = create_active_campaign(
        cpm_cents=500, total_budget_cents=100000, daily_budget_cents=500
    )
    b1, b2 = ctx["breaks"]
    d1 = run_decision_run(b1["id"])
    assert len(d1) == 1, "slot 0 fits exactly; slot 1 would exceed the daily cap"
    assert d1[0]["fill_type"] == "DIRECT" and d1[0]["slot_index"] == 0

    d2 = run_decision_run(b2["id"])
    assert d2 == [], "daily spend 500 == cap 500: no further placement on D"
    brk2 = get_break(b2["id"])
    assert brk2["break_status"] == "DECIDED"
    assert brk2["slate_seconds"] == 60


def test_decision_run_with_stale_break_version_rejected(api):
    """PRD §2.8: "Executing a decision run on an ad break requires
    `expected_break_version` matching the break's current `version`. A mismatch is
    rejected with `ERR_STALE_BREAK_VERSION` (HTTP 412), preventing a stale writer
    from silently discarding placements created after its read, since a decision run
    voids and replaces the break's provisional decisions."

    Design: Corner/validations/decision_run_with_stale_break_version_rejected
    """
    ctx = setup_validated_loop(channel_name="Ch OC1", break_durations=(60,))
    c1, cr1 = create_active_campaign()
    stale_version = ctx["breaks"][0]["version"]
    first = api_client.break_decision_run(
        ctx["breaks"][0]["id"], {"expected_break_version": stale_version},
        make_adops_headers("ops-1"),
    )
    assert first.status_code == 201, "Setup failed: first run must succeed"
    resp = api_client.break_decision_run(
        ctx["breaks"][0]["id"], {"expected_break_version": stale_version},
        make_adops_headers("ops-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_BREAK_VERSION)
    assert resp.status_code == 412
