"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/boardgov/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- nonprofits ---
    def create_nonprofit(self, payload, headers):
        return self._request("POST", "/boardgov/nonprofits", payload, headers)

    def get_nonprofit(self, nonprofit_id, headers):
        return self._request("GET", f"/boardgov/nonprofits/{nonprofit_id}", headers=headers)

    def patch_nonprofit(self, nonprofit_id, payload, headers):
        return self._request("PATCH", f"/boardgov/nonprofits/{nonprofit_id}", payload, headers)

    def compliance_sweep(self, nonprofit_id, headers):
        return self._request("POST", f"/boardgov/nonprofits/{nonprofit_id}/compliance_sweep", {}, headers)

    def get_recruitment_matrix(self, nonprofit_id, headers):
        return self._request("GET", f"/boardgov/nonprofits/{nonprofit_id}/recruitment-matrix", headers=headers)

    # --- bylaws ---
    def create_bylaws(self, payload, headers):
        return self._request("POST", "/boardgov/bylaws", payload, headers)

    def get_bylaws(self, bylaws_id, headers):
        return self._request("GET", f"/boardgov/bylaws/{bylaws_id}", headers=headers)

    def list_bylaws(self, headers, params=None):
        return self._request("GET", "/boardgov/bylaws", headers=headers, params=params)

    def adopt_bylaws(self, bylaws_id, headers):
        return self._request("POST", f"/boardgov/bylaws/{bylaws_id}/adopt", {}, headers)

    def discard_bylaws(self, bylaws_id, headers):
        return self._request("POST", f"/boardgov/bylaws/{bylaws_id}/discard", {}, headers)

    # --- bylaws amendments ---
    def create_amendment(self, payload, headers):
        return self._request("POST", "/boardgov/bylaws-amendments", payload, headers)

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/boardgov/bylaws-amendments/{amendment_id}", headers=headers)

    def list_amendments(self, headers, params=None):
        return self._request("GET", "/boardgov/bylaws-amendments", headers=headers, params=params)

    def propose_amendment(self, amendment_id, headers):
        return self._request("POST", f"/boardgov/bylaws-amendments/{amendment_id}/propose", {}, headers)

    def revise_amendment(self, amendment_id, headers):
        return self._request("POST", f"/boardgov/bylaws-amendments/{amendment_id}/revise", {}, headers)

    def withdraw_amendment(self, amendment_id, headers):
        return self._request("POST", f"/boardgov/bylaws-amendments/{amendment_id}/withdraw", {}, headers)

    # --- board members ---
    def create_board_member(self, payload, headers):
        return self._request("POST", "/boardgov/board-members", payload, headers)

    def get_board_member(self, member_id, headers):
        return self._request("GET", f"/boardgov/board-members/{member_id}", headers=headers)

    def list_board_members(self, headers, params=None):
        return self._request("GET", "/boardgov/board-members", headers=headers, params=params)

    def patch_board_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/boardgov/board-members/{member_id}", payload, headers)

    def resign_member(self, member_id, headers):
        return self._request("POST", f"/boardgov/board-members/{member_id}/resign", {}, headers)

    def remove_member(self, member_id, payload, headers):
        return self._request("POST", f"/boardgov/board-members/{member_id}/remove", payload, headers)

    # --- board terms ---
    def create_board_term(self, payload, headers):
        return self._request("POST", "/boardgov/board-terms", payload, headers)

    def get_board_term(self, term_id, headers):
        return self._request("GET", f"/boardgov/board-terms/{term_id}", headers=headers)

    def list_board_terms(self, headers, params=None):
        return self._request("GET", "/boardgov/board-terms", headers=headers, params=params)

    # --- committees ---
    def create_committee(self, payload, headers):
        return self._request("POST", "/boardgov/committees", payload, headers)

    def get_committee(self, committee_id, headers):
        return self._request("GET", f"/boardgov/committees/{committee_id}", headers=headers)

    def list_committees(self, headers, params=None):
        return self._request("GET", "/boardgov/committees", headers=headers, params=params)

    def activate_committee(self, committee_id, headers):
        return self._request("POST", f"/boardgov/committees/{committee_id}/activate", {}, headers)

    def dissolve_committee(self, committee_id, headers):
        return self._request("POST", f"/boardgov/committees/{committee_id}/dissolve", {}, headers)

    # --- committee appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/boardgov/committee-appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/boardgov/committee-appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/boardgov/committee-appointments", headers=headers, params=params)

    def end_appointment(self, appointment_id, headers):
        return self._request("POST", f"/boardgov/committee-appointments/{appointment_id}/end", {}, headers)

    # --- meetings ---
    def create_meeting(self, payload, headers):
        return self._request("POST", "/boardgov/meetings", payload, headers)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/boardgov/meetings/{meeting_id}", headers=headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/boardgov/meetings", headers=headers, params=params)

    def call_to_order(self, meeting_id, payload, headers):
        return self._request("POST", f"/boardgov/meetings/{meeting_id}/call_to_order", payload, headers)

    def adjourn_meeting(self, meeting_id, headers):
        return self._request("POST", f"/boardgov/meetings/{meeting_id}/adjourn", {}, headers)

    def cancel_meeting(self, meeting_id, headers):
        return self._request("POST", f"/boardgov/meetings/{meeting_id}/cancel", {}, headers)

    def record_minutes(self, meeting_id, payload, headers):
        return self._request("POST", f"/boardgov/meetings/{meeting_id}/minutes", payload, headers)

    def approve_minutes(self, meeting_id, payload, headers):
        return self._request("POST", f"/boardgov/meetings/{meeting_id}/approve_minutes", payload, headers)

    def reject_minutes(self, meeting_id, payload, headers):
        return self._request("POST", f"/boardgov/meetings/{meeting_id}/reject_minutes", payload, headers)

    # --- motions ---
    def create_motion(self, payload, headers):
        return self._request("POST", "/boardgov/motions", payload, headers)

    def get_motion(self, motion_id, headers):
        return self._request("GET", f"/boardgov/motions/{motion_id}", headers=headers)

    def list_motions(self, headers, params=None):
        return self._request("GET", "/boardgov/motions", headers=headers, params=params)

    def open_voting(self, motion_id, headers):
        return self._request("POST", f"/boardgov/motions/{motion_id}/open_voting", {}, headers)

    def close_voting(self, motion_id, headers):
        return self._request("POST", f"/boardgov/motions/{motion_id}/close_voting", {}, headers)

    def table_motion(self, motion_id, headers):
        return self._request("POST", f"/boardgov/motions/{motion_id}/table", {}, headers)

    def resume_motion(self, motion_id, headers):
        return self._request("POST", f"/boardgov/motions/{motion_id}/resume", {}, headers)

    def withdraw_motion(self, motion_id, headers):
        return self._request("POST", f"/boardgov/motions/{motion_id}/withdraw", {}, headers)

    # --- votes ---
    def cast_vote(self, payload, headers):
        return self._request("POST", "/boardgov/votes", payload, headers)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"/boardgov/votes/{vote_id}", headers=headers)

    def list_votes(self, headers, params=None):
        return self._request("GET", "/boardgov/votes", headers=headers, params=params)

    # --- COI disclosures ---
    def file_disclosure(self, payload, headers):
        return self._request("POST", "/boardgov/coi-disclosures", payload, headers)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/boardgov/coi-disclosures/{disclosure_id}", headers=headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/boardgov/coi-disclosures", headers=headers, params=params)

    def start_review(self, disclosure_id, headers):
        return self._request("POST", f"/boardgov/coi-disclosures/{disclosure_id}/start_review", {}, headers)

    def clear_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/boardgov/coi-disclosures/{disclosure_id}/clear", {}, headers)

    def impose_restrictions(self, disclosure_id, payload, headers):
        return self._request("POST", f"/boardgov/coi-disclosures/{disclosure_id}/impose_restrictions", payload, headers)

    def lift_restrictions(self, disclosure_id, headers):
        return self._request("POST", f"/boardgov/coi-disclosures/{disclosure_id}/lift_restrictions", {}, headers)

    # --- executive evaluations ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/boardgov/executive-evaluations", payload, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/boardgov/executive-evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/boardgov/executive-evaluations", headers=headers, params=params)

    def patch_scores(self, evaluation_id, payload, headers):
        return self._request("PATCH", f"/boardgov/executive-evaluations/{evaluation_id}/scores", payload, headers)

    def submit_evaluation_review(self, evaluation_id, headers):
        return self._request("POST", f"/boardgov/executive-evaluations/{evaluation_id}/submit_review", {}, headers)

    def return_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/boardgov/executive-evaluations/{evaluation_id}/return", {}, headers)

    def ratify_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/boardgov/executive-evaluations/{evaluation_id}/ratify", {}, headers)

    def deliver_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/boardgov/executive-evaluations/{evaluation_id}/deliver", {}, headers)

    # --- succession plans ---
    def create_succession_plan(self, payload, headers):
        return self._request("POST", "/boardgov/succession-plans", payload, headers)

    def get_succession_plan(self, plan_id, headers):
        return self._request("GET", f"/boardgov/succession-plans/{plan_id}", headers=headers)

    def list_succession_plans(self, headers, params=None):
        return self._request("GET", "/boardgov/succession-plans", headers=headers, params=params)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/boardgov/succession-plans/{plan_id}/approve", {}, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/boardgov/succession-plans/{plan_id}/revise", {}, headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/boardgov/succession-plans/{plan_id}/activate", {}, headers)

    def stand_down_plan(self, plan_id, headers):
        return self._request("POST", f"/boardgov/succession-plans/{plan_id}/stand_down", {}, headers)

    def discard_plan(self, plan_id, headers):
        return self._request("POST", f"/boardgov/succession-plans/{plan_id}/discard", {}, headers)

    # --- Form 990 filings ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/boardgov/form990-filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/boardgov/form990-filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/boardgov/form990-filings", headers=headers, params=params)

    def submit_filing_for_review(self, filing_id, headers):
        return self._request("POST", f"/boardgov/form990-filings/{filing_id}/submit_for_review", {}, headers)

    def record_review(self, filing_id, headers):
        return self._request("POST", f"/boardgov/form990-filings/{filing_id}/record_review", {}, headers)

    def approve_filing(self, filing_id, headers):
        return self._request("POST", f"/boardgov/form990-filings/{filing_id}/approve", {}, headers)

    def mark_filed(self, filing_id, headers):
        return self._request("POST", f"/boardgov/form990-filings/{filing_id}/mark_filed", {}, headers)

    def post_public_disclosure(self, filing_id, headers):
        return self._request("POST", f"/boardgov/form990-filings/{filing_id}/post_public_disclosure", {}, headers)

    def discard_filing(self, filing_id, headers):
        return self._request("POST", f"/boardgov/form990-filings/{filing_id}/discard", {}, headers)

    # --- state registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/boardgov/state-registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/boardgov/state-registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/boardgov/state-registrations", headers=headers, params=params)

    def submit_renewal(self, registration_id, payload, headers):
        return self._request("POST", f"/boardgov/state-registrations/{registration_id}/submit_renewal", payload, headers)

    def confirm_renewal(self, registration_id, headers):
        return self._request("POST", f"/boardgov/state-registrations/{registration_id}/confirm_renewal", {}, headers)

    def reinstate_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/boardgov/state-registrations/{registration_id}/reinstate", payload, headers)

    # --- insurance policies ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/boardgov/insurance-policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/boardgov/insurance-policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/boardgov/insurance-policies", headers=headers, params=params)

    def bind_policy(self, policy_id, headers):
        return self._request("POST", f"/boardgov/insurance-policies/{policy_id}/bind", {}, headers)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/boardgov/insurance-policies/{policy_id}/activate", {}, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/boardgov/insurance-policies/{policy_id}/cancel", {}, headers)


api_client = ApiClient()
