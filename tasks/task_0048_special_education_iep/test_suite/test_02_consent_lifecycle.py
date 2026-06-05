"""Parental consent lifecycle: the branching-with-revert state machine
(PENDING → GRANTED/DENIED; GRANTED → REVOKED) and the invalid-transition guard
on an already-decided request (PRD §3.4).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_parent_headers,
    decide_consent_payload,
    set_clock,
    make_meeting_held_iep,
)

PAR = make_parent_headers("par_1")


class TestConsentBranching:
    def test_placement_consent_grant_then_revoke(self, api):
        """PRD §3.4: "When the `decision` is `GRANT`, the request moves `PENDING → GRANTED`; when the `decision` is `DENY`, it moves `PENDING → DENIED`."
        PRD §3.4: "The parent revokes a request that is currently `GRANTED`, moving it `GRANTED → REVOKED`, which is terminal; this increments the request's `version` by one."

        A PLACEMENT consent decided GRANT becomes GRANTED, then revoke takes it to
        REVOKED — the branch-then-revert shape.

        Design: Difficulty/non_linear_state_machine/consent_branching_revert_grant_revoke_rerequest
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, plc_cr_id = make_meeting_held_iep(
            student_overrides={"full_name": "Ivy Cole", "date_of_birth": "2014-07-07"},
        )
        granted = validate_success(
            api.decide_consent(plc_cr_id, decide_consent_payload("GRANT"), PAR), 200
        )
        assert granted["status"] == "GRANTED", granted["status"]
        revoked = validate_success(api.revoke_consent(plc_cr_id, PAR), 200)
        assert revoked["status"] == "REVOKED", revoked["status"]

    def test_revoked_consent_cannot_be_re_decided(self, api):
        """PRD §3.4: "Because both `DENIED` and `REVOKED` are terminal, there is no path back to `PENDING` for the same request: to retry a consent after a denial or revocation, a fresh consent request must be created by re-running the workflow step that spawns it."

        After GRANT then REVOKE, a further decide on the same request is rejected
        with ERR_INVALID_STATE (the request is no longer PENDING).

        Design: Difficulty/non_linear_state_machine/consent_branching_revert_grant_revoke_rerequest
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, plc_cr_id = make_meeting_held_iep(
            student_overrides={"full_name": "Ivy Cole2", "date_of_birth": "2014-07-07"},
        )
        validate_success(
            api.decide_consent(plc_cr_id, decide_consent_payload("GRANT"), PAR), 200
        )
        validate_success(api.revoke_consent(plc_cr_id, PAR), 200)
        validate_error(
            api.decide_consent(plc_cr_id, decide_consent_payload("GRANT"), PAR),
            ApiErrorId.ERR_INVALID_STATE.value,
        )


class TestConsentInvalidTransitions:
    def test_decide_already_granted_consent_rejected(self, api):
        """PRD §3.4: "Either decision requires the request to currently be `PENDING`, stamps `decided_at` with the server clock, and increments the request's `version` by one."

        A second decide on an already-GRANTED request is rejected with
        ERR_INVALID_STATE; only PENDING requests are decidable.

        Design: Corner/state_machines/decide_already_decided_consent_returns_invalid_state
        """
        set_clock("2026-03-01T09:00:00Z")
        # Drive an EVALUATION consent to GRANTED, then try a second decide on it.
        from test_helpers import create_student, api_client, make_case_manager_headers, make_evaluator_headers
        cm = make_case_manager_headers("cm_1")
        student = create_student(set_clock_first=False, full_name="Mae Holt",
                                 date_of_birth="2014-04-04", grade_level=6)
        from test_helpers import create_evaluation_payload
        ev = validate_success(api.create_evaluation(create_evaluation_payload(student["id"]), cm), 201)
        validate_success(api.request_consent(ev["id"], cm), 200)
        body = api.list_consent_requests(
            PAR, params={"student_id": student["id"], "consent_type": "EVALUATION", "status": "PENDING"}
        ).json()
        cr_id = body["data"][0]["id"]
        validate_success(api.decide_consent(cr_id, decide_consent_payload("GRANT"), PAR), 200)
        validate_error(
            api.decide_consent(cr_id, decide_consent_payload("DENY"), PAR),
            ApiErrorId.ERR_INVALID_STATE.value,
        )
