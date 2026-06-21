"""Combinatorial formulas across different modes.

Tests the creditor-payment waterfall's non-linear interaction across
priority class, ordering, and remaining capacity; and the intestacy
remainder allocation's pinned created_at-ascending order.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    bootstrap_administration_with_n_claims,
    bootstrap_intestacy_setup,
    make_executor_headers,
    make_judge_headers,
)


class TestWaterfallPriorityMarginalResidualPay:
    """PRD §3.6: priority order SECURED > ADMIN > FUNERAL > TAX > UNSECURED;
    marginal claim takes the residual; later siblings/classes get nothing."""

    def test_waterfall_three_classes_marginal_admin_residual(self, api):
        """PRD §3.6: "it walks the classes in the fixed statutory priority
        order — SECURED first, then ADMIN, then FUNERAL, then TAX, and
        UNSECURED last — and within each class iterates the allowed claims
        in ascending created_at order with amount_cents ascending as the
        tiebreaker. For every allowed claim earlier in the walk than the
        target, the walk simulates consumption: it subtracts the smaller of
        the remaining pool and that claim's amount_cents from the pool"

        Design: Difficulty/combinatorial_formula/waterfall_priority_with_residual_marginal_pay
        """
        ctx = bootstrap_administration_with_n_claims(
            claim_specs=[
                {"creditor_name": "Sec1", "amount_cents": 400000,
                 "claim_class": "SECURED", "filed_at": "2026-02-01T00:00:00Z"},
                {"creditor_name": "Adm1", "amount_cents": 700000,
                 "claim_class": "ADMIN", "filed_at": "2026-02-02T00:00:00Z"},
                {"creditor_name": "Unsec1", "amount_cents": 200000,
                 "claim_class": "UNSECURED", "filed_at": "2026-02-03T00:00:00Z"},
            ],
            gross_asset_value_cents=1000000,
            domicile_state_code="TX",
        )
        exec_id = ctx["executor"]["id"]
        sec, adm, unsec = ctx["claims"]

        # SECURED Sec1 takes 400_000 → remaining = 600_000.
        resp_sec = api.pay_creditor_claim(sec["id"], make_executor_headers(exec_id))
        data_sec = validate_success(resp_sec, expected_status=200)
        assert data_sec["paid_amount_cents"] == 400000
        assert data_sec["status"] == "PAID"

        # ADMIN Adm1 amount 700_000 > 600_000 → paid 600_000 (marginal residual).
        resp_adm = api.pay_creditor_claim(adm["id"], make_executor_headers(exec_id))
        data_adm = validate_success(resp_adm, expected_status=200)
        assert data_adm["paid_amount_cents"] == 600000
        assert data_adm["status"] == "PAID"

    def test_waterfall_unsecured_after_pool_exhausted_rejects(self, api):
        """PRD §3.6: "If the pool is zero or negative at that point — meaning
        every earlier-priority allowed claim has notionally consumed the full
        estate — the payment is rejected with ERR_INSUFFICIENT_ESTATE_FUNDS;
        the target's paid_amount_cents stays at zero and its status stays
        ALLOWED."

        Design: Difficulty/combinatorial_formula/waterfall_priority_with_residual_marginal_pay
        """
        ctx = bootstrap_administration_with_n_claims(
            claim_specs=[
                {"creditor_name": "Sec1", "amount_cents": 400000,
                 "claim_class": "SECURED", "filed_at": "2026-02-01T00:00:00Z"},
                {"creditor_name": "Adm1", "amount_cents": 700000,
                 "claim_class": "ADMIN", "filed_at": "2026-02-02T00:00:00Z"},
                {"creditor_name": "Unsec1", "amount_cents": 200000,
                 "claim_class": "UNSECURED", "filed_at": "2026-02-03T00:00:00Z"},
            ],
            gross_asset_value_cents=1000000,
            domicile_state_code="TX",
        )
        exec_id = ctx["executor"]["id"]
        sec, adm, unsec = ctx["claims"]
        # Pay SEC and ADM first (consuming the entire pool).
        api.pay_creditor_claim(sec["id"], make_executor_headers(exec_id))
        api.pay_creditor_claim(adm["id"], make_executor_headers(exec_id))
        # Now Unsec1: earlier priority has fully consumed; remaining = 0.
        resp = api.pay_creditor_claim(unsec["id"], make_executor_headers(exec_id))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESTATE_FUNDS)
        # Verify the target's status stays ALLOWED and paid_amount_cents=0.
        get_resp = api.get_creditor_claim(
            unsec["id"], make_executor_headers(exec_id),
        )
        get_data = validate_success(get_resp, expected_status=200)
        assert get_data["status"] == "ALLOWED"
        assert get_data["paid_amount_cents"] == 0


class TestIntestacyRemainderPinnedOrder:
    """PRD §3.7: intestacy class pool divided evenly; remainder allocated
    one bp at a time in created_at ASC order so per-class pool sums exactly
    and total sums to 10000."""

    def test_three_children_remainder_distributed_by_created_at(self, api):
        """PRD §3.7: "Within a class, the pool is divided evenly across the
        class's members: each member receives floor(pool / count) basis
        points and any remainder of pool % count is allocated one basis point
        at a time to members in created_at ascending order. The result is a
        map from designation id to assigned basis points, plus the total
        assigned (always exactly 10000)."

        Design: Difficulty/combinatorial_formula/intestacy_remainder_rounding_pinned_order
        """
        ctx = bootstrap_intestacy_setup(
            clock="2026-01-01T00:00:00Z",
            domicile_state_code="CA",
            spouse_count=1,
            child_count=3,
        )
        spouse = ctx["spouses"][0]
        child_a, child_b, child_c = ctx["children"]

        resp = api.compute_intestacy_shares(
            ctx["estate"]["id"], make_judge_headers(),
        )
        data = validate_success(resp, expected_status=200)
        shares = data["shares"]
        assert data["total_bp_assigned"] == 10000
        # CA: spouse_first_bp=5000, child_pool_bp=5000.
        assert shares[spouse["id"]] == 5000, (
            f"Spouse should receive 5000bp, got {shares[spouse['id']]}"
        )
        # Three children split 5000: floor(5000/3)=1666; remainder=2.
        # First two children (by created_at ASC) get +1: 1667, 1667, 1666.
        assert shares[child_a["id"]] == 1667, (
            f"Child A (earliest) should receive 1667bp, got {shares[child_a['id']]}"
        )
        assert shares[child_b["id"]] == 1667, (
            f"Child B (middle) should receive 1667bp, got {shares[child_b['id']]}"
        )
        assert shares[child_c["id"]] == 1666, (
            f"Child C (latest) should receive 1666bp, got {shares[child_c['id']]}"
        )

    def test_intestacy_total_always_10000(self, api):
        """PRD §3.7: "plus the total assigned (always exactly 10000)."

        Design: Difficulty/combinatorial_formula/intestacy_remainder_rounding_pinned_order
        """
        ctx = bootstrap_intestacy_setup(
            clock="2026-01-01T00:00:00Z",
            domicile_state_code="CA",
            spouse_count=1,
            child_count=3,
        )
        resp = api.compute_intestacy_shares(
            ctx["estate"]["id"], make_judge_headers(),
        )
        data = validate_success(resp, expected_status=200)
        assert data["total_bp_assigned"] == 10000
        assert sum(data["shares"].values()) == 10000, (
            f"Sum of shares must equal 10000, got {sum(data['shares'].values())}"
        )
