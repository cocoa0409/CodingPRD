"""Backcountry permits: creation, ranger-buffer time-collision check,
nightly-quota people aggregation, confirm/cancel state machine,
backcountry tiered refund.

Covers PRD §3.7.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    BACKCOUNTRY_PARTY_MAX,
    BACKCOUNTRY_REFUND_FULL_WINDOW_HOURS,
    BACKCOUNTRY_REFUND_HALF_WINDOW_HOURS,
    BOOKING_FEE_CENTS,
    advance_clock_by_hours,
    advance_clock_to,
    cancel_backcountry_permit,
    confirm_backcountry_permit,
    create_backcountry_permit,
    create_backcountry_permit_payload,
    create_backcountry_zone,
    create_park,
    create_visitor_with_wallet,
    current_clock,
    freeze_park,
    iso_utc,
    list_visitor_ledger,
    make_visitor_headers,
    parse_iso,
    setup_confirmed_backcountry_with_window,
    setup_park_with_backcountry_zone,
    utcnow,
    validate_error,
    validate_success,
)


class TestBackcountryCreation:

    def test_create_held_with_fee_includes_booking_fee(self, api):
        """PRD §3.7: "computes fee_cents as the zone's per_party_fee_cents
        plus the 800-cent booking fee".
        """
        park, z = setup_park_with_backcountry_zone(per_party_fee_cents=1500)
        v = create_visitor_with_wallet(wallet_cents=20_000)
        entry = utcnow() + timedelta(days=10)
        exit_dt = entry + timedelta(days=2)
        r = create_backcountry_permit(
            z["id"], v,
            party_size=2,
            entry_datetime_local=iso_utc(entry),
            exit_datetime_local=iso_utc(exit_dt),
        )
        # per_party_fee_cents + booking_fee = 1500 + 800 = 2300
        assert r["fee_cents"] == 1500 + BOOKING_FEE_CENTS, (
            f"PRD §3.7: fee_cents = per_party_fee_cents + 800; got "
            f"{r['fee_cents']}"
        )
        assert r["status"] == "HELD"

    def test_party_size_above_15_rejected(self, api):
        """PRD §3.7: "supplying party_size (1 through 15 inclusive)".
        """
        park, z = setup_park_with_backcountry_zone()
        v = create_visitor_with_wallet(wallet_cents=20_000)
        entry = utcnow() + timedelta(days=10)
        exit_dt = entry + timedelta(days=1)
        resp = api.create_backcountry_permit(
            z["id"],
            create_backcountry_permit_payload(
                party_size=16,
                entry_datetime_local=iso_utc(entry),
                exit_datetime_local=iso_utc(exit_dt),
            ),
            make_visitor_headers(v["id"]),
        )
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        assert err in {
            ApiErrorId.ERR_PARTY_SIZE_INVALID.value,
            ApiErrorId.ERR_VALIDATION.value,
        }, f"out-of-range party_size must reject; got {err!r}"

    def test_exit_must_be_after_entry(self, api):
        """PRD §3.7: "exit_datetime_local; the latter must be strictly
        after the former."
        """
        park, z = setup_park_with_backcountry_zone()
        v = create_visitor_with_wallet(wallet_cents=20_000)
        entry = utcnow() + timedelta(days=10)
        resp = api.create_backcountry_permit(
            z["id"],
            create_backcountry_permit_payload(
                party_size=2,
                entry_datetime_local=iso_utc(entry),
                exit_datetime_local=iso_utc(entry),
            ),
            make_visitor_headers(v["id"]),
        )
        assert resp.status_code >= 400


class TestRangerBufferOverlap:

    def test_buffer_collision_rejected_with_buffer_error(self, api):
        """PRD §3.7: "a new permit [a, b) collides with an existing
        [c, d) exactly when a is strictly less than d plus buffer and c
        is strictly less than b plus buffer ... A time collision is
        reported with ERR_RANGER_BUFFER_VIOLATION."

        Claim: ranger_buffer_minutes=30; existing 09:00-11:00, new
        11:15-13:00 → gap is 15 min < 30 min → ERR_RANGER_BUFFER_VIOLATION.
        """
        park, z = setup_park_with_backcountry_zone(
            ranger_buffer_minutes=30, nightly_quota_people=20,
            per_party_fee_cents=1500,
        )
        # Anchor at a fixed UTC date to control gaps precisely.
        base = utcnow() + timedelta(days=30)
        a_entry = base.replace(hour=17, minute=0, second=0, microsecond=0)
        a_exit = a_entry + timedelta(hours=2)
        park, z, _v1, _r1 = setup_confirmed_backcountry_with_window(
            a_entry, a_exit, party_size=2, park=park, zone=z,
        )
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        b_entry = a_exit + timedelta(minutes=15)
        b_exit = b_entry + timedelta(hours=2)
        held = create_backcountry_permit(
            z["id"], v2,
            party_size=2,
            entry_datetime_local=iso_utc(b_entry),
            exit_datetime_local=iso_utc(b_exit),
        )
        resp = api.confirm_backcountry_permit(
            z["id"], held["id"], make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RANGER_BUFFER_VIOLATION.value)

    def test_gap_equal_to_buffer_passes(self, api):
        """PRD §3.7: "equality at b equal to c passes the test exactly
        when the gap between them is at least buffer."

        Claim: ranger_buffer_minutes=30; existing 09:00-11:00, new
        11:30-13:00 → gap is exactly 30 min → confirm succeeds.
        """
        base = utcnow() + timedelta(days=30)
        a_entry = base.replace(hour=17, minute=0, second=0, microsecond=0)
        a_exit = a_entry + timedelta(hours=2)
        park, z, _v1, _r1 = setup_confirmed_backcountry_with_window(
            a_entry, a_exit, party_size=2,
            zone_overrides={
                "ranger_buffer_minutes": 30,
                "nightly_quota_people": 20,
                "per_party_fee_cents": 1500,
            },
        )
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        b_entry = a_exit + timedelta(minutes=30)
        b_exit = b_entry + timedelta(hours=2)
        held = create_backcountry_permit(
            z["id"], v2,
            party_size=2,
            entry_datetime_local=iso_utc(b_entry),
            exit_datetime_local=iso_utc(b_exit),
        )
        confirmed = confirm_backcountry_permit(z["id"], held["id"], v2)
        assert confirmed["status"] == "CONFIRMED"


class TestBackcountryRefund:

    def test_refund_full_at_or_above_168h(self, api):
        """PRD §3.7: "When the number is at least 168 (seven days, the
        full-window constant), the refund is the full fee_cents."
        """
        base = utcnow() + timedelta(days=10)
        a_entry = base.replace(hour=14, minute=0, second=0, microsecond=0)
        a_exit = a_entry + timedelta(days=1)
        park, z, v, r = setup_confirmed_backcountry_with_window(
            a_entry, a_exit, party_size=2,
            zone_overrides={
                "ranger_buffer_minutes": 30,
                "nightly_quota_people": 20,
                "per_party_fee_cents": 1500,
            },
        )
        # We are 10 days out > 168h. Cancel now and assert refund.
        cancel_backcountry_permit(z["id"], r["id"], v)
        ledger = list_visitor_ledger(v["id"])
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r["id"]
        ]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == r["fee_cents"], (
            f"PRD §3.7 ≥168h refund must equal fee_cents={r['fee_cents']}; "
            f"got {refunds[0]['amount_cents']}"
        )

    def test_refund_half_at_24_to_168h(self, api):
        """PRD §3.7: "When the number is at least 24 (one day, the
        half-window constant) but less than 168, the refund is fee_cents
        multiplied by one-half, with the result floored to an integer
        cent."
        """
        base = utcnow() + timedelta(days=10)
        a_entry = base.replace(hour=14, minute=0, second=0, microsecond=0)
        a_exit = a_entry + timedelta(days=1)
        park, z, v, r = setup_confirmed_backcountry_with_window(
            a_entry, a_exit, party_size=2,
            zone_overrides={
                "ranger_buffer_minutes": 30,
                "nightly_quota_people": 20,
                "per_party_fee_cents": 1500,
            },
        )
        fee = r["fee_cents"]
        # Advance so we are roughly 48h before entry (in [24, 168)).
        target = a_entry - timedelta(hours=48)
        advance_clock_to(target)
        cancel_backcountry_permit(z["id"], r["id"], v)
        ledger = list_visitor_ledger(v["id"])
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r["id"]
        ]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == fee // 2, (
            f"PRD §3.7 24-168h refund = floor(fee*0.5) = {fee // 2}; "
            f"got {refunds[0]['amount_cents']}"
        )

    def test_refund_zero_under_24h(self, api):
        """PRD §3.7: "When the number is less than 24, the refund is
        zero."
        """
        base = utcnow() + timedelta(days=5)
        a_entry = base.replace(hour=14, minute=0, second=0, microsecond=0)
        a_exit = a_entry + timedelta(days=1)
        park, z, v, r = setup_confirmed_backcountry_with_window(
            a_entry, a_exit, party_size=2,
            zone_overrides={
                "ranger_buffer_minutes": 30,
                "nightly_quota_people": 20,
                "per_party_fee_cents": 1500,
            },
        )
        target = a_entry - timedelta(hours=12)
        advance_clock_to(target)
        cancel_backcountry_permit(z["id"], r["id"], v)
        ledger = list_visitor_ledger(v["id"])
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r["id"]
        ]
        if refunds:
            assert all(e["amount_cents"] == 0 for e in refunds)


class TestBackcountryParkPosture:

    def test_create_blocked_when_park_restricted(self, api):
        """PRD §2.7: "When the park is RESTRICTED, new timed-entry
        reservation creation and new backcountry permit creation are
        blocked with ERR_PARK_RESTRICTED."
        """
        from test_helpers import restrict_park
        park, z = setup_park_with_backcountry_zone()
        restrict_park(park["id"])
        v = create_visitor_with_wallet(wallet_cents=20_000)
        entry = utcnow() + timedelta(days=10)
        exit_dt = entry + timedelta(days=1)
        resp = api.create_backcountry_permit(
            z["id"],
            create_backcountry_permit_payload(
                party_size=2,
                entry_datetime_local=iso_utc(entry),
                exit_datetime_local=iso_utc(exit_dt),
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARK_RESTRICTED.value)

    def test_create_blocked_when_park_frozen(self, api):
        """PRD §2.7: "When the park is FROZEN, every form of new
        reservation creation, every new lottery application, every new
        backcountry permit, and lottery draws themselves are blocked
        with ERR_PARK_FROZEN".
        """
        park, z = setup_park_with_backcountry_zone()
        freeze_park(park["id"])
        v = create_visitor_with_wallet(wallet_cents=20_000)
        entry = utcnow() + timedelta(days=10)
        exit_dt = entry + timedelta(days=1)
        resp = api.create_backcountry_permit(
            z["id"],
            create_backcountry_permit_payload(
                party_size=2,
                entry_datetime_local=iso_utc(entry),
                exit_datetime_local=iso_utc(exit_dt),
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARK_FROZEN.value)
