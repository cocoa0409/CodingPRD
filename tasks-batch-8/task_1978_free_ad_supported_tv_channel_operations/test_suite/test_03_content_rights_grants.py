"""Content lifecycle, rights-grant windows, ops-run expiry, and the
loop-revert cascade (PRD §3.1, §3.2, §3.4)."""
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
    tile_loop,
    setup_channel_with_grant,
    setup_validated_loop,
    create_active_campaign,
    run_decision_run,
    go_live,
    publish_loop,
    advance_clock,
    get_content,
    get_grant,
    get_loop,
    get_break,
    get_decision,
    get_channel,
)

ADMIN = TEST_USERS["admin_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]
LICENSING = TEST_USERS["licensing_headers"]


def test_content_asset_create_with_invalid_enum_rejected(api):
    """PRD §3.2: "a `content_type` of `MOVIE`, `EPISODE`, or `SHORT`"; PRD §2.10:
    "Request body shape: required fields present, enum values valid, and numeric
    ranges respected (for example `max_plays` must be positive, `runtime_seconds`
    must be positive, and revenue-share basis points outside 0..6000 are reported as
    `ERR_REV_SHARE_OUT_OF_RANGE`), else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/content_asset_create_with_invalid_enum_rejected
    """
    create_channel(name="Seed Ch")
    resp = api.create_content_asset(
        factories.create_content_asset_payload(title="Bad", content_type="SERIES"),
        LICENSING,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_archived_content_terminal_lockdown(api):
    """PRD §3.2: "may be archived (`PULLED` → `ARCHIVED`, terminal) only when no
    such grant remains"; PRD §2.10: "State-transition legality: the trigger must be
    valid from the resource's current state, including terminal-state lockdown, else
    `ERR_INVALID_STATE_TRANSITION`".

    Design: Corner/state_machines/archived_content_terminal_lockdown
    """
    content = create_available_content(runtime_seconds=540, title="Old Movie")
    get_success_data(api.content_pull(content["id"], LICENSING))
    get_success_data(api.content_archive(content["id"], LICENSING))
    resp = api.content_reinstate(content["id"], LICENSING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_content(content["id"])["content_status"] == "ARCHIVED"


def test_grant_invalid_window_rejected(api):
    """PRD §3.2: "The end of the window must fall strictly after its start, else
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/grant_invalid_window_rejected
    """
    channel = create_channel(name="Ch IW")
    content = create_available_content(runtime_seconds=540, title="M")
    resp = api.create_rights_grant(
        factories.create_rights_grant_payload(
            channel["id"], content["id"],
            window_start_utc="2026-08-01T00:00:00Z",
            window_end_utc="2026-08-01T00:00:00Z", max_plays=5,
        ),
        LICENSING,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_rights_grant_adjacent_windows_allowed(api):
    """PRD §3.2: "Among grants in `PENDING` or `ACTIVE` status for the same
    (content, channel) pair, windows may not overlap under half-open semantics —
    adjacency, where one grant's end equals another's start, is allowed — and a
    violating creation is rejected with `ERR_GRANT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/r8_rights_grant_half_open_windows_allow_adjacency
    """
    channel = create_channel(name="Ch N")
    content = create_available_content(runtime_seconds=540, title="Movie 540")
    g1 = get_success_data(
        api.create_rights_grant(
            factories.create_rights_grant_payload(
                channel["id"], content["id"],
                window_start_utc="2026-08-01T00:00:00Z",
                window_end_utc="2026-09-01T00:00:00Z", max_plays=5,
            ),
            LICENSING,
        )
    )
    assert g1["grant_status"] == "PENDING"
    g2 = get_success_data(
        api.create_rights_grant(
            factories.create_rights_grant_payload(
                channel["id"], content["id"],
                window_start_utc="2026-09-01T00:00:00Z",
                window_end_utc="2026-10-01T00:00:00Z", max_plays=5,
            ),
            LICENSING,
        )
    )
    assert g2["grant_status"] == "PENDING", (
        "end == start is adjacency, allowed under half-open semantics"
    )


def test_rights_grant_interior_overlap_rejected(api):
    """PRD §3.2: "Among grants in `PENDING` or `ACTIVE` status for the same
    (content, channel) pair, windows may not overlap under half-open semantics —
    adjacency, where one grant's end equals another's start, is allowed — and a
    violating creation is rejected with `ERR_GRANT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/r8_rights_grant_half_open_windows_allow_adjacency
    """
    channel = create_channel(name="Ch N2")
    content = create_available_content(runtime_seconds=540, title="Movie 540")
    get_success_data(
        api.create_rights_grant(
            factories.create_rights_grant_payload(
                channel["id"], content["id"],
                window_start_utc="2026-08-01T00:00:00Z",
                window_end_utc="2026-09-01T00:00:00Z", max_plays=5,
            ),
            LICENSING,
        )
    )
    resp = api.create_rights_grant(
        factories.create_rights_grant_payload(
            channel["id"], content["id"],
            window_start_utc="2026-08-15T00:00:00Z",
            window_end_utc="2026-08-20T00:00:00Z", max_plays=5,
        ),
        LICENSING,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW_OVERLAP)


def test_ops_run_expires_grants_at_window_end(api):
    """PRD §3.1: "The checkpoint increments the channel's `ops_run_index` by one,
    expires every rights grant whose `window_end_utc` is at or before the current
    logical time — whether the grant is still `PENDING` or already `ACTIVE`, both
    move to `EXPIRED` with the content re-evaluation cascade of §3.2". PRD §3.2:
    "Whenever a grant leaves the usable set — expired at an ops-run, exhausted at
    publish, or revoked — and no other grant for that content remains in `PENDING`
    or `ACTIVE`, an `AVAILABLE` asset transitions to `WINDOW_EXPIRED`."

    Design: Corner/cross_cutting_layers/ops_run_expires_grants_at_window_end
    """
    channel = create_channel(name="Ch OP")
    content = create_available_content(runtime_seconds=540, title="M540")
    grant = create_active_grant(
        channel["id"], content["id"], max_plays=5,
        window_start="2026-08-01T00:00:00Z", window_end="2026-08-20T00:00:00Z",
    )
    advance_clock("2026-08-19T00:00:00Z")
    api.channel_run_ops(channel["id"], ADMIN)
    assert get_grant(grant["id"])["grant_status"] == "ACTIVE", (
        "2026-08-19 < window_end 2026-08-20: grant survives"
    )
    assert get_channel(channel["id"])["ops_run_index"] == 1

    advance_clock("2026-08-20T00:00:00Z")
    api.channel_run_ops(channel["id"], ADMIN)
    assert get_grant(grant["id"])["grant_status"] == "EXPIRED", (
        "now >= window_end under half-open semantics"
    )
    assert get_content(content["id"])["content_status"] == "WINDOW_EXPIRED"
    assert get_channel(channel["id"])["ops_run_index"] == 2


def test_content_pull_reverts_validated_loops(api):
    """PRD §3.2: "That transition, like an explicit pull (`AVAILABLE` → `PULLED`),
    fires the loop-revert cascade: every playlist loop in `VALIDATED` or `LOCKED`
    status that contains an entry of this content reverts to `DRAFT`". PRD §3.4:
    "Reverting a validated loop (`VALIDATED` → `DRAFT`) voids every provisional fill
    decision on the loop's breaks — with no spend impact, since provisional
    decisions were never charged — and flips each break in `DECIDED` status that has
    no remaining provisional or committed decisions back to `MARKED`."

    Design: Corner/state_machines/content_pull_reverts_validated_loops
    """
    ctx = setup_validated_loop(channel_name="Ch PL", break_durations=(60,))
    campaign, _ = create_active_campaign(total_budget_cents=5000, daily_budget_cents=5000)
    decisions = run_decision_run(ctx["breaks"][0]["id"])
    assert decisions, "Setup failed: expected a DIRECT decision"

    get_success_data(api.content_pull(ctx["content"]["id"], LICENSING))
    assert get_content(ctx["content"]["id"])["content_status"] == "PULLED"
    assert get_loop(ctx["loop"]["id"])["loop_status"] == "DRAFT"
    assert get_decision(decisions[0]["id"])["decision_status"] == "VOIDED"
    assert get_break(ctx["breaks"][0]["id"])["break_status"] == "MARKED"


def test_publish_exhausts_grant_and_marks_it_exhausted(api):
    """PRD §3.4: "For each content, the covering grant's `plays_used` increases by
    the number of entries of that content, and a grant whose `plays_used` reaches
    `max_plays` flips to `EXHAUSTED`, firing the content re-evaluation of §3.2".
    With max_plays 1, publishing the first loop consumes the final play exactly.

    Design: Difficulty/transitive_cascade/r4_publish_plays_exhaustion_cascade_reverts_validated_loops
    """
    base = setup_channel_with_grant(
        channel_name="Ch H", loop_duration=600, content_runtime=540, max_plays=1,
    )
    l1 = create_loop(base["channel"]["id"], "2026-09-01")
    entries1, breaks1 = tile_loop(l1["id"], base["content"]["id"], (60,))
    get_success_data(api.loop_validate(l1["id"], PROGRAMMER))
    run_decision_run(breaks1[0]["id"])
    get_success_data(api.loop_lock(l1["id"], PROGRAMMER))
    go_live(base["channel"]["id"])

    published = publish_loop(l1["id"], base["channel"]["id"])
    assert published["loop_status"] == "PUBLISHED"
    grant = get_grant(base["grant"]["id"])
    assert grant["plays_used"] == 1
    assert grant["grant_status"] == "EXHAUSTED", (
        "plays_used >= max_plays at exact boundary"
    )


def test_publish_exhaustion_cascade_reverts_unrelated_validated_loop(api):
    """PRD §3.4: "a grant whose `plays_used` reaches `max_plays` flips to
    `EXHAUSTED`, firing the content re-evaluation of §3.2 — which may drive the
    asset to `WINDOW_EXPIRED` with its own loop-revert cascade." PRD §3.2: "every
    playlist loop in `VALIDATED` or `LOCKED` status that contains an entry of this
    content reverts to `DRAFT`".

    Design: Difficulty/transitive_cascade/r4_publish_plays_exhaustion_cascade_reverts_validated_loops
    """
    base = setup_channel_with_grant(
        channel_name="Ch H2", loop_duration=600, content_runtime=540, max_plays=1,
    )
    l1 = create_loop(base["channel"]["id"], "2026-09-01")
    _, breaks1 = tile_loop(l1["id"], base["content"]["id"], (60,))
    get_success_data(api.loop_validate(l1["id"], PROGRAMMER))
    run_decision_run(breaks1[0]["id"])
    get_success_data(api.loop_lock(l1["id"], PROGRAMMER))
    go_live(base["channel"]["id"])

    l2 = create_loop(base["channel"]["id"], "2026-09-02")
    tile_loop(l2["id"], base["content"]["id"], (60,))
    l2 = get_success_data(api.loop_validate(l2["id"], PROGRAMMER))
    assert l2["loop_status"] == "VALIDATED", "Setup failed: second loop must validate"

    publish_loop(l1["id"], base["channel"]["id"])
    assert get_content(base["content"]["id"])["content_status"] == "WINDOW_EXPIRED"
    assert get_loop(l2["id"])["loop_status"] == "DRAFT", (
        "cascade revert of a loop the publish never touched directly"
    )


def test_validate_rejected_when_rights_window_not_covering(api):
    """PRD §3.4: "Fourth, rights coverage: every entry's air window must be covered
    by a grant in `PENDING` or `ACTIVE` status for that (content, channel) pair" and
    "An entry with no covering window is rejected with
    `ERR_RIGHTS_WINDOW_VIOLATION`". The grant window ends 2026-08-20; the air date
    is 2026-09-01.

    Design: Corner/validations/validate_rejected_when_rights_window_not_covering
    """
    base = setup_channel_with_grant(
        channel_name="Ch RW", loop_duration=600, content_runtime=540,
        grant_window=("2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"),
    )
    loop = create_loop(base["channel"]["id"], "2026-09-01")
    tile_loop(loop["id"], base["content"]["id"], (60,))
    resp = api.loop_validate(loop["id"], PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_RIGHTS_WINDOW_VIOLATION)
    assert get_loop(loop["id"])["loop_status"] == "DRAFT"


def test_publish_rejected_when_plays_exhausted_between_validate_and_publish(api):
    """PRD §3.4: "per covering grant, the grant's `plays_used` plus the number of
    entries it covers in this loop must not exceed `max_plays`, with equality
    permitted; shortfalls surface as `ERR_RIGHTS_WINDOW_VIOLATION` or
    `ERR_PLAYS_EXHAUSTED` respectively." Both loops validated while 3 plays
    remained; the first publish consumed 2, leaving 1 for a loop that needs 2.

    Design: Corner/validations/publish_rejected_when_plays_exhausted_between_validate_and_publish
    """
    base = setup_channel_with_grant(
        channel_name="Ch PE", loop_duration=600, content_runtime=240, max_plays=3,
    )
    locked = []
    for date in ("2026-09-01", "2026-09-02"):
        loop = create_loop(base["channel"]["id"], date)
        get_success_data(
            api.loop_add_entry(loop["id"], {"content_id": base["content"]["id"]}, PROGRAMMER)
        )
        get_success_data(
            api.loop_add_entry(loop["id"], {"content_id": base["content"]["id"]}, PROGRAMMER)
        )
        brk = get_success_data(
            api.loop_add_ad_break(loop["id"], {"duration_seconds": 120}, PROGRAMMER)
        )
        get_success_data(api.loop_validate(loop["id"], PROGRAMMER))
        run_decision_run(brk["id"])
        get_success_data(api.loop_lock(loop["id"], PROGRAMMER))
        locked.append(loop)
    go_live(base["channel"]["id"])
    publish_loop(locked[0]["id"], base["channel"]["id"])
    grant = get_grant(base["grant"]["id"])
    assert grant["plays_used"] == 2 and grant["grant_status"] == "ACTIVE", (
        "Setup failed: first publish consumes 2 of 3 plays without exhaustion"
    )

    resp = api.loop_publish(
        locked[1]["id"],
        {"expected_channel_version": get_channel(base["channel"]["id"])["version"]},
        PROGRAMMER,
    )
    validate_error(resp, ApiErrorId.ERR_PLAYS_EXHAUSTED)
    assert get_loop(locked[1]["id"])["loop_status"] == "LOCKED"
