"""No-show sweep, cancellation, and member-block cascade.

Covers PRD §3.3 (cancel rules, no-show sweep) and §3.8 (test-only
clock + sweep capabilities).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NO_SHOW_THRESHOLD_30D,
    RESERVATION_SLOT_MINUTES,
    advance_clock_to,
    book_reservation,
    create_member_with_prior_no_shows,
    create_reservation_payload,
    iso_plus,
    make_member_headers,
    make_operator_headers,
    now_iso,
    reservation_at,
    setup_basic_scene,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS


class TestCancellation:
    def test_cancel_before_window_releases_hold(self, api):
        """PRD §3.3: "Cancellation of a BOOKED reservation by either the
        owning member or a station operator releases the soft hold —
        held_battery_id is cleared to null and the battery remains IDLE
        — and is only accepted at least five minutes before slot_start_at."

        Claim: cancel a reservation more than 5 min before slot_start →
        Reservation.status=CANCELLED, held_battery_id=null.
        """
        scene = setup_basic_scene()
        res = book_reservation(scene, lead_minutes=20)
        # We are at "now"; slot_start is 20 min away; cancellation window
        # is everything > 5 min before slot_start, so cancel is allowed.
        resp = api.cancel_reservation(
            res["id"], make_member_headers(scene["member"]["id"]),
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled.get("held_battery_id") in (None, "")

    def test_cancel_inside_five_minute_window_rejected(self, api):
        """PRD §3.3: "Inside the five-minute window cancellation is no
        longer permitted and is rejected as an invalid state transition."

        Claim: cancel less than 5 minutes before slot_start →
        ERR_INVALID_STATE.
        """
        scene = setup_basic_scene()
        res = book_reservation(scene, lead_minutes=10)
        # Advance to within 5 minutes of slot_start.
        advance_clock_to(iso_plus(res["slot_start_at"], minutes=-1))
        resp = api.cancel_reservation(
            res["id"], make_member_headers(scene["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestNoShowSweep:
    def test_sweep_flips_expired_reservation_to_no_show(self, api,
                                                       platform_admin_headers):
        """PRD §3.3: "A reservation that ages past its slot_end_at
        without being checked in is swept to NO_SHOW: an admin-only sweep
        endpoint scans every BOOKED reservation, transitions each one
        whose slot_end_at has elapsed to NO_SHOW, releases its
        held_battery_id to null".

        Claim: after slot_end_at, the sweep flips status to NO_SHOW and
        clears held_battery_id.
        """
        scene = setup_basic_scene()
        res = book_reservation(scene, lead_minutes=10)
        # Advance past slot_end_at.
        advance_clock_to(iso_plus(res["slot_end_at"], minutes=1))
        api.run_no_show_sweep(platform_admin_headers)
        ref = api.get_reservation(
            res["id"], make_member_headers(scene["member"]["id"]),
        ).json()["data"]
        assert ref["status"] == "NO_SHOW"
        assert ref.get("held_battery_id") in (None, "")

    def test_three_no_shows_block_member(self, api, platform_admin_headers):
        """PRD §3.3: "If the recomputed count reaches three or more, the
        member's reservation_blocked_until is set to the current server
        time plus seventy-two hours".

        Claim: after the third NO_SHOW sweep tip, Member.no_show_count_30d
        ≥ 3 and reservation_blocked_until is non-null and in the future;
        a subsequent POST /reservations from this member →
        ERR_MEMBER_BLOCKED.
        """
        scene = create_member_with_prior_no_shows(prior_no_shows=3)
        m = api.get_member(
            scene["member"]["id"],
            make_member_headers(scene["member"]["id"]),
        ).json()["data"]
        assert m["no_show_count_30d"] >= NO_SHOW_THRESHOLD_30D
        assert m.get("reservation_blocked_until") not in (None, "")
        # Attempt a new reservation now — should be blocked.
        base = scene["base_clock"]
        s1 = iso_plus(base, minutes=10)
        e1 = iso_plus(s1, minutes=RESERVATION_SLOT_MINUTES)
        payload = create_reservation_payload(
            member_id=scene["member"]["id"],
            vehicle_id=scene["vehicle"]["id"],
            station_id=scene["station"]["id"],
            slot_start_at=s1,
            slot_end_at=e1,
        )
        resp = api.create_reservation(
            payload, make_member_headers(scene["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_BLOCKED.value)
