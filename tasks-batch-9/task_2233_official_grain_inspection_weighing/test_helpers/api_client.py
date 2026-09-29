"""API client: one method per endpoint defined in the PRD.

All resources except the logical-clock control are mounted under
`/grain-inspection`.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/grain-inspection"


class ApiClient(GenericApiClient):
    """One method per PRD endpoint. Returns the raw response object."""

    # ----------------------------------------------------------------- #
    # Logical clock
    # ----------------------------------------------------------------- #
    def set_current_utc(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----------------------------------------------------------------- #
    # Service areas
    # ----------------------------------------------------------------- #
    def create_service_area(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/service-areas", payload, headers)

    def list_service_areas(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/service-areas", headers=headers, params=params
        )

    def get_service_area(self, service_area_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/service-areas/{service_area_id}", headers=headers
        )

    def update_service_area(self, service_area_id: str, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/service-areas/{service_area_id}", payload, headers
        )

    # ----------------------------------------------------------------- #
    # Fee schedules
    # ----------------------------------------------------------------- #
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/fee-schedules", payload, headers)

    def activate_fee_schedule(self, fee_schedule_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/fee-schedules/{fee_schedule_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def list_fee_schedules(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/fee-schedules", headers=headers, params=params
        )

    def get_fee_schedule(self, fee_schedule_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/fee-schedules/{fee_schedule_id}", headers=headers
        )

    # ----------------------------------------------------------------- #
    # Applicants and payments
    # ----------------------------------------------------------------- #
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/applicants", payload, headers)

    def list_applicants(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/applicants", headers=headers, params=params
        )

    def get_applicant(self, applicant_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/applicants/{applicant_id}", headers=headers
        )

    def record_payment(self, applicant_id: str, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/applicants/{applicant_id}/payments", payload, headers
        )

    # ----------------------------------------------------------------- #
    # Inspectors
    # ----------------------------------------------------------------- #
    def create_inspector(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/inspectors", payload, headers)

    def list_inspectors(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/inspectors", headers=headers, params=params
        )

    def get_inspector(self, inspector_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/inspectors/{inspector_id}", headers=headers
        )

    def activate_inspector(self, inspector_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/inspectors/{inspector_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def suspend_inspector(self, inspector_id: str, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspectors/{inspector_id}/suspend", payload, headers
        )

    def reinstate_inspector(self, inspector_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/inspectors/{inspector_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    def revoke_inspector(self, inspector_id: str, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspectors/{inspector_id}/revoke", payload, headers
        )

    def create_training_record(self, inspector_id: str, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/inspectors/{inspector_id}/training-records",
            payload,
            headers,
        )

    # ----------------------------------------------------------------- #
    # Equipment and the comparison programme
    # ----------------------------------------------------------------- #
    def create_equipment(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/equipment", payload, headers)

    def list_equipment(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/equipment", headers=headers, params=params
        )

    def get_equipment(self, equipment_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/equipment/{equipment_id}", headers=headers
        )

    def certify_equipment(self, equipment_id: str, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/equipment/{equipment_id}/certify", payload, headers
        )

    def create_comparison_check(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/comparison-checks", payload, headers
        )

    # ----------------------------------------------------------------- #
    # Inspection requests
    # ----------------------------------------------------------------- #
    def create_inspection_request(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-requests", payload, headers
        )

    def list_inspection_requests(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/inspection-requests", headers=headers, params=params
        )

    def get_inspection_request(self, inspection_request_id: str, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/inspection-requests/{inspection_request_id}",
            headers=headers,
        )

    def list_request_certificates(
        self, inspection_request_id: str, headers, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/inspection-requests/{inspection_request_id}/certificates",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------------- #
    # Samples
    # ----------------------------------------------------------------- #
    def create_sample(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/samples", payload, headers)

    def list_samples(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/samples", headers=headers, params=params
        )

    def get_sample(self, sample_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/samples/{sample_id}", headers=headers
        )

    def break_seal(self, sample_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/samples/{sample_id}/break-seal",
            payload if payload is not None else {},
            headers,
        )

    # ----------------------------------------------------------------- #
    # Grading determinations
    # ----------------------------------------------------------------- #
    def create_grading_result(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/grading-results", payload, headers)

    def list_grading_results(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/grading-results", headers=headers, params=params
        )

    def get_grading_result(self, grading_result_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/grading-results/{grading_result_id}", headers=headers
        )

    # ----------------------------------------------------------------- #
    # Protein and specialty analyses
    # ----------------------------------------------------------------- #
    def create_protein_analysis(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/protein-analyses", payload, headers
        )

    def recompute_protein_analysis(self, analysis_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/protein-analyses/{analysis_id}/recompute",
            payload if payload is not None else {},
            headers,
        )

    def list_protein_analyses(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/protein-analyses", headers=headers, params=params
        )

    def get_protein_analysis(self, analysis_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/protein-analyses/{analysis_id}", headers=headers
        )

    # ----------------------------------------------------------------- #
    # Weighing records
    # ----------------------------------------------------------------- #
    def create_weighing_record(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/weighing-records", payload, headers
        )

    def supervise_weighing_record(self, weighing_record_id: str, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/weighing-records/{weighing_record_id}/supervise",
            payload,
            headers,
        )

    def list_weighing_records(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/weighing-records", headers=headers, params=params
        )

    def get_weighing_record(self, weighing_record_id: str, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/weighing-records/{weighing_record_id}",
            headers=headers,
        )

    # ----------------------------------------------------------------- #
    # Certificates
    # ----------------------------------------------------------------- #
    def create_certificate(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/certificates", payload, headers)

    def list_certificates(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/certificates", headers=headers, params=params
        )

    def get_certificate(self, certificate_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/certificates/{certificate_id}", headers=headers
        )

    def list_certificate_appeals(
        self, certificate_id: str, headers, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/certificates/{certificate_id}/appeals",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------------- #
    # Appeals, votes
    # ----------------------------------------------------------------- #
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/appeals", payload, headers)

    def assign_appeal_sample(self, appeal_id: str, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/assign-sample", payload, headers
        )

    def decide_appeal(self, appeal_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/appeals/{appeal_id}/decide",
            payload if payload is not None else {},
            headers,
        )

    def dismiss_appeal(self, appeal_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/appeals/{appeal_id}/dismiss",
            payload if payload is not None else {},
            headers,
        )

    def list_appeals(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/appeals", headers=headers, params=params
        )

    def get_appeal(self, appeal_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/appeals/{appeal_id}", headers=headers
        )

    def create_appeal_vote(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/appeal-votes", payload, headers)

    def list_appeal_votes(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/appeal-votes", headers=headers, params=params
        )

    def get_appeal_vote(self, appeal_vote_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/appeal-votes/{appeal_vote_id}", headers=headers
        )

    # ----------------------------------------------------------------- #
    # Vessel watches
    # ----------------------------------------------------------------- #
    def create_vessel_watch(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/vessel-watches", payload, headers)

    def start_vessel_watch(self, vessel_watch_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/vessel-watches/{vessel_watch_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def close_vessel_watch(self, vessel_watch_id: str, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/vessel-watches/{vessel_watch_id}/close",
            payload,
            headers,
        )

    def abort_vessel_watch(self, vessel_watch_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/vessel-watches/{vessel_watch_id}/abort",
            payload if payload is not None else {},
            headers,
        )

    def list_vessel_watches(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/vessel-watches", headers=headers, params=params
        )

    def get_vessel_watch(self, vessel_watch_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/vessel-watches/{vessel_watch_id}", headers=headers
        )


api_client = ApiClient()
