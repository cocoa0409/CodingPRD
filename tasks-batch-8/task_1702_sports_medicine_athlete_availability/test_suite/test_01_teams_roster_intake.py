"""Team configuration, athlete enrollment, and injury intake basics."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_athlete,
    assert_injury_case,
    assert_team,
    create_team,
    parse_iso,
    setup_open_case,
    team_payload,
    validate_error,
    validate_success,
)


class TestTeamConfiguration:
    def test_create_team_applies_default_configuration(self, api):
        """PRD §3.1: "Two optional configuration knobs govern downstream
        behavior: `hipaa_mode`, defaulting to `STRICT`, which suppresses
        designation, body-region, and diagnosis detail for non-medical
        audiences regardless of grant scope; and `acwr_variant`, defaulting to
        `ROLLING`, which selects the authoritative ACWR calculation for that
        team."
        PRD §2.4: "The system maintains a logical clock, `current_utc`,
        initialized for every team to exactly `2026-08-01T00:00:00Z`."

        Design: Corner/entities/create_team_applies_defaults
        """
        resp = api.create_team(team_payload(name="Defaults FC"), self._admin())
        team = validate_success(resp, expected_status=201)
        assert_team(team)
        assert team["hipaa_mode"] == "STRICT", (
            f"hipaa_mode default must be STRICT, got {team['hipaa_mode']!r}"
        )
        assert team["acwr_variant"] == "ROLLING", (
            f"acwr_variant default must be ROLLING, got {team['acwr_variant']!r}"
        )
        assert parse_iso(team["current_utc"]) == datetime(2026, 8, 1, tzinfo=timezone.utc), (
            f"current_utc must initialize to 2026-08-01T00:00:00Z, got {team['current_utc']!r}"
        )

    @staticmethod
    def _admin():
        from test_helpers import TEST_USERS

        return TEST_USERS["team_admin"]


class TestAthleteEnrollment:
    def test_create_athlete_initializes_derived_fields(self, api, team_admin_headers):
        """PRD §3.1: "At enrollment the athlete's `roster_status` is `ACTIVE`,
        `availability_tier` is `FULL`, `load_flag` is `NONE`, and
        `acute_chronic_workload_ratio` is `null`."

        Design: Corner/entities/create_athlete_initializes_computed_fields
        """
        team = create_team()
        resp = api.create_athlete(
            {
                "team_id": team["id"],
                "full_name": "New Recruit",
                "position": "F",
                "enrollment_date": "2026-08-01",
            },
            team_admin_headers,
        )
        athlete = validate_success(resp, expected_status=201)
        assert_athlete(athlete)
        assert athlete["roster_status"] == "ACTIVE"
        assert athlete["availability_tier"] == "FULL"
        assert athlete["load_flag"] == "NONE"
        assert athlete["acute_chronic_workload_ratio"] is None, (
            "ACWR must be null at enrollment (no sessions ingested)"
        )

    def test_get_nonexistent_athlete_returns_not_found(self, api, team_admin_headers):
        """PRD §2.8: "A body foreign-key reference that is missing, or that
        points to an entity belonging to a different team, is rejected with
        `ERR_NOT_FOUND` (HTTP 404), indistinguishable from a missing path
        resource."

        Design: Corner/entities/get_nonexistent_resource_returns_not_found
        """
        resp = api.get_athlete(NON_EXISTENT_UUID, team_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestInjuryIntake:
    def test_intake_snapshots_diagnosis_code_attributes(self, api):
        """PRD §3.2: "The referenced diagnosis code contributes two immutable
        snapshots at intake: `severity_class_snapshot` and
        `is_concussion_snapshot`, copied from the code's `severity_class` and
        `is_concussion` fields so that later edits to the diagnosis code do not
        retroactively alter the case."

        Design: Corner/entities/injury_case_snapshots_immune_to_diagnosis_code_edit
        """
        sc = setup_open_case(
            sport="FOOTBALL",
            position="QB",
            severity_class="SEVERE",
            is_concussion=True,
            dx_code="S06.0X1A",
            body_region="HEAD_NECK",
            season=("2026-08-01", "2027-02-01"),
        )
        case = sc["case"]
        assert_injury_case(case)
        assert case["severity_class_snapshot"] == "SEVERE", (
            "severity_class_snapshot must be copied from the diagnosis code at intake"
        )
        assert case["is_concussion_snapshot"] is True, (
            "is_concussion_snapshot must be copied from the diagnosis code at intake"
        )
        assert case["status"] == "OPEN"
