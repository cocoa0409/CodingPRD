"""Two-posture compensation ledger: provisional vs posted variants, conservation."""
from test_helpers import (
    TEST_USERS, complete_review, create_consult, document_response,
    finalize_response, get_membership, get_summary,
    make_provider_headers, open_review, setup_answered_consult,
    setup_assigned_consult, setup_late_answered_consult, setup_panel_scenario,
    submit_response, validate_paginated, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestCompensationLedger:
    def _setup_late_answered_with_pass_review(self):
        """Late consult (on_time False) with a completed 5/5/5 PASS review and both
        documentation notes written — one step short of finalize.

        After the late answer the blend is 5100 (PROBATION); the PASS review lifts
        the review component to 10000, giving blend 6000 at finalize time.
        """
        scenario = setup_late_answered_consult(
            patient_ref="PAT-DV1", provider_npi="1000000021",
            specialist_npi="2000000021", reviewer_npi="2000000022",
            consult_overrides={
                "question_text": "Patient with persistent atypical chest pain and normal ECG; need guidance on ischemic workup.",
                "icd10_primary": "R07",
            },
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=5, appropriateness_score=5,
                        clarity_score=5, verdict="PASS")
        document_response(scenario["response"]["id"], scenario["provider"]["id"],
                          scenario["specialist"]["id"])
        return scenario

    def test_provisional_fee_at_submission_ignores_band_and_penalty(self, api):
        """PRD §3.5: "A `RESPONSE_FEE` compensation entry is appended at the
        provisional base: the track's `conversion_response_fee_cents` when the
        disposition is `CONVERT_TO_VISIT`, otherwise the track's
        `base_response_fee_cents` — no quality multiplier and no late penalty apply at
        this stage. The membership's `provisional_balance_cents` grows by that
        provisional amount"

        Design: Difficulty/dual_variant_calc/provisional_vs_posted_response_compensation_diverge
        """
        scenario = self._setup_late_answered_with_pass_review()
        response = scenario["response"]
        # The response was submitted 1h after sla_due_at: late.
        assert response["on_time"] is False
        # Before finalize: the full provisional base (10000) sits provisional and
        # nothing is posted, even though the response is late.
        summary = get_summary(scenario["membership"]["id"])
        assert summary["provisional_balance_cents"] == 10000
        assert summary["posted_balance_cents"] == 0

    def test_posted_fee_diverges_from_provisional_at_finalize(self, api):
        """PRD §3.6: "start from the same disposition base used provisionally, apply
        the quality band read from the membership's `quality_score_bps` **at finalize
        time** — a score of 9000 or above multiplies the base by 1.20; 7500 through
        8999 multiplies it by 1.00; 5000 through 7499 by 0.80; below 5000 by 0.50 —
        and round the product half up to whole cents. From that gross, subtract the
        track's `late_penalty_cents` when the response's `on_time` is false (nothing
        otherwise), and floor the result at zero so a penalty can never make a payment
        negative."
        PRD §3.6: "Because the posted response fee reflects the quality band and
        lateness, identical response data can legitimately yield a posted amount
        different from the provisional one."

        Design: Difficulty/dual_variant_calc/provisional_vs_posted_response_compensation_diverge
        """
        scenario = self._setup_late_answered_with_pass_review()
        finalized = finalize_response(scenario["response"]["id"],
                                      scenario["specialist"]["id"])
        assert finalized["status"] == "FINALIZED"
        # Score at finalize time is 6000 (band 0.80) and the response was late
        # (penalty 3000): posted = max(0, 10000 * 0.80 - 3000) = 5000.
        summary = get_summary(scenario["membership"]["id"])
        assert summary["provisional_balance_cents"] == 0
        assert summary["posted_balance_cents"] == 5000, (
            "posted 5000 diverges from provisional 10000 for identical response data"
        )

    def _setup_two_consults_with_excellent_score(self):
        """Consult 1 answered on time with a 5/5/5 PASS review, driving the blended
        score to 10000 (band 1.20). Consult 2 answered on time and documented."""
        scenario = setup_panel_scenario(provider_npi="1000000021",
                                        specialist_npi="2000000021",
                                        reviewer_npi="2000000022",
                                        with_reviewer=True)
        track_id = scenario["track"]["id"]
        prov_id = scenario["provider"]["id"]
        spec_id = scenario["specialist"]["id"]
        cons_1 = create_consult(
            track_id, prov_id, patient_ref="PAT-CF1",
            question_text="Palpitations with normal holter; asks whether event monitor or empiric beta blocker is next step.",
            icd10_primary="R00",
        )
        resp_1 = submit_response(cons_1["id"], spec_id, disposition="MANAGE_WITH_PLAN")
        review = open_review(resp_1["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=5, appropriateness_score=5,
                        clarity_score=5, verdict="PASS")
        cons_2 = create_consult(
            track_id, prov_id, patient_ref="PAT-CF2",
            question_text="Stage 1 hypertension on lisinopril, home readings still elevated; add amlodipine or uptitrate?",
            icd10_primary="I10",
        )
        resp_2 = submit_response(cons_2["id"], spec_id,
                                 disposition="MANAGE_IN_PRIMARY_CARE")
        document_response(resp_2["id"], prov_id, spec_id)
        scenario["consult"] = cons_2
        scenario["response"] = resp_2
        return scenario

    def test_excellent_band_setup_reaches_score_10000(self, api):
        """PRD §3.7: "The blended score is six times the review component plus four
        times the timeliness component, the sum divided by ten, rounded half up."

        Design: Difficulty/combinatorial_formula/final_compensation_three_input_band_interaction
        """
        scenario = self._setup_two_consults_with_excellent_score()
        membership = get_membership(scenario["membership"]["id"])
        # Review component 10000 (one 5/5/5 review), timeliness 10000 (2/2 on time).
        assert membership["quality_score_bps"] == 10000
        # Before finalize, consult 2's RESPONSE_FEE entry is the flat provisional base.
        entries, _meta = validate_paginated(api.list_compensation_entries(
            COORD, params={"consult_id": scenario["consult"]["id"]}
        ))
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "RESPONSE_FEE"
        assert entries[0]["amount_cents"] == 10000
        assert entries[0]["posture"] == "PROVISIONAL"

    def test_finalize_posts_12000_under_excellent_band(self, api):
        """PRD §3.6: "apply the quality band read from the membership's
        `quality_score_bps` **at finalize time** — a score of 9000 or above multiplies
        the base by 1.20"
        PRD §3.6: "The consult's `RESPONSE_FEE` entry flips from `PROVISIONAL` to
        `POSTED`, and its `amount_cents` is recomputed at the final variant"

        Design: Difficulty/combinatorial_formula/final_compensation_three_input_band_interaction
        """
        scenario = self._setup_two_consults_with_excellent_score()
        finalize_response(scenario["response"]["id"], scenario["specialist"]["id"])
        entries, _meta = validate_paginated(api.list_compensation_entries(
            COORD, params={"consult_id": scenario["consult"]["id"]}
        ))
        assert len(entries) == 1
        # round_half_up(10000 * 12000 / 10000) = 12000; on time -> no penalty.
        assert entries[0]["amount_cents"] == 12000
        assert entries[0]["posture"] == "POSTED"

    def test_compensation_summary_matches_ledger(self, api):
        """PRD §2.6: "A membership's `provisional_balance_cents` is the sum of
        `amount_cents` over its `PROVISIONAL` entries, and its `posted_balance_cents`
        is the sum over its `POSTED` entries; both are maintained eagerly as entries
        change posture, so a read of the membership always reflects the current
        ledger."
        PRD §3.6: "A computed summary read on any membership returns its
        `provisional_balance_cents`, `posted_balance_cents`, the `reversed_total_cents`
        accumulated across reversed entries, and its current `open_consult_count`."

        Design: Corner/endpoints/compensation_summary_matches_ledger
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-EP2", provider_npi="1000005003",
            specialist_npi="2000005003",
            consult_overrides={
                "question_text": "Question about preoperative beta blocker continuation before elective hip surgery.",
                "icd10_primary": "Z01",
            },
        )
        entries, _meta = validate_paginated(api.list_compensation_entries(
            COORD, params={"consult_id": scenario["consult"]["id"]}
        ))
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "RESPONSE_FEE"
        assert entry["amount_cents"] == 10000
        assert entry["posture"] == "PROVISIONAL"
        assert entry["period_key"] == "2026-06"
        summary = get_summary(scenario["membership"]["id"])
        assert summary["provisional_balance_cents"] == entry["amount_cents"]
        assert summary["posted_balance_cents"] == 0
        assert summary["reversed_total_cents"] == 0

    def test_provisional_cents_added_at_submit(self, api):
        """PRD §3.5: "The membership's `provisional_balance_cents` grows by that
        provisional amount, `responded_count` increases by one, `on_time_count`
        increases by one when the response was on time, and `open_consult_count`
        decreases by one."

        Design: Difficulty/compensating_invariant/provisional_cents_conserved_across_submit_and_rebuke
        """
        scenario = setup_panel_scenario(provider_npi="1000000161",
                                        specialist_npi="2000000161")
        before = get_summary(scenario["membership"]["id"])
        assert before["provisional_balance_cents"] == 0
        consult = create_consult(
            scenario["track"]["id"], scenario["provider"]["id"], patient_ref="PAT-CI1",
            question_text="Wolff-Parkinson-White pattern on ECG, asymptomatic; asks about activity restrictions pending ablation.",
            icd10_primary="I45",
        )
        submit_response(consult["id"], scenario["specialist"]["id"],
                        disposition="MANAGE_WITH_PLAN")
        after = get_summary(scenario["membership"]["id"])
        # Forward action: +10000 provisional cents (MANAGE_WITH_PLAN base).
        assert after["provisional_balance_cents"] == 10000

    def test_rebuke_reversal_restores_provisional_zero(self, api):
        """PRD §3.7: "every `PROVISIONAL` compensation entry for the consult — the
        response fee and any clarification fees — is `REVERSED`, shrinking
        `provisional_balance_cents`"
        PRD §2.6: "A membership's `provisional_balance_cents` is the sum of
        `amount_cents` over its `PROVISIONAL` entries"

        Design: Difficulty/compensating_invariant/provisional_cents_conserved_across_submit_and_rebuke
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-CI1", provider_npi="1000000161",
            specialist_npi="2000000161", reviewer_npi="2000000162",
            with_reviewer=True, disposition="MANAGE_WITH_PLAN",
        )
        baseline = get_summary(scenario["membership"]["id"])
        assert baseline["provisional_balance_cents"] == 10000
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=2, appropriateness_score=1,
                        clarity_score=4, verdict="REBUKE")
        restored = get_summary(scenario["membership"]["id"])
        # The compensating action restores the conserved quantity exactly to zero.
        assert restored["provisional_balance_cents"] == 0

    def test_open_consult_count_increments_on_assign(self, api):
        """PRD §3.2: "The winning membership is recorded on the consult through
        `assigned_specialist_id` and `assigned_membership_id`, its `open_consult_count`
        increases by one (which refreshes the membership's `updated_at` and increments
        its `version`), and the consult lands in `ASSIGNED`."

        Design: Difficulty/compensating_invariant/open_consult_count_conserved_across_assign_and_cancel
        """
        scenario = setup_panel_scenario(provider_npi="1000000171",
                                        specialist_npi="2000000171")
        before = get_membership(scenario["membership"]["id"])
        assert before["open_consult_count"] == 0
        consult = create_consult(
            scenario["track"]["id"], scenario["provider"]["id"], patient_ref="PAT-CI2",
            question_text="Asks whether home INR monitoring is appropriate for stable mechanical valve patient.",
            icd10_primary="Z95",
        )
        assert consult["status"] == "ASSIGNED"
        after = get_membership(scenario["membership"]["id"])
        assert after["open_consult_count"] == 1

    def test_cancel_restores_open_consult_count(self, api):
        """PRD §3.3: "Cancelling a consult in `ASSIGNED` or `CLARIFICATION_REQUESTED`
        decrements the holding membership's `open_consult_count` by one"
        PRD §3.3: "In all four cases the consult becomes `CANCELLED`, its
        `billing_status` moves from `UNBILLABLE` to `VOID`, and its `version`
        increments."

        Design: Difficulty/compensating_invariant/open_consult_count_conserved_across_assign_and_cancel
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-CI2", provider_npi="1000000171",
            specialist_npi="2000000171",
            consult_overrides={
                "question_text": "Asks whether home INR monitoring is appropriate for stable mechanical valve patient.",
                "icd10_primary": "Z95",
            },
        )
        assert get_membership(scenario["membership"]["id"])["open_consult_count"] == 1
        cancelled = validate_success(api.cancel_consult(
            scenario["consult"]["id"],
            make_provider_headers(scenario["provider"]["id"]),
        ), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["billing_status"] == "VOID"
        # The counter returns exactly to its pre-assignment value.
        assert get_membership(scenario["membership"]["id"])["open_consult_count"] == 0
