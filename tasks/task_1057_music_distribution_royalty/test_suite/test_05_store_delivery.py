"""Store delivery: queueing gates, dispatch, the reject/retry cycle and window capacity."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, assert_delivery,
    setup_world, setup_release_ready_for_delivery, lock_sheets_for_world,
    drive_release_to_approved, queue_delivery, send_delivery, ack_delivery, retry_delivery,
    create_split_sheet, add_share, send_sheet, accept_share, lock_sheet,
    read_delivery, read_release, read_track, create_collaborator, add_track,
    isrc, upc, make_ops_headers, make_artist_headers, make_admin_headers,
)


def test_queued_delivery_starts_clean_and_moves_the_release_to_queued(api):
    """PRD §3.6: "A successful queueing creates the delivery in `QUEUED` with `attempt_count` at 0
    and `last_error_code`, `sent_at` and `taken_down_at` all null, moves the release's
    `delivery_status` from `NONE` to `QUEUED` when it was still `NONE`, and advances the release's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/release_status_and_delivery_status_advance_independently
    """
    world = setup_release_ready_for_delivery(artist_overrides={"email": "orca0@example.com"})

    delivery = validate_success(
        api.queue_delivery(world["release_id"],
                           {"store_id": world["store"]["id"],
                            "scheduled_send_at": "2026-07-20T10:00:00Z"},
                           make_ops_headers()),
        201,
    )

    assert_delivery(delivery)
    assert delivery["status"] == "QUEUED"
    assert delivery["attempt_count"] == 0
    assert delivery["last_error_code"] is None
    assert delivery["sent_at"] is None
    assert delivery["taken_down_at"] is None

    release = read_release(world["release_id"], world["artist_id"])
    assert release["delivery_status"] == "QUEUED"
    assert release["status"] == "APPROVED", "the editorial dimension is untouched by queueing"


def test_distribution_dimension_walks_partial_then_delivered_while_editorial_stays_approved(api):
    """PRD §2.9: "A release may sit in `APPROVED` while its distribution dimension moves
    `NONE → QUEUED → PARTIAL → DELIVERED`, and only the arrival at `DELIVERED` can push the
    editorial dimension forward."
    PRD §3.6: "If at least one delivery of the release is now `ACCEPTED` while at least one
    sibling delivery remains in `QUEUED`, `SENT` or `REJECTED`, the release moves
    `QUEUED → PARTIAL`."
    PRD §3.6: "If instead every delivery of the release is now `ACCEPTED`, the release moves to
    `DELIVERED` — from `PARTIAL` when siblings were previously outstanding, or directly from
    `QUEUED` when the release had exactly one delivery all along."

    Design: Difficulty/non_linear_state_machine/release_status_and_delivery_status_advance_independently
    """
    world = setup_release_ready_for_delivery(
        artist_overrides={"email": "deneb@example.com"},
        extra_stores=[{"code": "APPLE", "name": "Apple Music", "delivery_lead_days": 5}],
    )
    store_spot, store_apple = world["stores"]
    del_spot = queue_delivery(world["release_id"], store_spot["id"], "2026-07-20T10:00:00Z")
    del_apple = queue_delivery(world["release_id"], store_apple["id"], "2026-07-20T10:00:00Z")
    send_delivery(del_spot["id"])
    send_delivery(del_apple["id"])

    validate_success(api.ack_delivery(del_spot["id"], "ACCEPTED", make_ops_headers()))
    after_first = read_release(world["release_id"], world["artist_id"])
    assert after_first["delivery_status"] == "PARTIAL"
    assert after_first["status"] == "APPROVED"

    validate_success(api.ack_delivery(del_apple["id"], "ACCEPTED", make_ops_headers()))
    after_second = read_release(world["release_id"], world["artist_id"])
    assert after_second["delivery_status"] == "DELIVERED"
    assert after_second["status"] == "APPROVED", (
        "the clock has not reached release_date, so the editorial axis stays put"
    )


def test_reject_then_retry_cycle_returns_the_delivery_to_queued(api):
    """PRD §3.6: "Dispatch moves the delivery `QUEUED → SENT`, raises `attempt_count` by 1, stamps
    `sent_at` with the current instant, and advances the delivery's `version` by 1."
    PRD §3.6: "A rejecting acknowledgement moves the delivery `SENT → REJECTED`, copies the
    supplied `error_code` into `last_error_code`, and advances `version` by 1."
    PRD §3.6: "A rejected delivery may be requeued for another attempt, moving it
    `REJECTED → QUEUED` and advancing `version` by 1, but only while `attempt_count` remains below
    3 — the third dispatch is the last one the platform will make, and a further retry attempt is
    refused with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/delivery_reject_retry_cycle_returns_to_queued
    """
    world = setup_release_ready_for_delivery(artist_overrides={"email": "rigel@example.com"})
    delivery = queue_delivery(world["release_id"], world["store"]["id"], "2026-07-20T10:00:00Z")

    sent = validate_success(api.send_delivery(delivery["id"], make_ops_headers()))
    assert sent["status"] == "SENT" and sent["attempt_count"] == 1

    rejected = validate_success(
        api.ack_delivery(delivery["id"], "REJECTED", make_ops_headers(), "META_INVALID")
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["last_error_code"] == "META_INVALID"

    requeued = validate_success(api.retry_delivery(delivery["id"], make_ops_headers()))
    assert requeued["status"] == "QUEUED", "the cycle revisits QUEUED"
    assert requeued["attempt_count"] == 1, "a retry does not itself count as a dispatch"


def test_second_dispatch_after_retry_can_be_accepted_and_clears_the_error(api):
    """PRD §3.6: "An accepting acknowledgement moves the delivery `SENT → ACCEPTED`, clears
    `last_error_code` back to null, advances the delivery's `version` by 1, and then recomputes
    the release's distribution dimension."
    PRD §3.6: "If instead every delivery of the release is now `ACCEPTED`, the release moves to
    `DELIVERED` — from `PARTIAL` when siblings were previously outstanding, or directly from
    `QUEUED` when the release had exactly one delivery all along."

    Design: Difficulty/non_linear_state_machine/delivery_reject_retry_cycle_returns_to_queued
    """
    world = setup_release_ready_for_delivery(artist_overrides={"email": "rigel2@example.com"})
    delivery = queue_delivery(world["release_id"], world["store"]["id"], "2026-07-20T10:00:00Z")
    send_delivery(delivery["id"])
    ack_delivery(delivery["id"], "REJECTED", error_code="META_INVALID")
    retry_delivery(delivery["id"])
    send_delivery(delivery["id"])

    accepted = validate_success(api.ack_delivery(delivery["id"], "ACCEPTED", make_ops_headers()))

    assert accepted["status"] == "ACCEPTED"
    assert accepted["attempt_count"] == 2, "two dispatches happened across the cycle"
    assert accepted["last_error_code"] is None

    release = read_release(world["release_id"], world["artist_id"])
    assert release["delivery_status"] == "DELIVERED"
    assert release["status"] == "APPROVED"


def test_retry_beyond_the_third_attempt_is_refused(api):
    """PRD §3.6: "A rejected delivery may be requeued for another attempt, moving it
    `REJECTED → QUEUED` and advancing `version` by 1, but only while `attempt_count` remains below
    3 — the third dispatch is the last one the platform will make, and a further retry attempt is
    refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/delivery_retry_beyond_max_attempts_is_rejected
    """
    world = setup_release_ready_for_delivery(artist_overrides={"email": "pictor@example.com"})
    delivery = queue_delivery(world["release_id"], world["store"]["id"], "2026-07-20T10:00:00Z")

    for code in ("E1", "E2"):
        send_delivery(delivery["id"])
        ack_delivery(delivery["id"], "REJECTED", error_code=code)
        retry_delivery(delivery["id"])
    send_delivery(delivery["id"])
    ack_delivery(delivery["id"], "REJECTED", error_code="E3")

    resp = api.retry_delivery(delivery["id"], make_ops_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    stored = read_delivery(delivery["id"])
    assert stored["status"] == "REJECTED"
    assert stored["attempt_count"] == 3
    assert stored["last_error_code"] == "E3"


def test_delivery_missing_explicit_and_isrc_reports_metadata_noncompliance_first(api):
    """PRD §3.6: "Five further gates guard queueing, and they are evaluated in the order given
    here, so a release that trips more than one reports the earliest."
    PRD §3.6: "First, if the destination store's `requires_explicit_flag` is true, every track of
    the release must carry a non-null `explicit` declaration; a single undeclared track fails the
    whole delivery with `ERR_METADATA_NONCOMPLIANT` (HTTP 422)."
    PRD §3.6: "Second, if the store's `requires_isrc` is true, every track must carry a non-null
    `isrc`, otherwise `ERR_ISRC_MISSING` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_delivery_create_with_missing_explicit_and_isrc
    """
    world = setup_world(
        artist_overrides={"email": "pavo@example.com"},
        tracks=[{"title": "Sail", "duration_seconds": 190, "isrc": None, "explicit": None}],
    )
    drive_release_to_approved(world["release_id"], world["artist_id"])

    resp = api.queue_delivery(
        world["release_id"],
        {"store_id": world["store"]["id"], "scheduled_send_at": "2026-07-20T10:00:00Z"},
        make_ops_headers(),
    )
    error = validate_error(resp, ApiErrorId.ERR_METADATA_NONCOMPLIANT.value)

    assert error["error_id"] != ApiErrorId.ERR_ISRC_MISSING.value, (
        "the explicit-flag gate is evaluated before the ISRC gate"
    )
    _rows, meta = validate_paginated(
        api.list_deliveries(make_ops_headers(), params={"release_id": world["release_id"]})
    )
    assert meta["total_count"] == 0
    assert read_release(world["release_id"], world["artist_id"])["delivery_status"] == "NONE"


def test_delivery_with_declared_explicit_but_missing_isrc_reports_isrc_missing(api):
    """PRD §3.6: "Second, if the store's `requires_isrc` is true, every track must carry a
    non-null `isrc`, otherwise `ERR_ISRC_MISSING` (HTTP 422)."
    PRD §3.6: "Five further gates guard queueing, and they are evaluated in the order given here,
    so a release that trips more than one reports the earliest."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_delivery_create_with_missing_explicit_and_isrc
    """
    world = setup_world(
        artist_overrides={"email": "pavo2@example.com"},
        tracks=[{"title": "Sail", "duration_seconds": 190, "isrc": None, "explicit": False}],
    )
    drive_release_to_approved(world["release_id"], world["artist_id"])

    resp = api.queue_delivery(
        world["release_id"],
        {"store_id": world["store"]["id"], "scheduled_send_at": "2026-07-20T10:00:00Z"},
        make_ops_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ISRC_MISSING.value)

    _rows, meta = validate_paginated(
        api.list_deliveries(make_ops_headers(), params={"release_id": world["release_id"]})
    )
    assert meta["total_count"] == 0


def test_delivery_to_isrc_requiring_store_without_isrc_rejected(api):
    """PRD §3.6: "Second, if the store's `requires_isrc` is true, every track must carry a
    non-null `isrc`, otherwise `ERR_ISRC_MISSING` (HTTP 422)."
    PRD §3.1: "`requires_isrc` records whether it refuses a delivery when any track of the release
    still has no recording code (default true)"

    Design: Corner/validations/delivery_to_isrc_requiring_store_without_isrc_rejected
    """
    world = setup_world(
        artist_overrides={"email": "hydrus@example.com"},
        tracks=[{"title": "Coilless", "duration_seconds": 168, "isrc": None, "explicit": False}],
    )
    drive_release_to_approved(world["release_id"], world["artist_id"])

    resp = api.queue_delivery(
        world["release_id"],
        {"store_id": world["store"]["id"], "scheduled_send_at": "2026-07-20T10:00:00Z"},
        make_ops_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ISRC_MISSING.value)

    _rows, meta = validate_paginated(
        api.list_deliveries(make_ops_headers(), params={"release_id": world["release_id"]})
    )
    assert meta["total_count"] == 0


def test_delivery_blocked_while_a_track_has_no_locked_split_sheet(api):
    """PRD §3.6: "Third, every track of the release must hold a split sheet in `LOCKED`, otherwise
    `ERR_SPLIT_SHEET_NOT_LOCKED` (HTTP 409) — this is the invariant that later guarantees every
    earning track has somewhere to send its money."

    Design: Difficulty/cross_entity_state_dependency/delivery_create_requires_every_track_split_sheet_locked
    """
    world = setup_world(
        artist_overrides={"email": "tucana@example.com"},
        tracks=[{"title": "Beak", "duration_seconds": 180},
                {"title": "Plume", "duration_seconds": 205}],
    )
    artist_id, payee = world["artist_id"], world["payee"]
    track_a, track_b = world["tracks"]

    sheet_a = create_split_sheet(track_a["id"], artist_id,
                                 read_track(track_a["id"], artist_id)["version"])
    share_a = add_share(sheet_a["id"], artist_id, payee["id"], 10000)
    send_sheet(sheet_a["id"], artist_id)
    accept_share(share_a["id"], payee["id"])
    lock_sheet(sheet_a["id"], artist_id)

    sheet_b = create_split_sheet(track_b["id"], artist_id,
                                 read_track(track_b["id"], artist_id)["version"])
    add_share(sheet_b["id"], artist_id, payee["id"], 10000)
    send_sheet(sheet_b["id"], artist_id)

    drive_release_to_approved(world["release_id"], artist_id)

    resp = api.queue_delivery(
        world["release_id"],
        {"store_id": world["store"]["id"], "scheduled_send_at": "2026-07-20T10:00:00Z"},
        make_ops_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_SPLIT_SHEET_NOT_LOCKED.value)

    assert read_track(track_b["id"], artist_id)["locked_split_sheet_id"] is None


def test_delivery_succeeds_once_the_last_split_sheet_reaches_locked(api):
    """PRD §3.6: "Third, every track of the release must hold a split sheet in `LOCKED`, otherwise
    `ERR_SPLIT_SHEET_NOT_LOCKED` (HTTP 409) — this is the invariant that later guarantees every
    earning track has somewhere to send its money."
    PRD §3.4: "A successful lock moves the sheet `PENDING_ACCEPTANCE → LOCKED`, stamps `locked_at`
    with the current instant, writes the sheet's identifier into the parent track's
    `locked_split_sheet_id`, and — this is the cascade that makes re-splitting possible — moves
    any other sheet of the same track that was in `LOCKED` to `SUPERSEDED`, advancing that
    superseded sheet's `version` by 1 as well as the newly locked sheet's own `version`."

    Design: Difficulty/cross_entity_state_dependency/delivery_create_requires_every_track_split_sheet_locked
    """
    world = setup_world(
        artist_overrides={"email": "tucana2@example.com"},
        tracks=[{"title": "Beak", "duration_seconds": 180},
                {"title": "Plume", "duration_seconds": 205}],
    )
    artist_id, payee = world["artist_id"], world["payee"]
    track_a, track_b = world["tracks"]

    sheet_a = create_split_sheet(track_a["id"], artist_id,
                                 read_track(track_a["id"], artist_id)["version"])
    share_a = add_share(sheet_a["id"], artist_id, payee["id"], 10000)
    send_sheet(sheet_a["id"], artist_id)
    accept_share(share_a["id"], payee["id"])
    lock_sheet(sheet_a["id"], artist_id)

    sheet_b = create_split_sheet(track_b["id"], artist_id,
                                 read_track(track_b["id"], artist_id)["version"])
    share_b = add_share(sheet_b["id"], artist_id, payee["id"], 10000)
    send_sheet(sheet_b["id"], artist_id)
    drive_release_to_approved(world["release_id"], artist_id)

    blocked = api.queue_delivery(
        world["release_id"],
        {"store_id": world["store"]["id"], "scheduled_send_at": "2026-07-20T10:00:00Z"},
        make_ops_headers(),
    )
    validate_error(blocked, ApiErrorId.ERR_SPLIT_SHEET_NOT_LOCKED.value)

    accept_share(share_b["id"], payee["id"])
    locked = lock_sheet(sheet_b["id"], artist_id)
    assert locked["status"] == "LOCKED"
    assert read_track(track_b["id"], artist_id)["locked_split_sheet_id"] == sheet_b["id"]

    delivery = validate_success(
        api.queue_delivery(
            world["release_id"],
            {"store_id": world["store"]["id"], "scheduled_send_at": "2026-07-20T10:00:00Z"},
            make_ops_headers(),
        ),
        201,
    )
    assert delivery["status"] == "QUEUED"
    assert read_release(world["release_id"], artist_id)["delivery_status"] == "QUEUED"


def test_delivery_lead_time_accepts_exact_equality_and_rejects_one_second_later(api):
    """PRD §3.6: "Fourth, the schedule must respect the store's lead time: `scheduled_send_at`
    advanced by the store's `delivery_lead_days` whole days must fall at or before the release's
    `release_date`, with exact equality accepted; a schedule that would arrive too late is refused
    with `ERR_DELIVERY_LEAD_TIME_VIOLATION` (HTTP 422)."

    Design: Corner/validations/delivery_lead_time_passes_at_exact_equality_and_fails_one_second_later
    """
    world = setup_release_ready_for_delivery(artist_overrides={"email": "grus@example.com"})

    ok = validate_success(
        api.queue_delivery(world["release_id"],
                           {"store_id": world["store"]["id"],
                            "scheduled_send_at": "2026-08-27T00:00:00Z"},
                           make_ops_headers()),
        201,
    )
    assert ok["status"] == "QUEUED", "five whole days ahead of the release date is exact equality"

    late = api.queue_delivery(
        world["release_id"],
        {"store_id": world["store"]["id"], "scheduled_send_at": "2026-08-27T00:00:01Z"},
        make_ops_headers(),
    )
    validate_error(late, ApiErrorId.ERR_DELIVERY_LEAD_TIME_VIOLATION.value)

    _rows, meta = validate_paginated(
        api.list_deliveries(make_ops_headers(), params={"release_id": world["release_id"]})
    )
    assert meta["total_count"] == 1


def test_store_window_saturates_when_two_buffered_windows_already_intersect(api):
    """PRD §3.6: "on its store: the window opens 15 minutes before the delivery's
    `scheduled_send_at` and closes 75 minutes after it — that is, the 60-minute processing window
    plus the same 15-minute buffer on the trailing side."
    PRD §3.6: "Before a new delivery row is created, the platform counts the existing deliveries
    on that same store whose `status` is either `QUEUED` or `SENT` and whose buffer-expanded
    window has a non-empty intersection with the new one; deliveries that have already been
    accepted, rejected, marked for takedown or taken down no longer occupy the store and are not
    counted."
    PRD §3.6: "If that count is greater than or equal to the store's `max_concurrent_deliveries`,
    the request is refused with `ERR_STORE_WINDOW_SATURATED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/store_buffered_window_aggregate_capacity_saturation
    """
    world = setup_release_ready_for_delivery(artist_overrides={"email": "orca@example.com"})
    store_id = world["store"]["id"]
    del_1 = queue_delivery(world["release_id"], store_id, "2026-08-01T10:00:00Z")
    del_2 = queue_delivery(world["release_id"], store_id, "2026-08-01T11:00:00Z")

    resp = api.queue_delivery(
        world["release_id"], {"store_id": store_id, "scheduled_send_at": "2026-08-01T11:10:00Z"},
        make_ops_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STORE_WINDOW_SATURATED.value)

    assert read_delivery(del_1["id"])["scheduled_send_at"].startswith("2026-08-01T10:00:00")
    assert read_delivery(del_2["id"])["scheduled_send_at"].startswith("2026-08-01T11:00:00")
    _rows, meta = validate_paginated(
        api.list_deliveries(make_ops_headers(), params={"store_id": store_id})
    )
    assert meta["total_count"] == 2


def test_window_touching_an_open_right_edge_does_not_intersect_and_is_accepted(api):
    """PRD §3.6: "on its store: the window opens 15 minutes before the delivery's
    `scheduled_send_at` and closes 75 minutes after it — that is, the 60-minute processing window
    plus the same 15-minute buffer on the trailing side."
    PRD §3.6: "The window is closed at its opening instant and open at its closing instant, so two
    windows that merely touch endpoint-to-endpoint do"
    PRD §3.6: "If that count is greater than or equal to the store's `max_concurrent_deliveries`,
    the request is refused with `ERR_STORE_WINDOW_SATURATED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/store_buffered_window_aggregate_capacity_saturation
    """
    world = setup_release_ready_for_delivery(artist_overrides={"email": "orca2@example.com"})
    store_id = world["store"]["id"]
    queue_delivery(world["release_id"], store_id, "2026-08-01T10:00:00Z")
    queue_delivery(world["release_id"], store_id, "2026-08-01T11:00:00Z")

    saturated = api.queue_delivery(
        world["release_id"], {"store_id": store_id, "scheduled_send_at": "2026-08-01T11:10:00Z"},
        make_ops_headers(),
    )
    validate_error(saturated, ApiErrorId.ERR_STORE_WINDOW_SATURATED.value)

    accepted = validate_success(
        api.queue_delivery(
            world["release_id"],
            {"store_id": store_id, "scheduled_send_at": "2026-08-01T11:30:00Z"},
            make_ops_headers()),
        201,
    )
    assert accepted["status"] == "QUEUED", (
        "the 11:30 window opens exactly where the 10:00 window's open right edge closes"
    )

    _rows, meta = validate_paginated(
        api.list_deliveries(make_ops_headers(), params={"store_id": store_id})
    )
    assert meta["total_count"] == 3
