"""Actions issued from a state where they have no meaning.

Each refusal leaves its resource exactly as it was — same state, same stamped
identity, same version, same derived counters.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_score_2dp, assert_version
from test_helpers.test_users import COMPLIANCE, COMPLIANCE_COUNTERSIGNER, OFFICER


class TestCountersignatureReadsTheOtherEntity:
    @pytest.fixture()
    def signed_paper_on_a_screening_agency(self, client):
        """A signed contract whose agency has not finished due diligence."""
        agency = fx.register_agency(client, legal_name="Not Yet Cleared Agency")
        fx.screen_agency(client, agency["id"])
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")
        fx.append_schedule(client, contract["id"], contract["version"])
        fx.send_contract_for_signature(client, contract["id"])
        fx.agency_sign_contract(client, agency["id"], contract["id"])
        return {"agency_id": agency["id"], "contract_id": contract["id"]}

    def test_the_countersignature_waits_for_the_agencys_clearance(
        self, client, signed_paper_on_a_screening_agency
    ):
        """Paper may be prepared before clearance but not activated before it.

        "`COMPLIANCE_APPROVE` moves `PENDING_COMPLIANCE_REVIEW → ACTIVE` and is the
        countersignature. It requires an acting `X-User-ID` different from
        `created_by_user_id`, an agency whose due-diligence dimension has actually
        reached `CLEARED` — otherwise `ERR_AGENCY_NOT_CLEARED`"

        "The approving identity is stamped into `compliance_approved_by_user_id`."

        Design: Corner/validations/compliance_approve_requires_cleared_agency
        """
        env = signed_paper_on_a_screening_agency

        blocked = client.contract_lifecycle_action(
            env["contract_id"],
            F.lifecycle_payload(C.LIFECYCLE_COMPLIANCE_APPROVE),
            COMPLIANCE_COUNTERSIGNER,
        )
        validate_error(blocked, E.ERR_AGENCY_NOT_CLEARED, 422)
        assert (
            fx.read_contract(client, env["contract_id"])["status"]
            == C.CONTRACT_PENDING_COMPLIANCE_REVIEW
        )

        cleared = validate_success(
            client.agency_vetting_action(
                env["agency_id"], F.vetting_action_payload(C.VETTING_CLEAR), COMPLIANCE
            )
        )
        assert cleared["vetting_state"] == C.VETTING_CLEARED

        activated = validate_success(
            client.contract_lifecycle_action(
                env["contract_id"],
                F.lifecycle_payload(C.LIFECYCLE_COMPLIANCE_APPROVE),
                COMPLIANCE_COUNTERSIGNER,
            )
        )
        assert activated["status"] == C.CONTRACT_ACTIVE
        assert activated["compliance_approved_by_user_id"] == "compliance-2"


class TestPostureDeEscalationsNeedSomethingToUndo:
    def test_clearing_a_watch_and_reinstating_are_both_undefined_in_good_standing(
        self, client
    ):
        """Neither de-escalation has a source state on an unblemished agency.

        "`CLEAR_WATCH` moves `WATCH → GOOD_STANDING`, and only when
        `rolling_risk_score` is strictly below 40.00."

        "`REINSTATE` is the de-escalation and it lands on `WATCH`, never on
        `GOOD_STANDING`: from `PROBATION` or from `SUSPENDED` the agency returns to
        `WATCH`, and only when `rolling_risk_score` is strictly below 65.00."

        "An action not defined from the agency's current `compliance_posture`, or whose
        de-escalation risk-score precondition fails, is refused with
        `ERR_INVALID_POSTURE_ACTION`."

        Design: Corner/validations/posture_clear_watch_from_good_standing_rejected
        """
        agency = fx.register_agency(
            client, legal_name="Unblemished Agency", complete_diligence=False
        )
        assert agency["compliance_posture"] == C.POSTURE_GOOD_STANDING

        for action in (C.POSTURE_CLEAR_WATCH, C.POSTURE_REINSTATE):
            refused = client.agency_posture_action(
                agency["id"],
                F.posture_action_payload(action, "Nothing to undo"),
                COMPLIANCE,
            )
            validate_error(refused, E.ERR_INVALID_POSTURE_ACTION, 409)

        unchanged = fx.read_agency(client, agency["id"])
        assert unchanged["compliance_posture"] == C.POSTURE_GOOD_STANDING
        assert unchanged["last_posture_reason"] is None
        assert_version(unchanged, 1)


class TestAdmissionDecisionsNeedASubmission:
    def test_a_draft_file_cannot_be_admitted(self, client):
        """No decision is recorded and no submission date appears.

        "A `RecruitmentOfficer` decides a submitted application by supplying a `decision`
        and an optional `note`."

        "A decision requested from any status other than `SUBMITTED` is
        `ERR_INVALID_APPLICATION_STATE`."

        "It stamps `submitted_on` with the current logical-clock date."

        Design: Corner/validations/decision_on_draft_application_rejected
        """
        agency = fx.register_agency(
            client, legal_name="Premature Decision Agency", complete_diligence=False
        )
        program = fx.create_program(client)
        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )

        refused = client.application_decision(
            application["id"], F.decision_payload(C.DECISION_ADMIT), OFFICER
        )
        validate_error(refused, E.ERR_INVALID_APPLICATION_STATE, 409)

        unchanged = fx.read_application(client, application["id"])
        assert unchanged["status"] == C.APPLICATION_DRAFT
        assert unchanged["submitted_on"] is None
        assert_version(unchanged, 1)


class TestSecondStageOutcomesNeedAFlag:
    def test_neither_second_stage_outcome_is_reachable_from_pending(self, client):
        """Both forks past FLAGGED are refused while the document is untouched.

        "The dimension is a fork-join: `PENDING` forks to either `VERIFIED` or
        `FLAGGED` with different side effects, and `FLAGGED` forks again to either
        `CLEARED` or `CONFIRMED_FRAUD`."

        "An outcome that is not defined from the document's current
        `verification_state` — for instance `CLEARED` on a `PENDING` document, or
        `VERIFIED` on a `FLAGGED` one — is refused with `ERR_INVALID_DOCUMENT_STATE`."

        Design: Corner/validations/clear_outcome_on_pending_document_rejected
        """
        agency = fx.register_agency(
            client, legal_name="Pending Document Agency", complete_diligence=False
        )
        program = fx.create_program(client)
        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )
        document = fx.upload_document(
            client,
            agency["id"],
            application["id"],
            C.DOC_PASSPORT,
            "hash-p-001",
            "MEA India",
        )
        assert document["verification_state"] == C.VERIFICATION_PENDING

        for outcome in (C.VERIFICATION_CLEARED, C.VERIFICATION_CONFIRMED_FRAUD):
            refused = client.document_verification(
                document["id"], F.verification_payload(outcome), COMPLIANCE
            )
            validate_error(refused, E.ERR_INVALID_DOCUMENT_STATE, 409)

        untouched = fx.read_document(client, document["id"])
        assert untouched["verification_state"] == C.VERIFICATION_PENDING
        assert untouched["verified_by_user_id"] is None
        assert_version(untouched, 1)

        assert fx.read_application(client, application["id"])["integrity_hold"] is False
        assert fx.read_agency(client, agency["id"])["reviewed_document_count"] == 0


class TestAdjudicationHappensOnce:
    def test_a_confirmed_incident_refuses_both_kinds_of_second_verdict(self, client):
        """The risk contribution cannot be counted twice.

        "`CONFIRMED` and `DISMISSED` are both terminal, and an incident already in either
        is refused with `ERR_INVALID_INCIDENT_STATE`."

        "Severity carries a weight: `LOW` weighs 5, `MEDIUM` weighs 15, `HIGH` weighs
        30, and `CRITICAL` weighs 50."

        Design: Corner/validations/second_resolution_on_confirmed_incident_rejected
        """
        agency = fx.register_agency(
            client, legal_name="Single Verdict Agency", complete_diligence=False
        )
        incident = fx.file_incident(
            client,
            agency["id"],
            severity=C.SEVERITY_MEDIUM,
            occurred_on=C.DEFAULT_CLOCK_DATE,
        )
        fx.resolve_incident(client, incident["id"], C.RESOLUTION_CONFIRM)

        repeat_confirm = client.incident_resolution(
            incident["id"], F.resolution_payload(C.RESOLUTION_CONFIRM), COMPLIANCE
        )
        validate_error(repeat_confirm, E.ERR_INVALID_INCIDENT_STATE, 409)

        late_dismissal = client.incident_resolution(
            incident["id"],
            F.resolution_payload(C.RESOLUTION_DISMISS, note="Reconsidered"),
            COMPLIANCE,
        )
        validate_error(late_dismissal, E.ERR_INVALID_INCIDENT_STATE, 409)

        incidents = fx.read_incidents(client, agency_id=agency["id"])
        assert len(incidents) == 1
        assert incidents[0]["status"] == C.INCIDENT_CONFIRMED

        scored = fx.read_agency(client, agency["id"])
        assert scored["confirmed_incident_count"] == 1
        assert_score_2dp(
            scored["rolling_risk_score"], 15.00, "one confirmation, one weight"
        )
