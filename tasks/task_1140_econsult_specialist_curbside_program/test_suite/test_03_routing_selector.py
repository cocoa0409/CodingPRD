"""Routing selector: eligibility filters, deterministic ranking, audit rows."""
from test_helpers import (
    ApiErrorId, TEST_USERS, assert_routing_decision, complete_review,
    create_consult, create_membership, create_provider, create_specialist,
    create_track, create_window, get_consult, get_membership,
    make_provider_headers, open_review, set_clock, setup_assigned_consult,
    setup_late_answered_consult, setup_panel_scenario, submit_response,
    validate_error, validate_paginated, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestRoutingSelector:
    def test_routing_decision_logged_for_assignment(self, api):
        """PRD §3.2: "Every routing pass — successful or not — appends an immutable
        `RoutingDecision` audit row recording the `consult_id`, an `outcome` of
        `ASSIGNED` or `QUEUED`, the `candidate_count` (the size of the eligible pool
        at decision time), the `selected_membership_id` (null when queued), and a
        human-readable `ranking_basis`"

        Design: Corner/endpoints/routing_decision_logged_for_assignment
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-EP1", provider_npi="1000005002",
            specialist_npi="2000005002",
            consult_overrides={
                "question_text": "Secondary prevention question after peripheral artery disease diagnosis and stent placement.",
                "icd10_primary": "I73",
            },
        )
        consult = scenario["consult"]
        assert consult["status"] == "ASSIGNED"
        decisions, _meta = validate_paginated(
            api.list_routing_decisions(consult["id"], COORD)
        )
        assert len(decisions) == 1, f"exactly one routing decision, got {len(decisions)}"
        decision = decisions[0]
        assert_routing_decision(decision)
        assert decision["outcome"] == "ASSIGNED"
        assert decision["candidate_count"] == 1
        assert decision["selected_membership_id"] == scenario["membership"]["id"]
        assert isinstance(decision["ranking_basis"], str) and decision["ranking_basis"]

    def test_routing_tie_break_prefers_earliest_membership(self, api):
        """PRD §3.2: "the selector ranks candidates by `open_consult_count` ascending,
        then by `quality_score_bps` descending, then by the membership's `created_at`
        ascending as the final deterministic tie-break; the membership `id` must never
        be consulted for ranking."

        Design: Corner/calculations/routing_tie_break_prefers_earliest_membership
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        provider = create_provider(npi="1000003004")
        spec_a = create_specialist(npi="2000003004", full_name="Dr. Alpha Specialist")
        memb_a = create_membership(spec_a["id"], track["id"])
        create_window(memb_a["id"], spec_a["id"])
        # Advance the logical clock so the second membership has a later created_at.
        set_clock("2026-06-01T00:00:01Z")
        spec_b = create_specialist(npi="2000003005", full_name="Dr. Beta Specialist")
        memb_b = create_membership(spec_b["id"], track["id"])
        create_window(memb_b["id"], spec_b["id"])

        consult = create_consult(
            track["id"], provider["id"], patient_ref="PAT-C4",
            question_text="Stable coronary disease, asks about adding ranolazine for persistent exertional symptoms.",
            icd10_primary="I25",
        )
        assert consult["status"] == "ASSIGNED"
        # Both memberships tie on open_consult_count (0) and quality_score_bps
        # (8500); the earlier-created membership wins the deterministic tie-break.
        assert consult["assigned_membership_id"] == memb_a["id"], (
            f"earlier-created membership must win the tie, got "
            f"{consult['assigned_membership_id']}"
        )
        decisions, _meta = validate_paginated(
            api.list_routing_decisions(consult["id"], COORD)
        )
        assert decisions[0]["candidate_count"] == 2
        assert decisions[0]["selected_membership_id"] == memb_a["id"]

    def test_routing_skips_probation_membership_and_reroute_errors(self, api):
        """PRD §3.2: the eligible pool requires "the membership's `standing` is
        `GOOD_STANDING`".
        PRD §3.3: "The consult must actually be `QUEUED` — re-routing any other status
        is rejected with `ERR_CONSULT_NOT_QUEUED` — and the selector must find a
        non-empty pool, or the attempt fails with `ERR_NO_ELIGIBLE_SPECIALIST`."
        PRD §3.7: "A membership in `GOOD_STANDING` drops to `SUSPENDED` when its score
        falls below 5000, and otherwise drops to `PROBATION` when its score falls
        below 7000."

        Design: Corner/calculations/routing_skips_probation_membership_and_reroute_errors
        """
        scenario = setup_late_answered_consult(
            patient_ref="PAT-C5A", provider_npi="1000003005",
            specialist_npi="2000003006", with_reviewer=False,
            consult_overrides={
                "question_text": "Warfarin bridging question for AF ablation scheduled next month; periprocedural plan.",
                "icd10_primary": "I48",
            },
        )
        # One late response: timeliness component 0, review default 8500 ->
        # blend 5100 < 7000 -> PROBATION, so the only membership leaves the pool.
        membership = get_membership(scenario["membership"]["id"])
        assert membership["standing"] == "PROBATION"
        assert membership["quality_score_bps"] == 5100

        res = api.create_consult_request({
            "patient_ref": "PAT-C5B",
            "specialty_track_id": scenario["track"]["id"],
            "question_text": "New atrial flutter diagnosis; asks about ablation referral timing versus rate control trial.",
            "icd10_primary": "I48",
            "urgency": "ROUTINE",
        }, make_provider_headers(scenario["provider"]["id"]))
        consult2 = validate_success(res, 201)
        assert consult2["status"] == "QUEUED"
        assert consult2["assigned_membership_id"] is None

        # Reroute with the correct OCC version still fails: the pool is empty.
        res = api.reroute_consult(
            consult2["id"], {"expected_consult_version": consult2["version"]}, COORD
        )
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_SPECIALIST, expected_status=409)

    def test_routing_capacity_boundary_queues_sixth_consult(self, api):
        """PRD §3.2: the eligible pool requires "the membership's `open_consult_count`
        is below the program-wide ceiling of 5 open consults".

        Design: Corner/cross_cutting_layers/routing_capacity_boundary_queues_sixth_consult
        """
        scenario = setup_panel_scenario(provider_npi="1000007001",
                                        specialist_npi="2000007001")
        track_id = scenario["track"]["id"]
        prov_id = scenario["provider"]["id"]
        questions = [
            ("PAT-CAP1", "Capacity filler consult one regarding routine lipid management in primary prevention.", "E78"),
            ("PAT-CAP2", "Capacity filler consult two regarding home blood pressure monitoring technique.", "I10"),
            ("PAT-CAP3", "Capacity filler consult three regarding exercise thresholds after stent placement.", "Z95"),
            ("PAT-CAP4", "Capacity filler consult four regarding aspirin therapy in primary prevention setting.", "Z13"),
            ("PAT-CAP5", "Capacity filler consult five regarding salt intake targets in treated hypertension.", "I10"),
        ]
        for patient_ref, question, icd in questions:
            created = create_consult(track_id, prov_id, patient_ref=patient_ref,
                                     question_text=question, icd10_primary=icd)
            assert created["status"] == "ASSIGNED"
        membership = get_membership(scenario["membership"]["id"])
        assert membership["open_consult_count"] == 5, (
            f"five assignments must sit exactly at the ceiling, got "
            f"{membership['open_consult_count']}"
        )
        # The sixth consult finds the pool empty (5 is NOT below 5) and queues.
        res = api.create_consult_request({
            "patient_ref": "PAT-CAP6",
            "specialty_track_id": track_id,
            "question_text": "Sixth consult about palpitations workup when the panel member is fully loaded.",
            "icd10_primary": "R00",
            "urgency": "ROUTINE",
        }, make_provider_headers(prov_id))
        sixth = validate_success(res, 201)
        assert sixth["status"] == "QUEUED"
        assert sixth["assigned_membership_id"] is None

    def test_suspended_membership_requeues_assigned_consult(self, api):
        """PRD §3.7: "The moment a membership enters `SUSPENDED`, its `is_accepting`
        flips to false, and every consult currently `ASSIGNED` or
        `CLARIFICATION_REQUESTED` to that membership is re-queued: each such consult's
        `assigned_specialist_id` and `assigned_membership_id` are cleared to null, its
        `open_consult_count` contribution is decremented, and a `RoutingDecision` with
        outcome `QUEUED` and `ranking_basis` "SPECIALIST_SUSPENDED" is appended per
        consult."

        Design: Corner/state_machines/suspended_membership_requeues_assigned_consult
        """
        scenario = setup_panel_scenario(provider_npi="1000002010",
                                        specialist_npi="2000002010",
                                        reviewer_npi="2000002011",
                                        with_reviewer=True)
        track_id = scenario["track"]["id"]
        prov_id = scenario["provider"]["id"]
        spec_id = scenario["specialist"]["id"]
        cons_1 = create_consult(track_id, prov_id, patient_ref="PAT-S9A",
                                question_text="Post-stent dual antiplatelet duration question for stable patient at 11 months.",
                                icd10_primary="Z95")
        cons_2 = create_consult(track_id, prov_id, patient_ref="PAT-S9B",
                                question_text="Lipid management in very high risk patient already on maximal statin and ezetimibe.",
                                icd10_primary="E78")
        assert cons_1["status"] == "ASSIGNED" and cons_2["status"] == "ASSIGNED"

        # Late answer on consult 1 -> blend 5100 -> PROBATION.
        set_clock("2026-06-03T01:00:00Z")
        resp_1 = submit_response(cons_1["id"], spec_id)
        # Rebuke (composite 4000) -> blend 2400 < 5000 -> SUSPENDED.
        review = open_review(resp_1["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=2, appropriateness_score=1,
                        clarity_score=4, verdict="REBUKE")

        membership = get_membership(scenario["membership"]["id"])
        assert membership["standing"] == "SUSPENDED"
        assert membership["is_accepting"] is False
        # 2 assigned - 1 answered - 1 re-queued = 0 open consults.
        assert membership["open_consult_count"] == 0

        consult2_after = get_consult(cons_2["id"])
        assert consult2_after["status"] == "QUEUED"
        assert consult2_after["assigned_membership_id"] is None
        assert consult2_after["assigned_specialist_id"] is None

        decisions, _meta = validate_paginated(
            api.list_routing_decisions(cons_2["id"], COORD)
        )
        assert len(decisions) == 2
        assert decisions[0]["outcome"] == "ASSIGNED"
        assert decisions[1]["outcome"] == "QUEUED"
        assert decisions[1]["ranking_basis"] == "SPECIALIST_SUSPENDED"
