"""Injury-rate trend analytics by position x surface."""
import pytest

from test_helpers import (
    create_athlete,
    create_diagnosis_code,
    create_injury_case,
    create_team,
    ingest_session,
    set_clock,
    validate_success,
)


def _analytics(api, team_id, headers, from_date="2026-08-01", to_date="2026-08-31"):
    resp = api.get_injury_rates(
        team_id, headers, params={"from_date": from_date, "to_date": to_date}
    )
    data = validate_success(resp)
    assert isinstance(data.get("groups"), list), "analytics response must carry a groups array"
    return data["groups"]


class TestInjuryRateTrends:
    def test_zero_exposure_groups_omitted(self, api, medical_staff_headers):
        """PRD §3.10: "The rate is the number of injuries multiplied by
        `1000`, divided by the number of exposures, rounded half-up to two
        decimal places."
        PRD §3.10: "Groups with zero exposures are omitted from the response
        entirely."

        One QB/GRASS injury over four QB/GRASS exposures yields 250.00 per
        1000 exposures; the QB/TURF group has no exposures and must be absent.

        Design: Difficulty/boundary_precision_check/trend_empty_exposure_group_omitted
        """
        team = create_team(
            name="Trends", sport="FOOTBALL", season_start_date="2026-08-01",
            season_end_date="2027-02-01",
        )
        athlete = create_athlete(team["id"], position="QB", enrollment_date="2026-08-01")
        dx = create_diagnosis_code(code="S83.5", body_region="KNEE",
                                   severity_class="MODERATE", is_concussion=False)
        set_clock("2026-08-31T00:00:00Z")
        create_injury_case(athlete["id"], dx["id"], occurred_on="2026-08-10",
                           surface="GRASS", mechanism="CONTACT")
        ingest_session(athlete["id"], "2026-08-02", duration_minutes=60, rpe=5)
        ingest_session(athlete["id"], "2026-08-04", duration_minutes=60, rpe=5)
        ingest_session(athlete["id"], "2026-08-06", session_type="GAME",
                       duration_minutes=90, rpe=8)
        ingest_session(athlete["id"], "2026-08-08", session_type="CONDITIONING",
                       duration_minutes=45, rpe=6)

        groups = _analytics(api, team["id"], medical_staff_headers)
        qb_grass = [
            g for g in groups if g.get("position") == "QB" and g.get("surface") == "GRASS"
        ]
        assert len(qb_grass) == 1, "expected exactly one (QB, GRASS) group"
        group = qb_grass[0]
        assert group["exposures"] == 4
        assert group["injuries"] == 1
        assert group["rate_per_1000"] == pytest.approx(250.00, abs=0.005), (
            "1 injury * 1000 / 4 exposures = 250.00"
        )
        assert all(g["exposures"] > 0 for g in groups), (
            "every emitted group must have at least one exposure"
        )
        assert not any(g.get("surface") == "TURF" for g in groups), (
            "zero-exposure groups must be omitted, not reported with rate 0"
        )

    def test_group_with_exposures_but_no_injuries_reports_zero(self, api, medical_staff_headers):
        """PRD §3.10: "The rate is the number of injuries multiplied by
        `1000`, divided by the number of exposures, rounded half-up to two
        decimal places."
        PRD §3.10: "Groups with zero exposures are omitted from the response
        entirely."

        A (QB, GRASS) group with four exposures and no injuries is emitted
        with rate 0.00 — only zero-exposure groups are omitted.

        Design: Difficulty/boundary_precision_check/trend_empty_exposure_group_omitted
        """
        team = create_team(
            name="Trends0", sport="FOOTBALL", season_start_date="2026-08-01",
            season_end_date="2027-02-01",
        )
        athlete = create_athlete(team["id"], position="QB", enrollment_date="2026-08-01")
        set_clock("2026-08-31T00:00:00Z")
        for d in ("2026-08-02", "2026-08-04", "2026-08-06", "2026-08-08"):
            ingest_session(athlete["id"], d, duration_minutes=60, rpe=5)

        groups = _analytics(api, team["id"], medical_staff_headers)
        qb_grass = [
            g for g in groups if g.get("position") == "QB" and g.get("surface") == "GRASS"
        ]
        assert len(qb_grass) == 1
        assert qb_grass[0]["injuries"] == 0
        assert qb_grass[0]["rate_per_1000"] == pytest.approx(0.00, abs=0.005)
        assert not any(g.get("surface") == "TURF" for g in groups)
