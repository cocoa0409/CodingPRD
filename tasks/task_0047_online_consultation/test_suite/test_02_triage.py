"""Triage session lifecycle, severity scoring, and emergency routing.
Covers PRD §3.2."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_patient,
    create_triage_session_payload,
    assert_triage_session,
    make_patient_headers,
    make_questionnaire_response,
    open_triage_session,
    open_and_assess_triage,
    validate_error,
    validate_success,
    build_responses_for_band,
    setup_basic_org,
)


# =========================================================================
# Triage creation and basic shape.
# =========================================================================
class TestTriageCreate:

    def test_create_triage_returns_collecting(self, api):
        """PRD §3.2: 'The new TriageSession begins life in COLLECTING.'

        Claim: POST /consultation/triage-sessions -> status == COLLECTING.
        """
        setup_basic_org()  # ensure department/doctor exist
        patient = create_patient()
        res = api.create_triage_session(
            create_triage_session_payload(
                patient_id=patient["id"],
                questionnaire_responses=[make_questionnaire_response(
                    question_code="CHEST_PAIN", severity_weight=1,
                )],
            ),
            make_patient_headers(patient["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_triage_session(data)
        assert data["status"] == "COLLECTING"
        assert data["patient_id"] == patient["id"]


# =========================================================================
# /assess: state transition + score calculation.
# =========================================================================
class TestTriageAssess:

    def test_assess_empty_questionnaire_rejected(self, api):
        """PRD §3.2: 'The assessment is rejected with ERR_QUESTIONNAIRE_EMPTY
        when the questionnaire has fewer than one entry at the moment of
        assessment.'

        Claim: /assess with empty responses -> 422 ERR_QUESTIONNAIRE_EMPTY.
        """
        setup_basic_org()
        patient = create_patient()
        # Create a session but somehow with empty responses; the framework
        # rejects empty arrays in create-payload via PRD's 'has >= 1' rule,
        # so we mimic empty assessment by creating with empty list directly.
        res = api.create_triage_session(
            {"patient_id": patient["id"], "questionnaire_responses": []},
            make_patient_headers(patient["id"]),
        )
        if 200 <= res.status_code < 300:
            session = res.json()["data"]
            res2 = api.assess_triage_session(
                session["id"], make_patient_headers(patient["id"]),
            )
            validate_error(res2, ApiErrorId.ERR_QUESTIONNAIRE_EMPTY.value)
        else:
            validate_error(res, ApiErrorId.ERR_QUESTIONNAIRE_EMPTY.value)

    def test_assess_advances_to_assessed_and_scores(self, api):
        """PRD §3.2: 'the patient triggers assessment to advance the
        session from COLLECTING to ASSESSED.'

        PRD §3.2: 'The chief_complaint_score is the sum of severity_weight
        across all questionnaire responses, multiplied by a chief-complaint
        factor of 10.'

        Claim: /assess advances to ASSESSED and chief_complaint_score
        equals sum(severity_weight) * 10.
        """
        setup_basic_org()
        patient = create_patient()
        # One response with severity_weight=2 -> chief = 2*10 = 20
        session = open_and_assess_triage(
            patient=patient,
            responses=[make_questionnaire_response(
                question_code="CHEST_PAIN", severity_weight=2,
            )],
        )
        assert session["status"] == "ASSESSED"
        assert session["chief_complaint_score"] == 20

    def test_assess_low_band(self, api):
        """PRD §3.2: 'LOW when the score is strictly below 30'.

        Claim: severity_score < 30 -> severity_band == LOW.
        """
        setup_basic_org()
        patient = create_patient()
        # weight 1 -> chief 10 -> total 10 -> LOW
        session = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("LOW"),
        )
        assert session["severity_score"] == 10
        assert session["severity_band"] == "LOW"

    def test_assess_mid_band_boundary_30(self, api):
        """PRD §3.2: 'MID when the score is at least 30 and strictly
        below 60' and 'LOW when the score is strictly below 30'.

        Claim: severity_score == 30 -> MID (inclusive lower bound).
        """
        setup_basic_org()
        patient = create_patient(
            chronic_condition_codes=["DIABETES", "HYPERTENSION"],
        )
        # chief = 2*10 = 20; vital = 2*2 = 4; risk = (1+1)*3 = 6; total = 30
        responses = [
            make_questionnaire_response(
                question_code="CHEST_PAIN", severity_weight=2,
            ),
            make_questionnaire_response(
                question_code="VITAL_BP", answer_value="ABNORMAL",
                severity_weight=0,
            ),
            make_questionnaire_response(
                question_code="VITAL_HR", answer_value="ABNORMAL",
                severity_weight=0,
            ),
        ]
        session = open_and_assess_triage(
            patient=patient, responses=responses,
        )
        assert session["severity_score"] == 30
        assert session["severity_band"] == "MID"

    def test_assess_below_30_is_low(self, api):
        """PRD §3.2: 'LOW when the score is strictly below 30'.

        Claim: severity_score == 28 -> LOW (boundary - 2).
        """
        setup_basic_org()
        patient = create_patient(
            chronic_condition_codes=["DIABETES", "HYPERTENSION"],
        )
        # chief = 2*10 = 20; vital = 1*2 = 2; risk = (1+1)*3 = 6; total = 28
        responses = [
            make_questionnaire_response(
                question_code="CHEST_PAIN", severity_weight=2,
            ),
            make_questionnaire_response(
                question_code="VITAL_BP", answer_value="ABNORMAL",
                severity_weight=0,
            ),
        ]
        session = open_and_assess_triage(
            patient=patient, responses=responses,
        )
        assert session["severity_score"] == 28
        assert session["severity_band"] == "LOW"

    def test_assess_emergency_routes(self, api):
        """PRD §3.2: 'When the band is EMERGENCY, the assessment transition
        fires a secondary automatic transition from ASSESSED to
        EMERGENCY_ROUTED: the system mints an opaque
        emergency_routing_ticket, ... leaves recommended_department_code
        null'.

        Claim: severity_score >= 90 -> status EMERGENCY_ROUTED,
        emergency_routing_ticket set, recommended_department_code null.
        """
        setup_basic_org()
        patient = create_patient()
        # weight 10 -> chief 100 -> severity 100 -> EMERGENCY
        session = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("EMERGENCY"),
        )
        assert session["severity_band"] == "EMERGENCY"
        assert session["status"] == "EMERGENCY_ROUTED"
        assert session.get("emergency_routing_ticket") is not None
        assert session.get("recommended_department_code") is None

    def test_assess_vital_anomaly_counts_only_vital_prefix_abnormal(self, api):
        """PRD §3.2: 'The vital_anomaly_score is the count of
        questionnaire entries whose question_code begins with VITAL_ and
        whose answer_value equals ABNORMAL, multiplied by a vital-anomaly
        factor of 2.'

        Claim: only entries with VITAL_ prefix AND answer_value=='ABNORMAL'
        contribute; vital_anomaly_score == count * 2.
        """
        setup_basic_org()
        patient = create_patient()
        # 2 VITAL_/ABNORMAL + 1 VITAL_/NORMAL + 1 non-VITAL
        responses = [
            make_questionnaire_response(
                question_code="VITAL_BP", answer_value="ABNORMAL",
                severity_weight=0,
            ),
            make_questionnaire_response(
                question_code="VITAL_HR", answer_value="ABNORMAL",
                severity_weight=0,
            ),
            make_questionnaire_response(
                question_code="VITAL_TEMP", answer_value="NORMAL",
                severity_weight=0,
            ),
            make_questionnaire_response(
                question_code="CHEST_PAIN", answer_value="ABNORMAL",
                severity_weight=0,
            ),
        ]
        session = open_and_assess_triage(
            patient=patient, responses=responses,
        )
        # Only 2 entries qualify (VITAL_BP and VITAL_HR both ABNORMAL)
        # vital_anomaly_score = 2 * 2 = 4
        assert session["vital_anomaly_score"] == 4

    def test_assess_risk_factor_from_chronic_codes(self, api):
        """PRD §3.2: 'for each code, if that code appears in the system's
        risk table (where DIABETES contributes 1, HYPERTENSION contributes
        1, and IMMUNOCOMPROMISED contributes 2; codes outside the table
        contribute nothing), the corresponding entry is summed, and the
        resulting sum is multiplied by a risk factor of 3.'

        Claim: chronic_condition_codes=['DIABETES'] -> risk_factor_score == 3.
        """
        setup_basic_org()
        patient = create_patient(chronic_condition_codes=["DIABETES"])
        session = open_and_assess_triage(
            patient=patient,
            responses=[make_questionnaire_response(
                question_code="CHEST_PAIN", severity_weight=1,
            )],
        )
        assert session["risk_factor_score"] == 3

    def test_assess_idempotency_on_non_assessed_only(self, api):
        """PRD §3.2: 'the patient triggers assessment to advance the
        session from COLLECTING to ASSESSED.'

        Claim: /assess on an already-ASSESSED session -> ERR_INVALID_STATE
        (precondition is from-state COLLECTING).
        """
        setup_basic_org()
        patient = create_patient()
        session = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("MID"),
        )
        # Already ASSESSED — repeat /assess should fail state precondition.
        res = api.assess_triage_session(
            session["id"], make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# /close: ASSESSED -> CLOSED.
# =========================================================================
class TestTriageClose:

    def test_close_assessed_session(self, api):
        """PRD §3.2: 'A patient may also walk away from an assessed but
        non-emergency triage by closing it, advancing status from
        ASSESSED to the terminal CLOSED.'

        Claim: /close on ASSESSED -> status == CLOSED.
        """
        setup_basic_org()
        patient = create_patient()
        session = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("MID"),
        )
        res = api.close_triage_session(
            session["id"], make_patient_headers(patient["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "CLOSED"

    def test_close_collecting_invalid_state(self, api):
        """PRD §3.2: 'A patient may also walk away from an assessed but
        non-emergency triage by closing it, advancing status from
        ASSESSED to the terminal CLOSED.'

        Claim: /close on COLLECTING (not yet assessed) -> ERR_INVALID_STATE.
        """
        setup_basic_org()
        patient = create_patient()
        session = open_triage_session(patient=patient)
        # status is COLLECTING -- close requires ASSESSED.
        res = api.close_triage_session(
            session["id"], make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
