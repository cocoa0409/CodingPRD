"""Client onboarding, risk questionnaire, activation/suspension cascade.

Coverage targets (PRD §3.1):
- Client create defaults (kyc_status=PENDING, risk_band=null).
- time_horizon_years validation.
- Risk questionnaire q1..q5 validation.
- STANDARD vs AGE_ADJUSTED scoring variants and bucket boundaries.
- Activation precondition (questionnaire + horizon set).
- Suspension cascade -> account FROZEN_DOC_REVIEW + opportunities
  DISMISSED.
- Reinstate cascade -> account ACTIVE; dismissed opps stay dismissed.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_client,
    advance_clock_to,
    api_client,
    create_account,
    create_client,
    create_client_payload,
    create_questionnaire_payload,
    iso_instant_utc,
    re_get_account,
    re_get_client,
    reinstate_client,
    seed_nine_model_portfolios,
    setup_active_client_with_account,
    setup_harvest_detected_with_replacement,
    submit_questionnaire,
    suspend_client,
    validate_error,
    validate_success,
)


# ===========================================================================
# Client create — PRD §3.1
# ===========================================================================
class TestClientCreate:

    def test_client_created_in_pending(self, api):
        """PRD §3.1: "A client begins life when a ComplianceOfficer
        creates them; the new Client row is born with kyc_status set
        to PENDING and risk_band null."

        Claim: POST /clients returns kyc_status=PENDING, risk_band=null.
        """
        payload = create_client_payload()
        resp = api.create_client(
            payload, TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["kyc_status"] == "PENDING"
        assert data.get("risk_band") is None

    @pytest.mark.parametrize("bad_horizon", [0, -1, 41, 100])
    def test_horizon_out_of_range_rejected(self, api, bad_horizon):
        """PRD §3.1: "The time_horizon_years value must be at least
        one and at most forty; values outside that inclusive range
        are rejected with ERR_TIME_HORIZON_OUT_OF_RANGE."

        Claim: time_horizon_years outside [1,40] ->
        ERR_TIME_HORIZON_OUT_OF_RANGE.
        """
        payload = create_client_payload(time_horizon_years=bad_horizon)
        resp = api.create_client(
            payload, TEST_USERS["compliance_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_TIME_HORIZON_OUT_OF_RANGE.value,
        )

    @pytest.mark.parametrize("good_horizon", [1, 40])
    def test_horizon_boundary_accepted(self, api, good_horizon):
        """PRD §3.1: "The time_horizon_years value must be at least
        one and at most forty".

        Claim: time_horizon_years at the boundaries 1 and 40 is
        accepted.
        """
        payload = create_client_payload(time_horizon_years=good_horizon)
        resp = api.create_client(
            payload, TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["time_horizon_years"] == good_horizon


# ===========================================================================
# Risk questionnaire validation — PRD §3.1
# ===========================================================================
class TestQuestionnaireValidation:

    @pytest.mark.parametrize(
        "field",
        [
            "q1_loss_tolerance", "q2_volatility_comfort",
            "q3_growth_vs_stability", "q4_liquidity_need",
            "q5_experience",
        ],
    )
    @pytest.mark.parametrize("bad", [0, 6, -1, 100])
    def test_answer_out_of_range_rejected(self, api, field, bad):
        """PRD §3.1: "Each of the five integer answers ... must be an
        integer in the inclusive range one through five. Any answer
        outside that range causes the entire submission to fail with
        ERR_QUESTIONNAIRE_OUT_OF_RANGE."

        Claim: any qN answer outside [1,5] ->
        ERR_QUESTIONNAIRE_OUT_OF_RANGE.
        """
        client = create_client()
        payload = create_questionnaire_payload()
        payload[field] = bad
        resp = api.submit_questionnaire(
            client["id"], payload,
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_QUESTIONNAIRE_OUT_OF_RANGE.value,
        )


# ===========================================================================
# STANDARD scoring — PRD §3.1
# ===========================================================================
class TestStandardScoring:

    def test_standard_score_formula(self, api):
        """PRD §3.1: "the raw score equals one times q1_loss_tolerance,
        plus one times q2_volatility_comfort, plus one times
        q3_growth_vs_stability, plus one times the quantity six minus
        q4_liquidity_need, plus one times q5_experience."

        Claim: STANDARD raw_score = q1 + q2 + q3 + (6 - q4) + q5.
        For q1=3, q2=3, q3=3, q4=2, q5=3 -> raw = 3+3+3+4+3 = 16.
        """
        client = create_client()
        data = submit_questionnaire(
            client,
            q1_loss_tolerance=3, q2_volatility_comfort=3,
            q3_growth_vs_stability=3, q4_liquidity_need=2,
            q5_experience=3,
            scoring_method="STANDARD",
        )
        assert data["raw_score"] == 16

    @pytest.mark.parametrize(
        "q1,q2,q3,q4,q5,expected_band",
        [
            # CONSERVATIVE bucket boundary: raw <= 10
            (1, 1, 1, 5, 1, "CONSERVATIVE"),  # raw=1+1+1+1+1=5
            (2, 2, 2, 4, 2, "CONSERVATIVE"),  # raw=2+2+2+2+2=10 (boundary)
            # MODERATE bucket boundaries: 11..17
            (3, 3, 3, 4, 3, "MODERATE"),  # raw=3+3+3+2+3=14 (mid)
            (3, 3, 3, 1, 3, "MODERATE"),  # raw=3+3+3+5+3=17 (boundary high)
            # AGGRESSIVE bucket: raw >= 18
            (4, 4, 4, 2, 4, "AGGRESSIVE"),  # raw=4+4+4+4+4=20
            (5, 5, 5, 1, 5, "AGGRESSIVE"),  # raw=25 max
        ],
    )
    def test_band_buckets(self, api, q1, q2, q3, q4, q5, expected_band):
        """PRD §3.1: "a raw score of ten or less assigns CONSERVATIVE;
        a raw score from eleven through seventeen assigns MODERATE; a
        raw score of eighteen or greater (and no higher than the
        maximum twenty-five) assigns AGGRESSIVE."

        Claim: STANDARD raw -> CONSERVATIVE if <=10, MODERATE if
        11..17, AGGRESSIVE if >=18.
        """
        client = create_client()
        data = submit_questionnaire(
            client,
            q1_loss_tolerance=q1, q2_volatility_comfort=q2,
            q3_growth_vs_stability=q3, q4_liquidity_need=q4,
            q5_experience=q5, scoring_method="STANDARD",
        )
        assert data["assigned_band"] == expected_band

    def test_client_risk_band_updated_on_submission(self, api):
        """PRD §3.1: "When the submission completes successfully, the
        client's risk_band field is overwritten with the freshly
        computed assigned_band."

        Claim: after questionnaire submission Client.risk_band ==
        assigned_band.
        """
        client = create_client()
        q = submit_questionnaire(
            client,
            q1_loss_tolerance=4, q2_volatility_comfort=4,
            q3_growth_vs_stability=4, q4_liquidity_need=2,
            q5_experience=4, scoring_method="STANDARD",
        )
        refreshed = re_get_client(client["id"])
        assert refreshed["risk_band"] == q["assigned_band"]


# ===========================================================================
# Activation — PRD §3.1
# ===========================================================================
class TestActivation:

    def test_activate_requires_questionnaire(self, api):
        """PRD §3.1: "A ComplianceOfficer moves the client from
        PENDING to ACTIVE only after at least one RiskQuestionnaire
        has been submitted and time_horizon_years has been set".

        Claim: activate without any questionnaire ->
        ERR_INVALID_STATE.
        """
        client = create_client()
        resp = api.activate_client(
            client["id"],
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_activate_after_questionnaire_succeeds(self, api):
        """PRD §3.1: "A ComplianceOfficer moves the client from
        PENDING to ACTIVE only after at least one RiskQuestionnaire
        has been submitted and time_horizon_years has been set".

        Claim: with a questionnaire submitted activate moves PENDING
        -> ACTIVE.
        """
        client = create_client()
        submit_questionnaire(client)
        resp = api.activate_client(
            client["id"],
            TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(resp)
        assert data["kyc_status"] == "ACTIVE"


# ===========================================================================
# Suspension cascade — PRD §3.1
# ===========================================================================
class TestSuspendCascade:

    def test_suspend_freezes_all_accounts(self, api):
        """PRD §3.1: "From ACTIVE, a compliance officer may move the
        client to SUSPENDED; the suspension cascades into the
        per-account compliance dimension (every Account belonging to
        the suspended client transitions its compliance_status to
        FROZEN_DOC_REVIEW)".

        Claim: suspend(client) -> every account.compliance_status =
        FROZEN_DOC_REVIEW.
        """
        client, account = setup_active_client_with_account()
        # Create a second account too.
        a2 = create_account(client)
        suspend_client(client)
        a1 = re_get_account(account["id"])
        a2 = re_get_account(a2["id"])
        assert a1["compliance_status"] == "FROZEN_DOC_REVIEW"
        assert a2["compliance_status"] == "FROZEN_DOC_REVIEW"

    def test_suspend_dismisses_detected_opportunities(self, api):
        """PRD §3.1: "the suspension cascades ... into the harvest
        pipeline (every HarvestOpportunity in DETECTED for those
        accounts transitions to DISMISSED)".

        Claim: suspend(client) -> previously DETECTED opportunities
        on that client's accounts become DISMISSED.
        """
        setup = setup_harvest_detected_with_replacement()
        client = setup["client"]
        account = setup["account"]
        opp = setup["opportunity"]
        assert opp is not None
        assert opp["status"] == "DETECTED"
        suspend_client(client)
        opps = api.list_harvest_opportunities(
            account["id"], TEST_USERS["compliance_officer_headers"],
        )
        items = opps.json()["data"]
        if isinstance(items, dict):
            items = items.get("items", [])
        found = [o for o in items if o.get("id") == opp["id"]]
        assert found, "previously DETECTED opp should still exist"
        assert found[0]["status"] == "DISMISSED"

    def test_reinstate_unfreezes_all_accounts(self, api):
        """PRD §3.1: "A subsequent reinstatement from SUSPENDED back
        to ACTIVE cascades the account-level compliance_status back
        to ACTIVE".

        Claim: reinstate(client) -> every account.compliance_status
        = ACTIVE.
        """
        client, account = setup_active_client_with_account()
        suspend_client(client)
        a_after_suspend = re_get_account(account["id"])
        assert a_after_suspend["compliance_status"] == "FROZEN_DOC_REVIEW"
        reinstate_client(client)
        a_after_reinstate = re_get_account(account["id"])
        assert a_after_reinstate["compliance_status"] == "ACTIVE"


# ===========================================================================
# AGE_ADJUSTED variant — PRD §3.1
# ===========================================================================
class TestAgeAdjustedScoring:

    def test_age_adjusted_inverts_q3_for_old_client(self, api):
        """PRD §3.1: "the variant uses the same formula except that
        the third term — the growth-vs-stability contribution — is
        replaced by one times the quantity six minus
        q3_growth_vs_stability, inverting the growth axis so that a
        higher growth preference for an older client lowers the raw
        score and biases the bucket toward stability."

        Claim: with q1=4, q2=4, q3=5, q4=2, q5=4 and age >=55:
        STANDARD raw = 4+4+5+4+4 = 21 (AGGRESSIVE); AGE_ADJUSTED raw
        = 4+4+(6-5)+4+4 = 17 (MODERATE).
        """
        client = create_client(
            birth_date="1965-01-01", time_horizon_years=10,
        )
        # Advance the clock so derived age >= 55.
        advance_clock_to(iso_instant_utc(2025, 6, 1, 12, 0, 0))
        # STANDARD path.
        a = submit_questionnaire(
            client,
            q1_loss_tolerance=4, q2_volatility_comfort=4,
            q3_growth_vs_stability=5, q4_liquidity_need=2,
            q5_experience=4, scoring_method="STANDARD",
        )
        assert a["raw_score"] == 21
        assert a["assigned_band"] == "AGGRESSIVE"
        # AGE_ADJUSTED path.
        b = submit_questionnaire(
            client,
            q1_loss_tolerance=4, q2_volatility_comfort=4,
            q3_growth_vs_stability=5, q4_liquidity_need=2,
            q5_experience=4, scoring_method="AGE_ADJUSTED",
        )
        assert b["raw_score"] == 17
        assert b["assigned_band"] == "MODERATE"


# ===========================================================================
# Suspension blocks questionnaire — PRD §3.1
# ===========================================================================
class TestSuspendedClientInput:

    def test_questionnaire_on_suspended_client_rejected(self, api):
        """PRD §3.1: "the racing operations serialize first-writer-
        wins on the client's kyc_status read at submission time, so
        if suspension lands first the submission is rejected with
        ERR_CLIENT_NOT_ACCEPTING_INPUT".

        Claim: after suspension, POST questionnaire ->
        ERR_CLIENT_NOT_ACCEPTING_INPUT.
        """
        client, _ = setup_active_client_with_account()
        suspend_client(client)
        payload = create_questionnaire_payload()
        resp = api.submit_questionnaire(
            client["id"], payload,
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_CLIENT_NOT_ACCEPTING_INPUT.value,
        )
