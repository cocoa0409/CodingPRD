"""One client method per endpoint of the Investor Relations API (PRD section 4)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def _clean_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop unset filters and render booleans the way a query string expects."""
    if not params:
        return None
    cleaned: Dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
        else:
            cleaned[key] = value
    return cleaned or None


class ApiClient(GenericApiClient):
    """Typed wrapper around every documented route."""

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Companies (PRD 3.1)
    # ------------------------------------------------------------------
    def create_company(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/companies", payload, headers)

    def list_companies(self, headers=None, **filters):
        return self._request(
            "GET", "/companies", None, headers, params=_clean_params(filters)
        )

    def get_company(self, company_id: str, headers=None):
        return self._request("GET", f"/companies/{company_id}", None, headers)

    def recompute_posture(self, company_id: str, headers=None):
        return self._request(
            "POST", f"/companies/{company_id}/recompute-posture", {}, headers
        )

    def get_consensus(
        self,
        company_id: str,
        metric: Optional[str] = None,
        period_label: Optional[str] = None,
        variant: Optional[str] = None,
        headers=None,
    ):
        params = _clean_params(
            {"metric": metric, "period_label": period_label, "variant": variant}
        )
        return self._request(
            "GET", f"/companies/{company_id}/consensus", None, headers, params=params
        )

    # ------------------------------------------------------------------
    # Contacts (PRD 3.2, 3.3)
    # ------------------------------------------------------------------
    def create_contact(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/contacts", payload, headers)

    def list_contacts(self, headers=None, **filters):
        return self._request(
            "GET", "/contacts", None, headers, params=_clean_params(filters)
        )

    def get_contact(self, contact_id: str, headers=None):
        return self._request("GET", f"/contacts/{contact_id}", None, headers)

    def update_position(self, contact_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "PATCH", f"/contacts/{contact_id}/position", payload, headers
        )

    def servicing(self, contact_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/contacts/{contact_id}/servicing", payload, headers
        )

    def list_contact_estimates(self, contact_id: str, headers=None, **filters):
        return self._request(
            "GET",
            f"/contacts/{contact_id}/estimates",
            None,
            headers,
            params=_clean_params(filters),
        )

    # ------------------------------------------------------------------
    # Estimates (PRD 3.7)
    # ------------------------------------------------------------------
    def create_estimate(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/estimates", payload, headers)

    # ------------------------------------------------------------------
    # Disclosures (PRD 3.4)
    # ------------------------------------------------------------------
    def create_disclosure(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/disclosures", payload, headers)

    def list_disclosures(self, headers=None, **filters):
        return self._request(
            "GET", "/disclosures", None, headers, params=_clean_params(filters)
        )

    def get_disclosure(self, disclosure_id: str, headers=None):
        return self._request("GET", f"/disclosures/{disclosure_id}", None, headers)

    def publish_disclosure(self, disclosure_id: str, headers=None):
        return self._request(
            "POST", f"/disclosures/{disclosure_id}/publish", {}, headers
        )

    def withdraw_disclosure(self, disclosure_id: str, reason: str, headers=None):
        return self._request(
            "POST",
            f"/disclosures/{disclosure_id}/withdraw",
            {"reason": reason},
            headers,
        )

    # ------------------------------------------------------------------
    # Inquiry tickets (PRD 3.5)
    # ------------------------------------------------------------------
    def create_inquiry(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/inquiries", payload, headers)

    def list_inquiries(self, headers=None, **filters):
        return self._request(
            "GET", "/inquiries", None, headers, params=_clean_params(filters)
        )

    def get_inquiry(self, inquiry_id: str, headers=None):
        return self._request("GET", f"/inquiries/{inquiry_id}", None, headers)

    def route_inquiry(
        self, inquiry_id: str, target_queue: Optional[str] = None, headers=None
    ):
        payload: Dict[str, Any] = {}
        if target_queue is not None:
            payload["target_queue"] = target_queue
        return self._request(
            "POST", f"/inquiries/{inquiry_id}/route", payload, headers
        )

    # ------------------------------------------------------------------
    # Response drafts (PRD 3.6)
    # ------------------------------------------------------------------
    def create_response_draft(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/response-drafts", payload, headers)

    def list_response_drafts(self, headers=None, **filters):
        return self._request(
            "GET", "/response-drafts", None, headers, params=_clean_params(filters)
        )

    def get_response_draft(self, draft_id: str, headers=None):
        return self._request("GET", f"/response-drafts/{draft_id}", None, headers)

    def submit_draft_for_review(self, draft_id: str, headers=None):
        return self._request(
            "POST", f"/response-drafts/{draft_id}/submit-review", {}, headers
        )

    def review_draft(self, draft_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/response-drafts/{draft_id}/review", payload, headers
        )

    def revise_draft(self, draft_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/response-drafts/{draft_id}/revise", payload, headers
        )

    def send_draft(self, draft_id: str, headers=None):
        return self._request(
            "POST", f"/response-drafts/{draft_id}/send", {}, headers
        )

    # ------------------------------------------------------------------
    # Roadshow events (PRD 3.8)
    # ------------------------------------------------------------------
    def create_roadshow_event(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/roadshow-events", payload, headers)

    def list_roadshow_events(self, headers=None, **filters):
        return self._request(
            "GET", "/roadshow-events", None, headers, params=_clean_params(filters)
        )

    def get_roadshow_event(self, event_id: str, headers=None):
        return self._request("GET", f"/roadshow-events/{event_id}", None, headers)

    def open_event_requests(self, event_id: str, headers=None):
        return self._request(
            "POST", f"/roadshow-events/{event_id}/open-requests", {}, headers
        )

    def allocate_event(self, event_id: str, headers=None):
        return self._request(
            "POST", f"/roadshow-events/{event_id}/allocate", {}, headers
        )

    def complete_event(self, event_id: str, headers=None):
        return self._request(
            "POST", f"/roadshow-events/{event_id}/complete", {}, headers
        )

    # ------------------------------------------------------------------
    # Meeting requests (PRD 3.8)
    # ------------------------------------------------------------------
    def create_meeting_request(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/meeting-requests", payload, headers)

    def list_meeting_requests(self, headers=None, **filters):
        return self._request(
            "GET", "/meeting-requests", None, headers, params=_clean_params(filters)
        )

    def get_meeting_request(self, request_id: str, headers=None):
        return self._request("GET", f"/meeting-requests/{request_id}", None, headers)

    def release_meeting_request(self, request_id: str, reason: str, headers=None):
        return self._request(
            "POST",
            f"/meeting-requests/{request_id}/release",
            {"reason": reason},
            headers,
        )

    # ------------------------------------------------------------------
    # Transfer agent instructions (PRD 3.9)
    # ------------------------------------------------------------------
    def create_instruction(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/transfer-agent-instructions", payload, headers)

    def list_instructions(self, headers=None, **filters):
        return self._request(
            "GET",
            "/transfer-agent-instructions",
            None,
            headers,
            params=_clean_params(filters),
        )

    def get_instruction(self, instruction_id: str, headers=None):
        return self._request(
            "GET", f"/transfer-agent-instructions/{instruction_id}", None, headers
        )

    def acknowledge_instruction(
        self, instruction_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST",
            f"/transfer-agent-instructions/{instruction_id}/acknowledge",
            payload,
            headers,
        )

    def execute_instruction(self, instruction_id: str, headers=None):
        return self._request(
            "POST",
            f"/transfer-agent-instructions/{instruction_id}/execute",
            {},
            headers,
        )

    def reverse_instruction(self, instruction_id: str, reason: str, headers=None):
        return self._request(
            "POST",
            f"/transfer-agent-instructions/{instruction_id}/reverse",
            {"reason": reason},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches for header/precedence probes
    # ------------------------------------------------------------------
    def raw_get(self, path: str, headers=None, params: Optional[Dict] = None):
        return self._request("GET", path, None, headers, params=_clean_params(params))

    def raw_post(self, path: str, payload: Optional[Dict] = None, headers=None):
        return self._request("POST", path, payload if payload is not None else {}, headers)
