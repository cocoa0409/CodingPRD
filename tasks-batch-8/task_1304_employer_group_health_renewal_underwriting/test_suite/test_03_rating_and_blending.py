"""Credibility blending and the renewal rate cap."""
import pytest

from test_helpers import (
    get_success_data,
    api_client,
    create_broker,
    create_case_in_rating,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestRateCapVariants:
    def test_blended_rate_cap_binds(self):
        """PRD section 3.3: "If the raw blend exceeds that ceiling, the blend is
        clamped to the ceiling and `is_rate_cap_applied` becomes true; otherwise
        it becomes false."
        PRD section 3.1: "The default rate cap on any renewal is a fifteen
        percent maximum increase, expressed as the decimal 0.15, and
        `rate_cap_pct` carries that value once rating computes."

        Design: Difficulty/dual_variant_calc/blended_rate_cap_binds_vs_uncapped
        """
        broker = create_broker()
        # current PEPM = 19200000 / 12 / 400 = 4000; cap ceiling = 4000*1.15 = 4600
        case, _ = create_case_in_rating(
            broker["id"], current_premium_annual=19200000
        )
        assert case["blended_rate_cents"] == 4600
        assert case["is_rate_cap_applied"] is True
        assert case["rate_cap_pct"] == pytest.approx(0.15, abs=1e-9)

    def test_blended_rate_cap_not_binding(self):
        """PRD section 3.3: "the maximum permissible PEPM is the current in-force
        PEPM — `current_premium_annual` divided by 12 and then by the census
        `enrolled_employees` — grown by one plus `rate_cap_pct` (the default
        0.15). If the raw blend exceeds that ceiling, the blend is clamped to the
        ceiling and `is_rate_cap_applied` becomes true; otherwise it becomes
        false."

        Design: Difficulty/dual_variant_calc/blended_rate_cap_binds_vs_uncapped
        """
        broker = create_broker()
        # current PEPM = 24000000 / 12 / 400 = 5000; cap ceiling 5750 > 5338
        case, _ = create_case_in_rating(
            broker["id"], current_premium_annual=24000000
        )
        assert case["blended_rate_cents"] == 5338
        assert case["is_rate_cap_applied"] is False


class TestRateCapBoundaryFlag:
    def test_cap_boundary_blend_below_ceiling_uncapped(self):
        """PRD section 3.3: "If the raw blend exceeds that ceiling, the blend is
        clamped to the ceiling and `is_rate_cap_applied` becomes true; otherwise
        it becomes false."
        With current_premium_annual 22280400 the ceiling is 5338.0125 — above the
        raw blend of 5338 — so no clamping occurs.

        Design: Corner/complexity_layers/rate_cap_boundary_flag
        """
        broker = create_broker()
        case, _ = create_case_in_rating(
            broker["id"], current_premium_annual=22280400
        )
        assert case["blended_rate_cents"] == 5338
        assert case["is_rate_cap_applied"] is False

    def test_cap_boundary_blend_above_ceiling_capped(self):
        """PRD section 3.3: "If the raw blend exceeds that ceiling, the blend is
        clamped to the ceiling and `is_rate_cap_applied` becomes true".
        With current_premium_annual 22280000 the ceiling is 5337.9167 — below the
        raw blend of 5338 — so the blend is clamped (rounding lands on the same
        whole-cent value while the flag flips).

        Design: Corner/complexity_layers/rate_cap_boundary_flag
        """
        broker = create_broker()
        case, _ = create_case_in_rating(
            broker["id"], current_premium_annual=22280000
        )
        assert case["blended_rate_cents"] == 5338
        assert case["is_rate_cap_applied"] is True
