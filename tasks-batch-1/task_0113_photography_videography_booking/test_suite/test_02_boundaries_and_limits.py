"""Numeric-threshold boundaries (lead-day tiers, image-count sufficiency) and the
state-machine limit guards (reschedule cap, revision cap, shoot-end timing).

Queue A (difficulty) instances exercised here:
  boundary_precision_check / cancellation_lead_days_14_boundary_on_cancel
  boundary_precision_check / gallery_finalize_image_count_boundary_on_finalize
Queue B (corner) instances exercised here:
  state_machines / reschedule_limit_exhausted_returns_reschedule_limit
  state_machines / revision_limit_exhausted_returns_revision_limit
  state_machines / shoot_complete_before_end_returns_shoot_not_ended
  state_machines / weather_reschedule_moves_window_bumps_count
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client, TEST_USERS,
    ApiErrorId, make_client_headers, make_photographer_headers,
    # fixtures
    setup_confirmed_booking, setup_deposit_paid_booking, setup_proofing_gallery,
    set_clock,
    # factories
    reschedule_payload, upload_gallery_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# boundary_precision_check / cancellation_lead_days_14_boundary_on_cancel
# ===========================================================================
def test_cancellation_lead_exactly_fourteen_days_quarter_rate(api):
    """PRD §3.8: "apply a fee percentage of twenty-five percent when that lead time is
    fourteen days or more, fifty percent when it is at least seven but fewer than
    fourteen days ... multiply the booking's pinned deposit_due_cents by that percentage
    and round half up to whole cents to obtain cancellation_fee_cents."

    deposit_due 30000; shoot starts 2026-08-20T10:00Z, clock 2026-08-06T10:00Z
    (exactly 14 whole days) -> 25% -> 7500.

    Design: Difficulty/boundary_precision_check/cancellation_lead_days_14_boundary_on_cancel
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-08-20T10:00:00Z", end_utc="2026-08-20T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    assert booking["deposit_due_cents"] == 30000
    set_clock("2026-08-06T10:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["cancellation_fee_cents"] == 7500, (
        f"exactly 14 days -> 25% of 30000 = 7500, got {cancelled['cancellation_fee_cents']}"
    )


def test_cancellation_lead_thirteen_days_half_rate(api):
    """PRD §3.8: "apply a fee percentage of twenty-five percent when that lead time is
    fourteen days or more, fifty percent when it is at least seven but fewer than
    fourteen days, and one hundred percent when it is under seven days ..."

    deposit_due 30000; shoot starts 2026-08-20T10:00Z, clock 2026-08-07T10:00Z
    (13 whole days, just below the 14-day boundary) -> 50% -> 15000.

    Design: Difficulty/boundary_precision_check/cancellation_lead_days_14_boundary_on_cancel
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-08-20T10:00:00Z", end_utc="2026-08-20T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    set_clock("2026-08-07T10:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["cancellation_fee_cents"] == 15000, (
        f"13 days (<14, >=7) -> 50% of 30000 = 15000, got {cancelled['cancellation_fee_cents']}"
    )


# ===========================================================================
# boundary_precision_check / gallery_finalize_image_count_boundary_on_finalize
# ===========================================================================
def test_gallery_finalize_at_exact_image_count_succeeds(api):
    """PRD §3.7: "Finalization by the photographer moves the gallery PROOFING -> FINALIZED
    and bubbles the booking SHOT -> DELIVERED; it is permitted only while the gallery is
    PROOFING and only when delivered_image_count is at least the package's
    included_edited_images, an insufficient count being rejected with ERR_INSUFFICIENT_IMAGES."

    included_edited_images 30, uploaded exactly 30 -> finalize succeeds; booking DELIVERED.

    Design: Difficulty/boundary_precision_check/gallery_finalize_image_count_boundary_on_finalize
    """
    ctx = setup_proofing_gallery(delivered_image_count=30, included_edited_images=30)
    gallery, photographer, booking = ctx["gallery"], ctx["photographer"], ctx["booking"]
    finalized = validate_success(
        api.finalize_gallery(gallery["id"], make_photographer_headers(photographer["id"]))
    )
    assert finalized["status"] == "FINALIZED"
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["workflow_status"] == "DELIVERED"


def test_gallery_finalize_below_image_count_rejected(api):
    """PRD §3.7: "it is permitted only while the gallery is PROOFING and only when
    delivered_image_count is at least the package's included_edited_images, an
    insufficient count being rejected with ERR_INSUFFICIENT_IMAGES."

    included_edited_images 30, uploaded only 29 (one below the threshold) ->
    ERR_INSUFFICIENT_IMAGES.

    Design: Difficulty/boundary_precision_check/gallery_finalize_image_count_boundary_on_finalize
    """
    ctx = setup_proofing_gallery(delivered_image_count=29, included_edited_images=30)
    gallery, photographer = ctx["gallery"], ctx["photographer"]
    validate_error(
        api.finalize_gallery(gallery["id"], make_photographer_headers(photographer["id"])),
        ApiErrorId.ERR_INSUFFICIENT_IMAGES.value,
    )


# ===========================================================================
# state_machines / reschedule_limit_exhausted_returns_reschedule_limit
# ===========================================================================
def test_reschedule_limit_blocks_fourth_move(api):
    """PRD §3.4: "A window may be moved at most three times: if reschedule_count has
    already reached three, a further move is rejected with ERR_RESCHEDULE_LIMIT."

    After three reschedules (reschedule_count == 3) a fourth is rejected.

    Design: Corner/state_machines/reschedule_limit_exhausted_returns_reschedule_limit
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-20T10:00:00Z", end_utc="2026-07-20T12:00:00Z",
    )
    schedule = ctx["schedule"]
    for day in (21, 22, 23):
        get_success_data(api_client.reschedule_shoot_schedule(
            schedule["id"],
            reschedule_payload(f"2026-07-{day}T10:00:00Z", f"2026-07-{day}T12:00:00Z", "WEATHER"),
            ADMIN,
        ))
    validate_error(
        api.reschedule_shoot_schedule(
            schedule["id"],
            reschedule_payload("2026-07-24T10:00:00Z", "2026-07-24T12:00:00Z", "WEATHER"),
            ADMIN,
        ),
        ApiErrorId.ERR_RESCHEDULE_LIMIT.value,
    )


