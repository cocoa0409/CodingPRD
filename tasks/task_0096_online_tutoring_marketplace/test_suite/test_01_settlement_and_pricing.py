"""Settlement, commission, and billed-minutes pricing calculations.

Covers the dual-variant settlement (trial vs standard), the nested-min
billed-minutes formula, the inclusive commission-tier breakpoint, and the
three-hop confirm-settlement cascade.
"""
from test_helpers import (
    consume_trial_slot,
    create_booking,
    deliver_booking,
    settlement_for_session,
    setup_marketplace,
    validate_success,
)


class TestTrialVsStandardSettlement:
    def test_trial_and_standard_net_diverge_by_750(self, api):
        """PRD §3.8: "for a standard (non-trial) settlement the rate is the tier
        rate selected from the active commission policy by the tutor's
        `lifetime_net_earnings_cents` as observed before this settlement's net is
        added; for a trial settlement the rate is the policy's
        `trial_commission_bps`, which overrides the tiered rate."
        PRD §3.8: "`commission_cents` is the `gross_amount_cents` multiplied by
        `commission_bps`, divided by 10000, rounded half up. Fourth the **net**:
        `tutor_net_cents` is `gross_amount_cents` minus `commission_cents`."

        Design: Difficulty/dual_variant_calc/trial_vs_standard_settlement_net_diverges
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        # Trial booking #1: planned 30, actual 45 -> billed capped at 30; gross 3000.
        trial_booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        trial_session = deliver_booking(mk, trial_booking["id"], 45, "2026-06-02T11:00:00Z")
        validate_success(api.confirm_session(trial_session["id"], mk["parent_headers"]))

        # Standard booking #2 for the same pair: planned 30, actual 30, billed 30.
        std_booking = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=30)
        std_session = deliver_booking(mk, std_booking["id"], 30, "2026-06-03T11:00:00Z")
        validate_success(api.confirm_session(std_session["id"], mk["parent_headers"]))

        trial_settle = settlement_for_session(trial_session["id"])
        std_settle = settlement_for_session(std_session["id"])

        assert trial_settle["gross_amount_cents"] == 3000
        assert trial_settle["commission_bps"] == 5000
        assert trial_settle["tutor_net_cents"] == 1500

        assert std_settle["gross_amount_cents"] == 3000
        assert std_settle["commission_bps"] == 2500
        assert std_settle["tutor_net_cents"] == 2250

        assert std_settle["tutor_net_cents"] - trial_settle["tutor_net_cents"] == 750

    def test_trial_settlement_commission_uses_trial_rate(self, api):
        """PRD §3.8: "for a trial settlement the rate is the policy's
        `trial_commission_bps`, which overrides the tiered rate."
        PRD §3.8: "`gross_amount_cents` is the session's `effective_hourly_rate_cents`
        ... multiplied by the session's `billed_minutes`, divided by 60, rounded
        half up to whole cents."

        Design: Difficulty/dual_variant_calc/trial_vs_standard_settlement_net_diverges
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        trial_booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        trial_session = deliver_booking(mk, trial_booking["id"], 45, "2026-06-02T11:00:00Z")
        validate_success(api.confirm_session(trial_session["id"], mk["parent_headers"]))

        trial_settle = settlement_for_session(trial_session["id"])
        # 6000 c/hr * 30 billed / 60 = 3000 gross; 3000 * 5000 / 10000 = 1500 commission.
        assert trial_settle["gross_amount_cents"] == 3000
        assert trial_settle["commission_bps"] == 5000
        assert trial_settle["commission_cents"] == 1500
        assert trial_settle["tutor_net_cents"] == 1500


class TestBilledMinutes:
    def test_standard_overtime_cap_wins_over_actual(self, api):
        """PRD §3.7: "Cap it at `planned_minutes` plus a fifteen-minute overtime
        grace — that is, billed minutes may not exceed the planned duration by
        more than fifteen minutes."
        PRD §3.7: "For a non-trial booking only the overtime cap and the floor
        apply."

        Design: Difficulty/combinatorial_formula/billed_minutes_nested_min_three_inputs
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        consume_trial_slot(mk)
        # Standard booking planned 60, delivered actual 120 -> billed capped at 75.
        std_booking = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=60)
        session = deliver_booking(mk, std_booking["id"], 120, "2026-06-03T11:00:00Z")
        assert session["billed_minutes"] == 75

    def test_trial_cap_wins_over_overtime_cap(self, api):
        """PRD §3.7: "If the booking is a trial, apply a second cap so that billed
        minutes additionally may not exceed the policy's `trial_max_billed_minutes`;
        the active cap is whichever of these limits is the smaller."

        Design: Difficulty/combinatorial_formula/billed_minutes_nested_min_three_inputs
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        # First booking for the pair is the trial. planned 60, actual 120:
        # overtime cap = 75, trial cap = 30 -> 30 wins.
        trial_booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=60)
        session = deliver_booking(mk, trial_booking["id"], 120, "2026-06-02T11:00:00Z")
        assert session["billed_minutes"] == 30


