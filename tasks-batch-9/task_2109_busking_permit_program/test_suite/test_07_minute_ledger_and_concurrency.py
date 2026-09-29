"""The minute ledger, cancellation and the permit's optimistic-concurrency token."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_session_booking, assert_minute_ledger_invariant,
    create_session_booking_payload, cancel_booking_payload,
    set_clock, setup_district_pitch_and_active_permit,
    book_session, cancel_booking, read_permit, read_booking, permit_version,
    list_bookings,
    make_officer_headers, make_performer_headers,
)
from test_helpers.api_client import api_client


PITCH = dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
             amplification_allowed=True)


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant /
#          cancel_restores_permit_season_minutes_to_pre_booking_value
# ---------------------------------------------------------------------------

def test_cancellation_credits_back_exactly_what_the_booking_debited(api):
    """PRD §3.6: "On admission the booking's `duration_minutes` is added to the
    permit's `season_minutes_used` and the permit's `version` is incremented."
    PRD §3.6: "The cancelled session moves to `CANCELLED_BY_PERFORMER`, and its
    `duration_minutes` is subtracted from the permit's `season_minutes_used`,
    restoring that counter to exactly its pre-booking value; both the session's
    `version` and the permit's `version` are incremented."

    Design: Difficulty/compensating_invariant/cancel_restores_permit_season_minutes_to_pre_booking_value
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PITCH)
    permit_id, performer_id = ctx["permit"]["id"], ctx["performer"]["id"]
    assert read_permit(permit_id)["season_minutes_used"] == 0

    booking = book_session(permit_id, ctx["pitch"]["id"],
                           "2026-08-25T10:00:00Z", "2026-08-25T11:30:00Z",
                           performer_id)
    assert booking["duration_minutes"] == 90
    assert read_permit(permit_id)["season_minutes_used"] == 90

    cancelled = cancel_booking(booking["id"], performer_id=performer_id,
                               reason="Act pulled out of the festival")
    assert cancelled["status"] == "CANCELLED_BY_PERFORMER"

    permit = read_permit(permit_id)
    assert permit["season_minutes_used"] == 0, (
        "the compensating cancellation restores the counter to its pre-booking "
        f"value, got {permit['season_minutes_used']}")
    assert permit["closure_credit_minutes"] == 0
    assert permit["lifecycle_status"] == "ACTIVE"
    assert permit["compliance_status"] == "CLEAR"


def test_minute_ledger_recomputation_holds_after_the_cancellation(api):
    """PRD §2.9: "The **minute ledger** invariant: a permit's
    `season_minutes_used` always equals the sum of `duration_minutes` over that
    permit's sessions whose `status` is `RESERVED`, `RELOCATED` or `COMPLETED`.
    Sessions in any cancelled status contribute nothing; relocated and completed
    sessions still contribute. Every path that cancels a session therefore
    subtracts that session's `duration_minutes` from `season_minutes_used`, and
    a cancellation restores the counter to exactly the value it held before the
    booking was created."

    Design: Difficulty/compensating_invariant/cancel_restores_permit_season_minutes_to_pre_booking_value
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PITCH)
    permit_id, performer_id = ctx["permit"]["id"], ctx["performer"]["id"]

    kept = book_session(permit_id, ctx["pitch"]["id"],
                        "2026-08-25T10:00:00Z", "2026-08-25T11:30:00Z",
                        performer_id)
    released = book_session(permit_id, ctx["pitch"]["id"],
                            "2026-08-26T10:00:00Z", "2026-08-26T11:00:00Z",
                            performer_id)
    assert read_permit(permit_id)["season_minutes_used"] == 150

    cancel_booking(released["id"], performer_id=performer_id, reason="Weather")

    permit = read_permit(permit_id)
    bookings = list_bookings(permit_id=permit_id)
    assert_minute_ledger_invariant(permit, bookings)
    assert permit["season_minutes_used"] == 90, \
        "only the surviving RESERVED session still counts"
    assert read_booking(kept["id"])["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Queue B: cancellation preconditions
# ---------------------------------------------------------------------------

def test_cancelling_a_session_that_has_begun_is_refused(api):
    """PRD §3.6: "Cancellation takes an optional `reason`, is available to the
    owning performer and to officers, and is admissible only while the session
    is `RESERVED` or `RELOCATED` and its `start_at` is still strictly in the
    future; a session that has already begun is refused with
    `ERR_SESSION_ALREADY_STARTED`."

    Design: Corner/state_machines/corner_cancel_after_session_start_rejected
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PITCH)
    permit_id, performer_id = ctx["permit"]["id"], ctx["performer"]["id"]
    booking = book_session(permit_id, ctx["pitch"]["id"],
                           "2026-08-25T10:00:00Z", "2026-08-25T11:30:00Z",
                           performer_id)

    set_clock("2026-08-25T10:00:00Z")
    resp = api.cancel_session_booking(booking["id"],
                                      cancel_booking_payload("Rain"),
                                      make_performer_headers(performer_id))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_SESSION_ALREADY_STARTED)

    assert read_booking(booking["id"])["status"] == "RESERVED"
    assert read_permit(permit_id)["season_minutes_used"] == 90


