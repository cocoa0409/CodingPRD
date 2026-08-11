"""Validation rules: schema, ranges, uniqueness, temporal pairs (PRD §2.9, §3)."""
from test_helpers import (
    ApiErrorId,
    GM_HEADERS,
    MED_HEADERS,
    NON_EXISTENT_UUID,
    api_client,
    area_headers,
    create_prospect,
    create_report,
    create_scout,
    director_headers,
    create_director,
    make_board_ready_prospect,
    validate_error,
    validate_success,
)


class TestSchemaValidation:
    def test_report_create_missing_required_grade(self, api):
        """PRD §2.9 item 3: "Request schema — required fields present, types
        correct, enum values in range, end strictly after start on temporal
        pairs, integers non-negative where declared (`ERR_VALIDATION`)."
        `raw_grade` is a required input on report creation (PRD §3.3: "by
        supplying a `raw_grade` on the team's 1.00–9.00 scale and a
        `scheme_fit` multiplier between 0.00 and 1.50").

        Design: Corner/validations/report_create_missing_required_grade
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        resp = api_client.create_report(
            p1["id"], {"scheme_fit": 1.00}, area_headers(s1)
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400

    def test_flag_create_invalid_enum_severity(self, api):
        """PRD §3.4: "A confidential flag is raised against a prospect by
        supplying a `flag_type` of `MEDICAL` or `CHARACTER`, a `severity` of
        `LOW` or `HIGH`, and a free-text `detail` narrative." PRD §2.9 item
        3: "enum values in range" violations are `ERR_VALIDATION`. `EXTREME`
        is outside the declared severity enum.

        Design: Corner/validations/flag_create_invalid_enum_severity
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        resp = api_client.create_flag(
            p1["id"],
            {"flag_type": "MEDICAL", "severity": "EXTREME", "detail": "x"},
            MED_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400

    def test_video_tag_end_before_start_rejected(self, api):
        """PRD §3.3: "each tag carries a `clip_url`, an integer `start_sec` at
        or above zero, an integer `end_sec` strictly greater than `start_sec`,
        and a `tag` category of `SCHEME`, `ATHLETICISM`, `TECHNIQUE`, or
        `CHARACTER`." §2.9 item 3: "end strictly after start on temporal
        pairs" violations are `ERR_VALIDATION`. end_sec == start_sec fails.

        Design: Corner/validations/video_tag_end_before_start_rejected
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        resp = api_client.create_video_tag(
            r1["id"],
            {"clip_url": "https://video.example/c1", "start_sec": 30, "end_sec": 30, "tag": "SCHEME"},
            area_headers(s1),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400


class TestRangeValidation:
    def test_raw_grade_out_of_range_rejected(self, api):
        """PRD §3.3: "An `AreaScout` authors a `ScoutingReport` against a
        prospect by supplying a `raw_grade` on the team's 1.00–9.00 scale and
        a `scheme_fit` multiplier between 0.00 and 1.50, both with at most 2
        decimal places; values outside those ranges are rejected with
        `ERR_GRADE_OUT_OF_RANGE`." raw_grade 9.50 exceeds 9.00.

        Design: Corner/validations/raw_grade_out_of_range_rejected
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        resp = api_client.create_report(
            p1["id"], {"raw_grade": 9.50, "scheme_fit": 1.00}, area_headers(s1)
        )
        validate_error(resp, ApiErrorId.ERR_GRADE_OUT_OF_RANGE)
        assert resp.status_code == 422

    def test_weight_zero_rejected(self, api):
        """PRD §3.1: "a weight must be strictly greater than zero, and an
        attempt to set a non-positive weight is rejected with
        `ERR_WEIGHT_INVALID`."

        Design: Corner/validations/weight_zero_rejected
        """
        s1 = create_scout(level="AREA", full_name="S")
        d1 = create_director(full_name="D")
        resp = api_client.set_scout_weight(
            s1["id"], {"new_weight": 0}, director_headers(d1)
        )
        validate_error(resp, ApiErrorId.ERR_WEIGHT_INVALID)
        assert resp.status_code == 422


class TestUniqueness:
    def test_duplicate_report_rejected(self, api):
        """PRD §3.3: "At most one report per scout per prospect exists: a
        second creation attempt by the same scout against the same prospect is
        rejected with `ERR_DUPLICATE_REPORT`."

        Design: Corner/validations/duplicate_report_rejected
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        resp = api_client.create_report(
            p1["id"], {"raw_grade": 8.00, "scheme_fit": 1.00}, area_headers(s1)
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)
        assert resp.status_code == 409


class TestOutcomeStateGate:
    def test_outcome_before_drafted_rejected(self, api):
        """PRD §3.9: "a `GeneralManager` records an `OutcomeRecord` for a
        `DRAFTED` prospect — recording against any other evaluation state is
        rejected with `ERR_OUTCOME_NOT_DRAFTED`"."

        Design: Corner/validations/outcome_before_drafted_rejected
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="D")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P", position="QB", college="A")
        resp = api_client.create_outcome(
            p1["id"],
            {"season_year": 2026, "games_started": 5, "pro_bowl": False, "outcome_percentile": 40},
            GM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_OUTCOME_NOT_DRAFTED)
        assert resp.status_code == 409