class TestCommissionTierBreakpoint:
    def test_lifetime_at_breakpoint_selects_higher_tier_inclusive(self, api):
        """PRD §3.8: "Selecting the standard tier means choosing the largest index
        for which the breakpoint at that index in `tier_breakpoints_cents` is less
        than or equal to the tutor's pre-settlement `lifetime_net_earnings_cents`,
        and taking the parallel rate at that index in `tier_rates_bps`."
        PRD §3.8: "the tier read uses the lifetime earnings value from before this
        settlement's `tutor_net_cents` is added".

        Design: Difficulty/boundary_precision_check/commission_tier_breakpoint_inclusive
        """
        # Effective rate 400000c/hr via subject_rate override; base stays in bounds.
        mk = setup_marketplace(base_hourly_rate_cents=50000, subject_rate_cents=400000, wallet_cents=1000000)
        # Trial: planned 30 -> billed 30 -> gross 200000; trial 5000 bps -> net 100000.
        trial_booking = create_booking(mk, "2026-06-02T06:00:00Z", planned_minutes=30)
        trial_session = deliver_booking(mk, trial_booking["id"], 30, "2026-06-02T07:00:00Z")
        validate_success(api.confirm_session(trial_session["id"], mk["parent_headers"]))
        # Pre-settlement lifetime is now EXACTLY 100000.
        std_booking = create_booking(mk, "2026-06-02T08:00:00Z", planned_minutes=60)
        std_session = deliver_booking(mk, std_booking["id"], 60, "2026-06-02T09:00:00Z")
        validate_success(api.confirm_session(std_session["id"], mk["parent_headers"]))

        std_settle = settlement_for_session(std_session["id"])
        # lifetime == 100000 == breakpoint[1] -> tier index 1 -> 1500 bps (inclusive).
        assert std_settle["commission_bps"] == 1500
        assert std_settle["gross_amount_cents"] == 400000
        assert std_settle["commission_cents"] == 60000
        assert std_settle["tutor_net_cents"] == 340000

    def test_lifetime_below_breakpoint_uses_lower_tier(self, api):
        """PRD §3.8: "Selecting the standard tier means choosing the largest index
        for which the breakpoint at that index in `tier_breakpoints_cents` is less
        than or equal to the tutor's pre-settlement `lifetime_net_earnings_cents`".

        Design: Difficulty/boundary_precision_check/commission_tier_breakpoint_inclusive
        """
        # A tutor with zero prior earnings: pre-settlement lifetime 0 -> tier 0 (2500 bps).
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        consume_trial_slot(mk)  # trial does not use a standard tier
        std_booking = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=30)
        std_session = deliver_booking(mk, std_booking["id"], 30, "2026-06-03T11:00:00Z")
        validate_success(api.confirm_session(std_session["id"], mk["parent_headers"]))
        std_settle = settlement_for_session(std_session["id"])
        # lifetime 0 == breakpoint[0] -> tier 0 -> 2500 bps.
        assert std_settle["commission_bps"] == 2500


class TestConfirmSettlementCascade:
    def test_confirm_drives_three_hop_settlement_cascade(self, api):
        """PRD §3.7: "Confirming the delivery moves the session's `delivery_status`
        from `REPORTED` to `CONFIRMED` and triggers settlement: a `Settlement` is
        created, the booking advances from `DELIVERED` to `SETTLED`, the session's
        `settlement_status` becomes `SETTLED`, and the tutor's
        `lifetime_net_earnings_cents` and `reliability_score` are updated."
        PRD §3.7: "As part of settlement the parent's wallet hold is released and
        the wallet is debited by the settlement's `gross_amount_cents`, and the
        tutor's `payout_balance_cents` is credited by the settlement's
        `tutor_net_cents`."

        Design: Difficulty/transitive_cascade/confirm_session_three_hop_settlement_cascade
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000, wallet_cents=100000)
        # First booking for the pair is the trial: planned 30, billed 30, gross 3000,
        # trial 5000 bps -> net 1500.
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        session = deliver_booking(mk, booking["id"], 30, "2026-06-02T11:00:00Z")
        validate_success(api.confirm_session(session["id"], mk["parent_headers"]))

        # Hop 2: booking SETTLED.
        booking_after = validate_success(api.get_booking(booking["id"], mk["parent_headers"]))
        assert booking_after["status"] == "SETTLED"

        # Hop 1: a Settlement exists with net 1500.
        settle = settlement_for_session(session["id"])
        assert settle is not None and settle["tutor_net_cents"] == 1500

        # Hop 3: tutor ledger updated.
        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        assert tutor["lifetime_net_earnings_cents"] == 1500
        assert tutor["payout_balance_cents"] == 1500

        # Parent wallet debited by gross 3000; hold released.
        parent = validate_success(api.get_parent_account(mk["parent"]["id"], mk["parent_headers"]))
        assert parent["wallet_balance_cents"] == 97000
        assert parent["held_balance_cents"] == 0

    def test_confirm_sets_session_settled_and_credits_tutor_net(self, api):
        """PRD §3.7: "the session's `settlement_status` becomes `SETTLED`, and the
        tutor's `lifetime_net_earnings_cents` and `reliability_score` are updated."
        PRD §3.7: "the tutor's `payout_balance_cents` is credited by the
        settlement's `tutor_net_cents`."

        Design: Difficulty/transitive_cascade/confirm_session_three_hop_settlement_cascade
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000, wallet_cents=100000)
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        session = deliver_booking(mk, booking["id"], 30, "2026-06-02T11:00:00Z")
        confirmed = validate_success(api.confirm_session(session["id"], mk["parent_headers"]))
        # The session axis advances to SETTLED as part of the cascade.
        assert confirmed["settlement_status"] == "SETTLED"
        settle = settlement_for_session(session["id"])
        # Trial: gross 3000, net 1500. Tutor payout credited by the net.
        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        assert tutor["payout_balance_cents"] == settle["tutor_net_cents"] == 1500
