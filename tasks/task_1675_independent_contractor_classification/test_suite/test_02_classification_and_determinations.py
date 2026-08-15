"""Classification test variants, determination lifecycle, and OCC on engagements."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_determination,
    create_contractor,
    create_engagement,
    create_jurisdiction,
    get_engagement,
    make_answers,
    run_determination,
    setup_engagement_at_state,
    submit_questionnaire,
    validate_error,
    validate_paginated,
    validate_success,
)

_MANAGER = TEST_USERS["engagement_manager_headers"]
_ANALYST = TEST_USERS["classification_analyst_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


def _jurisdiction(code, test_type, **overrides):
    payload = {"code": code, "test_type": test_type}
    payload.update(overrides)
    return create_jurisdiction(**payload)


class TestDualVariantClassification:
    """Identical answers classified under two different regimes (PRD §3.1)."""

    def _setup_pair(self):
        jur_ca = _jurisdiction(
            "US-CA", "ABC_TEST", state_filing_threshold_cents=0,
        )
        jur_tx = _jurisdiction(
            "US-TX", "COMMON_LAW_WEIGHTED", employee_score_threshold=0.60,
        )
        contractor = create_contractor()
        # CONTROL_METHOD=YES is the only employee-indicative answer.
        answers = make_answers(CONTROL_METHOD="YES")
        eng_ca = create_engagement(contractor["id"], jur_ca["id"], title="CA engagement")
        eng_tx = create_engagement(contractor["id"], jur_tx["id"], title="TX engagement")
        submit_questionnaire(eng_ca["id"], answers)
        submit_questionnaire(eng_tx["id"], answers)
        det_ca = run_determination(eng_ca["id"])
        det_tx = run_determination(eng_tx["id"])
        return det_ca, det_tx

    def test_abc_test_single_failed_prong_flips_outcome(self, api):
        """PRD §3.1: "The outcome is `CONTRACTOR` only when no prong fails; a single
        failed prong flips the outcome to `EMPLOYEE_RISK` regardless of how favorable
        the remaining answers are."
        PRD §3.1: "The determination's `score` and `failed_prongs` both record the
        failed-prong count, an integer from zero to three."

        Design: Difficulty/dual_variant_calc/dvc_classification_abc_vs_common_law_same_answers
        """
        det_ca, _ = self._setup_pair()
        assert_determination(det_ca)
        assert det_ca["outcome"] == "EMPLOYEE_RISK"
        assert det_ca["failed_prongs"] == 1
        assert det_ca["score"] == 1

    def test_common_law_weighted_score_below_threshold_passes(self, api):
        """PRD §3.1: "The weighted score sums 0.25 for control of method, 0.20 for
        control of hours, 0.20 for integral-to-business work, 0.15 for profit-and-loss
        posture, 0.10 for permanency, and 0.10 for investment — each term contributing
        its weight only when the corresponding answer is employee-indicative, and
        contributing zero otherwise."
        PRD §3.1: "The outcome is `EMPLOYEE_RISK` when the score is greater than or
        equal to the jurisdiction's `employee_score_threshold` — the boundary is
        inclusive — and `CONTRACTOR` otherwise."

        Design: Difficulty/dual_variant_calc/dvc_classification_abc_vs_common_law_same_answers
        """
        _, det_tx = self._setup_pair()
        assert_determination(det_tx)
        assert det_tx["outcome"] == "CONTRACTOR"
        assert det_tx["score"] == pytest.approx(0.25, abs=1e-9)
        assert det_tx["failed_prongs"] == 0


class TestCommonLawInclusiveThreshold:
    def test_score_exactly_at_threshold_is_employee_risk(self, api):
        """PRD §3.1: "The outcome is `EMPLOYEE_RISK` when the score is greater than or
        equal to the jurisdiction's `employee_score_threshold` — the boundary is
        inclusive — and `CONTRACTOR` otherwise."
        PRD §3.4: "`risk_tier` is `HIGH` when the current outcome is `EMPLOYEE_RISK`"
        and "`HIGH` requires three" approvals.

        Design: Corner/calculations/calc_common_law_inclusive_threshold_060
        """
        # CONTROL_METHOD 0.25 + CONTROL_HOURS 0.20 + PROFIT_LOSS(NO) 0.15 = 0.60.
        setup = setup_engagement_at_state(
            "CLASSIFIED",
            answers=make_answers(CONTROL_METHOD="YES", CONTROL_HOURS="YES", PROFIT_LOSS="NO"),
        )
        det = setup["determination"]
        assert det["score"] == pytest.approx(0.60, abs=1e-9)
        assert det["outcome"] == "EMPLOYEE_RISK"
        engagement = setup["engagement"]
        assert engagement["risk_tier"] == "HIGH"
        assert engagement["required_approval_count"] == 3

    def test_score_one_step_below_threshold_is_contractor(self, api):
        """PRD §3.1: "The outcome is `EMPLOYEE_RISK` when the score is greater than or
        equal to the jurisdiction's `employee_score_threshold` — the boundary is
        inclusive — and `CONTRACTOR` otherwise."
        PRD §3.4: "`STANDARD` when the outcome is `CONTRACTOR` under
        `COMMON_LAW_WEIGHTED`" and "`STANDARD` requires one approval".

        Design: Corner/calculations/calc_common_law_inclusive_threshold_060
        """
        # CONTROL_METHOD 0.25 + CONTROL_HOURS 0.20 + PERMANENCY 0.10 = 0.55 < 0.60.
        setup = setup_engagement_at_state(
            "CLASSIFIED",
            answers=make_answers(CONTROL_METHOD="YES", CONTROL_HOURS="YES", PERMANENCY="YES"),
        )
        det = setup["determination"]
        assert det["score"] == pytest.approx(0.55, abs=1e-9)
        assert det["outcome"] == "CONTRACTOR"
        engagement = setup["engagement"]
        assert engagement["risk_tier"] == "STANDARD"
        assert engagement["required_approval_count"] == 1


class TestDeterminationPreconditions:
    def test_determination_requires_complete_questionnaire(self, api, classification_analyst_headers,
                                                           platform_admin_headers):
        """PRD §3.4: "The questionnaire must also be complete; running the test against
        an incomplete questionnaire is rejected with `ERR_QUESTIONNAIRE_INCOMPLETE`
        (HTTP 422)."
        PRD §3.3: "fewer than eight factors, or duplicated factor keys, leave it
        incomplete."

        Design: Corner/validations/val_questionnaire_incomplete_blocks_determination
        """
        setup = setup_engagement_at_state("DRAFT")
        engagement = setup["engagement"]
        six_factor_answers = make_answers()[:6]
        q_res = api.submit_questionnaire(engagement["id"], {"answers": six_factor_answers}, _MANAGER)
        questionnaire = validate_success(q_res, 200)
        assert questionnaire["complete"] is False

        engagement = get_engagement(engagement["id"])
        res = api.create_determination(
            engagement["id"],
            {"expected_engagement_version": engagement["version"]},
            classification_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_QUESTIONNAIRE_INCOMPLETE.value)

        dets, _ = validate_paginated(api.list_determinations(engagement["id"], platform_admin_headers))
        assert dets == [], "no determination may be persisted for an incomplete questionnaire"

    def test_determination_stale_engagement_version_rejected(self, api, classification_analyst_headers):
        """PRD §2.6: "If the engagement's current `version` differs — because the
        questionnaire was resubmitted, a determination was recorded, or any other
        engagement mutation intervened since the client last read it — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/layer_occ_stale_engagement_version_on_determination
        """
        setup = setup_engagement_at_state("INTAKE_SUBMITTED")
        engagement = setup["engagement"]
        stale_version = engagement["version"]
        payload = {"expected_engagement_version": stale_version}

        first = api.create_determination(engagement["id"], payload, classification_analyst_headers)
        validate_success(first, 201)

        second = api.create_determination(engagement["id"], payload, classification_analyst_headers)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION.value)


class TestDeterminationHistory:
    def test_determinations_listed_newest_first_with_supersession(self, api, platform_admin_headers):
        """PRD §3.4: "The prior current determination, if one exists, has its
        `superseded` flag set to true; the engagement's `current_determination_id` —
        a soft pointer to the non-superseded determination — is updated to the new
        record".
        PRD §3.4: "An engagement's full determination history is retrievable as a list
        ordered newest first, an exception to the default ascending creation order of
        §2.3."

        Design: Corner/endpoints/ep_determinations_reverse_list_and_supersession
        """
        setup = setup_engagement_at_state("CLASSIFIED")
        engagement = setup["engagement"]
        det1 = setup["determination"]
        assert det1["outcome"] == "CONTRACTOR"

        # Revision 2 answers: CONTROL_METHOD + CONTROL_HOURS + PROFIT_LOSS(NO)
        # score 0.25 + 0.20 + 0.15 = 0.60 >= 0.60 => EMPLOYEE_RISK (PRD §3.1).
        submit_questionnaire(
            engagement["id"],
            make_answers(CONTROL_METHOD="YES", CONTROL_HOURS="YES", PROFIT_LOSS="NO"),
        )
        det2 = run_determination(engagement["id"])
        assert det2["outcome"] == "EMPLOYEE_RISK"

        dets, _ = validate_paginated(api.list_determinations(engagement["id"], platform_admin_headers))
        assert len(dets) == 2
        assert dets[0]["id"] == det2["id"], "newest determination first"
        assert dets[0]["superseded"] is False
        assert dets[1]["id"] == det1["id"]
        assert dets[1]["superseded"] is True

        fresh = validate_success(api.get_engagement(engagement["id"], platform_admin_headers), 200)
        assert fresh["current_determination_id"] == det2["id"]