class TestReportCreateRequiresScoutingPhase:
    """Difficulty: cross_entity_state_dependency/report_create_requires_scouting_phase."""

    def _setup_board_ready(self):
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        s2 = create_scout(level="AREA", full_name="S2", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="Dir One")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="Ready Guy", position="OT", college="State U")
        return s1, s2, d1, p1

    def test_report_create_on_board_ready_rejected(self, api):
        """PRD §3.3: "Report creation is permitted only while the prospect's
        `evaluation_status` is `NEW`, `SCOUTING`, or `EVALUATED` — a prospect
        already `BOARD_READY`, `DRAFTED`, or `ARCHIVED` accepts no new
        reports." §2.9 item 5 makes this a state guard reported as
        `ERR_INVALID_STATE` (HTTP 409).

        Design: Difficulty/cross_entity_state_dependency/report_create_requires_scouting_phase
        """
        _, s2, _, p1 = self._setup_board_ready()
        resp = api_client.create_report(
            p1["id"], {"raw_grade": 8.00, "scheme_fit": 1.00}, area_headers(s2)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_report_create_allowed_in_evaluated(self, api):
        """PRD §3.3: "Report creation is permitted only while the prospect's
        `evaluation_status` is `NEW`, `SCOUTING`, or `EVALUATED`". EVALUATED
        is in the allowed set; a second scout's report succeeds there.

        Design: Difficulty/cross_entity_state_dependency/report_create_requires_scouting_phase
        """
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        s2 = create_scout(level="AREA", full_name="S2", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="Dir One")
        p1 = create_prospect(s1, full_name="P", position="OT", college="State U")
        from test_helpers import create_and_lock_report, advance_prospect
        create_and_lock_report(p1["id"], s1, d1, raw_grade=7.00, scheme_fit=1.00)
        advance_prospect(p1["id"], "EVALUATED", d1)
        resp = api_client.create_report(
            p1["id"], {"raw_grade": 8.00, "scheme_fit": 1.00}, area_headers(s2)
        )
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "DRAFT"


class TestNotFound:
    def test_prospect_get_not_found_returns_404(self, api):
        """PRD §2.8: "the system validates existence of every referenced
        identifier in left-to-right order, rejecting with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not resolve."

        Design: Corner/entities/prospect_get_not_found_returns_404
        """
        s1 = create_scout(level="AREA", full_name="S1")
        resp = api_client.get_prospect(NON_EXISTENT_UUID, area_headers(s1))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestUnauthenticated:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        string that is not one of these four, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        # No X-User-ID / X-User-Role headers at all.
        resp = api_client.list_prospects(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401
