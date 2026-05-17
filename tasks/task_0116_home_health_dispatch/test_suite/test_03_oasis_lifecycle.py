"""OASIS authoring, locking, supersede side effect, and recert window.

PRD §3.3 (OASIS lifecycle).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    anchor_clock,
    assert_oasis_assessment,
    create_oasis,
    create_oasis_payload,
    create_patient,
    lock_oasis,
    re_get_oasis,
    validate_error,
    validate_success,
)


# ===========================================================================
# OASIS create
# ===========================================================================
class TestOASISCreate:

    def test_create_draft_oasis_returns_resource(self, api):
        """PRD §3.3: "A new OASIS starts in DRAFT."

        Claim: POST /patients/{id}/oasis returns 201 with DRAFT status.
        """
        patient = create_patient()
        res = api.create_oasis(
            patient["id"],
            create_oasis_payload(),
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_oasis_assessment(data)
        assert data["status"] == "DRAFT"
        assert data["patient_id"] == patient["id"]

    def test_hha_companion_hours_defaults_to_zero_when_omitted(self, api):
        """PRD §3.3: "If the coordinator does not supply
        hha_companion_hours_ordered, it defaults to 0, which is a hard
        ceiling that blocks any HHA visit from being scheduled later."

        Claim: an OASIS created without hha_companion_hours_ordered
        comes back with the value 0.
        """
        patient = create_patient()
        # Build payload WITHOUT hha_companion_hours_ordered.
        payload = create_oasis_payload()
        assert "hha_companion_hours_ordered" not in payload
        res = api.create_oasis(
            patient["id"], payload,
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["hha_companion_hours_ordered"] == 0


# ===========================================================================
# OASIS lock — preconditions and side effects
# ===========================================================================
class TestOASISLock:

    def test_lock_draft_oasis_transitions_to_locked(self, api):
        """PRD §3.3: "Locking it — promoting it to LOCKED — is the
        prerequisite for opening an episode".

        Claim: POST /patients/{id}/oasis/{id}/lock transitions DRAFT to
        LOCKED.
        """
        patient = create_patient()
        oasis = create_oasis(patient=patient)
        before_version = oasis["version"]
        res = api.lock_oasis(
            patient["id"], oasis["id"],
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert_oasis_assessment(data)
        assert data["status"] == "LOCKED"
        assert data["version"] == before_version + 1, (
            "PRD §2.4: version increments by exactly 1 on mutation"
        )

    def test_cannot_lock_oasis_already_locked(self, api):
        """PRD §1.4 / §2.9 priority 4: "On POST /patients/{patientId}/
        oasis/{oasisId}/lock, OASIS.status == DRAFT" otherwise
        ERR_OASIS_NOT_DRAFT.

        Claim: attempting to lock an already-LOCKED OASIS is rejected
        with ERR_OASIS_NOT_DRAFT.
        """
        patient = create_patient()
        oasis = create_oasis(patient=patient)
        lock_oasis(patient=patient, oasis=oasis)
        res = api.lock_oasis(
            patient["id"], oasis["id"],
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_OASIS_NOT_DRAFT")

    def test_lock_supersedes_other_draft_oasis_on_same_patient(
        self, api,
    ):
        """PRD §3.3: "Locking carries a side effect: any other OASIS on
        the same patient still in DRAFT is moved to SUPERSEDED in the
        same atomic step, refreshing each superseded row's updated_at
        and incrementing its version."

        Claim: when a second DRAFT OASIS exists and the first is
        locked, the second is moved to SUPERSEDED.
        """
        patient = create_patient()
        o1 = create_oasis(patient=patient)
        o2 = create_oasis(patient=patient)
        # Lock o1.
        lock_oasis(patient=patient, oasis=o1)
        # Re-read o2.
        o2_after = re_get_oasis(patient["id"], o2["id"])
        assert o2_after["status"] == "SUPERSEDED", (
            "PRD §3.3: locking one OASIS supersedes other DRAFT OASIS "
            f"on the same patient. Got status={o2_after['status']}"
        )


# ===========================================================================
# OASIS recert window
# ===========================================================================
class TestRecertWindow:

    def test_recert_lock_outside_window_rejected(self, api):
        """PRD §3.3: "A RECERTIFICATION lock requires that the patient
        have a prior episode whose recert_due_date is on or before
        current_date and whose end_date is on or after current_date —
        i.e., the clock is inside the inclusive recertification window
        [prior_episode.recert_due_date, prior_episode.end_date]. A lock
        attempted outside that window is rejected with
        ERR_RECERT_WINDOW_VIOLATION."

        Claim: locking a RECERT OASIS on a patient with NO prior
        episode (so the precondition cannot be satisfied) is rejected
        with ERR_RECERT_WINDOW_VIOLATION.
        """
        anchor_clock()
        patient = create_patient()
        # Create a RECERTIFICATION OASIS WITHOUT first creating a prior
        # episode → the recert window cannot be satisfied regardless of
        # the clock.
        oasis = create_oasis(
            patient=patient,
            assessment_reason="RECERTIFICATION",
        )
        res = api.lock_oasis(
            patient["id"], oasis["id"],
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_RECERT_WINDOW_VIOLATION")
