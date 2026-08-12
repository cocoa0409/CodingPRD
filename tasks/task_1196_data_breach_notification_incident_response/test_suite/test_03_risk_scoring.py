"""Risk-score calculations — both variants (difficulty rule dual_variant_calc,
corner design calculations section)."""
from test_helpers import (
    TEST_USERS,
    create_affected_subject_payload,
    create_forensic_scope_payload,
    create_incident,
    get_success_data,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]
DA = TEST_USERS["data_analyst_headers"]


class TestRiskScoreVariants:
    def test_conservative_vs_likelihood_adjusted(self, api):
        """PRD §3.3: "The conservative variant, stored in
        `risk_score_conservative`, is the base score rounded half-up to an
        integer, capped at 100. The likelihood-adjusted variant, stored in
        `risk_score_likelihood_adjusted`, first multiplies the unrounded base
        score by `exfiltration_likelihood_pct` divided by 100, then rounds
        half-up, then caps at 100."
        PRD §3.3 element weights: "`SSN` contributes 20". With zero subjects
        the volume bonus is `floor(0/500)=0`; with source_channel
        INTERNAL_DETECTION the multiplier is 1.0.

        Design: Difficulty/dual_variant_calc/risk_score_conservative_vs_likelihood_adjusted
        """
        inc = create_incident()
        scope_resp = api.create_forensic_scope(
            inc["id"],
            create_forensic_scope_payload(
                scope_statement="SSN only",
                systems_in_scope=["HR_DB"],
                data_elements_at_risk=["SSN"],
                exfiltration_likelihood_pct=40,
            ),
            FL,
        )
        scope = validate_success(scope_resp, expected_status=201)
        baseline_resp = api.baseline_forensic_scope(inc["id"], scope["id"], FL)
        validate_success(baseline_resp)
        after = get_success_data(api.get_incident(inc["id"], IC))
        # SSN=20, channel multiplier 1.0, volume bonus 0 -> base=20.
        assert after["risk_score_conservative"] == 20
        # 20 * 40/100 = 8.0 -> round_half_up -> 8.
        assert after["risk_score_likelihood_adjusted"] == 8
        assert after["risk_score_conservative"] != after["risk_score_likelihood_adjusted"]

    def test_conservative_includes_volume_bonus_and_excluded_dropped(self, api):
        """PRD §3.3: "the current set of non-`EXCLUDED` affected subjects"
        supplies the volume bonus; "`SSN` contributes 20"; with one
        non-`EXCLUDED` subject the volume bonus is `floor(1/500)=0`. An
        `EXCLUDED` subject contributes neither to `total_affected_subjects`
        nor to the volume bonus.

        Design: Corner/calculations/risk_score_input_set_filtering
        """
        inc = create_incident()
        scope_resp = api.create_forensic_scope(
            inc["id"],
            create_forensic_scope_payload(
                data_elements_at_risk=["SSN"], exfiltration_likelihood_pct=100
            ),
            FL,
        )
        scope = validate_success(scope_resp, expected_status=201)
        api.baseline_forensic_scope(inc["id"], scope["id"], FL)

        s1 = validate_success(
            api.create_affected_subject(
                inc["id"],
                create_affected_subject_payload(external_subject_ref="S1"),
                DA,
            ),
            expected_status=201,
        )
        s2 = validate_success(
            api.create_affected_subject(
                inc["id"],
                create_affected_subject_payload(external_subject_ref="S2"),
                DA,
            ),
            expected_status=201,
        )
        api.verify_affected_subject(inc["id"], s1["id"], DA)
        api.exclude_affected_subject(inc["id"], s2["id"], DA)

        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["total_affected_subjects"] == 1
        # SSN=20, channel 1.0, volume bonus floor(1/500)=0 -> conservative=20.
        assert after["risk_score_conservative"] == 20
