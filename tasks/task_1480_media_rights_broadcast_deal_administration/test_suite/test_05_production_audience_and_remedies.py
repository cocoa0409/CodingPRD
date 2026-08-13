"""Production obligations, make-good credits, and audience measurement
accumulation: escalated-fee vs make-good domains, aggravation threshold,
liability conservation, and CONFIRMED-only rating accumulation."""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    create_audience_measurement_payload,
    create_delivered_events,
    get_deal,
    get_milestone,
    get_obligation,
    make_bid_coordinator_headers,
    setup_executed_deal,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]
PA = TEST_USERS["production_auditor_headers"]
CO = TEST_USERS["compliance_officer_headers"]

PAST_SEASON_END = "2027-01-15T00:00:00Z"


class TestMakeGoodVersusEscalatedFee:
    def test_declare_shortfall_computes_make_good_credit(self, api):
        """PRD §3.6: "Declaring a shortfall fixes `shortfall_games` as the
        games required minus the games delivered, computes the obligation's
        `make_good_credit_cents`, adds that credit into the deal's
        `accrued_make_good_credit_cents`".

        Per-game 50000000/20 = 2500000; shortfall 12; ratio 0.60 > 0.20 so
        the 1.5 multiplier applies: 12 * 2500000 * 1.5 = 45000000, under the
        50000000 season-fee cap.

        Design: Difficulty/dual_variant_calc/escalated_fee_vs_make_good_credit_divergent_domains
        """
        bundle = setup_executed_deal(
            package_overrides={"games_committed": 20},
            bid_overrides={
                "offered_fee_cents": 50000000,
                "escalator_rate_pct": 0.05,
                "minimum_growth_pct": 0.02,
                "fee_cap_cents": 80000000,
                "production_commitment_games": 20,
            },
        )
        deal_id = bundle["deal"]["id"]
        obligation = bundle["obligations"][0]
        create_delivered_events(deal_id, obligation["id"], 8)
        advance_clock(PAST_SEASON_END)

        result = validate_success(
            api.declare_shortfall(deal_id, obligation["id"], PA), 200
        )
        assert result["shortfall_games"] == 12
        assert result["make_good_credit_cents"] == 45000000
        assert get_deal(deal_id)["accrued_make_good_credit_cents"] == 45000000

    def test_season_fee_and_make_good_credit_are_independent_figures(self, api):
        """PRD §3.4: "in season 1 the fee is simply the smaller of
        `base_fee_cents` and the cap."
        PRD §3.6: "the obligation's `games_required` is copied from the
        winning bid's `production_commitment_games`".

        Same deal, two subsystems: the season-1 escalated fee is 50000000
        (milestone weight 1.0) while the make-good credit on the obligation
        is 45000000.

        Design: Difficulty/dual_variant_calc/escalated_fee_vs_make_good_credit_divergent_domains
        """
        bundle = setup_executed_deal(
            package_overrides={"games_committed": 20},
            bid_overrides={
                "offered_fee_cents": 50000000,
                "escalator_rate_pct": 0.05,
                "minimum_growth_pct": 0.02,
                "fee_cap_cents": 80000000,
                "production_commitment_games": 20,
            },
        )
        deal_id = bundle["deal"]["id"]
        obligation = bundle["obligations"][0]
        assert obligation["games_required"] == 20
        create_delivered_events(deal_id, obligation["id"], 8)
        advance_clock(PAST_SEASON_END)
        validate_success(api.declare_shortfall(deal_id, obligation["id"], PA), 200)

        milestone = get_milestone(deal_id, bundle["milestones"][0]["id"])
        assert milestone["base_amount_cents"] == 50000000
        obligation_after = get_obligation(deal_id, obligation["id"])
        assert obligation_after["make_good_credit_cents"] == 45000000
        assert milestone["base_amount_cents"] != obligation_after["make_good_credit_cents"]


