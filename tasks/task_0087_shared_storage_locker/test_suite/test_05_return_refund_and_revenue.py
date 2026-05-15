"""Return, refund, and revenue reconciliation tests (PRD §3.6, §2.12)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    drive_claim_to_denied,
    file_insurance_claim,
    iso_utc,
    make_renter_headers,
    refund_rental_payload,
    return_rental_as_owner,
    return_rental_payload,
    run_sweep,
    setup_basic_rental,
    setup_overdue_rental,
    setup_returned_rental,
    setup_returned_rental_with_insurance_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Return — happy path (PRD §3.6)
# ===========================================================================
class TestReturnHappyPath:

    def test_return_active_rental_moves_to_returned(self, api):
        """PRD §3.6: "On success the rental's status becomes RETURNED,
        ended_at is set to the transition time, the compartment's
        occupancy_status cascades to IDLE."

        Claim: returning an ACTIVE rental sets status=RETURNED,
        ended_at set, compartment occupancy_status=IDLE.
        """
        ctx = setup_basic_rental()
        returned = return_rental_as_owner(ctx["rental"], ctx["renter_id"])
        assert returned["status"] == "RETURNED"
        assert returned["ended_at"] is not None

    def test_return_cascades_compartment_to_idle(self, api, operator_headers):
        """PRD §3.6: "the compartment's occupancy_status cascades to IDLE,
        the compartment's active_rental_id is cleared."

        Claim: after return the compartment is IDLE with null active_rental_id.
        """
        ctx = setup_basic_rental()
        return_rental_as_owner(ctx["rental"], ctx["renter_id"])
        comp = validate_success(api.get_compartment(
            ctx["cabinet"]["id"], ctx["compartment"]["id"], operator_headers,
        ))
        assert comp["occupancy_status"] == "IDLE"
        assert comp.get("active_rental_id") in (None,)

    def test_returning_already_terminated_rejected(self, api):
        """PRD §3.6: "a return against RETURNED, FORCE_CLEARED, or
        REFUNDED is rejected with ERR_INVALID_STATE."

        Claim: returning a RETURNED rental → ERR_INVALID_STATE.
        """
        ctx = setup_returned_rental(renter_id="renter-already-returned")
        resp = api.return_rental(
            ctx["rental"]["id"], return_rental_payload(),
            make_renter_headers(ctx["renter_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Deposit settlement on return (PRD §3.6, §1.3 deposit_settlement)
# ===========================================================================
class TestDepositSettlementOnReturn:

    def test_full_deposit_refunded_when_no_overdue(self, api):
        """PRD §3.6: "if overdue_fee_cents (final-settled at ended_at) is
        at most deposit_cents_snapshot, then deposit_refunded_cents is
        deposit_cents_snapshot minus overdue_fee_cents and
        deposit_forfeited_cents is zero."

        Claim: returning an ACTIVE rental with overdue_fee_cents=0
        yields deposit_refunded_cents == deposit_cents_snapshot and
        deposit_forfeited_cents == 0.
        """
        ctx = setup_basic_rental()
        returned = return_rental_as_owner(ctx["rental"], ctx["renter_id"])
        assert returned["overdue_fee_cents"] == 0
        assert returned["deposit_refunded_cents"] == returned["deposit_cents_snapshot"]
        assert returned["deposit_forfeited_cents"] == 0


# ===========================================================================
# Refund — happy path and ordering (PRD §3.6)
# ===========================================================================
class TestRefundHappyPath:

    def test_refund_returned_rental_moves_to_refunded(self, api,
                                                     operator_headers):
        """PRD §3.6: "On success the rental's status advances to
        REFUNDED, a REFUND_REVERSAL RevenueRecord row is emitted whose
        gross_cents is the negative of the sum of all prior RENTAL_FEE
        and OVERDUE_FEE gross_cents for this rental."

        Claim: refunding a RETURNED rental sets status=REFUNDED.
        """
        ctx = setup_returned_rental()
        resp = api.refund_rental(
            ctx["rental"]["id"], refund_rental_payload(),
            operator_headers,
        )
        refunded = validate_success(resp)
        assert refunded["status"] == "REFUNDED"

    def test_refund_emits_refund_reversal_revenue_record(self, api,
                                                       operator_headers):
        """PRD §3.6: "a REFUND_REVERSAL RevenueRecord row is emitted
        whose gross_cents is the negative of the sum of all prior
        RENTAL_FEE and OVERDUE_FEE gross_cents for this rental."

        Claim: after refund, one REFUND_REVERSAL row exists with
        gross_cents == -(sum of RENTAL_FEE+OVERDUE_FEE gross_cents).
        """
        ctx = setup_returned_rental()
        api.refund_rental(ctx["rental"]["id"], refund_rental_payload(),
                          operator_headers)
        rows = api.list_revenue_records(operator_headers, params={
            "cabinet_id": ctx["cabinet"]["id"],
        }).json()["data"]
        rental_rows = [r for r in rows if r["rental_id"] == ctx["rental"]["id"]]
        reversal = [r for r in rental_rows if r["revenue_kind"] == "REFUND_REVERSAL"]
        assert len(reversal) >= 1, "Expected at least one REFUND_REVERSAL row"
        prior = [r for r in rental_rows
                 if r["revenue_kind"] in ("RENTAL_FEE", "OVERDUE_FEE")]
        prior_sum = sum(r["gross_cents"] for r in prior)
        rev_sum = sum(r["gross_cents"] for r in reversal)
        assert rev_sum == -prior_sum, (
            f"REFUND_REVERSAL sum {rev_sum} must equal -prior_sum={-prior_sum}"
        )


# ===========================================================================
# Refund blocked by open / paid insurance claim (PRD §3.6)
# ===========================================================================
class TestRefundBlockedByClaim:

    def test_refund_blocked_when_claim_in_reported(self, api,
                                                  operator_headers):
        """PRD §3.6: "the system must observe no InsuranceClaim against
        this rental in status REPORTED, EVIDENCE_PENDING, UNDER_REVIEW,
        EVIDENCE_REJECTED, APPROVED, or PAID ... A refund against a
        rental with an active or paid claim is rejected with
        ERR_REFUND_BLOCKED_BY_CLAIM."

        Claim: refunding a rental that has a REPORTED claim →
        ERR_REFUND_BLOCKED_BY_CLAIM.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC",
            renter_id="renter-claim-block",
        )
        assert ctx["claim"]["status"] == "REPORTED"
        resp = api.refund_rental(
            ctx["rental"]["id"], refund_rental_payload(),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_BLOCKED_BY_CLAIM.value)

    def test_refund_allowed_after_claim_denied(self, api, operator_headers):
        """PRD §3.6: "the only acceptable state of an existing claim is
        DENIED, and the absence of any claim is also acceptable."

        Claim: refunding a rental whose claim is DENIED → success.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC",
            renter_id="renter-claim-denied",
        )
        # Walk REPORTED → EVIDENCE_PENDING → submit → UNDER_REVIEW → deny.
        denied = drive_claim_to_denied(ctx["claim"], ctx["renter_id"])
        assert denied["status"] == "DENIED"
        resp = api.refund_rental(
            ctx["rental"]["id"], refund_rental_payload(),
            operator_headers,
        )
        refunded = validate_success(resp)
        assert refunded["status"] == "REFUNDED"


# ===========================================================================
# Revenue records — flat list filters (PRD §3.6)
# ===========================================================================
class TestRevenueRecordsList:

    def test_filter_by_revenue_kind(self, api, operator_headers):
        """PRD §3.6: "A flat list is available for filtering across
        cabinets, revenue kinds, and time windows."

        Claim: filtering by revenue_kind=RENTAL_FEE yields only
        RENTAL_FEE rows.
        """
        ctx = setup_returned_rental()
        rows = api.list_revenue_records(operator_headers, params={
            "cabinet_id": ctx["cabinet"]["id"],
            "revenue_kind": "RENTAL_FEE",
        }).json()["data"]
        # Filter rows belonging to this cabinet — implementations may include
        # cross-cabinet rows otherwise.
        rows = [r for r in rows if r["cabinet_id"] == ctx["cabinet"]["id"]]
        assert len(rows) >= 1
        assert all(r["revenue_kind"] == "RENTAL_FEE" for r in rows)


# ===========================================================================
# Revenue summary aggregate (PRD §3.6, §1.3 revenue_share_split per-period)
# ===========================================================================
class TestRevenueSummaryAggregate:

    def test_revenue_summary_uses_per_period_aggregate(self, api,
                                                      operator_headers):
        """PRD §3.6: "the summary first sums gross_cents across the
        period, then computes the aggregate partner share as that sum
        multiplied by partner_share_pct divided by 100 and rounded
        half-up, then derives the aggregate platform share as the period
        total minus the aggregate partner share. This per-period
        aggregate variant of the partner split differs from the per-row
        variant ... The summary endpoint MUST report the per-period
        aggregate."

        Claim: 3 rows of gross=15 with partner_share_pct=30 yield
        per-row partner sum=15, but the summary endpoint reports
        total_partner_cents=14 (per-period: round_half_up(45*0.30)=
        round_half_up(13.5)=14) and total_platform_cents=31.

        # difficulty: dual_variant_calc/revenue_share_per_row_vs_per_period_on_revenuerecord
        """
        from test_helpers import (
            create_active_rental,
            return_rental_as_owner,
            setup_cabinet_with_n_small_compartments,
        )
        cabinet, comps, _ = setup_cabinet_with_n_small_compartments(
            3, rental_mode="DAILY",
            cabinet_overrides={"partner_share_pct": 30},
            pricing_overrides={
                "unit_price_cents": 15,
                "deposit_cents": 0,
                "grace_minutes": 15,
                "overdue_rate_cents_per_hour": 0,
                "forced_clearance_hours": 48,
            },
        )
        for i, comp in enumerate(comps):
            rental, renter_id = create_active_rental(
                cabinet["id"], comp["id"],
                renter_id=f"renter-rev-{i}",
                rental_mode="DAILY",
                billing_units=1,
                unlock_channel="QR",
            )
            return_rental_as_owner(rental, renter_id)

        # Per-row variant: sum of partner shares from /revenue-records
        rows = api.list_revenue_records(operator_headers, params={
            "cabinet_id": cabinet["id"],
            "revenue_kind": "RENTAL_FEE",
        }).json()["data"]
        # Restrict to our cabinet.
        rental_fee_rows = [r for r in rows if r["cabinet_id"] == cabinet["id"]
                           and r["revenue_kind"] == "RENTAL_FEE"
                           and r["gross_cents"] == 15]
        assert len(rental_fee_rows) >= 3
        per_row_partner_sum = sum(r["partner_share_cents"] for r in rental_fee_rows[:3])
        # Per-row: 4.5 rounds half-up to 5; 5*3 = 15.
        assert per_row_partner_sum == 15, (
            f"per-row sum of partner_share_cents should be 15, got "
            f"{per_row_partner_sum}"
        )

        # Per-period aggregate: round_half_up(45 * 0.30) = round_half_up(13.5) = 14
        summary = validate_success(api.get_revenue_summary(
            cabinet["id"], operator_headers,
        ))
        assert summary["total_gross_cents"] == 45, (
            f"summary total_gross_cents should be 45, got "
            f"{summary['total_gross_cents']}"
        )
        assert summary["total_partner_cents"] == 14, (
            f"per_period_aggregate variant: round_half_up(13.5) = 14, got "
            f"{summary['total_partner_cents']}"
        )
        assert summary["total_platform_cents"] == 31, (
            f"per_period_aggregate platform: 45-14=31, got "
            f"{summary['total_platform_cents']}"
        )


# ===========================================================================
# Per-row partner residual invariant (PRD §2.12)
# ===========================================================================
class TestPerRowPartnerResidual:

    def test_partner_plus_platform_equals_gross_for_every_row(self, api,
                                                              operator_headers):
        """PRD §2.12: "Each RevenueRecord row stores gross_cents,
        partner_share_cents, and platform_share_cents; the row-level
        split rounds the partner share half-up and assigns the residual
        to the platform so that the two always sum to gross_cents,
        including for negative-gross_cents refund reversal rows."

        Claim: every emitted row (including REFUND_REVERSAL) satisfies
        partner + platform == gross.
        """
        ctx = setup_returned_rental()
        api.refund_rental(ctx["rental"]["id"], refund_rental_payload(),
                          operator_headers)
        rows = api.list_revenue_records(operator_headers, params={
            "cabinet_id": ctx["cabinet"]["id"],
        }).json()["data"]
        for r in rows:
            assert r["partner_share_cents"] + r["platform_share_cents"] == r["gross_cents"], (
                f"Row {r['id']}: partner={r['partner_share_cents']} + "
                f"platform={r['platform_share_cents']} != "
                f"gross={r['gross_cents']}"
            )
