"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def list_patient_immunizations(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/immunizations",
                             headers=headers, params=params)

    def list_patient_allergy_records(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/allergy-records",
                             headers=headers, params=params)

    def list_patient_evaluations(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/evaluations",
                             headers=headers, params=params)

    def list_patient_certificates(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/certificates",
                             headers=headers, params=params)

    # ---- Providers ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ---- Lots ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def list_lot_immunizations(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/immunizations",
                             headers=headers, params=params)

    # ---- Lot recalls ----
    def create_recall(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/recalls", payload, headers)

    def list_recalls(self, lot_id, headers, params=None):
        return self._request("GET", f"/lots/{lot_id}/recalls",
                             headers=headers, params=params)

    def reverse_recall(self, lot_id, recall_id, headers):
        return self._request("POST",
                             f"/lots/{lot_id}/recalls/{recall_id}/reverse",
                             {}, headers)

    # ---- Immunizations ----
    def create_immunization(self, payload, headers):
        return self._request("POST", "/immunizations", payload, headers)

    def get_immunization(self, immunization_id, headers):
        return self._request("GET", f"/immunizations/{immunization_id}",
                             headers=headers)

    def amend_immunization(self, immunization_id, payload, headers):
        return self._request("PATCH", f"/immunizations/{immunization_id}",
                             payload, headers)

    def delete_immunization(self, immunization_id, headers):
        return self._request("DELETE", f"/immunizations/{immunization_id}",
                             headers=headers)

    def list_immunizations(self, headers, params=None):
        return self._request("GET", "/immunizations", headers=headers, params=params)

    # ---- Allergy records ----
    def create_allergy_record(self, payload, headers):
        return self._request("POST", "/allergy-records", payload, headers)

    def get_allergy_record(self, allergy_id, headers):
        return self._request("GET", f"/allergy-records/{allergy_id}",
                             headers=headers)

    def list_allergy_records(self, headers, params=None):
        return self._request("GET", "/allergy-records", headers=headers, params=params)

    # ---- Provider reports ----
    def create_provider_report(self, payload, headers):
        return self._request("POST", "/provider-reports", payload, headers)

    def add_report_line(self, report_id, payload, headers):
        return self._request("POST", f"/provider-reports/{report_id}/lines",
                             payload, headers)

    def get_provider_report(self, report_id, headers):
        return self._request("GET", f"/provider-reports/{report_id}",
                             headers=headers)

    def list_provider_reports(self, headers, params=None):
        return self._request("GET", "/provider-reports", headers=headers, params=params)

    def list_report_immunizations(self, report_id, headers, params=None):
        return self._request("GET", f"/provider-reports/{report_id}/immunizations",
                             headers=headers, params=params)

    def submit_provider_report(self, report_id, headers):
        return self._request("POST", f"/provider-reports/{report_id}/submit",
                             {}, headers)

    def adjudicate_provider_report(self, report_id, headers):
        return self._request("POST", f"/provider-reports/{report_id}/adjudicate",
                             {}, headers)

    # ---- Adverse events ----
    def create_adverse_event(self, payload, headers):
        return self._request("POST", "/adverse-events", payload, headers)

    def get_adverse_event(self, ae_id, headers):
        return self._request("GET", f"/adverse-events/{ae_id}", headers=headers)

    def list_adverse_events(self, headers, params=None):
        return self._request("GET", "/adverse-events", headers=headers, params=params)

    def review_adverse_event(self, ae_id, headers):
        return self._request("POST", f"/adverse-events/{ae_id}/review", {}, headers)

    def confirm_adverse_event(self, ae_id, headers):
        return self._request("POST", f"/adverse-events/{ae_id}/confirm", {}, headers)

    def dismiss_adverse_event(self, ae_id, headers):
        return self._request("POST", f"/adverse-events/{ae_id}/dismiss", {}, headers)

    # ---- Schedule evaluations ----
    def create_evaluation(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/evaluations",
                             payload, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/evaluations/{evaluation_id}", headers=headers)

    # ---- Certificates ----
    def create_certificate(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/certificates",
                             payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}",
                             headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)


api_client = ApiClient()
