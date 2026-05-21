"""Concurrency: PRD §2.11 first-writer-wins races + PRD §2.5 OCC.

Each race here is one PRD explicitly defines an outcome for. Per the
testing philosophy, race tests are generated only when PRD names the
losing-side error_id.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_park,
    create_visitor_with_wallet,
    current_clock,
    date_to_local_str,
    iso_utc,
    make_visitor_headers,
    parse_iso,
    run_race,
    setup_park_with_campground,
    setup_park_with_lottery_permit,
    submit_lottery_application,
    utcnow,
    validate_error,
    validate_error_is_one_of,
)


class TestCampgroundCapacityRace:

    def test_two_visitors_race_last_standard_site(self, api):
        """PRD §2.11: "Two visitors race to hold the last STANDARD site
        for the same nights at the same campground: serialisation is
        first-writer-wins on the campground's standard_site_count
        counter for that date range; the loser receives
        ERR_CAMPGROUND_FULL."
        """
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=2,
        )
        v1 = create_visitor_with_wallet(wallet_cents=20_000)
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
        from test_helpers import create_campground_reservation_payload
        results = run_race(
            lambda: api.create_campground_reservation(
                c["id"],
                create_campground_reservation_payload(
                    site_kind="STANDARD", party_size=2,
                    check_in_date_local=ci, check_out_date_local=co,
                ),
                make_visitor_headers(v1["id"]),
            ),
            lambda: api.create_campground_reservation(
                c["id"],
                create_campground_reservation_payload(
                    site_kind="STANDARD", party_size=2,
                    check_in_date_local=ci, check_out_date_local=co,
                ),
                make_visitor_headers(v2["id"]),
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        # PRD pins the losing error_id explicitly.
        loser = outcome["failures"][0]
        body = loser.json()
        err = body.get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_CAMPGROUND_FULL.value, (
            f"PRD §2.11 names ERR_CAMPGROUND_FULL as the loser's error_id "
            f"on the standard-site race; got {err!r}"
        )


class TestTimedEntryCapacityRace:

    def test_two_visitors_race_last_timed_entry_slot(self, api):
        """PRD §2.11: "Two visitors race to hold the last timed-entry
        slot in the same (park_id, entry_date_local, window_start_local)
        tuple: serialisation is first-writer-wins on that tuple's
        counter; the loser receives ERR_TIMED_ENTRY_FULL."
        """
        park = create_park(timed_entry_daily_capacity=1)
        v1 = create_visitor_with_wallet(wallet_cents=5_000)
        v2 = create_visitor_with_wallet(wallet_cents=5_000)
        entry_date = date_to_local_str(date.today() + timedelta(days=5))
        from test_helpers import create_timed_entry_payload
        results = run_race(
            lambda: api.create_timed_entry(
                park["id"],
                create_timed_entry_payload(
                    entry_date_local=entry_date,
                    window_start_local="09:00",
                ),
                make_visitor_headers(v1["id"]),
            ),
            lambda: api.create_timed_entry(
                park["id"],
                create_timed_entry_payload(
                    entry_date_local=entry_date,
                    window_start_local="09:00",
                ),
                make_visitor_headers(v2["id"]),
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        body = loser.json()
        err = body.get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_TIMED_ENTRY_FULL.value, (
            f"PRD §2.11 names ERR_TIMED_ENTRY_FULL as the loser's error_id "
            f"on the timed-entry race; got {err!r}"
        )


class TestLotteryDrawRace:

    def test_two_simultaneous_draws_reject_second(self, api):
        """PRD §2.11: "Two simultaneous draws are POSTed against the
        same LotteryPermit: serialisation is first-writer-wins on the
        lottery's status transition from CLOSED to DRAWN; the second
        draw receives ERR_LOTTERY_ALREADY_DRAWN."
        """
        now = utcnow()
        park, permit = setup_park_with_lottery_permit(
            daily_slot_count=5,
            lottery_open_at=iso_utc(now - timedelta(hours=2)),
            lottery_close_at=iso_utc(now - timedelta(minutes=1)),
            draw_at=iso_utc(now + timedelta(minutes=1)),
            hike_date=iso_utc(now + timedelta(days=10)),
        )
        from test_helpers import TEST_USERS
        results = run_race(
            lambda: api.draw_lottery(
                permit["id"], TEST_USERS["park_admin_headers"],
            ),
            lambda: api.draw_lottery(
                permit["id"], TEST_USERS["system_operator_headers"],
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        body = loser.json()
        err = body.get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_LOTTERY_ALREADY_DRAWN.value, (
            f"PRD §2.11 names ERR_LOTTERY_ALREADY_DRAWN; got {err!r}"
        )


class TestOCCConflict:

    def test_stale_version_rejected_on_patch_park(self, api,
                                                 park_admin_headers):
        """PRD §2.5: "two callers updating the same Campground with
        stale version values resolve such that the higher-version
        writer wins and the stale one receives ERR_VERSION_CONFLICT."

        Generalised to Park here — the same OCC rule applies to all
        PATCH endpoints per PRD §2.5.
        """
        from test_helpers import patch_park_payload, validate_success
        from test_helpers import create_park
        park = create_park()
        # Two sequential PATCHes with the same stale version: the first
        # succeeds, the second hits a version conflict.
        validate_success(
            api.patch_park(
                park["id"],
                patch_park_payload(version=park["version"], name="A"),
                park_admin_headers,
            ),
            200,
        )
        resp = api.patch_park(
            park["id"],
            patch_park_payload(version=park["version"], name="B"),
            park_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestAcceptDeclineRace:

    def test_concurrent_accept_decline_exactly_one_wins(self, api):
        """PRD §2.11: "A visitor simultaneously accepts and declines
        the same AWARDED LotteryApplication: serialisation is first-
        writer-wins on the application's status exit from AWARDED; the
        loser receives ERR_INVALID_STATE."
        """
        from test_helpers import (
            setup_lottery_with_three_applications,
            draw_lottery,
            list_lottery_applications,
            advance_clock_to,
        )
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(
                daily_slot_count=10,
                application_fee_cents=100,
                permit_fee_cents=100,
            )
        )
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        awarded = next(a for a in apps if a["status"] == "AWARDED")
        owner = next(
            x for x in (v1, v2, v3) if x["id"] == awarded["visitor_id"]
        )
        headers = make_visitor_headers(owner["id"])
        results = run_race(
            lambda: api.accept_lottery_application(awarded["id"], headers),
            lambda: api.decline_lottery_application(awarded["id"], headers),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        body = loser.json()
        err = body.get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_INVALID_STATE.value, (
            f"PRD §2.11 names ERR_INVALID_STATE on the accept/decline "
            f"race loser; got {err!r}"
        )
