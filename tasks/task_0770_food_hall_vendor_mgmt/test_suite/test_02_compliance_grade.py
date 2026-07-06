"""Stall compliance grade: the LATEST vs WEIGHTED dual variant, and the
single-inspection WEIGHTED base case.
"""
import pytest
from test_helpers import (
    validate_success, create_food_hall, create_stall, conduct_inspection,
    TEST_USERS,
)

HM = TEST_USERS["hall_manager_headers"]


class TestComplianceGradeDualVariant:
    """dual_variant_calc / compliance_grade_latest_vs_weighted. Two conducted
    inspections (older 95, newer 78)."""

    def _setup(self):
        hall = create_food_hall()
        stall = create_stall(hall["id"])
        # Older inspection first (score 95), then newer (score 78). With the clock
        # unset both share conducted_at, so created_at DESC makes the 78 the newest.
        conduct_inspection(stall["id"], 95, scheduled_for="2026-04-01T09:00:00Z")
        conduct_inspection(stall["id"], 78, scheduled_for="2026-05-01T09:00:00Z")
        return stall

    def test_latest_uses_newest_inspection_score(self, api):
        """PRD §3.4: "Under `LATEST`, the score is simply the newest conducted
        inspection's `score`."
        PRD §3.4: "The resulting letter `grade` is `A` when the score is at least
        90, otherwise `B` at 80 or above, otherwise `C` at 70 or above, otherwise
        `D` at 60 or above, otherwise `F`."

        Design: Difficulty/dual_variant_calc/compliance_grade_latest_vs_weighted
        """
        stall = self._setup()
        data = validate_success(api.get_compliance_grade(stall["id"], "LATEST", HM), 200)
        assert data["score"] == 78
        assert data["grade"] == "C"

    def test_weighted_averages_last_two_inspections(self, api):
        """PRD §3.4: "Under `WEIGHTED`, the score is a weighted average of the
        retained inspections applied newest to oldest: with a single inspection the
        weight is 1.0; with two inspections the weights are 0.6 and 0.4; with three
        the weights are 0.5, 0.3, and 0.2; the score is the sum of each weight times
        its inspection's `score`, rounded half up to a whole number."

        Design: Difficulty/dual_variant_calc/compliance_grade_latest_vs_weighted
        """
        stall = self._setup()
        data = validate_success(api.get_compliance_grade(stall["id"], "WEIGHTED", HM), 200)
        assert data["score"] == 85
        assert data["grade"] == "B"


def test_weighted_single_inspection_equals_score(api):
    """PRD §3.4: "Under `WEIGHTED`, the score is a weighted average of the retained
    inspections applied newest to oldest: with a single inspection the weight is
    1.0; with two inspections the weights are 0.6 and 0.4; with three the weights are
    0.5, 0.3, and 0.2; the score is the sum of each weight times its inspection's
    `score`, rounded half up to a whole number."

    Design: Corner/calculations/compliance_grade_single_inspection_weighted_equals_score
    """
    hall = create_food_hall()
    stall = create_stall(hall["id"])
    conduct_inspection(stall["id"], 82, scheduled_for="2026-04-01T09:00:00Z")

    data = validate_success(api.get_compliance_grade(stall["id"], "WEIGHTED", HM), 200)
    assert data["score"] == 82
    assert data["grade"] == "B"
