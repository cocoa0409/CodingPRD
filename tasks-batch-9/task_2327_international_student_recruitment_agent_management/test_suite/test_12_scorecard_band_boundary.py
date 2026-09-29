"""The top performance band is entered at exactly 0.8500.

A perfect yield and a perfect persistence rate carry 0.80 of the composite; the
remaining 0.20 is the quality index.  Three flagged documents out of four
reviewed give a quality index of 0.2500 and a composite of exactly 0.8500.  One
more flagged document takes the composite to 0.8400 and the band down a step.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_rate_4dp, assert_score_2dp


@pytest.fixture()
def cohort_with_flagged_documents(client):
    """One perfectly persisted file carrying a deliberately poor document set."""
    partner = fx.build_active_partner(
        client,
        program_overrides={
            "code": "FOUND-2026",
            "name": "Foundation Pathway",
            "level": C.LEVEL_UNDERGRADUATE,
            "annual_tuition_cents": 1000000,
            "term_start_date": "2026-08-03",
            "census_date": "2026-08-06",
            "persistence_check_date": "2026-08-10",
            "commission_eligible": False,
        },
    )
    admitted = fx.build_admitted_application(
        client,
        partner,
        student_ref="STU-5001",
        passport_hash="hash-passport-5001",
        applicant_user_id="applicant-5001",
    )

    flagging_signals = [
        C.SIGNAL_ISSUER_UNVERIFIED,
        C.SIGNAL_TRANSCRIPT_ANOMALY,
        C.SIGNAL_TRANSLATION_MISMATCH,
    ]
    for doc_type, content_hash, issuer in (
        (C.DOC_TRANSCRIPT, "hash-transcript-5001", "Regional Board"),
        (C.DOC_FINANCIAL_PROOF, "hash-finance-5001", "Unknown Cooperative Bank"),
        (C.DOC_SPONSOR_LETTER, "hash-sponsor-5001", "Unknown Sponsor"),
    ):
        fx.upload_document(
            client,
            partner["agency_id"],
            admitted["application_id"],
            doc_type=doc_type,
            content_hash=content_hash,
            issuer_name=issuer,
            declared_signals=flagging_signals,
        )

    # Auto-flagging each upload set the application's `integrity_hold`, and a
    # derived mutation increments the touched resource's own `version`, so the
    # registrar must re-read the frontier before appending a milestone.
    version = fx.application_version(client, admitted["application_id"])
    for milestone, event_date in (
        (C.MILESTONE_DEPOSIT_PAID, "2026-08-03"),
        (C.MILESTONE_ENROLLED, "2026-08-04"),
        (C.MILESTONE_CENSUS_CONFIRMED, "2026-08-06"),
        (C.MILESTONE_PERSISTED, "2026-08-10"),
    ):
        fx.set_clock(client, f"{event_date}T00:00:00Z")
        updated = fx.register_milestone(
            client, admitted["application_id"], milestone, event_date, version
        )
        version = updated["version"]

    fx.set_clock(client, "2026-08-11T00:00:00Z")

    return {
        "partner": partner,
        "agency_id": partner["agency_id"],
        "application_id": admitted["application_id"],
        "flagging_signals": flagging_signals,
    }


class TestScorecardBandBoundary:
    def test_a_composite_of_exactly_the_band_floor_earns_the_top_tier(
        self, client, cohort_with_flagged_documents
    ):
        """0.45 plus 0.35 plus 0.20 times 0.2500 is 0.8500, and that is PLATINUM.

        "`quality_index` is one minus `flagged_document_count` divided by
        `reviewed_document_count`, or 1.0000 when no document was ever reviewed"

        "`composite_score` is then built from the *already-rounded* rates, with
        `yield_rate` weighted 0.45, `persistence_rate` weighted 0.35 and
        `quality_index` weighted 0.20"

        "`tier` is the band of `composite_score`: `PLATINUM` at or above 0.8500,
        `GOLD` at or above 0.7000 but below 0.8500"

        Design: Difficulty/boundary_precision_check/scorecard_composite_platinum_band_at_exactly_zero_point_eight_five
        """
        env = cohort_with_flagged_documents

        scorecard = fx.run_scorecard(
            client, env["agency_id"], "2026-08-01", "2026-08-11"
        )
        assert scorecard["submitted_count"] == 1
        assert scorecard["enrolled_count"] == 1
        assert scorecard["persisted_count"] == 1
        assert scorecard["reviewed_document_count"] == 4
        assert scorecard["flagged_document_count"] == 3
        assert_rate_4dp(scorecard["yield_rate"], 1.0000, "yield_rate")
        assert_rate_4dp(scorecard["persistence_rate"], 1.0000, "persistence_rate")
        assert_rate_4dp(scorecard["quality_index"], 0.2500, "quality_index")
        assert_rate_4dp(scorecard["composite_score"], 0.8500, "composite_score")
        assert scorecard["tier"] == C.TIER_PLATINUM
        assert scorecard["posture_action_applied"] == C.POSTURE_ACTION_NONE

    def test_one_ten_thousandth_below_the_floor_drops_a_band(
        self, client, cohort_with_flagged_documents
    ):
        """Four flagged of five reviewed gives 0.2000, 0.8400 and GOLD.

        "`tier` is the band of `composite_score`: `PLATINUM` at or above 0.8500,
        `GOLD` at or above 0.7000 but below 0.8500"

        "Writing a scorecard also refreshes the agency's `current_tier`, which is
        the `tier` of that agency's scorecard with the greatest `period_end_date`,
        ties broken by `created_at` descending"

        Design: Difficulty/boundary_precision_check/scorecard_composite_platinum_band_at_exactly_zero_point_eight_five
        """
        env = cohort_with_flagged_documents

        fx.run_scorecard(client, env["agency_id"], "2026-08-01", "2026-08-11")

        fx.upload_document(
            client,
            env["agency_id"],
            env["application_id"],
            doc_type=C.DOC_TRANSCRIPT,
            content_hash="hash-transcript-5002",
            issuer_name="Regional Board",
            declared_signals=env["flagging_signals"],
        )

        second = fx.run_scorecard(
            client, env["agency_id"], "2026-08-01", "2026-08-11"
        )
        assert second["reviewed_document_count"] == 5
        assert second["flagged_document_count"] == 4
        assert_rate_4dp(second["quality_index"], 0.2000, "quality_index")
        assert_rate_4dp(second["composite_score"], 0.8400, "composite_score")
        assert second["tier"] == C.TIER_GOLD

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["current_tier"] == C.TIER_GOLD, (
            "the later created_at must win the period_end_date tie-break"
        )
        assert agency["compliance_posture"] == C.POSTURE_GOOD_STANDING
        assert_score_2dp(agency["rolling_risk_score"], 0.00, "rolling_risk_score")
