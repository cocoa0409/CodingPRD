"""Calendar blocks, rate-plan windows, channel sync, imports, and the
calendar-version OCC + channel-bump cascades.

Covers difficulty rule resource_temporal_overlap (both halves) plus corner
state_machines / errors / cross_cutting channel and calendar instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_host_headers, make_guest_headers, admin_headers,
    create_host, create_guest, create_draft_listing, create_listed_listing,
    add_rate_plan, create_connected_channel, create_manual_block,
    get_calendar_version, create_booking,
    create_calendar_block_payload, create_rate_plan_payload,
    create_imported_reservation_payload, create_channel_connection_payload,
)


# ==========================================================================
# Difficulty: resource_temporal_overlap (calendar block half-open + gap buffer)
# ==========================================================================
def test_calendar_block_insufficient_gap_rejected(api):
    """PRD §3.3: "the requested half-open `[start_date, end_date)` must not
    overlap any existing `ACTIVE` block on the listing, and it must honor the
    listing's `gap_nights` buffer on both sides — there must be at least
    `gap_nights` nights of clearance between this interval and the nearest
    `ACTIVE` block before it and after it. A violation of either the overlap rule
    or the gap buffer yields `ERR_DATES_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/calendar_block_halfopen_with_gap_buffer
    """
    host = create_host()
    _, listing = create_draft_listing(host=host, listing_overrides={"gap_nights": 2})
    # Existing ACTIVE block [2026-08-10, 2026-08-13).
    create_manual_block(host, listing, start_date="2026-08-10", end_date="2026-08-13")
    # New block ending 2026-08-09 leaves only 1 gap night before existing -> reject.
    cv = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))
    resp = api.create_calendar_block(
        listing["id"],
        create_calendar_block_payload(cv, source="MANUAL",
                                      start_date="2026-08-05", end_date="2026-08-09"),
        headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_DATES_UNAVAILABLE.value)


def test_calendar_block_sufficient_gap_succeeds(api):
    """PRD §3.3: "it must honor the listing's `gap_nights` buffer on both sides —
    there must be at least `gap_nights` nights of clearance between this interval
    and the nearest `ACTIVE` block before it and after it."

    Boundary: a block ending 2026-08-08 leaves exactly gap_nights=2 clearance
    before the existing [2026-08-10,...) block and is accepted.

    Design: Difficulty/resource_temporal_overlap/calendar_block_halfopen_with_gap_buffer
    """
    host = create_host()
    _, listing = create_draft_listing(host=host, listing_overrides={"gap_nights": 2})
    create_manual_block(host, listing, start_date="2026-08-10", end_date="2026-08-13")
    cv = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))
    resp = api.create_calendar_block(
        listing["id"],
        create_calendar_block_payload(cv, source="MANUAL",
                                      start_date="2026-08-05", end_date="2026-08-08"),
        headers=make_host_headers(host["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", f"gap-clear block should be ACTIVE, got {data['status']}"


# ==========================================================================
# Difficulty: resource_temporal_overlap (rate plan closed interval, no buffer)
# ==========================================================================
def test_rate_plan_shared_endpoint_overlap_rejected(api):
    """PRD §3.1: "if the new closed interval `[window_start, window_end]` overlaps
    the closed interval of any existing rate plan on the same listing, the create
    is rejected with `ERR_RATE_PLAN_OVERLAP` (HTTP 409). This overlap test treats
    both endpoints as inclusive and applies no turnaround buffer."

    Design: Difficulty/resource_temporal_overlap/rate_plan_closed_interval_no_buffer
    """
    host = create_host()
    _, listing = create_draft_listing(host=host)
    add_rate_plan(host, listing, label="JUL", window_start="2026-07-01",
                  window_end="2026-07-31", seasonal_multiplier_bps=15000)
    # New plan [2026-07-31, 2026-08-10] shares endpoint 2026-07-31 -> overlap.
    resp = api.create_rate_plan(
        create_rate_plan_payload(listing["id"], label="OVERLAP",
                                 window_start="2026-07-31", window_end="2026-08-10",
                                 seasonal_multiplier_bps=13000),
        headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_RATE_PLAN_OVERLAP.value)


def test_rate_plan_adjacent_no_buffer_succeeds(api):
    """PRD §3.1: "This overlap test treats both endpoints as inclusive and
    applies no turnaround buffer."

    Boundary: an adjacent plan [2026-08-01,2026-08-31] right after
    [...,2026-07-31] does not overlap (no buffer required) and is accepted.

    Design: Difficulty/resource_temporal_overlap/rate_plan_closed_interval_no_buffer
    """
    host = create_host()
    _, listing = create_draft_listing(host=host)
    add_rate_plan(host, listing, label="JUL", window_start="2026-07-01",
                  window_end="2026-07-31", seasonal_multiplier_bps=15000)
    resp = api.create_rate_plan(
        create_rate_plan_payload(listing["id"], label="AUG",
                                 window_start="2026-08-01", window_end="2026-08-31",
                                 seasonal_multiplier_bps=13000),
        headers=make_host_headers(host["id"]))
    validate_success(resp, expected_status=201)


# ==========================================================================
# Corner: state_machines (calendar block / channel / decline)
# ==========================================================================
def test_manual_release_of_booking_block_rejected(api):
    """PRD §3.3: "A block whose `source` is `BOOKING`, however, may never be
    released through the manual release action — such a block is released only as
    part of the booking decline or cancel cascade. A manual-release attempt on a
    booking-origin block is rejected with `ERR_RELEASE_BOOKING_BLOCK` (HTTP 409)."

    Design: Corner/state_machines/manual_release_of_booking_block_rejected
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    booking = create_booking(host, listing, guest)
    block_id = booking["calendar_block_id"]
    resp = api.release_calendar_block(listing["id"], block_id, headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_RELEASE_BOOKING_BLOCK.value)


def test_decline_releases_booking_block(api):
    """PRD §3.5: "declining releases the booking's calendar block (the block's
    `status` becomes `RELEASED` and the booking's `calendar_block_id` is set to
    null), advances the listing's `calendar_version` by 1, and bumps each
    `CONNECTED` or `ERROR` channel's `pending_sync_count` by 1."

    Design: Corner/state_machines/decline_releases_block_side_effect
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    booking = create_booking(host, listing, guest)
    block_id = booking["calendar_block_id"]
    api.screen_booking(booking["id"], headers=make_host_headers(host["id"]))
    resp = api.decline_booking(booking["id"], headers=make_host_headers(host["id"]))
    after = validate_success(resp)
    assert after["status"] == "DECLINED", f"booking should be DECLINED, got {after['status']}"
    blk = validate_success(api.get_calendar_block(block_id, headers=make_host_headers(host["id"])))
    assert blk["status"] == "RELEASED", f"declined booking block should be RELEASED, got {blk['status']}"


def test_channel_sync_round_clears_pending(api):
    """PRD §3.2: "Finishing the round successfully moves it from `SYNCING` back to
    `CONNECTED`, and as it lands it sets `pending_sync_count` to 0 and sets
    `last_synced_at` to the current clock instant."

    Design: Corner/state_machines/channel_sync_round_cycle_clears_pending
    """
    host = create_host()
    _, listing = create_draft_listing(host=host, listing_overrides={"gap_nights": 0})
    cc = create_connected_channel(host, listing, channel="VRBO")
    # A manual block bumps pending_sync_count to 1 on the CONNECTED channel.
    create_manual_block(host, listing, start_date="2026-09-10", end_date="2026-09-13")
    api.sync_channel(cc["id"], headers=admin_headers())
    resp = api.sync_complete_channel(cc["id"], headers=admin_headers())
    after = validate_success(resp)
    assert after["pending_sync_count"] == 0, \
        f"sync-complete should clear pending_sync_count to 0, got {after['pending_sync_count']}"
    assert after["status"] == "CONNECTED"


# ==========================================================================
# Corner: cross_cutting_complexity_layers (OCC + cascade)
# ==========================================================================
def test_manual_block_stale_calendar_version_rejected(api):
    """PRD §2.6: "When a manual calendar block is created on a listing, the
    request must include `expected_listing_calendar_version`, and it must equal
    the live `calendar_version` of that listing. If another writer has created or
    released an `ACTIVE` block since the client last read the calendar —
    advancing `calendar_version` — the values disagree and the create is rejected
    with `ERR_STALE_CALENDAR_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_listing_version_on_manual_block_create
    """
    host = create_host()
    _, listing = create_draft_listing(host=host, listing_overrides={"gap_nights": 0})
    stale_cv = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))
    # First create advances calendar_version stale_cv -> stale_cv+1.
    api.create_calendar_block(
        listing["id"],
        create_calendar_block_payload(stale_cv, source="MANUAL",
                                      start_date="2026-09-01", end_date="2026-09-04"),
        headers=make_host_headers(host["id"]))
    # Second create still carrying the stale version -> rejected.
    resp = api.create_calendar_block(
        listing["id"],
        create_calendar_block_payload(stale_cv, source="MANUAL",
                                      start_date="2026-09-20", end_date="2026-09-23"),
        headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_CALENDAR_VERSION.value)


def test_block_create_bumps_connected_channel_pending_sync(api):
    """PRD §2.7: "Whenever an `ACTIVE` calendar block is created or released on a
    listing (whether manually, through a booking, through an import, or through a
    booking cancellation or decline), the listing's `calendar_version` advances by
    1 and, as a propagation hop, every `ChannelConnection` on that listing whose
    `status` is `CONNECTED` or `ERROR` has its `pending_sync_count` incremented by
    1 to record that a local calendar change is awaiting push to that channel."

    Design: Corner/cross_cutting_complexity_layers/cascade_block_create_bumps_channel_pending_sync
    """
    host = create_host()
    _, listing = create_draft_listing(host=host, listing_overrides={"gap_nights": 0})
    cc = create_connected_channel(host, listing, channel="AIRBNB")
    create_manual_block(host, listing, start_date="2026-09-01", end_date="2026-09-04")
    after = validate_success(api.get_channel_connection(cc["id"], headers=make_host_headers(host["id"])))
    assert after["pending_sync_count"] == 1, \
        f"CONNECTED channel pending_sync_count should bump to 1, got {after['pending_sync_count']}"


# ==========================================================================
# Corner: errors / imports
# ==========================================================================
def test_import_duplicate_external_ref_rejected(api):
    """PRD §3.2: "If a reservation with the same `external_ref` already exists on
    that `channel_connection_id`, the import is rejected with
    `ERR_DUPLICATE_EXTERNAL_REF` (HTTP 409)."

    Design: Corner/errors/error_duplicate_external_ref_on_import
    """
    host = create_host()
    _, listing = create_draft_listing(host=host)
    cc = create_connected_channel(host, listing, channel="BOOKINGCOM")
    api.import_reservation(
        cc["id"],
        create_imported_reservation_payload(external_ref="EXT-A",
                                            start_date="2026-09-01", end_date="2026-09-05"),
        headers=admin_headers())
    resp = api.import_reservation(
        cc["id"],
        create_imported_reservation_payload(external_ref="EXT-A",
                                            start_date="2026-10-01", end_date="2026-10-05"),
        headers=admin_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXTERNAL_REF.value)


def test_import_overlap_records_rejected_status(api):
    """PRD §3.2: "if the requested `[start_date, end_date)` overlaps any `ACTIVE`
    calendar block or violates the listing's `gap_nights` turnaround buffer, the
    `ImportedReservation` is recorded with `import_status` of `REJECTED_OVERLAP`
    and its `calendar_block_id` left null — no block is created."

    Design: Corner/errors/imported_reservation_overlap_rejected_status
    """
    host = create_host()
    _, listing = create_draft_listing(host=host, listing_overrides={"gap_nights": 0})
    cc = create_connected_channel(host, listing, channel="AIRBNB")
    create_manual_block(host, listing, start_date="2026-09-10", end_date="2026-09-13")
    resp = api.import_reservation(
        cc["id"],
        create_imported_reservation_payload(external_ref="EXT-OV",
                                            start_date="2026-09-11", end_date="2026-09-14"),
        headers=admin_headers())
    ir = validate_success(resp, expected_status=201)
    assert ir["import_status"] == "REJECTED_OVERLAP", \
        f"overlapping import should be REJECTED_OVERLAP, got {ir['import_status']}"
    assert ir["calendar_block_id"] is None, \
        f"rejected import calendar_block_id must be null, got {ir['calendar_block_id']}"


def test_import_clean_accepted_with_block(api):
    """PRD §3.2: "Otherwise the import succeeds with `import_status` of `ACCEPTED`:
    a fresh `IMPORTED`-source calendar block is created in `ACTIVE`, the
    reservation's `calendar_block_id` points at it, the listing's
    `calendar_version` advances by 1, and the other connected or errored channels
    on the listing have their `pending_sync_count` bumped by 1."

    Design: Corner/entities/imported_reservation_immutable_no_version_field
    """
    host = create_host()
    _, listing = create_draft_listing(host=host)
    cc = create_connected_channel(host, listing, channel="AIRBNB")
    resp = api.import_reservation(
        cc["id"],
        create_imported_reservation_payload(external_ref="EXT-1",
                                            start_date="2026-09-01", end_date="2026-09-05"),
        headers=admin_headers())
    ir = validate_success(resp, expected_status=201)
    assert ir["import_status"] == "ACCEPTED", \
        f"clean import should be ACCEPTED, got {ir['import_status']}"
    assert ir["calendar_block_id"] is not None, \
        "accepted import should reference a synthesized calendar block"
