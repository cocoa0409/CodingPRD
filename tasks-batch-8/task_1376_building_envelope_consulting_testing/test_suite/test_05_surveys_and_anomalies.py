"""Surveys, anomaly triage, risk-score accumulation, and posture derivation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_anomaly,
    create_active_engagement,
    create_anomaly,
    create_assembly,
    create_completed_survey,
    create_survey,
    create_survey_payload,
    get_engagement,
    verify_anomaly,
    validate_error,
    validate_success,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]
FT = TEST_USERS["field_technician_headers"]


class TestSurveyDeltaTBoundary:

    def test_survey_imaging_delta_t_boundary(self):
        """PRD §3.5: "Completion requires the posture to be other than `FROZEN`
        (`ERR_ENGAGEMENT_FROZEN`) and, for the imaging modalities, a real
        thermal contrast: when the `survey_type` is `THERMAL_IMAGING` or
        `COMBINED`, the recorded `ambient_delta_t_c` must be at least 3.0
        degrees Celsius, or completion is rejected with
        `ERR_IMAGING_DELTA_T_INSUFFICIENT` (HTTP 409). A pure `MOISTURE` survey
        carries no such condition."

        Design: Corner/state_machines/survey_imaging_delta_t_boundary
        """
        eng = create_active_engagement(name="ES")
        asm = create_assembly(eng["id"], tag="AS", assembly_type="ROOFING",
                              design_u_factor=0.8,
                              required_airtightness_lps_m2=3.0)
        s1 = create_survey(eng["id"], asm["id"], survey_type="THERMAL_IMAGING",
                           ambient_delta_t_c=2.9)
        s2 = create_survey(eng["id"], asm["id"], survey_type="THERMAL_IMAGING",
                           ambient_delta_t_c=3.0)
        s3 = create_survey(eng["id"], asm["id"], survey_type="MOISTURE",
                           ambient_delta_t_c=0.5)

        resp = api_client.complete_survey(eng["id"], s1["id"], FT)
        validate_error(resp, ApiErrorId.ERR_IMAGING_DELTA_T_INSUFFICIENT)
        data = validate_success(api_client.complete_survey(eng["id"], s2["id"], FT),
                                200)
        assert data["status"] == "COMPLETED"
        data = validate_success(api_client.complete_survey(eng["id"], s3["id"], FT),
                                200)
        assert data["status"] == "COMPLETED"


class TestAnomalyParentageAndDismissal:

    def test_anomaly_xor_constraint_enforced(self):
        """PRD §3.6: "A `Consultant` raises one against exactly one parent:
        either the `field_test_id` of a field test or the `survey_id` of a
        survey. Supplying both, or neither, violates the parentage rule and is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/anomaly_xor_constraint_enforced
        """
        eng = create_active_engagement(name="EX")
        asm = create_assembly(eng["id"], tag="AX", assembly_type="MASONRY",
                              design_u_factor=1.0,
                              required_airtightness_lps_m2=2.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        # Neither parent set.
        resp = api_client.create_anomaly(
            eng["id"],
            {"anomaly_type": "WATER_INGRESS", "severity": "LOW",
             "description": "neither parent"},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Both parents set.
        resp = api_client.create_anomaly(
            eng["id"],
            {"anomaly_type": "WATER_INGRESS", "severity": "LOW",
             "description": "both parents", "survey_id": srv["id"],
             "field_test_id": srv["id"]},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_anomaly_dismiss_recomputes_survey_count(self):
        """PRD §3.5: "A survey's `anomaly_count` is a read-only figure
        maintained by the server: it counts the anomalies whose `survey_id`
        references this survey and whose status is anything other than
        `DISMISSED`. The count is recomputed when a survey-sourced anomaly is
        raised and again if such an anomaly is later dismissed."

        Design: Corner/state_machines/anomaly_dismiss_recomputes_survey_count
        """
        eng = create_active_engagement(name="ED")
        asm = create_assembly(eng["id"], tag="AD", assembly_type="ROOFING",
                              design_u_factor=0.8,
                              required_airtightness_lps_m2=3.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        a1 = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                            severity="LOW", description="one",
                            survey_id=srv["id"])
        a2 = create_anomaly(eng["id"], anomaly_type="THERMAL_BRIDGE",
                            severity="LOW", description="two",
                            survey_id=srv["id"])
        mid = validate_success(api_client.get_survey(eng["id"], srv["id"], C),
                               200)
        assert mid["anomaly_count"] == 2

        resp = api_client.dismiss_anomaly(eng["id"], a1["id"], P)
        dismissed = validate_success(resp, 200)
        assert dismissed["status"] == "DISMISSED"
        after = validate_success(api_client.get_survey(eng["id"], srv["id"], C),
                                 200)
        assert after["anomaly_count"] == 1
        a2_after = validate_success(api_client.get_anomaly(eng["id"], a2["id"], C),
                                    200)
        assert a2_after["status"] == "OPEN"


class TestRiskScoreAndPostureDerivation:

    def test_risk_score_severity_deltas_accumulate(self):
        """PRD §2.6: "Verifying an anomaly subtracts an amount keyed to the
        anomaly's severity: 15 for `CRITICAL`, 10 for `HIGH`, 5 for `MEDIUM`,
        and 2 for `LOW`."
        PRD §2.5: "Otherwise, if the engagement's `risk_score` is below 40, or
        if any anomaly of the engagement is simultaneously in `VERIFIED` status
        and of `CRITICAL` severity, the posture is `FROZEN`."

        Design: Corner/calculations/risk_score_severity_deltas_accumulate
        """
        eng = create_active_engagement(name="EK", fee_cap_cents=90_000_000)
        asm = create_assembly(eng["id"], tag="AK", assembly_type="ROOFING",
                              design_u_factor=0.8,
                              required_airtightness_lps_m2=3.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        ids = [
            create_anomaly(eng["id"], anomaly_type="WATER_INGRESS",
                           severity="CRITICAL", description=f"c{i}",
                           survey_id=srv["id"])["id"]
            for i in range(3)
        ]
        for an_id in ids:
            verify_anomaly(eng["id"], an_id)
        mid = get_engagement(eng["id"])
        assert mid["risk_score"] == 55
        assert mid["posture"] == "FROZEN"
        # Read-back is stable.
        final = get_engagement(eng["id"])
        assert final["risk_score"] == 55
        assert final["posture"] == "FROZEN"

    def test_posture_derivation_open_anomaly_restricts(self):
        """PRD §2.5: "Otherwise, if the `risk_score` is below 70, or if any
        anomaly of the engagement is in `OPEN` status, the posture is
        `RESTRICTED`. Only when none of those conditions holds is the posture
        `OPEN`. Note the asymmetry deliberately encoded here: an `OPEN` anomaly
        restricts but does not freeze; only a verified critical anomaly, a low
        risk score, or a litigation hold freezes."
        PRD §2.6: "Verifying an anomaly subtracts an amount keyed to the
        anomaly's severity: 15 for `CRITICAL`..."

        Design: Corner/calculations/posture_derivation_open_anomaly_restricts
        """
        eng = create_active_engagement(name="EP")
        asm = create_assembly(eng["id"], tag="AP", assembly_type="ROOFING",
                              design_u_factor=0.8,
                              required_airtightness_lps_m2=3.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        a1 = create_anomaly(eng["id"], anomaly_type="WATER_INGRESS",
                            severity="CRITICAL", description="open critical",
                            survey_id=srv["id"])
        a2 = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                            severity="LOW", description="to dismiss",
                            survey_id=srv["id"])
        resp = api_client.dismiss_anomaly(eng["id"], a2["id"], P)
        validate_success(resp, 200)

        before = get_engagement(eng["id"])
        assert before["posture"] == "RESTRICTED"
        assert before["risk_score"] == 100

        verify_anomaly(eng["id"], a1["id"])
        after = get_engagement(eng["id"])
        assert after["posture"] == "FROZEN"
        assert after["risk_score"] == 85

    def test_rate_threshold_posture_band_crossing(self):
        """PRD §2.5: "Otherwise, if the `risk_score` is below 70, or if any
        anomaly of the engagement is in `OPEN` status, the posture is
        `RESTRICTED`. Only when none of those conditions holds is the posture
        `OPEN`."
        PRD §2.6: "Verifying an anomaly subtracts an amount keyed to the
        anomaly's severity: 15 for `CRITICAL`, 10 for `HIGH`, 5 for `MEDIUM`,
        and 2 for `LOW`."

        Design: Corner/cross_cutting_layers/rate_threshold_posture_band_crossing
        """
        eng = create_active_engagement(name="ERT", fee_cap_cents=90_000_000)
        asm = create_assembly(eng["id"], tag="ART", assembly_type="ROOFING",
                              design_u_factor=0.8,
                              required_airtightness_lps_m2=3.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        h = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                           severity="HIGH", description="h",
                           survey_id=srv["id"])
        mediums = [
            create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                           severity="MEDIUM", description=f"m{i}",
                           survey_id=srv["id"])
            for i in range(4)
        ]
        verify_anomaly(eng["id"], h["id"])
        for m in mediums:
            verify_anomaly(eng["id"], m["id"])

        # No anomaly remains OPEN at this checkpoint: 100 - 10 - 4*5 = 70,
        # and the 70 band boundary is inclusive of OPEN per §2.5 ("below 70").
        at_70 = get_engagement(eng["id"])
        assert at_70["risk_score"] == 70
        assert at_70["posture"] == "OPEN"

        m5 = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                            severity="MEDIUM", description="m4",
                            survey_id=srv["id"])
        verify_anomaly(eng["id"], m5["id"])
        at_65 = get_engagement(eng["id"])
        assert at_65["risk_score"] == 65
        assert at_65["posture"] == "RESTRICTED"
