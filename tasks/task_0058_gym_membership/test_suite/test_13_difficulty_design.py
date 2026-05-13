"""Difficulty-design instances (mandatory priority queue).

Each difficulty-design instance is covered by at least TWO dedicated
tests tagged with `# difficulty: <rule_id>/<instance.name>`. The
docstring of every test carries a PRD citation for the underlying
rule (PRD prose, not the difficulty-design entry itself).
"""
from __future__ import annotations
import pytest
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    PA, SO,
    advance_clock,
    create_funded_member,
    create_group_booking,
    create_group_class,
    create_pt_booking,
    create_pt_package,
    create_trainer,
    create_trainer_slot,
    cancel_group_booking,
    find_audit_entries,
    find_commission_rows,
    find_wallet_txn,
    freeze_card,
    get_card,
    get_member,
    iso_z, parse_iso,
    list_audit_log,
    list_trainer_commissions,
    list_wallet_transactions,
    make_member_headers,
    make_trainer_headers,
    recharge_member,
    reset_clock_to,
    round_half_up,
    setup_annual_card_at_remaining_days,
    setup_card_currently_frozen_with_settled_history,
    setup_card_for_auto_renew_chain,
    setup_group_class_with_waitlist,
    setup_inactive_trainer_with_published_slot,
    setup_monthly_card_for_refund_eligibility,
    setup_package_with_partial_consumption_simple,
    setup_pt_booking_past_starts_with_zero_balance,
    setup_two_trainers_bronze_and_gold,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    # difficulty: dual_variant_calc/card_remaining_value_dual_variant
    def test_refund_preview_exposes_both_variants(self, api):
        """PRD §3.6: 'The refund-preview capability surfaces both the
        forward-looking remaining value (which the actual refund will
        use) and a parallel chronological variant. The chronological
        variant ... walks day-by-day from the current instant to
        effective_expiry_date, accumulating Card.issuance_price_cents
        divided by CardType.validity_days per day, rounding each
        per-day amount half-up to the nearest cent before summing.'

        ANNUAL 120000/365 over 100 remaining days:
          forward_looking = round_half_up(120000*100/365) = 32877
          chronological  = round_half_up(120000/365) * 100 = 329 * 100
                          = 32900
        """
        _, _, card = setup_annual_card_at_remaining_days(
            remaining_days=100,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            max_freeze_days=0,
        )
        data = validate_success(
            api.get_refund_preview(card["id"], SO),
            expected_status=200,
        )
        assert data.get("forward_looking_remaining_value_cents") == 32_877
        assert data.get("chronological_remaining_value_cents") == 32_900

    # difficulty: dual_variant_calc/card_remaining_value_dual_variant
    def test_actual_refund_uses_forward_looking(self, api):
        """PRD §3.6: 'On refund, the system computes the remaining
        value via the forward-looking formula.' and 'this variant is
        for preview only and never drives the actual refund.'

        After actual refund, ledger REFUND row equals 32877 (NOT 32900).
        """
        _, member, card = setup_annual_card_at_remaining_days(
            remaining_days=100,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            max_freeze_days=0,
        )
        validate_success(
            api.refund_card(card["id"], SO),
            expected_status=200,
        )
        rows = list_wallet_transactions(
            member["id"], headers=make_member_headers(member["id"]),
        )
        refund_rows = find_wallet_txn(
            rows, kind="REFUND", bucket="PRINCIPAL",
            ref_startswith=f"Card:{card['id']}",
        )
        assert len(refund_rows) == 1
        assert refund_rows[0]["amount_cents"] == 32_877, (
            "PRD §3.6 the actual refund credits the forward_looking "
            "remaining value (32877), not the chronological variant "
            "(32900)."
        )
        # And the card is REFUNDED.
        assert get_card(card["id"])["status"] == "REFUNDED"

    # difficulty: dual_variant_calc/trainer_session_commission_tier_modifier_variant
    @pytest.mark.timeout(600)
    def test_gold_trainer_session_commission_uplift(self, api):
        """PRD §3.8: 'A CommissionRecord of kind=SESSION is appended
        whose amount_cents is session_price_cents multiplied by the
        trainer's effective rate divided by 10,000, rounded half-up.
        The effective rate is Trainer.session_commission_pct_bp plus a
        tier modifier: 0 basis points when the trainer is BRONZE, 500
        when SILVER (a five-percentage-point uplift), and 1000 when
        GOLD (a ten-percentage-point uplift). The tier modifier is
        applied at session-complete time, not deferred to payout
        close.'

        Two trainers, both session_commission_pct_bp=1500. Same
        session_price 20000. Bronze commission = 3000; Gold = 5000.
        """
        bronze, gold = setup_two_trainers_bronze_and_gold()
        assert bronze["tier"] == "BRONZE"
        assert gold["tier"] == "GOLD"

        # Book + complete one session per trainer at session_price=20000.
        # We supply an explicit slot start after the existing cycle
        # because the gold trainer's setup booked through 2026-04-01;
        # use 2026-04-05.
        advance_clock("2026-04-05T00:00:00.000Z")

        def book_and_complete(trainer: dict, hour_offset: int) -> dict:
            s = parse_iso("2026-04-05T10:00:00.000Z") + timedelta(
                hours=hour_offset,
            )
            e = s + timedelta(hours=1)
            slot = create_trainer_slot(
                trainer_id=trainer["id"],
                starts_at=iso_z(s), ends_at=iso_z(e),
            )
            m = create_funded_member(wallet_balance_cents=100_000)
            booking = create_pt_booking(
                member=m, slot=slot, billing_mode="SINGLE",
            )
            advance_clock(iso_z(s + timedelta(minutes=5)))
            from test_helpers import complete_pt_booking
            completed = complete_pt_booking(booking["id"], trainer["id"])
            return completed

        booking_b = book_and_complete(bronze, 0)
        booking_g = book_and_complete(gold, 2)

        # Read session commissions for each.
        bronze_commissions = find_commission_rows(
            list_trainer_commissions(bronze["id"]),
            kind="SESSION",
            ref_startswith=f"PTBooking:{booking_b['id']}",
        )
        gold_commissions = find_commission_rows(
            list_trainer_commissions(gold["id"]),
            kind="SESSION",
            ref_startswith=f"PTBooking:{booking_g['id']}",
        )
        assert len(bronze_commissions) == 1
        assert len(gold_commissions) == 1

        # Bronze: round_half_up(price * 1500 / 10000)
        # Gold: round_half_up(price * 2500 / 10000) — +1000 bp uplift.
        bronze_price = booking_b["session_price_cents"]
        gold_price = booking_g["session_price_cents"]
        assert bronze_commissions[0]["amount_cents"] == round_half_up(
            bronze_price * 1_500 / 10_000,
        )
        assert gold_commissions[0]["amount_cents"] == round_half_up(
            gold_price * (1_500 + 1_000) / 10_000,
        )

    # difficulty: dual_variant_calc/trainer_session_commission_tier_modifier_variant
    @pytest.mark.timeout(600)
    def test_default_trainer_tier_bronze_zero_modifier(self, api):
        """PRD §3.8: 'The effective rate is
        Trainer.session_commission_pct_bp plus a tier modifier: 0
        basis points when the trainer is BRONZE.'

        A brand-new trainer starts at BRONZE (PRD §3.8: 'BRONZE as the
        default'). Their session commission is computed with zero
        modifier — i.e., effective rate equals base rate.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(
            specialties=["STRENGTH"],
            session_commission_pct_bp=1_500,
        )
        assert trainer["tier"] == "BRONZE", (
            "PRD §3.8: 'BRONZE as the default.'"
        )
        s = parse_iso("2026-01-02T10:00:00.000Z")
        e = s + timedelta(hours=1)
        slot = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at=iso_z(s), ends_at=iso_z(e),
        )
        m = create_funded_member(wallet_balance_cents=100_000)
        booking = create_pt_booking(
            member=m, slot=slot, billing_mode="SINGLE",
        )
        advance_clock(iso_z(s + timedelta(minutes=5)))
        from test_helpers import complete_pt_booking
        completed = complete_pt_booking(booking["id"], trainer["id"])
        commissions = find_commission_rows(
            list_trainer_commissions(trainer["id"]),
            kind="SESSION",
            ref_startswith=f"PTBooking:{booking['id']}",
        )
        assert len(commissions) == 1
        expected = round_half_up(
            completed["session_price_cents"] * 1_500 / 10_000,
        )
        assert commissions[0]["amount_cents"] == expected


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    # difficulty: combinatorial_formula/recharge_bonus_tiered_rate_nested_min
    def test_25k_recharge_bonus_5_percent_tier(self, api):
        """PRD §3.3: 'amounts of at least 20,000 cents earn a 5%
        bonus.' and 'The bonus amount in cents equals the requested
        amount multiplied by the tier's basis-point rate divided by
        10,000, with the result truncated toward zero.'

        25_000 * 500 / 10_000 = 1250 (exact).
        """
        m = create_funded_member(wallet_balance_cents=0)
        recharge_member(m["id"], 25_000)
        after = get_member(m["id"])
        assert after["wallet_balance_cents"] == 26_250, (
            "PRD §3.3: 25k recharge → 25000 principal + 1250 bonus "
            "= 26250 total wallet projection."
        )
        assert after["bonus_balance_cents"] == 1_250

    # difficulty: combinatorial_formula/recharge_bonus_tiered_rate_nested_min
    def test_50k_recharge_bonus_jumps_tier(self, api):
        """PRD §3.3: 'amounts of at least 50,000 cents earn a 10%
        bonus.'

        Sequencing of two recharges: 25k then 50k. After first:
        bonus=1250, principal=25000. After second: bonus += 5000 →
        6250; principal += 50000 → 75000. Total wallet = 81_250.
        """
        m = create_funded_member(wallet_balance_cents=0)
        recharge_member(m["id"], 25_000)
        recharge_member(m["id"], 50_000)
        after = get_member(m["id"])
        assert after["bonus_balance_cents"] == 6_250
        assert after["wallet_balance_cents"] == 81_250

    # difficulty: combinatorial_formula/transfer_fee_round_order_pinned
    def test_transfer_fee_pinned_round_order(self, api):
        """PRD §3.6: 'When the transfer proceeds, the system first
        computes remaining_value_cents using the forward-looking
        formula above. It then computes transfer_fee_cents by
        multiplying that remaining value by
        CardType.transfer_fee_pct_bp and dividing by 10,000, rounding
        half-up at this step, and finally taking the maximum of that
        result and 2,000 cents — that floor is the minimum transfer
        fee.'

        ANNUAL 120000/365, 100 days remaining → forward_looking =
        32877. transfer_fee_pct_bp = 1000 →
        round_half_up(32877 * 1000 / 10000) = round_half_up(3287.7) =
        3288. Max(3288, 2000) = 3288.
        """
        ct, holder, card = setup_annual_card_at_remaining_days(
            remaining_days=100,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            transfer_fee_pct_bp=1_000,
            max_freeze_days=0,
            family_group_id="FAM_TRANSFER",
        )
        dest = create_funded_member(
            wallet_balance_cents=10_000,
            family_group_id="FAM_TRANSFER",
        )
        record = validate_success(
            api.transfer_card(
                card["id"], {"to_member_id": dest["id"]}, SO,
            ),
            expected_status=200,
        )
        assert record["remaining_value_cents"] == 32_877
        assert record["transfer_fee_cents"] == 3_288, (
            "PRD §3.6 pinned order: round_half_up(remaining_value * bp / "
            "10000); round_half_up(32877 * 1000 / 10000) == 3288."
        )

    # difficulty: combinatorial_formula/transfer_fee_round_order_pinned
    def test_transfer_fee_walletdebit_records_principal(self, api):
        """PRD §3.6: 'The wallet is debited for the transfer fee as a
        WalletTransaction with kind=DEBIT, bucket=PRINCIPAL,
        service_type=TRANSFER_FEE, and ref_entity pointing at the
        card.'"""
        ct, holder, card = setup_annual_card_at_remaining_days(
            remaining_days=100,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            transfer_fee_pct_bp=1_000,
            max_freeze_days=0,
            family_group_id="FAM_TRANSFER2",
        )
        dest = create_funded_member(
            wallet_balance_cents=10_000,
            family_group_id="FAM_TRANSFER2",
        )
        validate_success(
            api.transfer_card(
                card["id"], {"to_member_id": dest["id"]}, SO,
            ),
            expected_status=200,
        )
        rows = list_wallet_transactions(
            holder["id"], headers=make_member_headers(holder["id"]),
        )
        debits = find_wallet_txn(
            rows, kind="DEBIT", bucket="PRINCIPAL",
            service_type="TRANSFER_FEE",
            ref_startswith=f"Card:{card['id']}",
        )
        assert len(debits) == 1
        assert debits[0]["amount_cents"] == -3_288, (
            "PRD §3.6 debit amount is the (signed-negative) computed "
            "fee."
        )

    # difficulty: combinatorial_formula/renewal_quote_circular_dependency_evaluation_order
    def test_renewal_quote_uses_effective_expiry_with_approved_freeze(self, api):
        """PRD §3.5: 'APPROVED episodes contribute their current
        actual_days so an in-progress freeze pushes the effective
        expiry out immediately.'

        PRD §3.7: 'The system measures the number of whole days
        between the current instant and effective_expiry_date.'

        Monthly card validity 30 days; activate at t0; advance to
        t0+19 (so 10 days remain in original). Start a 5-day freeze
        → APPROVED → effective_expiry pushed to t0+30+5 = t0+35.
        From t0+19 to t0+35 is 16 days, which sits in the [7,30]
        band → discount = base 1500 bp → 30000*8500/10000 = 25500.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=11,        # advance 19 days post-activation
            refund_eligibility_days=0,
            validity_days=30,
            price_cents=30_000,
        )
        # The helper used create_monthly_card_type defaulting
        # renewal_discount_pct_bp=1500 and max_freeze_days=0. Override:
        # we need a card with max_freeze_days > 0. So instead set up
        # custom.
        # Replace with a custom setup:
        from test_helpers import (
            create_card_type, create_funded_member,
            issue_and_activate_card,
        )
        reset_clock_to("2026-01-01T00:00:00.000Z")
        ct = create_card_type(
            category="MONTHLY",
            price_cents=30_000,
            validity_days=30,
            visit_quota=0,
            max_freeze_days=10,
            transfer_fee_pct_bp=1_000,
            renewal_discount_pct_bp=1_500,
            refund_eligibility_days=0,
        )
        m = create_funded_member(wallet_balance_cents=100_000)
        card = issue_and_activate_card(card_type=ct, member=m)
        # Advance to t0+19 days (11 days remain in original).
        advance_clock("2026-01-20T00:00:00.000Z")
        # Now freeze 5 days → APPROVED. effective_expiry pushes out 5.
        freeze_card(card["id"], requested_days=5)
        # days_to_expiry from 2026-01-20 to 2026-02-04 (end-of-day) =
        # 15 days. PRD §3.7 inside [7,30] → discount = 1500 bp →
        # renewal_price = round_half_up(30000 * 8500 / 10000) = 25500.
        data = validate_success(
            api.get_renewal_quote(card["id"], SO),
            expected_status=200,
        )
        assert data.get("renewal_price_cents") == 25_500, (
            "PRD §3.7: in [7,30] window discount equals "
            "renewal_discount_pct_bp; effective_expiry accounts for "
            "the in-progress APPROVED freeze."
        )

    # difficulty: combinatorial_formula/renewal_quote_circular_dependency_evaluation_order
    def test_renewal_quote_no_discount_far_from_expiry(self, api):
        """PRD §3.7: 'When that value is greater than 30, no discount
        applies and the quote equals CardType.price_cents.'

        Without any freeze, an annual card 200 days from expiry pays
        full price.
        """
        _, _, card = setup_annual_card_at_remaining_days(
            remaining_days=200,
            price_cents=100_000,
        )
        data = validate_success(
            api.get_renewal_quote(card["id"], SO),
            expected_status=200,
        )
        assert data.get("renewal_price_cents") == 100_000


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    # difficulty: non_linear_state_machine/card_branching_cycle_freeze_unfreeze
    def test_card_cycles_active_frozen_active_frozen(self, api):
        """PRD §3.5: 'Two paths end a freeze.  When the clock crosses
        ends_at, the system settles the episode (APPROVED → SETTLED)
        and brings the card back from FROZEN to ACTIVE.' and 'When a
        member or operator invokes the early-unfreeze capability
        before ends_at ..., the episode transitions APPROVED →
        CANCELED ... the card transitions back to ACTIVE.'"""
        _, _, card = setup_annual_card_at_remaining_days(
            remaining_days=300,
            refund_eligibility_days=0,
            max_freeze_days=14,
        )
        # Cycle hop 1: ACTIVE → FROZEN.
        ep1 = freeze_card(card["id"], requested_days=5)
        assert get_card(card["id"])["status"] == "FROZEN"
        # Advance past ep1.ends_at: FROZEN → ACTIVE (settle).
        advance_clock(
            iso_z(parse_iso(ep1["ends_at"]) + timedelta(minutes=1)),
        )
        assert get_card(card["id"])["status"] == "ACTIVE"
        # Cycle hop 3: ACTIVE → FROZEN again.
        ep2 = freeze_card(card["id"], requested_days=4)
        assert get_card(card["id"])["status"] == "FROZEN"
        # Cycle hop 4: unfreeze early → APPROVED → CANCELED; FROZEN →
        # ACTIVE.
        from test_helpers import unfreeze_card
        unfreeze_card(card["id"], ep2["id"])
        assert get_card(card["id"])["status"] == "ACTIVE"

    # difficulty: non_linear_state_machine/card_branching_cycle_freeze_unfreeze
    def test_cumulative_freeze_days_tracks_settled_only(self, api):
        """PRD §3.2 Card.cumulative_freeze_days field description (in
        scaffold form) AND PRD §3.5: 'its cumulative_freeze_days rises
        by the episode's actual_days' on approval cascade.

        After one freeze of 5 days that fully settles plus a second
        4-day freeze in progress, the cumulative count is at least 5
        (the SETTLED actual_days). PRD prose treats
        cumulative_freeze_days as the freeze-budget counter consulted
        on freeze requests; here we observe its monotonic rise.
        """
        _, _, card = setup_annual_card_at_remaining_days(
            remaining_days=300,
            refund_eligibility_days=0,
            max_freeze_days=14,
        )
        initial = get_card(card["id"])["cumulative_freeze_days"]
        ep1 = freeze_card(card["id"], requested_days=5)
        after_freeze_1 = get_card(card["id"])["cumulative_freeze_days"]
        assert after_freeze_1 == initial + 5, (
            "PRD §3.5: cumulative_freeze_days rises by actual_days on "
            "freeze approval."
        )
        advance_clock(
            iso_z(parse_iso(ep1["ends_at"]) + timedelta(minutes=1)),
        )
        # After settle the count remains at least 5.
        after_settle = get_card(card["id"])["cumulative_freeze_days"]
        assert after_settle >= 5

    # difficulty: non_linear_state_machine/group_booking_branching_with_waitlist_promotion
    def test_cancel_promotes_waitlist_head_to_confirmed(self, api):
        """PRD §3.9: 'On successful cancellation, confirmed_count
        decreases by one and the head of the waitlist (the row with
        the lowest waitlist_position) is promoted: that row
        transitions WAITLISTED → CONFIRMED, its waitlist_position is
        set to null, every later waitlist row has its
        waitlist_position decremented by one, and an IM PROMOTED
        notification is emitted.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-05T10:00:00.000Z",
            ends_at="2026-01-05T11:00:00.000Z",
            capacity=1, deduction_cents=0,
        )
        m1 = create_funded_member(wallet_balance_cents=50_000)
        m2 = create_funded_member(wallet_balance_cents=50_000)
        b1 = create_group_booking(class_id=klass["id"], member=m1)
        b2 = create_group_booking(
            class_id=klass["id"], member=m2, accept_waitlist=True,
        )
        assert b1["status"] == "CONFIRMED"
        assert b2["status"] == "WAITLISTED"

        # Cancel m1's confirmed booking → promotion side effect.
        validate_success(
            api.cancel_group_booking(
                b1["id"], make_member_headers(m1["id"]),
            ),
            expected_status=200,
        )
        # PRD §3.9: GroupClass.confirmed_count = 1 after promotion (m2
        # promoted to CONFIRMED).  Read class via subsequent
        # patch-version cycle: PRD §4 has no GET /group-classes/{id}
        # listed, but PATCH returns the updated row, and we can
        # observe confirmed_count there.  We use PATCH with a no-op
        # capacity bump (capacity stays as-is); but PATCH requires a
        # non-empty body of capacity? or substitute_trainer_id? — we
        # set capacity=current capacity which is a valid no-op.
        # Better: read the audit log? The promotion is an internal
        # cascade and may not be in audit.  We rely on observability
        # via creating a third member who tries to book with
        # accept_waitlist=False — if there is still a free seat, they
        # should be CONFIRMED; if not, they would land WAITLISTED.
        m3 = create_funded_member(wallet_balance_cents=50_000)
        # capacity 1, m2 was promoted to CONFIRMED → no free seat;
        # m3 with accept_waitlist=False must hit ERR_CAPACITY_REACHED.
        res = api.create_group_booking(
            {"class_id": klass["id"], "member_id": m3["id"],
             "accept_waitlist": False},
            make_member_headers(m3["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CAPACITY_REACHED.value)

    # difficulty: non_linear_state_machine/group_booking_branching_with_waitlist_promotion
    def test_empty_waitlist_cancel_no_promotion(self, api):
        """PRD §3.9: 'On successful cancellation, confirmed_count
        decreases by one and the head of the waitlist (the row with
        the lowest waitlist_position) is promoted.'

        When the waitlist is empty there is no head to promote — the
        cancel must succeed (no crash) and the next booking attempt
        must land in CONFIRMED.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-05T10:00:00.000Z",
            ends_at="2026-01-05T11:00:00.000Z",
            capacity=2, deduction_cents=0,
        )
        m1 = create_funded_member(wallet_balance_cents=50_000)
        b1 = create_group_booking(class_id=klass["id"], member=m1)
        validate_success(
            api.cancel_group_booking(
                b1["id"], make_member_headers(m1["id"]),
            ),
            expected_status=200,
        )
        # Now a fresh booking must succeed in CONFIRMED status (capacity
        # has 2 free seats again).
        m2 = create_funded_member(wallet_balance_cents=50_000)
        b2 = create_group_booking(class_id=klass["id"], member=m2)
        assert b2["status"] == "CONFIRMED"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    # difficulty: transitive_cascade/package_refund_to_commission_to_audit_chain
    def test_package_refund_writes_reversal_commission(self, api):
        """PRD §3.8: 'On refund the wallet receives a credit equal to
        ...  the package-sale commission is reversed proportionally:
        the system locates the original PACKAGE_SALE CommissionRecord
        for the package, computes the unconsumed-sessions count, and
        appends a CommissionRecord of kind=REVERSAL whose amount_cents
        equals the negative of the original commission multiplied by
        unconsumed sessions divided by total_sessions, rounded
        half-up.'

        gross 100000, total 7, consumed 3, pkg_bp 800 →
        original sale = round_half_up(100000*800/10000) = 8000.
        unconsumed = 4. Reversal = -round_half_up(8000*4/7) = -4571.
        """
        trainer, member, package, obs = (
            setup_package_with_partial_consumption_simple(
                total_sessions=7,
                sessions_to_complete=3,
                gross_price_cents=100_000,
                package_commission_pct_bp=800,
            )
        )
        # Trigger refund.
        refunded = validate_success(
            api.refund_pt_package(package["id"], SO),
            expected_status=200,
        )
        assert refunded["status"] == "REFUNDED"

        # New CommissionRecord kind=REVERSAL on this package.
        commissions = list_trainer_commissions(trainer["id"])
        rev_rows = find_commission_rows(
            commissions, kind="REVERSAL",
            ref_startswith=f"PTPackage:{package['id']}",
        )
        assert len(rev_rows) == 1, (
            f"PRD §3.8 expects one REVERSAL row pointing at the package; "
            f"got {rev_rows!r}"
        )
        assert rev_rows[0]["amount_cents"] == -4_571, (
            "PRD §3.8: reversal amount = -round_half_up(8000*4/7) = "
            "-4571."
        )

    # difficulty: transitive_cascade/package_refund_to_commission_to_audit_chain
    def test_package_refund_writes_audit_log(self, api):
        """PRD §3.8: 'an AuditLogEntry with action=COMMISSION_REVERSAL
        is written.'"""
        trainer, member, package, _ = (
            setup_package_with_partial_consumption_simple(
                total_sessions=7,
                sessions_to_complete=3,
                gross_price_cents=100_000,
                package_commission_pct_bp=800,
            )
        )
        validate_success(
            api.refund_pt_package(package["id"], SO),
            expected_status=200,
        )
        # Audit log should contain an entry with action ==
        # COMMISSION_REVERSAL targeted at the package.
        entries = list_audit_log(action="COMMISSION_REVERSAL")
        targeted = [
            e for e in entries
            if (e.get("target_entity") or "").startswith(
                f"PTPackage:{package['id']}",
            )
        ]
        assert len(targeted) >= 1, (
            f"PRD §3.8 expects an AuditLogEntry action="
            f"COMMISSION_REVERSAL targeted at the package; got "
            f"{entries!r}"
        )

    # difficulty: transitive_cascade/clock_advance_to_card_expiry_to_autorenew_chain
    def test_clock_advance_expires_card_when_no_auto_renew(self, api):
        """PRD §3.2: 'A card naturally expires when the clock crosses
        its effective_expiry_date.' and 'When auto-renewal does not
        fire, a RenewalReminder is recorded with tier=T0 and
        status=LAPSED.'

        Member without auto_renew_authorized → after expiry clock
        cross, original card is EXPIRED.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        from test_helpers import (
            create_monthly_card_type, create_funded_member,
            issue_and_activate_card,
        )
        ct = create_monthly_card_type(
            price_cents=30_000, validity_days=30,
            renewal_discount_pct_bp=0,
            refund_eligibility_days=0,
            max_freeze_days=0,
        )
        m = create_funded_member(
            wallet_balance_cents=60_000,
            auto_renew_authorized=False,
        )
        card = issue_and_activate_card(card_type=ct, member=m)
        # Advance past effective_expiry_date (end of day on day 30).
        advance_clock("2026-02-01T00:00:00.000Z")
        after = get_card(card["id"])
        assert after["status"] == "EXPIRED", (
            "PRD §3.2: 'A card naturally expires when the clock "
            "crosses its effective_expiry_date.'"
        )

    # difficulty: transitive_cascade/clock_advance_to_card_expiry_to_autorenew_chain
    def test_clock_advance_auto_renew_creates_child_card(self, api):
        """PRD §3.2: 'Auto-renewal fires only when the member's
        auto_renew_authorized is true and a RenewalReminder with tier
        T0 has been dispatched: in that case the system creates a
        child Card in PENDING status with its parent_card_id set to
        the expiring card, debits the member's wallet for the renewal
        price (computed per §3.7), and activates the child card
        immediately (the same PENDING → ACTIVE cascade described
        above).'

        We dispatch the T0 reminder via /_sweep/run at the moment
        days_to_expiry == 0 (end-of-day same date), then advance the
        clock past effective_expiry to trigger expiry. The child card
        must be created in ACTIVE state with parent_card_id pointing
        at the original.
        """
        ct, member, original = setup_card_for_auto_renew_chain(
            price_cents=30_000,
            validity_days=30,
            extra_funds_cents=200_000,
        )
        # Advance clock to the day-of expiry (2026-01-31, midnight).
        # effective_expiry is end-of-day on day-30, so on 2026-01-31
        # 00:00:00 days_to_expiry rounded to whole days is 0.
        advance_clock("2026-01-31T00:00:00.000Z")
        # Dispatch T0 reminder via sweep (PRD §3.7 / §3.2).
        from test_helpers import run_sweep
        run_sweep()
        # Now cross past effective_expiry to trigger auto-renew.
        advance_clock("2026-02-01T00:00:01.000Z")
        # Original is EXPIRED.
        assert get_card(original["id"])["status"] == "EXPIRED"
        # A child card must exist for the member with parent_card_id
        # pointing at the original; list /cards filtered by holder.
        rows_resp = api.list_cards(
            PA, params={"holder_member_id": member["id"]},
        )
        from test_helpers import validate_paginated
        cards, _ = validate_paginated(rows_resp)
        child = [c for c in cards if c.get("parent_card_id") == original["id"]]
        assert len(child) == 1, (
            f"PRD §3.2 auto-renew cascade must create a child Card; "
            f"got cards={cards!r}"
        )
        assert child[0]["status"] == "ACTIVE", (
            "PRD §3.2: 'activates the child card immediately.'"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    # difficulty: priority_pair_validation_conflict/state_vs_business_referential_refund_on_frozen_card
    def test_refund_on_frozen_card_returns_invalid_state_first(self, api):
        """PRD §3.12: 'State-machine from-state checks come next, with
        ERR_INVALID_STATE for the generic mismatch ...
        ERR_REFUND_FROZEN_CARD_BLOCKED only when remaining days are
        sufficient.' and PRD §3.6: 'A card can be refunded only while
        it is in ACTIVE status (rejected with ERR_INVALID_STATE
        otherwise).'

        A card that is currently FROZEN cannot be in ACTIVE state, so
        the priority-7 state check fires first → ERR_INVALID_STATE,
        not ERR_REFUND_FROZEN_CARD_BLOCKED.
        """
        _, _, card = setup_card_currently_frozen_with_settled_history()
        assert card["status"] == "FROZEN"
        res = api.refund_card(card["id"], SO)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: priority_pair_validation_conflict/state_vs_business_referential_refund_on_frozen_card
    def test_refund_on_active_settled_history_returns_frozen_block(self, api):
        """PRD §3.6: 'The card must additionally have no FreezeEpisode
        in SETTLED status: any card that was ever frozen and settled
        is non-refundable, with rejection code
        ERR_REFUND_FROZEN_CARD_BLOCKED.'

        When the card is back in ACTIVE state (no in-progress freeze)
        but has SETTLED freeze history, the dedicated error fires.
        """
        ct, member, card = setup_annual_card_at_remaining_days(
            remaining_days=300,
            refund_eligibility_days=10,
            max_freeze_days=14,
        )
        ep = freeze_card(card["id"], requested_days=3)
        advance_clock(
            iso_z(parse_iso(ep["ends_at"]) + timedelta(minutes=1)),
        )
        assert get_card(card["id"])["status"] == "ACTIVE"
        res = api.refund_card(card["id"], SO)
        validate_error(
            res, ApiErrorId.ERR_REFUND_FROZEN_CARD_BLOCKED.value,
        )

    # difficulty: priority_pair_validation_conflict/business_constraint_vs_business_fiscal_pt_cancel_late_with_low_balance
    def test_pt_cancel_after_starts_returns_cancel_window_expired(self, api):
        """PRD §3.8: 'Attempting to cancel at or after
        scheduled_starts_at is rejected with
        ERR_CANCEL_WINDOW_EXPIRED.'

        Even when other failure conditions co-exist (e.g., the wallet
        could not cover a hypothetical refund), the cancel-window
        check fires first.
        """
        trainer, member, booking, slot = (
            setup_pt_booking_past_starts_with_zero_balance()
        )
        res = api.cancel_pt_booking(
            booking["id"], make_member_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CANCEL_WINDOW_EXPIRED.value)

    # difficulty: priority_pair_validation_conflict/business_constraint_vs_business_fiscal_pt_cancel_late_with_low_balance
    def test_pt_cancel_before_starts_succeeds(self, api):
        """PRD §3.8: 'Cancelling a CONFIRMED booking before its
        scheduled_starts_at returns the slot to OPEN.'

        Contrast: when the cancel-window guard does NOT fire, the
        cancel succeeds. This isolates the priority pair from the
        sibling test above.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        s = parse_iso("2026-01-05T10:00:00.000Z")
        e = s + timedelta(hours=1)
        slot = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at=iso_z(s), ends_at=iso_z(e),
        )
        m = create_funded_member(wallet_balance_cents=50_000)
        booking = create_pt_booking(
            member=m, slot=slot, billing_mode="SINGLE",
        )
        # Cancel while now() < starts_at — succeeds.
        res = api.cancel_pt_booking(
            booking["id"], make_member_headers(m["id"]),
        )
        validate_success(res, expected_status=200)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    # difficulty: boundary_precision_check/refund_eligibility_day_inclusive_boundary
    def test_exactly_at_eligibility_threshold_accepted(self, api):
        """PRD §3.6: 'The card's remaining validity in days ... must
        be at least CardType.refund_eligibility_days; otherwise the
        response is ERR_REFUND_NOT_ELIGIBLE.'

        Remaining == threshold (30 == 30) → accepted.
        """
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=30,
            refund_eligibility_days=30,
            validity_days=90,
            price_cents=90_000,
        )
        validate_success(api.refund_card(card["id"], SO), expected_status=200)
        assert get_card(card["id"])["status"] == "REFUNDED"

    # difficulty: boundary_precision_check/refund_eligibility_day_inclusive_boundary
    def test_one_below_eligibility_threshold_rejected(self, api):
        """PRD §3.6: '... must be at least
        CardType.refund_eligibility_days; otherwise the response is
        ERR_REFUND_NOT_ELIGIBLE.'

        Remaining == threshold - 1 (29 < 30) → rejected.
        """
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=29,
            refund_eligibility_days=30,
            validity_days=90,
            price_cents=90_000,
        )
        res = api.refund_card(card["id"], SO)
        validate_error(res, ApiErrorId.ERR_REFUND_NOT_ELIGIBLE.value)

    # difficulty: boundary_precision_check/group_class_waitlist_empty_promotion_no_op
    def test_cancel_with_empty_waitlist_does_not_raise(self, api):
        """PRD §3.9: 'On successful cancellation, confirmed_count
        decreases by one and the head of the waitlist ... is
        promoted.'

        With an empty waitlist (waitlist_count == 0) the promotion
        side effect is a no-op — the cancel must succeed without
        crashing.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-05T10:00:00.000Z",
            ends_at="2026-01-05T11:00:00.000Z",
            capacity=2, deduction_cents=0,
        )
        m1 = create_funded_member(wallet_balance_cents=50_000)
        b1 = create_group_booking(class_id=klass["id"], member=m1)
        # No m2 waitlist exists.
        validate_success(
            api.cancel_group_booking(
                b1["id"], make_member_headers(m1["id"]),
            ),
            expected_status=200,
        )

    # difficulty: boundary_precision_check/group_class_waitlist_empty_promotion_no_op
    def test_cancel_with_empty_waitlist_leaves_other_seats_open(self, api):
        """PRD §3.9: capacity-aware booking. After cancel with an
        empty waitlist, a third member booking with accept_waitlist=
        false must land CONFIRMED (no ghost promotion blocked seat).
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-05T10:00:00.000Z",
            ends_at="2026-01-05T11:00:00.000Z",
            capacity=1, deduction_cents=0,
        )
        m1 = create_funded_member(wallet_balance_cents=50_000)
        b1 = create_group_booking(class_id=klass["id"], member=m1)
        validate_success(
            api.cancel_group_booking(
                b1["id"], make_member_headers(m1["id"]),
            ),
            expected_status=200,
        )
        m2 = create_funded_member(wallet_balance_cents=50_000)
        b2 = create_group_booking(
            class_id=klass["id"], member=m2, accept_waitlist=False,
        )
        assert b2["status"] == "CONFIRMED", (
            "After empty-waitlist cancel a fresh booking must enter "
            "CONFIRMED, proving the capacity slot was actually freed."
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    # difficulty: cross_entity_state_dependency/card_freeze_blocked_by_active_pt_booking
    def test_freeze_blocked_by_confirmed_booking(self, api):
        """PRD §3.5: 'it must have no PTBooking in CONFIRMED status
        whose scheduled_starts_at falls inside the proposed freeze
        window — that cross-entity guard is rejected with
        ERR_FREEZE_CONFLICTS_WITH_BOOKING.'"""
        from test_helpers import (
            setup_card_with_confirmed_pt_booking_in_freeze_window,
        )
        _, _, card, _ = setup_card_with_confirmed_pt_booking_in_freeze_window(
            booking_offset_days=3,
        )
        res = api.freeze_card(
            card["id"], {"reason": "ILLNESS", "requested_days": 7}, SO,
        )
        validate_error(res, ApiErrorId.ERR_FREEZE_CONFLICTS_WITH_BOOKING.value)

    # difficulty: cross_entity_state_dependency/card_freeze_blocked_by_active_pt_booking
    def test_freeze_succeeds_when_booking_outside_window(self, api):
        """PRD §3.5: the cross-entity guard fires only when the
        confirmed booking's scheduled_starts_at falls within the
        proposed freeze window. When the booking is well beyond the
        window, freeze must succeed.
        """
        from test_helpers import (
            setup_card_with_confirmed_pt_booking_in_freeze_window,
        )
        _, _, card, _ = (
            setup_card_with_confirmed_pt_booking_in_freeze_window(
                booking_offset_days=30,
            )
        )
        # Freeze 7 days: booking at day 30 lies outside [now, now+7].
        ep = freeze_card(card["id"], requested_days=7)
        assert ep["status"] == "APPROVED"
        assert get_card(card["id"])["status"] == "FROZEN"

    # difficulty: cross_entity_state_dependency/pt_booking_blocked_by_inactive_trainer
    def test_booking_inactive_trainer_rejected(self, api):
        """PRD §3.8: 'Inactive trainers cannot be booked or sold
        against, with rejection code ERR_TRAINER_INACTIVE.'"""
        trainer, member, slot = (
            setup_inactive_trainer_with_published_slot()
        )
        res = api.create_pt_booking(
            {"member_id": member["id"], "slot_id": slot["id"],
             "billing_mode": "SINGLE"},
            make_member_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRAINER_INACTIVE.value)

    # difficulty: cross_entity_state_dependency/pt_booking_blocked_by_inactive_trainer
    def test_booking_active_trainer_succeeds(self, api):
        """PRD §3.8: 'Inactive trainers cannot be booked.' Negative
        baseline: an ACTIVE trainer of equivalent setup IS bookable.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        s = parse_iso("2026-01-05T10:00:00.000Z")
        e = s + timedelta(hours=1)
        slot = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at=iso_z(s), ends_at=iso_z(e),
        )
        m = create_funded_member(wallet_balance_cents=100_000)
        booking = create_pt_booking(
            member=m, slot=slot, billing_mode="SINGLE",
        )
        assert booking["status"] == "CONFIRMED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    # difficulty: resource_temporal_overlap/trainer_slot_half_open_adjacent_allowed
    def test_trainer_slot_adjacent_endpoints_allowed(self, api):
        """PRD §3.8: 'Slots that touch endpoint-to-endpoint (one
        slot's ends_at equals the next slot's starts_at) are
        explicitly allowed because the half-open semantics make them
        non-overlapping.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        a = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
        )
        # Touching endpoint.
        b = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at="2026-01-02T11:00:00.000Z",
            ends_at="2026-01-02T12:00:00.000Z",
        )
        assert a["status"] == "OPEN"
        assert b["status"] == "OPEN"

    # difficulty: resource_temporal_overlap/trainer_slot_half_open_adjacent_allowed
    def test_trainer_slot_one_minute_overlap_rejected(self, api):
        """PRD §3.8: 'publishing a slot that overlaps any other slot
        of the same trainer whose status is OPEN or RESERVED is
        rejected with ERR_SLOT_OVERLAP.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
        )
        # 1-minute overlap.
        res = api.create_trainer_slot(
            {"trainer_id": trainer["id"],
             "starts_at": "2026-01-02T10:59:00.000Z",
             "ends_at": "2026-01-02T11:30:00.000Z",
             "specialty_code": "STRENGTH"},
            make_trainer_headers(trainer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP.value)

    # difficulty: resource_temporal_overlap/group_class_30min_buffer_required
    def test_group_class_touching_endpoints_rejected(self, api):
        """PRD §3.9: 'Adjacent-endpoint classes are therefore rejected
        at this step, with ERR_CLASS_OVERLAP.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
            capacity=5,
        )
        res = api.create_group_class(
            {"class_code": "GC_TOUCH", "instructor_trainer_id": trainer["id"],
             "starts_at": "2026-01-02T11:00:00.000Z",
             "ends_at": "2026-01-02T12:00:00.000Z",
             "capacity": 5},
            SO,
        )
        validate_error(res, ApiErrorId.ERR_CLASS_OVERLAP.value)

    # difficulty: resource_temporal_overlap/group_class_30min_buffer_required
    def test_group_class_30min_buffer_accepted(self, api):
        """PRD §3.9: 'b's starts_at minus a's ends_at must be at least
        30 minutes.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
            capacity=5,
        )
        # Exactly 30 minutes buffer.
        res = api.create_group_class(
            {"class_code": "GC_30B", "instructor_trainer_id": trainer["id"],
             "starts_at": "2026-01-02T11:30:00.000Z",
             "ends_at": "2026-01-02T12:30:00.000Z",
             "capacity": 5},
            SO,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    # difficulty: compensating_invariant/card_refund_wallet_principal_invariant
    def test_card_refund_returns_wallet_principal_to_baseline(self, api):
        """PRD §3.6: 'On refund, the system computes the remaining
        value via the forward-looking formula.' and 'The remaining
        value is credited to the holder's wallet as a
        WalletTransaction with kind=REFUND, bucket=PRINCIPAL.'

        For zero days elapsed and exact divisibility, remaining_value
        equals issuance_price; after refund the principal returns to
        baseline (zero drift).

        ANNUAL price 120000, 365 days elapsed=0 → remaining_value =
        round_half_up(120000 * 365 / 365) = 120000. Principal before
        issue was 200000 → 80000 → 200000 after refund.
        """
        # remaining_days=365 → activate then a tiny clock bump.
        ct, member, card = setup_annual_card_at_remaining_days(
            remaining_days=365,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            max_freeze_days=0,
        )
        # Member's wallet before refund is post-issuance.
        before = get_member(member["id"])
        validate_success(api.refund_card(card["id"], SO), expected_status=200)
        after = get_member(member["id"])
        # Principal after = principal before + 120000 (refund credit).
        # Bonus is not refunded (PRD §3.4).
        assert (
            after["wallet_balance_cents"] - before["wallet_balance_cents"]
            == 120_000
        ), (
            "PRD §3.6 refund credits exactly remaining_value to "
            "PRINCIPAL; with 365/365 days elapsed=0 that equals "
            "issuance_price=120000."
        )

    # difficulty: compensating_invariant/card_refund_wallet_principal_invariant
    def test_card_refund_ledger_principal_sum_matches_projection(self, api):
        """PRD §2.8: 'A member's wallet_balance_cents is projected by
        summing every WalletTransaction.amount_cents for that
        member.'

        Sum of all WalletTransaction.amount_cents (filtered to
        PRINCIPAL bucket) must equal Member.wallet_balance_cents
        minus Member.bonus_balance_cents (i.e., the principal
        sub-projection).
        """
        ct, member, card = setup_annual_card_at_remaining_days(
            remaining_days=365,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            max_freeze_days=0,
        )
        validate_success(api.refund_card(card["id"], SO), expected_status=200)
        after = get_member(member["id"])
        rows = list_wallet_transactions(
            member["id"], headers=make_member_headers(member["id"]),
        )
        principal_sum = sum(
            r["amount_cents"] for r in rows
            if r.get("bucket") == "PRINCIPAL"
        )
        expected_principal = (
            after["wallet_balance_cents"] - after["bonus_balance_cents"]
        )
        assert principal_sum == expected_principal, (
            f"PRD §2.8: sum of PRINCIPAL-bucket WalletTransaction "
            f"amounts must equal the projected principal balance; got "
            f"sum={principal_sum} vs projected={expected_principal}"
        )

    # difficulty: compensating_invariant/package_refund_commission_invariant
    def test_package_refund_commission_invariant(self, api):
        """PRD §3.8: 'On refund ... the system locates the original
        PACKAGE_SALE CommissionRecord for the package, computes the
        unconsumed-sessions count, and appends a CommissionRecord of
        kind=REVERSAL whose amount_cents equals the negative of the
        original commission multiplied by unconsumed sessions divided
        by total_sessions, rounded half-up.'

        Invariant: SUM(SALE + REVERSAL) for this package equals the
        commission attributable to CONSUMED sessions only:
          round_half_up(original * consumed / total).
        With gross=100000, pkg_bp=800, total=7, consumed=3:
          original = 8000; reversal = -round_half_up(8000*4/7) =
          -4571; net = 3429 == round_half_up(8000*3/7).
        """
        trainer, member, package, _ = (
            setup_package_with_partial_consumption_simple(
                total_sessions=7,
                sessions_to_complete=3,
                gross_price_cents=100_000,
                package_commission_pct_bp=800,
            )
        )
        validate_success(
            api.refund_pt_package(package["id"], SO),
            expected_status=200,
        )
        rows = list_trainer_commissions(trainer["id"])
        pkg_rows = [
            r for r in rows
            if (r.get("ref_entity") or "").startswith(
                f"PTPackage:{package['id']}",
            )
        ]
        net = sum(
            r["amount_cents"] for r in pkg_rows
            if r["kind"] in ("PACKAGE_SALE", "REVERSAL")
        )
        expected = round_half_up(8_000 * 3 / 7)   # 3429
        assert net == expected, (
            f"PRD §3.8 invariant: net commission after package refund "
            f"equals commission attributable to consumed sessions only; "
            f"got net={net}, expected {expected}."
        )

    # difficulty: compensating_invariant/package_refund_commission_invariant
    def test_package_refund_status_terminal(self, api):
        """PRD §3.8: 'The package transitions ACTIVE → REFUNDED.'"""
        trainer, member, package, _ = (
            setup_package_with_partial_consumption_simple(
                total_sessions=5,
                sessions_to_complete=2,
                gross_price_cents=50_000,
                package_commission_pct_bp=500,
            )
        )
        refunded = validate_success(
            api.refund_pt_package(package["id"], SO),
            expected_status=200,
        )
        assert refunded["status"] == "REFUNDED"
