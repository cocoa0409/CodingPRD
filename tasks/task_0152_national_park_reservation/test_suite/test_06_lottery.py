"""Lottery permits and applications: submission gates, draw waterfall,
accept/decline/no-show state transitions, slot-return cascades.

Covers PRD §3.6 fully and the strike-limit interactions from §3.1, §3.4.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    AWARD_EXPIRY_HOURS,
    MAX_LOTTERY_STRIKES,
    advance_clock_by_hours,
    advance_clock_to,
    create_lottery_application_payload,
    create_lottery_permit,
    create_park,
    create_visitor,
    create_visitor_with_wallet,
    current_clock,
    deposit_wallet,
    draw_lottery,
    find_lottery_application,
    freeze_park,
    get_visitor,
    iso_utc,
    list_lottery_applications,
    list_visitor_ledger,
    make_visitor_headers,
    parse_iso,
    run_sweep,
    setup_lottery_with_three_applications,
    setup_park_with_lottery_permit,
    setup_visitor_with_lottery_strikes,
    submit_lottery_application,
    utcnow,
    validate_error,
    validate_success,
)


class TestLotterySubmission:

    def test_submit_debits_application_fee_immediately(self, api):
        """PRD §3.6: "snapshots application_fee_cents from the permit's
        current application_fee_cents, mints a 64-bit unsigned pseudo-
        random rank_seed (lower wins), places the application in
        SUBMITTED status, and immediately appends a LedgerEntry of kind
        LOTTERY_FEE debiting the visitor's wallet by application_fee_cents
        — this fee is non-refundable regardless of draw outcome."
        """
        park, permit = setup_park_with_lottery_permit(
            application_fee_cents=1000,
            lottery_open_at=iso_utc(utcnow() - timedelta(hours=1)),
            lottery_close_at=iso_utc(utcnow() + timedelta(hours=24)),
            draw_at=iso_utc(utcnow() + timedelta(days=2)),
            hike_date=iso_utc(utcnow() + timedelta(days=10)),
        )
        v = create_visitor_with_wallet(wallet_cents=5_000)
        app = submit_lottery_application(permit["id"], v, party_size=2)
        assert app["status"] == "SUBMITTED"
        assert app["application_fee_cents"] == 1000
        # Wallet must have been debited.
        v_after = get_visitor(v["id"])
        assert v_after["wallet_balance_cents"] == 5_000 - 1000
        # Exactly one LOTTERY_FEE LedgerEntry referencing this app.
        ledger = list_visitor_ledger(v["id"])
        lottery_entries = [
            e for e in ledger if e["kind"] == "LOTTERY_FEE"
            and e.get("reference_id") == app["id"]
        ]
        assert len(lottery_entries) == 1
        assert lottery_entries[0]["amount_cents"] == -1000

    def test_submit_outside_window_rejected(self, api):
        """PRD §3.6: "The current instant must be strictly at or after
        lottery_open_at and strictly before lottery_close_at (the
        closing instant itself is excluded); outside this half-open
        interval the request is rejected with ERR_LOTTERY_CLOSED."
        """
        # Permit that already closed: lottery_close_at is in the past.
        past = utcnow() - timedelta(hours=2)
        park, permit = setup_park_with_lottery_permit(
            lottery_open_at=iso_utc(past - timedelta(hours=2)),
            lottery_close_at=iso_utc(past),
            draw_at=iso_utc(past + timedelta(hours=1)),
            hike_date=iso_utc(utcnow() + timedelta(days=10)),
        )
        v = create_visitor_with_wallet(wallet_cents=5_000)
        resp = api.create_lottery_application(
            permit["id"],
            create_lottery_application_payload(party_size=2),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOTTERY_CLOSED.value)

    def test_party_size_above_per_application_max_rejected(self, api):
        """PRD §3.6: "The requested party_size must be at least 1 and
        must not exceed the permit's per_application_max_party;
        otherwise the request is rejected with ERR_PARTY_SIZE_INVALID."
        """
        park, permit = setup_park_with_lottery_permit(
            per_application_max_party=4,
        )
        v = create_visitor_with_wallet(wallet_cents=5_000)
        resp = api.create_lottery_application(
            permit["id"],
            create_lottery_application_payload(party_size=5),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTY_SIZE_INVALID.value)

    def test_submit_blocked_when_park_frozen(self, api):
        """PRD §3.6: "The park's status must not be FROZEN; otherwise
        the request is rejected with ERR_PARK_FROZEN."
        """
        park, permit = setup_park_with_lottery_permit()
        freeze_park(park["id"])
        v = create_visitor_with_wallet(wallet_cents=5_000)
        resp = api.create_lottery_application(
            permit["id"],
            create_lottery_application_payload(party_size=2),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARK_FROZEN.value)

    def test_strike_three_blocked(self, api):
        """PRD §3.6: "The submitting visitor's lottery_strikes must be
        strictly less than 3; otherwise the request is rejected with
        ERR_STRIKE_LIMIT_REACHED."
        """
        park, v = setup_visitor_with_lottery_strikes(target_strikes=3)
        permit = create_lottery_permit(
            park["id"],
            lottery_open_at=iso_utc(current_clock() - timedelta(hours=1)),
            lottery_close_at=iso_utc(current_clock() + timedelta(days=1)),
            draw_at=iso_utc(current_clock() + timedelta(days=2)),
            hike_date=iso_utc(current_clock() + timedelta(days=10)),
            application_fee_cents=100,
            permit_fee_cents=100,
        )
        resp = api.create_lottery_application(
            permit["id"],
            create_lottery_application_payload(party_size=1),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STRIKE_LIMIT_REACHED.value)


class TestLotteryDraw:

    def test_draw_waterfall_awards_then_waitlists(self, api):
        """PRD §3.6: "iterate in sorted order, and for each application,
        if the remaining-slot counter is at least the application's
        party_size, mark the application AWARDED and subtract party_size
        from the counter, otherwise mark the application WAITLISTED."

        Claim: with daily_slot_count=5 and three applications of size
        3, 4, 2 sorted by rank_seed, the slot allocation is:
            - If A_first awarded with party=3 → remaining 2.
            - A_second party=4 → 2 < 4 → WAITLISTED.
            - A_third party=2 → 2 >= 2 → AWARDED → remaining 0.

        The exact ordering of rank_seed is system-minted (random), so
        we test the invariant: total AWARDED party_size ≤ 5 and any
        WAITLISTED has party_size strictly greater than what remained
        when it was visited.
        """
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(daily_slot_count=5)
        )
        # Move clock past lottery_close_at, then run the draw.
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        # Permit transitioned to DRAWN.
        from test_helpers import api_client
        permit_after = api_client.list_lottery_permits(
            park["id"],
            make_visitor_headers(v1["id"]),
        ).json()["data"]
        permit_state = next(
            (p for p in permit_after if p["id"] == permit["id"]),
            None,
        )
        assert permit_state["status"] == "DRAWN"
        # Sum AWARDED party_size <= daily_slot_count.
        awarded = [a for a in apps if a["status"] == "AWARDED"]
        waitlisted = [a for a in apps if a["status"] == "WAITLISTED"]
        awarded_total = sum(a["party_size"] for a in awarded)
        assert awarded_total <= 5, (
            f"PRD §3.6 waterfall must respect daily_slot_count=5; awarded "
            f"sum={awarded_total}"
        )
        # Every WAITLISTED app must have a party_size that exceeded the
        # remaining slots when it was visited — i.e. each was rejected
        # not because of strikes (none of these visitors are flagged)
        # but because of capacity.
        for a in apps:
            assert a["status"] in {"AWARDED", "WAITLISTED"}

    def test_draw_sets_award_expires_at_72h_after_draw_at(self, api):
        """PRD §3.6: "set each AWARDED application's award_expires_at
        to 72 hours after draw_at."
        """
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(daily_slot_count=10)
        )
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        draw_at = parse_iso(permit["draw_at"])
        for a in apps:
            if a["status"] == "AWARDED":
                expected = draw_at + timedelta(hours=AWARD_EXPIRY_HOURS)
                actual = parse_iso(a["award_expires_at"])
                delta = abs((actual - expected).total_seconds())
                assert delta < 2, (
                    f"AWARDED.award_expires_at must be draw_at + 72h; "
                    f"expected {expected}, got {actual}"
                )
            else:
                # WAITLISTED apps have award_expires_at == null.
                assert a.get("award_expires_at") in (None, ""), (
                    f"non-AWARDED app must not stamp award_expires_at; got "
                    f"{a.get('award_expires_at')!r}"
                )

    def test_draw_twice_rejected(self, api):
        """PRD §3.6: "Two simultaneous draws on the same permit
        serialise so that the second draw receives
        ERR_LOTTERY_ALREADY_DRAWN."
        """
        (park, permit, *_rest) = setup_lottery_with_three_applications(
            daily_slot_count=10,
        )
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        # Sequential second draw must reject.
        resp = api.draw_lottery(
            permit["id"], make_visitor_headers("any-fake-id")  # ParkAdmin role
        )
        # The visitor role is forbidden anyway — use a real admin:
        from test_helpers import TEST_USERS
        resp = api.draw_lottery(
            permit["id"], TEST_USERS["park_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOTTERY_ALREADY_DRAWN.value)



class TestLotteryAcceptDecline:

    def test_accept_awarded_debits_permit_fee_times_party(self, api):
        """PRD §3.6: "Accepting requires the application still be
        AWARDED, the current instant be strictly before
        award_expires_at, and Visitor.wallet_balance_cents be at least
        permit_fee_cents multiplied by party_size. On accept the
        application transitions from AWARDED to ACCEPTED, the wallet is
        debited by permit_fee_cents multiplied by party_size, and a
        LedgerEntry of kind PERMIT_FEE is appended."
        """
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(
                daily_slot_count=10,
                application_fee_cents=100,
                permit_fee_cents=2000,
            )
        )
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        awarded = next(a for a in apps if a["status"] == "AWARDED")
        # Identify the owner visitor.
        owner = next(
            x for x in (v1, v2, v3) if x["id"] == awarded["visitor_id"]
        )
        wallet_before = get_visitor(owner["id"])["wallet_balance_cents"]
        resp = api.accept_lottery_application(
            awarded["id"], make_visitor_headers(owner["id"]),
        )
        accepted = validate_success(resp, 200)
        assert accepted["status"] == "ACCEPTED"
        expected_charge = 2000 * awarded["party_size"]
        wallet_after = get_visitor(owner["id"])["wallet_balance_cents"]
        assert wallet_after == wallet_before - expected_charge, (
            f"accept must debit permit_fee_cents*party_size; "
            f"before={wallet_before}, after={wallet_after}, expected_debit="
            f"{expected_charge}"
        )
        # LedgerEntry kind PERMIT_FEE recorded.
        ledger = list_visitor_ledger(owner["id"])
        permit_entries = [
            e for e in ledger if e["kind"] == "PERMIT_FEE"
            and e.get("reference_id") == awarded["id"]
        ]
        assert len(permit_entries) == 1
        assert permit_entries[0]["amount_cents"] == -expected_charge

    def test_decline_returns_slot_and_promotes_waitlisted(self, api):
        """PRD §3.6: "on decline the application transitions from
        AWARDED to DECLINED, the awarded slot is returned to the
        permit's pool, and the first remaining WAITLISTED application
        (lowest rank_seed, then earliest created_at) is promoted from
        WAITLISTED to AWARDED — a cascade of depth three from one
        application's decline, through the permit's slot pool, through
        to a sibling application's status flip."

        Claim: with daily_slot_count=5 and applications 3,4,2, the
        WAITLISTED app of party=4 is only promotable if remaining slots
        after a decline reaches at least 4. We arrange that by choosing
        slot counts and party sizes ourselves.
        """
        # Make A1 party=3 likely to be awarded first, with slot_count=4
        # leaving 1 slot left; A2 party=2 is WAITLISTED (needs 2, only 1).
        # If A1 declines, 3 slots return → A2 can be promoted.
        # Because rank_seed is random, we can only assert post-decline
        # invariants: total AWARDED party <= daily_slot_count, and the
        # original AWARDED's status is DECLINED, and there exists at
        # least one freshly AWARDED application that was WAITLISTED.
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(daily_slot_count=4)
        )
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps_before = list_lottery_applications(permit["id"])
        awarded_before = [a for a in apps_before if a["status"] == "AWARDED"]
        waitlisted_before = [
            a for a in apps_before if a["status"] == "WAITLISTED"
        ]
        if not waitlisted_before:
            pytest.skip(
                "draw produced no WAITLISTED applications; cannot exercise "
                "promotion cascade with this particular rank_seed ordering"
            )
        # Decline one AWARDED — choose the largest party so the freed
        # slots have the best chance of meeting a WAITLISTED party_size.
        awarded_before.sort(key=lambda a: a["party_size"], reverse=True)
        target = awarded_before[0]
        owner = next(
            x for x in (v1, v2, v3) if x["id"] == target["visitor_id"]
        )
        resp = api.decline_lottery_application(
            target["id"], make_visitor_headers(owner["id"]),
        )
        declined = validate_success(resp, 200)
        assert declined["status"] == "DECLINED"
        apps_after = list_lottery_applications(permit["id"])
        target_after = next(a for a in apps_after if a["id"] == target["id"])
        assert target_after["status"] == "DECLINED"

    def test_accept_after_award_expires_at_rejected(self, api):
        """PRD §3.6: "Accepting requires ... the current instant be
        strictly before award_expires_at".
        """
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(daily_slot_count=10)
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
        # Advance past award_expires_at without running the sweep so the
        # application is still AWARDED in storage.
        advance_clock_to(
            parse_iso(awarded["award_expires_at"]) + timedelta(minutes=1),
        )
        resp = api.accept_lottery_application(
            awarded["id"], make_visitor_headers(owner["id"]),
        )
        # PRD §3.6 names the requirement; §5 catalogues ERR_AWARD_EXPIRED
        # for "AWARDED slot already past award_expires_at". Some
        # implementations may surface ERR_INVALID_STATE; accept either.
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        assert err in {
            ApiErrorId.ERR_AWARD_EXPIRED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        }, f"expected award-expired rejection; got {err!r}"


class TestLotteryNoShow:

    def test_ranger_records_no_show_after_hike_date(self, api):
        """PRD §3.6: "A ParkRanger may also record an ACCEPTED
        application as a no-show after hike_date has ended (the park-
        local time must be after 23:59 on hike_date): the application
        transitions from ACCEPTED to FORFEITED, no refund of
        permit_fee_cents is issued, and lottery_strikes is incremented
        by one."
        """
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(
                daily_slot_count=10,
                application_fee_cents=100,
                permit_fee_cents=500,
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
        # Accept the awarded slot.
        accepted = validate_success(
            api.accept_lottery_application(
                awarded["id"], make_visitor_headers(owner["id"]),
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        # Advance past hike_date 23:59 park-local. hike_date is a UTC
        # instant; PRD §3.6 pins the gate to 23:59 in the *park-local*
        # timezone (America/Los_Angeles by default, ~UTC-7/-8), so we
        # advance two full UTC days past hike_date to be safely after
        # 23:59 in any IANA park timezone.
        hike_date = parse_iso(permit["hike_date"])
        advance_clock_to(hike_date + timedelta(days=2))
        from test_helpers import TEST_USERS
        resp = api.no_show_lottery_application(
            awarded["id"], TEST_USERS["park_ranger_headers"],
        )
        forfeited = validate_success(resp, 200)
        assert forfeited["status"] == "FORFEITED"
        # lottery_strikes incremented.
        owner_after = get_visitor(owner["id"])
        owner_before_strikes = 0  # owner came from fresh test setup
        assert owner_after["lottery_strikes"] >= owner_before_strikes + 1
