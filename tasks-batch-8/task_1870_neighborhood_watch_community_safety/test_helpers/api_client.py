"""API client: one method per endpoint defined in the PRD (mounted under /watch)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/watch/_clock/set_current_utc", payload, headers)

    # ---- WatchGroup ----
    def create_watch_group(self, payload, headers):
        return self._request("POST", "/watch/watch-groups", payload, headers)

    def list_watch_groups(self, headers, params=None):
        return self._request("GET", "/watch/watch-groups", headers=headers, params=params)

    def get_watch_group(self, group_id, headers):
        return self._request("GET", f"/watch/watch-groups/{group_id}", headers=headers)

    def suspend_certification(self, group_id, headers):
        return self._request(
            "POST", f"/watch/watch-groups/{group_id}/certification-suspend",
            {}, headers,
        )

    def reinstate_certification(self, group_id, headers):
        return self._request(
            "POST", f"/watch/watch-groups/{group_id}/certification-reinstate",
            {}, headers,
        )

    def freeze_watch_group(self, group_id, headers):
        return self._request(
            "POST", f"/watch/watch-groups/{group_id}/freeze", {}, headers,
        )

    def unfreeze_watch_group(self, group_id, headers):
        return self._request(
            "POST", f"/watch/watch-groups/{group_id}/unfreeze", {}, headers,
        )

    def issue_materials(self, group_id, payload, headers):
        return self._request(
            "POST", f"/watch/watch-groups/{group_id}/materials/issue",
            payload, headers,
        )

    def recall_materials(self, group_id, payload, headers):
        return self._request(
            "POST", f"/watch/watch-groups/{group_id}/materials/recall",
            payload, headers,
        )

    # ---- Block ----
    def create_block(self, group_id, payload, headers):
        return self._request(
            "POST", f"/watch/watch-groups/{group_id}/blocks", payload, headers,
        )

    def list_blocks(self, group_id, headers, params=None):
        return self._request(
            "GET", f"/watch/watch-groups/{group_id}/blocks",
            headers=headers, params=params,
        )

    def get_block(self, block_id, headers):
        return self._request("GET", f"/watch/blocks/{block_id}", headers=headers)

    def register_block(self, block_id, headers):
        return self._request(
            "POST", f"/watch/blocks/{block_id}/register", {}, headers,
        )

    def deregister_block(self, block_id, headers):
        return self._request(
            "POST", f"/watch/blocks/{block_id}/deregister", {}, headers,
        )

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/watch/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/watch/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/watch/members/{member_id}", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request(
            "POST", f"/watch/members/{member_id}/suspend", {}, headers,
        )

    def reinstate_member(self, member_id, headers):
        return self._request(
            "POST", f"/watch/members/{member_id}/reinstate", {}, headers,
        )

    def withdraw_member(self, member_id, headers):
        return self._request(
            "POST", f"/watch/members/{member_id}/withdraw", {}, headers,
        )

    # ---- BlockCaptainAssignment ----
    def create_captain_assignment(self, block_id, payload, headers):
        return self._request(
            "POST", f"/watch/blocks/{block_id}/captain-assignments",
            payload, headers,
        )

    def list_block_captain_assignments(self, block_id, headers, params=None):
        return self._request(
            "GET", f"/watch/blocks/{block_id}/captain-assignments",
            headers=headers, params=params,
        )

    def list_captain_assignments(self, headers, params=None):
        return self._request(
            "GET", "/watch/captain-assignments", headers=headers, params=params,
        )

    def get_captain_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/watch/captain-assignments/{assignment_id}", headers=headers,
        )

    def relieve_captain_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/watch/captain-assignments/{assignment_id}/relieve",
            {}, headers,
        )

    # ---- IncidentReport ----
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/watch/incident-reports", payload, headers)

    def list_incident_reports(self, headers, params=None):
        return self._request(
            "GET", "/watch/incident-reports", headers=headers, params=params,
        )

    def get_incident_report(self, report_id, headers):
        return self._request(
            "GET", f"/watch/incident-reports/{report_id}", headers=headers,
        )

    def begin_review_incident(self, report_id, headers):
        return self._request(
            "POST", f"/watch/incident-reports/{report_id}/begin-review",
            {}, headers,
        )

    def request_info_incident(self, report_id, headers):
        return self._request(
            "POST", f"/watch/incident-reports/{report_id}/request-info",
            {}, headers,
        )

    def resubmit_incident(self, report_id, headers):
        return self._request(
            "POST", f"/watch/incident-reports/{report_id}/resubmit", {}, headers,
        )

    def corroborate_incident(self, report_id, headers):
        return self._request(
            "POST", f"/watch/incident-reports/{report_id}/corroborate",
            {}, headers,
        )

    def dismiss_incident(self, report_id, headers):
        return self._request(
            "POST", f"/watch/incident-reports/{report_id}/dismiss", {}, headers,
        )

    def clear_incident(self, report_id, headers):
        return self._request(
            "POST", f"/watch/incident-reports/{report_id}/clear", {}, headers,
        )

    # ---- Alert ----
    def create_alert(self, payload, headers):
        return self._request("POST", "/watch/alerts", payload, headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/watch/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/watch/alerts/{alert_id}", headers=headers)

    def queue_alert(self, alert_id, headers):
        return self._request(
            "POST", f"/watch/alerts/{alert_id}/queue", {}, headers,
        )

    def send_alert(self, alert_id, headers):
        return self._request(
            "POST", f"/watch/alerts/{alert_id}/send", {}, headers,
        )

    def unqueue_alert(self, alert_id, headers):
        return self._request(
            "POST", f"/watch/alerts/{alert_id}/unqueue", {}, headers,
        )

    def recall_alert(self, alert_id, headers):
        return self._request(
            "POST", f"/watch/alerts/{alert_id}/recall", {}, headers,
        )

    def ack_alert(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/watch/alerts/{alert_id}/ack", payload, headers,
        )

    # ---- LiaisonOfficer ----
    def create_liaison_officer(self, payload, headers):
        return self._request("POST", "/watch/liaison-officers", payload, headers)

    def list_liaison_officers(self, headers, params=None):
        return self._request(
            "GET", "/watch/liaison-officers", headers=headers, params=params,
        )

    def get_liaison_officer(self, officer_id, headers):
        return self._request(
            "GET", f"/watch/liaison-officers/{officer_id}", headers=headers,
        )

    # ---- LiaisonMeeting ----
    def create_liaison_meeting(self, payload, headers):
        return self._request("POST", "/watch/liaison-meetings", payload, headers)

    def list_liaison_meetings(self, headers, params=None):
        return self._request(
            "GET", "/watch/liaison-meetings", headers=headers, params=params,
        )

    def get_liaison_meeting(self, meeting_id, headers):
        return self._request(
            "GET", f"/watch/liaison-meetings/{meeting_id}", headers=headers,
        )

    def mark_meeting_held(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/watch/liaison-meetings/{meeting_id}/mark-held",
            payload, headers,
        )

    def cancel_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/watch/liaison-meetings/{meeting_id}/cancel", {}, headers,
        )

    # ---- DataShareAgreement ----
    def create_data_share_agreement(self, payload, headers):
        return self._request("POST", "/watch/data-share-agreements", payload, headers)

    def list_data_share_agreements(self, headers, params=None):
        return self._request(
            "GET", "/watch/data-share-agreements", headers=headers, params=params,
        )

    def get_data_share_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/watch/data-share-agreements/{agreement_id}", headers=headers,
        )

    def activate_data_share_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/watch/data-share-agreements/{agreement_id}/activate",
            {}, headers,
        )

    def revoke_data_share_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/watch/data-share-agreements/{agreement_id}/revoke",
            {}, headers,
        )

    # ---- TrainingSession ----
    def create_training_session(self, payload, headers):
        return self._request("POST", "/watch/training-sessions", payload, headers)

    def list_training_sessions(self, headers, params=None):
        return self._request(
            "GET", "/watch/training-sessions", headers=headers, params=params,
        )

    def get_training_session(self, session_id, headers):
        return self._request(
            "GET", f"/watch/training-sessions/{session_id}", headers=headers,
        )

    def complete_training_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/watch/training-sessions/{session_id}/complete",
            payload, headers,
        )

    def cancel_training_session(self, session_id, headers):
        return self._request(
            "POST", f"/watch/training-sessions/{session_id}/cancel", {}, headers,
        )

    # ---- CommunityEvent ----
    def create_community_event(self, payload, headers):
        return self._request("POST", "/watch/community-events", payload, headers)

    def list_community_events(self, headers, params=None):
        return self._request(
            "GET", "/watch/community-events", headers=headers, params=params,
        )

    def get_community_event(self, event_id, headers):
        return self._request(
            "GET", f"/watch/community-events/{event_id}", headers=headers,
        )

    def approve_community_event(self, event_id, headers):
        return self._request(
            "POST", f"/watch/community-events/{event_id}/approve", {}, headers,
        )

    def complete_community_event(self, event_id, headers):
        return self._request(
            "POST", f"/watch/community-events/{event_id}/complete", {}, headers,
        )

    def cancel_community_event(self, event_id, headers):
        return self._request(
            "POST", f"/watch/community-events/{event_id}/cancel", {}, headers,
        )

    # ---- CertificationReview ----
    def create_certification_review(self, payload, headers):
        return self._request("POST", "/watch/certification-reviews", payload, headers)

    def list_certification_reviews(self, headers, params=None):
        return self._request(
            "GET", "/watch/certification-reviews", headers=headers, params=params,
        )

    def get_certification_review(self, review_id, headers):
        return self._request(
            "GET", f"/watch/certification-reviews/{review_id}", headers=headers,
        )

    def decide_certification_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/watch/certification-reviews/{review_id}/decide",
            payload, headers,
        )


api_client = ApiClient()