# ---------------------------------------------------------------------------
# Queue B: optimistic concurrency on the permit
# ---------------------------------------------------------------------------

def test_stale_expected_permit_version_is_rejected_on_a_second_booking(api):
    """PRD §2.7: "Creating a session booking requires `expected_permit_version`,
    carrying the `version` the client last observed on the permit it is booking
    against. If it does not equal the permit's current `version`, the booking is
    rejected with `ERR_STALE_PERMIT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_layers/corner_stale_expected_permit_version_rejected_on_booking
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PITCH)
    permit_id, pitch_id = ctx["permit"]["id"], ctx["pitch"]["id"]
    performer_id = ctx["performer"]["id"]
    stale_version = permit_version(permit_id)

    first = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T11:00:00Z", stale_version),
        make_performer_headers(performer_id))
    booking = validate_success(first, 201)
    assert booking["status"] == "RESERVED"

    second = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-26T10:00:00Z",
                                       "2026-08-26T11:00:00Z", stale_version),
        make_performer_headers(performer_id))
    assert second.status_code == 412, f"Expected 412, got {second.status_code}"
    validate_error(second, ApiErrorId.ERR_STALE_PERMIT_VERSION)
    assert read_permit(permit_id)["season_minutes_used"] == 60

    retry = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-26T10:00:00Z",
                                       "2026-08-26T11:00:00Z",
                                       permit_version(permit_id)),
        make_performer_headers(performer_id))
    second_booking = validate_success(retry, 201)
    assert second_booking["status"] == "RESERVED"
    assert read_permit(permit_id)["season_minutes_used"] == 120


def test_permit_version_advances_on_every_mutation_and_never_on_a_read(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is
    created and increases by exactly 1 on every mutation of that row, whether the
    mutation was requested directly by a client or produced as a side effect of
    an operation on another resource."
    PRD §3.6: "On admission the booking's `duration_minutes` is added to the
    permit's `season_minutes_used` and the permit's `version` is incremented."
    PRD §3.6: "The cancelled session moves to `CANCELLED_BY_PERFORMER`, and its
    `duration_minutes` is subtracted from the permit's `season_minutes_used`,
    restoring that counter to exactly its pre-booking value; both the session's
    `version` and the permit's `version` are incremented."

    Design: Corner/cross_cutting_layers/corner_permit_version_advances_on_every_mutation_and_never_on_reads
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PITCH)
    permit_id, performer_id = ctx["permit"]["id"], ctx["performer"]["id"]
    before_booking = permit_version(permit_id)

    booking = book_session(permit_id, ctx["pitch"]["id"],
                           "2026-08-25T10:00:00Z", "2026-08-25T11:30:00Z",
                           performer_id, expected_permit_version=before_booking)
    after_booking = permit_version(permit_id)
    assert after_booking == before_booking + 1, (
        f"a booking must advance the permit version by exactly 1, "
        f"{before_booking} -> {after_booking}")

    assert permit_version(permit_id) == after_booking, \
        "a read never advances the version"

    cancel_booking(booking["id"], performer_id=performer_id, reason="Weather")
    after_cancel = permit_version(permit_id)
    assert after_cancel == after_booking + 1, (
        f"a cancellation must advance the permit version by exactly 1, "
        f"{after_booking} -> {after_cancel}")

    assert read_booking(booking["id"])["status"] == "CANCELLED_BY_PERFORMER"
    assert read_permit(permit_id)["season_minutes_used"] == 0


def test_booking_create_response_and_the_permit_read_agree_immediately(api):
    """PRD §3.6: "A successful booking is created with `status` `RESERVED`,
    `origin` `DIRECT`, `noise_violation_count` 0, and null values for
    `lottery_entry_id` and `relocated_from_pitch_id`; those two are written only
    when a draw mints the booking or a closure moves it."
    PRD §3.6: "The booking also records an advisory `effective_noise_cap_db`: the
    effective sound ceiling of section 3.1, evaluated at the session's
    `start_at`, using the permit's compliance axis as it stands when the booking
    is created."
    PRD §3.1: "Take the smaller of that allowance and the pitch's own
    `noise_cap_db`."

    Design: Corner/consistency_model/corner_booking_create_response_and_permit_read_agree_immediately
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PITCH)
    permit_id = ctx["permit"]["id"]

    resp = api.create_session_booking(
        create_session_booking_payload(permit_id, ctx["pitch"]["id"],
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T11:30:00Z",
                                       permit_version(permit_id)),
        make_performer_headers(ctx["performer"]["id"]))
    booking = validate_success(resp, 201)
    assert_session_booking(booking)
    assert booking["duration_minutes"] == 90
    assert booking["effective_noise_cap_db"] == 78, (
        "min(pitch 82, district allowance 78) on a Tuesday morning, got "
        f"{booking['effective_noise_cap_db']}")
    assert booking["origin"] == "DIRECT"
    assert booking["lottery_entry_id"] is None
    assert booking["relocated_from_pitch_id"] is None

    assert read_permit(permit_id)["season_minutes_used"] == 90, \
        "the permit read issued straight afterwards already shows the debit"
    _, meta = validate_paginated(api.list_session_bookings(
        make_officer_headers(), params={"permit_id": permit_id}))
    assert meta["total_count"] == 1
