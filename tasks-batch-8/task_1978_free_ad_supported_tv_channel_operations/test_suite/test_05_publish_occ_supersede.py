"""Loop publishing: channel-liveness guard, optimistic concurrency, supersede
invariant, and validation-tier ordering (PRD §2.8, §2.10, §3.4)."""
from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_channel,
    create_available_content,
    create_active_grant,
    create_loop,
    tile_loop,
    setup_channel_with_grant,
    setup_validated_loop,
    setup_locked_loop,
    setup_published_loop,
    run_decision_run,
    go_live,
    publish_loop,
    advance_clock,
    get_loop,
    get_grant,
    get_channel,
)

ADMIN = TEST_USERS["admin_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]
LICENSING = TEST_USERS["licensing_headers"]


def _setup_locked_loop_for(channel_name="Ch M"):
    """LOCKED loop (all-slate decision run) on a channel still in DRAFT."""
    ctx = setup_validated_loop(channel_name=channel_name, break_durations=(60,))
    run_decision_run(ctx["breaks"][0]["id"])
    ctx["loop"] = get_success_data(api_client.loop_lock(ctx["loop"]["id"], PROGRAMMER))
    assert ctx["loop"]["loop_status"] == "LOCKED", "Setup failed: loop must lock"
    return ctx


def test_loop_publish_rejected_while_channel_not_live(api):
    """PRD §3.4: "The channel must be `LIVE` — anything else is
    `ERR_CHANNEL_NOT_LIVE` — and its posture must not be `FROZEN`." The loop is
    fully LOCKED but the channel is still DRAFT.

    Design: Difficulty/cross_entity_state_dependency/r7_loop_publish_requires_channel_live
    """
    ctx = _setup_locked_loop_for("Ch M")
    resp = api_client.loop_publish(
        ctx["loop"]["id"],
        {"expected_channel_version": get_channel(ctx["channel"]["id"])["version"]},
        PROGRAMMER,
    )
    validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_LIVE)


def test_loop_publish_rejected_while_channel_not_live_states_unchanged(api):
    """PRD §3.4: "The channel must be `LIVE` — anything else is
    `ERR_CHANNEL_NOT_LIVE`". The rejected publish leaves the loop LOCKED and the
    channel DRAFT.

    Design: Difficulty/cross_entity_state_dependency/r7_loop_publish_requires_channel_live
    """
    ctx = _setup_locked_loop_for("Ch M2")
    resp = api_client.loop_publish(
        ctx["loop"]["id"],
        {"expected_channel_version": get_channel(ctx["channel"]["id"])["version"]},
        PROGRAMMER,
    )
    validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_LIVE)
    assert get_loop(ctx["loop"]["id"])["loop_status"] == "LOCKED"
    assert get_channel(ctx["channel"]["id"])["channel_status"] == "DRAFT"


def test_publish_with_stale_channel_version_rejected(api):
    """PRD §2.8: "Publishing a loop requires `expected_channel_version` carrying the
    client's last observed `version` of the channel. If the channel's current
    `version` differs — for example because another writer has since published a
    loop for that date, which bumps the channel's version — the publish is rejected
    with `ERR_STALE_CHANNEL_VERSION` (HTTP 412)".

    Design: Corner/validations/publish_with_stale_channel_version_rejected
    """
    base = setup_channel_with_grant(channel_name="Ch OC3", content_runtime=540)
    l1 = create_loop(base["channel"]["id"], "2026-09-01")
    _, b1 = tile_loop(l1["id"], base["content"]["id"], (60,))
    get_success_data(api_client.loop_validate(l1["id"], PROGRAMMER))
    run_decision_run(b1[0]["id"])
    get_success_data(api_client.loop_lock(l1["id"], PROGRAMMER))
    go_live(base["channel"]["id"])
    stale_version = get_channel(base["channel"]["id"])["version"]
    l1 = publish_loop(l1["id"], base["channel"]["id"])
    assert l1["loop_status"] == "PUBLISHED", "Setup failed: first loop must publish"

    # A second loop for the same date is allowed once the first is PUBLISHED.
    l2 = create_loop(base["channel"]["id"], "2026-09-01")
    _, b2 = tile_loop(l2["id"], base["content"]["id"], (60,))
    get_success_data(api_client.loop_validate(l2["id"], PROGRAMMER))
    run_decision_run(b2[0]["id"])
    get_success_data(api_client.loop_lock(l2["id"], PROGRAMMER))

    resp = api_client.loop_publish(
        l2["id"], {"expected_channel_version": stale_version}, PROGRAMMER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CHANNEL_VERSION)
    assert get_loop(l1["id"])["loop_status"] == "PUBLISHED"
    assert get_loop(l2["id"])["loop_status"] == "LOCKED"


