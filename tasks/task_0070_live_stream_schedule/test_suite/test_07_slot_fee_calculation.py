"""Slot-fee calculation — provisional, final, peak, package, deposit precision.

PRD §3.5 — slot-fee arithmetic. Covers difficulty-design dual_variant_calc and
combinatorial_formula (slot-fee mode b — pinned rounding order).
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from test_helpers import (
    validate_success,
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    setup_active_streamer,
    setup_studio_with_window,
    setup_draft_application,
    attach_compatible_product,
    submit_application,
    ops_approve,
    compliance_approve,
    fetch_invoice,
    setup_silver_streamer_for_pricing_divergence,
    setup_silver_streamer_for_combo_discount,
    boost_streamer_to_tier,
)


def round_half_up(x) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class TestSlotFeeBronzeStandard:
    """PRD §3.5: 'The arithmetic proceeds as follows. The number of hours in the
    requested broadcast ... Multiplying that hour count by the studio's
    base_hour_price_cents produces the base component. ...'
    """

    def test_off_peak_bronze_standard_2h_total(self, api):
        """PRD §3.5: "The arithmetic proceeds as follows. The number of hours
        in the requested broadcast, kept at full precision, is the difference
        between ends_at and starts_at expressed in seconds and divided by
        3600. Multiplying that hour count by the studio's
        base_hour_price_cents produces the base component."

        BRONZE: 0% tier discount; STANDARD: 0% package discount.
        2 hours at 10000 cents/hr, no peak overlap (10:00-12:00 UTC).
        Expected total = 20000.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        # 10:00 - 12:00 UTC is fully off-peak
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=1)  # 10:00
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=30),
            available_end=ends + timedelta(days=30),
            base_hour_price_cents=10_000,
            slot_tier="A",
        )
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
            package_code="STANDARD",
        )
        attach_compatible_product(app, streamer)
        submitted = submit_application(streamer, app)
        # PRD §3.5: provisional = base + peak. Off-peak BRONZE STANDARD = 20000
        assert submitted["provisional_fee_cents"] == 20_000


class TestSlotFeePeakSurcharge:
    """PRD §3.5: 'The number of peak hours in the interval is the count of
    minutes in the half-open interval that fall inside the peak window
    19:00–23:00 UTC, divided by 60 — kept at full precision, not rounded.
    Multiplying the peak-hour count by base_hour_price_cents and by the peak
    multiplier 0.50 produces the peak surcharge component.'
    """

    def test_full_peak_window_2h_surcharge(self, api):
        """PRD §3.5: "Multiplying the peak-hour count by base_hour_price_cents
        and by the peak multiplier 0.50 produces the peak surcharge component.
        Their sum is the unrounded subtotal."

        20:00-22:00 UTC: 2 peak hours. base = 2*10000=20000, peak = 2*10000*0.5
        = 10000, subtotal = 30000, BRONZE STANDARD => 30000.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)  # 20:00 UTC
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=30),
            available_end=ends + timedelta(days=30),
            base_hour_price_cents=10_000,
        )
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
            package_code="STANDARD",
        )
        attach_compatible_product(app, streamer)
        submitted = submit_application(streamer, app)
        assert submitted["provisional_fee_cents"] == 30_000


class TestSlotFeeFinalVsProvisional:
    """PRD §3.5: 'The slot-fee calculation runs in two variants: a provisional
    variant at submit time (writing provisional_fee_cents) and a final variant
    at compliance approval (writing final_fee_cents, which must equal the
    invoice's total_cents).'
    """

    def test_final_equals_provisional_when_tier_unchanged(self, api):
        """PRD §3.5: "Whenever the streamer's tier escalates between submit and
        compliance approval, the two variants produce different integer-cent
        results."

        Negative form: if tier does NOT escalate, the two must match.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=30),
            available_end=ends + timedelta(days=30),
            base_hour_price_cents=10_000,
        )
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
            package_code="STANDARD",
        )
        attach_compatible_product(app, streamer)
        app = submit_application(streamer, app)
        prov = app["provisional_fee_cents"]
        app = ops_approve(app["id"], decision="APPROVE")
        app = compliance_approve(app["id"], decision="APPROVE")
        assert app["pinned_streamer_tier"] == "BRONZE"
        assert app["final_fee_cents"] == prov, \
            "final_fee_cents must equal provisional when tier is unchanged"

    def test_invoice_total_equals_final_fee_cents(self, api):
        """PRD §3.5: "the invoice's total_cents equals final_fee_cents".
        Also: "When SlotFeeInvoice is issued at compliance approval, ...
        its total_cents equals final_fee_cents."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=30),
            available_end=ends + timedelta(days=30),
            base_hour_price_cents=10_000,
        )
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
        )
        attach_compatible_product(app, streamer)
        submit_application(streamer, app)
        app = ops_approve(app["id"], decision="APPROVE")
        app = compliance_approve(app["id"], decision="APPROVE")
        invoice = fetch_invoice(app["id"])
        assert invoice["total_cents"] == app["final_fee_cents"]


class TestDepositPrecision:
    """PRD §2.7 + §3.5: 'The deposit fraction is fixed at 30% of the final slot
    fee, with the single end-of-calculation rounding applied.'
    """

    def test_deposit_is_30_percent_rounded_once(self, api):
        """PRD §3.5: "The invoice's deposit_due_cents is then the single-rounded
        30% of total_cents."
        Specifically per PRD §3.4: "computes deposit_cents as 30% of
        final_fee_cents with the single end-of-calculation rounding."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=30),
            available_end=ends + timedelta(days=30),
            base_hour_price_cents=10_000,
        )
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
        )
        attach_compatible_product(app, streamer)
        submit_application(streamer, app)
        app = ops_approve(app["id"], decision="APPROVE")
        app = compliance_approve(app["id"], decision="APPROVE")
        invoice = fetch_invoice(app["id"])
        expected_deposit = round_half_up(invoice["total_cents"] * 0.30)
        assert invoice["deposit_due_cents"] == expected_deposit, (
            f"deposit_due_cents={invoice['deposit_due_cents']} but PRD-spec "
            f"30% rounded = {expected_deposit}"
        )


