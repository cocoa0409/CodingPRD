"""Risk assessment scoring variants, adjudication loop, and the IMMINENT cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_plan_for_case,
    assert_risk_assessment,
    create_and_finalize_assessment,
    create_assessment_payload,
    create_draft_assessment,
    create_draft_plan,
    get_case,
    list_case_assessments,
    list_case_plans,
    list_case_referrals,
    make_team_lead_headers,
    make_threat_assessor_headers,
    setup_case_under_assessment,
    setup_case_with_finalized_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")
TL1 = TEST_USERS["team_lead_headers"]
TL9 = make_team_lead_headers("tl_9")


class TestVariantScoringDivergence:
    FACTORS = [
        {"factor_code": "GRIEVANCE_HISTORY", "severity": 3},
        {"factor_code": "BEHAVIORAL_ESCALATION", "severity": 3},
        {"factor_code": "PEER_REPORTS", "severity": 2},
        {"factor_code": "SUPERVISION_GAP", "severity": 2},
    ]

    def test_standard_variant_scores_weighted_sum_plus_bonus(self, api):
        """PRD: "Under the `STANDARD` variant, the base score is the sum, over
        the submitted factors, of each factor's weight multiplied by its
        severity; if any submitted factor has severity 3, a critical bonus of
        10 points is added."
        PRD: "The `risk_level` band is then read off the score: `LOW` below
        20, `MODERATE` from 20 up to but not including 40, `HIGH` from 40 up
        to but not including 60, and `IMMINENT` at 60 or above."

        Design: Difficulty/dual_variant_calc/assessment_standard_vs_expedited_divergence
        """
        case = setup_case_under_assessment()
        assessment = validate_success(
            api.create_assessment(
                create_assessment_payload(case["id"], variant="STANDARD",
                                          factors=self.FACTORS),
                TA1),
            201,
        )
        assert_risk_assessment(assessment)
        # 10*3 + 10*3 + 5*2 + 8*2 = 86, plus the severity-3 bonus of 10.
        assert assessment["raw_score"] == 96
        assert assessment["risk_level"] == "IMMINENT"

    def test_expedited_replacement_rescores_same_factors(self, api):
        """PRD: "Under the `EXPEDITED` variant, only `WEAPON_ACCESS` and
        `PLAN_SPECIFICITY` contribute: their weighted sum is multiplied by one
        and a half, the product is rounded half-up to a whole number, and then
        — if any submitted factor, counted or not, has severity 3 — a critical
        bonus of 15 points is added."
        PRD: "While the assessment remains `DRAFT`, the assessor may replace
        its `variant`, its `factors`, or both; the server recomputes the
        scores on every such update, and an update attempted on a non-`DRAFT`
        assessment is `ERR_ASSESSMENT_NOT_DRAFT`."

        Design: Difficulty/dual_variant_calc/assessment_standard_vs_expedited_divergence
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(case["id"], variant="STANDARD",
                                             factors=self.FACTORS)

        updated = validate_success(
            api.update_assessment(assessment["id"], {"variant": "EXPEDITED"},
                                  TA1),
            200,
        )
        # No WEAPON_ACCESS/PLAN_SPECIFICITY factors: 0 x 1.5 = 0, plus the
        # severity-3 bonus of 15 (the bonus considers every submitted factor).
        assert updated["raw_score"] == 15
        assert updated["risk_level"] == "LOW"
        assert updated["variant"] == "EXPEDITED"
        assert updated["factors"] == self.FACTORS, (
            "a variant-only replacement must leave the factors array untouched"
        )


