"""Typed HTTP client — one method per endpoint declared in PRD §4."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per PRD §4 endpoint row, in PRD §4 table order."""

    # ------------------------------------------------------------------
    # Program
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def advance_program_phase(self, program_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/advance-phase", payload, headers=headers
        )

    def run_match(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/programs/{program_id}/run-match", payload or {}, headers=headers
        )

    def get_pipeline_report(self, program_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/pipeline-report", headers=headers
        )

    # ------------------------------------------------------------------
    # Applicant
    # ------------------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def create_application_review(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/reviews", payload, headers=headers
        )

    def list_application_reviews(self, headers, params=None):
        return self._request(
            "GET", "/application-reviews", headers=headers, params=params
        )

    def get_application_review(self, review_id, headers):
        return self._request(
            "GET", f"/application-reviews/{review_id}", headers=headers
        )

    def screen_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/screen", payload, headers=headers
        )

    def withdraw_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/withdraw",
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # FacultyMember
    # ------------------------------------------------------------------
    def create_faculty_member(self, payload, headers):
        return self._request("POST", "/faculty-members", payload, headers=headers)

    def list_faculty_members(self, headers, params=None):
        return self._request("GET", "/faculty-members", headers=headers, params=params)

    def get_faculty_member(self, faculty_member_id, headers):
        return self._request(
            "GET", f"/faculty-members/{faculty_member_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # InterviewWave
    # ------------------------------------------------------------------
    def create_interview_wave(self, payload, headers):
        return self._request("POST", "/interview-waves", payload, headers=headers)

    def list_interview_waves(self, headers, params=None):
        return self._request("GET", "/interview-waves", headers=headers, params=params)

    def get_interview_wave(self, wave_id, headers):
        return self._request("GET", f"/interview-waves/{wave_id}", headers=headers)

    def release_interview_wave(self, wave_id, headers, payload=None):
        return self._request(
            "POST", f"/interview-waves/{wave_id}/release", payload or {}, headers=headers
        )

    def close_interview_wave(self, wave_id, headers, payload=None):
        return self._request(
            "POST", f"/interview-waves/{wave_id}/close", payload or {}, headers=headers
        )

    def create_interview_invitation(self, wave_id, payload, headers):
        return self._request(
            "POST", f"/interview-waves/{wave_id}/invitations", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # InterviewSlot
    # ------------------------------------------------------------------
    def create_interview_slot(self, payload, headers):
        return self._request("POST", "/interview-slots", payload, headers=headers)

    def list_interview_slots(self, headers, params=None):
        return self._request("GET", "/interview-slots", headers=headers, params=params)

    def get_interview_slot(self, slot_id, headers):
        return self._request("GET", f"/interview-slots/{slot_id}", headers=headers)

    def complete_interview_slot(self, slot_id, headers, payload=None):
        return self._request(
            "POST",
            f"/interview-slots/{slot_id}/complete",
            payload or {},
            headers=headers,
        )

    def cancel_interview_slot(self, slot_id, headers, payload=None):
        return self._request(
            "POST", f"/interview-slots/{slot_id}/cancel", payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # InterviewInvitation
    # ------------------------------------------------------------------
    def list_interview_invitations(self, headers, params=None):
        return self._request(
            "GET", "/interview-invitations", headers=headers, params=params
        )

    def get_interview_invitation(self, invitation_id, headers):
        return self._request(
            "GET", f"/interview-invitations/{invitation_id}", headers=headers
        )

    def accept_interview_invitation(self, invitation_id, payload, headers):
        return self._request(
            "POST",
            f"/interview-invitations/{invitation_id}/accept",
            payload,
            headers=headers,
        )

    def decline_interview_invitation(self, invitation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/interview-invitations/{invitation_id}/decline",
            payload or {},
            headers=headers,
        )

    def reschedule_interview_invitation(self, invitation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/interview-invitations/{invitation_id}/reschedule",
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # InterviewAssignment
    # ------------------------------------------------------------------
    def create_interview_assignment(self, payload, headers):
        return self._request("POST", "/interview-assignments", payload, headers=headers)

    def list_interview_assignments(self, headers, params=None):
        return self._request(
            "GET", "/interview-assignments", headers=headers, params=params
        )

    def get_interview_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/interview-assignments/{assignment_id}", headers=headers
        )

    def release_interview_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/interview-assignments/{assignment_id}/release",
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # ScoreCard
    # ------------------------------------------------------------------
    def create_score_card(self, payload, headers):
        return self._request("POST", "/score-cards", payload, headers=headers)

    def list_score_cards(self, headers, params=None):
        return self._request("GET", "/score-cards", headers=headers, params=params)

    def get_score_card(self, score_card_id, headers):
        return self._request("GET", f"/score-cards/{score_card_id}", headers=headers)

    def submit_score_card(self, score_card_id, headers, payload=None):
        return self._request(
            "POST", f"/score-cards/{score_card_id}/submit", payload or {}, headers=headers
        )

    def request_score_card_amendment(self, score_card_id, headers, payload=None):
        return self._request(
            "POST",
            f"/score-cards/{score_card_id}/request-amendment",
            payload or {},
            headers=headers,
        )

    def revise_score_card(self, score_card_id, payload, headers):
        return self._request(
            "POST", f"/score-cards/{score_card_id}/revise", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # RankList
    # ------------------------------------------------------------------
    def create_rank_list(self, payload, headers):
        return self._request("POST", "/rank-lists", payload, headers=headers)

    def list_rank_lists(self, headers, params=None):
        return self._request("GET", "/rank-lists", headers=headers, params=params)

    def get_rank_list(self, rank_list_id, headers):
        return self._request("GET", f"/rank-lists/{rank_list_id}", headers=headers)

    def create_rank_list_entry(self, rank_list_id, payload, headers):
        return self._request(
            "POST", f"/rank-lists/{rank_list_id}/entries", payload, headers=headers
        )

    def list_entries_of_rank_list(self, rank_list_id, headers, params=None):
        return self._request(
            "GET", f"/rank-lists/{rank_list_id}/entries", headers=headers, params=params
        )

    def list_rank_list_entries(self, headers, params=None):
        return self._request("GET", "/rank-list-entries", headers=headers, params=params)

    def get_rank_list_entry(self, entry_id, headers):
        return self._request("GET", f"/rank-list-entries/{entry_id}", headers=headers)

    def submit_rank_list_to_committee(self, rank_list_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rank-lists/{rank_list_id}/submit-to-committee",
            payload or {},
            headers=headers,
        )

    def create_committee_vote(self, rank_list_id, payload, headers):
        return self._request(
            "POST", f"/rank-lists/{rank_list_id}/votes", payload, headers=headers
        )

    def list_votes_of_rank_list(self, rank_list_id, headers, params=None):
        return self._request(
            "GET", f"/rank-lists/{rank_list_id}/votes", headers=headers, params=params
        )

    def list_committee_votes(self, headers, params=None):
        return self._request("GET", "/committee-votes", headers=headers, params=params)

    def get_committee_vote(self, vote_id, headers):
        return self._request("GET", f"/committee-votes/{vote_id}", headers=headers)

    def revise_rank_list(self, rank_list_id, headers, payload=None):
        return self._request(
            "POST", f"/rank-lists/{rank_list_id}/revise", payload or {}, headers=headers
        )

    def certify_rank_list(self, rank_list_id, payload, headers):
        return self._request(
            "POST", f"/rank-lists/{rank_list_id}/certify", payload, headers=headers
        )

    def withdraw_rank_list(self, rank_list_id, headers, payload=None):
        return self._request(
            "POST", f"/rank-lists/{rank_list_id}/withdraw", payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # MatchResult
    # ------------------------------------------------------------------
    def list_match_results(self, headers, params=None):
        return self._request("GET", "/match-results", headers=headers, params=params)

    def get_match_result(self, match_result_id, headers):
        return self._request("GET", f"/match-results/{match_result_id}", headers=headers)

    # ------------------------------------------------------------------
    # SoapOffer
    # ------------------------------------------------------------------
    def create_soap_offer(self, payload, headers):
        return self._request("POST", "/soap-offers", payload, headers=headers)

    def list_soap_offers(self, headers, params=None):
        return self._request("GET", "/soap-offers", headers=headers, params=params)

    def get_soap_offer(self, soap_offer_id, headers):
        return self._request("GET", f"/soap-offers/{soap_offer_id}", headers=headers)

    def accept_soap_offer(self, soap_offer_id, headers, payload=None):
        return self._request(
            "POST", f"/soap-offers/{soap_offer_id}/accept", payload or {}, headers=headers
        )

    def decline_soap_offer(self, soap_offer_id, headers, payload=None):
        return self._request(
            "POST",
            f"/soap-offers/{soap_offer_id}/decline",
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def sign_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/sign", payload or {}, headers=headers
        )

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate", payload or {}, headers=headers
        )

    def void_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/void", payload, headers=headers
        )

    def rescind_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/rescind", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # CredentialItem
    # ------------------------------------------------------------------
    def list_credential_items_of_contract(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/contracts/{contract_id}/credential-items",
            headers=headers,
            params=params,
        )

    def get_credential_item(self, credential_item_id, headers):
        return self._request(
            "GET", f"/credential-items/{credential_item_id}", headers=headers
        )

    def submit_credential_item(self, credential_item_id, payload, headers):
        return self._request(
            "POST",
            f"/credential-items/{credential_item_id}/submit",
            payload,
            headers=headers,
        )

    def verify_credential_item(self, credential_item_id, headers, payload=None):
        return self._request(
            "POST",
            f"/credential-items/{credential_item_id}/verify",
            payload or {},
            headers=headers,
        )

    def reject_credential_item(self, credential_item_id, payload, headers):
        return self._request(
            "POST",
            f"/credential-items/{credential_item_id}/reject",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # CommunicationLog
    # ------------------------------------------------------------------
    def create_communication_log(self, payload, headers):
        return self._request("POST", "/communication-logs", payload, headers=headers)

    def list_communication_logs(self, headers, params=None):
        return self._request(
            "GET", "/communication-logs", headers=headers, params=params
        )

    def get_communication_log(self, log_id, headers):
        return self._request("GET", f"/communication-logs/{log_id}", headers=headers)

    def resolve_communication_log(self, log_id, payload, headers):
        return self._request(
            "POST", f"/communication-logs/{log_id}/resolve", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Logical season clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", payload, headers=headers
        )


api_client = ApiClient()
