"""Waitlist join/delete, waitlist promotion cascade after campground
cancellation, lottery decline cascade promoting next WAITLISTED.

Covers PRD §3.4 (cancel cascade), §3.5 (waitlist), §3.6 (decline
promotes WAITLISTED), §2.11 (4-hour promotion hold).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    PROMOTION_HOLD_HOURS,
    advance_clock_by_hours,
    advance_clock_to,
    api_client,
    cancel_campground_reservation,
    confirm_campground_reservation,
    create_campground_reservation,
    create_visitor_with_wallet,
    create_waitlist_entry,
    current_clock,
    date_to_local_str,
    find_held_promoted_reservation,
    list_waitlist,
    make_visitor_headers,
    parse_iso,
    setup_at_capacity_campground,
    setup_park_with_campground,
    validate_error,
    validate_success,
)


class TestWaitlistJoin:

    def test_join_waitlist_succeeds(self, api):
        """PRD §3.5: "A Visitor joins a campground's waitlist by
        supplying site_kind, check_in_date_local, and nights (1 through
        14 inclusive)."
        """
        park, c = setup_park_with_campground()
        v = create_visitor_with_wallet(wallet_cents=10_000)
        check_in = date_to_local_str(date.today() + timedelta(days=2))
        entry = create_waitlist_entry(
            c["id"], v, site_kind="STANDARD",
            check_in_date_local=check_in, nights=2,
        )
        assert entry["status"] == "WAITING"
        # PRD §2.4: WaitlistEntry is append-only, no updated_at/version.
        assert "updated_at" not in entry or entry.get("updated_at") is None
        assert "version" not in entry or entry.get("version") is None
        # PRD §3.5: "snapshots a tie-break priority_score computed as
        # the integer floor of the number of seconds between the Unix
        # epoch and the entry's created_at divided by 60".
        created_at = parse_iso(entry["created_at"])
        expected = int(created_at.timestamp() // 60)
        assert entry["priority_score"] == expected, (
            f"priority_score must be floor(epoch_seconds / 60); expected "
            f"{expected}, got {entry['priority_score']}"
        )

    def test_visitor_cancels_own_waitlist_entry(self, api):
        """PRD §3.5: "A visitor may also delete their own waitlist
        entry while it is still WAITING; the entry transitions from
        WAITING to CANCELLED."
        """
        park, c = setup_park_with_campground()
        v = create_visitor_with_wallet(wallet_cents=10_000)
        entry = create_waitlist_entry(
            c["id"], v, site_kind="STANDARD",
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=2),
            ),
            nights=2,
        )
        resp = api.delete_waitlist_entry(
            c["id"], entry["id"], make_visitor_headers(v["id"]),
        )
        assert resp.status_code == 204, (
            f"DELETE returns 204 No Content per PRD §4; got "
            f"{resp.status_code}"
        )
        # Subsequent GET via list shows status CANCELLED.
        entries = list_waitlist(c["id"])
        e = next((x for x in entries if x["id"] == entry["id"]), None)
        if e is not None:
            assert e["status"] == "CANCELLED"

    def test_waitlist_nights_must_be_in_range(self, api):
        """PRD §3.5: "nights (1 through 14 inclusive)".
        """
        park, c = setup_park_with_campground()
        v = create_visitor_with_wallet(wallet_cents=10_000)
        # 15 nights — outside the allowed range.
        from test_helpers import create_waitlist_payload
        resp = api.create_waitlist_entry(
            c["id"],
            create_waitlist_payload(
                site_kind="STANDARD",
                check_in_date_local=date_to_local_str(
                    date.today() + timedelta(days=2),
                ),
                nights=15,
            ),
            make_visitor_headers(v["id"]),
        )
        assert resp.status_code >= 400


class TestCampgroundCancelCascadesWaitlist:

    def test_cancel_confirmed_cascades_to_promotion(self, api):
        """PRD §3.4: "On success the reservation transitions from
        CONFIRMED to CANCELLED, the refund is computed per the
        campground tiered-refund rule below and written to refund_cents
        on the reservation, a LedgerEntry of kind FEE_REFUND with
        amount_cents equal to the refund credits the wallet, the site
        occupancy is released, and the waitlist-promotion cascade
        fires: a fresh CampgroundReservation may be created in HELD for
        the next eligible WaitlistEntry, and that waitlist entry's
        status is set to PROMOTED".

        PRD §2.11: "A HELD CampgroundReservation that is created by
        waitlist promotion is held for 4 hours after creation".

        Claim: holder cancels CONFIRMED → waitlister's WAITING entry
        flips to PROMOTED and a new HELD reservation exists for the
        waitlister.
        """
        # Build the cascade scenario from scratch so we control the
        # timing precisely: a 1-site campground, holder confirmed,
        # waitlister WAITING for the same dates.
        from datetime import date as _date
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=2,
            waitlist_window_hours=24, nightly_standard_fee_cents=3500,
            nightly_group_fee_cents=12000,
        )
        holder = create_visitor_with_wallet(wallet_cents=12_000)
        waitlister = create_visitor_with_wallet(wallet_cents=12_000)
        # PRD §3.5 promotion eligibility requires now within
        # waitlist_window_hours of check_in_date_local — set check-in
        # 12 hours from now.
        check_in_dt = current_clock() + timedelta(hours=12)
        check_in = check_in_dt.date().isoformat()
        check_out = (check_in_dt + timedelta(days=2)).date().isoformat()
        # Holder books and confirms.
        r1_held = create_campground_reservation(
            c["id"], holder,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=check_in,
            check_out_date_local=check_out,
        )
        r1 = confirm_campground_reservation(c["id"], r1_held["id"], holder)
        assert r1["status"] == "CONFIRMED"
        # Waitlister joins waitlist for the same dates.
        w = create_waitlist_entry(
            c["id"], waitlister, site_kind="STANDARD",
            check_in_date_local=check_in, nights=2,
        )
        assert w["status"] == "WAITING"
        # Holder cancels CONFIRMED (still before 16:00 on check-in date
        # — we're 12 hours out so still well before that boundary).
        cancel_campground_reservation(c["id"], r1["id"], holder)
        # Waitlister's entry should now be PROMOTED.
        entries = list_waitlist(c["id"])
        w_after = next((x for x in entries if x["id"] == w["id"]), None)
        assert w_after is not None
        assert w_after["status"] == "PROMOTED", (
            f"waitlister's entry must transition WAITING -> PROMOTED on "
            f"cancel cascade; got {w_after['status']!r}"
        )
        assert w_after["promoted_reservation_id"] is not None
        # The promoted reservation exists in HELD for the waitlister.
        promoted = find_held_promoted_reservation(c["id"], waitlister["id"])
        assert promoted is not None
        assert promoted["status"] == "HELD"
        # PRD §2.11 / §3.5: held_until is 4 hours after creation.
        created_at = parse_iso(promoted["created_at"])
        held_until = parse_iso(promoted["held_until"])
        delta_hours = (held_until - created_at).total_seconds() / 3600
        assert abs(delta_hours - PROMOTION_HOLD_HOURS) < 0.01, (
            f"PRD §3.5: promoted reservation held_until must be "
            f"created_at + 4 hours; got delta={delta_hours}h"
        )

    def test_held_cancel_also_runs_waitlist_promotion(self, api):
        """PRD §3.4: "A HELD campground reservation may be cancelled at
        any time ... the system releases site occupancy for the
        [check_in_date_local, check_out_date_local) range, and the
        system runs a waitlist-promotion sweep on that campground
        (cascade depth two — the campground's freed inventory may
        itself create a new HELD CampgroundReservation for the next
        eligible waitlisted visitor)."
        """
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=2,
            waitlist_window_hours=24,
        )
        holder = create_visitor_with_wallet(wallet_cents=12_000)
        waitlister = create_visitor_with_wallet(wallet_cents=12_000)
        check_in_dt = current_clock() + timedelta(hours=12)
        check_in = check_in_dt.date().isoformat()
        check_out = (check_in_dt + timedelta(days=2)).date().isoformat()
        r_held = create_campground_reservation(
            c["id"], holder,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=check_in,
            check_out_date_local=check_out,
        )
        w = create_waitlist_entry(
            c["id"], waitlister, site_kind="STANDARD",
            check_in_date_local=check_in, nights=2,
        )
        # Holder cancels HELD reservation.
        cancel_campground_reservation(c["id"], r_held["id"], holder)
        entries = list_waitlist(c["id"])
        w_after = next((x for x in entries if x["id"] == w["id"]), None)
        assert w_after is not None
        assert w_after["status"] == "PROMOTED", (
            f"HELD cancel cascade must promote waitlister; got "
            f"{w_after['status']!r}"
        )


class TestLotteryDeclineCascade:

    def test_decline_promotes_waitlisted_application(self, api):
        """PRD §3.6: "on decline the application transitions from
        AWARDED to DECLINED, the awarded slot is returned to the
        permit's pool, and the first remaining WAITLISTED application
        (lowest rank_seed, then earliest created_at) is promoted from
        WAITLISTED to AWARDED — a cascade of depth three from one
        application's decline, through the permit's slot pool, through
        to a sibling application's status flip."

        We arrange daily_slot_count=2 with three applications of
        party_size=2 so that exactly one is initially AWARDED and the
        others WAITLISTED. After the AWARDED visitor declines, exactly
        one WAITLISTED app should be promoted to AWARDED.
        """
        from test_helpers import (
            setup_park_with_lottery_permit,
            submit_lottery_application,
            draw_lottery,
            list_lottery_applications,
            iso_utc,
            utcnow,
        )
        from datetime import timedelta
        park, permit = setup_park_with_lottery_permit(
            daily_slot_count=2,
            application_fee_cents=100,
            permit_fee_cents=100,
            per_application_max_party=4,
            lottery_open_at=iso_utc(utcnow() - timedelta(hours=1)),
            lottery_close_at=iso_utc(utcnow() + timedelta(hours=2)),
            draw_at=iso_utc(utcnow() + timedelta(hours=3)),
            hike_date=iso_utc(utcnow() + timedelta(days=10)),
        )
        v1 = create_visitor_with_wallet(wallet_cents=10_000)
        v2 = create_visitor_with_wallet(wallet_cents=10_000)
        v3 = create_visitor_with_wallet(wallet_cents=10_000)
        a1 = submit_lottery_application(permit["id"], v1, party_size=2)
        a2 = submit_lottery_application(permit["id"], v2, party_size=2)
        a3 = submit_lottery_application(permit["id"], v3, party_size=2)
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        awarded = [a for a in apps if a["status"] == "AWARDED"]
        waitlisted = [a for a in apps if a["status"] == "WAITLISTED"]
        # With slot_count=2 and three party=2 apps, exactly one is
        # AWARDED and two are WAITLISTED.
        assert len(awarded) == 1, (
            f"daily_slot_count=2 with three party=2 apps must produce "
            f"1 AWARDED; got {len(awarded)}: {[a['status'] for a in apps]}"
        )
        assert len(waitlisted) == 2
        target = awarded[0]
        owner = next(
            x for x in (v1, v2, v3) if x["id"] == target["visitor_id"]
        )
        # Decline.
        resp = api.decline_lottery_application(
            target["id"], make_visitor_headers(owner["id"]),
        )
        validate_success(resp, 200)
        # After decline, one of the previously WAITLISTED applications
        # is now AWARDED.
        apps_after = list_lottery_applications(permit["id"])
        promoted = [
            a for a in apps_after
            if a["id"] in {w["id"] for w in waitlisted}
            and a["status"] == "AWARDED"
        ]
        assert len(promoted) == 1, (
            f"PRD §3.6 cascade: decline must promote exactly one "
            f"WAITLISTED app to AWARDED; got {len(promoted)}"
        )
        # PRD §3.6: "set each AWARDED application's award_expires_at"
        # — the newly-promoted app must now carry an award_expires_at.
        new_award = promoted[0]
        assert new_award.get("award_expires_at") not in (None, ""), (
            f"promoted application must carry award_expires_at; got "
            f"{new_award.get('award_expires_at')!r}"
        )
