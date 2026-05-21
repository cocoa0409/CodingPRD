"""Difficulty-design coverage — at least two tests per declared
instance in the test-targeting index.

Each test docstring carries a `# difficulty: <rule_id>/<instance>` tag
so coverage can be audited. Each test pins to a verbatim PRD sentence
stating the underlying rule.

The difficulty-design index covers 9 rules × 2 instances = 18 instances.
Each instance is covered by at least two dedicated tests below.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from test_helpers import (
    AWARD_EXPIRY_HOURS,
    ApiErrorId,
    BOOKING_FEE_CENTS,
    PROMOTION_HOLD_HOURS,
    TAX_RATE,
    TEST_USERS,
    advance_clock_by_days,
    advance_clock_by_hours,
    advance_clock_by_minutes,
    advance_clock_to,
    api_client,
    cancel_backcountry_permit,
    cancel_campground_reservation,
    confirm_backcountry_permit,
    confirm_campground_reservation,
    create_backcountry_permit,
    create_backcountry_zone,
    create_campground_reservation,
    create_lottery_permit,
    create_park,
    create_timed_entry,
    create_visitor,
    create_visitor_with_wallet,
    current_clock,
    date_to_local_str,
    deposit_wallet,
    draw_lottery,
    find_held_promoted_reservation,
    freeze_park,
    get_campground_reservation,
    get_park,
    get_visitor,
    iso_utc,
    issue_pass,
    list_lottery_applications,
    list_visitor_ledger,
    list_waitlist,
    make_visitor_headers,
    parse_iso,
    reopen_park,
    restrict_park,
    revoke_pass,
    run_sweep,
    setup_at_capacity_campground,
    setup_confirmed_backcountry_with_window,
    setup_confirmed_campground_reservation,
    setup_confirmed_timed_entry,
    setup_park_with_backcountry_zone,
    setup_park_with_campground,
    setup_park_with_lottery_permit,
    setup_pass_waived_vs_paid_timed_entries,
    setup_two_campground_reservations_for_refund_variant,
    setup_visitor_with_lottery_strikes,
    submit_lottery_application,
    utcnow,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    create_campground_reservation_payload,
    create_timed_entry_payload,
    create_waitlist_entry,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_campground_refund_standard_vs_group_at_14d_out(self, api):
        """# difficulty: dual_variant_calc/campground_refund_standard_vs_group_strict

        PRD §3.4: "When hours to check-in is at least 336 (fourteen
        days), the refund is total_fee_cents minus the 800-cent booking
        fee, so the visitor forfeits only the booking fee."

        PRD §3.4 GROUP variant: "For a GROUP site, the booking fee is
        always forfeit and one full night's nightly_rate_cents is held
        back as a non-refundable deposit regardless of timing: the
        refund is total_fee_cents minus 800 minus nightly_rate_cents,
        clamped to zero when negative."

        Claim: at >= 336h, STANDARD r_std produces refund =
        total - 800 = 7624; GROUP r_grp produces refund =
        total - 800 - nightly = 26944. Different formula on the same
        timing because of the site_kind variant.
        """
        (park, c, v1, r_std, v2, r_grp) = (
            setup_two_campground_reservations_for_refund_variant(
                days_out=30,
                nightly_standard_fee_cents=3500,
                nightly_group_fee_cents=12000,
                group_party_size=10,
                group_nights=3,
                standard_party_size=2,
                standard_nights=2,
            )
        )
        # Both reservations are still at ~30 days out (> 336h).
        cancel_campground_reservation(c["id"], r_std["id"], v1)
        cancel_campground_reservation(c["id"], r_grp["id"], v2)
        r_std_after = get_campground_reservation(c["id"], r_std["id"])
        r_grp_after = get_campground_reservation(c["id"], r_grp["id"])
        assert r_std_after["refund_cents"] == 7624, (
            f"STANDARD 14d+ refund must be total(8424) - 800 = 7624; "
            f"got {r_std_after['refund_cents']}"
        )
        assert r_grp_after["refund_cents"] == 26944, (
            f"GROUP variant refund must be total(39744) - 800 - "
            f"nightly(12000) = 26944; got {r_grp_after['refund_cents']}"
        )

    def test_campground_refund_group_lower_than_standard_at_same_timing(self, api):
        """# difficulty: dual_variant_calc/campground_refund_standard_vs_group_strict

        PRD §3.4: "This produces a strictly lower refund than the
        STANDARD variant on identical inputs whenever the STANDARD
        variant would have returned more than total_fee_cents minus
        800 minus nightly_rate_cents."

        Claim: on identical total + nightly inputs, the GROUP-variant
        refund is strictly less than the STANDARD-variant refund.
        """
        # Build STANDARD vs GROUP reservations on a campground that lets
        # us probe identical numerical formulas. We compute the
        # difference algebraically: 7624 (STANDARD 14d+) vs 26944 (GROUP)
        # — the GROUP value happens to be larger because totals differ,
        # but the per-formula comparison is: STANDARD returned
        # total_std - 800 = 7624 and GROUP returned
        # total_grp - 800 - nightly_grp = 26944. The STANDARD branch
        # would have returned total_grp - 800 = 38944 on the GROUP's
        # numeric inputs, which is strictly greater than 26944. So
        # GROUP variant strictly cuts refund vs the STANDARD branch on
        # identical inputs.
        (park, c, v1, r_std, v2, r_grp) = (
            setup_two_campground_reservations_for_refund_variant(
                days_out=30,
            )
        )
        cancel_campground_reservation(c["id"], r_grp["id"], v2)
        r_grp_after = get_campground_reservation(c["id"], r_grp["id"])
        # Compute the hypothetical STANDARD refund on the GROUP's totals.
        hypothetical_std = r_grp["total_fee_cents"] - BOOKING_FEE_CENTS
        assert r_grp_after["refund_cents"] < hypothetical_std, (
            f"PRD §3.4 GROUP variant must yield a strictly lower refund "
            f"than the STANDARD branch on identical totals; got "
            f"GROUP={r_grp_after['refund_cents']} vs STANDARD-on-same"
            f"-total={hypothetical_std}"
        )

    def test_timed_entry_refund_paid_vs_pass_waived(self, api):
        """# difficulty: dual_variant_calc/timed_entry_refund_paid_vs_pass_waived

        PRD §3.3: "When that number is at least 168 (seven days), the
        refund is the full entry_fee_cents."

        PRD §3.3 pass_waived variant: "when the original
        entry_fee_cents was zero because a valid pass was supplied at
        confirm time, the refund is always zero regardless of timing
        — every tier above collapses to zero because the fee was zero."

        Claim: paid reservation cancelled >= 168h out refunds full fee
        (>0); pass-waived reservation refunds 0 cents on identical
        timing.
        """
        (park, v1, pass_, v2, r_pass, r_paid) = (
            setup_pass_waived_vs_paid_timed_entries(days_out=10)
        )
        # Both >= 168h before entry. Cancel both.
        from test_helpers import cancel_timed_entry
        if r_paid["entry_fee_cents"] > 0:
            cancel_timed_entry(park["id"], r_paid["id"], v2)
            ledger_paid = list_visitor_ledger(v2["id"])
            refunds_paid = [
                e for e in ledger_paid if e["kind"] == "FEE_REFUND"
                and e.get("reference_id") == r_paid["id"]
            ]
            assert len(refunds_paid) == 1
            assert refunds_paid[0]["amount_cents"] == r_paid["entry_fee_cents"], (
                f"paid reservation refund at >=168h must equal "
                f"entry_fee_cents; got {refunds_paid[0]['amount_cents']}"
            )
        else:
            pytest.skip(
                "default entry_fee_cents is zero; cannot exercise paid path"
            )
        cancel_timed_entry(park["id"], r_pass["id"], v1)
        ledger_pass = list_visitor_ledger(v1["id"])
        refunds_pass = [
            e for e in ledger_pass if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r_pass["id"]
        ]
        if refunds_pass:
            assert all(e["amount_cents"] == 0 for e in refunds_pass), (
                f"pass_waived refund must be zero regardless of timing; "
                f"got {refunds_pass}"
            )

    def test_timed_entry_pass_waived_records_no_ledger_charge(self, api):
        """# difficulty: dual_variant_calc/timed_entry_refund_paid_vs_pass_waived

        PRD §3.3: "the wallet is debited by entry_fee_cents".

        Claim: confirming a pass_waived timed-entry (entry_fee_cents=0)
        does not write a wallet-debit ledger entry, so the visitor's
        wallet stays at the deposit total. This is the precondition
        underpinning the variant's "refund always zero" rule: there is
        nothing to refund because no fee was charged.
        """
        (park, v1, pass_, v2, r_pass, r_paid) = (
            setup_pass_waived_vs_paid_timed_entries(days_out=10)
        )
        # entry_fee_cents was 0 for the pass-waived reservation.
        assert r_pass["entry_fee_cents"] == 0
        ledger_v1 = list_visitor_ledger(v1["id"])
        charges = [
            e for e in ledger_v1 if e["kind"] == "FEE_CHARGE"
            and e.get("reference_id") == r_pass["id"]
        ]
        # Either no charge entry at all, or zero-amount entry — both
        # are PRD-faithful interpretations of "debit by entry_fee_cents=0".
        for e in charges:
            assert e["amount_cents"] == 0, (
                f"pass_waived confirm must not record a non-zero "
                f"FEE_CHARGE; got {e}"
            )


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_booking_total_sum_first_evaluation_order(self, api):
        """# difficulty: combinatorial_formula/booking_total_rounding_order_mode_b

        PRD §3.4: "Compute the site total as nightly_rate_cents
        multiplied by nights; both operands are already integer cents,
        so the product is exact. Add the fixed booking fee of 800 cents
        to produce the pre-tax subtotal. Compute the tax amount as the
        pre-tax subtotal multiplied by the tax rate of 0.08, then floor
        that tax amount to an integer cent. The total_fee_cents value
        is the pre-tax subtotal plus the floored tax amount. The order
        is pinned: tax is applied to the rounded-integer pre-tax
        subtotal, then floored, and only then added — the system never
        floors each nightly rate independently."

        Claim: nightly=3500, nights=2 → total_fee_cents=8424; the
        nightly_rate_cents persisted on the reservation equals 3500
        (raw rate) and NOT 3780 (rate with floor(3500*0.08) added).
        """
        park, c = setup_park_with_campground(nightly_standard_fee_cents=3500)
        v = create_visitor_with_wallet(wallet_cents=20_000)
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
            f"PRD §3.4 forbids flooring each nightly rate; "
            f"nightly_rate_cents must remain the raw 3500, not 3780; "
            f"got {r['nightly_rate_cents']}"
        )
        assert r["total_fee_cents"] == 8424

    def test_booking_total_arithmetic_at_alternate_inputs(self, api):
        """# difficulty: combinatorial_formula/booking_total_rounding_order_mode_b

        PRD §3.4: "Compute the tax amount as the pre-tax subtotal
        multiplied by the tax rate of 0.08, then floor that tax amount
        to an integer cent. The total_fee_cents value is the pre-tax
        subtotal plus the floored tax amount."

        Claim: nightly=4567, nights=3 → pre_tax = 4567*3 + 800 = 14501;
        tax = floor(14501 * 0.08) = floor(1160.08) = 1160; total = 15661.
        """
        park, c = setup_park_with_campground(nightly_standard_fee_cents=4567)
        v = create_visitor_with_wallet(wallet_cents=50_000)
        r = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=30),
            ),
            check_out_date_local=date_to_local_str(
                date.today() + timedelta(days=33),
            ),
        )
        pre_tax = 4567 * 3 + BOOKING_FEE_CENTS
        tax = int(pre_tax * TAX_RATE)  # int() truncates toward zero == floor
        assert r["total_fee_cents"] == pre_tax + tax, (
            f"PRD §3.4 formula: total = (nightly*nights + 800) + "
            f"floor((nightly*nights+800)*0.08); expected "
            f"{pre_tax + tax}, got {r['total_fee_cents']}"
        )

    def test_backcountry_buffer_collision_rejected(self, api):
        """# difficulty: combinatorial_formula/backcountry_overlap_with_buffer_mode_a

        PRD §3.7: "a new permit [a, b) collides with an existing [c, d)
        exactly when a is strictly less than d plus buffer and c is
        strictly less than b plus buffer."

        Claim: ranger_buffer_minutes=30, existing [09:00, 11:00),
        new [11:15, 13:00) — gap 15 min < 30 min → reject with
        ERR_RANGER_BUFFER_VIOLATION.
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

    def test_backcountry_buffer_equal_gap_passes(self, api):
        """# difficulty: combinatorial_formula/backcountry_overlap_with_buffer_mode_a

        PRD §3.7: "equality at b equal to c passes the test exactly
        when the gap between them is at least buffer."

        Claim: gap == buffer (30 min on both sides) → confirm succeeds.
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


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_lottery_draw_fork_awarded_and_waitlisted(self, api):
        """# difficulty: non_linear_state_machine/lottery_application_branching_with_revert

        PRD §3.6: "iterate in sorted order, and for each application,
        if the remaining-slot counter is at least the application's
        party_size, mark the application AWARDED and subtract party_size
        from the counter, otherwise mark the application WAITLISTED."

        Claim: with daily_slot_count=4 and three applications of party
        size 3, 4, 2, after a draw at least one ends WAITLISTED and at
        least one ends AWARDED (the SUBMITTED→AWARDED and
        SUBMITTED→WAITLISTED forks both fire).
        """
        from test_helpers import setup_lottery_with_three_applications
        (park, permit, v1, v2, v3, a1, a2, a3) = (
            setup_lottery_with_three_applications(
                daily_slot_count=4,
                application_fee_cents=100,
                permit_fee_cents=100,
            )
        )
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        awarded = [a for a in apps if a["status"] == "AWARDED"]
        waitlisted = [a for a in apps if a["status"] == "WAITLISTED"]
        assert len(awarded) >= 1, (
            f"PRD §3.6 fork must produce at least one AWARDED; got 0"
        )
        assert len(waitlisted) >= 1, (
            f"PRD §3.6 fork must produce at least one WAITLISTED on "
            f"slot_count=4 with party sums 3+4+2=9; got 0"
        )
        # AWARDED entries carry award_expires_at; WAITLISTED do not.
        for a in awarded:
            assert a.get("award_expires_at") not in (None, ""), (
                f"AWARDED app must carry award_expires_at; got "
                f"{a.get('award_expires_at')!r}"
            )
        for w in waitlisted:
            assert w.get("award_expires_at") in (None, ""), (
                f"WAITLISTED app must not stamp award_expires_at; got "
                f"{w.get('award_expires_at')!r}"
            )

    def test_lottery_decline_branches_with_cascade(self, api):
        """# difficulty: non_linear_state_machine/lottery_application_branching_with_revert

        PRD §3.6: "on decline the application transitions from AWARDED
        to DECLINED, the awarded slot is returned to the permit's pool,
        and the first remaining WAITLISTED application (lowest
        rank_seed, then earliest created_at) is promoted from
        WAITLISTED to AWARDED."

        Claim: AWARDED → DECLINED is a different terminal branch from
        ACCEPTED (no PERMIT_FEE LedgerEntry written) and triggers the
        slot-return cascade (a sibling WAITLISTED becomes AWARDED).
        """
        from test_helpers import (
            setup_park_with_lottery_permit,
            submit_lottery_application,
            create_visitor_with_wallet,
            advance_clock_to,
            current_clock,
            iso_utc,
        )
        from datetime import timedelta
        # Deterministic cascade: slot_count=2 with three apps each party=1.
        # No matter the rank_seed shuffle, exactly 2 AWARDED + 1 WAITLISTED,
        # and the WAITLISTED party (1) always fits in the freed slot (1).
        now = current_clock()
        park, permit = setup_park_with_lottery_permit(
            daily_slot_count=2,
            application_fee_cents=100,
            permit_fee_cents=100,
            per_application_max_party=4,
            lottery_open_at=iso_utc(now - timedelta(hours=1)),
            lottery_close_at=iso_utc(now + timedelta(hours=2)),
            draw_at=iso_utc(now + timedelta(hours=3)),
            hike_date=iso_utc(now + timedelta(days=10)),
        )
        v1 = create_visitor_with_wallet(wallet_cents=100_000)
        v2 = create_visitor_with_wallet(wallet_cents=100_000)
        v3 = create_visitor_with_wallet(wallet_cents=100_000)
        submit_lottery_application(permit["id"], v1, party_size=1)
        submit_lottery_application(permit["id"], v2, party_size=1)
        submit_lottery_application(permit["id"], v3, party_size=1)
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        awarded = [a for a in apps if a["status"] == "AWARDED"]
        waitlisted_before = {
            a["id"] for a in apps if a["status"] == "WAITLISTED"
        }
        assert awarded and waitlisted_before, (
            "Setup expectation: slot=2 with three party=1 apps must "
            "produce 2 AWARDED + 1 WAITLISTED"
        )
        target = awarded[0]
        owner = next(
            x for x in (v1, v2, v3) if x["id"] == target["visitor_id"]
        )
        api.decline_lottery_application(
            target["id"], make_visitor_headers(owner["id"]),
        )
        apps_after = list_lottery_applications(permit["id"])
        target_after = next(a for a in apps_after if a["id"] == target["id"])
        assert target_after["status"] == "DECLINED"
        promoted = [
            a for a in apps_after
            if a["id"] in waitlisted_before and a["status"] == "AWARDED"
        ]
        assert len(promoted) >= 1, (
            f"PRD §3.6 cascade: decline must promote a previously "
            f"WAITLISTED app; got {len(promoted)}"
        )
        # No PERMIT_FEE entry was written for the declined app.
        ledger_owner = list_visitor_ledger(owner["id"])
        permit_fees = [
            e for e in ledger_owner if e["kind"] == "PERMIT_FEE"
            and e.get("reference_id") == target["id"]
        ]
        assert len(permit_fees) == 0, (
            f"DECLINED branch must not write PERMIT_FEE; got {permit_fees}"
        )

    def test_park_open_restricted_reopen_freeze_paths(self, api):
        """# difficulty: non_linear_state_machine/park_compound_status_with_revert

        PRD §2.7: "From OPEN the park may be moved to RESTRICTED ...
        or directly to FROZEN. From RESTRICTED the park may be moved
        back to OPEN or onward to FROZEN. From FROZEN the park may
        only be returned to OPEN."

        Claim: each declared transition is observable on the same Park
        entity — OPEN → RESTRICTED → OPEN → FROZEN → OPEN.
        """
        park = create_park()
        assert park["status"] == "OPEN"
        s1 = restrict_park(park["id"])
        assert s1["status"] == "RESTRICTED"
        s2 = reopen_park(park["id"])
        assert s2["status"] == "OPEN"
        s3 = freeze_park(park["id"])
        assert s3["status"] == "FROZEN"
        s4 = reopen_park(park["id"])
        assert s4["status"] == "OPEN"

    def test_park_status_gates_downstream_creates(self, api):
        """# difficulty: non_linear_state_machine/park_compound_status_with_revert

        PRD §2.7: "When the park is RESTRICTED, new timed-entry
        reservation creation and new backcountry permit creation are
        blocked with ERR_PARK_RESTRICTED, but new campground reservation
        creation continues to be allowed. When the park is FROZEN,
        every form of new reservation creation, every new lottery
        application, every new backcountry permit, and lottery draws
        themselves are blocked with ERR_PARK_FROZEN".

        Claim: in RESTRICTED, campground create succeeds, backcountry
        create rejects with ERR_PARK_RESTRICTED; in FROZEN, campground
        create rejects with ERR_PARK_FROZEN.
        """
        park = create_park(timed_entry_daily_capacity=10)
        c = api.create_campground(
            park["id"],
            {
                "name": "RestrictedCamp",
                "standard_site_count": 5,
                "group_site_count": 2,
                "nightly_standard_fee_cents": 3500,
                "nightly_group_fee_cents": 12000,
            },
            TEST_USERS["park_admin_headers"],
        )
        camp = validate_success(c, 201)
        z = api.create_backcountry_zone(
            park["id"],
            {
                "name": "RestrictedZone",
                "nightly_quota_people": 20,
                "per_party_fee_cents": 1500,
            },
            TEST_USERS["park_admin_headers"],
        )
        zone = validate_success(z, 201)
        v = create_visitor_with_wallet(wallet_cents=20_000)
        # RESTRICTED.
        restrict_park(park["id"])
        # Campground create still permitted.
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
        resp_cg = api.create_campground_reservation(
            camp["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=ci, check_out_date_local=co,
            ),
            make_visitor_headers(v["id"]),
        )
        assert resp_cg.status_code == 201, (
            f"campground create must succeed in RESTRICTED; got "
            f"{resp_cg.status_code}: {resp_cg.text}"
        )
        # Backcountry create blocked with ERR_PARK_RESTRICTED.
        resp_bc = api.create_backcountry_permit(
            zone["id"],
            {
                "party_size": 2,
                "entry_datetime_local": iso_utc(
                    utcnow() + timedelta(days=10),
                ),
                "exit_datetime_local": iso_utc(
                    utcnow() + timedelta(days=11),
                ),
            },
            make_visitor_headers(v["id"]),
        )
        validate_error(resp_bc, ApiErrorId.ERR_PARK_RESTRICTED.value)
        # FROZEN.
        freeze_park(park["id"])
        ci2 = date_to_local_str(date.today() + timedelta(days=40))
        co2 = date_to_local_str(date.today() + timedelta(days=41))
        resp_frozen = api.create_campground_reservation(
            camp["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=ci2, check_out_date_local=co2,
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp_frozen, ApiErrorId.ERR_PARK_FROZEN.value)


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_campground_cancel_cascades_to_waitlist_promotion(self, api):
        """# difficulty: transitive_cascade/campground_cancel_to_waitlist_promotion_to_new_reservation

        PRD §3.4: "On success the reservation transitions from
        CONFIRMED to CANCELLED ... the site occupancy is released, and
        the waitlist-promotion cascade fires: a fresh
        CampgroundReservation may be created in HELD for the next
        eligible WaitlistEntry, and that waitlist entry's status is
        set to PROMOTED (cascade depth three — cancel produces freed
        inventory, which may produce a promoted reservation, which
        itself flips the waitlist entry's status)."

        PRD §3.5: "sets that reservation's held_until to 4 hours after
        the moment of promotion (this is the four-hour promotion-hold
        constant), writes the new reservation's id into the waitlist
        entry's promoted_reservation_id, and transitions the waitlist
        entry from WAITING to PROMOTED."
        """
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=2,
            waitlist_window_hours=24,
        )
        holder = create_visitor_with_wallet(wallet_cents=20_000)
        waitlister = create_visitor_with_wallet(wallet_cents=20_000)
        ci_dt = current_clock() + timedelta(hours=12)
        ci = ci_dt.date().isoformat()
        co = (ci_dt + timedelta(days=2)).date().isoformat()
        r_held = create_campground_reservation(
            c["id"], holder,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=ci, check_out_date_local=co,
        )
        r1 = confirm_campground_reservation(c["id"], r_held["id"], holder)
        w = create_waitlist_entry(
            c["id"], waitlister, site_kind="STANDARD",
            check_in_date_local=ci, nights=2,
        )
        # Cancel cascades.
        cancel_campground_reservation(c["id"], r1["id"], holder)
        entries = list_waitlist(c["id"])
        w_after = next(x for x in entries if x["id"] == w["id"])
        assert w_after["status"] == "PROMOTED"
        assert w_after["promoted_reservation_id"] is not None
        # The HELD reservation for the waitlister exists.
        new_r = find_held_promoted_reservation(c["id"], waitlister["id"])
        assert new_r is not None
        # held_until == created_at + 4h.
        delta = (
            parse_iso(new_r["held_until"]) - parse_iso(new_r["created_at"])
        ).total_seconds() / 3600
        assert abs(delta - PROMOTION_HOLD_HOURS) < 0.01

    def test_campground_cancel_does_not_promote_when_no_waitlister(self, api):
        """# difficulty: transitive_cascade/campground_cancel_to_waitlist_promotion_to_new_reservation

        PRD §3.4: "the waitlist-promotion cascade fires: a fresh
        CampgroundReservation may be created in HELD for the next
        eligible WaitlistEntry".

        Claim: when no WaitlistEntry exists, the cancel still succeeds
        but no new HELD reservation is created — the cascade's tail
        depends on the previous step's freed inventory matching an
        eligible waiting visitor.
        """
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=2,
            waitlist_window_hours=24,
        )
        holder = create_visitor_with_wallet(wallet_cents=20_000)
        ci_dt = current_clock() + timedelta(hours=12)
        ci = ci_dt.date().isoformat()
        co = (ci_dt + timedelta(days=2)).date().isoformat()
        r_held = create_campground_reservation(
            c["id"], holder,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=ci, check_out_date_local=co,
        )
        r1 = confirm_campground_reservation(c["id"], r_held["id"], holder)
        cancel_campground_reservation(c["id"], r1["id"], holder)
        # No waitlister exists; no new HELD reservation must be created.
        from test_helpers import list_campground_reservations
        rows = list_campground_reservations(c["id"])
        held_rows = [r for r in rows if r["status"] == "HELD"]
        assert len(held_rows) == 0, (
            f"with no waitlister, cancel must not produce a HELD "
            f"reservation; got {held_rows}"
        )

    def test_lottery_decline_promotes_with_award_expires_at_stamp(self, api):
        """# difficulty: transitive_cascade/lottery_decline_to_waitlist_promotion_to_award_expiry_clock

        PRD §3.6: "on decline the application transitions from AWARDED
        to DECLINED, the awarded slot is returned to the permit's
        pool, and the first remaining WAITLISTED application (lowest
        rank_seed, then earliest created_at) is promoted from
        WAITLISTED to AWARDED".

        PRD §3.6: "On completion, transition the permit from CLOSED to
        DRAWN and set each AWARDED application's award_expires_at to
        72 hours after draw_at." The decline cascade reuses the same
        rule: the freshly-promoted application gets award_expires_at.
        """
        from test_helpers import (
            setup_park_with_lottery_permit,
            submit_lottery_application,
        )
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
        submit_lottery_application(permit["id"], v1, party_size=2)
        submit_lottery_application(permit["id"], v2, party_size=2)
        submit_lottery_application(permit["id"], v3, party_size=2)
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        awarded = [a for a in apps if a["status"] == "AWARDED"]
        waitlisted_ids = {a["id"] for a in apps if a["status"] == "WAITLISTED"}
        assert len(awarded) == 1
        assert len(waitlisted_ids) == 2
        target = awarded[0]
        owner = next(
            x for x in (v1, v2, v3) if x["id"] == target["visitor_id"]
        )
        api.decline_lottery_application(
            target["id"], make_visitor_headers(owner["id"]),
        )
        apps_after = list_lottery_applications(permit["id"])
        promoted = [
            a for a in apps_after
            if a["id"] in waitlisted_ids and a["status"] == "AWARDED"
        ]
        assert len(promoted) == 1
        # Newly-promoted carries award_expires_at.
        new_award = promoted[0]
        assert new_award.get("award_expires_at") not in (None, "")

    def test_award_expiry_sweep_promotes_next_waitlisted(self, api):
        """# difficulty: transitive_cascade/lottery_decline_to_waitlist_promotion_to_award_expiry_clock

        PRD §3.6: "When award_expires_at has passed on an AWARDED
        application, the sweep transitions it from AWARDED to
        FORFEITED, increments the visitor's lottery_strikes by one,
        returns the slot to the pool, and promotes the next WAITLISTED
        application."

        Claim: sweep-triggered FORFEITURE produces the same cascade as
        decline — a previously WAITLISTED app becomes AWARDED with
        award_expires_at stamped.
        """
        from test_helpers import (
            setup_park_with_lottery_permit,
            submit_lottery_application,
        )
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
        submit_lottery_application(permit["id"], v1, party_size=2)
        submit_lottery_application(permit["id"], v2, party_size=2)
        submit_lottery_application(permit["id"], v3, party_size=2)
        advance_clock_to(
            parse_iso(permit["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit["id"])
        apps = list_lottery_applications(permit["id"])
        awarded = [a for a in apps if a["status"] == "AWARDED"]
        waitlisted_ids = {a["id"] for a in apps if a["status"] == "WAITLISTED"}
        # Advance past award_expires_at without anyone accepting/declining.
        advance_clock_to(
            parse_iso(awarded[0]["award_expires_at"]) + timedelta(minutes=1),
        )
        run_sweep()
        apps_after = list_lottery_applications(permit["id"])
        promoted = [
            a for a in apps_after
            if a["id"] in waitlisted_ids and a["status"] == "AWARDED"
        ]
        assert len(promoted) == 1, (
            f"sweep cascade must promote a WAITLISTED app on forfeiture; "
            f"got {len(promoted)}"
        )
        assert promoted[0].get("award_expires_at") not in (None, "")


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_frozen_park_beats_insufficient_funds_on_campground_create(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_fiscal_park_frozen_beats_insufficient_funds

        PRD §2.12: "Park posture. Park-level frozen and restricted
        blocks (ERR_PARK_FROZEN, ERR_PARK_RESTRICTED) apply before any
        business-domain checks. A FROZEN park blocks every reservation/
        permit/lottery creation and every lottery draw".

        Claim: empty-wallet visitor posting a campground reservation
        creation in a FROZEN park sees ERR_PARK_FROZEN, not
        ERR_INSUFFICIENT_FUNDS. The state check runs before the fiscal
        check.
        """
        park, c = setup_park_with_campground()
        freeze_park(park["id"])
        v = create_visitor()
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

    def test_park_restricted_beats_other_checks_on_backcountry_create(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_fiscal_park_frozen_beats_insufficient_funds

        PRD §2.12: "Park posture ... apply before any business-domain
        checks."

        Claim: a backcountry create in a RESTRICTED park with an
        obviously invalid party_size (16, > 15) returns
        ERR_PARK_RESTRICTED — park-posture priority 5 beats the
        business_constraint priority 9 party-size check.
        """
        park, z = setup_park_with_backcountry_zone()
        restrict_park(park["id"])
        v = create_visitor_with_wallet(wallet_cents=10_000)
        resp = api.create_backcountry_permit(
            z["id"],
            {
                "party_size": 16,
                "entry_datetime_local": iso_utc(
                    utcnow() + timedelta(days=10),
                ),
                "exit_datetime_local": iso_utc(
                    utcnow() + timedelta(days=11),
                ),
            },
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARK_RESTRICTED.value)

    def test_strike_limit_beats_campground_full_on_group(self, api):
        """# difficulty: priority_pair_validation_conflict/safety_vs_capacity_strike_limit_beats_campground_full

        PRD §2.12: "The group-site strike check fires before the
        capacity check, so a strike-flagged visitor sees
        ERR_STRIKE_LIMIT_REACHED even when the group site has no
        inventory left."
        """
        park, c = setup_park_with_campground(
            standard_site_count=5, group_site_count=1,
            nightly_standard_fee_cents=3500, nightly_group_fee_cents=12000,
        )
        holder = create_visitor_with_wallet(wallet_cents=100_000)
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
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
        # Build a strike-3 visitor in the same park.
        park2, v_flagged = setup_visitor_with_lottery_strikes(target_strikes=3)
        # v_flagged was built against park2; we need them strike-3 but
        # posting to park's campground c. Strikes are global per PRD §3.1
        # ("Strikes accumulate across the calendar year"), so the visitor
        # carries strikes regardless of which park they were earned in.
        # Top up wallet so the fiscal check is not the discriminator.
        deposit_wallet(v_flagged["id"], 200_000)
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="GROUP", party_size=8,
                check_in_date_local=ci, check_out_date_local=co,
            ),
            make_visitor_headers(v_flagged["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STRIKE_LIMIT_REACHED.value)

    def test_strike_limit_beats_capacity_on_separate_dates(self, api):
        """# difficulty: priority_pair_validation_conflict/safety_vs_capacity_strike_limit_beats_campground_full

        PRD §2.12: "Strike-limit gates. For new lottery applications
        and for new GROUP campground reservations, a Visitor whose
        lottery_strikes is 3 is rejected with ERR_STRIKE_LIMIT_REACHED."

        Claim: even with a free GROUP slot (no capacity conflict at
        all), a strike-3 visitor's GROUP request is rejected with the
        strike error — the priority is observable in isolation, not
        only against capacity.
        """
        park, c = setup_park_with_campground(
            standard_site_count=5, group_site_count=5,
            nightly_standard_fee_cents=3500, nightly_group_fee_cents=12000,
        )
        park_dummy, v_flagged = setup_visitor_with_lottery_strikes(
            target_strikes=3,
        )
        deposit_wallet(v_flagged["id"], 200_000)
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="GROUP", party_size=8,
                check_in_date_local=ci, check_out_date_local=co,
            ),
            make_visitor_headers(v_flagged["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STRIKE_LIMIT_REACHED.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_campground_refund_inclusive_at_336h(self, api):
        """# difficulty: boundary_precision_check/refund_at_exact_336h_boundary_inclusive

        PRD §3.4: "When hours to check-in is at least 336 (fourteen
        days), the refund is total_fee_cents minus the 800-cent
        booking fee".

        Claim: cancelling at exactly 336h before check-in (00:00 park-
        local on check_in_date_local) falls in the >=336h branch:
        refund = total - 800.
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="STANDARD", party_size=2, nights=2, days_out=14,
            wallet_cents=20_000,
            campground_overrides={
                "nightly_standard_fee_cents": 3500,
                "nightly_group_fee_cents": 12000,
            },
        )
        assert r["total_fee_cents"] == 8424
        # Anchor: check_in = today + 14 days at 00:00 UTC.
        check_in = parse_iso(r["check_in_date_local"] + "T00:00:00+00:00")
        target = check_in - timedelta(hours=336)
        advance_clock_to(target)
        cancel_campground_reservation(c["id"], r["id"], v)
        refreshed = get_campground_reservation(c["id"], r["id"])
        assert refreshed["refund_cents"] == 7624, (
            f"PRD §3.4 >=336h branch at exactly 336h must return "
            f"total - 800 = 7624; got {refreshed['refund_cents']}"
        )

    def test_campground_refund_below_336h_falls_to_half_branch(self, api):
        """# difficulty: boundary_precision_check/refund_at_exact_336h_boundary_inclusive

        PRD §3.4: "When hours to check-in is at least 72 (three days)
        but less than 336, the refund is total_fee_cents minus 800,
        then multiplied by one-half, with the multiplication floored
        to an integer cent."

        Claim: cancelling at 335h59m before check-in (one minute below
        the 336h boundary) drops into the 72-336h branch: refund =
        floor((total - 800) * 0.5).
        """
        park, c, v, r = setup_confirmed_campground_reservation(
            site_kind="STANDARD", party_size=2, nights=2, days_out=14,
            wallet_cents=20_000,
            campground_overrides={
                "nightly_standard_fee_cents": 3500,
                "nightly_group_fee_cents": 12000,
            },
        )
        # PRD §3.4 anchors hours_to_check_in to check_in 00:00 in the
        # PARK-LOCAL timezone (converted to UTC), not UTC midnight. We
        # compute that anchor via zoneinfo for the park's IANA tz so
        # the 335h59m offset puts the clock into the 72-336h branch.
        from zoneinfo import ZoneInfo
        from datetime import datetime
        d = r["check_in_date_local"]
        y, mo, da = int(d[:4]), int(d[5:7]), int(d[8:10])
        check_in_park_local = datetime(
            y, mo, da, 0, 0, tzinfo=ZoneInfo(park["timezone"]),
        )
        check_in_utc = check_in_park_local.astimezone(timezone.utc)
        target = check_in_utc - timedelta(hours=335, minutes=59)
        advance_clock_to(target)
        cancel_campground_reservation(c["id"], r["id"], v)
        refreshed = get_campground_reservation(c["id"], r["id"])
        expected = (8424 - 800) // 2  # floor(7624 * 0.5) = 3812
        assert refreshed["refund_cents"] == expected, (
            f"PRD §3.4 just-below-336h must use the 50% branch; "
            f"expected {expected}, got {refreshed['refund_cents']}"
        )

    def test_lottery_draw_zero_eligible_applications(self, api):
        """# difficulty: boundary_precision_check/empty_set_lottery_draw_zero_eligible_apps

        PRD §3.6: "select every LotteryApplication whose
        lottery_permit_id matches and whose status is SUBMITTED and
        whose applying visitor's lottery_strikes is strictly less than
        3 ... initialise the remaining-slot counter to
        daily_slot_count; iterate in sorted order, and for each
        application, ... On completion, transition the permit from
        CLOSED to DRAWN".

        Claim: when zero applications are eligible (all applicants are
        strike-flagged), the draw still flips LotteryPermit.status to
        DRAWN but zero AWARDED rows exist; all SUBMITTED applications
        remain SUBMITTED.
        """
        # Build two visitors who become strike-3 after their SUBMITTED
        # applications, then run the draw. Strikes accrue across permits.
        park = create_park()
        v1 = create_visitor_with_wallet(wallet_cents=20_000)
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        # Permit M's draw_at sits far enough in the future to survive
        # all the sweeps used to accrue strikes (each cycle advances the
        # clock by ~73h+; 3 cycles × 2 visitors = ~440h ≈ 18 days, so
        # we set draw_at well beyond that to prevent auto-draw).
        now = current_clock()
        permit_main = create_lottery_permit(
            park["id"],
            lottery_open_at=iso_utc(now - timedelta(hours=1)),
            lottery_close_at=iso_utc(now + timedelta(days=60)),
            draw_at=iso_utc(now + timedelta(days=61)),
            hike_date=iso_utc(now + timedelta(days=90)),
            daily_slot_count=5,
            application_fee_cents=100,
            permit_fee_cents=100,
        )
        a_v1 = submit_lottery_application(permit_main["id"], v1, party_size=1)
        a_v2 = submit_lottery_application(permit_main["id"], v2, party_size=1)
        # Accumulate three strikes for each via short-window forfeiture.
        for v in (v1, v2):
            for _ in range(3):
                snow = current_clock()
                p = create_lottery_permit(
                    park["id"],
                    lottery_open_at=iso_utc(snow - timedelta(minutes=10)),
                    lottery_close_at=iso_utc(snow + timedelta(minutes=10)),
                    draw_at=iso_utc(snow + timedelta(minutes=15)),
                    hike_date=iso_utc(snow + timedelta(days=10)),
                    daily_slot_count=10,
                    application_fee_cents=100, permit_fee_cents=100,
                )
                submit_lottery_application(p["id"], v, party_size=1)
                advance_clock_to(snow + timedelta(minutes=16))
                draw_lottery(p["id"])
                advance_clock_by_hours(AWARD_EXPIRY_HOURS + 1)
                run_sweep()
        assert get_visitor(v1["id"])["lottery_strikes"] == 3
        assert get_visitor(v2["id"])["lottery_strikes"] == 3
        # Now run the main draw — both applicants are strike-3.
        advance_clock_to(
            parse_iso(permit_main["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit_main["id"])
        apps = list_lottery_applications(permit_main["id"])
        awarded = [a for a in apps if a["status"] == "AWARDED"]
        assert len(awarded) == 0, (
            f"PRD §3.6 strike filter must produce zero AWARDED; got "
            f"{len(awarded)}"
        )
        # Both applications remain SUBMITTED.
        for a in apps:
            assert a["status"] == "SUBMITTED", (
                f"filtered-out app should remain SUBMITTED; got "
                f"{a['status']!r}"
            )

    def test_lottery_draw_permit_status_drawn_even_with_zero_eligible(self, api):
        """# difficulty: boundary_precision_check/empty_set_lottery_draw_zero_eligible_apps

        PRD §3.6: "On completion, transition the permit from CLOSED to
        DRAWN".

        Claim: even when zero applications are eligible, the permit
        still moves to DRAWN — the empty-set boundary does not abort
        the state transition.
        """
        # Reuse the previous scenario but assert the permit status only.
        park = create_park()
        v1 = create_visitor_with_wallet(wallet_cents=20_000)
        now = current_clock()
        # Put permit_main's draw_at far enough in the future to survive
        # the 3 short-cycle sweeps used to accrue strikes.
        permit_main = create_lottery_permit(
            park["id"],
            lottery_open_at=iso_utc(now - timedelta(hours=1)),
            lottery_close_at=iso_utc(now + timedelta(days=60)),
            draw_at=iso_utc(now + timedelta(days=61)),
            hike_date=iso_utc(now + timedelta(days=90)),
            daily_slot_count=5,
            application_fee_cents=100,
            permit_fee_cents=100,
        )
        submit_lottery_application(permit_main["id"], v1, party_size=1)
        # Force v1 to strike-3.
        for _ in range(3):
            snow = current_clock()
            p = create_lottery_permit(
                park["id"],
                lottery_open_at=iso_utc(snow - timedelta(minutes=10)),
                lottery_close_at=iso_utc(snow + timedelta(minutes=10)),
                draw_at=iso_utc(snow + timedelta(minutes=15)),
                hike_date=iso_utc(snow + timedelta(days=10)),
                daily_slot_count=10,
                application_fee_cents=100, permit_fee_cents=100,
            )
            submit_lottery_application(p["id"], v1, party_size=1)
            advance_clock_to(snow + timedelta(minutes=16))
            draw_lottery(p["id"])
            advance_clock_by_hours(AWARD_EXPIRY_HOURS + 1)
            run_sweep()
        advance_clock_to(
            parse_iso(permit_main["lottery_close_at"]) + timedelta(minutes=1),
        )
        draw_lottery(permit_main["id"])
        # Read permit status via the park's permit list.
        permits = api_client.list_lottery_permits(
            park["id"], TEST_USERS["park_admin_headers"],
        ).json()["data"]
        permit_after = next(
            p for p in permits if p["id"] == permit_main["id"]
        )
        assert permit_after["status"] == "DRAWN"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_campground_create_blocked_in_frozen_park(self, api):
        """# difficulty: cross_entity_state_dependency/campground_create_depends_on_park_status

        PRD §2.7: "When the park is FROZEN, every form of new
        reservation creation ... are blocked with ERR_PARK_FROZEN".
        """
        park, c = setup_park_with_campground()
        freeze_park(park["id"])
        v = create_visitor_with_wallet(wallet_cents=20_000)
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

    def test_campground_create_succeeds_after_reopen(self, api):
        """# difficulty: cross_entity_state_dependency/campground_create_depends_on_park_status

        PRD §2.7: "From FROZEN the park may only be returned to OPEN."

        Claim: after a freeze + reopen, the same campground request
        that was previously rejected now succeeds — the gate is the
        parent Park's status, not the request itself.
        """
        park, c = setup_park_with_campground()
        freeze_park(park["id"])
        v = create_visitor_with_wallet(wallet_cents=20_000)
        ci = date_to_local_str(date.today() + timedelta(days=30))
        co = date_to_local_str(date.today() + timedelta(days=32))
        resp_frozen = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=ci, check_out_date_local=co,
            ),
            make_visitor_headers(v["id"]),
        )
        validate_error(resp_frozen, ApiErrorId.ERR_PARK_FROZEN.value)
        reopen_park(park["id"])
        # Identical request now succeeds because Park.status is OPEN.
        resp_open = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=ci, check_out_date_local=co,
            ),
            make_visitor_headers(v["id"]),
        )
        assert resp_open.status_code == 201, (
            f"identical request must succeed after reopen; got "
            f"{resp_open.status_code}: {resp_open.text}"
        )

    def test_timed_entry_with_revoked_pass_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/timed_entry_fee_depends_on_pass_status

        PRD §3.3: "If pass_id references a pass not owned by the
        requesting visitor or whose status is not ACTIVE at
        entry_date_local, the request is rejected with
        ERR_PASS_INVALID."
        """
        park = create_park()
        v = create_visitor_with_wallet(wallet_cents=10_000)
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

    def test_timed_entry_without_pass_succeeds_after_revoke(self, api):
        """# difficulty: cross_entity_state_dependency/timed_entry_fee_depends_on_pass_status

        PRD §3.3: "otherwise it is the park's standard entry fee."

        Claim: the same request, with pass_id omitted, succeeds — the
        gate is the sibling pass's status, not the request itself.
        """
        park = create_park()
        v = create_visitor_with_wallet(wallet_cents=10_000)
        pass_ = issue_pass(v["id"])
        revoke_pass(v["id"], pass_["id"])
        # Without pass_id the request must succeed.
        resp = api.create_timed_entry(
            park["id"],
            create_timed_entry_payload(
                entry_date_local=date_to_local_str(
                    date.today() + timedelta(days=5),
                ),
                window_start_local="09:00",
            ),
            make_visitor_headers(v["id"]),
        )
        assert resp.status_code == 201


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_backcountry_buffer_collision_15min_under_30min_buffer(self, api):
        """# difficulty: resource_temporal_overlap/backcountry_buffer_expanded_open_intervals

        PRD §3.7: "a new permit [a, b) collides with an existing [c, d)
        exactly when a is strictly less than d plus buffer and c is
        strictly less than b plus buffer."

        Claim: gap of 15 minutes against a 30-minute ranger buffer is
        a collision → ERR_RANGER_BUFFER_VIOLATION.
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

    def test_backcountry_buffer_equal_gap_passes(self, api):
        """# difficulty: resource_temporal_overlap/backcountry_buffer_expanded_open_intervals

        PRD §3.7: "equality at b equal to c passes the test exactly
        when the gap between them is at least buffer."

        Claim: gap of exactly 30 minutes against a 30-minute buffer is
        NOT a collision; confirm succeeds.
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

    def test_campground_inventory_overlap_blocks_shared_night(self, api):
        """# difficulty: resource_temporal_overlap/campground_aggregate_inventory_closed_half_open

        PRD §3.4: "The campground must have site_kind inventory
        available across the entire date range; otherwise the request
        is rejected with ERR_CAMPGROUND_FULL."

        Claim: with standard_site_count=1 and an existing reservation
        for 06-01 → 06-03, a new request for 06-02 → 06-03 (overlapping
        the night of 06-02) is rejected → ERR_CAMPGROUND_FULL.
        """
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=2,
            nightly_standard_fee_cents=3500, nightly_group_fee_cents=12000,
        )
        v1 = create_visitor_with_wallet(wallet_cents=20_000)
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        ci_dt = date.today() + timedelta(days=30)
        r1 = create_campground_reservation(
            c["id"], v1,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(ci_dt),
            check_out_date_local=date_to_local_str(
                ci_dt + timedelta(days=2),
            ),
        )
        confirm_campground_reservation(c["id"], r1["id"], v1)
        # Overlapping night (06-02 covered by r1 since [06-01, 06-03)).
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=date_to_local_str(
                    ci_dt + timedelta(days=1),
                ),
                check_out_date_local=date_to_local_str(
                    ci_dt + timedelta(days=2),
                ),
            ),
            make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAMPGROUND_FULL.value)

    def test_campground_inventory_check_out_edge_open(self, api):
        """# difficulty: resource_temporal_overlap/campground_aggregate_inventory_closed_half_open

        PRD §3.4: "the system releases site occupancy for the
        [check_in_date_local, check_out_date_local) range".

        Claim: a request whose check_in equals a prior reservation's
        check_out succeeds — check_out is the open boundary of the
        half-open interval, so the night is free.
        """
        park, c = setup_park_with_campground(
            standard_site_count=1, group_site_count=2,
            nightly_standard_fee_cents=3500, nightly_group_fee_cents=12000,
        )
        v1 = create_visitor_with_wallet(wallet_cents=20_000)
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        ci_dt = date.today() + timedelta(days=30)
        r1 = create_campground_reservation(
            c["id"], v1,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(ci_dt),
            check_out_date_local=date_to_local_str(
                ci_dt + timedelta(days=2),
            ),
        )
        confirm_campground_reservation(c["id"], r1["id"], v1)
        # New reservation 06-03 -> 06-04: shares zero nights with r1's
        # [06-01, 06-03) — must succeed.
        resp = api.create_campground_reservation(
            c["id"],
            create_campground_reservation_payload(
                site_kind="STANDARD", party_size=2,
                check_in_date_local=date_to_local_str(
                    ci_dt + timedelta(days=2),
                ),
                check_out_date_local=date_to_local_str(
                    ci_dt + timedelta(days=3),
                ),
            ),
            make_visitor_headers(v2["id"]),
        )
        assert resp.status_code == 201, (
            f"check-out-edge boundary must allow back-to-back booking; "
            f"got {resp.status_code}: {resp.text}"
        )


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_wallet_invariant_after_confirm_then_full_refund(self, api):
        """# difficulty: compensating_invariant/wallet_invariant_after_full_refund

        PRD §3.4: "On success the reservation transitions from HELD to
        CONFIRMED, the wallet is debited by total_fee_cents, and a
        LedgerEntry of kind FEE_CHARGE is appended."

        PRD §3.4: "When hours to check-in is at least 336 (fourteen
        days), the refund is total_fee_cents minus the 800-cent
        booking fee, so the visitor forfeits only the booking fee."

        PRD §2.9: "Visitor.wallet_balance_cents is the running sum of
        all amount_cents values for that visitor."

        Claim: initial_wallet 12000 - total 8424 + refund 7624 = 11200.
        The only retained quantity is the 800-cent booking fee.
        """
        park, c = setup_park_with_campground(
            standard_site_count=5, group_site_count=2,
            nightly_standard_fee_cents=3500, nightly_group_fee_cents=12000,
        )
        v = create_visitor_with_wallet(wallet_cents=12000)
        ci_dt = date.today() + timedelta(days=30)
        r_held = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(ci_dt),
            check_out_date_local=date_to_local_str(
                ci_dt + timedelta(days=2),
            ),
        )
        r = confirm_campground_reservation(c["id"], r_held["id"], v)
        assert r["total_fee_cents"] == 8424
        cancel_campground_reservation(c["id"], r["id"], v)
        v_after = get_visitor(v["id"])
        assert v_after["wallet_balance_cents"] == 11_200, (
            f"PRD §2.9/§3.4: 12000 - 8424 (confirm) + 7624 (refund) = "
            f"11200; got {v_after['wallet_balance_cents']}"
        )
        # PRD §2.9 invariant: sum of ledger == wallet.
        ledger = list_visitor_ledger(v["id"])
        total = sum(int(e["amount_cents"]) for e in ledger)
        assert total == 11_200, (
            f"ledger sum must equal wallet balance; got ledger={total}, "
            f"wallet={v_after['wallet_balance_cents']}"
        )

    def test_wallet_invariant_specific_ledger_entries(self, api):
        """# difficulty: compensating_invariant/wallet_invariant_after_full_refund

        PRD §2.9 lists the exact LedgerEntry kinds for confirm + cancel.

        Claim: after confirm + cancel of a STANDARD reservation at
        >=336h, exactly one FEE_CHARGE of -8424 and one FEE_REFUND of
        +7624 exist for that reservation, summing to -800 (the booking
        fee retained).
        """
        park, c = setup_park_with_campground(
            standard_site_count=5, group_site_count=2,
            nightly_standard_fee_cents=3500, nightly_group_fee_cents=12000,
        )
        v = create_visitor_with_wallet(wallet_cents=12000)
        ci_dt = date.today() + timedelta(days=30)
        r_held = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(ci_dt),
            check_out_date_local=date_to_local_str(
                ci_dt + timedelta(days=2),
            ),
        )
        r = confirm_campground_reservation(c["id"], r_held["id"], v)
        cancel_campground_reservation(c["id"], r["id"], v)
        ledger = list_visitor_ledger(v["id"])
        related = [
            e for e in ledger
            if e.get("reference_id") == r["id"]
            and e["kind"] in {"FEE_CHARGE", "FEE_REFUND"}
        ]
        charges = [e for e in related if e["kind"] == "FEE_CHARGE"]
        refunds = [e for e in related if e["kind"] == "FEE_REFUND"]
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == -8424
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == 7624
        # Sum over these entries == -800 (booking fee retained).
        assert sum(e["amount_cents"] for e in related) == -800

    def test_backcountry_zone_usage_returns_after_cancel(self, api):
        """# difficulty: compensating_invariant/backcountry_zone_quota_invariant_after_cancel

        PRD §3.7: "On success the wallet is debited by fee_cents via a
        LedgerEntry of kind FEE_CHARGE, and zone usage is incremented
        by party_size for each overnight night the permit occupies."

        PRD §3.7: "on success the permit transitions from CONFIRMED to
        CANCELLED, the refund is computed per the backcountry tiered-
        refund rule below and credited via a LedgerEntry of kind
        FEE_REFUND, and zone usage is decremented by party_size for
        each released night."

        Claim: after confirm + cancel, the zone's per-night usage is
        restored — a subsequent permit equal to the zone's full
        nightly_quota_people on the same nights succeeds.
        """
        base = utcnow() + timedelta(days=10)
        a_entry = base.replace(hour=14, minute=0, second=0, microsecond=0)
        a_exit = a_entry + timedelta(days=2)
        park, z, v1, r1 = setup_confirmed_backcountry_with_window(
            a_entry, a_exit, party_size=5,
            zone_overrides={
                "ranger_buffer_minutes": 30,
                # quota=15: pre-cancel residual=5; post-cancel new
                # party=15 leaves no headroom unless usage returns to 0.
                "nightly_quota_people": 15,
                "per_party_fee_cents": 1500,
            },
        )
        cancel_backcountry_permit(z["id"], r1["id"], v1)
        # Now another visitor can take party_size up to the permit cap
        # (PRD §3.7 caps individual permit party_size at 15) on the same
        # nights — confirming that usage returned to 0 (otherwise zone
        # would still show 5 used + 15 new = 20 which is at quota, but
        # before the fix it would be 5 + 15 = 20 > 20 if not refunded).
        # Using party_size=15 lets the test detect any failed
        # decrement: pre-cancel residual 5 + new 15 = 20, equal to
        # quota — the new permit would just barely fit. To force the
        # invariant to fail when usage isn't returned, we also create
        # a separate buffer-safe earlier confirmed permit; or simpler,
        # we use party_size=15 with quota=15 to make the test sharp.
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        b_entry = a_entry + timedelta(hours=1)  # different trailhead time
        b_exit = a_exit + timedelta(hours=1)
        held = create_backcountry_permit(
            z["id"], v2,
            party_size=15,
            entry_datetime_local=iso_utc(b_entry),
            exit_datetime_local=iso_utc(b_exit),
        )
        confirmed = confirm_backcountry_permit(z["id"], held["id"], v2)
        assert confirmed["status"] == "CONFIRMED"

    def test_backcountry_cancel_writes_compensating_ledger(self, api):
        """# difficulty: compensating_invariant/backcountry_zone_quota_invariant_after_cancel

        PRD §3.7: "the refund is computed per the backcountry tiered-
        refund rule below and credited via a LedgerEntry of kind
        FEE_REFUND".

        Claim: a CONFIRMED→CANCELLED at >=168h credits a FEE_REFUND
        of fee_cents (full refund branch). The wallet's net change
        from confirm + cancel is zero.
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
        wallet_before = get_visitor(v["id"])["wallet_balance_cents"]
        cancel_backcountry_permit(z["id"], r["id"], v)
        wallet_after = get_visitor(v["id"])["wallet_balance_cents"]
        # Full refund: net change must be zero.
        assert wallet_after == wallet_before + r["fee_cents"], (
            f"backcountry full refund must restore wallet to pre-confirm "
            f"value; before={wallet_before}, after={wallet_after}, "
            f"fee_cents={r['fee_cents']}"
        )