class TestCombinatorialScoring:
    def test_standard_weighted_bonus_and_high_tier(self, api):
        """PRD: "Under the `STANDARD` variant, the base score is the sum, over
        the submitted factors, of each factor's weight multiplied by its
        severity; if any submitted factor has severity 3, a critical bonus of
        10 points is added."
        PRD: "The `risk_level` band is then read off the score: `LOW` below
        20, `MODERATE` from 20 up to but not including 40, `HIGH` from 40 up
        to but not including 60, and `IMMINENT` at 60 or above."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_bonus_clamp_tiers
        """
        case = setup_case_under_assessment()
        assessment = validate_success(
            api.create_assessment(
                create_assessment_payload(
                    case["id"], variant="STANDARD",
                    factors=[{"factor_code": "PLAN_SPECIFICITY", "severity": 3}]),
                TA1),
            201,
        )
        # 15*3 = 45, plus the severity-3 bonus of 10.
        assert assessment["raw_score"] == 55
        assert assessment["risk_level"] == "HIGH"

    def test_expedited_product_rounds_half_up_before_tier(self, api):
        """PRD: "Under the `EXPEDITED` variant, only `WEAPON_ACCESS` and
        `PLAN_SPECIFICITY` contribute: their weighted sum is multiplied by one
        and a half, the product is rounded half-up to a whole number, and then
        — if any submitted factor, counted or not, has severity 3 — a critical
        bonus of 15 points is added."
        PRD: "Where the assessment algorithm multiplies by one and a half, the
        product is rounded half-up to a whole number before any subsequent
        step."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_bonus_clamp_tiers
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(case["id"], variant="STANDARD")
        updated = validate_success(
            api.update_assessment(
                assessment["id"],
                {"variant": "EXPEDITED",
                 "factors": [{"factor_code": "WEAPON_ACCESS", "severity": 1},
                             {"factor_code": "PLAN_SPECIFICITY", "severity": 1}]},
                TA1),
            200,
        )
        # (20*1 + 15*1) x 1.5 = 52.5 -> 53 rounded half-up; no severity 3.
        assert updated["raw_score"] == 53, (
            "52.5 must round half-up to 53 before any later step"
        )
        assert updated["risk_level"] == "HIGH"


class TestRiskLevelTierBoundaries:
    def test_score_twenty_is_moderate(self, api):
        """PRD: "The `risk_level` band is then read off the score: `LOW` below
        20, `MODERATE` from 20 up to but not including 40, `HIGH` from 40 up
        to but not including 60, and `IMMINENT` at 60 or above."
        PRD: "Under the `STANDARD` variant, the base score is the sum, over
        the submitted factors, of each factor's weight multiplied by its
        severity; if any submitted factor has severity 3, a critical bonus of
        10 points is added."

        Design: Corner/calculations/risk_level_tier_boundaries_20_and_40
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(
            case["id"], variant="STANDARD",
            factors=[{"factor_code": "WEAPON_ACCESS", "severity": 1}])
        assert assessment["raw_score"] == 20
        assert assessment["risk_level"] == "MODERATE", (
            "20 is not LOW; LOW is strictly below 20"
        )

    def test_score_forty_is_high(self, api):
        """PRD: "The `risk_level` band is then read off the score: `LOW` below
        20, `MODERATE` from 20 up to but not including 40, `HIGH` from 40 up
        to but not including 60, and `IMMINENT` at 60 or above."
        PRD: "Under the `STANDARD` variant, the base score is the sum, over
        the submitted factors, of each factor's weight multiplied by its
        severity; if any submitted factor has severity 3, a critical bonus of
        10 points is added."

        Design: Corner/calculations/risk_level_tier_boundaries_20_and_40
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(
            case["id"], variant="STANDARD",
            factors=[{"factor_code": "WEAPON_ACCESS", "severity": 2}])
        assert assessment["raw_score"] == 40
        assert assessment["risk_level"] == "HIGH", (
            "40 is not MODERATE; MODERATE stops below 40"
        )


class TestSubmitReturnLoop:
    def test_return_moves_submitted_assessment_back_to_draft(self, api):
        """PRD: "Submitting moves the assessment from `DRAFT` to `SUBMITTED`
        for team-lead review."
        PRD: "Returning the assessment moves it from `SUBMITTED` back to
        `DRAFT` and records the supplied `return_reason` in the audit event's
        `detail`."
        PRD: "While the assessment remains `DRAFT`, the assessor may replace
        its `variant`, its `factors`, or both; the server recomputes the
        scores on every such update, and an update attempted on a non-`DRAFT`
        assessment is `ERR_ASSESSMENT_NOT_DRAFT`."

        Design: Difficulty/non_linear_state_machine/assessment_submit_return_loop
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(case["id"], variant="STANDARD")

        submitted = validate_success(
            api.submit_assessment(assessment["id"], TA1), 200)
        assert submitted["status"] == "SUBMITTED"

        returned = validate_success(
            api.return_assessment(assessment["id"],
                                  {"return_reason": "needs more interview data"},
                                  TL1),
            200,
        )
        assert returned["status"] == "DRAFT", (
            "return loops the assessment back to DRAFT for revision"
        )

        revised = validate_success(
            api.update_assessment(
                assessment["id"],
                {"factors": [{"factor_code": "WEAPON_ACCESS", "severity": 2}]},
                TA1),
            200,
        )
        # 20*2 = 40 with no severity-3 factor.
        assert revised["raw_score"] == 40
        assert revised["risk_level"] == "HIGH"

    def test_resubmit_and_finalize_propagates_risk_level(self, api):
        """PRD: "Submitting moves the assessment from `DRAFT` to `SUBMITTED`
        for team-lead review."
        PRD: "It stamps `finalized_at`, copies the assessment's `risk_level`
        onto the case (where `risk_level` was null until the first
        finalization), increments the case's `version` by one, and writes
        `ASSESSMENT_FINALIZED`."

        Design: Difficulty/non_linear_state_machine/assessment_submit_return_loop
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(case["id"], variant="STANDARD")
        validate_success(api.submit_assessment(assessment["id"], TA1), 200)
        validate_success(
            api.return_assessment(assessment["id"], {"return_reason": "revise"},
                                  TL1),
            200,
        )
        validate_success(
            api.update_assessment(
                assessment["id"],
                {"factors": [{"factor_code": "WEAPON_ACCESS", "severity": 2}]},
                TA1),
            200,
        )
        validate_success(api.submit_assessment(assessment["id"], TA1), 200)

        finalized = validate_success(
            api.finalize_assessment(assessment["id"], TL1), 200)
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_at"] is not None

        case_after = get_case(case["id"])
        assert case_after["risk_level"] == "HIGH", (
            "finalization copies the assessment's risk_level onto the case"
        )


class TestSegregationOfDutiesOnFinalize:
    def test_finalize_by_creator_rejected(self, api):
        """PRD: "Finalizing moves it from `SUBMITTED` to `FINALIZED`, but
        segregation of duties applies: if the finalizer's `X-User-ID` equals
        the assessment's `created_by_user_id`, the call is rejected with
        `ERR_SOD_SELF_APPROVAL`."

        Design: Corner/validations/sod_finalize_by_creator_rejected
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(case["id"], creator=TA1)
        validate_success(api.submit_assessment(assessment["id"], TA1), 200)

        self_finalize = api.finalize_assessment(
            assessment["id"], make_team_lead_headers("ta_1"))
        validate_error(self_finalize, ApiErrorId.ERR_SOD_SELF_APPROVAL)

        finalized = validate_success(
            api.finalize_assessment(assessment["id"], TL9), 200)
        assert finalized["status"] == "FINALIZED", (
            "a finalizer whose id differs from the creator's succeeds"
        )


