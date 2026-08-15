"""Playlist loop construction: initial state, offset walk, capacity guards,
referential checks, and exact-second tiling (PRD §3.3, §3.4)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    factories,
    create_channel,
    create_available_content,
    create_active_grant,
    create_loop,
    tile_loop,
    setup_channel_with_grant,
    setup_validated_loop,
    setup_locked_loop,
    run_decision_run,
    go_live,
    advance_clock,
    get_loop,
    get_break,
    get_channel,
)

ADMIN = TEST_USERS["admin_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]
LICENSING = TEST_USERS["licensing_headers"]


def test_loop_create_starts_in_draft(api):
    """PRD §3.3: "A new loop starts in `DRAFT` with `used_seconds` at 0,
    `validated_at` and `published_at` null, and `supersedes_loop_id` null."

    Design: Corner/state_machines/loop_create_starts_in_draft
    """
    channel = create_channel(name="Ch Init")
    loop = get_success_data(
        api.create_playlist_loop(
            factories.create_playlist_loop_payload(channel["id"]), PROGRAMMER
        )
    )
    assert loop["loop_status"] == "DRAFT"
    assert loop["used_seconds"] == 0
    assert loop.get("published_at") is None
    assert loop.get("validated_at") is None


def test_loop_offset_walk_recomputes_positions(api):
    """PRD §3.3: "The walk visits entries in ascending `sequence_index`, carrying a
    running offset that starts at zero." ... "The loop's `used_seconds` is the final
    value of the running offset." A 540s entry followed by a 60s break places the
    entry at [0, 540) and the break at 540.

    Design: Corner/entities/loop_offset_walk_recomputes_positions
    """
    base = setup_channel_with_grant(channel_name="Ch Walk", content_runtime=540)
    loop = create_loop(base["channel"]["id"], "2026-09-01")
    entries, breaks = tile_loop(loop["id"], base["content"]["id"], (60,))
    entry, brk = entries[0], breaks[0]
    assert entry["sequence_index"] == 0
    assert entry["start_offset_seconds"] == 0
    assert entry["end_offset_seconds"] == 540
    assert brk["start_offset_seconds"] == 540
    assert brk["after_entry_index"] == 1
    assert get_loop(loop["id"])["used_seconds"] == 600


def test_duplicate_loop_date_rejected(api):
    """PRD §3.3: "Only one loop per (channel, broadcast date) may exist in `DRAFT`,
    `VALIDATED`, or `LOCKED` status at a time; a second attempt is rejected with
    `ERR_DUPLICATE_LOOP_DATE`."

    Design: Corner/validations/duplicate_loop_date_rejected
    """
    channel = create_channel(name="Ch DL")
    create_loop(channel["id"], "2026-09-01")
    resp = api.create_playlist_loop(
        factories.create_playlist_loop_payload(channel["id"], broadcast_date="2026-09-01"),
        PROGRAMMER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOOP_DATE)


def test_loop_create_with_past_broadcast_date_rejected(api):
    """PRD §3.3: "A `broadcast_date` earlier than the current logical date is
    rejected with `ERR_BROADCAST_DATE_IN_PAST`". At logical 2026-09-02 a loop for
    2026-09-01 is already in the past.

    Design: Corner/validations/loop_create_with_past_broadcast_date_rejected
    """
    channel = create_channel(name="Ch PD")
    advance_clock("2026-09-02T00:00:00Z")
    resp = api.create_playlist_loop(
        factories.create_playlist_loop_payload(channel["id"], broadcast_date="2026-09-01"),
        PROGRAMMER,
    )
    validate_error(resp, ApiErrorId.ERR_BROADCAST_DATE_IN_PAST)


def test_loop_overflow_entry_rejected(api):
    """PRD §3.3: "Adding an entry or marking a break that would push the loop's
    `used_seconds` beyond the channel's `loop_duration_seconds` is rejected with
    `ERR_LOOP_OVERFLOW`." A second 540s entry would take the 600s loop to 1080.

    Design: Corner/validations/loop_overflow_entry_rejected
    """
    channel = create_channel(name="Ch OF2")
    content = create_available_content(runtime_seconds=540, title="M540")
    loop = create_loop(channel["id"], "2026-09-01")
    get_success_data(api.loop_add_entry(loop["id"], {"content_id": content["id"]}, PROGRAMMER))
    resp = api.loop_add_entry(loop["id"], {"content_id": content["id"]}, PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_LOOP_OVERFLOW)
    assert get_loop(loop["id"])["used_seconds"] == 540


def test_break_duration_not_multiple_of_slot_rejected(api):
    """PRD §3.3: "a `duration_seconds`, which must be a multiple of 30 and lie
    between 30 and 240 inclusive — anything else is rejected with
    `ERR_BREAK_DURATION_INVALID`." 45 seconds is not a multiple of 30.

    Design: Corner/validations/break_duration_not_multiple_of_slot_rejected
    """
    channel = create_channel(name="Ch BD")
    content = create_available_content(runtime_seconds=540, title="M")
    loop = create_loop(channel["id"], "2026-09-01")
    get_success_data(api.loop_add_entry(loop["id"], {"content_id": content["id"]}, PROGRAMMER))
    resp = api.loop_add_ad_break(loop["id"], {"duration_seconds": 45}, PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_BREAK_DURATION_INVALID)


def test_ad_capacity_cap_25_percent_enforced(api):
    """PRD §3.3: "And marking a break that would push the loop's total break seconds
    beyond the ad-capacity fraction — one quarter of the loop duration — is rejected
    with `ERR_AD_CAPACITY_EXCEEDED`." Two 60s breaks total 120 <= 150; the third
    would reach 180 > floor(600 * 25 / 100) == 150.

    Design: Corner/validations/ad_capacity_cap_25_percent_enforced
    """
    channel = create_channel(name="Ch AC")
    content = create_available_content(runtime_seconds=420, title="M420")
    loop = create_loop(channel["id"], "2026-09-01")
    get_success_data(api.loop_add_entry(loop["id"], {"content_id": content["id"]}, PROGRAMMER))
    get_success_data(api.loop_add_ad_break(loop["id"], {"duration_seconds": 60}, PROGRAMMER))
    get_success_data(api.loop_add_ad_break(loop["id"], {"duration_seconds": 60}, PROGRAMMER))
    resp = api.loop_add_ad_break(loop["id"], {"duration_seconds": 60}, PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_AD_CAPACITY_EXCEEDED)


def test_entry_add_with_missing_content_returns_reference_not_found(api):
    """PRD §2.9: "a body reference that points at a non-existent resource is
    rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

    Design: Corner/validations/entry_add_with_missing_content_returns_reference_not_found
    """
    channel = create_channel(name="Ch RF")
    loop = create_loop(channel["id"], "2026-09-01")
    resp = api.loop_add_entry(loop["id"], {"content_id": NON_EXISTENT_UUID}, PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_entry_add_rejected_when_content_not_available(api):
    """PRD §3.3: "The content must be `AVAILABLE`, else
    `ERR_CONTENT_NOT_AVAILABLE`."

    Design: Corner/validations/entry_add_rejected_when_content_not_available
    """
    channel = create_channel(name="Ch NA")
    content = get_success_data(
        api.create_content_asset(
            factories.create_content_asset_payload(title="Unready"), LICENSING
        )
    )
    assert content["content_status"] == "INGESTING", "Setup failed: never marked available"
    loop = create_loop(channel["id"], "2026-09-01")
    resp = api.loop_add_entry(loop["id"], {"content_id": content["id"]}, PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_AVAILABLE)
    assert get_loop(loop["id"])["used_seconds"] == 0


def test_validate_succeeds_at_exact_second_tiling(api):
    """PRD §3.4: "First, exact tiling: `used_seconds` must equal the channel's
    `loop_duration_seconds` exactly — one second under or over fails with
    `ERR_LOOP_NOT_TILED`." 540s entry + 60s break tiles 600 exactly.

    Design: Difficulty/boundary_precision_check/r6_loop_validate_requires_exact_second_tiling
    """
    ctx = setup_validated_loop(channel_name="Ch K", break_durations=(60,))
    assert ctx["loop"]["loop_status"] == "VALIDATED"
    assert ctx["loop"]["used_seconds"] == 600
    assert ctx["loop"].get("validated_at"), "validate stamps validated_at (PRD §3.4)"


def test_validate_fails_one_slot_short_of_tiling(api):
    """PRD §3.4: "`used_seconds` must equal the channel's `loop_duration_seconds`
    exactly — one second under or over fails with `ERR_LOOP_NOT_TILED`." A 540s
    entry plus a 30s break reaches only 570 of 600.

    Design: Difficulty/boundary_precision_check/r6_loop_validate_requires_exact_second_tiling
    """
    base = setup_channel_with_grant(channel_name="Ch K2", content_runtime=540)
    loop = create_loop(base["channel"]["id"], "2026-09-01")
    tile_loop(loop["id"], base["content"]["id"], (30,))
    resp = api.loop_validate(loop["id"], PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_LOOP_NOT_TILED)
    assert get_loop(loop["id"])["loop_status"] == "DRAFT"


def test_lock_requires_all_breaks_decided(api):
    """PRD §3.4: "The posture must again not be `FROZEN`, and every ad break of the
    loop must be in `DECIDED` status." Locking a VALIDATED loop whose only break is
    still MARKED is rejected; PRD §2.10: "State-transition legality: the trigger
    must be valid from the resource's current state, including terminal-state
    lockdown, else `ERR_INVALID_STATE_TRANSITION`".

    Design: Corner/state_machines/lock_requires_all_breaks_decided
    """
    ctx = setup_validated_loop(channel_name="Ch LK", break_durations=(60,))
    resp = api.loop_lock(ctx["loop"]["id"], PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_loop(ctx["loop"]["id"])["loop_status"] == "VALIDATED"
    assert get_break(ctx["breaks"][0]["id"])["break_status"] == "MARKED"


def test_publish_from_validated_loop_rejected(api):
    """PRD §3.4: "Publishing (`LOCKED` → `PUBLISHED`) puts the loop on air." A
    VALIDATED loop is not LOCKED; PRD §2.10: "State-transition legality: the trigger
    must be valid from the resource's current state, including terminal-state
    lockdown, else `ERR_INVALID_STATE_TRANSITION`". (The channel is taken LIVE via a
    separate locked loop so only the loop-state check can fail.)

    Design: Corner/state_machines/publish_from_validated_loop_rejected
    """
    base = setup_channel_with_grant(channel_name="Ch PV", content_runtime=540)
    # Bring the channel LIVE through a fully locked loop for another date.
    live_loop = create_loop(base["channel"]["id"], "2026-09-02")
    _, live_breaks = tile_loop(live_loop["id"], base["content"]["id"], (60,))
    get_success_data(api.loop_validate(live_loop["id"], PROGRAMMER))
    run_decision_run(live_breaks[0]["id"])
    get_success_data(api.loop_lock(live_loop["id"], PROGRAMMER))
    go_live(base["channel"]["id"])

    pending_loop = create_loop(base["channel"]["id"], "2026-09-01")
    tile_loop(pending_loop["id"], base["content"]["id"], (60,))
    pending_loop = get_success_data(api.loop_validate(pending_loop["id"], PROGRAMMER))
    assert pending_loop["loop_status"] == "VALIDATED", "Setup failed: loop must validate"

    resp = api.loop_publish(
        pending_loop["id"],
        {"expected_channel_version": get_channel(base["channel"]["id"])["version"]},
        PROGRAMMER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_loop(pending_loop["id"])["loop_status"] == "VALIDATED"
