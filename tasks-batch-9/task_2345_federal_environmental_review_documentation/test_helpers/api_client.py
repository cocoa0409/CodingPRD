"""Typed HTTP client — one method per endpoint of the Federal Environmental
Review API (PRD 4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per declared endpoint. Every method returns the raw response
    so tests can assert status codes themselves."""

    # ---------------------------------------------------------------- offices
    def create_review_office(self, payload: dict, headers: dict):
        return self._request("POST", "/review-offices", payload, headers)

    def get_review_office(self, office_id: str, headers: dict):
        return self._request("GET", f"/review-offices/{office_id}", headers=headers)

    def list_review_offices(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/review-offices", headers=headers, params=params)

    # --------------------------------------------------------------- agencies
    def create_agency(self, payload: dict, headers: dict):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: dict):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def list_agencies(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/agencies", headers=headers, params=params)

    # -------------------------------------------------------- proposed actions
    def create_proposed_action(self, payload: dict, headers: dict):
        return self._request("POST", "/proposed-actions", payload, headers)

    def get_proposed_action(self, action_id: str, headers: dict):
        return self._request("GET", f"/proposed-actions/{action_id}", headers=headers)

    def list_proposed_actions(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/proposed-actions", headers=headers, params=params)

    def classify_proposed_action(self, action_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/classify", payload or {}, headers
        )

    # ------------------------------------------------------------- ec screens
    def submit_ec_screen(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/ec-screens", payload, headers
        )

    def list_ec_screens(self, action_id: str, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/ec-screens", headers=headers, params=params
        )

    def get_ec_screen(self, screen_id: str, headers: dict):
        return self._request("GET", f"/ec-screens/{screen_id}", headers=headers)

    def adjudicate_ec_screen(self, screen_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/ec-screens/{screen_id}/adjudicate", payload, headers)

    def resubmit_ec_screen(self, screen_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/ec-screens/{screen_id}/resubmit", payload, headers)

    # ------------------------------------------------ purpose need statements
    def create_purpose_need_statement(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/purpose-need-statements", payload, headers
        )

    def list_purpose_need_statements(self, action_id: str, headers: dict,
                                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/purpose-need-statements",
            headers=headers, params=params,
        )

    def get_purpose_need_statement(self, statement_id: str, headers: dict):
        return self._request(
            "GET", f"/purpose-need-statements/{statement_id}", headers=headers
        )

    def adopt_purpose_need_statement(self, statement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/purpose-need-statements/{statement_id}/adopt", payload, headers
        )

    # -------------------------------------------------------- scoping periods
    def create_scoping_period(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/scoping-periods", payload, headers
        )

    def list_scoping_periods(self, action_id: str, headers: dict,
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/scoping-periods",
            headers=headers, params=params,
        )

    def get_scoping_period(self, period_id: str, headers: dict):
        return self._request("GET", f"/scoping-periods/{period_id}", headers=headers)

    def close_scoping_period(self, period_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/scoping-periods/{period_id}/close", payload or {}, headers
        )

    # ----------------------------------------------------------------- issues
    def create_issue(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/issues", payload, headers
        )

    def list_action_issues(self, action_id: str, headers: dict,
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/issues", headers=headers, params=params
        )

    def get_issue(self, issue_id: str, headers: dict):
        return self._request("GET", f"/issues/{issue_id}", headers=headers)

    def list_issues(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/issues", headers=headers, params=params)

    # ----------------------------------------------------------- alternatives
    def create_alternative(self, payload: dict, headers: dict):
        return self._request("POST", "/alternatives", payload, headers)

    def get_alternative(self, alternative_id: str, headers: dict):
        return self._request("GET", f"/alternatives/{alternative_id}", headers=headers)

    def list_alternatives(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/alternatives", headers=headers, params=params)

    def screen_alternative(self, alternative_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/alternatives/{alternative_id}/screen", payload, headers
        )

    # ----------------------------------------------------- cumulative actions
    def create_cumulative_action(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/cumulative-actions", payload, headers
        )

    def list_cumulative_actions(self, action_id: str, headers: dict,
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/cumulative-actions",
            headers=headers, params=params,
        )

    # ------------------------------------------------------ resource analyses
    def create_resource_analysis(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/resource-analyses", payload, headers
        )

    def list_resource_analyses(self, action_id: str, headers: dict,
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/resource-analyses",
            headers=headers, params=params,
        )

    def get_resource_analysis(self, analysis_id: str, headers: dict):
        return self._request("GET", f"/resource-analyses/{analysis_id}", headers=headers)

    def finalize_resource_analysis(self, analysis_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/resource-analyses/{analysis_id}/finalize", payload, headers
        )

    def reopen_resource_analysis(self, analysis_id: str, headers: dict,
                                 payload: Optional[dict] = None):
        return self._request(
            "POST", f"/resource-analyses/{analysis_id}/reopen", payload or {}, headers
        )

    # ---------------------------------------------------------- consultations
    def create_consultation(self, payload: dict, headers: dict):
        return self._request("POST", "/consultations", payload, headers)

    def get_consultation(self, consultation_id: str, headers: dict):
        return self._request("GET", f"/consultations/{consultation_id}", headers=headers)

    def list_consultations(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/consultations", headers=headers, params=params)

    def respond_to_consultation(self, consultation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/consultations/{consultation_id}/respond", payload, headers
        )

    # -------------------------------------------------------------- documents
    def create_document(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/proposed-actions/{action_id}/documents", payload, headers
        )

    def list_documents(self, action_id: str, headers: dict,
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/documents", headers=headers, params=params
        )

    def get_document(self, document_id: str, headers: dict):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    def publish_document(self, document_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/documents/{document_id}/publish", payload, headers)

    def close_comment_period(self, document_id: str, headers: dict,
                             payload: Optional[dict] = None):
        return self._request(
            "POST", f"/documents/{document_id}/close-comment-period", payload or {}, headers
        )

    def finalize_document(self, document_id: str, headers: dict,
                          payload: Optional[dict] = None):
        return self._request(
            "POST", f"/documents/{document_id}/finalize", payload or {}, headers
        )

    # --------------------------------------------------------------- comments
    def create_comment(self, payload: dict, headers: dict):
        return self._request("POST", "/comments", payload, headers)

    def get_comment(self, comment_id: str, headers: dict):
        return self._request("GET", f"/comments/{comment_id}", headers=headers)

    def list_comments(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/comments", headers=headers, params=params)

    def respond_to_comment(self, comment_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/comments/{comment_id}/respond", payload, headers)

    # -------------------------------------------------------------- decisions
    def create_decision(self, payload: dict, headers: dict):
        return self._request("POST", "/decisions", payload, headers)

    def get_decision(self, decision_id: str, headers: dict):
        return self._request("GET", f"/decisions/{decision_id}", headers=headers)

    def list_decisions(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/decisions", headers=headers, params=params)

    def add_mitigation(self, decision_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/decisions/{decision_id}/mitigations", payload, headers)

    def get_mitigation(self, mitigation_id: str, headers: dict):
        return self._request("GET", f"/mitigations/{mitigation_id}", headers=headers)

    def list_mitigations(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/mitigations", headers=headers, params=params)

    def sign_decision(self, decision_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/decisions/{decision_id}/sign", payload or {}, headers)

    def certify_record(self, decision_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/decisions/{decision_id}/certify-record", payload or {}, headers
        )

    # ------------------------------------------------------------- objections
    def file_objection(self, decision_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/decisions/{decision_id}/objections", payload, headers)

    def list_decision_objections(self, decision_id: str, headers: dict,
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/decisions/{decision_id}/objections", headers=headers, params=params
        )

    def get_objection(self, objection_id: str, headers: dict):
        return self._request("GET", f"/objections/{objection_id}", headers=headers)

    def resolve_objection(self, objection_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/objections/{objection_id}/resolve", payload, headers)

    # --------------------------------------------------------- record entries
    def list_record_entries(self, action_id: str, headers: dict,
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/proposed-actions/{action_id}/record-entries",
            headers=headers, params=params,
        )

    # ---------------------------------------------------------- logical clock
    def set_clock(self, current_utc: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()
