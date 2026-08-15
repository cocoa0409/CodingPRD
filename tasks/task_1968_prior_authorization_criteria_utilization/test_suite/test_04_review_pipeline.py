"""Two-tier review ladder: escalation cycle, segregation, withdraw (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    basic_um_environment,
    escalated_request,
    get_determination,
    list_conferences,
    list_request_determinations,
    make_medical_director_headers,
    md_decide,
    pended_request,
    reviewer_decide,
    scheduled_conference,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["um_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
REVIEWER = TEST_USERS["clinical_reviewer_headers"]


class TestEscalationSendBackCycle:
    def test_escalate_then_send_back_clears_escalation_marker(self, api):
        """PRD §3.3: "Escalation instead moves the request to `ESCALATED_MD`, recording `escalated_by_user_id` from `X-User-ID`, and creates no determination."
        PRD §3.3: "`SEND_BACK` takes no `reason_code` and returns the request to `PENDED_REVIEW` with `escalated_by_user_id` cleared to null — the send-back cycle that lets the reviewer tier take another pass."

        Design: Difficulty/non_linear_state_machine/request_escalation_send_back_cycle
        """
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        escalated = reviewer_decide(req["id"], "ESCALATE", user_id="u-rev-1")
        assert escalated["status"] == "ESCALATED_MD"
        assert escalated["escalated_by_user_id"] == "u-rev-1"
        sent_back = md_decide(req["id"], "SEND_BACK", user_id="u-md-1")
        assert sent_back["status"] == "PENDED_REVIEW"
        assert sent_back["escalated_by_user_id"] is None, (
            "send-back clears the escalation marker"
        )

    def test_reviewer_approval_after_send_back_cycle(self, api):
        """PRD §3.3: "Approval moves the request `PENDED_REVIEW → APPROVED` and creates a `FINAL` determination with `decided_by_role` `CLINICAL_REVIEWER`, `decided_by_user_id` taken from `X-User-ID`, `outcome` `APPROVED`, and `issued_at` from the clock; `determined_at` is set, and if `issued_at` is strictly later than `due_at` the request's `is_tat_breached` flips true and a `TAT_BREACHED` event is emitted."

        Design: Difficulty/non_linear_state_machine/request_escalation_send_back_cycle
        """
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        reviewer_decide(req["id"], "ESCALATE", user_id="u-rev-1")
        md_decide(req["id"], "SEND_BACK", user_id="u-md-1")
        approved = reviewer_decide(
            req["id"], "APPROVE", reason_code="MEDICAL_NECESSITY_MET",
            user_id="u-rev-1",
        )
        assert approved["status"] == "APPROVED", (
            "the cycle returns to a state from which approval is again reachable"
        )
        det = get_determination(list_request_determinations(req["id"])[0]["id"])
        assert det["decided_by_role"] == "CLINICAL_REVIEWER"
        assert det["outcome"] == "APPROVED"
        assert det["decided_by_user_id"] == "u-rev-1"


class TestMedicalDirectorGate:
    def test_md_decision_on_pended_request_rejected(self, api):
        """PRD §3.3: "Every medical-director decision first requires the request to be `ESCALATED_MD` (`ERR_REQUEST_NOT_ESCALATED`) and the caller to differ from `escalated_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/validations/md_decision_on_pended_request_rejected
        """
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        resp = api.md_decision(
            req["id"],
            {"decision": "APPROVE", "reason_code": "MEDICAL_NECESSITY_MET"},
            make_medical_director_headers("u-md-1"),
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_ESCALATED)

    def test_md_decision_by_escalating_reviewer_rejected(self, api):
        """PRD §2.8: "A `MedicalDirector` may not decide an escalated case that they themselves escalated while acting as the reviewer: on any medical-director decision the caller's `X-User-ID` must differ from the request's `escalated_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/md_decision_by_escalating_reviewer_rejected
        """
        provider, cs, _gv = basic_um_environment()
        req = escalated_request(
            provider["id"], cs["id"], reviewer_user_id="u-rev-1",
        )
        # Same human, now wearing the medical-director hat: X-User-ID matches
        # the recorded escalated_by_user_id.
        resp = api.md_decision(
            req["id"],
            {"decision": "APPROVE", "reason_code": "MEDICAL_NECESSITY_MET"},
            make_medical_director_headers("u-rev-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_prior_auth_request(api, req["id"])["status"] == "ESCALATED_MD"


class TestWithdraw:
    def test_withdraw_determined_request_rejected(self, api):
        """PRD §3.2: "While a request is in `PENDED_REVIEW` or `ESCALATED_MD`, the `IntakeSpecialist` may withdraw it — moving it to the terminal `WITHDRAWN` state and, as a conditional cascade, moving any peer-to-peer conference still `SCHEDULED` for the request to `CANCELLED`. Withdrawal from any other status is rejected with `ERR_REQUEST_NOT_WITHDRAWABLE`."

        Design: Corner/state_machines/withdraw_determined_request_rejected
        """
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        reviewer_decide(req["id"], "APPROVE", reason_code="MEDICAL_NECESSITY_MET")
        resp = api.withdraw_prior_auth_request(req["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_WITHDRAWABLE)
        assert get_prior_auth_request(api, req["id"])["status"] == "APPROVED"

    def test_withdraw_cascades_cancel_scheduled_p2p(self, api):
        """PRD §3.2: "While a request is in `PENDED_REVIEW` or `ESCALATED_MD`, the `IntakeSpecialist` may withdraw it — moving it to the terminal `WITHDRAWN` state and, as a conditional cascade, moving any peer-to-peer conference still `SCHEDULED` for the request to `CANCELLED`."
        PRD §3.3: "Conferences also cancel automatically when their parent request is withdrawn, and a request's conferences can be listed under the request."

        Design: Corner/state_machines/withdraw_cascades_cancel_scheduled_p2p
        """
        provider, cs, _gv = basic_um_environment()
        req = escalated_request(provider["id"], cs["id"])
        conference = scheduled_conference(req["id"], md_user_id="u-md-1")
        withdrawn = validate_success(
            api.withdraw_prior_auth_request(req["id"], INTAKE)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        conferences = list_conferences(req["id"])
        assert len(conferences) == 1
        assert conferences[0]["id"] == conference["id"]
        assert conferences[0]["status"] == "CANCELLED", (
            "the cascade fired because the conference was still SCHEDULED"
        )


class TestImmediateConsistency:
    def test_decision_response_and_followup_read_agree(self, api):
        """PRD §2.4: "Cascades settle immediately, inside the triggering request; there is no eventual consistency window."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.3: "Approval moves the request `PENDED_REVIEW → APPROVED` and creates a `FINAL` determination with `decided_by_role` `CLINICAL_REVIEWER`, `decided_by_user_id` taken from `X-User-ID`, `outcome` `APPROVED`, and `issued_at` from the clock; `determined_at` is set, and if `issued_at` is strictly later than `due_at` the request's `is_tat_breached` flips true and a `TAT_BREACHED` event is emitted."

        Design: Corner/cross_cutting_layers/immediate_consistency_on_decision_response
        """
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        decided = validate_success(
            api.reviewer_decision(
                req["id"],
                {"decision": "APPROVE", "reason_code": "MEDICAL_NECESSITY_MET"},
                REVIEWER,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["determined_at"] == "2026-08-01T00:00:00.000Z", (
            "determined_at mirrors the determination's issued_at, stamped from "
            "the startup logical clock"
        )
        det = list_request_determinations(req["id"])[0]
        assert det["outcome"] == "APPROVED"
        assert det["status"] == "FINAL"


def get_prior_auth_request(api, request_id):
    return validate_success(api.get_prior_auth_request(request_id, ADMIN))
