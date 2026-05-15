"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Authors (PRD §3.1, §4)
    # =======================================================================
    def create_author(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/authors", payload, headers)

    def get_author(self, author_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/authors/{author_id}", headers=headers)

    def list_authors(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/authors",
                             headers=headers, params=params)

    # =======================================================================
    # Reviewers (PRD §3.5 — pool registry, §4)
    # =======================================================================
    def create_reviewer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reviewers/{reviewer_id}",
                             headers=headers)

    def list_reviewers(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/reviewers",
                             headers=headers, params=params)

    # =======================================================================
    # Editors (PRD §3.4, §4)
    # =======================================================================
    def create_editor(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/editors", payload, headers)

    def get_editor(self, editor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/editors/{editor_id}",
                             headers=headers)

    def list_editors(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/editors",
                             headers=headers, params=params)

    # =======================================================================
    # Manuscripts — collection + reads (PRD §3.2, §4)
    # =======================================================================
    def create_manuscript(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/manuscripts", payload, headers)

    def get_manuscript(self, manuscript_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/manuscripts/{manuscript_id}",
                             headers=headers)

    def list_manuscripts(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/manuscripts",
                             headers=headers, params=params)

    # =======================================================================
    # Manuscript actions (PRD §3.2–§3.8)
    # =======================================================================
    def submit_manuscript(self, manuscript_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/submit",
            payload or {}, headers,
        )

    def withdraw_manuscript(self, manuscript_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/withdraw",
            payload or {}, headers,
        )

    def confirm_coauthor(self, manuscript_id: str, confirmation_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/manuscripts/{manuscript_id}"
             f"/coauthor-confirmations/{confirmation_id}/confirm"),
            {}, headers,
        )

    def decline_coauthor(self, manuscript_id: str, confirmation_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/manuscripts/{manuscript_id}"
             f"/coauthor-confirmations/{confirmation_id}/decline"),
            {}, headers,
        )

    def list_coauthor_confirmations(self, manuscript_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/manuscripts/{manuscript_id}/coauthor-confirmations",
            headers=headers,
        )

    def assign_section_editor(self, manuscript_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/manuscripts/{manuscript_id}/assign-section-editor",
            payload, headers,
        )

    def desk_reject_manuscript(self, manuscript_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/manuscripts/{manuscript_id}/desk-reject",
            payload or {}, headers,
        )

    def assign_associate(self, manuscript_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/manuscripts/{manuscript_id}/assign-associate",
            payload, headers,
        )

    # =======================================================================
    # Reviewer Invitations (PRD §3.5)
    # =======================================================================
    def create_invitation(self, manuscript_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/invitations",
            payload, headers,
        )

    def list_invitations(self, manuscript_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/manuscripts/{manuscript_id}/invitations",
            headers=headers, params=params,
        )

    def accept_invitation(self, manuscript_id: str, invitation_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/manuscripts/{manuscript_id}"
             f"/invitations/{invitation_id}/accept"),
            {}, headers,
        )

    def decline_invitation(self, manuscript_id: str, invitation_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/manuscripts/{manuscript_id}"
             f"/invitations/{invitation_id}/decline"),
            {}, headers,
        )

    def withdraw_invitation(self, manuscript_id: str, invitation_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/manuscripts/{manuscript_id}"
             f"/invitations/{invitation_id}/withdraw"),
            {}, headers,
        )

    # =======================================================================
    # Reviews (PRD §3.6)
    # =======================================================================
    def get_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reviews/{review_id}",
                             headers=headers)

    def patch_review(self, review_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("PATCH", f"/reviews/{review_id}",
                             payload, headers)

    def submit_review(self, review_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reviews/{review_id}/submit",
            payload or {}, headers,
        )

    # =======================================================================
    # Editor Decisions (PRD §3.7)
    # =======================================================================
    def create_decision(self, manuscript_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/decisions",
            payload, headers,
        )

    def recommend_decision(self, manuscript_id: str, decision_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            (f"/manuscripts/{manuscript_id}"
             f"/decisions/{decision_id}/recommend"),
            payload or {}, headers,
        )

    def finalize_decision(self, manuscript_id: str, decision_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/manuscripts/{manuscript_id}"
             f"/decisions/{decision_id}/finalize"),
            payload, headers,
        )

    # =======================================================================
    # Revisions (PRD §3.8)
    # =======================================================================
    def submit_revision(self, manuscript_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/revisions",
            payload, headers,
        )

    def reinvite_reviewers(self, manuscript_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/reinvite-reviewers",
            payload, headers,
        )

    # =======================================================================
    # Publications (PRD §3.9)
    # =======================================================================
    def create_publication(self, manuscript_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/publications",
            payload, headers,
        )

    def send_proof(self, publication_id: str,
                   headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/publications/{publication_id}/send-proof",
            payload or {}, headers,
        )

    def approve_proof(self, publication_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/publications/{publication_id}/approve-proof",
            payload or {}, headers,
        )

    def publish_issue(self, publication_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/publications/{publication_id}/publish-issue",
            payload or {}, headers,
        )

    def retract_manuscript(self, manuscript_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/manuscripts/{manuscript_id}/retract",
            payload or {}, headers,
        )

    # =======================================================================
    # Audit logs (PRD §2.10, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-logs",
                             headers=headers, params=params)

    # =======================================================================
    # Test-driving / event-ingestion endpoints (PRD §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)

    def orcid_verified_event(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/_events/orcid-verified",
                             payload, headers)

    def plagiarism_result_event(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/_events/plagiarism-result",
                             payload, headers)

    def doi_mint_event(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/_events/doi-mint",
                             payload, headers)

    def indexing_ack_event(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/_events/indexing-ack",
                             payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
