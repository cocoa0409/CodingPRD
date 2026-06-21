"""Portfolio prosecution risk score: the snapshot variant versus the projected
variant that additionally counts blown-but-unswept PENDING deadlines.

Source: Difficulty/dual_variant_calc.
"""
from test_helpers import (
    api_client,
    validate_success,
    setup_application_with_outstanding_oa,
    set_clock,
    examiner_headers,
)


class TestRiskScoreSnapshotVsProjected:
    """For an applicant with one OUTSTANDING OfficeAction whose mirrored deadline
    is already past (clock advanced past it but still PENDING), snapshot=15 and
    projected=30."""

    def _setup(self):
        # USE TEAS_STANDARD app, examined, one OUTSTANDING non-final OA issued
        # 2026-01-01 (response_deadline 2026-04-01); clock advanced to 2026-04-02.
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="MERELY_DESCRIPTIVE", is_final=False,
            filing_basis="USE", mark_text="ORBIT")
        set_clock("2026-04-02T00:00:00Z")
        return base

    def test_snapshot_risk_score_is_15(self, api):
        """PRD §3.7: "The snapshot variant sums weighted counts over the applicant's
        portfolio: 15 points for each OfficeAction with status OUTSTANDING across the
        applicant's applications"

        Design: Difficulty/dual_variant_calc/risk_score_snapshot_vs_projected_diverges
        """
        base = self._setup()
        res = api.get_risk_score(base["applicant"]["id"], examiner_headers())
        data = validate_success(res, 200)
        assert data["risk_score"] == 15, (
            f"snapshot should count the one OUTSTANDING OA (15), got {data['risk_score']}")

    def test_projected_risk_score_is_30(self, api):
        """PRD §3.7: "When the caller requests the projected variant by passing
        include_pending_deadlines as true, the computation additionally adds 15
        points for each PENDING DocketDeadline whose due_at is already before the
        current instant — a deadline blown but not yet swept to MISSED"

        Design: Difficulty/dual_variant_calc/risk_score_snapshot_vs_projected_diverges
        """
        base = self._setup()
        res = api.get_risk_score(
            base["applicant"]["id"], examiner_headers(),
            params={"include_pending_deadlines": "true"})
        data = validate_success(res, 200)
        assert data["risk_score"] == 30, (
            f"projected should add 15 for the blown-but-pending OA deadline (15+15=30), "
            f"got {data['risk_score']}")
