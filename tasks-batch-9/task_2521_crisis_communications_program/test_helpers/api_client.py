"""Typed HTTP client exposing one method per declared endpoint (PRD §4).

Every method returns the raw ``requests.Response`` so tests can assert on both
the status code and the payload through the framework validators.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Payload = Dict[str, Any]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per endpoint in the Crisis Communications Program API."""

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _body(payload: Optional[Payload]) -> Payload:
        return {} if payload is None else payload

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Payload, headers: Headers):
        """POST /_clock/set_current_utc"""
        return self.post("/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Team members
    # ------------------------------------------------------------------
    def create_team_member(self, payload: Payload, headers: Headers):
        """POST /crisis/team-members"""
        return self.post("/crisis/team-members", payload, headers)

    def get_team_member(self, member_id: str, headers: Headers):
        """GET /crisis/team-members/{member_id}"""
        return self.get(f"/crisis/team-members/{member_id}", headers)

    def list_team_members(self, headers: Headers, params: Params = None):
        """GET /crisis/team-members"""
        return self.get("/crisis/team-members", headers, params)

    # ------------------------------------------------------------------
    # Monitored channels
    # ------------------------------------------------------------------
    def create_monitored_channel(self, payload: Payload, headers: Headers):
        """POST /crisis/monitored-channels"""
        return self.post("/crisis/monitored-channels", payload, headers)

    def get_monitored_channel(self, channel_id: str, headers: Headers):
        """GET /crisis/monitored-channels/{channel_id}"""
        return self.get(f"/crisis/monitored-channels/{channel_id}", headers)

    def list_monitored_channels(self, headers: Headers, params: Params = None):
        """GET /crisis/monitored-channels"""
        return self.get("/crisis/monitored-channels", headers, params)

    def verify_escalation_path(
        self, channel_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/monitored-channels/{channel_id}/verify-escalation-path"""
        return self.post(
            f"/crisis/monitored-channels/{channel_id}/verify-escalation-path",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------
    def create_incident(self, payload: Payload, headers: Headers):
        """POST /crisis/incidents"""
        return self.post("/crisis/incidents", payload, headers)

    def get_incident(self, incident_id: str, headers: Headers):
        """GET /crisis/incidents/{incident_id}"""
        return self.get(f"/crisis/incidents/{incident_id}", headers)

    def list_incidents(self, headers: Headers, params: Params = None):
        """GET /crisis/incidents"""
        return self.get("/crisis/incidents", headers, params)

    def activate_incident(
        self, incident_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/incidents/{incident_id}/activate"""
        return self.post(
            f"/crisis/incidents/{incident_id}/activate", self._body(payload), headers
        )

    def assert_privilege(
        self, incident_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/incidents/{incident_id}/assert-privilege"""
        return self.post(
            f"/crisis/incidents/{incident_id}/assert-privilege", payload, headers
        )

    def waive_privilege(
        self, incident_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/incidents/{incident_id}/waive-privilege"""
        return self.post(
            f"/crisis/incidents/{incident_id}/waive-privilege",
            self._body(payload),
            headers,
        )

    def resolve_incident(
        self, incident_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/incidents/{incident_id}/resolve"""
        return self.post(
            f"/crisis/incidents/{incident_id}/resolve", self._body(payload), headers
        )

    def sla_sweep(
        self, incident_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/incidents/{incident_id}/sla-sweep"""
        return self.post(
            f"/crisis/incidents/{incident_id}/sla-sweep", self._body(payload), headers
        )

    # ------------------------------------------------------------------
    # Team assignments
    # ------------------------------------------------------------------
    def create_team_assignment(self, payload: Payload, headers: Headers):
        """POST /crisis/team-assignments"""
        return self.post("/crisis/team-assignments", payload, headers)

    def get_team_assignment(self, assignment_id: str, headers: Headers):
        """GET /crisis/team-assignments/{assignment_id}"""
        return self.get(f"/crisis/team-assignments/{assignment_id}", headers)

    def list_team_assignments(self, headers: Headers, params: Params = None):
        """GET /crisis/team-assignments"""
        return self.get("/crisis/team-assignments", headers, params)

    def acknowledge_team_assignment(
        self, assignment_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/team-assignments/{assignment_id}/acknowledge"""
        return self.post(
            f"/crisis/team-assignments/{assignment_id}/acknowledge",
            self._body(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Issue signals
    # ------------------------------------------------------------------
    def create_issue_signal(self, payload: Payload, headers: Headers):
        """POST /crisis/issue-signals"""
        return self.post("/crisis/issue-signals", payload, headers)

    def get_issue_signal(self, signal_id: str, headers: Headers):
        """GET /crisis/issue-signals/{signal_id}"""
        return self.get(f"/crisis/issue-signals/{signal_id}", headers)

    def list_issue_signals(self, headers: Headers, params: Params = None):
        """GET /crisis/issue-signals"""
        return self.get("/crisis/issue-signals", headers, params)

    def link_issue_signal(self, signal_id: str, payload: Payload, headers: Headers):
        """POST /crisis/issue-signals/{signal_id}/link"""
        return self.post(f"/crisis/issue-signals/{signal_id}/link", payload, headers)

    def escalate_issue_signal(
        self, signal_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/issue-signals/{signal_id}/escalate"""
        return self.post(
            f"/crisis/issue-signals/{signal_id}/escalate", self._body(payload), headers
        )

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------
    def create_statement(self, payload: Payload, headers: Headers):
        """POST /crisis/statements"""
        return self.post("/crisis/statements", payload, headers)

    def get_statement(self, statement_id: str, headers: Headers):
        """GET /crisis/statements/{statement_id}"""
        return self.get(f"/crisis/statements/{statement_id}", headers)

    def list_statements(self, headers: Headers, params: Params = None):
        """GET /crisis/statements"""
        return self.get("/crisis/statements", headers, params)

    def submit_statement_review(
        self, statement_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/statements/{statement_id}/submit-review"""
        return self.post(
            f"/crisis/statements/{statement_id}/submit-review",
            self._body(payload),
            headers,
        )

    def revise_statement(self, statement_id: str, payload: Payload, headers: Headers):
        """POST /crisis/statements/{statement_id}/revise"""
        return self.post(
            f"/crisis/statements/{statement_id}/revise", payload, headers
        )

    def publish_statement(
        self, statement_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/statements/{statement_id}/publish"""
        return self.post(
            f"/crisis/statements/{statement_id}/publish", self._body(payload), headers
        )

    def withdraw_statement(
        self, statement_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/statements/{statement_id}/withdraw"""
        return self.post(
            f"/crisis/statements/{statement_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Approval tasks
    # ------------------------------------------------------------------
    def get_approval_task(self, task_id: str, headers: Headers):
        """GET /crisis/approval-tasks/{task_id}"""
        return self.get(f"/crisis/approval-tasks/{task_id}", headers)

    def list_approval_tasks(self, headers: Headers, params: Params = None):
        """GET /crisis/approval-tasks"""
        return self.get("/crisis/approval-tasks", headers, params)

    def decide_approval_task(self, task_id: str, payload: Payload, headers: Headers):
        """POST /crisis/approval-tasks/{task_id}/decide"""
        return self.post(f"/crisis/approval-tasks/{task_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Stakeholder notices
    # ------------------------------------------------------------------
    def create_stakeholder_notice(self, payload: Payload, headers: Headers):
        """POST /crisis/stakeholder-notices"""
        return self.post("/crisis/stakeholder-notices", payload, headers)

    def get_stakeholder_notice(self, notice_id: str, headers: Headers):
        """GET /crisis/stakeholder-notices/{notice_id}"""
        return self.get(f"/crisis/stakeholder-notices/{notice_id}", headers)

    def list_stakeholder_notices(self, headers: Headers, params: Params = None):
        """GET /crisis/stakeholder-notices"""
        return self.get("/crisis/stakeholder-notices", headers, params)

    def release_stakeholder_notice(
        self, notice_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/stakeholder-notices/{notice_id}/release"""
        return self.post(
            f"/crisis/stakeholder-notices/{notice_id}/release",
            self._body(payload),
            headers,
        )

    def cancel_stakeholder_notice(
        self, notice_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/stakeholder-notices/{notice_id}/cancel"""
        return self.post(
            f"/crisis/stakeholder-notices/{notice_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Prepared materials
    # ------------------------------------------------------------------
    def create_prepared_material(self, payload: Payload, headers: Headers):
        """POST /crisis/prepared-materials"""
        return self.post("/crisis/prepared-materials", payload, headers)

    def get_prepared_material(self, material_id: str, headers: Headers):
        """GET /crisis/prepared-materials/{material_id}"""
        return self.get(f"/crisis/prepared-materials/{material_id}", headers)

    def list_prepared_materials(self, headers: Headers, params: Params = None):
        """GET /crisis/prepared-materials"""
        return self.get("/crisis/prepared-materials", headers, params)

    def review_prepared_material(
        self, material_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/prepared-materials/{material_id}/review"""
        return self.post(
            f"/crisis/prepared-materials/{material_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Media interviews
    # ------------------------------------------------------------------
    def create_media_interview(self, payload: Payload, headers: Headers):
        """POST /crisis/media-interviews"""
        return self.post("/crisis/media-interviews", payload, headers)

    def get_media_interview(self, interview_id: str, headers: Headers):
        """GET /crisis/media-interviews/{interview_id}"""
        return self.get(f"/crisis/media-interviews/{interview_id}", headers)

    def list_media_interviews(self, headers: Headers, params: Params = None):
        """GET /crisis/media-interviews"""
        return self.get("/crisis/media-interviews", headers, params)

    def confirm_media_interview(
        self, interview_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/media-interviews/{interview_id}/confirm"""
        return self.post(
            f"/crisis/media-interviews/{interview_id}/confirm",
            self._body(payload),
            headers,
        )

    def cancel_media_interview(
        self, interview_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/media-interviews/{interview_id}/cancel"""
        return self.post(
            f"/crisis/media-interviews/{interview_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Misinformation claims
    # ------------------------------------------------------------------
    def create_misinformation_claim(self, payload: Payload, headers: Headers):
        """POST /crisis/misinformation-claims"""
        return self.post("/crisis/misinformation-claims", payload, headers)

    def get_misinformation_claim(self, claim_id: str, headers: Headers):
        """GET /crisis/misinformation-claims/{claim_id}"""
        return self.get(f"/crisis/misinformation-claims/{claim_id}", headers)

    def list_misinformation_claims(self, headers: Headers, params: Params = None):
        """GET /crisis/misinformation-claims"""
        return self.get("/crisis/misinformation-claims", headers, params)

    def triage_misinformation_claim(
        self, claim_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/misinformation-claims/{claim_id}/triage"""
        return self.post(
            f"/crisis/misinformation-claims/{claim_id}/triage",
            self._body(payload),
            headers,
        )

    def escalate_platform(
        self, claim_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        """POST /crisis/misinformation-claims/{claim_id}/escalate-platform"""
        return self.post(
            f"/crisis/misinformation-claims/{claim_id}/escalate-platform",
            self._body(payload),
            headers,
        )

    def issue_correction(self, claim_id: str, payload: Payload, headers: Headers):
        """POST /crisis/misinformation-claims/{claim_id}/issue-correction"""
        return self.post(
            f"/crisis/misinformation-claims/{claim_id}/issue-correction",
            payload,
            headers,
        )

    def close_misinformation_claim(
        self, claim_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/misinformation-claims/{claim_id}/close"""
        return self.post(
            f"/crisis/misinformation-claims/{claim_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Post-crisis reviews
    # ------------------------------------------------------------------
    def get_post_crisis_review(self, review_id: str, headers: Headers):
        """GET /crisis/post-crisis-reviews/{review_id}"""
        return self.get(f"/crisis/post-crisis-reviews/{review_id}", headers)

    def list_post_crisis_reviews(self, headers: Headers, params: Params = None):
        """GET /crisis/post-crisis-reviews"""
        return self.get("/crisis/post-crisis-reviews", headers, params)

    def score_post_crisis_review(
        self, review_id: str, payload: Payload, headers: Headers
    ):
        """POST /crisis/post-crisis-reviews/{review_id}/score"""
        return self.post(
            f"/crisis/post-crisis-reviews/{review_id}/score", payload, headers
        )


api_client = ApiClient()
