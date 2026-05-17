"""Supervisor + SupervisionAssignment lifecycle.

PRD §3.3 (create supervisor, pair via SupervisionAssignment, terminate).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_supervision_assignment,
    assert_supervisor,
    create_supervision_assignment,
    create_supervision_assignment_payload,
    create_supervisor,
    create_supervisor_payload,
    create_therapist,
    terminate_supervision_assignment,
    validate_error,
    validate_success,
)


class TestSupervisor:

    def test_create_supervisor_minimal_payload(self, api):
        """PRD §3.3: "A Supervisor is recorded with their full_name,
        their home_state_code (two-letter US state where the supervisor
        is fully licensed), and an active flag that defaults to true
        indicating availability for new supervisees."

        Claim: a freshly-created Supervisor has the recorded fields and
        active=true by default.
        """
        res = api.create_supervisor(
            create_supervisor_payload(),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_supervisor(data)
        assert data["active"] is True


class TestSupervisionAssignment:

    def test_create_supervision_assignment_initial_state(self, api):
        """PRD §3.3: "The assignment is born in status = ACTIVE with
        ended_on left null."

        Claim: a freshly-created SupervisionAssignment has status=
        ACTIVE and ended_on null.
        """
        therapist = create_therapist(supervision_track="PRE_LICENSED")
        supervisor = create_supervisor()
        res = api.create_supervision_assignment(
            create_supervision_assignment_payload(
                therapist_id=therapist["id"],
                supervisor_id=supervisor["id"],
            ),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_supervision_assignment(data)
        assert data["status"] == "ACTIVE"
        assert data.get("ended_on") is None

    def test_supervision_assignment_has_no_version_field(self, api):
        """PRD §2.4: "A supervision assignment carries id and
        created_at but, by design, no updated_at and no version field;
        mutations to its status field are recorded on the lifecycle
        ledger rather than through the optimistic-concurrency channel."

        Claim: a SupervisionAssignment response payload does NOT carry
        updated_at or version fields.
        """
        therapist = create_therapist(supervision_track="PRE_LICENSED")
        supervisor = create_supervisor()
        res = api.create_supervision_assignment(
            create_supervision_assignment_payload(
                therapist_id=therapist["id"],
                supervisor_id=supervisor["id"],
            ),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert "version" not in data, (
            "SupervisionAssignment must not expose a version field"
        )
        assert "updated_at" not in data, (
            "SupervisionAssignment must not expose updated_at"
        )

    def test_terminate_supervision_assignment_transitions_to_terminated(
        self, api,
    ):
        """PRD §3.3: "The assignment is terminated by an administrative
        termination action, which writes status := TERMINATED and stamps
        ended_on to the current clock instant."

        Claim: terminate transitions an ACTIVE assignment to TERMINATED
        and sets ended_on to a non-null value.
        """
        therapist = create_therapist(supervision_track="PRE_LICENSED")
        supervisor = create_supervisor()
        assignment = create_supervision_assignment(
            therapist_id=therapist["id"],
            supervisor_id=supervisor["id"],
        )
        res = api.terminate_supervision_assignment(
            assignment["id"], TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "TERMINATED"
        assert data.get("ended_on") is not None

    def test_terminate_already_terminated_rejected(self, api):
        """PRD §3.3: termination transitions ACTIVE -> TERMINATED.
        PRD §2.7: "state-machine admissibility" gate fires before
        endpoint-specific checks.

        Claim: terminating an already TERMINATED assignment is
        rejected (state-machine admissibility — generic
        ERR_INVALID_STATE).
        """
        therapist = create_therapist(supervision_track="PRE_LICENSED")
        supervisor = create_supervisor()
        assignment = create_supervision_assignment(
            therapist_id=therapist["id"],
            supervisor_id=supervisor["id"],
        )
        terminate_supervision_assignment(assignment["id"])
        res = api.terminate_supervision_assignment(
            assignment["id"], TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
