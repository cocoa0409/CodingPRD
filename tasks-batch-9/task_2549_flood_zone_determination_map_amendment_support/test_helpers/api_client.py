"""API client: one method per endpoint defined in the PRD (PRD section 4).

Every path is mounted under the ``/flood-zone`` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/flood-zone"


class ApiClient(GenericApiClient):
    # ---------------- clock ----------------
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers=headers,
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers=headers
        )

    # ---------------- communities ----------------
    def list_communities(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/communities", headers=headers, params=params)

    def get_community(self, community_id, headers=None):
        return self._request("GET", f"{PREFIX}/communities/{community_id}", headers=headers)

    def create_community(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/communities", payload, headers=headers)

    def change_participation(self, community_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/communities/{community_id}/participation-changes",
            payload, headers=headers,
        )

    # ---------------- lenders ----------------
    def list_lenders(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/lenders", headers=headers, params=params)

    def get_lender(self, lender_id, headers=None):
        return self._request("GET", f"{PREFIX}/lenders/{lender_id}", headers=headers)

    def create_lender(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/lenders", payload, headers=headers)

    # ---------------- map panels ----------------
    def list_map_panels(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/map-panels", headers=headers, params=params)

    def get_map_panel(self, map_panel_id, headers=None):
        return self._request("GET", f"{PREFIX}/map-panels/{map_panel_id}", headers=headers)

    def get_impact_analysis(self, map_panel_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/map-panels/{map_panel_id}/impact-analysis", headers=headers
        )

    def create_map_panel(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/map-panels", payload, headers=headers)

    def open_appeal_period(self, map_panel_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/map-panels/{map_panel_id}/appeal-period",
            payload if payload is not None else {}, headers=headers,
        )

    def record_appeal_decision(self, map_panel_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/map-panels/{map_panel_id}/appeal-decision",
            payload, headers=headers,
        )

    def make_panel_effective(self, map_panel_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/map-panels/{map_panel_id}/effective",
            payload if payload is not None else {}, headers=headers,
        )

    # ---------------- properties ----------------
    def list_properties(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/properties", headers=headers, params=params)

    def get_property(self, property_id, headers=None):
        return self._request("GET", f"{PREFIX}/properties/{property_id}", headers=headers)

    def create_property(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/properties", payload, headers=headers)

    def correct_geocode(self, property_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/properties/{property_id}/geocode-corrections",
            payload, headers=headers,
        )

    # ---------------- structures ----------------
    def list_structures(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/structures", headers=headers, params=params)

    def get_structure(self, structure_id, headers=None):
        return self._request("GET", f"{PREFIX}/structures/{structure_id}", headers=headers)

    def create_structure(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/structures", payload, headers=headers)

    # ---------------- loan folios ----------------
    def list_loan_folios(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/loan-folios", headers=headers, params=params)

    def get_loan_folio(self, loan_folio_id, headers=None):
        return self._request("GET", f"{PREFIX}/loan-folios/{loan_folio_id}", headers=headers)

    def create_loan_folio(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/loan-folios", payload, headers=headers)

    def report_insurance(self, loan_folio_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/loan-folios/{loan_folio_id}/insurance-reports",
            payload, headers=headers,
        )

    def force_place(self, loan_folio_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/loan-folios/{loan_folio_id}/force-placements",
            payload if payload is not None else {}, headers=headers,
        )

    # ---------------- determinations ----------------
    def list_determinations(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/determinations", headers=headers, params=params)

    def get_determination(self, determination_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/determinations/{determination_id}", headers=headers
        )

    def create_determination(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/determinations", payload, headers=headers)

    # ---------------- disputes ----------------
    def list_disputes(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers=None):
        return self._request("GET", f"{PREFIX}/disputes/{dispute_id}", headers=headers)

    def create_dispute(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/disputes", payload, headers=headers)

    def provider_review_dispute(self, dispute_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/provider-review", payload, headers=headers
        )

    def agency_review_dispute(self, dispute_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/agency-review", payload, headers=headers
        )

    # ---------------- elevation certificates ----------------
    def list_elevation_certificates(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/elevation-certificates", headers=headers, params=params
        )

    def get_elevation_certificate(self, elevation_certificate_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/elevation-certificates/{elevation_certificate_id}",
            headers=headers,
        )

    def create_elevation_certificate(self, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/elevation-certificates", payload, headers=headers
        )

    def review_elevation_certificate(self, elevation_certificate_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/elevation-certificates/{elevation_certificate_id}/review",
            payload, headers=headers,
        )

    # ---------------- map amendment requests ----------------
    def list_map_amendment_requests(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/map-amendment-requests", headers=headers, params=params
        )

    def get_map_amendment_request(self, map_amendment_request_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/map-amendment-requests/{map_amendment_request_id}",
            headers=headers,
        )

    def create_map_amendment_request(self, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/map-amendment-requests", payload, headers=headers
        )

    def submit_map_amendment_request(self, map_amendment_request_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/map-amendment-requests/{map_amendment_request_id}/submission",
            payload if payload is not None else {}, headers=headers,
        )

    def decide_map_amendment_request(self, map_amendment_request_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/map-amendment-requests/{map_amendment_request_id}/agency-decision",
            payload, headers=headers,
        )

    # ---------------- compliance notices ----------------
    def list_compliance_notices(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/compliance-notices", headers=headers, params=params
        )

    def get_compliance_notice(self, compliance_notice_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/compliance-notices/{compliance_notice_id}", headers=headers
        )

    def create_compliance_notice(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/compliance-notices", payload, headers=headers)

    def acknowledge_compliance_notice(self, compliance_notice_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/compliance-notices/{compliance_notice_id}/acknowledgement",
            payload if payload is not None else {}, headers=headers,
        )

    # ---------------- monitoring runs ----------------
    def run_monitoring(self, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/monitoring-runs",
            payload if payload is not None else {}, headers=headers,
        )


api_client = ApiClient()
