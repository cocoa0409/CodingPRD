"""API client: one method per endpoint defined in the PRD.

Every endpoint is rooted at the ``/fundraising`` prefix, with the sole
exception of the logical-clock control endpoint (PRD 4).
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fundraising"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Employers and coordinators
    # ------------------------------------------------------------------
    def create_employer(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/employers/{employer_id}", headers=headers)

    def activate_employer(self, employer_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/employers/{employer_id}/activate", payload or {}, headers
        )

    def create_coordinator(self, employer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/employers/{employer_id}/coordinators", payload, headers
        )

    def list_employer_coordinators(
        self, employer_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/employers/{employer_id}/coordinators", headers=headers, params=params
        )

    def list_employer_campaigns(
        self, employer_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/employers/{employer_id}/campaigns", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    def create_campaign(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/campaigns", payload, headers)

    def get_campaign(self, campaign_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/campaigns/{campaign_id}", headers=headers)

    def open_campaign(self, campaign_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/open", payload or {}, headers
        )

    def close_campaign_solicitation(
        self, campaign_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/close-solicitation", payload or {}, headers
        )

    def reconcile_campaign(self, campaign_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/reconcile", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Pledges, designation lines, remittances and write-offs
    # ------------------------------------------------------------------
    def create_pledge(self, campaign_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/pledges", payload, headers
        )

    def get_pledge(self, pledge_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/pledges", headers=headers, params=params)

    def list_pledge_designations(
        self, pledge_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/pledges/{pledge_id}/designations", headers=headers, params=params
        )

    def confirm_pledge(self, pledge_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/pledges/{pledge_id}/confirm", payload or {}, headers
        )

    def amend_pledge_designations(self, pledge_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/pledges/{pledge_id}/designations:amend", payload, headers
        )

    def create_collection(self, pledge_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/pledges/{pledge_id}/collections", payload, headers
        )

    def write_off_pledge(self, pledge_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/pledges/{pledge_id}/write-off", payload, headers
        )

    # ------------------------------------------------------------------
    # Agencies and financial reviews
    # ------------------------------------------------------------------
    def create_agency(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/agencies/{agency_id}", headers=headers)

    def list_agency_designations(
        self, agency_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/designations", headers=headers, params=params
        )

    def create_agency_review(self, agency_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/agencies/{agency_id}/reviews", payload, headers
        )

    def list_agency_reviews(
        self, agency_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/reviews", headers=headers, params=params
        )

    def certify_agency_review(
        self, agency_id: str, review_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{PREFIX}/agencies/{agency_id}/reviews/{review_id}/certify",
            payload,
            headers,
        )

    def reinstate_agency(self, agency_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/agencies/{agency_id}/reinstate", payload, headers
        )

    # ------------------------------------------------------------------
    # Panelists, cycles and panel seats
    # ------------------------------------------------------------------
    def create_panelist(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/panelists", payload, headers)

    def get_panelist(self, panelist_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/panelists/{panelist_id}", headers=headers)

    def list_panelist_scores(
        self, panelist_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/panelists/{panelist_id}/scores", headers=headers, params=params
        )

    def list_panelist_panel_assignments(
        self, panelist_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/panelists/{panelist_id}/panel-assignments",
            headers=headers,
            params=params,
        )

    def create_allocation_cycle(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/allocation-cycles", payload, headers)

    def get_allocation_cycle(self, cycle_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/allocation-cycles/{cycle_id}", headers=headers)

    def get_impact_fund_summary(self, cycle_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/allocation-cycles/{cycle_id}/impact-fund-summary", headers=headers
        )

    def create_panel_assignment(self, cycle_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/allocation-cycles/{cycle_id}/panel-assignments", payload, headers
        )

    def list_cycle_panel_assignments(
        self, cycle_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/allocation-cycles/{cycle_id}/panel-assignments",
            headers=headers,
            params=params,
        )

    def open_allocation_cycle(self, cycle_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/allocation-cycles/{cycle_id}/open", payload or {}, headers
        )

    def freeze_allocation_cycle(
        self, cycle_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/allocation-cycles/{cycle_id}/freeze", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Allocation requests, scores, review closure and awards
    # ------------------------------------------------------------------
    def create_allocation_request(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/allocation-requests", payload, headers)

    def get_allocation_request(self, request_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/allocation-requests/{request_id}", headers=headers
        )

    def list_allocation_requests(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/allocation-requests", headers=headers, params=params
        )

    def submit_allocation_request(
        self, request_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/allocation-requests/{request_id}/submit", payload or {}, headers
        )

    def create_panel_score(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/allocation-requests/{request_id}/scores", payload, headers
        )

    def list_request_scores(
        self, request_id: str, headers: dict, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/allocation-requests/{request_id}/scores",
            headers=headers,
            params=params,
        )

    def finalize_review(self, request_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{PREFIX}/allocation-requests/{request_id}/finalize-review",
            payload or {},
            headers,
        )

    def create_award(self, cycle_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/allocation-cycles/{cycle_id}/awards", payload, headers
        )

    def rescind_award(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/allocation-requests/{request_id}/rescind-award", payload, headers
        )

    # ------------------------------------------------------------------
    # Outcome reports, monitoring site visits and closure
    # ------------------------------------------------------------------
    def create_outcome_report(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/allocation-requests/{request_id}/outcome-reports", payload, headers
        )

    def get_outcome_report(self, report_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/outcome-reports/{report_id}", headers=headers)

    def list_outcome_reports(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/outcome-reports", headers=headers, params=params)

    def schedule_site_visit(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/outcome-reports/{report_id}/site-visit", payload, headers
        )

    def complete_site_visit(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/outcome-reports/{report_id}/site-visit/complete", payload, headers
        )

    def accept_outcome_report(self, report_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/outcome-reports/{report_id}/accept", payload or {}, headers
        )

    def request_outcome_report_revision(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/outcome-reports/{report_id}/request-revision", payload, headers
        )

    def resubmit_outcome_report(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/outcome-reports/{report_id}/resubmit", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock (out-of-band administrative endpoint, PRD 2.7 / 4)
    # ------------------------------------------------------------------
    def set_logical_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
