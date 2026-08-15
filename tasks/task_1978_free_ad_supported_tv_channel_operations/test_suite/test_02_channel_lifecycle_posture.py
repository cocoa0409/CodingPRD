"""Channel creation defaults, lifecycle preconditions, and the two independent
state dimensions channel_status x channel_posture (PRD §2.6, §3.1)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    factories,
    create_channel,
    setup_published_loop,
    advance_clock,
    get_channel,
    assert_channel,
)

ADMIN = TEST_USERS["admin_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]
LICENSING = TEST_USERS["licensing_headers"]


def test_channel_create_applies_documented_defaults(api):
    """PRD §3.1: "it defaults to 86400 — one full day — and must be positive.
    `refresh_cadence_days`, defaulting to 7" ... "`ad_separation_window_seconds`,
    defaulting to 600" ... "`avg_slot_impressions`, defaulting to 1000" and
    "A new channel starts in `DRAFT` status with posture `ACTIVE`, an
    `ops_run_index` of 0, and `last_published_on` null until its first publish."

    Design: Corner/entities/channel_create_applies_documented_defaults
    """
    get_success_data(
        api.create_distributor_platform(
            factories.create_distributor_platform_payload(name="Seed"), ADMIN
        )
    )
    channel = get_success_data(
        api.create_channel(
            factories.create_channel_payload(name="Ch Defaults"), ADMIN
        )
    )
    assert_channel(channel)
    assert channel["loop_duration_seconds"] == 86400
    assert channel["refresh_cadence_days"] == 7
    assert channel["ad_separation_window_seconds"] == 600
    assert channel["avg_slot_impressions"] == 1000
    assert channel["channel_status"] == "DRAFT"
    assert channel["channel_posture"] == "ACTIVE"
    assert channel["ops_run_index"] == 0
    assert channel.get("last_published_on") is None


def test_channel_create_missing_name_returns_invalid_request(api):
    """PRD §2.10: "Request body shape: required fields present, enum values valid,
    and numeric ranges respected (for example `max_plays` must be positive,
    `runtime_seconds` must be positive, and revenue-share basis points outside
    0..6000 are reported as `ERR_REV_SHARE_OUT_OF_RANGE`), else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/channel_create_missing_name_returns_invalid_request
    """
    resp = api.create_channel({"genre": "movies", "timezone": "UTC"}, ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_channel_create_client_id_input_ignored(api):
    """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."

    Design: Corner/entities/channel_create_client_id_input_ignored
    """
    payload = factories.create_channel_payload(name="Ch Sys")
    payload["id"] = "client-supplied"
    channel = get_success_data(api.create_channel(payload, ADMIN))
    assert channel["id"] != "client-supplied"
    assert is_valid_uuid(channel["id"]), "the server mints the id"


def test_channel_get_missing_id_returns_not_found(api):
    """PRD §2.9: "the system validates the existence of each identifier in strict
    left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at
    the first identifier that does not correspond to an existing resource, without
    examining later identifiers."

    Design: Corner/entities/channel_get_missing_id_returns_not_found
    """
    create_channel(name="Ch Real")
    resp = api.get_channel("00000000-0000-0000-0000-000000000000", ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_channel_go_live_without_locked_loop_rejected(api):
    """PRD §3.1: "Going live — `DRAFT` → `LIVE` — is permitted only once the channel
    has at least one playlist loop in `LOCKED` or `PUBLISHED` status whose
    `broadcast_date` is on or after the current logical date." and "any attempt to
    drive a transition from a state where it is not defined is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/channel_go_live_without_locked_loop_rejected
    """
    channel = create_channel(name="Ch GL")
    resp = api.channel_go_live(channel["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_channel(channel["id"])["channel_status"] == "DRAFT"


def test_frozen_channel_after_grant_revoke_under_published_loop(api):
    """PRD §2.6: "The posture is `FROZEN` when there exists a published loop of the
    channel containing an entry whose air window lacks a covering active rights
    grant." PRD §3.2: "Revoking a grant (`PENDING` or `ACTIVE` → `REVOKED`) triggers
    two evaluations: every channel with a published loop containing an entry whose
    air window this grant covered is evaluated for the frozen rule of §2.6, and the
    content is re-evaluated as follows."

    Design: Corner/validations/frozen_channel_blocks_loop_create
    """
    ctx = setup_published_loop(channel_name="Ch FZ", break_durations=(60,))
    get_success_data(api_client.grant_revoke(ctx["grant"]["id"], LICENSING))
    channel = get_channel(ctx["channel"]["id"])
    assert channel["channel_posture"] == "FROZEN", (
        "published loop's entry lost its covering ACTIVE grant at revoke"
    )
    assert get_channel(ctx["channel"]["id"])["channel_status"] == "LIVE"


def test_run_ops_marks_channel_guarded_while_still_live(api):
    """PRD §2.6: "Otherwise it is `GUARDED` when the channel is `LIVE` and has never
    published a loop (its `last_published_on` is null), or when the current logical
    date is strictly later than `last_published_on` plus the channel's
    `refresh_cadence_days`". Published 2026-08-01 with cadence 7; at 2026-08-09 the
    posture flips while the lifecycle dimension stays LIVE.

    Design: Difficulty/non_linear_state_machine/r3_channel_status_and_posture_independent_dimensions
    """
    ctx = setup_published_loop(
        channel_name="Ch F", break_durations=(60,),
        channel_overrides={"refresh_cadence_days": 7},
    )
    assert ctx["channel"]["last_published_on"] == "2026-08-01"
    advance_clock("2026-08-09T00:00:00Z")
    api_client.channel_run_ops(ctx["channel"]["id"], ADMIN)
    channel = get_channel(ctx["channel"]["id"])
    assert channel["channel_posture"] == "GUARDED"
    assert channel["channel_status"] == "LIVE"


def test_suspend_resume_toggle_status_without_touching_guarded_posture(api):
    """PRD §2.6: "Mutations on one dimension never rewrite the other; a channel can
    be `LIVE` and `FROZEN` at once, and taking a channel offline does not change its
    posture." Suspend then resume a GUARDED channel: the lifecycle dimension moves,
    the posture stays GUARDED.

    Design: Difficulty/non_linear_state_machine/r3_channel_status_and_posture_independent_dimensions
    """
    ctx = setup_published_loop(
        channel_name="Ch F2", break_durations=(60,),
        channel_overrides={"refresh_cadence_days": 7},
    )
    advance_clock("2026-08-09T00:00:00Z")
    api_client.channel_run_ops(ctx["channel"]["id"], ADMIN)
    channel_id = ctx["channel"]["id"]

    get_success_data(api_client.channel_suspend(channel_id, ADMIN))
    channel = get_channel(channel_id)
    assert channel["channel_status"] == "SUSPENDED"
    assert channel["channel_posture"] == "GUARDED"

    get_success_data(api_client.channel_resume(channel_id, ADMIN))
    channel = get_channel(channel_id)
    assert channel["channel_status"] == "LIVE"
    assert channel["channel_posture"] == "GUARDED"


def test_staleness_boundary_equality_is_not_stale(api):
    """PRD §2.6: "or when the current logical date is strictly later than
    `last_published_on` plus the channel's `refresh_cadence_days` — on the exact
    date `last_published_on` plus the cadence the channel is not stale, because the
    comparison is strict." Published 2026-08-01, cadence 7, ops-run at 2026-08-08
    leaves posture ACTIVE.

    Design: Difficulty/boundary_precision_check/r6_refresh_staleness_strictly_greater_than_cadence
    """
    ctx = setup_published_loop(
        channel_name="Ch L", break_durations=(60,),
        channel_overrides={"refresh_cadence_days": 7},
    )
    advance_clock("2026-08-08T00:00:00Z")
    api_client.channel_run_ops(ctx["channel"]["id"], ADMIN)
    channel = get_channel(ctx["channel"]["id"])
    assert channel["channel_posture"] == "ACTIVE"


def test_staleness_one_day_past_cadence_flips_guarded(api):
    """PRD §2.6: "on the exact date `last_published_on` plus the cadence the channel
    is not stale, because the comparison is strict." One day past that boundary the
    ops-run flips the posture to GUARDED (strictly greater).

    Design: Difficulty/boundary_precision_check/r6_refresh_staleness_strictly_greater_than_cadence
    """
    ctx = setup_published_loop(
        channel_name="Ch L2", break_durations=(60,),
        channel_overrides={"refresh_cadence_days": 7},
    )
    advance_clock("2026-08-09T00:00:00Z")
    api_client.channel_run_ops(ctx["channel"]["id"], ADMIN)
    channel = get_channel(ctx["channel"]["id"])
    assert channel["channel_posture"] == "GUARDED"
    assert channel["channel_status"] == "LIVE"
