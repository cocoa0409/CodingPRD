"""Validation-priority observations: when multiple checks would fail
on the same request, the lower-priority error code surfaces.

PRD §2.12: "Every endpoint walks its validations in a fixed priority
order. The order is observable: when two conditions both fail on the
same request, the lower-priority error code surfaces, not the
higher-numbered one."
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_by_hours,
    create_campground_reservation_payload,
    create_park,
    create_visitor,
    create_visitor_with_wallet,
    date_to_local_str,
    freeze_park,
    iso_utc,
    make_visitor_headers,
    setup_park_with_campground,
    setup_visitor_with_lottery_strikes,
    utcnow,
    validate_error,
)


class TestParkPostureBeatsFiscal:

    def test_frozen_park_beats_insufficient_funds(self, api):
        """PRD §2.12: "Park posture. Park-level frozen and restricted
        blocks (ERR_PARK_FROZEN, ERR_PARK_RESTRICTED) apply before any
        business-domain checks. A FROZEN park blocks every reservation/
        permit/lottery creation and every lottery draw".

        PRD §2.12 numerical ordering: park-posture is priority 5,
        fiscal is priority 11; lower-priority error surfaces first.

        Claim: a visitor with empty wallet posts a campground
        reservation creation in a FROZEN park — both checks would
        fail, but ERR_PARK_FROZEN wins.
        """
        park, c = setup_park_with_campground()
        freeze_park(park["id"])
        v = create_visitor()  # wallet == 0
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=date_to_local_str(
                    date.today() + timedelta(days=30),
                ),
                check_out_date_local=date_to_local_str(
                    date.today() + timedelta(days=32),
                ),
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARK_FROZEN.value)


class TestStrikeLimitBeatsCapacity:

    def test_group_strike_limit_beats_campground_full(self, api):
        """PRD §2.12: "Strike-limit gates. For new lottery applications
        and for new GROUP campground reservations, a Visitor whose
        lottery_strikes is 3 is rejected with ERR_STRIKE_LIMIT_REACHED.
        The group-site strike check fires before the capacity check,
        so a strike-flagged visitor sees ERR_STRIKE_LIMIT_REACHED even
        when the group site has no inventory left."

        Claim: V_flagged (3 strikes) posts a GROUP reservation against a
        campground with zero remaining GROUP inventory. PRD pins the
        priority: strike wins over capacity.
        """
        # Build a campground with one GROUP slot, fully occupied.
        park, c = setup_park_with_campground(
            standard_site_count=2, group_site_count=1,
            nightly_standard_fee_cents=3500, nightly_group_fee_cents=12000,
        )
        holder = create_visitor_with_wallet(wallet_cents=100_000)
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
        # Holder fills the GROUP site.
        from test_helpers import (
            create_campground_reservation,
            confirm_campground_reservation,
        )
        r1 = create_campground_reservation(
            c["id"], holder,
            site_kind="GROUP", party_size=8,
            check_in_date_local=ci, check_out_date_local=co,
        )
        confirm_campground_reservation(c["id"], r1["id"], holder)
        # Strike-flagged visitor.
        # Re-use the existing test_helpers fixture but reset park so we
        # do not introduce extra lottery permits to the current park.
        from test_helpers import (
            create_lottery_permit,
            current_clock,
            submit_lottery_application,
            draw_lottery,
            run_sweep,
            advance_clock_to,
        )
        from test_helpers import AWARD_EXPIRY_HOURS
        v_flagged = create_visitor_with_wallet(wallet_cents=100_000)
        # Build three quick lotteries to accumulate strikes.
        for _ in range(3):
            now = current_clock()
            permit = create_lottery_permit(
                park["id"],
                lottery_open_at=iso_utc(now - timedelta(hours=1)),
                lottery_close_at=iso_utc(now + timedelta(hours=1)),
                draw_at=iso_utc(now + timedelta(hours=2)),
                hike_date=iso_utc(now + timedelta(days=30)),
                daily_slot_count=10,
                application_fee_cents=100, permit_fee_cents=100,
            )
            submit_lottery_application(permit["id"], v_flagged, party_size=1)
            advance_clock_to(now + timedelta(hours=2, minutes=1))
            draw_lottery(permit["id"])
            advance_clock_by_hours(AWARD_EXPIRY_HOURS + 1)
            run_sweep()
        from test_helpers import get_visitor
        v_flagged_after = get_visitor(v_flagged["id"])
        assert v_flagged_after["lottery_strikes"] == 3
        # Now post the GROUP reservation in a fully-occupied campground.
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="GROUP", party_size=8,
                check_in_date_local=ci, check_out_date_local=co,
            ),
            make_visitor_headers(v_flagged["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STRIKE_LIMIT_REACHED.value)


class TestAuthBeatsExistence:

    def test_unauthenticated_beats_404(self, api):
        """PRD §2.12: "Authentication" is priority 1, "Existence" is
        priority 3.

        Claim: a request to a non-existent park with no auth headers
        returns ERR_UNAUTHENTICATED (not ERR_NOT_FOUND).
        """
        from test_helpers import NON_EXISTENT_UUID
        resp = api._request(
            "GET", f"/parks/{NON_EXISTENT_UUID}", headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestForbiddenBeatsExistence:

    def test_forbidden_beats_404(self, api):
        """PRD §2.12: "Authorization" is priority 2, "Existence" is
        priority 3.

        Claim: a visitor calling POST /parks (admin-only) on a
        nonsense payload returns ERR_FORBIDDEN before any creation
        validation runs.
        """
        from test_helpers import TEST_USERS, create_park_payload
        resp = api.create_park(
            create_park_payload(), TEST_USERS["visitor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