def test_publish_supersedes_prior_published_loop(api):
    """PRD §3.4: "Any other loop of this channel with the same `broadcast_date`
    still in `PUBLISHED` status becomes `SUPERSEDED`, and this loop's
    `supersedes_loop_id` is set to that displaced loop."

    Design: Difficulty/compensating_invariant/r9_publish_supersede_conserves_single_published_loop
    """
    base = setup_channel_with_grant(channel_name="Ch Q", content_runtime=540)
    loops = {}
    for tag in ("l1", "l2"):
        loop = create_loop(base["channel"]["id"], "2026-09-01")
        _, breaks = tile_loop(loop["id"], base["content"]["id"], (60,))
        get_success_data(api_client.loop_validate(loop["id"], PROGRAMMER))
        run_decision_run(breaks[0]["id"])
        get_success_data(api_client.loop_lock(loop["id"], PROGRAMMER))
        if base["channel"]["channel_status"] != "LIVE":
            go_live(base["channel"]["id"])
            base["channel"] = get_channel(base["channel"]["id"])
        loops[tag] = publish_loop(loop["id"], base["channel"]["id"])

    assert loops["l2"]["loop_status"] == "PUBLISHED"
    assert get_loop(loops["l1"]["id"])["loop_status"] == "SUPERSEDED"
    assert loops["l2"].get("supersedes_loop_id") == loops["l1"]["id"]


def test_publish_supersede_conserves_single_published_loop_per_date(api):
    """PRD §3.4: "Any other loop of this channel with the same `broadcast_date`
    still in `PUBLISHED` status becomes `SUPERSEDED`". Exactly one PUBLISHED loop
    exists for the (channel, date) before and after the second publish; each publish
    consumed one play of the content ("the covering grant's `plays_used` increases
    by the number of entries of that content").

    Design: Difficulty/compensating_invariant/r9_publish_supersede_conserves_single_published_loop
    """
    base = setup_channel_with_grant(channel_name="Ch Q2", content_runtime=540)
    for _ in range(2):
        loop = create_loop(base["channel"]["id"], "2026-09-01")
        _, breaks = tile_loop(loop["id"], base["content"]["id"], (60,))
        get_success_data(api_client.loop_validate(loop["id"], PROGRAMMER))
        run_decision_run(breaks[0]["id"])
        get_success_data(api_client.loop_lock(loop["id"], PROGRAMMER))
        if base["channel"]["channel_status"] != "LIVE":
            go_live(base["channel"]["id"])
            base["channel"] = get_channel(base["channel"]["id"])
        publish_loop(loop["id"], base["channel"]["id"])

    data, meta = validate_paginated(
        api_client.list_playlist_loops(
            PROGRAMMER,
            params={
                "channel_id": base["channel"]["id"],
                "broadcast_date": "2026-09-01",
                "loop_status": "PUBLISHED",
            },
        )
    )
    assert len(data) == 1, "invariant: exactly one PUBLISHED loop per (channel, date)"
    assert get_grant(base["grant"]["id"])["plays_used"] == 2


def test_publish_draft_loop_with_past_date_reports_state_error(api):
    """PRD §2.10: "When several checks could reject the same request, the server
    evaluates them in a fixed order and reports the first failure it encounters" —
    state-transition legality (tier 7) runs before temporal windows (tier 11), so a
    publish of a DRAFT loop whose broadcast date has passed must not surface
    `ERR_BROADCAST_DATE_IN_PAST`.

    Design: Difficulty/priority_pair_validation_conflict/r5_publish_state_trumps_temporal_broadcast_date
    """
    base = setup_channel_with_grant(channel_name="Ch J", content_runtime=540)
    loop = create_loop(base["channel"]["id"], "2026-09-01")
    advance_clock("2026-09-02T00:00:00Z")
    resp = api_client.loop_publish(
        loop["id"],
        {"expected_channel_version": get_channel(base["channel"]["id"])["version"]},
        PROGRAMMER,
    )
    actual = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE_TRANSITION, ApiErrorId.ERR_CHANNEL_NOT_LIVE]
    )
    assert actual != ApiErrorId.ERR_BROADCAST_DATE_IN_PAST.value
    assert resp.status_code == 409


def test_publish_draft_loop_with_past_date_leaves_loop_untouched(api):
    """PRD §2.10: tier 7 ("State-transition legality ... else
    `ERR_INVALID_STATE_TRANSITION`") runs before tier 11 ("broadcast dates not in
    the past at loop create or publish (`ERR_BROADCAST_DATE_IN_PAST`)"); the
    rejected publish leaves the loop in DRAFT and the channel in DRAFT.

    Design: Difficulty/priority_pair_validation_conflict/r5_publish_state_trumps_temporal_broadcast_date
    """
    base = setup_channel_with_grant(channel_name="Ch J2", content_runtime=540)
    loop = create_loop(base["channel"]["id"], "2026-09-01")
    advance_clock("2026-09-02T00:00:00Z")
    resp = api_client.loop_publish(
        loop["id"],
        {"expected_channel_version": get_channel(base["channel"]["id"])["version"]},
        PROGRAMMER,
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE_TRANSITION, ApiErrorId.ERR_CHANNEL_NOT_LIVE]
    )
    assert get_loop(loop["id"])["loop_status"] == "DRAFT"
    assert get_channel(base["channel"]["id"])["channel_status"] == "DRAFT"
