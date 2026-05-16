"""FPL percentage computation and CSR tier classification.

PRD §2.7 (precision), §3.2 (FPL), §3.3 (CSR thresholds).

The FPL percentage is the household MAGI divided by the FPL denominator
times 100, rounded half-up to one decimal place. CSR tier follows a
step function over fpl_percentage with half-open intervals at one-
decimal precision.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    fpl_denominator,
    re_get_application,
    setup_application_at_fpl_percentage,
    setup_submitted_application,
    validate_success,
)


# ===========================================================================
# FPL percentage calculation (PRD §3.2)
# ===========================================================================
class TestFplPercentage:
    """PRD §3.2: "The fpl_percentage field is then the household's MAGI
    divided by that denominator, multiplied by 100, and rounded half-up
    to one decimal place."""

    def test_fpl_percentage_two_person_2026_at_211(self, api):
        """PRD §3.2: "For coverage year 2026 (version v2), the
        corresponding denominators are 1,572,500 cents, 2,131,000 cents,
        2,689,500 cents, 3,248,000 cents, 3,806,500 cents, and
        4,365,000 cents."

        Claim: household_size=2, coverage_year=2026 (denom 2,131,000),
        MAGI 4,500,000 → fpl_percentage = round_half_up(
        4_500_000 / 2_131_000 * 100) = round_half_up(211.169) = 211.2.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=211.2, coverage_year=2026,
                household_size=2,
            )
        )
        # The helper pegs MAGI to produce fpl_percentage == target after
        # rounding; assert exact one-decimal value.
        assert determined["fpl_percentage"] == 211.2

    def test_fpl_percentage_single_person_2025_table(self, api):
        """PRD §3.2: "For coverage year 2025 (version v1), those
        denominators are 1,525,500 cents at household size 1".

        Claim: household_size=1, coverage_year=2025, MAGI 1,500,000 →
        fpl_percentage = round_half_up(1_500_000/1_525_500 * 100)
        = round_half_up(98.328) = 98.3.

        PRD §3.2: coverage_year must equal current_year or
        current_year+1. We advance the logical clock back to 2024 so
        coverage_year=2025 is current_year+1.
        """
        # Advance the logical clock into 2024 so 2025 is a valid future
        # coverage_year (current_year+1).
        advance_clock_to("2024-06-15T00:00:00.000Z")
        denom = fpl_denominator(2025, 1)
        # Pick a MAGI that gives a clean one-decimal value: 1_500_000.
        # We compute the expected rounding of the percentage:
        raw = 1_500_000 / denom * 100.0
        # Round half-up to 1 decimal.
        from decimal import ROUND_HALF_UP, Decimal
        expected = float(
            Decimal(str(raw)).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP,
            ),
        )
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=expected, coverage_year=2025,
                household_size=1,
            )
        )
        assert determined["fpl_percentage"] == expected


# ===========================================================================
# CSR tier classification (PRD §3.3) — boundary precision
# ===========================================================================
class TestCsrBoundaries:
    """PRD §3.3: "A household whose fpl_percentage is strictly below
    100.0 lies in Medicaid territory; its csr_eligibility is set to
    NONE ... A household at or above 100.0 and strictly below 138.0 is
    assigned CSR_PLUS ... A household at or above 138.0 and strictly
    below 150.0 is CSR_94; at or above 150.0 and strictly below 200.0
    it is CSR_87; at or above 200.0 and strictly below 250.0 it is
    CSR_73. A household at or above 250.0 receives no CSR and
    csr_eligibility is NONE."

    PRD §2.7: "threshold comparisons against fpl_percentage are made
    at that one-decimal precision, so a value of 149.9 sits below the
    150.0 boundary while 150.0 sits on it."
    """

    def test_csr_138_exact_lower_boundary_yields_csr_94(self, api):
        """# difficulty: boundary_precision_check/
        fpl_138_inclusive_lower_boundary_csr_94_vs_csr_plus

        PRD §3.3: "A household at or above 138.0 and strictly below
        150.0 is CSR_94".
        PRD §2.7: "a value of 149.9 sits below the 150.0 boundary
        while 150.0 sits on it."

        Claim: fpl_percentage == 138.0 → csr_eligibility == 'CSR_94'.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=138.0, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["fpl_percentage"] == 138.0
        assert determined["csr_eligibility"] == "CSR_94"

    def test_csr_137_9_below_boundary_yields_csr_plus(self, api):
        """# difficulty: boundary_precision_check/
        fpl_138_inclusive_lower_boundary_csr_94_vs_csr_plus

        PRD §3.3: "A household at or above 100.0 and strictly below
        138.0 is assigned CSR_PLUS".

        Claim: fpl_percentage == 137.9 → csr_eligibility == 'CSR_PLUS'.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=137.9, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["fpl_percentage"] == 137.9
        assert determined["csr_eligibility"] == "CSR_PLUS"

    def test_csr_150_exact_boundary_yields_csr_87(self, api):
        """PRD §3.3: "at or above 150.0 and strictly below 200.0 it is
        CSR_87".

        Claim: fpl_percentage == 150.0 → 'CSR_87'.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=150.0, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["fpl_percentage"] == 150.0
        assert determined["csr_eligibility"] == "CSR_87"

    def test_csr_149_9_below_150_yields_csr_94(self, api):
        """PRD §2.7: "a value of 149.9 sits below the 150.0 boundary
        while 150.0 sits on it."

        Claim: fpl_percentage == 149.9 → 'CSR_94'.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=149.9, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["fpl_percentage"] == 149.9
        assert determined["csr_eligibility"] == "CSR_94"

    def test_csr_200_boundary_yields_csr_73(self, api):
        """PRD §3.3: "at or above 200.0 and strictly below 250.0 it is
        CSR_73".

        Claim: fpl_percentage == 200.0 → 'CSR_73'.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=200.0, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["fpl_percentage"] == 200.0
        assert determined["csr_eligibility"] == "CSR_73"

    def test_csr_250_or_above_yields_none(self, api):
        """PRD §3.3: "A household at or above 250.0 receives no CSR and
        csr_eligibility is NONE."

        Claim: fpl_percentage == 250.0 → 'NONE'.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=250.0, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["fpl_percentage"] == 250.0
        assert determined["csr_eligibility"] == "NONE"

    def test_fpl_below_100_yields_none(self, api):
        """PRD §3.3: "A household whose fpl_percentage is strictly
        below 100.0 lies in Medicaid territory; its csr_eligibility
        is set to NONE."

        Claim: fpl_percentage = 99.0 → 'NONE'.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=99.0, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["fpl_percentage"] == 99.0
        assert determined["csr_eligibility"] == "NONE"
