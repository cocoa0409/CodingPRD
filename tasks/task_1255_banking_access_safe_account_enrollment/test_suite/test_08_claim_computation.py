"""Partner-report claim computation: per-account rounding order, retention
rate variants and null-rate boundary, education stipend, cap and funds gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_institution_officer_headers,
    setup_report_ready, setup_two_account_retention_scenario,
    create_report, submit_report, get_grant,
)

ADMIN = TEST_USERS["coalition_admin_headers"]


class TestPerAccountRounding:
    def test_three_accounts_round_per_account_then_sum(self, api):
        """PRD §3.9: "each account's net is computed individually as its gross reduced by an administrative withholding of 75 basis points — that is, gross multiplied by 0.9925 — with the per-account net rounded half-up to integer cents before any summation; `opening_claim_cents` is the sum of those per-account nets. Summing gross first and rounding once is forbidden, because the orders disagree on cents: three accounts at gross 5000 yield 14889 by the pinned order (three times 4963) but 14888 by the forbidden order."

        Design: Difficulty/combinatorial_formula/claim_rounding_per_account_then_sum
        """
        ctx = setup_report_ready(num_accounts=3)  # three OPENED at 2026-05-01
        report = create_report(ctx["institution"]["id"], ctx["grant"],
                               period_start="2026-01-01", period_end="2026-05-31",
                               evaluation_mode="FINAL")
        assert report["opened_count"] == 3
        assert report["opening_claim_cents"] == 14889, (
            "3 x round_half_up(5000 x 0.9925) = 3 x 4963; sum-then-round would give 14888"
        )
        assert report["claim_total_cents"] == 14889

    def test_three_accounts_null_rates_and_zero_stipend(self, api):
        """PRD §3.9: "when a kind's eligible set is empty the rate is null, not zero, and contributes nothing to the bonus."
        PRD §3.9: "When the education condition is not met, or `opened_count` is zero, the stipend is zero."

        Design: Difficulty/combinatorial_formula/claim_rounding_per_account_then_sum
        """
        ctx = setup_report_ready(num_accounts=3)
        report = create_report(ctx["institution"]["id"], ctx["grant"],
                               period_start="2026-01-01", period_end="2026-05-31",
                               evaluation_mode="FINAL")
        assert report["retention_rate_m6"] is None, (
            "no M6 checkpoint due on or before period_end 2026-05-31"
        )
        assert report["retention_bonus_cents"] == 0
        assert report["education_stipend_cents"] == 0, (
            "the standard does not require financial education"
        )


class TestNullRateBoundary:
    def test_empty_eligible_set_yields_null_rates(self, api):
        """PRD §3.9: "For each kind, the eligible set is the retention checkpoints of the report's institution, of that kind, whose `due_date` is on or before `period_end`."
        PRD §3.9: "Each rate — `retention_rate_m6` and `retention_rate_m12` — is the retained count divided by the eligible count, rounded half-up to four decimal places; when a kind's eligible set is empty the rate is null, not zero, and contributes nothing to the bonus."

        Design: Difficulty/boundary_precision_check/retention_empty_eligible_set_null_rate
        """
        ctx = setup_report_ready(num_accounts=1)  # OPENED 2026-05-01; M6 due 2026-10-31
        report = create_report(ctx["institution"]["id"], ctx["grant"],
                               period_start="2026-01-01", period_end="2026-05-31",
                               evaluation_mode="FINAL")
        assert report["retention_rate_m6"] is None, (
            "M6 due 2026-10-31 is after period_end 2026-05-31 -> empty eligible set"
        )
        assert report["retention_rate_m12"] is None
        assert report["retention_bonus_cents"] == 0, "a null primary rate earns no tier"

    def test_null_rate_claim_is_opening_only(self, api):
        """PRD §3.9: "Seventh, `claim_total_cents` is the sum of `opening_claim_cents`, `retention_bonus_cents`, and `education_stipend_cents`."
        PRD §3.9: "with the per-account net rounded half-up to integer cents before any summation; `opening_claim_cents` is the sum of those per-account nets."

        Design: Difficulty/boundary_precision_check/retention_empty_eligible_set_null_rate
        """
        ctx = setup_report_ready(num_accounts=1)
        report = create_report(ctx["institution"]["id"], ctx["grant"],
                               period_start="2026-01-01", period_end="2026-05-31",
                               evaluation_mode="FINAL")
        assert report["opening_claim_cents"] == 4963, "1 x round_half_up(5000 x 0.9925)"
        assert report["claim_total_cents"] == 4963


class TestRetentionVariantDivergence:
    def test_provisional_counts_pending_as_retained(self, api):
        """PRD §3.9: "Under `PROVISIONAL` mode the retained numerator counts checkpoints in `EVALUATED_RETAINED`, `PENDING`, or `EXPIRED_UNCONFIRMED` — an optimistic reading; under `FINAL` mode the retained numerator counts only `EVALUATED_RETAINED` checkpoints, so the same underlying data yields a lower rate."
        PRD §3.9: "a rate of at least 0.80 earns 2500 cents per retained account, a rate of at least 0.60 but below 0.80 earns 1500 cents per retained account, and anything lower (or a null primary rate) earns nothing; the bonus is the tier rate multiplied by the retained count."

        Design: Difficulty/dual_variant_calc/retention_rate_provisional_vs_final
        """
        # A1 OPENED 2026-05-01 (M6 evaluated retained), A2 OPENED 2026-05-15
        # (M6 still PENDING at the 2026-11-10 epoch); period ends 2026-11-30.
        ctx = setup_two_account_retention_scenario()
        report = create_report(ctx["institution"]["id"], ctx["grant_provisional"],
                               period_start="2026-01-01", period_end="2026-11-30",
                               evaluation_mode="PROVISIONAL")
        assert report["retention_rate_m6"] == pytest.approx(1.0, abs=1e-6), (
            "PROVISIONAL counts EVALUATED_RETAINED + PENDING: 2/2"
        )
        assert report["retention_bonus_cents"] == 5000, "rate 1.0000 >= 0.80 -> 2500 x 2"
        assert report["opening_claim_cents"] == 9926
        assert report["claim_total_cents"] == 14926

    def test_final_counts_only_evaluated_retained(self, api):
        """PRD §3.9: "under `FINAL` mode the retained numerator counts only `EVALUATED_RETAINED` checkpoints, so the same underlying data yields a lower rate."
        PRD §3.9: "a rate of at least 0.80 earns 2500 cents per retained account, a rate of at least 0.60 but below 0.80 earns 1500 cents per retained account, and anything lower (or a null primary rate) earns nothing; the bonus is the tier rate multiplied by the retained count."

        Design: Difficulty/dual_variant_calc/retention_rate_provisional_vs_final
        """
        ctx = setup_two_account_retention_scenario()
        report = create_report(ctx["institution"]["id"], ctx["grant_final"],
                               period_start="2026-01-01", period_end="2026-11-30",
                               evaluation_mode="FINAL")
        assert report["retention_rate_m6"] == pytest.approx(0.5, abs=1e-6), (
            "FINAL counts EVALUATED_RETAINED only: 1/2 over the same data"
        )
        assert report["retention_bonus_cents"] == 0, "rate 0.5000 < 0.60 -> no tier"
        assert report["opening_claim_cents"] == 9926
        assert report["claim_total_cents"] == 9926


class TestEducationStipend:
    def test_stipend_computed_on_pre_stipend_subtotal(self, api):
        """PRD §3.9: "Sixth, the `education_stipend_cents` applies only when the institution's certified standard declares `requires_financial_education` and the fraction of eligible-opened accounts whose participant holds a `COMPLETED`, `FOLLOW_UP_DUE`, or `FOLLOW_UP_DONE` pairing is at least 0.5 of `opened_count`; the stipend is then ten percent of the pre-stipend subtotal — `opening_claim_cents` plus `retention_bonus_cents` — rounded half-up to integer cents, and it is computed on that pre-stipend subtotal so it never feeds back into its own base."

        Design: Corner/calculations/education_stipend_pinned_evaluation_order
        """
        ctx = setup_report_ready(num_accounts=1, requires_financial_education=True,
                                 with_completed_pairing=True)
        report = create_report(ctx["institution"]["id"], ctx["grant"],
                               period_start="2026-01-01", period_end="2026-05-31",
                               evaluation_mode="FINAL")
        assert report["opening_claim_cents"] == 4963
        assert report["retention_bonus_cents"] == 0
        assert report["education_stipend_cents"] == 496, (
            "round_half_up(0.10 x 4963) = round(496.3); completion rate 1/1 >= 0.5"
        )
        assert report["claim_total_cents"] == 5459, "4963 + 0 + 496"


class TestSubmitFiscalGates:
    def test_claim_exceeding_per_report_cap_rejected(self, api):
        """PRD §3.9: "The `claim_total_cents` must not exceed the grant's `per_report_cap_cents` (`ERR_CLAIM_EXCEEDS_CAP`) and must not exceed the grant's `available_cents` (`ERR_INSUFFICIENT_GRANT_FUNDS`)."

        Design: Corner/validations/claim_exceeds_cap_rejected
        """
        # Cap 4000 < claim 4963; grant total ample so the funds rule is silent.
        ctx = setup_report_ready(num_accounts=1, grant_total=500000, grant_cap=4000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])

        resp = api.submit_partner_report(
            report["id"], make_institution_officer_headers(inst_id)
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_CAP)

        report_after = get_success_data(api.get_partner_report(report["id"], ADMIN))
        assert report_after["status"] == "DRAFT"
        grant_after = get_grant(ctx["grant"]["id"])
        assert grant_after["reserved_cents"] == 0
        assert grant_after["available_cents"] == 500000

    def test_claim_exceeding_available_funds_rejected(self, api):
        """PRD §3.9: "The `claim_total_cents` must not exceed the grant's `per_report_cap_cents` (`ERR_CLAIM_EXCEEDS_CAP`) and must not exceed the grant's `available_cents` (`ERR_INSUFFICIENT_GRANT_FUNDS`)."

        Design: Corner/validations/insufficient_grant_funds_single_failure
        """
        # Grant total 9000, cap ample. R1 submits (reserved 4963, available
        # 4037); R2's claim 4963 > 4037 fails funds as the sole failing rule.
        ctx = setup_report_ready(num_accounts=1, grant_total=9000, grant_cap=200000)
        inst_id = ctx["institution"]["id"]
        report1 = create_report(inst_id, ctx["grant"])
        submit_report(report1["id"], inst_id)
        report2 = create_report(inst_id, ctx["grant"])  # fresh OCC version fetched

        resp = api.submit_partner_report(
            report2["id"], make_institution_officer_headers(inst_id)
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_GRANT_FUNDS)

        report2_after = get_success_data(api.get_partner_report(report2["id"], ADMIN))
        assert report2_after["status"] == "DRAFT"
        grant_after = get_grant(ctx["grant"]["id"])
        assert grant_after["reserved_cents"] == 4963, "only R1's reservation remains"
