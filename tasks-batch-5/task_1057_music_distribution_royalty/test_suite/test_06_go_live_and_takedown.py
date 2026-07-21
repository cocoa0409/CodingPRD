"""Going live, and the takedown cascade that reaches from a store back to the release slot."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_release_ready_for_delivery, setup_delivered_release,
    queue_delivery, send_delivery, ack_delivery, confirm_takedown,
    read_release, read_track, read_artist, read_subscription, read_delivery,
    set_clock, make_ops_headers, make_artist_headers,
)


def test_go_live_before_the_release_date_is_refused(api):
    """PRD §3.5: "The editorial transition `APPROVED → LIVE` demands three things at once: the
    release's editorial `status` is `APPROVED`, its distribution `delivery_status` is `DELIVERED`,
    and the current instant has reached — is at or after — its `release_date`."
    PRD §3.5: "if the clock has not yet reached `release_date` that explicit attempt is refused
    with `ERR_RELEASE_DATE_NOT_REACHED` (HTTP 422), and if the release is not `APPROVED` or its
    distribution dimension is not yet `DELIVERED` it is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/go_live_before_release_date_is_rejected
    """
    world = setup_delivered_release(
        artist_overrides={"email": "antlia@example.com"},
        clock_at_ack="2026-07-25T00:00:00Z",
    )
    assert world["release"]["delivery_status"] == "DELIVERED"
    assert world["release"]["status"] == "APPROVED"

    resp = api.go_live_release(world["release_id"], make_ops_headers())
    validate_error(resp, ApiErrorId.ERR_RELEASE_DATE_NOT_REACHED.value)

    release = read_release(world["release_id"], world["artist_id"])
    assert release["status"] == "APPROVED"
    assert release["delivery_status"] == "DELIVERED"
    assert read_track(world["track"]["id"], world["artist_id"])["status"] == "PENDING"
    assert read_artist(world["artist_id"])["live_track_count"] == 0


def test_go_live_activates_tracks_while_delivery_dimension_stays_delivered(api):
    """PRD §3.5: "The editorial transition `APPROVED → LIVE` demands three things at once: the
    release's editorial `status` is `APPROVED`, its distribution `delivery_status` is `DELIVERED`,
    and the current instant has reached — is at or after — its `release_date`."
    PRD §3.5: "Whichever entry point fires, the effects are the same: every track of the release
    still sitting in `PENDING` is moved to `ACTIVE`, the owning artist's `live_track_count` is
    recomputed as the number of tracks in `ACTIVE` across all of that artist's releases, and the
    release's `version` advances by 1."

    Design: Difficulty/non_linear_state_machine/release_status_and_delivery_status_advance_independently
    """
    world = setup_delivered_release(
        artist_overrides={"email": "deneb2@example.com"},
        clock_at_ack="2026-07-25T00:00:00Z",
    )

    set_clock("2026-09-02T00:00:00Z")
    live = validate_success(api.go_live_release(world["release_id"], make_ops_headers()))

    assert live["status"] == "LIVE"
    assert live["delivery_status"] == "DELIVERED", (
        "the distribution dimension is unmoved by the editorial transition"
    )
    assert read_track(world["track"]["id"], world["artist_id"])["status"] == "ACTIVE"
    assert read_artist(world["artist_id"])["live_track_count"] == 1


def test_confirm_takedown_drives_release_to_taken_down_on_both_dimensions(api):
    """PRD §3.6: "The first hop moves the release's distribution dimension
    `DELIVERED → TAKEDOWN_PENDING` and moves every delivery of that release currently in
    `ACCEPTED` to `TAKEDOWN_REQUESTED`, advancing each such delivery's `version` by 1 as well as
    the release's own."
    PRD §3.6: "Confirming a takedown moves that delivery `TAKEDOWN_REQUESTED → TAKEN_DOWN`, stamps
    its `taken_down_at` with the current instant, and advances its `version` by 1."
    PRD §3.6: "At that point the release's `delivery_status` becomes `TAKEN_DOWN` and, as the
    third hop, its editorial `status` moves `LIVE → TAKEN_DOWN` with `taken_down_at` stamped on
    the release itself."

    Design: Difficulty/transitive_cascade/confirm_takedown_depth_four_cascade_to_subscription_slots
    """
    world = setup_delivered_release(
        artist_overrides={"email": "antares@example.com"},
        tracks=[{"title": "Red Star", "duration_seconds": 250,
                 "explicit": True, "content_id_enabled": True}],
        clock_at_ack="2026-09-02T00:00:00Z",
    )
    assert world["release"]["status"] == "LIVE"
    delivery_id = world["delivery"]["id"]

    requested = validate_success(
        api.takedown_release(world["release_id"], make_artist_headers(world["artist_id"]))
    )
    assert requested["delivery_status"] == "TAKEDOWN_PENDING"
    assert read_delivery(delivery_id)["status"] == "TAKEDOWN_REQUESTED"

    confirmed = validate_success(api.confirm_takedown(delivery_id, make_ops_headers()))

    assert confirmed["status"] == "TAKEN_DOWN"
    assert confirmed["taken_down_at"].startswith("2026-09-02T00:00:00")

    release = read_release(world["release_id"], world["artist_id"])
    assert release["delivery_status"] == "TAKEN_DOWN"
    assert release["status"] == "TAKEN_DOWN"
    assert release["taken_down_at"].startswith("2026-09-02T00:00:00")


def test_confirm_takedown_deactivates_tracks_and_frees_the_release_slot(api):
    """PRD §3.6: "The third hop drags a fourth behind it: every track of the release still in
    `ACTIVE` is moved to `INACTIVE` and has its `content_id_enabled` forced back to false, and
    because those tracks have left the active set, the owning artist's `live_track_count` is
    recomputed and the artist's subscription `releases_used` is recomputed too — a taken-down
    release no longer occupies a slot."
    PRD §3.6: "The second hop fires on whichever confirmation leaves no delivery of the release in
    `QUEUED`, `SENT`, `ACCEPTED` or `TAKEDOWN_REQUESTED` — in other words, when every delivery of
    the release now sits in either `TAKEN_DOWN` or `REJECTED`."

    Design: Difficulty/transitive_cascade/confirm_takedown_depth_four_cascade_to_subscription_slots
    """
    world = setup_delivered_release(
        artist_overrides={"email": "antares2@example.com"},
        tracks=[{"title": "Red Star", "duration_seconds": 250,
                 "explicit": True, "content_id_enabled": True}],
        clock_at_ack="2026-09-02T00:00:00Z",
    )
    assert read_artist(world["artist_id"])["live_track_count"] == 1
    assert read_subscription(world["subscription"]["id"])["releases_used"] == 1

    validate_success(
        api.takedown_release(world["release_id"], make_artist_headers(world["artist_id"]))
    )
    confirm_takedown(world["delivery"]["id"])

    track = read_track(world["track"]["id"], world["artist_id"])
    assert track["status"] == "INACTIVE"
    assert track["content_id_enabled"] is False
    assert read_artist(world["artist_id"])["live_track_count"] == 0
    assert read_subscription(world["subscription"]["id"])["releases_used"] == 0


def test_taken_down_release_cannot_be_taken_down_again(api):
    """PRD §3.6: "Either the owning artist or a `DistributionOps` operator initiates it, and it is
    permitted only while the release's `delivery_status` is `DELIVERED`; otherwise
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cannot_transition_out_of_terminal_taken_down_release
    """
    world = setup_delivered_release(
        artist_overrides={"email": "norma@example.com"},
        clock_at_ack="2026-09-02T00:00:00Z",
    )
    validate_success(
        api.takedown_release(world["release_id"], make_artist_headers(world["artist_id"]))
    )
    confirm_takedown(world["delivery"]["id"])

    resp = api.takedown_release(world["release_id"], make_artist_headers(world["artist_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    release = read_release(world["release_id"], world["artist_id"])
    assert release["status"] == "TAKEN_DOWN"
    assert release["delivery_status"] == "TAKEN_DOWN"
    assert release["taken_down_at"].startswith("2026-09-02T00:00:00")
