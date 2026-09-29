"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def convene_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/sessions/{session_id}/convene", {}, headers)

    def adjourn_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/sessions/{session_id}/adjourn", {}, headers)

    # ------------------------------------------------------------------
    # Committees
    # ------------------------------------------------------------------
    def create_committee(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sessions/{session_id}/committees", payload, headers
        )

    def list_session_committees(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/sessions/{session_id}/committees", headers=headers, params=params
        )

    def get_committee(self, committee_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/committees/{committee_id}", headers=headers)

    # ------------------------------------------------------------------
    # Members, drafters, agencies
    # ------------------------------------------------------------------
    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def create_drafter(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/drafters", payload, headers)

    def get_drafter(self, drafter_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/drafters/{drafter_id}", headers=headers)

    def create_agency(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    # ------------------------------------------------------------------
    # Drafting requests
    # ------------------------------------------------------------------
    def create_drafting_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/drafting-requests", payload, headers)

    def get_drafting_request(self, drafting_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/drafting-requests/{drafting_request_id}", headers=headers
        )

    def list_drafting_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/drafting-requests", headers=headers, params=params
        )

    def assign_drafting_request(
        self, drafting_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/drafting-requests/{drafting_request_id}/assign", payload, headers
        )

    def complete_research(
        self, drafting_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/drafting-requests/{drafting_request_id}/complete-research",
            payload,
            headers,
        )

    def clarify_drafting_request(
        self, drafting_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/drafting-requests/{drafting_request_id}/clarify", payload, headers
        )

    def certify_draft(
        self, drafting_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/drafting-requests/{drafting_request_id}/certify-draft",
            payload,
            headers,
        )

    def withdraw_drafting_request(
        self, drafting_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/drafting-requests/{drafting_request_id}/withdraw",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Statutory conflicts
    # ------------------------------------------------------------------
    def create_statutory_conflict(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/statutory-conflicts", payload, headers)

    def get_statutory_conflict(self, conflict_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/statutory-conflicts/{conflict_id}", headers=headers
        )

    def list_request_statutory_conflicts(
        self,
        drafting_request_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/drafting-requests/{drafting_request_id}/statutory-conflicts",
            headers=headers,
            params=params,
        )

    def resolve_statutory_conflict(
        self, conflict_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/statutory-conflicts/{conflict_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Bills
    # ------------------------------------------------------------------
    def create_bill(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/bills", payload, headers)

    def get_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def list_bills(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/bills", headers=headers, params=params)

    def link_companion(
        self, bill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/bills/{bill_id}/companion", payload, headers)

    def create_referral(
        self, bill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/bills/{bill_id}/referrals", payload, headers)

    def pass_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/bills/{bill_id}/pass", {}, headers)

    def enroll_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/bills/{bill_id}/enroll", {}, headers)

    # ------------------------------------------------------------------
    # Committee referrals
    # ------------------------------------------------------------------
    def get_committee_referral(self, referral_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/committee-referrals/{referral_id}", headers=headers
        )

    def list_committee_referrals(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/committee-referrals", headers=headers, params=params
        )

    def report_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/committee-referrals/{referral_id}/report", payload, headers
        )

    # ------------------------------------------------------------------
    # Fiscal note requests
    # ------------------------------------------------------------------
    def create_fiscal_note_request(
        self, bill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/bills/{bill_id}/fiscal-note-requests", payload, headers
        )

    def get_fiscal_note_request(
        self, fiscal_note_request_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/fiscal-note-requests/{fiscal_note_request_id}", headers=headers
        )

    def list_fiscal_note_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/fiscal-note-requests", headers=headers, params=params
        )

    def create_cost_estimate(
        self,
        fiscal_note_request_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fiscal-note-requests/{fiscal_note_request_id}/cost-estimates",
            payload,
            headers,
        )

    def list_cost_estimates(
        self,
        fiscal_note_request_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/fiscal-note-requests/{fiscal_note_request_id}/cost-estimates",
            headers=headers,
            params=params,
        )

    def submit_fiscal_note_request(
        self,
        fiscal_note_request_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fiscal-note-requests/{fiscal_note_request_id}/submit",
            payload,
            headers,
        )

    def return_fiscal_note_request(
        self,
        fiscal_note_request_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fiscal-note-requests/{fiscal_note_request_id}/return",
            payload,
            headers,
        )

    def certify_fiscal_note_request(
        self,
        fiscal_note_request_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fiscal-note-requests/{fiscal_note_request_id}/certify",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Amendments
    # ------------------------------------------------------------------
    def create_amendment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/amendments", payload, headers)

    def get_amendment(self, amendment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/amendments/{amendment_id}", headers=headers)

    def list_amendments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/amendments", headers=headers, params=params)

    def draft_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/amendments/{amendment_id}/draft", payload, headers
        )

    def adopt_amendment(self, amendment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/amendments/{amendment_id}/adopt", {}, headers)

    def reject_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/amendments/{amendment_id}/reject", payload, headers
        )

    def rescind_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/amendments/{amendment_id}/rescind", payload, headers
        )

    # ------------------------------------------------------------------
    # Enrollment, corrections and signatures
    # ------------------------------------------------------------------
    def get_enrolled_bill(self, enrolled_bill_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrolled-bills/{enrolled_bill_id}", headers=headers
        )

    def list_enrolled_bills(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/enrolled-bills", headers=headers, params=params)

    def create_technical_correction(
        self, enrolled_bill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/enrolled-bills/{enrolled_bill_id}/technical-corrections",
            payload,
            headers,
        )

    def get_technical_correction(self, correction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/technical-corrections/{correction_id}", headers=headers
        )

    def list_technical_corrections(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/technical-corrections", headers=headers, params=params
        )

    def apply_technical_correction(self, correction_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/technical-corrections/{correction_id}/apply", {}, headers
        )

    def create_signature(
        self, enrolled_bill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/enrolled-bills/{enrolled_bill_id}/signatures", payload, headers
        )


api_client = ApiClient()
