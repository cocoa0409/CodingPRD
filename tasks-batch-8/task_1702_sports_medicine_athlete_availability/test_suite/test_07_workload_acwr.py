"""Workload ingestion: session_load/exposure derivation, ACWR gate, load flags."""
import pytest

from test_helpers import (
    assert_workload_session,
    create_athlete,
    create_team,
    ingest_session,
    set_clock,
    setup_acwr_athlete,
    validate_success,
    workload_session_payload,
)

# Fixed chronic-window base: 2026-07-05/07-12/07-19 plus six acute-window days
# (07-22..07-27) at load 100; today is 2026-07-28 (PRD §3.6 windows).
_BASE_1250 = [
    ("2026-07-05", 400),
    ("2026-07-12", 400),
    ("2026-07-19", 450),
    ("2026-07-22", 100),
    ("2026-07-23", 100),
    ("2026-07-24", 100),
    ("2026-07-25", 100),
    ("2026-07-26", 100),
    ("2026-07-27", 100),
]


class TestLoadFlagBoundaries:
    def test_ratio_at_spike_threshold_is_spike(self, api, performance_staff_headers):
        """PRD §3.6: "The boundary is inclusive at both thresholds: a rounded
        ratio of exactly `1.500` yields `SPIKE`, while `1.499` yields
        `ELEVATED`."

        Chronic sum 2000 (400+400+450+600+150), acute 750: 750/(2000/4) =
        exactly 1.500.

        Design: Difficulty/boundary_precision_check/load_flag_threshold_inclusive_boundaries
        """
        sc = setup_acwr_athlete(_BASE_1250 + [("2026-07-28", 150)])
        ratio = sc["athlete"]["acute_chronic_workload_ratio"]
        assert ratio == pytest.approx(1.500, abs=1e-6), (
            f"expected ACWR 1.500, got {ratio}"
        )
        assert sc["athlete"]["load_flag"] == "SPIKE", (
            "a rounded ratio of exactly 1.500 is SPIKE (inclusive boundary)"
        )

    def test_ratio_at_elevated_threshold_is_elevated(self, api, performance_staff_headers):
        """PRD §3.6: "If the ratio is at least `1.300` but less than `1.500`,
        `load_flag` is `ELEVATED`."

        Chronic sum 2000 (400+400+550+600+50), acute 650: 650/(2000/4) =
        exactly 1.300.

        Design: Difficulty/boundary_precision_check/load_flag_threshold_inclusive_boundaries
        """
        history = [
            ("2026-07-05", 400),
            ("2026-07-12", 400),
            ("2026-07-19", 550),
            ("2026-07-22", 100),
            ("2026-07-23", 100),
            ("2026-07-24", 100),
            ("2026-07-25", 100),
            ("2026-07-26", 100),
            ("2026-07-27", 100),
            ("2026-07-28", 50),
        ]
        sc = setup_acwr_athlete(history)
        ratio = sc["athlete"]["acute_chronic_workload_ratio"]
        assert ratio == pytest.approx(1.300, abs=1e-6)
        assert sc["athlete"]["load_flag"] == "ELEVATED", (
            "a rounded ratio of exactly 1.300 is ELEVATED (inclusive boundary)"
        )

    def test_ratio_rounding_to_1499_is_elevated_not_spike(self, api, performance_staff_headers):
        """PRD §3.6: "The boundary is inclusive at both thresholds: a rounded
        ratio of exactly `1.500` yields `SPIKE`, while `1.499` yields
        `ELEVATED`."
        PRD §3.6: "The ratio is the acute load divided by the chronic load,
        rounded half-up to three decimal places"

        Acute 749, chronic sum 1999: 749/499.75 = 1.49874..., which rounds
        half-up to 1.499 — ELEVATED, just under the SPIKE threshold.

        Design: Difficulty/boundary_precision_check/load_flag_threshold_inclusive_boundaries
        """
        sc = setup_acwr_athlete(_BASE_1250 + [("2026-07-28", 149)])
        ratio = sc["athlete"]["acute_chronic_workload_ratio"]
        assert ratio == pytest.approx(1.499, abs=1e-6), (
            f"749/(1999/4) rounds half-up to 1.499, got {ratio}"
        )
        assert sc["athlete"]["load_flag"] == "ELEVATED"

    def test_ratio_below_elevated_threshold_is_none(self, api, performance_staff_headers):
        """PRD §3.6: "If the ratio is at least `1.300` but less than `1.500`,
        `load_flag` is `ELEVATED`. Otherwise `load_flag` is `NONE`."

        Acute 600, chronic sum 1850: 600/462.5 = 1.2972..., below 1.300.

        Design: Difficulty/boundary_precision_check/load_flag_threshold_inclusive_boundaries
        """
        sc = setup_acwr_athlete(_BASE_1250)  # 9 sessions, no final-day load
        ratio = sc["athlete"]["acute_chronic_workload_ratio"]
        assert ratio == pytest.approx(1.297, abs=0.001), (
            f"600/(1850/4) rounds to 1.297, got {ratio}"
        )
        assert sc["athlete"]["load_flag"] == "NONE"


