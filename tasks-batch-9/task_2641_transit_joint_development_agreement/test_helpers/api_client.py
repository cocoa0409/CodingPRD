"""Endpoint-per-method API client for the Joint Development Agreement API.

One method per endpoint row of the PRD's endpoint catalogue. Every method
returns the raw response so tests can assert status codes themselves.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Domain client. Read endpoints accept any role; writes are role-gated."""

    # ---------------------------------------------------------------- sites
    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/jda/sites", headers=headers, params=params)

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/sites/{site_id}", headers=headers)

    def create_site(self, payload: Dict, headers: Dict[str, str]):
        return self._request("POST", "/jda/sites", payload, headers)

    def list_site_assessments(self, site_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", f"/jda/sites/{site_id}/assessments",
                             headers=headers, params=params)

    def list_site_solicitations(self, site_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/jda/sites/{site_id}/solicitations",
                             headers=headers, params=params)

    def list_site_valuations(self, site_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"/jda/sites/{site_id}/valuations",
                             headers=headers, params=params)

    def list_site_shared_facilities(self, site_id: str, headers: Dict[str, str],
                                    params: Optional[Dict] = None):
        return self._request("GET", f"/jda/sites/{site_id}/shared-facilities",
                             headers=headers, params=params)

    def create_assessment(self, site_id: str, payload: Dict, headers: Dict[str, str]):
        return self._request("POST", f"/jda/sites/{site_id}/assessments",
                             payload, headers)

    def certify_assessment(self, assessment_id: str, headers: Dict[str, str],
                           payload: Optional[Dict] = None):
        return self._request("POST", f"/jda/assessments/{assessment_id}/certify",
                             payload if payload is not None else {}, headers)

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/assessments/{assessment_id}",
                             headers=headers)

    def release_site_for_solicitation(self, site_id: str, headers: Dict[str, str],
                                      payload: Optional[Dict] = None):
        return self._request("POST", f"/jda/sites/{site_id}/release-for-solicitation",
                             payload if payload is not None else {}, headers)

    def reopen_site_inventory(self, site_id: str, payload: Dict,
                              headers: Dict[str, str]):
        return self._request("POST", f"/jda/sites/{site_id}/reopen-inventory",
                             payload, headers)

    # ----------------------------------------------------------- developers
    def create_developer(self, payload: Dict, headers: Dict[str, str]):
        return self._request("POST", "/jda/developers", payload, headers)

    def get_developer(self, developer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/developers/{developer_id}",
                             headers=headers)

    # -------------------------------------------------------- solicitations
    def create_solicitation(self, site_id: str, payload: Dict,
                            headers: Dict[str, str]):
        return self._request("POST", f"/jda/sites/{site_id}/solicitations",
                             payload, headers)

    def get_solicitation(self, solicitation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/solicitations/{solicitation_id}",
                             headers=headers)

    def issue_solicitation(self, solicitation_id: str, headers: Dict[str, str],
                           payload: Optional[Dict] = None):
        return self._request("POST", f"/jda/solicitations/{solicitation_id}/issue",
                             payload if payload is not None else {}, headers)

    def close_solicitation(self, solicitation_id: str, headers: Dict[str, str],
                           payload: Optional[Dict] = None):
        return self._request("POST", f"/jda/solicitations/{solicitation_id}/close",
                             payload if payload is not None else {}, headers)

    def award_solicitation(self, solicitation_id: str, payload: Dict,
                           headers: Dict[str, str]):
        return self._request("POST", f"/jda/solicitations/{solicitation_id}/award",
                             payload, headers)

    def list_solicitation_proposals(self, solicitation_id: str,
                                    headers: Dict[str, str],
                                    params: Optional[Dict] = None):
        return self._request("GET", "/jda/proposals", headers=headers,
                             params=dict(params or {}, solicitation_id=solicitation_id))

    # ------------------------------------------------------------ proposals
    def create_proposal(self, solicitation_id: str, payload: Dict,
                        headers: Dict[str, str]):
        return self._request("POST", f"/jda/solicitations/{solicitation_id}/proposals",
                             payload, headers)

    def get_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/jda/proposals", headers=headers, params=params)

    def shortlist_proposal(self, proposal_id: str, headers: Dict[str, str],
                           payload: Optional[Dict] = None):
        return self._request("POST", f"/jda/proposals/{proposal_id}/shortlist",
                             payload if payload is not None else {}, headers)

    # -------------------------------------------------- negotiation periods
    def create_negotiation_period(self, site_id: str, payload: Dict,
                                  headers: Dict[str, str]):
        return self._request("POST", f"/jda/sites/{site_id}/negotiation-periods",
                             payload, headers)

    def get_negotiation_period(self, period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/negotiation-periods/{period_id}",
                             headers=headers)

    def list_negotiation_periods(self, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request("GET", "/jda/negotiation-periods", headers=headers,
                             params=params)

    def extend_negotiation_period(self, period_id: str, payload: Dict,
                                  headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/negotiation-periods/{period_id}/extend",
                             payload, headers)

    def terminate_negotiation_period(self, period_id: str, payload: Dict,
                                     headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/negotiation-periods/{period_id}/terminate",
                             payload, headers)

    # ----------------------------------------------------------- valuations
    def create_valuation(self, site_id: str, payload: Dict,
                         headers: Dict[str, str]):
        return self._request("POST", f"/jda/sites/{site_id}/valuations",
                             payload, headers)

    def get_valuation(self, valuation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/valuations/{valuation_id}",
                             headers=headers)

    def certify_valuation(self, valuation_id: str, headers: Dict[str, str],
                          payload: Optional[Dict] = None):
        return self._request("POST", f"/jda/valuations/{valuation_id}/certify",
                             payload if payload is not None else {}, headers)

    # ----------------------------------------------------------- agreements
    def create_agreement(self, payload: Dict, headers: Dict[str, str]):
        return self._request("POST", "/jda/agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/agreements/{agreement_id}",
                             headers=headers)

    def list_agreements(self, headers: Dict[str, str],
                        params: Optional[Dict] = None):
        return self._request("GET", "/jda/agreements", headers=headers,
                             params=params)

    def update_agreement(self, agreement_id: str, payload: Dict,
                         headers: Dict[str, str]):
        return self._request("PATCH", f"/jda/agreements/{agreement_id}",
                             payload, headers)

    def submit_agreement_for_review(self, agreement_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict] = None):
        return self._request("POST",
                             f"/jda/agreements/{agreement_id}/submit-for-review",
                             payload if payload is not None else {}, headers)

    def request_agreement_revision(self, agreement_id: str, payload: Dict,
                                   headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/agreements/{agreement_id}/request-revision",
                             payload, headers)

    def board_approve_agreement(self, agreement_id: str, payload: Dict,
                                headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/agreements/{agreement_id}/board-approve",
                             payload, headers)

    def execute_agreement(self, agreement_id: str, payload: Dict,
                          headers: Dict[str, str]):
        return self._request("POST", f"/jda/agreements/{agreement_id}/execute",
                             payload, headers)

    # ------------------------------------------------- disposition requests
    def create_disposition_request(self, agreement_id: str, payload: Dict,
                                   headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/agreements/{agreement_id}/disposition-requests",
                             payload, headers)

    def list_agreement_disposition_requests(self, agreement_id: str,
                                            headers: Dict[str, str],
                                            params: Optional[Dict] = None):
        return self._request("GET",
                             f"/jda/agreements/{agreement_id}/disposition-requests",
                             headers=headers, params=params)

    def get_disposition_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/disposition-requests/{request_id}",
                             headers=headers)

    def record_disposition_determination(self, request_id: str, payload: Dict,
                                         headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/disposition-requests/{request_id}/determination",
                             payload, headers)

    def withdraw_disposition_request(self, request_id: str, payload: Dict,
                                     headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/disposition-requests/{request_id}/withdraw",
                             payload, headers)

    # ---------------------------------------------- facility replacements
    def create_facility_replacement(self, agreement_id: str, payload: Dict,
                                    headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/agreements/{agreement_id}/facility-replacements",
                             payload, headers)

    def list_agreement_facility_replacements(self, agreement_id: str,
                                             headers: Dict[str, str],
                                             params: Optional[Dict] = None):
        return self._request("GET",
                             f"/jda/agreements/{agreement_id}/facility-replacements",
                             headers=headers, params=params)

    def get_facility_replacement(self, replacement_id: str,
                                 headers: Dict[str, str]):
        return self._request("GET", f"/jda/facility-replacements/{replacement_id}",
                             headers=headers)

    def report_facility_replacement_status(self, replacement_id: str, payload: Dict,
                                          headers: Dict[str, str]):
        return self._request("POST",
                             f"/jda/facility-replacements/{replacement_id}/status",
                             payload, headers)

    # ------------------------------------------------------ shared facilities
    def create_shared_facility(self, site_id: str, payload: Dict,
                               headers: Dict[str, str]):
        return self._request("POST", f"/jda/sites/{site_id}/shared-facilities",
                             payload, headers)

    def get_shared_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/shared-facilities/{facility_id}",
                             headers=headers)

    # -------------------------------------------------------- staging windows
    def create_staging_window(self, payload: Dict, headers: Dict[str, str]):
        return self._request("POST", "/jda/staging-windows", payload, headers)

    def get_staging_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/jda/staging-windows/{window_id}",
                             headers=headers)

    def list_staging_windows(self, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", "/jda/staging-windows", headers=headers,
                             params=params)

    def decide_staging_window(self, window_id: str, payload: Dict,
                              headers: Dict[str, str]):
        return self._request("POST", f"/jda/staging-windows/{window_id}/decision",
                             payload, headers)

    def close_staging_window(self, window_id: str, headers: Dict[str, str],
                             payload: Optional[Dict] = None):
        return self._request("POST", f"/jda/staging-windows/{window_id}/close",
                             payload if payload is not None else {}, headers)

    # ---------------------------------------------------- maintenance charges
    def create_maintenance_charge(self, facility_id: str, payload: Dict,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/jda/shared-facilities/{facility_id}/maintenance-charges",
            payload, headers)

    def list_facility_maintenance_charges(self, facility_id: str,
                                          headers: Dict[str, str],
                                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"/jda/shared-facilities/{facility_id}/maintenance-charges",
            headers=headers, params=params)

    def list_agreement_maintenance_charges(self, agreement_id: str,
                                           headers: Dict[str, str],
                                           params: Optional[Dict] = None):
        return self._request("GET",
                             f"/jda/agreements/{agreement_id}/maintenance-charges",
                             headers=headers, params=params)

    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload: Dict, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ raw helpers
    def get_path(self, path: str, headers: Dict[str, str],
                 params: Optional[Dict] = None):
        """Escape hatch for reading an arbitrary declared path."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