class TestFinalizeRequiresSubmitted:
    def test_finalize_draft_assessment_returns_not_submitted(self, api):
        """PRD: "A `TeamLead` then has two adjudication paths, each requiring
        `SUBMITTED` status (`ERR_ASSESSMENT_NOT_SUBMITTED` otherwise)."

        Design: Corner/errors/finalize_draft_assessment_returns_not_submitted
        """
        case = setup_case_under_assessment()
        assessment = create_draft_assessment(
            case["id"],
            factors=[{"factor_code": "PEER_REPORTS", "severity": 1}])

        resp = api.finalize_assessment(assessment["id"], TL1)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_SUBMITTED)


class TestImminentFinalizeCascade:
    OLD_FACTORS = [
        {"factor_code": "GRIEVANCE_HISTORY", "severity": 2},
        {"factor_code": "PEER_REPORTS", "severity": 2},
    ]
    NEW_FACTORS = [
        {"factor_code": "WEAPON_ACCESS", "severity": 2},
        {"factor_code": "PLAN_SPECIFICITY", "severity": 2},
        {"factor_code": "GRIEVANCE_HISTORY", "severity": 1},
    ]

    def _setup(self, api):
        """Case in PLAN_ACTIVE under a MODERATE (30) assessment; a second
        SUBMITTED assessment scoring 80 (IMMINENT) awaits finalization."""
        case, old_assessment = setup_case_with_finalized_assessment(
            factors=self.OLD_FACTORS)
        plan = create_draft_plan(case["id"])
        activate_plan_for_case(plan["id"], case["id"])
        new_assessment = create_draft_assessment(case["id"],
                                                 factors=self.NEW_FACTORS)
        validate_success(api.submit_assessment(new_assessment["id"], TA1), 200)
        return case, old_assessment, plan, new_assessment

    def test_finalize_imminent_supersedes_prior_and_autocreates_referral(self, api):
        """PRD: "Any other assessment for the same case that was `FINALIZED`
        is moved to `SUPERSEDED` with `superseded_at` stamped."
        PRD: "And when the finalized level is `IMMINENT`, a cascade fires:
        unless a law-enforcement referral for the case already exists in
        `SENT` or `ACKNOWLEDGED` status, the system auto-creates one at
        `URGENT` urgency addressed to the agency `DISTRICT_SRT` with
        `auto_created` true, writing `REFERRAL_AUTO_CREATED`; that
        auto-referral then sets the case's `escalation_flag` to true and
        writes `ESCALATION_RAISED`; and the escalation, in turn, sets
        `needs_review` to true on the case's `ACTIVE` management plan if one
        exists."

        Design: Difficulty/transitive_cascade/finalize_imminent_referral_escalation_cascade
        """
        case, old_assessment, _plan, new_assessment = self._setup(api)

        finalized = validate_success(
            api.finalize_assessment(new_assessment["id"], TL1), 200)
        assert finalized["status"] == "FINALIZED"
        # 20*2 + 15*2 + 10*1 = 80 with no severity-3 factor.
        assert finalized["raw_score"] == 80
        assert finalized["risk_level"] == "IMMINENT"

        case_after = get_case(case["id"])
        assert case_after["risk_level"] == "IMMINENT"
        assert case_after["escalation_flag"] is True

        superseded, sup_meta = validate_paginated(api.list_case_assessments(
            case["id"], TL1, params={"status": "SUPERSEDED"}))
        assert sup_meta["total_count"] == 1
        assert superseded[0]["id"] == old_assessment["id"]
        assert superseded[0]["superseded_at"] is not None

        referrals, ref_meta = validate_paginated(api.list_case_referrals(
            case["id"], TL1,
            params={"referral_type": "LAW_ENFORCEMENT", "status": "SENT"}))
        assert ref_meta["total_count"] == 1
        auto_ref = referrals[0]
        assert auto_ref["auto_created"] is True
        assert auto_ref["urgency"] == "URGENT"
        assert auto_ref["agency_name"] == "DISTRICT_SRT"

    def test_finalize_imminent_flags_active_plan_needs_review(self, api):
        """PRD: "And when the finalized level is `IMMINENT`, a cascade fires:
        unless a law-enforcement referral for the case already exists in
        `SENT` or `ACKNOWLEDGED` status, the system auto-creates one at
        `URGENT` urgency addressed to the agency `DISTRICT_SRT` with
        `auto_created` true, writing `REFERRAL_AUTO_CREATED`; that
        auto-referral then sets the case's `escalation_flag` to true and
        writes `ESCALATION_RAISED`; and the escalation, in turn, sets
        `needs_review` to true on the case's `ACTIVE` management plan if one
        exists."

        Design: Difficulty/transitive_cascade/finalize_imminent_referral_escalation_cascade
        """
        case, _old, plan, new_assessment = self._setup(api)

        validate_success(api.finalize_assessment(new_assessment["id"], TL1), 200)

        active_plans, plan_meta = validate_paginated(api.list_case_plans(
            case["id"], TL1, params={"status": "ACTIVE"}))
        assert plan_meta["total_count"] == 1
        assert active_plans[0]["id"] == plan["id"]
        assert active_plans[0]["needs_review"] is True, (
            "the escalation propagates to the ACTIVE plan's needs_review flag"
        )
