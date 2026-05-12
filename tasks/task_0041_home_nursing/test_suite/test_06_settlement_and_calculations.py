"""Settlement, refunds, fee calculations, and rounding precision.

Covers PRD §3.5 and the rounding rule in §2.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_SCHEDULED_START_ISO,
    accept_dispatch,
    add_hours,
    add_seconds,
    advance_clock,
    api_client,
    assert_settlement,
    assert_settlement_invariants,
    confirm_completion,
    create_certified_nurse,
    create_order_raw,
    create_service_item_raw,
    finish_service_record,
    get_success_data,
    haversine_km,
    make_compliance_officer_headers,
    make_nurse_headers,
    make_patient_headers,
    offset_lat_km,
    perform_checkin,
    setup_completed_order,
    setup_basic_dispatched_order,
    setup_in_progress_order,
    stable_user_id,
    validate_error,
    validate_success,
)


# Reference scenario constants (PRD §2.7 + §3.5)
# base_price=20000 cents, daytime weekday checkin -> tod_surcharge=0,
# nurse home == service coords -> distance=0 -> distance_surcharge=0,
# revenue_share_bps=7000.
class TestEstimatedFeeBaseline:

    def test_estimated_fee_baseline_no_surcharges(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'The estimate stored on estimated_fee_cents is the
        net plus tax. Each component is rounded before the sum is taken
        -- sum-then-round is wrong.'

        With base=20000, distance=0 (free under 5km), daytime weekday
        (no tod surcharge), no package: net=20000, tax=
        round_half_up(20000*600/10000)=1200, total=21200.
        """
        item = create_service_item_raw(
            required_skill="ELDERLY_CARE",
            base_price_cents=20000,
        )
        nurse = create_certified_nurse(
            specialty_tags=["ELDERLY_CARE"],
            home_lat=31.20, home_lng=121.40,
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        # PRD §2.7 mandates per-component round_half_up THEN sum.
        # Net=20000+0+0-0=20000; tax=round_half_up(20000*600/10000)=1200.
        # Total estimated_fee = 21200.
        assert order["estimated_fee_cents"] == 21200, (
            f"PRD §3.2: estimated_fee_cents={order['estimated_fee_cents']}, "
            f"expected 21200 = 20000 + 0 + 0 - 0 + 1200(tax)"
        )


class TestSettlementCalculation:

    def test_settlement_baseline_components(
        self, api, platform_admin_headers,
    ):
        """PRD §3.5: 'The base remains the catalog item's base_price_cents.
        The distance surcharge takes the actual distance_km from the
        accepted dispatch ... rounded up to the next whole kilometre, and
        multiplying by 200 cents per kilometre ... The pre-tax
        gross_fee_cents is the maximum of zero and the sum of base,
        distance surcharge, and time-of-day surcharge minus the package
        deduction. The tax_cents is the gross multiplied by 600 basis
        points divided by 10000, rounded half-up.'

        With base=20000, distance=0, daytime weekday checkin, no package:
        gross=20000, tax=1200, nurse_share=14000 (70%), platform=6000.
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000,
            revenue_share_bps=7000,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
        )
        s = setup["settlement"]
        assert s["gross_fee_cents"] == 20000, (
            f"PRD §3.5: gross_fee_cents=20000, got {s['gross_fee_cents']}"
        )
        assert s["tax_cents"] == 1200, (
            f"PRD §3.5: tax = round_half_up(20000*600/10000)=1200, "
            f"got {s['tax_cents']}"
        )
        assert s["nurse_revenue_share_cents"] == 14000, (
            f"PRD §3.5: nurse share = round_half_up(20000*7000/10000)="
            f"14000, got {s['nurse_revenue_share_cents']}"
        )
        assert s["platform_share_cents"] == 6000, (
            f"PRD §3.5: 'platform_share_cents is the gross minus the "
            f"nurse share' = 20000-14000=6000, "
            f"got {s['platform_share_cents']}"
        )
        assert_settlement_invariants(s)

    def test_settlement_status_finalized_after_completion(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4 / §3.5: at completion, 'a Settlement row is created
        with status FINALIZED'."""
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        assert setup["settlement"]["status"] == "FINALIZED"


class TestRefundTiers:

    def test_refund_full_at_one_hour_inclusive(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'When the elapsed time is at-or-below 1 hour, the
        refund equals gross_fee_cents plus tax_cents -- a full refund.'
        Plus PRD §3.5: 'exactly 1.0 hour is a full refund and 1.0001
        hours is a fifty-percent refund.'

        Claim: refund issued at exactly 1.0h after completion = full
        refund (gross + tax).
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000, revenue_share_bps=7000,
        )
        gross = setup["settlement"]["gross_fee_cents"]
        tax = setup["settlement"]["tax_cents"]
        # Advance clock to completed_at + 3600s exactly.
        completed_at = setup["order"].get("updated_at") or \
            setup["settlement"]["created_at"]
        advance_clock(add_seconds(completed_at, 3600))
        res = api.refund_order(
            setup["order"]["id"], compliance_officer_headers
        )
        data = get_success_data(res)
        assert data["refund_cents"] == gross + tax, (
            f"PRD §3.5: at exactly 1h elapsed, refund = gross + tax "
            f"= {gross + tax}, got {data['refund_cents']}"
        )
        assert data["status"] == "REVERSED", (
            "PRD §3.5: 'On a successful refund, ... Settlement.status "
            "advances to REVERSED'"
        )

    def test_refund_window_exceeded_rejected(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'The refund window is 24 hours after
        ServiceRecord.completed_at; a refund requested strictly later
        than 24 hours after completion is rejected with
        ERR_REFUND_WINDOW_EXPIRED.'
        """
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        completed_at = setup["settlement"]["created_at"]
        # 24h + 1s past completion -> outside window.
        advance_clock(add_seconds(completed_at, 24 * 3600 + 1))
        res = api.refund_order(
            setup["order"]["id"], compliance_officer_headers
        )
        validate_error(res, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED.value)


class TestSettlementInvariants:

    def test_payment_captured_on_completion(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'the payment is captured (payment_status advances
        from AUTHORIZED to CAPTURED)'."""
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        order = get_success_data(api.get_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        ))
        assert order["payment_status"] == "CAPTURED"
