"""Rent reasonableness — comparables, median tie-break, threshold,
and is_reasonable computation.

PRD §3.6.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    assert_rent_reasonableness_record,
    create_pending_tenancy,
    create_rent_reasonableness_payload,
    current_clock,
    iso_utc,
    make_case_worker_headers,
    new_case_worker_id,
    setup_eligible_applicant_with_voucher,
    setup_unit_with_payment_standard,
    validate_error,
    validate_success,
)


def _pending_tenancy_with_gross_rent(gross_rent_cents: int = 100_000):
    """Build a Tenancy in PENDING_INSPECTION/PENDING_RENT_REASONABLE
    state with a known gross_rent_cents."""
    applicant, voucher = setup_eligible_applicant_with_voucher(
        household_size=1, dependents_count=0,
        gross_annual_income_cents=1_200_000,
    )
    unit, _, _ = setup_unit_with_payment_standard(
        zone="ZONE_A", bedroom_count=0,
        asking_rent_cents=gross_rent_cents,
        tenant_paid_utilities_cents=0,
        standard_amount_cents=60_000,
        voucher_bedroom_size_for_ps=min(voucher["bedroom_size"], 0),
    )
    tenancy = create_pending_tenancy(
        voucher_id=voucher["id"], unit_id=unit["id"],
        lease_start=iso_utc(add_days(current_clock(), 30)),
    )
    return tenancy


class TestComparablesMinimumLength:

    def test_two_comparables_rejected(self, api):
        """PRD §3.6: "The array must contain at least 3 entries; an
        array with fewer is rejected with ERR_INSUFFICIENT_COMPARABLES."
        # difficulty: boundary_precision_check/comparable_rents_length_minimum_three
        """
        tenancy = _pending_tenancy_with_gross_rent(100_000)
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.create_rent_reasonableness_record(
            create_rent_reasonableness_payload(
                tenancy_id=tenancy["id"],
                comparable_rents_cents=[100_000, 110_000],
            ),
            cw,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_COMPARABLES.value,
        )

    def test_three_comparables_accepted(self, api):
        """PRD §3.6: same sentence — array of three or more is the
        accepted boundary.
        # difficulty: boundary_precision_check/comparable_rents_length_minimum_three
        """
        tenancy = _pending_tenancy_with_gross_rent(100_000)
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.create_rent_reasonableness_record(
            create_rent_reasonableness_payload(
                tenancy_id=tenancy["id"],
                comparable_rents_cents=[100_000, 110_000, 120_000],
            ),
            cw,
        )
        data = validate_success(resp, expected_status=201)
        assert_rent_reasonableness_record(data)
        # n=3 (odd): median = index (3-1)//2 = 1 → 110_000.
        assert data["median_comparable_cents"] == 110_000
        # floor(110_000 * 1.10) = 121_000.
        assert data["reasonable_threshold_cents"] == 121_000


class TestMedianTieBreak:

    def test_even_length_median_uses_lower_of_two_middles(self, api):
        """PRD §3.6: "For an even-length array, the median is the lower
        of the two middle elements (not the arithmetic mean) — this
        tie-break is pinned because the mean could land between two
        cents and create downstream rounding ambiguity."

        Claim: for [100, 110, 130, 150] median is 110 (index 1 = (4//2)-1),
        not the mean 120.
        """
        tenancy = _pending_tenancy_with_gross_rent(100_000)
        cw = make_case_worker_headers(new_case_worker_id())
        data = validate_success(
            api.create_rent_reasonableness_record(
                create_rent_reasonableness_payload(
                    tenancy_id=tenancy["id"],
                    comparable_rents_cents=[100_000, 110_000, 130_000, 150_000],
                ),
                cw,
            ),
            expected_status=201,
        )
        assert data["median_comparable_cents"] == 110_000
        # floor(110_000 * 1.10) = 121_000.
        assert data["reasonable_threshold_cents"] == 121_000

    def test_odd_length_median_is_middle(self, api):
        """PRD §3.6: "For an odd-length array, the median is the middle
        element (the element at index (n-1)/2 after sorting)."
        """
        tenancy = _pending_tenancy_with_gross_rent(100_000)
        cw = make_case_worker_headers(new_case_worker_id())
        data = validate_success(
            api.create_rent_reasonableness_record(
                create_rent_reasonableness_payload(
                    tenancy_id=tenancy["id"],
                    comparable_rents_cents=[120_000, 130_000, 140_000, 150_000, 160_000],
                ),
                cw,
            ),
            expected_status=201,
        )
        assert data["median_comparable_cents"] == 140_000
        # floor(140_000 * 1.10) = 154_000.
        assert data["reasonable_threshold_cents"] == 154_000


class TestThresholdBoundary:

    def test_gross_rent_equal_to_threshold_is_reasonable(self, api):
        """PRD §3.6: "a gross rent exactly equal to the floor of (median
        × 1.10) is reasonable; one cent above it is not."

        Comparables [100_000, 100_000, 100_000] → median 100_000 →
        threshold floor(110_000) = 110_000. Tenancy gross_rent 110_000
        → is_reasonable == True.
        """
        tenancy = _pending_tenancy_with_gross_rent(110_000)
        cw = make_case_worker_headers(new_case_worker_id())
        data = validate_success(
            api.create_rent_reasonableness_record(
                create_rent_reasonableness_payload(
                    tenancy_id=tenancy["id"],
                    comparable_rents_cents=[100_000, 100_000, 100_000],
                ),
                cw,
            ),
            expected_status=201,
        )
        assert data["reasonable_threshold_cents"] == 110_000
        assert data["is_reasonable"] is True

    def test_gross_rent_one_cent_above_threshold_not_reasonable(self, api):
        """PRD §3.6: "one cent above it is not."

        Tenancy gross_rent = 110_001; threshold = 110_000 → False.
        """
        tenancy = _pending_tenancy_with_gross_rent(110_001)
        cw = make_case_worker_headers(new_case_worker_id())
        data = validate_success(
            api.create_rent_reasonableness_record(
                create_rent_reasonableness_payload(
                    tenancy_id=tenancy["id"],
                    comparable_rents_cents=[100_000, 100_000, 100_000],
                ),
                cw,
            ),
            expected_status=201,
        )
        assert data["reasonable_threshold_cents"] == 110_000
        assert data["is_reasonable"] is False
