"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pathology/_clock/set_current_utc", payload, headers)

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/pathology/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/pathology/patients/{patient_id}", headers=headers)

    # --- Pathologists & coverage windows ---
    def create_pathologist(self, payload, headers):
        return self._request("POST", "/pathology/pathologists", payload, headers)

    def get_pathologist(self, pathologist_id, headers):
        return self._request("GET", f"/pathology/pathologists/{pathologist_id}", headers=headers)

    def create_coverage_window(self, pathologist_id, payload, headers):
        return self._request("POST", f"/pathology/pathologists/{pathologist_id}/coverage-windows", payload, headers)

    def list_coverage_windows(self, pathologist_id, headers, params=None):
        return self._request("GET", f"/pathology/pathologists/{pathologist_id}/coverage-windows", headers=headers, params=params)

    def cancel_coverage_window(self, window_id, headers):
        return self._request("POST", f"/pathology/coverage-windows/{window_id}/cancel", headers=headers)

    # --- Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/pathology/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/pathology/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/pathology/cases", headers=headers, params=params)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/assign", payload, headers)

    def reassign_case(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/reassign", payload, headers)

    def submit_for_signout(self, case_id, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/submit-for-signout", headers=headers)

    def sign_out_case(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/sign-out", payload, headers)

    def amend_case(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/amend", payload, headers)

    def amend_sign(self, case_id, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/amend/sign", headers=headers)

    def amend_cancel(self, case_id, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/amend/cancel", headers=headers)

    def cancel_case(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/cancel", payload, headers)

    # --- Specimens ---
    def accession_specimen(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/specimens", payload, headers)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/pathology/specimens/{specimen_id}", headers=headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/pathology/specimens", headers=headers, params=params)

    def reject_specimen(self, specimen_id, payload, headers):
        return self._request("POST", f"/pathology/specimens/{specimen_id}/reject", payload, headers)

    def gross_specimen(self, specimen_id, payload, headers):
        return self._request("POST", f"/pathology/specimens/{specimen_id}/gross", payload, headers)

    def dispose_wet_tissue(self, specimen_id, headers):
        return self._request("POST", f"/pathology/specimens/{specimen_id}/dispose-wet-tissue", headers=headers)

    # --- Blocks ---
    def create_block(self, specimen_id, payload, headers):
        return self._request("POST", f"/pathology/specimens/{specimen_id}/blocks", payload, headers)

    def get_block(self, block_id, headers):
        return self._request("GET", f"/pathology/blocks/{block_id}", headers=headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", "/pathology/blocks", headers=headers, params=params)

    def embed_block(self, block_id, headers):
        return self._request("POST", f"/pathology/blocks/{block_id}/embed", headers=headers)

    # --- Slides ---
    def create_slide(self, block_id, payload, headers):
        return self._request("POST", f"/pathology/blocks/{block_id}/slides", payload, headers)

    def get_slide(self, slide_id, headers):
        return self._request("GET", f"/pathology/slides/{slide_id}", headers=headers)

    def list_slides(self, headers, params=None):
        return self._request("GET", "/pathology/slides", headers=headers, params=params)

    def section_slide(self, slide_id, payload, headers):
        return self._request("POST", f"/pathology/slides/{slide_id}/section", payload, headers)

    def stain_complete_slide(self, slide_id, headers):
        return self._request("POST", f"/pathology/slides/{slide_id}/stain-complete", headers=headers)

    def qc_review_slide(self, slide_id, payload, headers):
        return self._request("POST", f"/pathology/slides/{slide_id}/qc-review", payload, headers)

    def recut_slide(self, slide_id, payload, headers):
        return self._request("POST", f"/pathology/slides/{slide_id}/recut", payload, headers)

    # --- Stain orders & reflex rules ---
    def create_stain_order(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/stain-orders", payload, headers)

    def get_stain_order(self, order_id, headers):
        return self._request("GET", f"/pathology/stain-orders/{order_id}", headers=headers)

    def list_stain_orders(self, headers, params=None):
        return self._request("GET", "/pathology/stain-orders", headers=headers, params=params)

    def start_stain_order(self, order_id, headers):
        return self._request("POST", f"/pathology/stain-orders/{order_id}/start", headers=headers)

    def result_stain_order(self, order_id, payload, headers):
        return self._request("POST", f"/pathology/stain-orders/{order_id}/result", payload, headers)

    def cancel_stain_order(self, order_id, headers):
        return self._request("POST", f"/pathology/stain-orders/{order_id}/cancel", headers=headers)

    def create_reflex_rule(self, payload, headers):
        return self._request("POST", "/pathology/reflex-rules", payload, headers)

    def get_reflex_rule(self, rule_id, headers):
        return self._request("GET", f"/pathology/reflex-rules/{rule_id}", headers=headers)

    def list_reflex_rules(self, headers, params=None):
        return self._request("GET", "/pathology/reflex-rules", headers=headers, params=params)

    def update_reflex_rule(self, rule_id, payload, headers):
        return self._request("PUT", f"/pathology/reflex-rules/{rule_id}", payload, headers)

    def deactivate_reflex_rule(self, rule_id, headers):
        return self._request("POST", f"/pathology/reflex-rules/{rule_id}/deactivate", headers=headers)

    # --- Reports ---
    def get_report(self, report_id, headers):
        return self._request("GET", f"/pathology/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/pathology/reports", headers=headers, params=params)

    # --- Consultations ---
    def create_consultation(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/consultations", payload, headers)

    def get_consultation(self, consultation_id, headers):
        return self._request("GET", f"/pathology/consultations/{consultation_id}", headers=headers)

    def list_consultations(self, headers, params=None):
        return self._request("GET", "/pathology/consultations", headers=headers, params=params)

    def accept_consultation(self, consultation_id, headers):
        return self._request("POST", f"/pathology/consultations/{consultation_id}/accept", headers=headers)

    def decline_consultation(self, consultation_id, payload, headers):
        return self._request("POST", f"/pathology/consultations/{consultation_id}/decline", payload, headers)

    def answer_consultation(self, consultation_id, payload, headers):
        return self._request("POST", f"/pathology/consultations/{consultation_id}/answer", payload, headers)

    def incorporate_consultation(self, consultation_id, headers):
        return self._request("POST", f"/pathology/consultations/{consultation_id}/incorporate", headers=headers)

    def reroute_consultation(self, consultation_id, payload, headers):
        return self._request("POST", f"/pathology/consultations/{consultation_id}/reroute", payload, headers)

    # --- Discrepancies ---
    def create_discrepancy(self, case_id, payload, headers):
        return self._request("POST", f"/pathology/cases/{case_id}/discrepancies", payload, headers)

    def get_discrepancy(self, discrepancy_id, headers):
        return self._request("GET", f"/pathology/discrepancies/{discrepancy_id}", headers=headers)

    def list_discrepancies(self, headers, params=None):
        return self._request("GET", "/pathology/discrepancies", headers=headers, params=params)

    def acknowledge_discrepancy(self, discrepancy_id, headers):
        return self._request("POST", f"/pathology/discrepancies/{discrepancy_id}/acknowledge", headers=headers)

    def resolve_discrepancy(self, discrepancy_id, payload, headers):
        return self._request("POST", f"/pathology/discrepancies/{discrepancy_id}/resolve", payload, headers)

    # --- Release requests ---
    def create_release_request(self, payload, headers):
        return self._request("POST", "/pathology/release-requests", payload, headers)

    def get_release_request(self, request_id, headers):
        return self._request("GET", f"/pathology/release-requests/{request_id}", headers=headers)

    def list_release_requests(self, headers, params=None):
        return self._request("GET", "/pathology/release-requests", headers=headers, params=params)

    def approve_release_request(self, request_id, headers):
        return self._request("POST", f"/pathology/release-requests/{request_id}/approve", headers=headers)

    def deny_release_request(self, request_id, payload, headers):
        return self._request("POST", f"/pathology/release-requests/{request_id}/deny", payload, headers)

    def ship_release_request(self, request_id, headers):
        return self._request("POST", f"/pathology/release-requests/{request_id}/ship", headers=headers)

    def return_release_request(self, request_id, headers):
        return self._request("POST", f"/pathology/release-requests/{request_id}/return", headers=headers)


api_client = ApiClient()
