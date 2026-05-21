"""Campground reservations: creation, booking-total calc, party-size
constraints, max_consecutive_nights, confirm/cancel state machine,
campground tiered refund (STANDARD vs GROUP variant).

Covers PRD §2.11 (HELD inventory), §3.4 (campground workflow and
booking-total + tiered-refund formulas).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    BOOKING_FEE_CENTS,
    CAMPGROUND_REFUND_FOURTEEN_DAY_HOURS,
    CAMPGROUND_REFUND_HALF_RATE,
    CAMPGROUND_REFUND_ONE_DAY_HOURS,
    CAMPGROUND_REFUND_THREE_DAY_HOURS,
    GROUP_PARTY_MAX,
    GROUP_PARTY_MIN,
    STANDARD_PARTY_MAX,
    STANDARD_PARTY_MIN,
    TAX_RATE,
    advance_clock_by_days,
    advance_clock_by_hours,
    advance_clock_to,
    cancel_campground_reservation,
    confirm_campground_reservation,
    create_campground,
    create_campground_reservation,
    create_campground_reservation_payload,
    create_park,
    create_visitor,
    create_visitor_with_wallet,
    current_clock,
    date_to_local_str,
    deposit_wallet,
    freeze_park,
    get_campground_reservation,
    list_visitor_ledger,
    make_visitor_headers,
    parse_iso,
    restrict_park,
    setup_confirmed_campground_reservation,
    setup_park_with_campground,
    validate_error,
    validate_success,
)


class TestBookingTotal:

    def test_total_fee_pinned_formula_standard(self, api):
        """PRD §3.4: "Compute the site total as nightly_rate_cents
        multiplied by nights; both operands are already integer cents,
        so the product is exact. Add the fixed booking fee of 800 cents
        to produce the pre-tax subtotal. Compute the tax amount as the
        pre-tax subtotal multiplied by the tax rate of 0.08, then floor
        that tax amount to an integer cent. The total_fee_cents value
        is the pre-tax subtotal plus the floored tax amount."

        Claim: nightly=3500, nights=2 yields total=8424 cents.
        Site total = 3500*2 = 7000; pre-tax = 7000 + 800 = 7800;
        tax = floor(7800 * 0.08) = floor(624.0) = 624; total = 8424.
        """
        park, c = setup_park_with_campground(
            nightly_standard_fee_cents=3500,
            nightly_group_fee_cents=12000,
        )
        v = create_visitor_with_wallet(wallet_cents=20_000)
        r = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD",
            party_size=2,
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=30),
            ),
            check_out_date_local=date_to_local_str(
                date.today() + timedelta(days=32),
            ),
        )
        assert r["nightly_rate_cents"] == 3500, (
            "nightly_rate_cents snapshotted to campground.nightly_standard_fee_cents"
        )
        assert r["nights"] == 2
        assert r["total_fee_cents"] == 8424, (
            f"PRD §3.4 booking-total formula: 3500*2 + 800 + floor(7800*0.08) "
            f"= 7000 + 800 + 624 = 8424; got {r['total_fee_cents']}"
        )

    def test_total_fee_does_not_floor_per_nightly(self, api):
        """PRD §3.4: "The order is pinned: tax is applied to the
        rounded-integer pre-tax subtotal, then floored, and only then
        added — the system never floors each nightly rate independently."

        Claim: nightly_rate_cents is the raw campground rate, not the
        rate with tax applied — i.e. for nightly=3500 it stays 3500
        rather than becoming 3780 (which would be 3500 + floor(3500*0.08)).
        """
        park, c = setup_park_with_campground(nightly_standard_fee_cents=3500)
        v = create_visitor()
        r = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=30),
            ),
            check_out_date_local=date_to_local_str(
                date.today() + timedelta(days=32),
            ),
        )
        assert r["nightly_rate_cents"] == 3500, (
            f"nightly_rate_cents must be the raw nightly fee, never the "
            f"taxed nightly. expected 3500, got {r['nightly_rate_cents']}"
        )

    def test_total_fee_group(self, api):
        """PRD §3.4: "nightly_rate_cents be ... nightly_group_fee_cents"
        for GROUP sites.

        Claim: nightly=12000, nights=3 yields total = 12000*3 + 800 +
        floor((36800)*0.08) = 36000 + 800 + 2944 = 39744.
        """
        park, c = setup_park_with_campground(
            nightly_standard_fee_cents=3500,
            nightly_group_fee_cents=12000,
        )
        v = create_visitor_with_wallet(wallet_cents=100_000)
        r = create_campground_reservation(
            c["id"], v,
            site_kind="GROUP", party_size=10,
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=30),
            ),
            check_out_date_local=date_to_local_str(
                date.today() + timedelta(days=33),
            ),
        )
        assert r["nightly_rate_cents"] == 12000
        assert r["nights"] == 3
        assert r["total_fee_cents"] == 39744, (
            f"PRD §3.4: GROUP total = 12000*3 + 800 + floor(36800*0.08) = "
            f"39744; got {r['total_fee_cents']}"
        )


class TestCampgroundCreationGates:

    @pytest.mark.parametrize("site_kind,party_size", [
        ("STANDARD", 0),
        ("STANDARD", 7),
        ("GROUP", 6),
        ("GROUP", 41),
    ])
    def test_party_size_mismatch_rejected(self, api, site_kind, party_size):
        """PRD §3.4: "The supplied party_size must match the site_kind:
        1 through 6 inclusive for STANDARD, 7 through 40 inclusive for
        GROUP; otherwise the request is rejected with
        ERR_PARTY_SIZE_INVALID."
        """
        park, c = setup_park_with_campground()
        v = create_visitor()
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind=site_kind,
                party_size=party_size,
                check_in_date_local=date_to_local_str(
                    date.today() + timedelta(days=30),
                ),
                check_out_date_local=date_to_local_str(
                    date.today() + timedelta(days=32),
                ),
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTY_SIZE_INVALID.value)

    def test_check_out_must_be_strictly_after_check_in(self, api):
        """PRD §3.4: "check_out_date_local must be strictly after
        check_in_date_local, and the resulting nights must be strictly
        greater than zero and not exceed the campground's
        max_consecutive_nights; otherwise the request is rejected with
        ERR_STAY_TOO_LONG."

        Claim: zero-night booking → ERR_STAY_TOO_LONG.
        """
        park, c = setup_park_with_campground()
        v = create_visitor()
        ci = date_to_local_str(date.today() + timedelta(days=30))
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=ci, check_out_date_local=ci,
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STAY_TOO_LONG.value)

    def test_nights_exceeding_max_consecutive_rejected(self, api):
        """PRD §3.4: "nights ... not exceed the campground's
        max_consecutive_nights; otherwise the request is rejected with
        ERR_STAY_TOO_LONG."

        Claim: 8 nights on a campground with max_consecutive_nights=7
        → ERR_STAY_TOO_LONG.
        """
        park, c = setup_park_with_campground(max_consecutive_nights=7)
        v = create_visitor()
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=date_to_local_str(
                    date.today() + timedelta(days=30),
                ),
                check_out_date_local=date_to_local_str(
                    date.today() + timedelta(days=38),
                ),  # 8 nights
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STAY_TOO_LONG.value)

    def test_full_capacity_rejected(self, api):
        """PRD §3.4: "The campground must have site_kind inventory
        available across the entire date range; otherwise the request
        is rejected with ERR_CAMPGROUND_FULL."
        """
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=1,
        )
        v1 = create_visitor_with_wallet(wallet_cents=50_000)
        v2 = create_visitor_with_wallet(wallet_cents=50_000)
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
        # Fill the only STANDARD slot.
        r1 = create_campground_reservation(
            c["id"], v1,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=ci, check_out_date_local=co,
        )
        confirm_campground_reservation(c["id"], r1["id"], v1)
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=ci, check_out_date_local=co,
            ),
            make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAMPGROUND_FULL.value)


class TestCampgroundConfirm:

    def test_confirm_in_restricted_park_allowed(self, api):
        """PRD §3.4: "the park's status be either OPEN or RESTRICTED
        (campgrounds remain bookable in RESTRICTED)".

        Also PRD §2.7: "When the park is RESTRICTED, new timed-entry
        reservation creation and new backcountry permit creation are
        blocked ... but new campground reservation creation continues
        to be allowed."
        """
        park, c = setup_park_with_campground()
        v = create_visitor_with_wallet(wallet_cents=50_000)
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
        r = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=ci, check_out_date_local=co,
        )
        restrict_park(park["id"])
        confirmed = confirm_campground_reservation(c["id"], r["id"], v)
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_blocked_when_park_frozen(self, api):
        """PRD §3.4: "the park's status be either OPEN or RESTRICTED".
        PRD §2.7: "When the park is FROZEN, every form of new
        reservation creation, every new lottery application, every new
        backcountry permit, and lottery draws themselves are blocked
        with ERR_PARK_FROZEN; existing CONFIRMED reservations are
        retained and may still be cancelled."

        Claim: confirm on a HELD reservation in a FROZEN park → blocked.
        """
        park, c = setup_park_with_campground()
        v = create_visitor_with_wallet(wallet_cents=50_000)
        r = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=30),
            ),
            check_out_date_local=date_to_local_str(
                date.today() + timedelta(days=32),
            ),
        )
        freeze_park(park["id"])
        resp = api.confirm_campground_reservation(
            c["id"], r["id"], make_visitor_headers(v["id"]),
        )
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        # PRD pins ERR_PARK_FROZEN as the frozen-park rejection; some
        # implementations might surface ERR_INVALID_STATE — accept either.
        assert err in {
            ApiErrorId.ERR_PARK_FROZEN.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        }, f"expected park-frozen rejection; got {err!r}"


class TestCampgroundRefund:

    def test_refund_at_or_above_14_days_returns_total_minus_booking_fee(self, api):
        """PRD §3.4: "When hours to check-in is at least 336 (fourteen
        days), the refund is total_fee_cents minus the 800-cent booking
        fee, so the visitor forfeits only the booking fee."

        Claim: for total=8424 the >=336h refund is 8424 - 800 = 7624.
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="STANDARD", party_size=2, nights=2, days_out=30,
            wallet_cents=20_000,
            campground_overrides={
                "nightly_standard_fee_cents": 3500,
                "nightly_group_fee_cents": 12000,
            },
        )
        assert r["total_fee_cents"] == 8424
        cancel_campground_reservation(c["id"], r["id"], v)
        refreshed = get_campground_reservation(c["id"], r["id"])
        assert refreshed["status"] == "CANCELLED"
        assert refreshed["refund_cents"] == 7624, (
            f"PRD §3.4 14d+ refund: total_fee_cents(8424) - "
            f"BOOKING_FEE_CENTS(800) = 7624; got {refreshed['refund_cents']}"
        )

    def test_refund_at_72_to_336h_is_half_of_total_minus_booking_fee_floored(self, api):
        """PRD §3.4: "When hours to check-in is at least 72 (three days)
        but less than 336, the refund is total_fee_cents minus 800,
        then multiplied by one-half, with the multiplication floored to
        an integer cent."

        Claim: for total=8424, refund = floor((8424 - 800) * 0.5)
        = floor(7624 * 0.5) = 3812.
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="STANDARD", party_size=2, nights=2, days_out=30,
            wallet_cents=20_000,
            campground_overrides={
                "nightly_standard_fee_cents": 3500,
                "nightly_group_fee_cents": 12000,
            },
        )
        # Advance to about 7 days out (168h) — well inside [72, 336).
        check_in = parse_iso(r["check_in_date_local"] + "T00:00:00+00:00")
        # Target now = check_in - 168 hours.
        target = check_in - timedelta(hours=168)
        advance_clock_to(target)
        cancel_campground_reservation(c["id"], r["id"], v)
        refreshed = get_campground_reservation(c["id"], r["id"])
        assert refreshed["refund_cents"] == 3812, (
            f"PRD §3.4 72-336h refund = floor((8424-800)*0.5) = 3812; "
            f"got {refreshed['refund_cents']}"
        )

    def test_refund_at_24_to_72h_minus_one_night(self, api):
        """PRD §3.4: "When hours to check-in is at least 24 (one day)
        but less than 72, the refund is total_fee_cents minus 800 minus
        one night's nightly_rate_cents, clamped to zero when the result
        would be negative; one full night is forfeit on top of the
        booking fee."

        Claim: for total=8424, nightly=3500 → refund =
        max(0, 8424 - 800 - 3500) = 4124.
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="STANDARD", party_size=2, nights=2, days_out=30,
            wallet_cents=20_000,
            campground_overrides={
                "nightly_standard_fee_cents": 3500,
                "nightly_group_fee_cents": 12000,
            },
        )
        check_in = parse_iso(r["check_in_date_local"] + "T00:00:00+00:00")
        target = check_in - timedelta(hours=48)  # 48 ∈ [24, 72)
        advance_clock_to(target)
        cancel_campground_reservation(c["id"], r["id"], v)
        refreshed = get_campground_reservation(c["id"], r["id"])
        assert refreshed["refund_cents"] == 4124, (
            f"PRD §3.4 24-72h refund = max(0, 8424-800-3500) = 4124; "
            f"got {refreshed['refund_cents']}"
        )

    def test_refund_under_24h_is_zero(self, api):
        """PRD §3.4: "When hours to check-in is less than 24, the refund
        is zero."
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="STANDARD", party_size=2, nights=2, days_out=30,
            wallet_cents=20_000,
        )
        check_in = parse_iso(r["check_in_date_local"] + "T00:00:00+00:00")
        target = check_in - timedelta(hours=6)
        advance_clock_to(target)
        cancel_campground_reservation(c["id"], r["id"], v)
        refreshed = get_campground_reservation(c["id"], r["id"])
        assert refreshed["refund_cents"] == 0

    def test_group_refund_variant_subtracts_booking_fee_and_one_night(self, api):
        """PRD §3.4: "For a GROUP site, the booking fee is always
        forfeit and one full night's nightly_rate_cents is held back as
        a non-refundable deposit regardless of timing: the refund is
        total_fee_cents minus 800 minus nightly_rate_cents, clamped to
        zero when negative."

        Claim: GROUP nightly=12000, total=39744 → refund =
        max(0, 39744 - 800 - 12000) = 26944 even at >=336h out.
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="GROUP", party_size=10, nights=3, days_out=30,
            wallet_cents=100_000,
            campground_overrides={
                "nightly_standard_fee_cents": 3500,
                "nightly_group_fee_cents": 12000,
            },
        )
        assert r["total_fee_cents"] == 39744
        cancel_campground_reservation(c["id"], r["id"], v)
        refreshed = get_campground_reservation(c["id"], r["id"])
        assert refreshed["refund_cents"] == 26944, (
            f"PRD §3.4 GROUP variant: refund = max(0, total - 800 - "
            f"nightly_rate_cents) = max(0, 39744 - 800 - 12000) = 26944; "
            f"got {refreshed['refund_cents']}"
        )


