"""Bills, tiered fee, settlement, payments, dispute lifecycle.

PRD references:
  - §3.6 Bills, Tiered Pricing, and Settlement
  - §2.10 Concurrency: tenant dispute racing payment
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_days,
    add_hours,
    advance_clock,
    assert_water_bill,
    create_water_bill_payload,
    DEFAULT_NOW_ISO,
    drive_command_to_executed,
    find_line_items,
    make_tenant_headers,
    payment_payload,
    setup_billing_period_with_quota,
    setup_full_active_scenario,
    setup_issued_bill_with_payment,
    setup_with_executed_volume_at_hours,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §3.6 — Bill period validation
# ===========================================================================
class TestBillPeriodValidation:
    def test_bill_period_end_le_start_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'The bill's period_end must be strictly greater
        than its period_start ... failure of either check yields
        ERR_BILL_PERIOD_INVALID (422).'

        Claim: period_end == period_start → ERR_BILL_PERIOD_INVALID.
        """
        ctx = setup_billing_period_with_quota()
        same = ctx["quota"]["period_start"]
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=same,
                period_end=same,
            ),
            water_admin_headers,
        )
        validate_error(res, "ERR_BILL_PERIOD_INVALID")

    def test_bill_period_misaligned_to_quota_period_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'the period_start must align to a period_start
        of a WaterQuota for the same plot; failure of either check
        yields ERR_BILL_PERIOD_INVALID (422).'

        Claim: period_start that does not match any quota.period_start
        on the plot → ERR_BILL_PERIOD_INVALID.
        """
        ctx = setup_billing_period_with_quota()
        wrong = add_hours(ctx["quota"]["period_start"], 1)
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=wrong,
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        validate_error(res, "ERR_BILL_PERIOD_INVALID")


# ===========================================================================
# §3.6 — Tiered fee + per-line rounding
# ===========================================================================
class TestTieredFee:
    def test_partition_into_peak_and_offpeak_within_tier1(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'For every ControlCommand whose status is
        EXECUTED and whose feedback_received_at lies within the bill's
        [period_start, period_end) interval, the command's
        actual_volume_liters is added to peak_liters if the
        hour-of-day component of feedback_received_at is in the set
        of peak hours {6, 7, 8, 9, 18, 19, 20, 21}, and otherwise to
        offpeak_liters.'
        PRD §3.6: 'For peak consumption the tiers are: liters from
        zero up to (but not including) one hundred thousand at thirty
        cents per liter ... For off-peak consumption the tiers are:
        liters from zero up to (but not including) one hundred
        thousand at eighteen cents per liter'.

        Recipe: 50000 L at hour=7 (peak), 100000 L at hour=14 (offpeak)
        — both stay inside tier 1.
          peak line:   50000 * 30  = 1500000
          offpeak line:100000 * 18 = 1800000
          total = 3300000
        """
        ctx = setup_with_executed_volume_at_hours(
            consumption_pairs=[(50000.0, 7), (100000.0, 14)],
            allocated_liters=10_000_000.0,
        )
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=ctx["quota"]["period_start"],
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        bill = validate_success(res, expected_status=201)
        assert_water_bill(bill)
        assert bill["peak_liters"] == pytest.approx(50000.0, abs=0.01)
        assert bill["offpeak_liters"] == pytest.approx(100000.0, abs=0.01)
        peak_lines = find_line_items(bill["line_items"], window="peak")
        offpeak_lines = find_line_items(
            bill["line_items"], window="offpeak"
        )
        assert len(peak_lines) >= 1
        assert len(offpeak_lines) >= 1
        peak_amt = sum(li["amount_cents"] for li in peak_lines)
        offpeak_amt = sum(li["amount_cents"] for li in offpeak_lines)
        assert peak_amt == 1_500_000, (
            f"Expected peak amount 1500000 cents, got {peak_amt}"
        )
        assert offpeak_amt == 1_800_000, (
            f"Expected offpeak amount 1800000 cents, got {offpeak_amt}"
        )

    def test_per_line_rounding_pinned_order(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'Each tier slab is appended to line_items with
        the tier index, the window (peak or off-peak), the slab
        quantity, the rate, and an amount_cents field equal to the
        tier amount rounded half-up to whole cents — this per-line
        rounding order is pinned'.

        Claim: each line_items[i].amount_cents is a non-negative
        integer (i.e., already rounded to whole cents per line).
        """
        ctx = setup_with_executed_volume_at_hours(
            consumption_pairs=[(50000.0, 7)],
            allocated_liters=10_000_000.0,
        )
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=ctx["quota"]["period_start"],
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        bill = validate_success(res, expected_status=201)
        for li in bill["line_items"]:
            assert isinstance(li["amount_cents"], int), (
                f"line_item.amount_cents must be integer cents, got "
                f"{type(li['amount_cents'])} {li['amount_cents']!r}"
            )
            assert li["amount_cents"] >= 0


# ===========================================================================
# §3.6 — Bill issue / payment / paid transitions
# ===========================================================================
class TestBillIssuePay:
    def test_issue_draft_bill_to_issued(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'Once a WaterAdmin issues a draft bill, it
        transitions from DRAFT to ISSUED, the line_items are pinned,
        and the total_amount_cents is locked.'

        Claim: POST /issue on a DRAFT bill → ISSUED.
        """
        ctx = setup_with_executed_volume_at_hours(
            consumption_pairs=[(50000.0, 7)],
            allocated_liters=10_000_000.0,
        )
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=ctx["quota"]["period_start"],
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        bill = validate_success(res, expected_status=201)
        assert bill["status"] == "DRAFT"
        res = api.issue_bill(bill["id"], water_admin_headers)
        issued = validate_success(res, expected_status=200)
        assert issued["status"] == "ISSUED"

    def test_payment_meeting_total_advances_to_paid(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'on every payment, amount_paid_cents is
        incremented by amount_cents, and once amount_paid_cents is at
        least total_amount_cents, status advances from ISSUED to
        PAID.'

        Claim: payment that brings amount_paid_cents to >=
        total_amount_cents → status advances to PAID.
        """
        ctx = setup_issued_bill_with_payment(
            bill_total_floor_cents=10000,
            partial_payment_cents=1000,
        )
        bill = ctx["bill"]
        # Compute remaining and pay it.
        remaining = bill["total_amount_cents"] - bill["amount_paid_cents"]
        assert remaining > 0
        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        res = api.pay_bill(
            bill["id"],
            payment_payload(amount_cents=remaining),
            tenant_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["amount_paid_cents"] >= data["total_amount_cents"]
        assert data["status"] == "PAID"


# ===========================================================================
# §3.6 — Dispute lifecycle (cycle ISSUED → DISPUTED → ISSUED on REJECT)
# ===========================================================================
class TestDisputeLifecycle:
    def test_dispute_issued_bill(self, api):
        """PRD §3.6: 'A Tenant may dispute an ISSUED bill by supplying
        a non-empty dispute_reason, which advances status from ISSUED
        to DISPUTED and stores the reason in dispute_reason.'

        Claim: POST /dispute on ISSUED → DISPUTED.
        """
        ctx = setup_issued_bill_with_payment(
            bill_total_floor_cents=10000,
            partial_payment_cents=1000,
        )
        bill = ctx["bill"]
        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        res = api.dispute_bill(
            bill["id"],
            {"dispute_reason": "billed too much"},
            tenant_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DISPUTED"
        assert data["dispute_reason"] == "billed too much"

    def test_dispute_resolve_reject_cycles_back_to_issued(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'a REJECT outcome advances status from DISPUTED
        back to ISSUED (a deliberate cycle)'.

        Claim: POST /dispute-resolve {outcome: REJECT} on DISPUTED →
        status==ISSUED.
        """
        ctx = setup_issued_bill_with_payment(
            bill_total_floor_cents=10000,
            partial_payment_cents=1000,
        )
        bill = ctx["bill"]
        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        api.dispute_bill(
            bill["id"], {"dispute_reason": "x"}, tenant_headers
        )
        res = api.resolve_bill_dispute(
            bill["id"], {"outcome": "REJECT"}, water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ISSUED"

    def test_dispute_resolve_accept_cancels_and_zeros_total(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'an ACCEPT outcome advances status from DISPUTED
        to CANCELLED and forces total_amount_cents to zero (preserving
        any non-zero amount_paid_cents, so the balance due may be
        negative, surfacing a refund obligation).'

        Claim: POST /dispute-resolve {outcome: ACCEPT} on DISPUTED →
        status==CANCELLED, total_amount_cents==0, amount_paid_cents
        unchanged.
        """
        ctx = setup_issued_bill_with_payment(
            bill_total_floor_cents=10000,
            partial_payment_cents=1000,
        )
        bill = ctx["bill"]
        original_paid = bill["amount_paid_cents"]
        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        api.dispute_bill(
            bill["id"], {"dispute_reason": "x"}, tenant_headers
        )
        res = api.resolve_bill_dispute(
            bill["id"], {"outcome": "ACCEPT"}, water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CANCELLED"
        assert data["total_amount_cents"] == 0
        assert data["amount_paid_cents"] == original_paid, (
            "PRD §3.6: 'preserving any non-zero amount_paid_cents, so "
            "the balance due may be negative'"
        )