class TestAcwrSessionGate:
    def test_acwr_null_below_min_sessions(self, api, performance_staff_headers):
        """PRD §3.6: "The ratio is also `null` when fewer than `8` qualifying
        sessions exist in the chronic window."
        PRD §3.6: "`REHAB_SESSION` is excluded from exposure denominators and
        ACWR windows."
        PRD §3.6: "If the ratio is `null`, `load_flag` is `NONE`."

        Three qualifying PRACTICE sessions plus two excluded REHAB_SESSION
        records leave the qualifying count at 3 (< 8).

        Design: Corner/calculations/acwr_null_below_min_sessions_gate
        """
        team = create_team(
            name="Gate", sport="FOOTBALL", season_start_date="2026-07-01",
            season_end_date="2027-02-01", acwr_variant="ROLLING",
        )
        athlete = create_athlete(team["id"], position="QB", enrollment_date="2026-07-01")
        set_clock("2026-07-28T00:00:00Z")
        for d in ("2026-07-26", "2026-07-27", "2026-07-28"):
            ingest_session(athlete["id"], d, duration_minutes=100, rpe=5)
        for d in ("2026-07-27", "2026-07-28"):
            ingest_session(
                athlete["id"], d, session_type="REHAB_SESSION",
                surface="TRAINING_ROOM", duration_minutes=60, rpe=3,
            )
        data = validate_success(api.get_athlete(athlete["id"], performance_staff_headers))
        assert data["acute_chronic_workload_ratio"] is None, (
            "fewer than 8 qualifying sessions must yield a null ACWR"
        )
        assert data["load_flag"] == "NONE"


class TestSessionDerivations:
    def test_session_load_and_exposure_rules(self, api, performance_staff_headers):
        """PRD §3.6: "The session's `session_load` is computed as
        `duration_minutes` multiplied by `rpe`. A session counts as exposure
        when `session_type` is `PRACTICE`, `GAME`, or `CONDITIONING` and
        `duration_minutes` is at least `10`; `REHAB_SESSION` is excluded from
        exposure denominators and ACWR windows."

        Design: Corner/calculations/session_load_and_exposure_derivation
        """
        team = create_team(
            name="Loads", sport="FOOTBALL", season_start_date="2026-07-01",
            season_end_date="2027-02-01",
        )
        athlete = create_athlete(team["id"], position="QB", enrollment_date="2026-07-01")
        set_clock("2026-07-28T00:00:00Z")

        s1 = validate_success(
            api.create_workload_session(
                workload_session_payload(
                    athlete["id"], "2026-07-28", duration_minutes=90, rpe=7
                ),
                performance_staff_headers,
            ),
            expected_status=201,
        )
        assert_workload_session(s1)
        assert s1["session_load"] == 630, "session_load = duration_minutes * rpe"
        assert s1["counts_as_exposure"] is True

        s2 = validate_success(
            api.create_workload_session(
                workload_session_payload(
                    athlete["id"], "2026-07-28", duration_minutes=5, rpe=9
                ),
                performance_staff_headers,
            ),
            expected_status=201,
        )
        assert s2["counts_as_exposure"] is False, (
            "duration below the 10-minute exposure floor must not count"
        )

        s3 = validate_success(
            api.create_workload_session(
                workload_session_payload(
                    athlete["id"], "2026-07-28", session_type="REHAB_SESSION",
                    surface="TRAINING_ROOM", duration_minutes=60, rpe=5,
                ),
                performance_staff_headers,
            ),
            expected_status=201,
        )
        assert s3["counts_as_exposure"] is False, (
            "REHAB_SESSION is excluded from exposure regardless of duration"
        )
