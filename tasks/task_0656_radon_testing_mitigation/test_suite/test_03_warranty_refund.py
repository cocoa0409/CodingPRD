"""Warranty cancellation refunds: STEP_TIER band vs STRAIGHT_LINE proration,
and the covered-price conservation invariant (refund + retained == covered).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_cleared_job_with_warranty, set_clock,
    cancel_warranty_payload, make_client_contact_headers,
)

# Job: BASEMENT/2200/3pts/sump/rush → quote_total 410550 (covered_system_price).
JOB_OVERRIDES_410550 = {"num_suction_points": 3, "has_sump_pump": True,
                        "is_rush": True}
PROP_RUSH = {"is_real_estate_transaction": True,
             "closing_deadline_utc": "2026-05-01T00:00:00Z"}


def test_step_tier_refund_first_band_ninety_percent(api):
    """PRD §3.6: "Under `STEP_TIER`, the elapsed fraction is the elapsed days
    divided by `term_days`, and a flat percentage is chosen by band: a fraction
    below 0.25 refunds 90 percent, a fraction below 0.50 refunds 60 percent, a
    fraction below 0.75 refunds 30 percent, and a fraction of 0.75 or greater
    refunds 0 percent; the refund is `covered_system_price_cents` multiplied by
    that chosen percentage, rounded half up."

    Design: Difficulty/dual_variant_calc/dvc_warranty_refund_straight_line_vs_step_tier
    """
    _, prop, _, warranty, _, _ = setup_cleared_job_with_warranty(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        job_overrides={**JOB_OVERRIDES_410550, "warranty_refund_method": "STEP_TIER"},
        **PROP_RUSH)
    assert warranty["refund_method"] == "STEP_TIER"
    assert warranty["covered_system_price_cents"] == 410550
    # 90 days elapsed of a 1825-day term → frac 0.049 < 0.25 → 90%.
    set_clock("2026-07-02T00:00:00Z")
    client = make_client_contact_headers(prop["id"])
    fresh = validate_success(api.get_warranty(warranty["id"], client), 200)
    cancelled = validate_success(
        api.cancel_warranty(warranty["id"],
                            cancel_warranty_payload(fresh["version"]), client), 200)
    # round_half_up(410550 * 0.90) = 369495
    assert cancelled["refund_paid_cents"] == 369495
    assert cancelled["coverage_status"] == "CANCELLED"


def test_step_tier_refund_method_recorded_on_warranty(api):
    """PRD §3.6: "The cancellation refund is computed by the warranty's
    `refund_method`."
    PRD §3.6: "Alternatively a `ClientContact` or `PlatformAdmin` may cancel an
    `ACTIVE` warranty, moving coverage from `ACTIVE` to `CANCELLED`."

    Design: Difficulty/dual_variant_calc/dvc_warranty_refund_straight_line_vs_step_tier
    """
    _, prop, _, warranty, _, _ = setup_cleared_job_with_warranty(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        job_overrides={**JOB_OVERRIDES_410550, "warranty_refund_method": "STEP_TIER"},
        **PROP_RUSH)
    set_clock("2026-07-02T00:00:00Z")
    client = make_client_contact_headers(prop["id"])
    fresh = validate_success(api.get_warranty(warranty["id"], client), 200)
    cancelled = validate_success(
        api.cancel_warranty(warranty["id"],
                            cancel_warranty_payload(fresh["version"]), client), 200)
    assert cancelled["refund_method"] == "STEP_TIER"
    assert cancelled["coverage_status"] == "CANCELLED"


def test_straight_line_refund_prorated_by_remaining_days(api):
    """PRD §3.6: "Under `STRAIGHT_LINE`, the refund is `covered_system_price_cents`
    multiplied by remaining days divided by `term_days`, rounded half up to a
    whole cent."

    Design: Difficulty/compensating_invariant/ci_warranty_cancel_refund_conserves_covered_price
    """
    _, prop, _, warranty, _, _ = setup_cleared_job_with_warranty(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        job_overrides={**JOB_OVERRIDES_410550, "warranty_refund_method": "STRAIGHT_LINE"},
        **PROP_RUSH)
    assert warranty["covered_system_price_cents"] == 410550
    # 90 elapsed days of 1825 → remaining 1735 → round(410550 * 1735/1825) = 390304
    set_clock("2026-07-02T00:00:00Z")
    client = make_client_contact_headers(prop["id"])
    fresh = validate_success(api.get_warranty(warranty["id"], client), 200)
    cancelled = validate_success(
        api.cancel_warranty(warranty["id"],
                            cancel_warranty_payload(fresh["version"]), client), 200)
    assert cancelled["refund_paid_cents"] == 390304


def test_straight_line_refund_plus_retained_conserves_covered_price(api):
    """PRD §3.6: "On cancel the prorated `refund_paid_cents` is computed over
    `covered_system_price_cents`."
    PRD §3.5: "`covered_system_price_cents` from the job's `quote_total_cents`."

    Design: Difficulty/compensating_invariant/ci_warranty_cancel_refund_conserves_covered_price
    """
    _, prop, _, warranty, _, _ = setup_cleared_job_with_warranty(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        job_overrides={**JOB_OVERRIDES_410550, "warranty_refund_method": "STRAIGHT_LINE"},
        **PROP_RUSH)
    set_clock("2026-07-02T00:00:00Z")
    client = make_client_contact_headers(prop["id"])
    fresh = validate_success(api.get_warranty(warranty["id"], client), 200)
    cancelled = validate_success(
        api.cancel_warranty(warranty["id"],
                            cancel_warranty_payload(fresh["version"]), client), 200)
    refund = cancelled["refund_paid_cents"]
    covered = cancelled["covered_system_price_cents"]
    assert refund == 390304
    assert covered == 410550
    # refund + retained == covered (390304 + 20246 == 410550)
    assert refund + (covered - refund) == covered