class TestAggravationThreshold:
    def _shortfall_deal(self, api, delivered):
        bundle = setup_executed_deal(
            package_overrides={"games_committed": 10},
            bid_overrides={
                "offered_fee_cents": 10000000,
                "escalator_rate_pct": 0.0,
                "minimum_growth_pct": 0.0,
                "fee_cap_cents": 20000000,
                "production_commitment_games": 10,
            },
        )
        deal_id = bundle["deal"]["id"]
        obligation = bundle["obligations"][0]
        create_delivered_events(deal_id, obligation["id"], delivered)
        advance_clock(PAST_SEASON_END)
        return deal_id, obligation

    def test_ratio_exactly_at_threshold_does_not_aggravate(self, api):
        """PRD §3.6: "When the shortfall ratio — `shortfall_games` divided
        by `games_required` — is strictly greater than 0.20, an aggravation
        multiplier of 1.5 applies; otherwise the multiplier is 1.0."

        2/10 = 0.20 exactly: per-game 1000000, credit 2 * 1000000 = 2000000.

        Design: Difficulty/boundary_precision_check/aggravation_threshold_strict_greater_than
        """
        deal_id, obligation = self._shortfall_deal(api, delivered=8)
        result = validate_success(
            api.declare_shortfall(deal_id, obligation["id"], PA), 200
        )
        assert result["shortfall_games"] == 2
        assert result["make_good_credit_cents"] == 2000000

    def test_ratio_above_threshold_applies_multiplier(self, api):
        """PRD §3.6: "When the shortfall ratio — `shortfall_games` divided
        by `games_required` — is strictly greater than 0.20, an aggravation
        multiplier of 1.5 applies; otherwise the multiplier is 1.0."

        3/10 = 0.30 > 0.20: 3 * 1000000 * 1.5 = 4500000.

        Design: Difficulty/boundary_precision_check/aggravation_threshold_strict_greater_than
        """
        deal_id, obligation = self._shortfall_deal(api, delivered=7)
        result = validate_success(
            api.declare_shortfall(deal_id, obligation["id"], PA), 200
        )
        assert result["shortfall_games"] == 3
        assert result["make_good_credit_cents"] == 4500000


class TestMakeGoodLiabilityConservation:
    def _declared_shortfall(self, api):
        """ACTIVE deal, obligation 5 required / 3 delivered, shortfall declared.

        Per-game 5000000/5 = 1000000; ratio 2/5 = 0.40 > 0.20 so the
        aggravated credit is 2 * 1000000 * 1.5 = 3000000.
        """
        bundle = setup_executed_deal(
            package_overrides={"games_committed": 5},
            bid_overrides={
                "offered_fee_cents": 5000000,
                "escalator_rate_pct": 0.0,
                "minimum_growth_pct": 0.0,
                "fee_cap_cents": 10000000,
                "production_commitment_games": 5,
            },
        )
        deal_id = bundle["deal"]["id"]
        obligation = bundle["obligations"][0]
        create_delivered_events(deal_id, obligation["id"], 3)
        advance_clock(PAST_SEASON_END)
        return deal_id, obligation

    def test_declare_shortfall_adds_credit_to_deal_balance(self, api):
        """PRD §3.6: "Declaring a shortfall fixes `shortfall_games` as the
        games required minus the games delivered, computes the obligation's
        `make_good_credit_cents`, adds that credit into the deal's
        `accrued_make_good_credit_cents` — the running credit the league
        owes back to the broadcaster — and re-evaluates posture."

        Design: Difficulty/compensating_invariant/make_good_credit_conserves_liability_balance
        """
        deal_id, obligation = self._declared_shortfall(api)
        assert get_deal(deal_id)["accrued_make_good_credit_cents"] == 0

        result = validate_success(
            api.declare_shortfall(deal_id, obligation["id"], PA), 200
        )
        assert result["shortfall_games"] == 2
        assert result["make_good_credit_cents"] == 3000000
        assert result["status"] == "SHORTFALL_DECLARED"
        assert get_deal(deal_id)["accrued_make_good_credit_cents"] == 3000000

    def test_forgive_credit_returns_balance_to_zero(self, api):
        """PRD §3.6: "a `RightsManager` may forgive the credit, but only
        while nothing has been offset — `credit_settled_cents` still zero —
        moving the obligation to `CREDITED`, zeroing its
        `make_good_credit_cents`, subtracting that amount from the deal's
        accrued credit".

        Design: Difficulty/compensating_invariant/make_good_credit_conserves_liability_balance
        """
        deal_id, obligation = self._declared_shortfall(api)
        validate_success(api.declare_shortfall(deal_id, obligation["id"], PA), 200)
        assert get_deal(deal_id)["accrued_make_good_credit_cents"] == 3000000

        forgiven = validate_success(
            api.forgive_credit(deal_id, obligation["id"], RM), 200
        )
        assert forgiven["status"] == "CREDITED"
        assert forgiven["make_good_credit_cents"] == 0
        # Compensating action conserves the balance: +3000000 then -3000000.
        assert get_deal(deal_id)["accrued_make_good_credit_cents"] == 0


