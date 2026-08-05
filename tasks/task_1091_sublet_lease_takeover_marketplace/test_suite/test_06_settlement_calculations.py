"""Settlement financial computations: proration, deposit cap, total move-in, fee rounding."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_applicant_headers, setup_scenario,
)

TAKEOVER_KW = dict(
    lease_overrides={"monthly_rent_cents": 400000, "security_deposit_cents": 1000000,
                     "allows_assignment": True, "allows_sublet": False},
    listing_overrides={"listing_type": "TAKEOVER", "asking_rent_cents": 400000, "min_term_months": 2},
    applicant_overrides={"annual_income_cents": 30000000, "credit_score": 760},
    application_overrides={"proposed_move_in_date": "2026-07-01", "proposed_move_out_date": "2026-09-30"},
    agreement_overrides={"occupancy_start_date": "2026-07-01", "occupancy_end_date": "2026-09-30"},
)

FEE_ROUND_KW = dict(
    lease_overrides={"monthly_rent_cents": 300005, "security_deposit_cents": 500050, "allows_sublet": True},
    listing_overrides={"listing_type": "SUBLET", "asking_rent_cents": 300005, "min_term_months": 2},
    applicant_overrides={"annual_income_cents": 30000000, "credit_score": 760},
    application_overrides={"proposed_move_in_date": "2026-06-01", "proposed_move_out_date": "2026-08-31"},
    agreement_overrides={"occupancy_start_date": "2026-06-01", "occupancy_end_date": "2026-08-31"},
)


class TestProrationProvisionalVsFinal:
    """Difficulty: dual_variant_calc — provisional proration (from occupancy_start) and
    final proration (from the actual handoff_date) differ when the dates differ."""

    def test_provisional_prorated_at_draft(self, api):
        """PRD §3.4: "The provisional rent is the base monthly rent multiplied by those
        remaining days, divided by the total number of days in that month, rounded half
        up to whole cents." PRD §3.4: "At creation the `final_prorated_first_rent_cents`
        is 0; it stays 0 until the actual key handoff recomputes it."

        Design: Difficulty/dual_variant_calc/proration_provisional_vs_final
        """
        ctx = setup_scenario(api, stage="drafted")  # rent 300000, occupancy_start 2026-06-10
        s = ctx["settlement"]
        assert s["prorated_first_rent_cents"] == 210000, f"provisional must be 210000, got {s['prorated_first_rent_cents']}"
        assert s["final_prorated_first_rent_cents"] == 0, "final must be 0 before handoff"

    def test_final_prorated_at_handoff(self, api):
        """PRD §3.6: "the `final_prorated_first_rent_cents` is the base monthly rent
        multiplied by the days remaining in the handoff month (days in that month minus
        the handoff day-of-month plus one, counting the handoff day), divided by the days
        in that month, rounded half up."

        Design: Difficulty/dual_variant_calc/proration_provisional_vs_final
        """
        ctx = setup_scenario(api, stage="handed_off", handoff_date="2026-06-15")
        s = ctx["settlement"]
        assert s["status"] == "HANDED_OFF", f"expected HANDED_OFF, got {s['status']}"
        assert s["final_prorated_first_rent_cents"] == 160000, (
            f"final proration from 2026-06-15 must be 160000, got {s['final_prorated_first_rent_cents']}")


class TestTotalMoveInTakeoverDepositCap:
    """Difficulty: combinatorial_formula — TAKEOVER total move-in with a nested deposit
    cap and a conditional last-month-rent branch."""

    def test_deposit_capped_and_last_month_rent_set(self, api):
        """PRD §3.4: "The `deposit_amount_cents` is the smaller of the lease's
        `security_deposit_cents` and twice the base monthly rent — the deposit cap
        multiple of 2 protects the applicant from an excessive hold. The
        `last_month_rent_cents` is the base monthly rent for a `TAKEOVER` and 0 for a
        `SUBLET`."

        Design: Difficulty/combinatorial_formula/total_move_in_takeover_deposit_cap
        """
        ctx = setup_scenario(api, stage="drafted", **TAKEOVER_KW)
        s = ctx["settlement"]
        assert s["deposit_amount_cents"] == 800000, f"deposit capped to 2x rent = 800000, got {s['deposit_amount_cents']}"
        assert s["last_month_rent_cents"] == 400000, f"TAKEOVER last-month rent = 400000, got {s['last_month_rent_cents']}"

    def test_total_move_in_and_fee(self, api):
        """PRD §3.4: "The `total_move_in_cents` — the amount the applicant must fund — is
        the sum of the provisional `prorated_first_rent_cents`, the `deposit_amount_cents`,
        the `last_month_rent_cents`, and the `platform_fee_cents`."

        Design: Difficulty/combinatorial_formula/total_move_in_takeover_deposit_cap
        """
        ctx = setup_scenario(api, stage="drafted", **TAKEOVER_KW)
        s = ctx["settlement"]
        assert s["platform_fee_cents"] == 64000, f"fee must be 64000, got {s['platform_fee_cents']}"
        assert s["total_move_in_cents"] == 1664000, f"total move-in must be 1664000, got {s['total_move_in_cents']}"


class TestPlatformFeeRoundEachTermThenSum:
    """Difficulty: combinatorial_formula — the platform fee rounds each component before
    summing, which differs from sum-then-round by a cent here."""

    def test_fee_rounds_each_component_before_summing(self, api):
        """PRD §2.7: "the service component and the processing component are each rounded
        half up to whole cents independently, and only then added together. Rounding the
        sum instead of the parts can differ by one cent, so the order is contractual, not
        incidental."

        Design: Difficulty/combinatorial_formula/platform_fee_round_each_term_then_sum
        """
        ctx = setup_scenario(api, stage="drafted", **FEE_ROUND_KW)
        s = ctx["settlement"]
        assert s["platform_fee_cents"] == 45003, (
            f"round-each-then-sum fee must be 45003 (not 45002), got {s['platform_fee_cents']}")

    def test_fee_component_inputs(self, api):
        """PRD §3.4: "a service component equal to 10% of the provisional
        `prorated_first_rent_cents`, rounded half up to whole cents, plus a processing
        component equal to 3% of the `deposit_amount_cents`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/platform_fee_round_each_term_then_sum
        """
        ctx = setup_scenario(api, stage="drafted", **FEE_ROUND_KW)
        s = ctx["settlement"]
        assert s["prorated_first_rent_cents"] == 300005, f"full-month prorate must equal 300005, got {s['prorated_first_rent_cents']}"
        assert s["deposit_amount_cents"] == 500050, f"deposit under cap must be 500050, got {s['deposit_amount_cents']}"


def test_funding_amount_mismatch_rejected(api):
    """PRD §3.6: "the tendered `funded_amount_cents` to equal the settlement's
    `total_move_in_cents` exactly; a mismatch is rejected with
    `ERR_FUNDING_AMOUNT_MISMATCH` (HTTP 402)."

    Design: Corner/validations/funding_amount_mismatch_on_fresh_settlement
    """
    ctx = setup_scenario(api, stage="drafted")  # PENDING settlement, total 746000
    resp = api.fund_settlement(ctx["settlement"]["id"], {"funded_amount_cents": 700000},
                               make_applicant_headers(ctx["applicant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FUNDING_AMOUNT_MISMATCH.value)


class TestFundStatePrecedesFiscal:
    """Difficulty: priority_pair_validation_conflict — on an already-FUNDED settlement the
    source-state check (§2.9 step 5) is reported ahead of the fiscal amount check (step 10)."""

    def test_refund_wrong_amount_reports_state_error(self, api):
        """PRD §2.9: "5. **Source state** — the target resource must be in a legal state
        for the requested transition, else the transition's specific conflict error (409)."
        PRD §3.6: "Funding requires the settlement to be `PENDING` (else
        `ERR_SETTLEMENT_NOT_PENDING`)".

        Design: Difficulty/priority_pair_validation_conflict/fund_state_precedes_fiscal
        """
        ctx = setup_scenario(api, stage="funded")  # settlement already FUNDED
        resp = api.fund_settlement(ctx["settlement"]["id"], {"funded_amount_cents": 1},
                                   make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_PENDING.value)

    def test_refund_correct_amount_still_reports_state_error(self, api):
        """PRD §2.9: "10. **Fiscal** — funded amount matching the required total (402)."
        PRD §3.6: "Funding requires the settlement to be `PENDING` (else
        `ERR_SETTLEMENT_NOT_PENDING`)".

        Design: Difficulty/priority_pair_validation_conflict/fund_state_precedes_fiscal
        """
        ctx = setup_scenario(api, stage="funded")
        total = ctx["settlement"]["total_move_in_cents"]
        resp = api.fund_settlement(ctx["settlement"]["id"], {"funded_amount_cents": total},
                                   make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_PENDING.value)
