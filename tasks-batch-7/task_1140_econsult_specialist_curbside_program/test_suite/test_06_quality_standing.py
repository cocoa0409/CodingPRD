"""Quality review, rebuke cascade, documentation gate, and panel standing cycles."""
from test_helpers import (
    ApiErrorId, TEST_USERS, complete_review, document_response,
    get_membership, get_response, make_provider_headers,
    make_reviewer_headers, make_specialist_headers, open_review, revise_response,
    setup_answered_consult, setup_late_answered_consult, setup_panel_scenario,
    validate_error, validate_paginated, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestQualityAndStanding:
    def test_verdict_must_match_computed_band_rejected(self, api):
        """PRD §3.7: "The verdict must agree with the computed band: a composite of
        6000 or more requires `PASS`, and below 6000 requires `REBUKE`; a verdict that
        contradicts its band is rejected with `ERR_VERDICT_SCORE_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/verdict_must_match_computed_band_rejected
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-V3", provider_npi="1000004004",
            specialist_npi="2000004004", reviewer_npi="2000004005",
            with_reviewer=True,
            consult_overrides={
                "question_text": "Pacemaker interrogation scheduling question after battery elective replacement alert.",
                "icd10_primary": "Z45",
            },
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        # 5/5/5 -> composite 10000 >= 6000, which requires PASS; REBUKE contradicts.
        res = api.complete_quality_review(
            review["id"],
            {"timeliness_score": 5, "appropriateness_score": 5, "clarity_score": 5,
             "verdict": "REBUKE"},
            make_reviewer_headers(scenario["reviewer"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERDICT_SCORE_MISMATCH, expected_status=422)
        # No state moved: the review stays PENDING and the response stays SUBMITTED.
        review_after = validate_success(api.get_quality_review(review["id"], COORD), 200)
        assert review_after["status"] == "PENDING"
        assert get_response(scenario["response"]["id"])["status"] == "SUBMITTED"

    def test_finalize_without_documentation_returns_incomplete(self, api):
        """PRD §3.6: "`documentation_complete` must be true
        (`ERR_DOCUMENTATION_INCOMPLETE`)"
        PRD §3.6: "Whenever either flag changes, `documentation_complete` is
        recomputed as the conjunction of the two flags — both notes written, and only
        then, make it true."

        Design: Corner/validations/finalize_without_documentation_returns_incomplete
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-V7", provider_npi="1000004008",
            specialist_npi="2000004009",
            consult_overrides={
                "question_text": "Dilated cardiomyopathy on GDMT; asks about digoxin addition for persistent symptoms.",
                "icd10_primary": "I42",
            },
        )
        spec_h = make_specialist_headers(scenario["specialist"]["id"])
        # No notes at all.
        res = api.finalize_response(scenario["response"]["id"], spec_h)
        validate_error(res, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE,
                       expected_status=409)
        # Only the PCP side documented: still incomplete.
        validate_success(api.mark_documentation(
            scenario["response"]["id"], {"record_type": "PCP_NOTE"},
            make_provider_headers(scenario["provider"]["id"]),
        ), 200)
        res = api.finalize_response(scenario["response"]["id"], spec_h)
        validate_error(res, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE,
                       expected_status=409)
        after = get_response(scenario["response"]["id"])
        assert after["status"] == "SUBMITTED"
        assert after["documentation_complete"] is False

    def test_late_response_finalize_requires_passed_review(self, api):
        """PRD §3.6: "when `review_required` was snapshotted true, there must exist a
        `COMPLETED` quality review with verdict `PASS` whose `created_at` is at or
        after the response's `last_submitted_at` — a review predating the latest
        submission does not count — with failure rejected as
        `ERR_REVIEW_REQUIRED_NOT_PASSED`."

        Design: Corner/validations/late_response_finalize_requires_passed_review
        """
        scenario = setup_late_answered_consult(
            patient_ref="PAT-V8", provider_npi="1000004009",
            specialist_npi="2000004010", reviewer_npi="2000004011",
            consult_overrides={
                "question_text": "Endocarditis prophylaxis question for dental work in patient with prosthetic valve.",
                "icd10_primary": "Z95",
            },
        )
        response = scenario["response"]
        assert response["review_required"] is True, "late response arms the review gate"
        document_response(response["id"], scenario["provider"]["id"],
                          scenario["specialist"]["id"])
        spec_h = make_specialist_headers(scenario["specialist"]["id"])
        # Fully documented but no passing review yet.
        res = api.finalize_response(response["id"], spec_h)
        validate_error(res, ApiErrorId.ERR_REVIEW_REQUIRED_NOT_PASSED,
                       expected_status=409)
        # A COMPLETED PASS review (created after the submission) unlocks finalize.
        review = open_review(response["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=4, appropriateness_score=5,
                        clarity_score=5, verdict="PASS")
        finalized = validate_success(api.finalize_response(response["id"], spec_h), 200)
        assert finalized["status"] == "FINALIZED"

    def test_quality_score_defaults_when_no_reviews(self, api):
        """PRD §3.7: "Then the timeliness component is computed: when
        `responded_count` is zero it defaults to 10000, otherwise it is 10000 times
        `on_time_count` divided by `responded_count`, rounded half up. The review
        component follows: when `reviews_count` is zero it defaults to 8500, otherwise
        it is `reviews_score_sum` divided by `reviews_count`, rounded half up. The
        blended score is six times the review component plus four times the timeliness
        component, the sum divided by ten, rounded half up."

        Design: Corner/calculations/quality_score_defaults_when_no_reviews
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-C2", provider_npi="1000003002",
            specialist_npi="2000003002",
            consult_overrides={
                "question_text": "Refractory hypertension workup question: when to screen for primary aldosteronism.",
                "icd10_primary": "I10",
            },
        )
        membership = get_membership(scenario["membership"]["id"])
        assert membership["responded_count"] == 1
        assert membership["on_time_count"] == 1
        # 0.6 * 8500 (default review component) + 0.4 * 10000 (1/1 on time) = 9100.
        assert membership["quality_score_bps"] == 9100
        assert membership["standing"] == "GOOD_STANDING"

    def test_rebuke_drops_membership_to_probation_then_revise_cycles(self, api):
        """PRD §3.7: "The system computes `composite_score_bps` as fifty times the
        appropriateness score plus twenty-five times the timeliness score plus
        twenty-five times the clarity score, the total divided by five, rounded half
        up, then multiplied by one hundred"
        PRD §3.7: "A membership in `GOOD_STANDING` drops to `SUSPENDED` when its score
        falls below 5000, and otherwise drops to `PROBATION` when its score falls
        below 7000."
        PRD §3.7: "Revision replaces `recommendation_text` and, when provided,
        `disposition`; it increments `revision_count`"

        Design: Difficulty/non_linear_state_machine/membership_standing_good_probation_good_cycle
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-NL2", provider_npi="1000000051",
            specialist_npi="2000000051", reviewer_npi="2000000052",
            with_reviewer=True, disposition="MANAGE_WITH_PLAN",
            consult_overrides={
                "question_text": "Murmur on exam, asymptomatic; asks if echo needed before clearing for marathon training.",
                "icd10_primary": "R01",
            },
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        completed = complete_review(review["id"], scenario["reviewer"]["id"],
                                    timeliness_score=2, appropriateness_score=1,
                                    clarity_score=4, verdict="REBUKE")
        # (1*50 + 2*25 + 4*25) / 5 = 40 -> 4000 bps; 4000 < 6000 so REBUKE agrees.
        assert completed["composite_score_bps"] == 4000
        membership = get_membership(scenario["membership"]["id"])
        # Blend: 0.6 * 4000 (review) + 0.4 * 10000 (timeliness 1/1) = 6400 < 7000.
        assert membership["quality_score_bps"] == 6400
        assert membership["standing"] == "PROBATION"
        # The REBUKED -> SUBMITTED revision cycle is exercised.
        revised = revise_response(
            scenario["response"]["id"], scenario["specialist"]["id"],
            recommendation_text="Order TTE within 2 weeks and cardiology follow-up; avoid maximal exertion until echo result is reviewed.",
        )
        assert revised["status"] == "SUBMITTED"
        assert revised["revision_count"] == 1

    def test_pass_review_recovers_membership_to_good_standing(self, api):
        """PRD §3.7: "A membership in `PROBATION` drops to `SUSPENDED` when its score
        falls below 5000 or its `rebuke_count` reaches 2, and otherwise recovers to
        `GOOD_STANDING` when its score reaches 7500 or higher."

        Design: Difficulty/non_linear_state_machine/membership_standing_good_probation_good_cycle
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-NL2", provider_npi="1000000051",
            specialist_npi="2000000051", reviewer_npi="2000000052",
            with_reviewer=True, disposition="MANAGE_WITH_PLAN",
        )
        # First review: composite 4000 REBUKE -> PROBATION (6400).
        review1 = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        complete_review(review1["id"], scenario["reviewer"]["id"],
                        timeliness_score=2, appropriateness_score=1,
                        clarity_score=4, verdict="REBUKE")
        assert get_membership(scenario["membership"]["id"])["standing"] == "PROBATION"
        # Revise back to SUBMITTED, then a 5/5/5 PASS (composite 10000).
        revise_response(
            scenario["response"]["id"], scenario["specialist"]["id"],
            recommendation_text="Order TTE within 2 weeks and cardiology follow-up; avoid maximal exertion until echo result is reviewed.",
        )
        review2 = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        complete_review(review2["id"], scenario["reviewer"]["id"],
                        timeliness_score=5, appropriateness_score=5,
                        clarity_score=5, verdict="PASS")
        membership = get_membership(scenario["membership"]["id"])
        # Review average (4000 + 10000) / 2 = 7000; blend 0.6*7000 + 0.4*10000 = 8200.
        assert membership["quality_score_bps"] == 8200
        assert membership["standing"] == "GOOD_STANDING", (
            "8200 >= 7500 recovery threshold must close the cycle"
        )

    def test_composite_5000_yields_exactly_7000_blend(self, api):
        """PRD §3.7: "The blended score is six times the review component plus four
        times the timeliness component, the sum divided by ten, rounded half up."

        Design: Difficulty/boundary_precision_check/standing_demotion_boundary_at_7000_bps
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-BP2", provider_npi="1000000111",
            specialist_npi="2000000111", reviewer_npi="2000000112",
            with_reviewer=True,
            consult_overrides={
                "question_text": "Asymptomatic bradycardia 48bpm on routine exam, athlete; asks if any workup is warranted.",
                "icd10_primary": "R00",
            },
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        completed = complete_review(review["id"], scenario["reviewer"]["id"],
                                    timeliness_score=2, appropriateness_score=2,
                                    clarity_score=4, verdict="REBUKE")
        # (2*50 + 2*25 + 4*25) / 5 = 50 -> 5000 bps; 5000 < 6000 so REBUKE agrees.
        assert completed["composite_score_bps"] == 5000
        membership = get_membership(scenario["membership"]["id"])
        # Blend: 0.6 * 5000 + 0.4 * 10000 = 7000 exactly.
        assert membership["quality_score_bps"] == 7000

    def test_standing_holds_good_at_exactly_7000(self, api):
        """PRD §3.7: "A membership in `GOOD_STANDING` drops to `SUSPENDED` when its
        score falls below 5000, and otherwise drops to `PROBATION` when its score
        falls below 7000." — 7000 is not below 7000, so no demotion occurs.

        Design: Difficulty/boundary_precision_check/standing_demotion_boundary_at_7000_bps
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-BP2", provider_npi="1000000111",
            specialist_npi="2000000111", reviewer_npi="2000000112",
            with_reviewer=True,
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=2, appropriateness_score=2,
                        clarity_score=4, verdict="REBUKE")
        membership = get_membership(scenario["membership"]["id"])
        assert membership["quality_score_bps"] == 7000
        assert membership["standing"] == "GOOD_STANDING", (
            "demotion is strict < 7000; exactly 7000 must keep GOOD_STANDING"
        )
        assert membership["rebuke_count"] == 1

    def test_rebuke_cascades_review_to_response(self, api):
        """PRD §3.7: "When the verdict is `REBUKE`, the consequences cascade. The
        response itself moves from `SUBMITTED` to `REBUKED`"

        Design: Difficulty/transitive_cascade/rebuke_cascades_review_response_ledger_standing
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-TC1", provider_npi="1000000061",
            specialist_npi="2000000061", reviewer_npi="2000000062",
            with_reviewer=True,
            consult_overrides={
                "question_text": "Requesting cath referral for atypical symptoms with negative stress test; appropriateness check.",
                "icd10_primary": "R07",
            },
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        completed = complete_review(review["id"], scenario["reviewer"]["id"],
                                    timeliness_score=2, appropriateness_score=1,
                                    clarity_score=4, verdict="REBUKE")
        # Link 1: the review itself completes with the band-consistent verdict.
        assert completed["status"] == "COMPLETED"
        assert completed["composite_score_bps"] == 4000
        assert completed["verdict"] == "REBUKE"
        # Link 2: the response is driven to REBUKED.
        assert get_response(scenario["response"]["id"])["status"] == "REBUKED"

    def test_rebuke_cascades_to_ledger_and_standing(self, api):
        """PRD §3.7: "every `PROVISIONAL` compensation entry for the consult — the
        response fee and any clarification fees — is `REVERSED`, shrinking
        `provisional_balance_cents`; and the membership's `rebuke_count` increases by
        one."
        PRD §3.7: "A membership in `GOOD_STANDING` drops to `SUSPENDED` when its score
        falls below 5000, and otherwise drops to `PROBATION` when its score falls
        below 7000."

        Design: Difficulty/transitive_cascade/rebuke_cascades_review_response_ledger_standing
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-TC1", provider_npi="1000000061",
            specialist_npi="2000000061", reviewer_npi="2000000062",
            with_reviewer=True,
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=2, appropriateness_score=1,
                        clarity_score=4, verdict="REBUKE")
        # Link 3: the provisional RESPONSE_FEE entry is REVERSED; balance drained.
        entries, _meta = validate_paginated(api.list_compensation_entries(
            COORD, params={"consult_id": scenario["consult"]["id"]}
        ))
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "RESPONSE_FEE"
        assert entries[0]["posture"] == "REVERSED"
        # Link 4: rebuke counted and the blend (6400 < 7000) demotes to PROBATION.
        membership = get_membership(scenario["membership"]["id"])
        assert membership["rebuke_count"] == 1
        assert membership["provisional_balance_cents"] == 0
        assert membership["quality_score_bps"] == 6400
        assert membership["standing"] == "PROBATION"

    def test_reinstate_requires_suspended_returns_invalid_state(self, api):
        """PRD §3.7: "only a `ProgramCoordinator` may reinstate a membership, moving
        it from `SUSPENDED` to `PROBATION` and restoring `is_accepting` to true;
        reinstatement attempted on a membership that is not `SUSPENDED` is rejected
        with `ERR_MEMBERSHIP_NOT_SUSPENDED`."

        Design: Corner/state_machines/reinstate_requires_suspended_returns_invalid_state
        """
        scenario = setup_panel_scenario(specialist_npi="2000002008")
        res = api.reinstate_membership(scenario["membership"]["id"], COORD)
        validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_SUSPENDED,
                       expected_status=409)