class TestDualVariantTierDivergence:
    """Difficulty-design Rule 1 instance: slot_fee_provisional_vs_final."""

    def test_silver_escalation_between_submit_and_approve_diverges_fees(self, api):
        """# difficulty: dual_variant_calc/slot_fee_provisional_vs_final_on_application
        PRD §3.5: "Whenever the streamer's tier escalates between submit and
        compliance approval, the two variants produce different integer-cent
        results."
        PRD §3.5: "the provisional variant reads the streamer's tier as it
        stands at submission, while the final variant reads
        pinned_streamer_tier, which is the snapshot the compliance approval
        just pinned."

        Per recipe: 2-hour fully-peak BRONZE booking submitted at provisional
        of 30000; streamer escalates to SILVER (5% off); compliance pins SILVER
        and final = round_half_up(30000 * 0.95) = 28500.
        """
        bundle = setup_silver_streamer_for_pricing_divergence()
        app = bundle["application"]
        invoice = bundle["invoice"]
        assert app["pinned_streamer_tier"] == "SILVER"
        assert app["provisional_fee_cents"] == 30_000, \
            f"provisional must be BRONZE-priced 30000, got {app['provisional_fee_cents']}"
        assert app["final_fee_cents"] == 28_500, \
            f"final must be SILVER-priced 28500, got {app['final_fee_cents']}"
        assert invoice["total_cents"] == 28_500
        # Deposit: round_half_up(28500 * 0.30) = round_half_up(8550.0) = 8550
        assert invoice["deposit_due_cents"] == 8_550


class TestPinnedRoundingOrderModeB:
    """Difficulty-design Rule 2 instance: slot_fee_pinned_rounding_order_mode_b."""

    def test_silver_combo_half_day_single_rounding_total(self, api):
        """# difficulty: combinatorial_formula/slot_fee_pinned_rounding_order_mode_b
        PRD §3.5: "The result is then rounded half-up to integer cents exactly
        once, at the very end — order of the two discounts matters because the
        package discount is taken on top of the tier-adjusted subtotal, not on
        the original unrounded subtotal."

        Per recipe: SILVER tier (5%), COMBO_HALF_DAY (8%), 2 peak hours at
        10000/hr => subtotal 30000; final = round_half_up(30000*0.95*0.92)
        = round_half_up(26220.0) = 26220; deposit = round_half_up(26220*0.30)
        = round_half_up(7866.0) = 7866.
        """
        bundle = setup_silver_streamer_for_combo_discount()
        invoice = bundle["invoice"]
        assert invoice["total_cents"] == 26_220, \
            f"total_cents must be 26220 (single-rounded), got {invoice['total_cents']}"
        assert invoice["deposit_due_cents"] == 7_866, \
            f"deposit_due_cents must be 7866 (single-rounded), got {invoice['deposit_due_cents']}"
