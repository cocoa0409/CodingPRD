"""API client: one method per endpoint of the Point-Of-Care Testing Oversight API."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/poct"


class ApiClient(GenericApiClient):
    # ── Logical clock ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ── CLIA certificates ──────────────────────────────────────────
    def create_certificate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/certificates/{certificate_id}", headers=headers
        )

    def suspend_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/certificates/{certificate_id}/suspend", payload, headers
        )

    # ── Testing sites ──────────────────────────────────────────────
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def assign_director(self, site_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/sites/{site_id}/director", payload, headers
        )

    def get_site_readiness(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sites/{site_id}/readiness", headers=headers, params=params
        )

    def list_site_operators(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sites/{site_id}/operators", headers=headers, params=params
        )

    def list_site_devices(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sites/{site_id}/devices", headers=headers, params=params
        )

    def list_site_storage_units(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sites/{site_id}/storage-units",
            headers=headers, params=params,
        )

    def list_site_inspections(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sites/{site_id}/inspections",
            headers=headers, params=params,
        )

    def list_site_pt_enrollments(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sites/{site_id}/pt-enrollments",
            headers=headers, params=params,
        )

    # ── Certificate coverage ───────────────────────────────────────
    def create_coverage(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/certificate-coverages", payload, headers
        )

    def get_coverage(self, coverage_id, headers):
        return self._request(
            "GET", f"{PREFIX}/certificate-coverages/{coverage_id}", headers=headers
        )

    def list_coverages(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/certificate-coverages", headers=headers, params=params
        )

    # ── Operators ──────────────────────────────────────────────────
    def create_operator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request(
            "GET", f"{PREFIX}/operators/{operator_id}", headers=headers
        )

    def list_operators(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/operators", headers=headers, params=params
        )

    def record_training(self, operator_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/operators/{operator_id}/training", payload, headers
        )

    def reinstate_access(self, operator_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/operators/{operator_id}/access-reinstatement",
            payload, headers,
        )

    # ── Competency assessments ─────────────────────────────────────
    def create_assessment(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competency-assessments", payload, headers
        )

    def get_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/competency-assessments/{assessment_id}", headers=headers
        )

    def list_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/competency-assessments", headers=headers, params=params
        )

    def decide_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competency-assessments/{assessment_id}/decision",
            payload, headers,
        )

    # ── Instruments ────────────────────────────────────────────────
    def create_device(self, payload, headers):
        return self._request("POST", f"{PREFIX}/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"{PREFIX}/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/devices", headers=headers, params=params)

    def qc_unlock_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/qc-unlock", payload, headers
        )

    def retire_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/retire", payload, headers
        )

    # ── Storage units and temperature readings ─────────────────────
    def create_storage_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storage-units", payload, headers)

    def get_storage_unit(self, storage_unit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/storage-units/{storage_unit_id}", headers=headers
        )

    def list_storage_units(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/storage-units", headers=headers, params=params
        )

    def create_temperature_reading(self, storage_unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/storage-units/{storage_unit_id}/temperature-readings",
            payload, headers,
        )

    def list_temperature_readings(self, storage_unit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/storage-units/{storage_unit_id}/temperature-readings",
            headers=headers, params=params,
        )

    def resolve_excursion(self, storage_unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/storage-units/{storage_unit_id}/excursion-resolution",
            payload, headers,
        )

    # ── Reagent lots ───────────────────────────────────────────────
    def create_reagent_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reagent-lots", payload, headers)

    def get_reagent_lot(self, lot_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reagent-lots/{lot_id}", headers=headers
        )

    def list_reagent_lots(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reagent-lots", headers=headers, params=params
        )

    def verify_reagent_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reagent-lots/{lot_id}/verify", payload, headers
        )

    # ── Control runs ───────────────────────────────────────────────
    def create_qc_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/qc-runs", payload, headers)

    def get_qc_run(self, qc_run_id, headers):
        return self._request("GET", f"{PREFIX}/qc-runs/{qc_run_id}", headers=headers)

    def list_qc_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/qc-runs", headers=headers, params=params)

    # ── Patient results ────────────────────────────────────────────
    def create_test_result(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-results", payload, headers)

    def get_test_result(self, result_id, headers):
        return self._request(
            "GET", f"{PREFIX}/test-results/{result_id}", headers=headers
        )

    def list_test_results(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/test-results", headers=headers, params=params
        )

    def post_test_result(self, result_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/test-results/{result_id}/post", payload, headers
        )

    def correct_test_result(self, result_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/test-results/{result_id}/correct", payload, headers
        )

    # ── Proficiency testing ────────────────────────────────────────
    def create_pt_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pt-enrollments", payload, headers)

    def get_pt_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pt-enrollments/{enrollment_id}", headers=headers
        )

    def list_pt_enrollments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pt-enrollments", headers=headers, params=params
        )

    def create_pt_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pt-events", payload, headers)

    def get_pt_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pt-events/{event_id}", headers=headers
        )

    def list_pt_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pt-events", headers=headers, params=params
        )

    def score_pt_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pt-events/{event_id}/score", payload, headers
        )

    def submit_pt_investigation(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pt-events/{event_id}/investigation", payload, headers
        )

    def decide_pt_investigation(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pt-events/{event_id}/investigation-decision",
            payload, headers,
        )

    # ── Surveys and deficiency findings ────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspections", headers=headers, params=params
        )

    def issue_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/issue", payload, headers
        )

    def rescind_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/rescind", payload, headers
        )

    def create_deficiency(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deficiencies", payload, headers)

    def get_deficiency(self, finding_id, headers):
        return self._request(
            "GET", f"{PREFIX}/deficiencies/{finding_id}", headers=headers
        )

    def list_deficiencies(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/deficiencies", headers=headers, params=params
        )

    def submit_correction(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deficiencies/{finding_id}/correction", payload, headers
        )

    def decide_correction(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deficiencies/{finding_id}/correction-decision",
            payload, headers,
        )

    # ── Oversight epoch ────────────────────────────────────────────
    def create_oversight_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/oversight-runs", payload, headers)


api_client = ApiClient()
