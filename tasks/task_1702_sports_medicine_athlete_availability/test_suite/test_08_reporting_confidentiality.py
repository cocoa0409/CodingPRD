"""Availability reporting and confidentiality redaction."""
from test_helpers import (
    ApiErrorId,
    assert_availability_report,
    availability_report_payload,
    create_grant,
    record_status_entry,
    setup_open_case,
    validate_error,
    validate_success,
)


def _row_for(report, athlete_id):
    rows = [r for r in report["rows"] if r["athlete_id"] == athlete_id]
    assert len(rows) == 1, f"expected exactly one report row for athlete {athlete_id}"
    return rows[0]


class TestMedicalAudience:
    def test_medical_report_is_unredacted(self, api, medical_staff_headers):
        """PRD §3.9: "The `rows` array contains one object per athlete with
        `athlete_id`, `availability_tier`, and optionally `designation`,
        `body_region`, and `diagnosis_detail`. For a `MEDICAL` audience all
        fields are always visible."

        Design: Corner/endpoints/availability_report_medical_audience_unredacted
        """
        sc = setup_open_case(clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02")
        record_status_entry(sc["case"]["id"], "2026-08-03", designation="OUT")
        resp = api.create_availability_report(
            availability_report_payload(sc["team"]["id"], "MEDICAL"),
            medical_staff_headers,
        )
        report = validate_success(resp, expected_status=201)
        assert_availability_report(report)
        assert report["generated_for_role"] == "MEDICAL"
        row = _row_for(report, sc["athlete"]["id"])
        assert row["availability_tier"] == "OUT"
        for field in ("designation", "body_region", "diagnosis_detail"):
            assert field in row, (
                f"MEDICAL audience must see {field}; row keys: {sorted(row.keys())}"
            )


class TestStrictModeOverride:
    def test_strict_mode_downgrades_general_grant(self, api, coaching_staff_headers):
        """PRD §3.9: "When the team's `hipaa_mode` is `STRICT` — rather than
        `STANDARD` — the override is applied last: `diagnosis_detail` is never
        exposed to non-medical audiences, and `GENERAL` scope is downgraded to
        `TIER_ONLY`, suppressing `designation` and `body_region`."

        Design: Corner/cross_cutting_layers/confidentiality_strict_mode_downgrades_general_grant
        """
        sc = setup_open_case(
            clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02",
            hipaa_mode="STRICT",
        )
        record_status_entry(
            sc["case"]["id"], "2026-08-03", designation="LIMITED",
            symptom_free=True, functional_test_score=65,
        )
        create_grant(
            sc["athlete"]["id"], grantee_role="COACHING", scope="GENERAL",
            effective_from="2026-08-01", effective_to="2026-12-31",
        )
        resp = api.create_availability_report(
            availability_report_payload(sc["team"]["id"], "COACHING"),
            coaching_staff_headers,
        )
        report = validate_success(resp, expected_status=201)
        row = _row_for(report, sc["athlete"]["id"])
        assert row["availability_tier"] == "LIMITED"
        assert "designation" not in row, (
            "STRICT mode downgrades GENERAL to TIER_ONLY: designation suppressed"
        )
        assert "body_region" not in row, (
            "STRICT mode downgrades GENERAL to TIER_ONLY: body_region suppressed"
        )
        assert "diagnosis_detail" not in row, (
            "diagnosis_detail is never exposed to non-medical audiences under STRICT"
        )


class TestAudienceValidation:
    def test_invalid_audience_rejected(self, api, medical_staff_headers):
        """PRD §3.9: "An availability report is generated for a team and an
        `audience` (`COACHING`, `FRONT_OFFICE`, or `MEDICAL`; any other
        audience is rejected with `ERR_AUDIENCE_INVALID`)."

        Design: Corner/validations/invalid_audience_rejected_on_report
        """
        sc = setup_open_case()
        resp = api.create_availability_report(
            {"team_id": sc["team"]["id"], "audience": "PUBLIC"},
            medical_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIENCE_INVALID)
