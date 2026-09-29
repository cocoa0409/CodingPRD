"""Typed endpoint wrapper for the contractor safety prequalification API.

One method per endpoint. Every method returns the raw response so tests can
assert on status codes as well as bodies.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class SafetyPrequalApiClient(GenericApiClient):
    """Endpoint methods for every operation the specification declares."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Clients and sites
    # ------------------------------------------------------------------

    def create_client(self, payload: dict, headers: dict):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: dict):
        return self._request("GET", f"/clients/{client_id}", None, headers)

    def create_site(self, client_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/clients/{client_id}/sites", payload, headers)

    def list_client_sites(self, client_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/clients/{client_id}/sites", None, headers, params)

    def get_site(self, site_id: str, headers: dict):
        return self._request("GET", f"/sites/{site_id}", None, headers)

    # ------------------------------------------------------------------
    # Contractors, workers and qualifications
    # ------------------------------------------------------------------

    def create_contractor(self, payload: dict, headers: dict):
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id: str, headers: dict):
        return self._request("GET", f"/contractors/{contractor_id}", None, headers)

    def patch_contractor(self, contractor_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/contractors/{contractor_id}", payload, headers)

    def create_worker(self, contractor_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/contractors/{contractor_id}/workers", payload, headers
        )

    def list_workers(self, contractor_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/contractors/{contractor_id}/workers", None, headers, params
        )

    def get_worker(self, worker_id: str, headers: dict):
        return self._request("GET", f"/workers/{worker_id}", None, headers)

    def create_qualification(self, worker_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/workers/{worker_id}/qualifications", payload, headers
        )

    def list_qualifications(self, worker_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/workers/{worker_id}/qualifications", None, headers, params
        )

    # ------------------------------------------------------------------
    # Insurance certificates
    # ------------------------------------------------------------------

    def create_certificate(self, contractor_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/contractors/{contractor_id}/insurance-certificates", payload, headers
        )

    def list_certificates(self, contractor_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/contractors/{contractor_id}/insurance-certificates",
            None,
            headers,
            params,
        )

    def verify_certificate(self, certificate_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/insurance-certificates/{certificate_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Prequalifications
    # ------------------------------------------------------------------

    def create_prequalification(self, payload: dict, headers: dict):
        return self._request("POST", "/prequalifications", payload, headers)

    def list_prequalifications(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/prequalifications", None, headers, params)

    def get_prequalification(self, prequalification_id: str, headers: dict):
        return self._request(
            "GET", f"/prequalifications/{prequalification_id}", None, headers
        )

    def submit_prequalification(self, prequalification_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/prequalifications/{prequalification_id}/submit", payload, headers
        )

    def grade_prequalification(self, prequalification_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/prequalifications/{prequalification_id}/grade", payload, headers
        )

    def get_scorecard(self, prequalification_id: str, headers: dict):
        return self._request(
            "GET", f"/prequalifications/{prequalification_id}/scorecard", None, headers
        )

    def record_audit_findings(self, prequalification_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/prequalifications/{prequalification_id}/audit-findings",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Safety statistics
    # ------------------------------------------------------------------

    def create_statistic(self, prequalification_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/prequalifications/{prequalification_id}/safety-statistics",
            payload,
            headers,
        )

    def list_statistics(
        self, prequalification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/prequalifications/{prequalification_id}/safety-statistics",
            None,
            headers,
            params,
        )

    def verify_statistic(self, statistic_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/safety-statistics/{statistic_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Written programs
    # ------------------------------------------------------------------

    def create_program(self, prequalification_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/prequalifications/{prequalification_id}/written-programs",
            payload,
            headers,
        )

    def list_programs(
        self, prequalification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/prequalifications/{prequalification_id}/written-programs",
            None,
            headers,
            params,
        )

    def review_program(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/written-programs/{program_id}/review", payload, headers
        )

    def resubmit_program(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/written-programs/{program_id}/resubmit", payload, headers
        )

    # ------------------------------------------------------------------
    # Improvement plans
    # ------------------------------------------------------------------

    def create_improvement_plan(self, prequalification_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/prequalifications/{prequalification_id}/improvement-plans",
            payload,
            headers,
        )

    def list_improvement_plans(
        self, prequalification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/prequalifications/{prequalification_id}/improvement-plans",
            None,
            headers,
            params,
        )

    def submit_improvement_plan(self, plan_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/improvement-plans/{plan_id}/submit", payload, headers
        )

    def decide_improvement_plan(self, plan_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/improvement-plans/{plan_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Variances
    # ------------------------------------------------------------------

    def create_variance(self, prequalification_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/prequalifications/{prequalification_id}/variances",
            payload,
            headers,
        )

    def list_variances(
        self, prequalification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/prequalifications/{prequalification_id}/variances",
            None,
            headers,
            params,
        )

    def decide_variance(self, variance_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/variances/{variance_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Site access grants
    # ------------------------------------------------------------------

    def create_grant(self, payload: dict, headers: dict):
        return self._request("POST", "/site-access-grants", payload, headers)

    def list_grants(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/site-access-grants", None, headers, params)

    def get_grant(self, grant_id: str, headers: dict):
        return self._request("GET", f"/site-access-grants/{grant_id}", None, headers)

    def revoke_grant(self, grant_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/site-access-grants/{grant_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------

    def create_incident(self, payload: dict, headers: dict):
        return self._request("POST", "/incident-reports", payload, headers)

    def list_incidents(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/incident-reports", None, headers, params)

    def get_incident(self, incident_id: str, headers: dict):
        return self._request("GET", f"/incident-reports/{incident_id}", None, headers)

    def close_incident_review(self, incident_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/close-review", payload, headers
        )

    # ------------------------------------------------------------------
    # Subcontractor links
    # ------------------------------------------------------------------

    def create_link(self, payload: dict, headers: dict):
        return self._request("POST", "/subcontractor-links", payload, headers)

    def list_links(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/subcontractor-links", None, headers, params)

    def get_link(self, link_id: str, headers: dict):
        return self._request("GET", f"/subcontractor-links/{link_id}", None, headers)

    def terminate_link(self, link_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/subcontractor-links/{link_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Periodic runs
    # ------------------------------------------------------------------

    def run_requalification(self, client_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/clients/{client_id}/requalification-runs", payload, headers
        )

    def run_audit_sampling(self, client_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/clients/{client_id}/audit-sampling-runs", payload, headers
        )
