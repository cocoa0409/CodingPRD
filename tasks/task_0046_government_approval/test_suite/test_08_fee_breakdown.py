"""Fee-breakdown calculation: pinned per-line ceil ordering, surcharge
tiering, provisional vs final variant freezing.

Covers PRD §3.11 (Fee Breakdown).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CAP_SURCHARGE_CENTS,
    SURCHARGE_PER_ROUND_CENTS,
    api_client,
    decide,
    expected_admin_overhead_cents,
    expected_fee_total_cents,
    expected_handling_line_cents,
    expected_surcharge_subtotal_cents,
    get_application,
    get_success_data,
    issue_correction_for_primary_material,
    list_review_tasks,
    resubmit_primary_material,
    setup_application_at_correction_round,
    setup_application_under_review_single_dept,
    submit_application,
    setup_single_department_published_version,
    TEST_USERS,
    validate_success,
)


# Helper to extract the fee_breakdown subtree of an Application detail.
def _read_fee_breakdown(api, application_id, headers):
    """PRD §3.12: 'Reading the application detail returns the full
    Application resource ... supplemented by the SLA snapshot of §3.7
    and the fee breakdown of §3.11.'
    """
    resp = api.get_application(application_id, headers)
    data = validate_success(resp)
    breakdown = data.get("fee_breakdown")
    assert breakdown is not None, (
        "PRD §3.12: GET /applications/{id} response must include fee_breakdown"
    )
    return data, breakdown


# ===========================================================================
# Surcharge subtotal tiering (PRD §3.11)
# ===========================================================================
class TestSurchargeSubtotal:
    def test_correction_round_zero_yields_zero_surcharge(self, api):
        """PRD §3.11: "The per-correction surcharge subtotal in cents is
        0 when the application's correction_round is 0."

        Claim: with correction_round=0, surcharge_subtotal_cents == 0.
        """
        ctx = setup_application_under_review_single_dept(fee_amount_cents=1000)
        _data, breakdown = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        assert breakdown["surcharge_subtotal_cents"] == 0

    def test_correction_round_one_surcharge_500_cents(self, api):
        """PRD §3.11: "for correction_round between 1 and 2 inclusive it
        equals the per-round surcharge constant of 500 cents (i.e., 5.00
        yuan per round) multiplied by correction_round."

        Claim: with correction_round=1, surcharge_subtotal_cents == 500.
        """
        ctx = setup_application_at_correction_round(
            target_round=1,
            leave_open_at_target=True,
            fee_amount_cents=1000,
        )
        _data, breakdown = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        assert breakdown["surcharge_subtotal_cents"] == 500


# ===========================================================================
# Per-line ceil ordering (PRD §3.11)
# ===========================================================================
class TestFeeBreakdownPerLineCeil:
    def test_pinned_per_line_ceil_for_base_997_round_1(self, api):
        """PRD §3.11: "The handling line in cents equals the base fee in
        cents multiplied by the handling-rate basis points (200 basis
        points, i.e., 2.00%), divided by 10,000, and ceilinged to the
        next integer cent. The administrative-overhead line in cents
        equals the surcharge subtotal in cents multiplied by the
        overhead-rate basis points (500 basis points, i.e., 5.00%),
        divided by 10,000, and ceilinged to the next integer cent. The
        total in cents is then the literal sum of four integer values:
        the base fee, the handling line, the surcharge subtotal, and
        the administrative-overhead line -- in that order."

        Claim: with base_fee_cents=997 and correction_round=1,
        handling_line_cents == ceil(997*200/10000) == 20,
        admin_overhead_cents == ceil(500*500/10000) == 25,
        surcharge_subtotal_cents == 500,
        total_cents == 997 + 20 + 500 + 25 == 1542.

        # difficulty: combinatorial_formula/certificate_fee_pinned_rounding_order
        """
        ctx = setup_application_at_correction_round(
            target_round=1,
            leave_open_at_target=True,
            fee_amount_cents=997,
            max_correction_rounds=2,
        )
        _data, breakdown = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        assert breakdown["handling_line_cents"] == 20
        assert breakdown["admin_overhead_cents"] == 25
        assert breakdown["surcharge_subtotal_cents"] == 500
        assert breakdown["total_cents"] == 1542

    def test_total_uses_helpers_for_base_1000_round_1(self, api):
        """PRD §3.11: "The total in cents is then the literal sum of
        four integer values: the base fee, the handling line, the
        surcharge subtotal, and the administrative-overhead line -- in
        that order."

        Claim: total_cents matches the helper formula for base=1000,
        correction_round=1: 1000 + 20 + 500 + 25 == 1545.
        """
        ctx = setup_application_at_correction_round(
            target_round=1,
            leave_open_at_target=True,
            fee_amount_cents=1000,
            max_correction_rounds=2,
        )
        _data, breakdown = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        expected_total = expected_fee_total_cents(1000, 1)
        assert expected_total == 1545
        assert breakdown["total_cents"] == 1545
        assert breakdown["handling_line_cents"] == 20
        assert breakdown["admin_overhead_cents"] == 25
        assert breakdown["surcharge_subtotal_cents"] == 500


# ===========================================================================
# Cap (PRD §3.11)
# ===========================================================================
class TestSurchargeCap:
    def test_correction_round_two_uses_per_round_not_cap(self, api):
        """PRD §3.11: "for correction_round between 1 and 2 inclusive it
        equals the per-round surcharge constant of 500 cents (i.e., 5.00
        yuan per round) multiplied by correction_round; and for
        correction_round strictly greater than 2 it is capped at the
        surcharge cap of 1,000 cents (i.e., 10.00 yuan)."

        Claim: at correction_round=2, surcharge subtotal is
        500*2 = 1000 cents (boundary == cap, but still computed via
        per-round multiplier).
        """
        ctx = setup_application_at_correction_round(
            target_round=2,
            leave_open_at_target=True,
            fee_amount_cents=1000,
            max_correction_rounds=2,
        )
        _data, breakdown = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        # PRD: "for correction_round between 1 and 2 inclusive it equals
        # the per-round surcharge constant of 500 cents ... multiplied by
        # correction_round" -> 500*2 = 1000 cents.
        assert breakdown["surcharge_subtotal_cents"] == 500 * 2


# ===========================================================================
# Provisional vs final variant freeze (PRD §3.11)
# ===========================================================================
class TestFeeBreakdownVariantFreeze:
    def test_final_variant_freezes_at_terminal_transition(self, api):
        """PRD §3.11: "The provisional variant is the form reported while
        the application is still in SUBMITTED, UNDER_REVIEW,
        AWAITING_CORRECTION, or ESCALATED ... The final variant is the
        form reported once the application is in APPROVED, REJECTED, or
        WITHDRAWN: the breakdown is frozen at the correction_round value
        at the moment of the terminal transition and never recomputes
        thereafter."

        Claim: read fee at correction_round=1 (provisional), then drive
        to APPROVED. The frozen final breakdown's correction_round (and
        hence surcharge subtotal) must equal the value at the moment of
        terminal transition (==1), and re-reading it later yields the
        same total_cents.

        # difficulty: dual_variant_calc/certificate_fee_provisional_vs_final_on_application
        """
        # Issue one correction (round 1), resubmit, then APPROVE.
        ctx = setup_application_under_review_single_dept(
            fee_amount_cents=1000,
            max_correction_rounds=2,
        )
        notice = issue_correction_for_primary_material(ctx=ctx)
        # Confirm provisional state.
        prov_data, prov_breakdown = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        assert prov_data["review_status"] == "AWAITING_CORRECTION"
        assert prov_data["correction_round"] == 1
        prov_total = prov_breakdown["total_cents"]
        assert prov_total == expected_fee_total_cents(1000, 1)
        # Resubmit -> back to UNDER_REVIEW with correction_round still 1.
        resubmit_primary_material(ctx=ctx, correction_notice_id=notice["id"])
        # Approve.
        tasks = list_review_tasks(
            ctx["application"]["id"], ctx["reviewer_headers"]
        )
        in_progress = next(t for t in tasks if t["status"] == "IN_PROGRESS")
        decide(in_progress["id"], "AGREED", ctx["reviewer_headers"])
        # Read final variant.
        final_data, final_breakdown = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        assert final_data["review_status"] == "APPROVED"
        # PRD: "frozen at the correction_round value at the moment of
        # terminal transition" -> remains correction_round==1 in final.
        assert final_breakdown["total_cents"] == expected_fee_total_cents(1000, 1)
        # Read again -- still the same.
        final_data2, final_breakdown2 = _read_fee_breakdown(
            api, ctx["application"]["id"], ctx["applicant_headers"]
        )
        assert final_breakdown2["total_cents"] == final_breakdown["total_cents"]
