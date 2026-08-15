"""Boundary precision: each numeric threshold is probed at X-1, X, X+1 — intake
variance, pause notice, lost-item age bands, and the overage quota."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_intake,
    create_case,
    create_pause_payload,
    generate_invoice,
    setup_active_subscription,
    setup_completed_stop_with_intake,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import BILLING


class TestIntakeVarianceThreshold:
    def test_variance_exactly_10_is_reconciled(self, api):
        """PRD 3.4: "When the variance is at most 10.00 percent the intake lands in
        `RECONCILED`; above that it lands in `DISPUTED`."
        PRD 3.4: "The `variance_pct` is the absolute difference between
        `scale_weight_g` and `expected_weight_g`, multiplied by ten thousand, divided
        by `expected_weight_g`, rounded half-up to a whole number, then divided by one
        hundred — a two-decimal percentage."

        Design: Difficulty/boundary_precision_check/intake_variance_threshold_exact_boundary
        """
        ctx = setup_completed_stop_with_intake(clean_items=80, scale_weight_g=8800)
        intake = ctx["intake"]
        assert_intake(intake)
        # expected = 80 items x 100 g = 8000 g; |8800 - 8000| x 10000 / 8000 = 10.00
        assert intake["expected_weight_g"] == 8000
        assert float(intake["variance_pct"]) == pytest.approx(10.00, abs=0.001)
        assert intake["status"] == "RECONCILED", (
            "the 10.00 percent threshold is inclusive"
        )

    def test_variance_10_01_is_disputed(self, api):
        """PRD 3.4: "When the variance is at most 10.00 percent the intake lands in
        `RECONCILED`; above that it lands in `DISPUTED`."

        Design: Difficulty/boundary_precision_check/intake_variance_threshold_exact_boundary
        """
        ctx = setup_completed_stop_with_intake(clean_items=80, scale_weight_g=8801)
        intake = ctx["intake"]
        # 801 x 10000 / 8000 = 1001.25 -> round_half_up 1001 -> 10.01
        assert float(intake["variance_pct"]) == pytest.approx(10.01, abs=0.001)
        assert intake["status"] == "DISPUTED", (
            "one gram past the boundary flips the outcome to DISPUTED"
        )


class TestPauseNoticeBoundary:
    def test_pause_notice_two_days_rejected(self, api):
        """PRD 3.7: "Notice: the `start_date` must be at least three days after the
        current logical date — exactly three days ahead is allowed — else
        `ERR_PAUSE_NOTICE_TOO_SHORT`."

        Design: Difficulty/boundary_precision_check/pause_notice_exactly_three_days
        """
        ctx = setup_active_subscription()  # clock at 2026-08-01
        response = _client.create_pause(
            create_pause_payload(
                ctx["subscription"]["id"], "2026-08-03", "2026-08-08",
                ctx["subscription_version"],
            ),
            ctx["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_PAUSE_NOTICE_TOO_SHORT.value)

    def test_pause_notice_exactly_three_days_allowed(self, api):
        """PRD 3.7: "Notice: the `start_date` must be at least three days after the
        current logical date — exactly three days ahead is allowed — else
        `ERR_PAUSE_NOTICE_TOO_SHORT`."
        PRD 3.7: "`estimated_credit_cents` is the number of distinct Monday-to-Sunday
        billing weeks that the half-open window touches, multiplied by the plan's
        `weekly_fee_cents`."

        Design: Difficulty/boundary_precision_check/pause_notice_exactly_three_days
        """
        ctx = setup_active_subscription()  # clock at 2026-08-01
        pause = validate_success(
            _client.create_pause(
                create_pause_payload(
                    ctx["subscription"]["id"], "2026-08-04", "2026-08-08",
                    ctx["subscription_version"],
                ),
                ctx["customer_headers"],
            ),
            201,
        )
        assert pause["status"] == "SCHEDULED"
        assert pause["estimated_credit_cents"] == 3900, (
            f"[08-04, 08-08) touches one billing week x 3900, got "
            f"{pause['estimated_credit_cents']}"
        )


class TestLostItemAgeBands:
    def _setup_two_cases(self):
        ctx = setup_active_subscription()  # clock at 2026-08-01
        case_90 = create_case(
            ctx["subscription"]["id"], ctx["pool"]["id"],
            case_type="LOST", item_count=1, first_issued_date="2026-05-03",
        )
        case_91 = create_case(
            ctx["subscription"]["id"], ctx["pool"]["id"],
            case_type="LOST", item_count=1, first_issued_date="2026-05-02",
        )
        return case_90, case_91

    def test_age_exactly_90_days_charges_full_price(self, api):
        """PRD 3.8: "at a logical date of 2026-08-01, items first issued on
        2026-05-03 are 90 days old and charge in full, while items issued on
        2026-05-02 are 91 days old and drop to 60 percent."

        Design: Difficulty/boundary_precision_check/lost_item_age_band_exact_boundary
        """
        case_90, _ = self._setup_two_cases()
        charged = validate_success(
            _client.case_event(case_90["id"], {"event_type": "CHARGE"}, BILLING)
        )
        assert charged["charge_cents"] == 300, (
            f"age exactly 90 days is in the full-price band: 1 x 300 x 1.00 = 300, "
            f"got {charged['charge_cents']}"
        )

    def test_age_91_days_drops_to_sixty_percent(self, api):
        """PRD 3.8: "For `LOST`, the schedule is size-based replacement cost —
        `NEWBORN` 250 cents, `SMALL` 275, `MEDIUM` 300, `LARGE` 325, `XL` 350 —
        depreciated by age: the item count times the replacement cost times the full
        amount when the items are at most 90 days old, 60 percent when the age is 91
        through 180 days, and 30 percent at 181 days or older, rounded half-up to
        whole cents."

        Design: Difficulty/boundary_precision_check/lost_item_age_band_exact_boundary
        """
        _, case_91 = self._setup_two_cases()
        charged = validate_success(
            _client.case_event(case_91["id"], {"event_type": "CHARGE"}, BILLING)
        )
        assert charged["charge_cents"] == 180, (
            f"age 91 days drops to the 60 percent band: 1 x 300 x 0.60 = 180, got "
            f"{charged['charge_cents']}"
        )


class TestOverageQuotaBoundary:
    def _invoice_for_week(self, clean_items, route_date, period_start, period_end, scale):
        ctx = setup_completed_stop_with_intake(
            clean_items=clean_items, scale_weight_g=scale, route_date=route_date
        )
        return generate_invoice(ctx["subscription"]["id"], period_start, period_end)

    def test_overage_zero_when_verified_equals_quota(self, api):
        """PRD 3.9: "each qualifying intake contributes its `verified_count` minus
        the `weekly_quota`, floored at zero and capped at `overage_cap_items`, and the
        summed items multiply by `overage_rate_cents`."

        Design: Difficulty/boundary_precision_check/overage_quota_exact_boundary
        """
        invoice = self._invoice_for_week(
            80, "2026-08-03", "2026-08-03", "2026-08-10", 8000
        )
        assert invoice["overage_cents"] == 0, (
            f"verified 80 == quota 80 -> max(80-80, 0) = 0, got {invoice['overage_cents']}"
        )
        assert invoice["total_cents"] == 3900

    def test_first_item_past_quota_bills(self, api):
        """PRD 3.9: "each qualifying intake contributes its `verified_count` minus
        the `weekly_quota`, floored at zero and capped at `overage_cap_items`, and the
        summed items multiply by `overage_rate_cents`."

        Design: Difficulty/boundary_precision_check/overage_quota_exact_boundary
        """
        invoice = self._invoice_for_week(
            81, "2026-08-10", "2026-08-10", "2026-08-17", 8100
        )
        assert invoice["overage_cents"] == 10, (
            f"verified 81 -> min(1, 20) x 10 = 10, got {invoice['overage_cents']}"
        )
        assert invoice["total_cents"] == 3910
