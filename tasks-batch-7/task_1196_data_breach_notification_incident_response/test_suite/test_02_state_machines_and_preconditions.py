"""State-machine preconditions and invalid transitions
(corner design — state_machines section)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_affected_subject_payload,
    create_forensic_scope_payload,
    create_incident,
    create_incident_confirmed,
    create_incident_in_investigating_state,
    create_draft_notice,
    create_evidence_item_payload,
    create_jurisdiction_evaluation_payload,
    get_success_data,
    validate_error,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]
PC = TEST_USERS["privacy_counsel_headers"]
GC = TEST_USERS["general_counsel_headers"]
DA = TEST_USERS["data_analyst_headers"]


class TestInvalidTransitions:
    def test_confirm_from_intake_returns_invalid_state(self, api):
        """PRD §3.6: "An `IncidentCommander` confirms the breach, advancing
        `investigation_status` from `INVESTIGATING` to `CONFIRMED`". Attempting
        confirm while still `INTAKE` violates the local-state precondition
        (PRD §2.7 step 5) and returns `ERR_INVALID_STATE` (409).

        Design: Corner/state_machines/confirm_from_intake_returns_invalid_state
        """
        inc = create_incident()
        resp = api.confirm_incident(inc["id"], IC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_terminal_state_lockdown_closed_incident(self, api):
        """PRD §3.6: confirm advances `investigation_status` from
        `INVESTIGATING` to `CONFIRMED`. From any other state (including INTAKE
        on a fresh incident) the local-state precondition fails with
        `ERR_INVALID_STATE` (409).

        Design: Corner/state_machines/terminal_state_lockdown_closed_incident
        """
        inc = create_incident()
        resp = api.confirm_incident(inc["id"], IC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_approve_from_draft_returns_invalid_state(self, api):
        """PRD §3.7: "Approval — moving the notice from `LEGAL_REVIEW` to
        `APPROVED`". Calling approve while the notice is still `DRAFT`
        violates the local-state precondition and returns `ERR_INVALID_STATE`
        (409).

        Design: Corner/state_machines/approve_from_draft_returns_invalid_state
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        notice = create_draft_notice(inc, je)
        # Notice is in DRAFT, never submitted for review.
        resp = api.approve_notice(inc["id"], notice["id"], GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_seal_precondition_evidence_sealed_for_confirm(self, api):
        """PRD §3.6: "An `IncidentCommander` confirms the breach ... only when
        two preconditions hold: at least one `SEALED` `EvidenceItem` exists
        for the incident (otherwise `ERR_EVIDENCE_NOT_SEALED`, 409), and
        `total_affected_subjects` is strictly greater than zero."

        Design: Corner/state_machines/seal_precondition_evidence_sealed_for_confirm
        """
        # INVESTIGATING with verified subject but NO sealed evidence.
        ctx = create_incident_in_investigating_state(
            subject_count=1, add_sealed_evidence=False
        )
        inc = ctx["incident"]
        resp = api.confirm_incident(inc["id"], IC)
        validate_error(
            resp, ApiErrorId.ERR_EVIDENCE_NOT_SEALED.value, expected_status=409
        )


class TestSideEffectCascade:
    def test_subject_verify_recomputes_totals(self, api):
        """PRD §3.4: "Verification recomputes `total_affected_subjects` and
        `total_pending_subjects` on the incident and increments the incident's
        `version`."

        Design: Corner/state_machines/side_effect_cascade_subject_verify_recomputes_totals
        """
        inc = create_incident()
        v0 = inc["version"]
        subj_resp = api.create_affected_subject(
            inc["id"],
            create_affected_subject_payload(external_subject_ref="S1"),
            DA,
        )
        subj = validate_success(subj_resp, expected_status=201)
        v_resp = api.verify_affected_subject(inc["id"], subj["id"], DA)
        validate_success(v_resp)
        inc_after = get_success_data(api.get_incident(inc["id"], IC))
        assert inc_after["total_affected_subjects"] == 1
        assert inc_after["total_pending_subjects"] == 1
        assert inc_after["version"] > v0
