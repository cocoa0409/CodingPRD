"""Overlap geometry on dated resources.

Inventory feed windows are half-open instant intervals where exact adjacency is
legal, while blackout windows are fully-closed date intervals inflated by a
reopen buffer, where even a clear gap can collide.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_vendor,
    create_blackout_payload,
    create_inventory_snapshot_payload,
    make_vendor_user_headers,
    refresh_item,
    reset_clock,
    setup_vendor_with_active_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
OPS_HEADERS = TEST_USERS["vendor_ops_analyst_headers"]


def _post_snapshot(
    api,
    item_id,
    vendor_id,
    on_hand_units,
    effective_from,
    feed_sequence,
    effective_to=None,
):
    """Post one feed message as its own vendor, carrying the offer's live version."""
    current = refresh_item(api, item_id)
    payload = create_inventory_snapshot_payload(
        expected_item_version=current["version"],
        on_hand_units=on_hand_units,
        effective_from=effective_from,
        feed_sequence=feed_sequence,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return api.create_inventory_snapshot(
        item_id, payload, make_vendor_user_headers(vendor_id)
    )


def _offer_at_snapshot_clock(api, suffix):
    """An ACTIVE offer with no feed yet and the clock at 2026-08-03T09:00:00Z."""
    return setup_vendor_with_active_offer(
        api, suffix=suffix, feed=False, now_at="2026-08-03T09:00:00Z"
    )


def _two_adjacent_windows(api, suffix):
    """Window A closed at 2026-08-04T00:00:00Z, then window B opening there."""
    base = _offer_at_snapshot_clock(api, suffix)
    window_a = validate_success(
        _post_snapshot(
            api,
            base["item_id"],
            base["vendor_id"],
            on_hand_units=60,
            effective_from="2026-08-03T00:00:00Z",
            effective_to="2026-08-04T00:00:00Z",
            feed_sequence=1,
        ),
        201,
    )
    window_b = validate_success(
        _post_snapshot(
            api,
            base["item_id"],
            base["vendor_id"],
            on_hand_units=45,
            effective_from="2026-08-04T00:00:00Z",
            feed_sequence=2,
        ),
        201,
    )
    return base, window_a, window_b


def _post_blackout(api, vendor_id, start_date, end_date, reason, reopen_buffer_days):
    return api.create_blackout(
        vendor_id,
        create_blackout_payload(
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            reopen_buffer_days=reopen_buffer_days,
        ),
        OPS_HEADERS,
    )


def _vendor_with_first_blackout(api, suffix):
    """An ACTIVE vendor closed 2026-08-10 through 2026-08-12 with a two-day buffer."""
    reset_clock(api)
    vendor = create_active_vendor(api, suffix=suffix)
    window_a = validate_success(
        _post_blackout(
            api,
            vendor["id"],
            start_date="2026-08-10",
            end_date="2026-08-12",
            reason="HOLIDAY",
            reopen_buffer_days=2,
        ),
        201,
    )
    return vendor, window_a


# ─── Half-open feed windows ───────────────────────────


def test_feed_window_starting_where_the_previous_one_ends_is_accepted(api):
    """PRD §2.6: "Windows that merely touch — where one window's `effective_to` equals the next window's `effective_from` — are permitted."

    Window A runs to 2026-08-04T00:00:00Z exclusively and window B opens on that
    exact instant, so the two share no instant at all.

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    base, window_a, window_b = _two_adjacent_windows(api, "TS1")

    assert window_a["effective_to"] == window_b["effective_from"]
    assert window_a["status"] == "ACTIVE"
    assert window_b["status"] == "ACTIVE"
    assert window_b["effective_to"] is None


def test_feed_window_nested_inside_an_active_window_is_rejected(api):
    """PRD §3.4: "Because a window covers `effective_from` inclusively and stops just short of `effective_to`, two windows that share a single boundary instant do not overlap and are both accepted; anything that genuinely intersects is refused with `ERR_SNAPSHOT_WINDOW_OVERLAP`."

    Window C sits wholly inside window A, so it genuinely intersects and no third
    row survives.

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    base, window_a, window_b = _two_adjacent_windows(api, "TS2")

    response = _post_snapshot(
        api,
        base["item_id"],
        base["vendor_id"],
        on_hand_units=10,
        effective_from="2026-08-03T12:00:00Z",
        effective_to="2026-08-03T18:00:00Z",
        feed_sequence=3,
    )
    validate_error(response, ApiErrorId.ERR_SNAPSHOT_WINDOW_OVERLAP.value)

    rows, meta = validate_paginated(
        api.list_inventory_snapshots(base["item_id"], ADMIN_HEADERS, params={"limit": 100})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_a_closed_earlier_window_is_not_superseded_by_the_next_message(api):
    """PRD §3.4: "Posting one also closes the offer's previous open-ended message: any `ACTIVE` snapshot of the same offer whose window is strictly earlier and open-ended is moved `ACTIVE → SUPERSEDED` and has its `effective_to` closed at the new message's `effective_from`."

    Window A already carries an `effective_to`, so it is not open-ended and the
    arrival of window B leaves it ACTIVE with its own end instant intact.

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    base, window_a, window_b = _two_adjacent_windows(api, "TS3")

    rows, _ = validate_paginated(
        api.list_inventory_snapshots(base["item_id"], ADMIN_HEADERS, params={"limit": 100})
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[window_a["id"]]["status"] == "ACTIVE"
    assert by_id[window_a["id"]]["effective_to"] == window_b["effective_from"]
    assert by_id[window_b["id"]]["status"] == "ACTIVE"


def test_the_governing_window_supplies_the_trusted_on_hand_figure(api):
    """PRD §3.4: "`effective_on_hand_units` is 0 when there is no governing snapshot or when `inventory_is_stale` is true, and is otherwise the governing snapshot's `on_hand_units`."

    At 2026-08-03T09:00:00Z only window A contains the clock, so its 60 units are
    the trusted figure and window B's future 45 units are ignored.

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    base, window_a, window_b = _two_adjacent_windows(api, "TS4")

    offer = refresh_item(api, base["item_id"])
    assert offer["inventory_is_stale"] is False
    assert offer["effective_on_hand_units"] == 60


def test_availability_applies_the_safety_buffer_to_the_governing_window(api):
    """PRD §3.4: "For an `ACTIVE` offer it is the trusted on-hand figure reduced by the vendor's `safety_buffer_units`, increased by the vendor's `oversell_grace_units`, and reduced by the offer's `reserved_units`, with the whole result floored at 0 — the floor is applied once, after every other term."

    Sixty trusted units less a five-unit safety buffer, with no oversell grace and
    nothing reserved, leaves 55 orderable units.

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    base, window_a, window_b = _two_adjacent_windows(api, "TS5")

    offer = refresh_item(api, base["item_id"])
    assert offer["reserved_units"] == 0
    assert offer["available_units"] == 55


def test_a_rejected_overlapping_window_leaves_the_offer_version_untouched(api):
    """PRD §2.6: "No row is mutated when a request fails."

    Creation, activation and the two accepted feed messages take the offer to
    version 4; the refused nested window must not advance it.

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    base, window_a, window_b = _two_adjacent_windows(api, "TS6")
    assert refresh_item(api, base["item_id"])["version"] == 4

    validate_error(
        _post_snapshot(
            api,
            base["item_id"],
            base["vendor_id"],
            on_hand_units=10,
            effective_from="2026-08-03T12:00:00Z",
            effective_to="2026-08-03T18:00:00Z",
            feed_sequence=3,
        ),
        ApiErrorId.ERR_SNAPSHOT_WINDOW_OVERLAP.value,
    )

    assert refresh_item(api, base["item_id"])["version"] == 4


# ─── Closed blackout intervals with a reopen buffer ───


def test_blackout_gap_equal_to_the_reopen_buffer_is_rejected(api):
    """PRD §2.6: "A new blackout's fully-closed interval, running from `start_date` through `end_date` with both ends included, neither overlaps nor sits within `reopen_buffer_days` of any `ACTIVE` blackout of the same vendor: the new `start_date` must be later than the earlier window's `end_date` by strictly more than that earlier window's `reopen_buffer_days`, and intervals that merely touch are rejected."

    The existing window ends 2026-08-12 with a two-day buffer, so a candidate
    opening 2026-08-14 clears exactly two days — equal to the buffer, not more.

    Design: Difficulty/resource_temporal_overlap/blackout_closed_date_intervals_require_a_reopen_buffer_gap_strictly_greater_than_the_buffer
    """
    vendor, window_a = _vendor_with_first_blackout(api, "TB1")
    assert window_a["status"] == "ACTIVE"

    response = _post_blackout(
        api,
        vendor["id"],
        start_date="2026-08-14",
        end_date="2026-08-16",
        reason="CAPACITY",
        reopen_buffer_days=1,
    )
    validate_error(response, ApiErrorId.ERR_BLACKOUT_WINDOW_CONFLICT.value)


def test_blackout_gap_exceeding_the_reopen_buffer_is_accepted(api):
    """PRD §3.2: "A second window proposed for the very next day is rejected, and so is one proposed two days later, because the new `start_date` must be later than the earlier window's `end_date` by strictly more than that earlier window's `reopen_buffer_days`; only the third day clears."

    Against a window ending 2026-08-12 with a two-day buffer, the third clear day
    is 2026-08-15 and that candidate is admitted.

    Design: Difficulty/resource_temporal_overlap/blackout_closed_date_intervals_require_a_reopen_buffer_gap_strictly_greater_than_the_buffer
    """
    vendor, window_a = _vendor_with_first_blackout(api, "TB2")

    accepted = validate_success(
        _post_blackout(
            api,
            vendor["id"],
            start_date="2026-08-15",
            end_date="2026-08-16",
            reason="CAPACITY",
            reopen_buffer_days=1,
        ),
        201,
    )
    assert accepted["start_date"] == "2026-08-15"
    assert accepted["status"] == "ACTIVE"


def test_a_rejected_blackout_candidate_leaves_no_window_behind(api):
    """PRD §2.6: "No row is mutated when a request fails."

    The vendor ends up holding only the original window and the accepted third-day
    window; the conflicting candidate persisted nothing.

    Design: Difficulty/resource_temporal_overlap/blackout_closed_date_intervals_require_a_reopen_buffer_gap_strictly_greater_than_the_buffer
    """
    vendor, window_a = _vendor_with_first_blackout(api, "TB3")
    validate_error(
        _post_blackout(
            api,
            vendor["id"],
            start_date="2026-08-14",
            end_date="2026-08-16",
            reason="CAPACITY",
            reopen_buffer_days=1,
        ),
        ApiErrorId.ERR_BLACKOUT_WINDOW_CONFLICT.value,
    )
    validate_success(
        _post_blackout(
            api,
            vendor["id"],
            start_date="2026-08-15",
            end_date="2026-08-16",
            reason="CAPACITY",
            reopen_buffer_days=1,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_blackouts(
            vendor["id"], ADMIN_HEADERS, params={"status": "ACTIVE", "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["start_date"] for row in rows) == ["2026-08-10", "2026-08-15"]
