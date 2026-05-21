"""Timed-entry reservations: creation gates, confirm/cancel/check-in
state machine, refund calculation.

Covers PRD §2.10 (window alignment), §2.11 (HELD inventory + 15-min
auto-expiry), §3.3 (timed-entry workflow and tiered refund).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    BOOKING_FEE_CENTS,
    TIMED_ENTRY_FULL_WINDOW_HOURS,
    TIMED_ENTRY_HALF_RATE,
    TIMED_ENTRY_HALF_WINDOW_HOURS,
    TIMED_ENTRY_BOOKING_WINDOW_DAYS,
    advance_clock_by_hours,
    advance_clock_to,
    cancel_timed_entry,
    confirm_timed_entry,
    create_park,
    create_timed_entry,
    create_timed_entry_payload,
    create_visitor,
    create_visitor_with_wallet,
    current_clock,
    date_to_local_str,
    deposit_wallet,
    freeze_park,
    get_visitor,
    issue_pass,
    iso_utc,
    list_visitor_ledger,
    make_visitor_headers,
    parse_iso,
    restrict_park,
    revoke_pass,
    run_sweep,
    setup_confirmed_timed_entry,
    utcnow,
    validate_error,
    validate_success,
)


class TestTimedEntryCreation:

    def test_create_held_with_15_minute_held_until(self, api):
        """PRD §2.11: "A HELD TimedEntryReservation auto-expires 15
        minutes after creation."

        Claim: a fresh HELD reservation has held_until ≈ created_at +
        15 minutes.
        """
        park = create_park()
        v = create_visitor()
        r = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        assert r["status"] == "HELD"
        created_at = parse_iso(r["created_at"])
        held_until = parse_iso(r["held_until"])
        delta = (held_until - created_at).total_seconds()
        # Allow a small tolerance for sub-second creation skew.
        assert 14 * 60 - 5 <= delta <= 15 * 60 + 5, (
            f"held_until must be 15 minutes after created_at; got "
            f"delta={delta}s"
        )

    def test_vehicle_plate_uppercased_on_persist(self, api):
        """PRD §3.3: "vehicle_plate (1 through 10 characters, uppercased
        on persist)".
        """
        park = create_park()
        v = create_visitor()
        r = create_timed_entry(
            park["id"], v,
            vehicle_plate="lower01",
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        assert r["vehicle_plate"] == "LOWER01"

    def test_window_start_misaligned_rejected(self, api):
        """PRD §2.10: "A window_start_local is valid only when the
        number of minutes from midnight is an exact multiple of
        timed_entry_window_minutes; misalignment returns
        ERR_WINDOW_MISALIGNED."
        """
        park = create_park(timed_entry_window_minutes=60)
        v = create_visitor()
        resp = api.create_timed_entry(
            park["id"],
            create_timed_entry_payload(
                window_start_local="09:30",
                entry_date_local=date_to_local_str(
                    date.today() + timedelta(days=5),
                ),
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_MISALIGNED.value)

    def test_entry_date_outside_30_day_window_rejected(self, api):
        """PRD §3.3: "entry_date_local must be at least the current
        park-local date and at most 30 days ahead; outside that window
        the request is rejected with ERR_OUT_OF_BOOKING_WINDOW."
        """
        park = create_park()
        v = create_visitor()
        # 60 days ahead is clearly outside the 30-day window.
        far_future = date_to_local_str(
            date.today() + timedelta(days=TIMED_ENTRY_BOOKING_WINDOW_DAYS + 30),
        )
        resp = api.create_timed_entry(
            park["id"],
            create_timed_entry_payload(
                entry_date_local=far_future,
                window_start_local="09:00",
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_BOOKING_WINDOW.value)

    def test_window_end_local_is_computed(self, api):
        """PRD §2.10: "The computed window_end_local is window_start_local
        plus timed_entry_window_minutes in the same park-local clock."
        """
        park = create_park(timed_entry_window_minutes=60)
        v = create_visitor()
        r = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        assert r["window_end_local"] == "10:00"

    def test_full_capacity_blocks_creation(self, api):
        """PRD §3.3: "The remaining capacity for the (park, date, window)
        triple must be strictly greater than zero; otherwise the
        request is rejected with ERR_TIMED_ENTRY_FULL."
        """
        park = create_park(timed_entry_daily_capacity=1)
        v1 = create_visitor()
        v2 = create_visitor()
        entry_date = date_to_local_str(date.today() + timedelta(days=5))
        # Fill the only slot.
        create_timed_entry(
            park["id"], v1,
            entry_date_local=entry_date,
            window_start_local="09:00",
        )
        # Second attempt for the same (park, date) tuple should fail when
        # the daily capacity is one. Note: PRD ties the counter to the
        # (park, date, window) tuple, so we must reuse the same window.
        resp = api.create_timed_entry(
            park["id"],
            create_timed_entry_payload(
                entry_date_local=entry_date,
                window_start_local="09:00",
            ),
            make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TIMED_ENTRY_FULL.value)


class TestPassWaiver:

    def test_active_pass_yields_zero_entry_fee(self, api):
        """PRD §3.3: "when a valid pass_id is supplied and the
        referenced America the Beautiful Pass belongs to the requesting
        visitor and is ACTIVE at entry_date_local, the entry fee is set
        to 0".
        """
        park = create_park()
        v = create_visitor_with_wallet(wallet_cents=5_000)
        pass_ = issue_pass(v["id"])
        r = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
            pass_id=pass_["id"],
        )
        assert r["entry_fee_cents"] == 0

    def test_revoked_pass_rejected(self, api):
        """PRD §3.3: "If pass_id references a pass not owned by the
        requesting visitor or whose status is not ACTIVE at
        entry_date_local, the request is rejected with
        ERR_PASS_INVALID."
        """
        park = create_park()
        v = create_visitor_with_wallet(wallet_cents=5_000)
        pass_ = issue_pass(v["id"])
        revoke_pass(v["id"], pass_["id"])
        resp = api.create_timed_entry(
            park["id"],
            create_timed_entry_payload(
                entry_date_local=date_to_local_str(
                    date.today() + timedelta(days=5),
                ),
                window_start_local="09:00",
                pass_id=pass_["id"],
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PASS_INVALID.value)

    def test_pass_owned_by_another_visitor_rejected(self, api):
        """PRD §3.3: "If pass_id references a pass not owned by the
        requesting visitor ... the request is rejected with
        ERR_PASS_INVALID."
        """
        park = create_park()
        v1 = create_visitor()
        v2 = create_visitor_with_wallet(wallet_cents=5_000)
        pass_v1 = issue_pass(v1["id"])
        resp = api.create_timed_entry(
            park["id"],
            create_timed_entry_payload(
                entry_date_local=date_to_local_str(
                    date.today() + timedelta(days=5),
                ),
                window_start_local="09:00",
                pass_id=pass_v1["id"],
            ),
            make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PASS_INVALID.value)


class TestTimedEntryConfirm:

    def test_confirm_from_held_transitions_to_confirmed(self, api):
        """PRD §3.3: "Confirming a HELD timed-entry reservation requires
        that the reservation still be in HELD, that the current UTC
        instant precede held_until, that the park's status be OPEN, and
        that Visitor.wallet_balance_cents be at least entry_fee_cents.
        On success the reservation transitions from HELD to CONFIRMED,
        the wallet is debited by entry_fee_cents, and a LedgerEntry of
        kind FEE_CHARGE referencing the timed-entry reservation is
        appended."
        """
        park, v, r = setup_confirmed_timed_entry(days_out=5)
        assert r["status"] == "CONFIRMED"

    def test_confirm_with_insufficient_funds_rejected(self, api):
        """PRD §3.3: "Confirming a HELD timed-entry reservation requires
        ... that Visitor.wallet_balance_cents be at least
        entry_fee_cents."

        PRD §5: ERR_INSUFFICIENT_FUNDS (402).
        """
        park = create_park()
        v = create_visitor()  # wallet = 0
        r = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        # Only fire this test when the standard entry fee is > 0 (i.e.
        # no pass was used). The fee may be zero in some implementations
        # only when explicit pass_id is supplied — without one PRD says
        # "otherwise it is the park's standard entry fee", which is the
        # park's positive entry fee.
        if r["entry_fee_cents"] == 0:
            pytest.skip(
                "PRD does not pin a non-zero default entry fee for parks "
                "without pass; cannot exercise insufficient-funds path."
            )
        resp = api.confirm_timed_entry(
            park["id"], r["id"], make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)

    def test_confirm_blocked_when_park_frozen(self, api):
        """PRD §3.3: "Confirming a HELD timed-entry reservation requires
        ... that the park's status be OPEN".
        """
        park = create_park()
        v = create_visitor_with_wallet(wallet_cents=10_000)
        r = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        freeze_park(park["id"])
        resp = api.confirm_timed_entry(
            park["id"], r["id"], make_visitor_headers(v["id"]),
        )
        # PRD §3.3 names the requirement; the resulting error is the
        # park-state class (ERR_PARK_FROZEN per §2.7 + §2.12).
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        assert err in {
            ApiErrorId.ERR_PARK_FROZEN.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        }, (
            f"frozen-park confirm must surface ERR_PARK_FROZEN or "
            f"ERR_INVALID_STATE; got {err!r}"
        )


class TestTimedEntryHeldExpiry:

    def test_held_reservation_expires_via_sweep(self, api):
        """PRD §2.11: "Once that instant arrives — either because a
        SystemOperator runs the sweep or because the visitor cancels —
        the row transitions to CANCELLED".

        Claim: advancing past held_until + sweep expires the HELD row
        to CANCELLED.
        """
        from test_helpers import get_campground_reservation  # noqa
        park = create_park()
        v = create_visitor()
        r = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        held_until = parse_iso(r["held_until"])
        advance_clock_to(held_until + timedelta(minutes=1))
        run_sweep()
        # List the park's timed-entry rows as admin and locate ours.
        resp = api.list_timed_entries(
            park["id"], make_visitor_headers(v["id"]),
        )
        body = resp.json()
        data = body.get("data") or []
        found = next((row for row in data if row["id"] == r["id"]), None)
        assert found is not None, (
            f"reservation {r['id']} not in list; got {data}"
        )
        assert found["status"] == "CANCELLED", (
            f"expected CANCELLED after sweep past held_until; got "
            f"{found['status']!r}"
        )

    def test_confirm_after_held_until_rejected(self, api):
        """PRD §2.11: "A confirmation attempt after held_until has
        passed is rejected with ERR_INVALID_STATE."
        """
        park = create_park()
        v = create_visitor_with_wallet(wallet_cents=10_000)
        r = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        held_until = parse_iso(r["held_until"])
        advance_clock_to(held_until + timedelta(minutes=1))
        run_sweep()
        resp = api.confirm_timed_entry(
            park["id"], r["id"], make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestTimedEntryCancelAndRefund:

    def test_held_cancel_releases_capacity(self, api):
        """PRD §3.3: "A HELD reservation may be cancelled at any time;
        whether by an explicit visitor cancel or by the sweep crossing
        held_until, the row transitions from HELD to CANCELLED and the
        system releases the capacity counter for the (date, window)
        pair."
        """
        park = create_park(timed_entry_daily_capacity=1)
        v1 = create_visitor()
        v2 = create_visitor()
        entry_date = date_to_local_str(date.today() + timedelta(days=5))
        r1 = create_timed_entry(
            park["id"], v1,
            entry_date_local=entry_date,
            window_start_local="09:00",
        )
        # Cancel V1's hold so capacity is released.
        cancel_timed_entry(park["id"], r1["id"], v1)
        # V2 can now book the same slot.
        r2 = create_timed_entry(
            park["id"], v2,
            entry_date_local=entry_date,
            window_start_local="09:00",
        )
        assert r2["status"] == "HELD"

    def test_refund_full_at_168_hours_or_more(self, api):
        """PRD §3.3: "When that number is at least 168 (seven days),
        the refund is the full entry_fee_cents."
        """
        park, v, r = setup_confirmed_timed_entry(days_out=10)
        fee = r["entry_fee_cents"]
        if fee == 0:
            pytest.skip(
                "default entry_fee_cents is zero; refund cannot be exercised"
            )
        # Advance clock to ensure we're at >= 168h before entry window.
        # Setup placed entry 10 days out, so we are already 240h out.
        # Cancel and assert refund == full fee.
        cancel_timed_entry(park["id"], r["id"], v)
        from test_helpers import list_visitor_ledger
        ledger = list_visitor_ledger(v["id"])
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r["id"]
        ]
        assert len(refunds) == 1, (
            f"expected exactly one FEE_REFUND for r={r['id']}, got {refunds}"
        )
        assert refunds[0]["amount_cents"] == fee, (
            f"full refund at >=168h must equal entry_fee_cents={fee}; got "
            f"{refunds[0]['amount_cents']}"
        )

    def test_refund_half_at_48_to_168_hours(self, api):
        """PRD §3.3: "When the number is at least 48 but less than 168,
        the refund is entry_fee_cents multiplied by one-half, with the
        result floored to an integer cent."
        """
        park, v, r = setup_confirmed_timed_entry(days_out=10)
        fee = r["entry_fee_cents"]
        if fee == 0:
            pytest.skip(
                "default entry_fee_cents is zero; refund cannot be exercised"
            )
        # Advance to ~96h before entry (between 48 and 168).
        entry_date = r["entry_date_local"]
        window_start = r["window_start_local"]
        # Approximate park-local => UTC: park is America/Los_Angeles so
        # window_start at 09:00 PT is 16:00 or 17:00 UTC depending on DST.
        # We use a coarse approach: rebase to 96h before the current
        # clock that already sits at the test wall-clock anchor.
        now = current_clock()
        target_now = parse_iso(entry_date + "T" + window_start + ":00+00:00")
        # Without a robust park-tz library here, advance the clock by
        # roughly (10 days - 96 hours) = 144 hours.
        advance_clock_by_hours(144)
        cancel_timed_entry(park["id"], r["id"], v)
        ledger = list_visitor_ledger(v["id"])
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r["id"]
        ]
        # The 50% refund formula is floor(fee * 0.5).
        expected = fee // 2
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == expected, (
            f"50% refund branch must return floor(fee*0.5)={expected}; got "
            f"{refunds[0]['amount_cents']}"
        )

    def test_refund_zero_under_48_hours(self, api):
        """PRD §3.3: "When the number is less than 48, the refund is
        zero."
        """
        park, v, r = setup_confirmed_timed_entry(days_out=5)
        fee = r["entry_fee_cents"]
        if fee == 0:
            pytest.skip(
                "default entry_fee_cents is zero; refund cannot be exercised"
            )
        # Park-local entry is 5 days * 24 = 120h from creation. Advance
        # 120-24 = 96h so we are ~24h before entry, < 48h.
        advance_clock_by_hours(120 - 24)
        cancel_timed_entry(park["id"], r["id"], v)
        ledger = list_visitor_ledger(v["id"])
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r["id"]
        ]
        # No refund entry, or a refund entry with amount_cents == 0.
        if len(refunds) == 0:
            return
        assert all(e["amount_cents"] == 0 for e in refunds), (
            f"refund <48h must be zero; got {refunds}"
        )

    def test_pass_waived_refund_is_zero_regardless_of_timing(self, api):
        """PRD §3.3: "There is one variant: when the original
        entry_fee_cents was zero because a valid pass was supplied at
        confirm time, the refund is always zero regardless of timing —
        every tier above collapses to zero because the fee was zero."
        """
        park = create_park()
        v = create_visitor_with_wallet(wallet_cents=10_000)
        pass_ = issue_pass(v["id"])
        held = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=10),
            ),
            window_start_local="09:00",
            pass_id=pass_["id"],
        )
        confirmed = confirm_timed_entry(park["id"], held["id"], v)
        assert confirmed["entry_fee_cents"] == 0
        cancel_timed_entry(park["id"], held["id"], v)
        ledger = list_visitor_ledger(v["id"])
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == held["id"]
        ]
        if refunds:
            assert all(e["amount_cents"] == 0 for e in refunds), (
                f"pass_waived refund must be 0 regardless of timing; got "
                f"{refunds}"
            )