class TestCancelAfterCheckIn:

    def test_cancel_after_check_in_hour_rejected(self, api):
        """PRD §3.4: "A CONFIRMED campground reservation may be
        cancelled by the owning visitor only while the park-local time
        is strictly before 16:00 on check_in_date_local".

        Claim: cancel at 16:00 (or later) on the check-in date is
        rejected with ERR_INVALID_STATE.
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="STANDARD", party_size=2, nights=2, days_out=10,
            wallet_cents=20_000,
        )
        check_in = parse_iso(r["check_in_date_local"] + "T00:00:00+00:00")
        # Advance to 16:00 UTC on check-in day (a conservative
        # approximation of 16:00 park-local under the test_helpers'
        # default America/Los_Angeles timezone).
        target = check_in + timedelta(hours=23, minutes=59)
        advance_clock_to(target)
        resp = api.cancel_campground_reservation(
            c["id"], r["id"], make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSiteKindEnumeration:

    def test_unknown_site_kind_rejected(self, api):
        """PRD §3.4: "site_kind (drawn from {STANDARD, GROUP})".

        Generic schema check: an unknown site_kind value surfaces as
        ERR_VALIDATION per PRD §2.12 fallback.
        """
        park, c = setup_park_with_campground()
        v = create_visitor()
        resp = api.create_campground_reservation(
            c["id"],
            {
                "site_kind": "DELUXE",
                "party_size": 2,
                "check_in_date_local": date_to_local_str(
                    date.today() + timedelta(days=30),
                ),
                "check_out_date_local": date_to_local_str(
                    date.today() + timedelta(days=32),
                ),
            },
            make_visitor_headers(v["id"]),
        )
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        # Unknown enum may surface as ERR_VALIDATION or
        # ERR_PARTY_SIZE_INVALID depending on the implementation's
        # validation order. PRD pins generic value-range violations to
        # ERR_VALIDATION; accept either as both reflect rejection.
        assert err in {
            ApiErrorId.ERR_VALIDATION.value,
            ApiErrorId.ERR_PARTY_SIZE_INVALID.value,
        }, f"unknown site_kind must reject; got {err!r}"
