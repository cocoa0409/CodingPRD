"""API client: one method per endpoint published by the Governance Records API."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/governance"


class ApiClient(GenericApiClient):
    # ---- Board members ---------------------------------------------------
    def create_board_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/board-members", payload, headers)

    def get_board_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/board-members/{member_id}", headers=headers)

    def resign_board_member(self, member_id, headers):
        return self._request("POST", f"{PREFIX}/board-members/{member_id}/resign", {}, headers)

    # ---- Committees ------------------------------------------------------
    def create_committee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/committees", payload, headers)

    def get_committee(self, committee_id, headers):
        return self._request("GET", f"{PREFIX}/committees/{committee_id}", headers=headers)

    def create_committee_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/committee-assignments", payload, headers)

    def list_committee_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/committee-assignments", headers=headers, params=params)

    def get_committee_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/committee-assignments/{assignment_id}", headers=headers)

    def set_committee_assignment_status(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/committee-assignments/{assignment_id}/status", payload, headers
        )

    # ---- Conflict disclosures -------------------------------------------
    def create_conflict_disclosure(self, payload, headers):
        return self._request("POST", f"{PREFIX}/conflict-disclosures", payload, headers)

    def list_conflict_disclosures(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/conflict-disclosures", headers=headers, params=params)

    def get_conflict_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"{PREFIX}/conflict-disclosures/{disclosure_id}", headers=headers)

    def clear_conflict_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"{PREFIX}/conflict-disclosures/{disclosure_id}/clear", {}, headers)

    # ---- Policies and versions ------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", headers=headers)

    def create_policy_version(self, policy_id, payload, headers):
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/versions", payload, headers)

    def list_policy_versions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/policy-versions", headers=headers, params=params)

    def get_policy_version(self, version_id, headers):
        return self._request("GET", f"{PREFIX}/policy-versions/{version_id}", headers=headers)

    def withdraw_policy_version(self, version_id, payload, headers):
        return self._request("POST", f"{PREFIX}/policy-versions/{version_id}/withdraw", payload, headers)

    # ---- Legal update service -------------------------------------------
    def create_legal_mandate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/legal-mandates", payload, headers)

    def list_legal_mandates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/legal-mandates", headers=headers, params=params)

    def get_legal_mandate(self, mandate_id, headers):
        return self._request("GET", f"{PREFIX}/legal-mandates/{mandate_id}", headers=headers)

    # ---- Meetings --------------------------------------------------------
    def create_meeting(self, payload, headers):
        return self._request("POST", f"{PREFIX}/meetings", payload, headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"{PREFIX}/meetings/{meeting_id}", headers=headers)

    def post_meeting_notice(self, meeting_id, headers):
        return self._request("POST", f"{PREFIX}/meetings/{meeting_id}/notice", {}, headers)

    def open_meeting(self, meeting_id, payload, headers):
        return self._request("POST", f"{PREFIX}/meetings/{meeting_id}/open", payload, headers)

    def adjourn_meeting(self, meeting_id, headers):
        return self._request("POST", f"{PREFIX}/meetings/{meeting_id}/adjourn", {}, headers)

    def advance_minutes(self, meeting_id, payload, headers):
        return self._request("POST", f"{PREFIX}/meetings/{meeting_id}/minutes", payload, headers)

    # ---- Agenda items and public comment --------------------------------
    def create_agenda_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agenda-items", payload, headers)

    def list_agenda_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agenda-items", headers=headers, params=params)

    def get_agenda_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/agenda-items/{item_id}", headers=headers)

    def record_vote(self, item_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agenda-items/{item_id}/record-vote", payload, headers)

    def create_public_comment(self, item_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agenda-items/{item_id}/public-comments", payload, headers)

    def list_public_comments(self, item_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/agenda-items/{item_id}/public-comments", headers=headers, params=params
        )

    # ---- Waiver requests -------------------------------------------------
    def create_waiver_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/waiver-requests", payload, headers)

    def list_waiver_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/waiver-requests", headers=headers, params=params)

    def get_waiver_request(self, waiver_id, headers):
        return self._request("GET", f"{PREFIX}/waiver-requests/{waiver_id}", headers=headers)

    def record_committee_recommendation(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/waiver-requests/{waiver_id}/committee-recommendation", payload, headers
        )

    def revoke_waiver_request(self, waiver_id, headers):
        return self._request("POST", f"{PREFIX}/waiver-requests/{waiver_id}/revoke", {}, headers)

    # ---- Superintendent evaluation --------------------------------------
    def create_superintendent_evaluation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/superintendent-evaluations", payload, headers)

    def get_superintendent_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/superintendent-evaluations/{evaluation_id}", headers=headers
        )

    def advance_superintendent_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/superintendent-evaluations/{evaluation_id}/advance", payload, headers
        )

    def create_evaluation_rating(self, payload, headers):
        return self._request("POST", f"{PREFIX}/evaluation-ratings", payload, headers)

    def list_evaluation_ratings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/evaluation-ratings", headers=headers, params=params)

    def get_evaluation_rating(self, rating_id, headers):
        return self._request("GET", f"{PREFIX}/evaluation-ratings/{rating_id}", headers=headers)

    # ---- Manual publication ---------------------------------------------
    def create_manual_publication(self, payload, headers):
        return self._request("POST", f"{PREFIX}/manual-publications", payload, headers)

    def get_manual_publication(self, publication_id, headers):
        return self._request("GET", f"{PREFIX}/manual-publications/{publication_id}", headers=headers)

    def publish_manual_publication(self, publication_id, headers):
        return self._request(
            "POST", f"{PREFIX}/manual-publications/{publication_id}/publish", {}, headers
        )

    # ---- Compliance sweep ------------------------------------------------
    def run_compliance_sweep(self, headers):
        return self._request("POST", f"{PREFIX}/compliance-sweeps", {}, headers)

    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