class TestRatingAccumulation:
    def _deal_with_two_measurements(self, api):
        """Executed deal with two delivered events; M1 confirmed, M2 filed
        but not yet confirmed."""
        bundle = setup_executed_deal(
            asset_overrides={"guaranteed_rating_basis_points": 5000},
            bid_overrides={"audience_commitment_pct": 0.6},
        )
        deal_id = bundle["deal"]["id"]
        obligation = bundle["obligations"][0]
        events = create_delivered_events(deal_id, obligation["id"], 2)
        m1 = validate_success(
            api.create_audience_measurement(
                deal_id,
                create_audience_measurement_payload(
                    events[0]["id"],
                    reporting_period_end="2026-09-30T23:59:59Z",
                    rating_basis_points=1000,
                ),
                PA,
            ),
            201,
        )
        validate_success(api.confirm_measurement(deal_id, m1["id"], PA), 200)
        m2 = validate_success(
            api.create_audience_measurement(
                deal_id,
                create_audience_measurement_payload(
                    events[1]["id"],
                    reporting_period_end="2026-11-15T23:59:59Z",
                    rating_basis_points=800,
                    source="CENSUS",
                ),
                PA,
            ),
            201,
        )
        return deal_id, m1, m2

    def test_provisional_measurement_not_counted_until_confirmed(self, api):
        """PRD §3.7: "The provisional remedy, computed at quarter-end review,
        draws its input only from `CONFIRMED` measurements whose
        `reporting_period_end` falls on or before the quarter's end."
        PRD §3.7: "confirmation adds the measurement's `rating_basis_points`
        to the deal's `cumulative_rating_basis_points`".

        With only M1 confirmed, cumulative delivery is 1000, not 1800.

        Design: Difficulty/dual_variant_calc/rating_shortfall_remedy_provisional_vs_final
        """
        deal_id, _m1, m2 = self._deal_with_two_measurements(api)
        deal = get_deal(deal_id)
        assert deal["cumulative_rating_basis_points"] == 1000
        assert deal["audience_commitment_basis_points"] == 3000
        # M2 is still PROVISIONAL: outside the confirmed input set.
        m2_state = validate_success(
            api.get_audience_measurement(deal_id, m2["id"], RM), 200
        )
        assert m2_state["status"] == "PROVISIONAL"

    def test_late_confirmed_measurement_joins_final_input_set(self, api):
        """PRD §3.7: "The final remedy, computed at season close, draws on
        every `CONFIRMED` measurement regardless of period, together with
        late-arriving measurements still `PROVISIONAL` at season close
        provided they reach `CONFIRMED` within `LATE_GRACE_DAYS` after the
        season ends."
        PRD §3.7: "confirmation adds the measurement's `rating_basis_points`
        to the deal's `cumulative_rating_basis_points`".

        Confirming M2 lifts cumulative delivery to 1800.

        Design: Difficulty/dual_variant_calc/rating_shortfall_remedy_provisional_vs_final
        """
        deal_id, _m1, m2 = self._deal_with_two_measurements(api)
        validate_success(api.confirm_measurement(deal_id, m2["id"], PA), 200)
        deal = get_deal(deal_id)
        assert deal["cumulative_rating_basis_points"] == 1800

    def test_only_confirmed_measurements_count_toward_cumulative(self, api):
        """PRD §3.7: "confirmation adds the measurement's
        `rating_basis_points` to the deal's
        `cumulative_rating_basis_points`" — only confirmation performs the
        addition, so PROVISIONAL, DISPUTED, and EXCLUDED rows never
        contribute.

        Design: Corner/calculations/cumulative_rating_only_counts_confirmed
        """
        bundle = setup_executed_deal()
        deal_id = bundle["deal"]["id"]
        obligation = bundle["obligations"][0]
        broadcaster = bundle["broadcaster"]
        events = create_delivered_events(deal_id, obligation["id"], 4)

        m1 = validate_success(
            api.create_audience_measurement(
                deal_id,
                create_audience_measurement_payload(
                    events[0]["id"], rating_basis_points=1000
                ),
                PA,
            ),
            201,
        )
        validate_success(api.confirm_measurement(deal_id, m1["id"], PA), 200)

        # PROVISIONAL 500: filed, never confirmed.
        validate_success(
            api.create_audience_measurement(
                deal_id,
                create_audience_measurement_payload(
                    events[1]["id"], rating_basis_points=500
                ),
                PA,
            ),
            201,
        )
        # DISPUTED 300.
        m3 = validate_success(
            api.create_audience_measurement(
                deal_id,
                create_audience_measurement_payload(
                    events[2]["id"], rating_basis_points=300
                ),
                PA,
            ),
            201,
        )
        validate_success(
            api.dispute_measurement(
                deal_id, m3["id"], make_bid_coordinator_headers(broadcaster["id"])
            ),
            200,
        )
        # EXCLUDED 200: disputed then excluded.
        m4 = validate_success(
            api.create_audience_measurement(
                deal_id,
                create_audience_measurement_payload(
                    events[3]["id"], rating_basis_points=200
                ),
                PA,
            ),
            201,
        )
        validate_success(
            api.dispute_measurement(
                deal_id, m4["id"], make_bid_coordinator_headers(broadcaster["id"])
            ),
            200,
        )
        validate_success(api.exclude_measurement(deal_id, m4["id"], CO), 200)

        assert get_deal(deal_id)["cumulative_rating_basis_points"] == 1000