# ===========================================================================
# state_machines / revision_limit_exhausted_returns_revision_limit
# ===========================================================================
def test_revision_limit_blocks_third_request(api):
    """PRD §3.7: "the owning client may also ask for changes, moving the gallery
    PROOFING -> REVISION_REQUESTED; this is permitted only while the gallery is PROOFING,
    only for the client who owns the gallery's booking, and only while revision_round is
    below the cap of two - a request beyond that cap is rejected with ERR_REVISION_LIMIT."

    Run two full revision loops (revision_round reaches 2), then a further
    request-revision is rejected.

    Design: Corner/state_machines/revision_limit_exhausted_returns_revision_limit
    """
    ctx = setup_proofing_gallery(delivered_image_count=30, included_edited_images=30)
    gallery, client, photographer = ctx["gallery"], ctx["client"], ctx["photographer"]
    client_h = make_client_headers(client["id"])
    photog_h = make_photographer_headers(photographer["id"])
    # loop 1: request revision then upload (revision_round -> 1)
    get_success_data(api_client.request_gallery_revision(gallery["id"], client_h))
    get_success_data(api_client.upload_gallery(gallery["id"], upload_gallery_payload(31), photog_h))
    # loop 2: request revision then upload (revision_round -> 2)
    get_success_data(api_client.request_gallery_revision(gallery["id"], client_h))
    get_success_data(api_client.upload_gallery(gallery["id"], upload_gallery_payload(32), photog_h))
    # third request beyond the cap
    validate_error(
        api.request_gallery_revision(gallery["id"], client_h),
        ApiErrorId.ERR_REVISION_LIMIT.value,
    )


# ===========================================================================
# state_machines / shoot_complete_before_end_returns_shoot_not_ended
# ===========================================================================
def test_shoot_complete_before_window_end_rejected(api):
    """PRD §3.7: "a completion attempted before the window ends is rejected with
    ERR_SHOOT_NOT_ENDED" — "Completion is permitted only when the schedule is SCHEDULED
    or RESCHEDULED, when the booking's payment_status is DEPOSIT_PAID or PAID_IN_FULL,
    and when the current time has reached or passed the window's end_utc."

    DEPOSIT_PAID booking, shoot ends 2026-07-30T12:00Z, clock 2026-07-30T11:00Z (before
    end) -> ERR_SHOOT_NOT_ENDED.

    Design: Corner/state_machines/shoot_complete_before_end_returns_shoot_not_ended
    """
    ctx = setup_deposit_paid_booking(
        start_utc="2026-07-30T10:00:00Z", end_utc="2026-07-30T12:00:00Z",
    )
    schedule, photographer = ctx["schedule"], ctx["photographer"]
    set_clock("2026-07-30T11:00:00Z")
    validate_error(
        api.complete_shoot_schedule(schedule["id"], make_photographer_headers(photographer["id"])),
        ApiErrorId.ERR_SHOOT_NOT_ENDED.value,
    )


# ===========================================================================
# state_machines / weather_reschedule_moves_window_bumps_count
# ===========================================================================
def test_weather_reschedule_moves_window_and_bumps_count(api):
    """PRD §3.4: "Each successful move sets the window to the new interval, increments
    reschedule_count by one, and bumps the schedule's version" — "a schedule that is
    SCHEDULED becomes RESCHEDULED ... The request supplies a new_start_utc, a new_end_utc,
    and a reason ... and is recorded in reschedule_reason."

    A WEATHER reschedule on a CONFIRMED booking sets status RESCHEDULED,
    reschedule_count 1, reschedule_reason WEATHER, and moves the window.

    Design: Corner/state_machines/weather_reschedule_moves_window_bumps_count
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-08-15T10:00:00Z", end_utc="2026-08-15T12:00:00Z",
    )
    schedule = ctx["schedule"]
    moved = validate_success(
        api.reschedule_shoot_schedule(
            schedule["id"],
            reschedule_payload("2026-08-16T10:00:00Z", "2026-08-16T12:00:00Z", "WEATHER"),
            ADMIN,
        )
    )
    assert moved["status"] == "RESCHEDULED"
    assert moved["reschedule_count"] == 1
    assert moved["reschedule_reason"] == "WEATHER"
    assert moved["start_utc"].startswith("2026-08-16T10:00:00")
