"""Episode lifecycle: DRAFT creation, DRAFT cancellation, EVALUATED
cascade on initial evaluation finalization.

PRD §3.2.
"""
from __future__ import annotations

from test_helpers import (
    TEST_USERS,
    anchor_clock,
    assert_episode,
    create_episode,
    create_evaluation,
    create_patient,
    create_pta_therapist,
    create_dpt_therapist,
    finalize_evaluation,
    make_therapist_headers,
    re_get_episode,
    validate_error,
    validate_success,
)
from test_helpers import create_episode_payload


# ===========================================================================
# Episode creation — PRD §3.2.
# ===========================================================================
class TestEpisodeCreation:

    def test_create_episode_in_draft(self, api):
        """PRD §3.2: "The episode is created in status DRAFT with its
        three unit counters and the boolean kx_modifier_required
        initialized to 0 and false respectively, and cap_policy and
        discharge_outcome left unset."

        Claim: new Episode → status=DRAFT, kx_modifier_required=false,
        all three unit counters = 0.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        res = api.create_episode(
            create_episode_payload(
                patient_id=patient["id"],
                body_region="LUMBAR",
            ),
            make_therapist_headers(therapist["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_episode(data)
        assert data["status"] == "DRAFT"
        assert data["kx_modifier_required"] is False
        assert data["total_authorized_units"] == 0
        assert data["total_committed_units"] == 0
        assert data["total_reserved_units"] == 0


# ===========================================================================
# DRAFT → CANCELLED — PRD §3.2.
# ===========================================================================
class TestDraftCancellation:

    def test_delete_draft_episode_cancels_it(self, api):
        """PRD §3.2: "While the episode remains in DRAFT, the same
        therapist can abandon it; deleting a DRAFT episode moves it
        directly to the terminal CANCELLED status."

        Claim: DELETE /episodes/{id} on a DRAFT moves it to CANCELLED.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        # PRD §4: DELETE returns 204.
        res = api.delete_episode(
            episode["id"], make_therapist_headers(therapist["id"]),
        )
        # 204 has no body; just check we got a 2xx.
        assert 200 <= res.status_code < 300, (
            f"Expected 2xx, got {res.status_code}"
        )
        # After delete, the episode is in CANCELLED.
        ep = re_get_episode(episode["id"])
        assert ep["status"] == "CANCELLED", (
            f"After DELETE, status must be CANCELLED, got {ep['status']!r}"
        )

    def test_delete_non_draft_episode_rejected(self, api):
        """PRD §3.2: "Once any evaluation has been finalized the
        episode is past DRAFT and can no longer be cancelled in that
        way."

        Claim: DELETE /episodes/{id} on a non-DRAFT episode (one whose
        initial evaluation has been finalized → status=EVALUATED) is
        rejected with ERR_INVALID_STATE.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        # Bring episode past DRAFT.
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        ep = re_get_episode(episode["id"])
        assert ep["status"] == "EVALUATED"
        # Now attempt to DELETE — should be rejected.
        res = api.delete_episode(
            episode["id"], make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# DRAFT → EVALUATED cascade — PRD §3.2.
# ===========================================================================
class TestInitialFinalizeCascade:

    def test_initial_evaluation_finalize_moves_episode_to_evaluated(
            self, api):
        """PRD §3.2: "when the finalized evaluation is the first
        INITIAL evaluation and the episode is in DRAFT, the episode
        advances from DRAFT to EVALUATED and Episode.cap_policy is
        stamped."

        Claim: after the first INITIAL eval is finalized, episode
        moves DRAFT → EVALUATED.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        ep = re_get_episode(episode["id"])
        assert ep["status"] == "EVALUATED"

    def test_medicare_part_b_finalize_stamps_cap_policy_capped(self, api):
        """PRD §3.2: "set to CAPPED when Patient.insurance_type is
        MEDICARE_PART_B, otherwise UNCAPPED."

        Claim: MEDICARE_PART_B + first INITIAL finalize → Episode.cap_policy
        == CAPPED.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="MEDICARE_PART_B")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        ep = re_get_episode(episode["id"])
        assert ep["cap_policy"] == "CAPPED", (
            f"MEDICARE_PART_B patient → cap_policy=CAPPED, "
            f"got {ep.get('cap_policy')!r}"
        )

    def test_commercial_finalize_stamps_cap_policy_uncapped(self, api):
        """PRD §3.2: "set to CAPPED when Patient.insurance_type is
        MEDICARE_PART_B, otherwise UNCAPPED."

        Claim: COMMERCIAL + first INITIAL finalize → cap_policy ==
        UNCAPPED.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        ep = re_get_episode(episode["id"])
        assert ep["cap_policy"] == "UNCAPPED", (
            f"COMMERCIAL patient → cap_policy=UNCAPPED, "
            f"got {ep.get('cap_policy')!r}"
        )

    def test_va_finalize_stamps_cap_policy_uncapped(self, api):
        """PRD §3.2: "otherwise UNCAPPED."

        Claim: VA + first INITIAL finalize → cap_policy == UNCAPPED.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="VA")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        ep = re_get_episode(episode["id"])
        assert ep["cap_policy"] == "UNCAPPED"
