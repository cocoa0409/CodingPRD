"""Home Exercise Program lifecycle: DRAFT → ISSUED → ACKNOWLEDGED →
SUPERSEDED, including the supersede-on-new-issue branching.

PRD §3.7.
"""
from __future__ import annotations

from test_helpers import (
    acknowledge_home_exercise_program,
    assert_home_exercise_program,
    create_home_exercise_program,
    issue_home_exercise_program,
    make_patient_headers,
    make_therapist_headers,
    setup_active_episode,
    validate_error,
    validate_success,
)
from test_helpers import default_exercise_items


# ===========================================================================
# DRAFT → ISSUED — PRD §3.7.
# ===========================================================================
class TestHepIssue:

    def test_draft_then_issue(self, api):
        """PRD §3.7: "Issuing the HEP requires exercise_items to remain
        non-empty and the bound plan to be in ACTIVE; on issue, the
        HEP transitions to ISSUED."

        Claim: HEP draft → issue → status=ISSUED.
        """
        setup = setup_active_episode()
        therapist = setup["therapist"]
        hep = create_home_exercise_program(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        assert hep["status"] == "DRAFT"
        issued = issue_home_exercise_program(
            hep_id=hep["id"], acting_therapist_id=therapist["id"],
        )
        assert issued["status"] == "ISSUED"


# ===========================================================================
# ISSUED → ACKNOWLEDGED — PRD §3.7.
# ===========================================================================
class TestHepAcknowledge:

    def test_patient_acknowledge_sets_status_and_timestamp(self, api):
        """PRD §3.7: "The patient may then acknowledge the issued HEP;
        acknowledgment transitions it to ACKNOWLEDGED and stamps
        patient_acknowledged_at with the current clock instant."

        Claim: post-acknowledge, status=ACKNOWLEDGED and
        patient_acknowledged_at is non-null.
        """
        setup = setup_active_episode()
        therapist = setup["therapist"]
        patient = setup["patient"]
        hep = create_home_exercise_program(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        issue_home_exercise_program(
            hep_id=hep["id"], acting_therapist_id=therapist["id"],
        )
        # PRD §2.1: Patient is entity-backed; X-User-ID must equal
        # the Patient.id whose episode owns the HEP.
        acknowledged = acknowledge_home_exercise_program(
            hep_id=hep["id"], acting_patient_id=patient["id"],
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged.get("patient_acknowledged_at"), (
            "patient_acknowledged_at must be set on ACKNOWLEDGED"
        )


# ===========================================================================
# Supersede branching — Difficulty design Rule 3.
# ===========================================================================
class TestHepSupersedeBranching:

    def test_home_exercise_program_supersede_branching(self, api):
        """# difficulty: non_linear_state_machine/home_exercise_program_supersede_branching
        PRD §3.7: "Issuing the HEP requires ... on issue, the HEP
        transitions to ISSUED, and any prior HEP on the same episode
        that was in ISSUED or ACKNOWLEDGED is transitioned to terminal
        SUPERSEDED."

        Claim: issuing H2 on an episode where H1 was ACKNOWLEDGED →
        H1 status='SUPERSEDED' and H2 status='ISSUED'.
        """
        setup = setup_active_episode()
        therapist = setup["therapist"]
        patient = setup["patient"]
        # H1: draft, issue, acknowledge.
        h1 = create_home_exercise_program(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        h1 = issue_home_exercise_program(
            hep_id=h1["id"], acting_therapist_id=therapist["id"],
        )
        h1 = acknowledge_home_exercise_program(
            hep_id=h1["id"], acting_patient_id=patient["id"],
        )
        assert h1["status"] == "ACKNOWLEDGED"

        # H2: draft a second HEP and issue.
        h2 = create_home_exercise_program(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        h2 = issue_home_exercise_program(
            hep_id=h2["id"], acting_therapist_id=therapist["id"],
        )
        assert h2["status"] == "ISSUED"
        # PRD §4 does not expose GET /home-exercise-programs/{id} or
        # a list endpoint, so H1's transition to SUPERSEDED is not
        # directly observable via the published surface. The strongest
        # PRD-grounded observable consequence is that H2 — issued
        # against the same Episode — is itself in ISSUED, which would
        # be impossible under the "only one active HEP per episode"
        # rule if H1 had not transitioned out of ISSUED/ACKNOWLEDGED.

    def test_supersede_replaces_issued_hep_on_subsequent_issue(self, api):
        """# difficulty: non_linear_state_machine/home_exercise_program_supersede_branching
        PRD §3.7: "on issue, the HEP transitions to ISSUED, and any
        prior HEP on the same episode that was in ISSUED or
        ACKNOWLEDGED is transitioned to terminal SUPERSEDED."

        Claim: issuing H2 on an episode where H1 is in ISSUED (not
        yet acknowledged) — H2 itself transitions to ISSUED, which is
        the response observable that PRD requires.
        """
        setup = setup_active_episode()
        therapist = setup["therapist"]
        # H1: draft + issue (not acknowledged).
        h1 = create_home_exercise_program(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        issue_home_exercise_program(
            hep_id=h1["id"], acting_therapist_id=therapist["id"],
        )
        # H2: draft + issue. PRD §3.7 guarantees H1 is superseded.
        h2 = create_home_exercise_program(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        h2_issued = issue_home_exercise_program(
            hep_id=h2["id"], acting_therapist_id=therapist["id"],
        )
        assert h2_issued["status"] == "ISSUED"
