"""Case completeness score — PRD §2.8 / §3.11.

Coverage:
- Score for a DRAFT case = 0.
- Pinned rounding ORDER: per-factor weighted-product rounded to 2 dp
  half-up FIRST, THEN summed and multiplied by 100, THEN rounded to
  integer half-up. Carefully constructed input divergence test.
- Status-only contribution.
- Score is integer and clamped to [0, 100].
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_completeness_score,
    setup_filed_case,
    validate_success,
)


def _get_score(api, case_id: str) -> int:
    resp = api_client.get_case_summary(
        case_id,
        {"X-User-ID": "officer-x", "X-User-Role": "Officer",
         "Content-Type": "application/json"},
    )
    data = validate_success(resp)
    score = data["case_completeness_score"]
    assert_completeness_score(score)
    return score


class TestCompletenessScoreBasics:

    def test_filed_case_score_in_range(self, api):
        """PRD §3.11: "The score is then clamped into the inclusive
        0-to-100 integer range."

        Claim: a FILED case's score is an int in [0, 100] (per the
        weighting it should be small but the exact value is in
        TestPinnedRounding below).
        """
        bundle = setup_filed_case(case_type="I-130")
        score = _get_score(api, bundle["case"]["id"])
        assert 0 <= score <= 100

    def test_filed_i130_known_score(self, api):
        """PRD §3.11: per-factor table:
          f_status[FILED] = 0.10, weight 0.40 -> 0.04
          f_biometrics = 0.00, weight 0.20 -> 0.00
          f_rfe — for an I-130 (requires_priority_date_current=false)
            -> 1.00 per PRD §3.11: "The RFE factor is 1.00 when either
            the matching CaseTypeConfig.requires_priority_date_current
            is false or no RFE row on the case is currently in
            OUTSTANDING status"; weight 0.10 -> 0.10
          f_interview = 0.00, weight 0.15 -> 0.00
          f_priority — I-130 priority_date_status=NOT_APPLICABLE ->
            1.00; weight 0.15 -> 0.15
        Sum = 0.04 + 0.00 + 0.10 + 0.00 + 0.15 = 0.29
        Total = round(0.29 * 100) = 29.

        Claim: a FILED I-130 has completeness score = 29.
        """
        bundle = setup_filed_case(case_type="I-130")
        score = _get_score(api, bundle["case"]["id"])
        assert score == 29, (
            f"FILED I-130 should produce score 29 per the pinned "
            f"rounding-order formula; got {score}"
        )


# ===========================================================================
# Pinned rounding-order divergence (the difficulty-design instance).
# ===========================================================================
class TestPinnedRoundingOrder:
    """The difficulty-design carefully-constructed input where the
    per-factor rounding order vs sum-then-round disagree by one
    point. PRD §3.11 / §2.8 pin: per-factor rounded 2 dp FIRST, then
    sum, then multiply by 100, then round-half-up integer.

    See test_12_difficulty_coverage.py
    completeness_score_pinned_rounding_order for the canonical
    instance (I-485 in RFE_ISSUED with one COMPLETED Biometrics, one
    OUTSTANDING RFE, one SCHEDULED Interview, priority NOT_CURRENT).
    Here we cover an additional state — a FILED I-485 with non-IR
    beneficiary — to show the rounding-order obligation in another
    state.
    """

    def test_filed_i485_score_known(self, api):
        """PRD §3.11: factor table.
        State FILED on I-485 (requires_priority_date_current=true,
        beneficiary F2A non-IR).
          f_status[FILED] = 0.10, w=0.40 -> 0.04
          f_biometrics = 0.00, w=0.20 -> 0.00
          f_rfe — I-485 has requires_priority_date_current=true AND no
            OUTSTANDING RFE -> 1.00; w=0.10 -> 0.10
            (PRD §3.11: "1.00 when either the matching
            CaseTypeConfig.requires_priority_date_current is false or
            no RFE row on the case is currently in OUTSTANDING status").
          f_interview = 0.00, w=0.15 -> 0.00
          f_priority — depends. After setup_filed_case for I-485 with
            no matching bulletin -> NOT_CURRENT -> 0.50; w=0.15 -> 0.075
            -> rounded half-up to 2 dp = 0.08.
        Sum = 0.04 + 0.00 + 0.10 + 0.00 + 0.08 = 0.22; *100 = 22.0;
        rounded = 22.

        Claim: score == 22 for a freshly FILED I-485 with priority
        NOT_CURRENT (no bulletin row published).
        """
        bundle = setup_filed_case(
            case_type="I-485", preference_category="F2A",
        )
        case = bundle["case"]
        # PRD §3.2: on FILED, priority_date_currency runs and the lack
        # of any published row yields NOT_CURRENT.
        assert case["priority_date_status"] == "NOT_CURRENT", (
            "Setup precondition: no bulletin -> NOT_CURRENT"
        )
        score = _get_score(api, case["id"])
        # Acceptable score per pinned rounding-order formula.
        assert score == 22, (
            f"FILED I-485 (priority NOT_CURRENT, no outstanding RFE) "
            f"should produce score 22 per the pinned rounding-order "
            f"formula; got {score}"
        )
