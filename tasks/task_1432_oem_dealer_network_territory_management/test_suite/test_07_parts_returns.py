"""Parts returns: per-line credit rounding, allowance gate, stocking gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_parts_return,
    create_parts_return,
    decide_parts_return,
    get_parts_return,
    make_dealer_user_headers,
    record_parts_purchase,
    set_clock,
    setup_active_dealer,
    setup_dealer_return_ready,
    submit_parts_return,
    validate_error,
)


class TestPerLineRounding:
    """Return credit rounds each line half-up first, then sums."""

    def _setup_two_penny_lines(self, api):
        # Default clock 2026-08-01 falls after June 30 of 2026, so the
        # 15 percent restocking deduction applies.
        ctx = setup_dealer_return_ready(
            "DL-D1", purchases_cents=10000, min_stock_value_cents=1000,
            observed_stock_value_cents=1500)
        parts_return = create_parts_return(
            ctx["dealer"]["id"], return_year=2026,
            lines=[
                {"part_number": "P1", "quantity": 1, "unit_credit_cents": 2},
                {"part_number": "P2", "quantity": 1, "unit_credit_cents": 2},
            ])
        return ctx, parts_return

    def test_return_credit_rounds_per_line_then_sums(
            self, api, oem_admin_headers):
        """PRD section 3.6: "The draft is created in `DRAFT` status with a **previewed** credit: the system computes each line's credit as the `quantity` times the `unit_credit_cents`, reduced by a 15 percent restocking deduction when the current logical date falls after June 30 of the `return_year` (the `restock_pct_applied` is 0.15 in that case and 0 otherwise), rounds each line's credit half-up to a whole cent, and sums the per-line rounded credits into `credit_cents`. The rounding order is pinned: round per line first, then sum — summing first and rounding once is not permitted."

        Design: Difficulty/combinatorial_formula/parts_return_credit_per_line_rounding
        """
        ctx, parts_return = self._setup_two_penny_lines(api)

        submitted = submit_parts_return(parts_return["id"],
                                        ctx["dealer"]["id"])
        # Per line: round_half_up(1 * 2 * (1 - 0.15)) = round_half_up(1.7) = 2;
        # total = 2 + 2 = 4. Sum-then-round would give round(3.4) = 3.
        assert submitted["credit_cents"] == 4, (
            "per-line round-then-sum must yield 4, got "
            f"{submitted['credit_cents']}"
        )
        assert submitted["restock_pct_applied"] == pytest.approx(0.15)

    def test_credited_return_keeps_recomputed_credit(
            self, api, oem_admin_headers):
        """PRD section 3.6: "Because the previewed credit may be stale by submission time, `credit_cents` and `restock_pct_applied` are recomputed against the submit date as part of the submit, and it is the recomputed `credit_cents` that the allowance check consumes. A successful submission moves the return to `SUBMITTED`."
        PRD section 3.6: "From there, `OemSalesOps` records a `decision` on the return: `CREDIT` moves it to `CREDITED`, `REJECT` moves it to `REJECTED`, and either `decision` requires the return to be `SUBMITTED` (`ERR_RETURN_INVALID_STATE`); the payload may carry an optional `reason`."

        Design: Difficulty/combinatorial_formula/parts_return_credit_per_line_rounding
        """
        ctx, parts_return = self._setup_two_penny_lines(api)

        submit_parts_return(parts_return["id"], ctx["dealer"]["id"])
        credited = decide_parts_return(parts_return["id"], "CREDIT")
        assert_parts_return(credited)
        assert credited["status"] == "CREDITED"
        assert credited["credit_cents"] == 4
        assert credited["restock_pct_applied"] == pytest.approx(0.15)


class TestAllowanceBoundary:
    """The annual allowance is five percent of parts purchases, and the
    used + this-credit comparison admits exact equality."""

    def test_parts_allowance_exact_equality_and_overflow(self, api):
        """PRD section 3.6: "And the return must fit within the dealer's **annual return allowance**: the allowance for the year is five percent of the dealer's `parts_purchases_ytd_cents`, rounded half-up to a whole cent; the amount already used is the sum of `credit_cents` over the dealer's other returns with the same `return_year` in `SUBMITTED` or `CREDITED` status; and the submission is allowed only when the used amount plus this return's `credit_cents` is less than or equal to the allowance — equality is allowed — otherwise `ERR_ALLOWANCE_EXCEEDED`."

        Design: Corner/calculations/parts_allowance_exact_equality_and_overflow
        """
        # Before June 30 there is no restocking deduction.
        set_clock("2026-03-01T00:00:00Z")
        ctx = setup_dealer_return_ready(
            "DL-CC4", purchases_cents=10000, min_stock_value_cents=1000,
            observed_stock_value_cents=1500)
        dealer_id = ctx["dealer"]["id"]

        # Allowance is 5% of 10000 = 500; this return consumes it exactly.
        first = create_parts_return(
            dealer_id, return_year=2026,
            lines=[{"part_number": "P1", "quantity": 1,
                    "unit_credit_cents": 500}])
        submitted1 = submit_parts_return(first["id"], dealer_id)
        assert submitted1["credit_cents"] == 500
        assert submitted1["restock_pct_applied"] == 0
        credited = decide_parts_return(first["id"], "CREDIT")
        assert credited["status"] == "CREDITED", (
            "credit exactly equal to the 500-cent allowance is allowed"
        )

        second = create_parts_return(
            dealer_id, return_year=2026,
            lines=[{"part_number": "P2", "quantity": 1,
                    "unit_credit_cents": 100}])
        resp = api.submit_parts_return(
            second["id"], make_dealer_user_headers(dealer_id))
        validate_error(resp, ApiErrorId.ERR_ALLOWANCE_EXCEEDED)
        assert resp.status_code == 402, (
            "500 used + 100 new exceeds the 500-cent allowance"
        )

        unchanged = get_parts_return(second["id"])
        assert unchanged["status"] == "DRAFT"


class TestReturnGatesAndStates:

    def test_stocking_noncompliant_blocks_return_submit(self, api):
        """PRD section 3.6: "The dealer's `stock_compliant` flag must be true — a dealer behind on its stocking obligation cannot return parts, and the attempt is rejected with `ERR_STOCKING_NONCOMPLIANT`."

        Design: Corner/validations/stocking_noncompliant_blocks_return_submit
        """
        # No stock audit: stock_compliant stays false even though the
        # allowance (5% of 10000 = 500) would cover the credit.
        ctx = setup_active_dealer("DL-ST1", min_stock_value_cents=1000)
        dealer_id = ctx["dealer"]["id"]
        record_parts_purchase(dealer_id, 10000)
        parts_return = create_parts_return(
            dealer_id, return_year=2026,
            lines=[{"part_number": "P1", "quantity": 1,
                    "unit_credit_cents": 100}])

        resp = api.submit_parts_return(
            parts_return["id"], make_dealer_user_headers(dealer_id))
        validate_error(resp, ApiErrorId.ERR_STOCKING_NONCOMPLIANT)

        unchanged = get_parts_return(parts_return["id"])
        assert unchanged["status"] == "DRAFT"

    def test_return_decide_from_draft_rejected(self, api, sales_ops_headers):
        """PRD section 3.6: "From there, `OemSalesOps` records a `decision` on the return: `CREDIT` moves it to `CREDITED`, `REJECT` moves it to `REJECTED`, and either `decision` requires the return to be `SUBMITTED` (`ERR_RETURN_INVALID_STATE`); the payload may carry an optional `reason`."

        Design: Corner/validations/return_decide_from_draft_rejected
        """
        ctx = setup_active_dealer("DL-RD1")
        parts_return = create_parts_return(
            ctx["dealer"]["id"], return_year=2026,
            lines=[{"part_number": "P1", "quantity": 1,
                    "unit_credit_cents": 100}])

        resp = api.decide_parts_return(parts_return["id"],
                                       {"decision": "CREDIT"},
                                       sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_RETURN_INVALID_STATE)

        unchanged = get_parts_return(parts_return["id"])
        assert unchanged["status"] == "DRAFT"
