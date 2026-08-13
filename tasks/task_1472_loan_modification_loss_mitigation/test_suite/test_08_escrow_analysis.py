"""Escrow re-analysis: computation, variants, apply/void conservation, overlap."""
import pytest

from test_helpers import (
    OPS,
    ApiErrorId,
    board_loan,
    create_escrow_analysis_payload,
    get_escrow_analysis,
    get_loan,
    get_success_data,
    make_borrower,
    validate_error,
    validate_success,
)


def _loan_with_escrow(borrower_id, loan_number, escrow_balance, escrow_monthly=30_000):
    return board_loan(
        borrower_id,
        loan_number=loan_number,
        escrow_balance_cents=escrow_balance,
        escrow_monthly_cents=escrow_monthly,
        delinquency_days=0,
        property_state_code="WA",
    )


class TestDualVariantSpread:
    def test_standard_annual_spreads_over_twelve_months(self, api, ops_headers):
        """PRD §3.11: "**Shortage spread** — `monthly_spread_cents` is the
        shortage divided by `comp_year_months`, rounded half-up; this amount is
        collected in months 1 through n−1."
        PRD §3.11: "For `STANDARD_ANNUAL`, `comp_year_months` must equal 12".

        Design: Difficulty/dual_variant_calc/escrow_standard_vs_postmod_shortage_spread
        """
        borrower = make_borrower(full_name="Bob B", email="bob@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-DV2A", 30_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"],
                create_escrow_analysis_payload(),
                ops_headers,
            )
        )
        # cushion 70000 - balance 30000 = shortage 40000 over 12 months.
        assert analysis["shortage_cents"] == 40_000
        assert analysis["monthly_spread_cents"] == 3_333
        assert analysis["new_monthly_escrow_cents"] == 38_333

    def test_post_modification_spreads_over_remaining_months(self, api, ops_headers):
        """PRD §3.11: "`monthly_spread_cents` is the shortage divided by
        `comp_year_months`, rounded half-up" — with a six-month post-modification
        window the identical shortage spreads differently: "for
        `POST_MODIFICATION` it must lie in 1–12".

        Design: Difficulty/dual_variant_calc/escrow_standard_vs_postmod_shortage_spread
        """
        borrower = make_borrower(full_name="Bob B2", email="bob2@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-DV2B", 30_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"],
                create_escrow_analysis_payload(
                    analysis_type="POST_MODIFICATION", comp_year_months=6
                ),
                ops_headers,
            )
        )
        assert analysis["shortage_cents"] == 40_000
        assert analysis["monthly_spread_cents"] == 6_667
        assert analysis["new_monthly_escrow_cents"] == 41_667
        assert analysis["monthly_spread_cents"] != 3_333, (
            "identical inputs diverge across the two computation-window variants"
        )


