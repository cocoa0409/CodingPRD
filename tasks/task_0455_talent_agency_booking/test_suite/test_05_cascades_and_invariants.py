"""Multi-link cascades and conserved-quantity invariants.

Covers the four-link booking-cancel cascade (hold release, deal void, commission
reversal, escrow debit), the two-link casting-call-close cascade (submission
withdrawal, slot release), and the money/day-count conservation across a
confirm-then-cancel round trip.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_confirmed_booking,
    setup_open_call_with_submission,
    schedule_audition_slot,
    make_casting_director_headers,
)
from test_helpers import api_client

AGENT = TEST_USERS["agent_headers"]


def _commission_entry_for_booking(api, booking_id):
    data, _meta = _list_entries(api, booking_id)
    assert len(data) >= 1, f"Expected a commission entry for booking {booking_id}"
    return data[0]


def _list_entries(api, booking_id):
    resp = api.list_commission_entries(AGENT, params={"booking_id": booking_id})
    from test_helpers import validate_paginated
    return validate_paginated(resp)


# ─── transitive_cascade: booking cancel depth-4 cascade ──────────────────────
def test_cancel_confirmed_booking_cascades_hold_deal_commission_escrow(api):
    """PRD §3.7: "Cancelling a confirmed booking originates a four-link cascade.
    The first link sets `booking_status` to `CANCELLED`. Caused by that, the
    second link releases the booking's availability hold from `ACTIVE` to
    `RELEASED`; the third link voids the booking's deal memo from `ACCEPTED` to
    `VOIDED`; and the fourth link reverses the booking's commission entry from
    `HELD` to `REVERSED`, setting that entry's `held_cents` to zero and
    reconciling the agency's `escrow_balance_cents` downward by the previously
    held amount."

    Design: Difficulty/transitive_cascade/booking_cancel_depth4_cascade
    """
    base = setup_confirmed_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="STREAMING"
    )
    agency_id = base["agency"]["id"]
    booking_id = base["booking"]["id"]
    hold_id = base["hold"]["id"]
    dm_id = base["deal_memo"]["id"]

    cancelled = validate_success(api.cancel_booking(booking_id, AGENT), 200)
    assert cancelled["booking_status"] == "CANCELLED"

    hold = validate_success(api.get_availability_hold(hold_id, AGENT), 200)
    assert hold["status"] == "RELEASED"

    deal = validate_success(api.get_deal_memo(dm_id, AGENT), 200)
    assert deal["status"] == "VOIDED"

    agency = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert agency["escrow_balance_cents"] == 0


def test_cancel_confirmed_booking_reverses_commission_entry(api):
    """PRD §3.7: "the fourth link reverses the booking's commission entry from
    `HELD` to `REVERSED`, setting that entry's `held_cents` to zero"

    Design: Difficulty/transitive_cascade/booking_cancel_depth4_cascade
    """
    base = setup_confirmed_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="STREAMING"
    )
    booking_id = base["booking"]["id"]
    validate_success(api.cancel_booking(booking_id, AGENT), 200)

    entry = _commission_entry_for_booking(api, booking_id)
    assert entry["status"] == "REVERSED"
    assert entry["held_cents"] == 0


# ─── transitive_cascade: casting call close depth-2 cascade ──────────────────
def test_close_casting_call_withdraws_submission_and_releases_slot(api):
    """PRD §3.2: "Closing originates a cascade: every submission for that call
    still in `SUBMITTED`, `AUDITION_SCHEDULED`, or `CALLBACK_SCHEDULED` is
    withdrawn to `WITHDRAWN` (the first cascade link), and each such withdrawn
    submission then has its audition slots that are still `SCHEDULED` released to
    `RELEASED` (the second link, caused by the first)."

    Design: Difficulty/transitive_cascade/casting_call_close_depth2_cascade
    """
    base = setup_open_call_with_submission(media_type="DIGITAL", usage_term_months=6)
    cd_id = base["cd"]["id"]
    call_id = base["call"]["id"]
    sub_id = base["submission"]["id"]
    cd_headers = make_casting_director_headers(cd_id)

    # Schedule an AUDITION slot -> submission AUDITION_SCHEDULED, slot SCHEDULED.
    slot = schedule_audition_slot(cd_id, sub_id)

    closed = validate_success(api.close_casting_call(call_id, cd_headers), 200)
    assert closed["status"] == "CLOSED"

    submission = validate_success(api.get_submission(sub_id, AGENT), 200)
    assert submission["status"] == "WITHDRAWN"

    refreshed_slot = validate_success(api.get_audition_slot(slot["id"], AGENT), 200)
    assert refreshed_slot["status"] == "RELEASED"


def test_close_casting_call_withdraws_plain_submitted_submission(api):
    """PRD §3.2: "every submission for that call still in `SUBMITTED`,
    `AUDITION_SCHEDULED`, or `CALLBACK_SCHEDULED` is withdrawn to `WITHDRAWN`
    (the first cascade link)"

    Design: Difficulty/transitive_cascade/casting_call_close_depth2_cascade
    """
    # A still-SUBMITTED submission (no slot) is withdrawn by the close — link 1 only.
    base = setup_open_call_with_submission(media_type="DIGITAL", usage_term_months=6)
    cd_id = base["cd"]["id"]
    call_id = base["call"]["id"]
    sub_id = base["submission"]["id"]
    cd_headers = make_casting_director_headers(cd_id)

    closed = validate_success(api.close_casting_call(call_id, cd_headers), 200)
    assert closed["status"] == "CLOSED"

    submission = validate_success(api.get_submission(sub_id, AGENT), 200)
    assert submission["status"] == "WITHDRAWN"


# ─── compensating_invariant: escrow money conserved ─────────────────────────
def test_escrow_money_conserved_across_confirm_then_cancel(api):
    """PRD §2.5: "An agency's `escrow_balance_cents` always equals the sum of
    `held_cents` across that agency's commission entries whose status is `HELD`,
    and it is recomputed on every commission-entry mutation."
    PRD §3.7: "reversing ... setting that entry's `held_cents` to zero and
    reconciling the agency's `escrow_balance_cents` downward by the previously
    held amount."

    Design: Difficulty/compensating_invariant/escrow_money_conserved_confirm_then_cancel
    """
    base = setup_confirmed_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="STREAMING"
    )
    agency_id = base["agency"]["id"]
    booking_id = base["booking"]["id"]

    # After confirm: escrow holds 100000 (1000000 gross * 10%).
    agency = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert agency["escrow_balance_cents"] == 100000

    validate_success(api.cancel_booking(booking_id, AGENT), 200)

    agency_after = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert agency_after["escrow_balance_cents"] == 0

    entry = _commission_entry_for_booking(api, booking_id)
    assert entry["status"] == "REVERSED"
    assert entry["held_cents"] == 0


def test_escrow_holds_then_returns_to_zero_at_higher_commission_rate(api):
    """PRD §2.5: "An agency's `escrow_balance_cents` always equals the sum of
    `held_cents` across that agency's commission entries whose status is `HELD`,
    and it is recomputed on every commission-entry mutation."

    Design: Difficulty/compensating_invariant/escrow_money_conserved_confirm_then_cancel
    """
    # 25% commission: gross 1000000 -> HELD 250000; confirm then cancel returns 0.
    base = setup_confirmed_booking(
        union_status="SAG", commission_rate_bps=2500, media_type="STREAMING"
    )
    agency_id = base["agency"]["id"]
    booking_id = base["booking"]["id"]

    agency = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert agency["escrow_balance_cents"] == 250000

    validate_success(api.cancel_booking(booking_id, AGENT), 200)
    agency_after = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert agency_after["escrow_balance_cents"] == 0


# ─── compensating_invariant: booked days conserved ──────────────────────────
def test_booked_day_counters_conserved_across_confirm_then_cancel(api):
    """PRD §2.5: "These counters are reconciled upward on confirm and downward on
    cancel, and they are conserved quantities: a cancel must subtract exactly
    what the matching confirm added."

    Design: Difficulty/compensating_invariant/booked_days_conserved_confirm_then_cancel
    """
    base = setup_confirmed_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="STREAMING"
    )
    agency_id = base["agency"]["id"]
    talent_id = base["talent"]["id"]
    booking_id = base["booking"]["id"]

    talent = validate_success(api.get_talent(talent_id, AGENT), 200)
    agency = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert talent["booked_day_count"] == 5
    assert agency["booked_day_count"] == 5

    validate_success(api.cancel_booking(booking_id, AGENT), 200)

    talent_after = validate_success(api.get_talent(talent_id, AGENT), 200)
    agency_after = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert talent_after["booked_day_count"] == 0
    assert agency_after["booked_day_count"] == 0


def test_booked_days_conserved_for_single_day_booking(api):
    """PRD §2.5: "the sum, over every booking for that party whose
    `booking_status` is either `CONFIRMED` or `COMPLETED`, of the booking's
    inclusive day span — that is, the number of days from the start date through
    the end date counting both endpoints."

    Design: Difficulty/compensating_invariant/booked_days_conserved_confirm_then_cancel
    """
    # A single-day booking adds exactly 1 inclusive day, then cancel returns to 0.
    base = setup_confirmed_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="STREAMING",
        shoot_start_date="2026-03-15T00:00:00Z", shoot_end_date="2026-03-15T00:00:00Z",
        hold_start="2026-03-15T00:00:00Z", hold_end="2026-03-15T00:00:00Z",
        booking_start="2026-03-15T00:00:00Z", booking_end="2026-03-15T00:00:00Z",
    )
    talent_id = base["talent"]["id"]
    agency_id = base["agency"]["id"]

    talent = validate_success(api.get_talent(talent_id, AGENT), 200)
    agency = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert talent["booked_day_count"] == 1
    assert agency["booked_day_count"] == 1

    validate_success(api.cancel_booking(base["booking"]["id"], AGENT), 200)
    talent_after = validate_success(api.get_talent(talent_id, AGENT), 200)
    agency_after = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert talent_after["booked_day_count"] == 0
    assert agency_after["booked_day_count"] == 0