class TestSpreadRoundingOrder:
    def test_last_month_absorbs_rounding_remainder(self, api, ops_headers):
        """PRD §3.11: "`spread_last_month_cents` is the shortage minus the
        monthly spread times (n − 1) — the rounding remainder always lands in the
        **last** month, never the first; the order is pinned."

        Design: Difficulty/combinatorial_formula/escrow_spread_per_month_rounding_last_month_remainder
        """
        borrower = make_borrower(full_name="Dave D", email="dave@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-CF2", 30_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        assert analysis["cushion_cents"] == 70_000  # 420000 * 2/12
        assert analysis["shortage_cents"] == 40_000
        assert analysis["monthly_spread_cents"] == 3_333  # 40000/12 half-up
        # 40000 - 3333 * 11 = 3337 lands in the LAST month.
        assert analysis["spread_last_month_cents"] == 3_337

    def test_spread_sum_preserved_and_new_monthly(self, api, ops_headers):
        """PRD §3.11: "**New monthly collection** — `new_monthly_escrow_cents` is
        the projected disbursements divided by twelve (rounded half-up) plus the
        monthly spread."
        PRD §3.11: "**Shortage spread** — `monthly_spread_cents` is the shortage
        divided by `comp_year_months`, rounded half-up; this amount is collected
        in months 1 through n−1. `spread_last_month_cents` is the shortage minus
        the monthly spread times (n − 1)".

        Design: Difficulty/combinatorial_formula/escrow_spread_per_month_rounding_last_month_remainder
        """
        borrower = make_borrower(full_name="Dave D2", email="dave2@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-CF2B", 30_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        spread = analysis["monthly_spread_cents"]
        last = analysis["spread_last_month_cents"]
        assert spread * 11 + last == analysis["shortage_cents"] == 40_000
        assert analysis["new_monthly_escrow_cents"] == 35_000 + spread == 38_333


class TestSurplusDisposition:
    def test_surplus_at_5000_refunds_in_full(self, api, ops_headers):
        """PRD §3.11: "**Surplus disposition** — when the surplus is at least
        5000 cents (fifty dollars), `refund_cents` equals the surplus and
        `credit_cents` is zero; when the surplus is positive but below 5000
        cents, `credit_cents` equals the surplus (it stays in the account) and
        `refund_cents` is zero; when there is no surplus, both are zero."

        Design: Corner/calculations/escrow_surplus_refund_50_dollar_boundary
        """
        borrower = make_borrower(full_name="Ann A", email="ann@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-CALC9A", 75_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        assert analysis["surplus_cents"] == 5_000  # 75000 - 70000 cushion
        assert analysis["refund_cents"] == 5_000
        assert analysis["credit_cents"] == 0

    def test_surplus_below_5000_stays_as_credit(self, api, ops_headers):
        """PRD §3.11: "when the surplus is positive but below 5000 cents,
        `credit_cents` equals the surplus (it stays in the account) and
        `refund_cents` is zero".

        Design: Corner/calculations/escrow_surplus_refund_50_dollar_boundary
        """
        borrower = make_borrower(full_name="Ann A2", email="ann2@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-CALC9B", 74_500)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        assert analysis["surplus_cents"] == 4_500
        assert analysis["refund_cents"] == 0
        assert analysis["credit_cents"] == 4_500

    def test_balance_equal_to_cushion_yields_zero_shortage_and_surplus(self, api, ops_headers):
        """PRD §3.11: "**Shortage and surplus** — `shortage_cents` is the amount
        by which the cushion exceeds the balance, floored at zero; `surplus_cents`
        is the amount by which the balance exceeds the cushion, floored at zero.
        Exactly one is positive, or both are zero."

        Design: Corner/calculations/escrow_zero_shortage_when_balance_equals_cushion
        """
        borrower = make_borrower(full_name="Ben B", email="ben@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-CALC10", 70_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        assert analysis["shortage_cents"] == 0
        assert analysis["surplus_cents"] == 0
        assert analysis["monthly_spread_cents"] == 0
        assert analysis["spread_last_month_cents"] == 0
        assert analysis["refund_cents"] == 0
        assert analysis["credit_cents"] == 0
        assert analysis["new_monthly_escrow_cents"] == 35_000


class TestApplyVoidConservation:
    def _applied_surplus_analysis(self, api, ops_headers):
        borrower = make_borrower(full_name="Wen W", email="wen@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-CI2", 200_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        return loan, analysis

    def test_apply_conserves_escrow_cash(self, api, ops_headers):
        """PRD §3.11: "Applying a `DRAFT` analysis moves it to `APPLIED`, sets
        the loan's `escrow_monthly_cents` to `new_monthly_escrow_cents`, and —
        when `refund_cents` is positive — reduces `escrow_balance_cents` by the
        refund amount. Conservation holds: the balance before apply equals the
        balance after apply plus the refund."

        Design: Difficulty/compensating_invariant/escrow_apply_void_cash_conservation
        """
        loan, analysis = self._applied_surplus_analysis(api, ops_headers)
        assert analysis["surplus_cents"] == 130_000
        assert analysis["refund_cents"] == 130_000
        applied = validate_success(api.apply_escrow_analysis(analysis["id"], ops_headers), 200)
        assert applied["status"] == "APPLIED"
        after = get_loan(loan["id"])
        assert after["escrow_balance_cents"] == 70_000
        assert after["escrow_balance_cents"] + analysis["refund_cents"] == 200_000
        assert after["escrow_monthly_cents"] == 35_000

    def test_void_claws_back_refund_and_restores_monthly(self, api, ops_headers):
        """PRD §3.11: "Voiding is the compensating action for an `APPLIED`
        analysis: the loan's `escrow_monthly_cents` is restored to the value it
        had before the apply, and any refund is clawed back into
        `escrow_balance_cents`."

        Design: Difficulty/compensating_invariant/escrow_apply_void_cash_conservation
        """
        loan, analysis = self._applied_surplus_analysis(api, ops_headers)
        get_success_data(api.apply_escrow_analysis(analysis["id"], ops_headers))
        voided = validate_success(api.void_escrow_analysis(analysis["id"], ops_headers), 200)
        assert voided["status"] == "VOIDED"
        after = get_loan(loan["id"])
        assert after["escrow_balance_cents"] == 200_000
        assert after["escrow_monthly_cents"] == 30_000


class TestEscrowStateAndStructureGates:
    def test_apply_requires_draft_state(self, api, ops_headers):
        """PRD §3.11: "Applying from any other state is rejected with
        `ERR_ANALYSIS_NOT_DRAFT`."

        Design: Corner/state_machines/escrow_apply_requires_draft_state
        """
        borrower = make_borrower(full_name="Opal O", email="opal@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-SM7", 200_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        get_success_data(api.apply_escrow_analysis(analysis["id"], ops_headers))
        res = api.apply_escrow_analysis(analysis["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_ANALYSIS_NOT_DRAFT, expected_status=409)
        assert get_loan(loan["id"])["escrow_balance_cents"] == 70_000

    def test_void_blocked_when_later_analysis_applied(self, api, ops_headers):
        """PRD §3.11: "A void is blocked when a later `APPLIED`, non-`VOIDED`
        analysis exists for the same loan — rejected with
        `ERR_ANALYSIS_VOID_BLOCKED`."

        Design: Corner/validations/escrow_void_blocked_when_later_analysis_applied
        """
        borrower = make_borrower(full_name="Tess T", email="tess@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-VAL7", 30_000)
        a1 = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        get_success_data(api.apply_escrow_analysis(a1["id"], ops_headers))
        a2 = get_success_data(
            api.create_escrow_analysis(
                loan["id"],
                create_escrow_analysis_payload(
                    comp_year_start_month="2027-08",
                    projected_annual_disbursements_cents=480_000,
                ),
                ops_headers,
            )
        )
        get_success_data(api.apply_escrow_analysis(a2["id"], ops_headers))

        res = api.void_escrow_analysis(a1["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_ANALYSIS_VOID_BLOCKED, expected_status=409)

        # Voiding the LATER analysis first succeeds and restores the monthly
        # escrow it overwrote (38333 from the first apply).
        voided = validate_success(api.void_escrow_analysis(a2["id"], ops_headers), 200)
        assert voided["status"] == "VOIDED"
        assert get_loan(loan["id"])["escrow_monthly_cents"] == 38_333

    def test_invalid_comp_year_months_rejected(self, api, ops_headers):
        """PRD §3.11: "For `STANDARD_ANNUAL`, `comp_year_months` must equal 12;
        for `POST_MODIFICATION` it must lie in 1–12 — any other combination is
        rejected with `ERR_INVALID_COMP_MONTHS`."

        Design: Corner/validations/invalid_comp_year_months_rejected
        """
        borrower = make_borrower(full_name="Ruth R", email="ruth@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-VAL5", 30_000)
        res1 = api.create_escrow_analysis(
            loan["id"],
            create_escrow_analysis_payload(comp_year_months=6),
            ops_headers,
        )
        validate_error(res1, ApiErrorId.ERR_INVALID_COMP_MONTHS, expected_status=422)
        res2 = api.create_escrow_analysis(
            loan["id"],
            create_escrow_analysis_payload(
                analysis_type="POST_MODIFICATION", comp_year_months=13
            ),
            ops_headers,
        )
        validate_error(res2, ApiErrorId.ERR_INVALID_COMP_MONTHS, expected_status=422)


class TestComputationWindowOverlap:
    def _loan_with_annual_window(self, api, ops_headers, name="Tara T"):
        borrower = make_borrower(full_name=name, email=f"{name.replace(' ', '.')}@x.com")
        loan = _loan_with_escrow(borrower["id"], f"LN-TO1-{name[-1]}", 30_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        return loan, analysis

    def test_intersecting_window_rejected(self, api, ops_headers):
        """PRD §3.11: "Computation windows for the same loan must not overlap:
        the new window [`comp_year_start_month`, start + `comp_year_months`) —
        half-open, so adjacent windows are allowed — is rejected with
        `ERR_ESCROW_YEAR_OVERLAP` when it intersects any non-`VOIDED`,
        non-`CANCELLED` existing analysis window for the same loan."

        Design: Difficulty/resource_temporal_overlap/escrow_year_half_open_window_overlap
        """
        loan, _a1 = self._loan_with_annual_window(api, ops_headers)
        res = api.create_escrow_analysis(
            loan["id"],
            create_escrow_analysis_payload(comp_year_start_month="2027-01"),
            ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_ESCROW_YEAR_OVERLAP, expected_status=422)

    def test_adjacent_window_allowed(self, api, ops_headers):
        """PRD §3.11: "Computation windows for the same loan must not overlap:
        the new window [`comp_year_start_month`, start + `comp_year_months`) —
        half-open, so adjacent windows are allowed — is rejected with
        `ERR_ESCROW_YEAR_OVERLAP` when it intersects any non-`VOIDED`,
        non-`CANCELLED` existing analysis window for the same loan."

        Design: Difficulty/resource_temporal_overlap/escrow_year_half_open_window_overlap
        """
        loan, _a1 = self._loan_with_annual_window(api, ops_headers, name="Tara T2")
        # [2026-08, +12) ends at 2027-08; a window starting exactly there only
        # touches the boundary (half-open), so it does not intersect.
        created = validate_success(
            api.create_escrow_analysis(
                loan["id"],
                create_escrow_analysis_payload(
                    comp_year_start_month="2027-08",
                    projected_annual_disbursements_cents=430_000,
                ),
                ops_headers,
            ),
            201,
        )
        assert created["status"] == "DRAFT"


class TestEscrowRbac:
    def test_foreclosure_counsel_cannot_apply(self, api, ops_headers, counsel_headers):
        """PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: POST /escrow-analyses/{id}/apply — "ServicingOps".

        Design: Corner/rbac/foreclosure_counsel_cannot_apply_escrow_analysis
        """
        borrower = make_borrower(full_name="Gia G", email="gia@x.com")
        loan = _loan_with_escrow(borrower["id"], "LN-RBAC6", 30_000)
        analysis = get_success_data(
            api.create_escrow_analysis(
                loan["id"], create_escrow_analysis_payload(), ops_headers
            )
        )
        res = api.apply_escrow_analysis(analysis["id"], counsel_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert get_escrow_analysis(analysis["id"])["status"] == "DRAFT"
