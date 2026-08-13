"""API client: one method per endpoint defined in the PRD endpoint catalogue."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/stewardship/_clock/set_current_utc", payload, headers)

    # --- Hospitals ---
    def create_hospital(self, payload, headers):
        return self._request("POST", "/stewardship/hospitals", payload, headers)

    def get_hospital(self, hospital_id, headers):
        return self._request("GET", f"/stewardship/hospitals/{hospital_id}", headers=headers)

    def list_hospitals(self, headers, params=None):
        return self._request("GET", "/stewardship/hospitals", headers=headers, params=params)

    # --- Practitioners ---
    def create_practitioner(self, payload, headers):
        return self._request("POST", "/stewardship/practitioners", payload, headers)

    def get_practitioner(self, practitioner_id, headers):
        return self._request("GET", f"/stewardship/practitioners/{practitioner_id}", headers=headers)

    def list_practitioners(self, headers, params=None):
        return self._request("GET", "/stewardship/practitioners", headers=headers, params=params)

    def patch_practitioner(self, practitioner_id, payload, headers):
        return self._request("PATCH", f"/stewardship/practitioners/{practitioner_id}", payload, headers)

    # --- Patient cases ---
    def create_patient_case(self, payload, headers):
        return self._request("POST", "/stewardship/patient-cases", payload, headers)

    def get_patient_case(self, patient_case_id, headers):
        return self._request("GET", f"/stewardship/patient-cases/{patient_case_id}", headers=headers)

    def list_patient_cases(self, headers, params=None):
        return self._request("GET", "/stewardship/patient-cases", headers=headers, params=params)

    def discharge_patient_case(self, patient_case_id, headers):
        return self._request("POST", f"/stewardship/patient-cases/{patient_case_id}/discharge", {}, headers)

    # --- Antimicrobials ---
    def create_antimicrobial(self, payload, headers):
        return self._request("POST", "/stewardship/antimicrobials", payload, headers)

    def get_antimicrobial(self, antimicrobial_id, headers):
        return self._request("GET", f"/stewardship/antimicrobials/{antimicrobial_id}", headers=headers)

    def list_antimicrobials(self, headers, params=None):
        return self._request("GET", "/stewardship/antimicrobials", headers=headers, params=params)

    def patch_antimicrobial(self, antimicrobial_id, payload, headers):
        return self._request("PATCH", f"/stewardship/antimicrobials/{antimicrobial_id}", payload, headers)

    # --- Allergy assessments ---
    def create_allergy_assessment(self, payload, headers):
        return self._request("POST", "/stewardship/allergy-assessments", payload, headers)

    def get_allergy_assessment(self, assessment_id, headers):
        return self._request("GET", f"/stewardship/allergy-assessments/{assessment_id}", headers=headers)

    def list_allergy_assessments(self, headers, params=None):
        return self._request("GET", "/stewardship/allergy-assessments", headers=headers, params=params)

    def schedule_allergy_test(self, assessment_id, headers):
        return self._request("POST", f"/stewardship/allergy-assessments/{assessment_id}/schedule-test", {}, headers)

    def record_allergy_result(self, assessment_id, payload, headers):
        return self._request("POST", f"/stewardship/allergy-assessments/{assessment_id}/record-result", payload, headers)

    def withdraw_allergy_assessment(self, assessment_id, headers):
        return self._request("POST", f"/stewardship/allergy-assessments/{assessment_id}/withdraw", {}, headers)

    # --- Culture reports & susceptibility ---
    def create_culture_report(self, payload, headers):
        return self._request("POST", "/stewardship/culture-reports", payload, headers)

    def get_culture_report(self, culture_id, headers):
        return self._request("GET", f"/stewardship/culture-reports/{culture_id}", headers=headers)

    def list_culture_reports(self, headers, params=None):
        return self._request("GET", "/stewardship/culture-reports", headers=headers, params=params)

    def finalize_culture_report(self, culture_id, headers):
        return self._request("POST", f"/stewardship/culture-reports/{culture_id}/finalize", {}, headers)

    def create_susceptibility_result(self, culture_id, payload, headers):
        return self._request("POST", f"/stewardship/culture-reports/{culture_id}/susceptibility-results", payload, headers)

    def list_culture_susceptibility_results(self, culture_id, headers):
        return self._request("GET", f"/stewardship/culture-reports/{culture_id}/susceptibility-results", headers=headers)

    def list_susceptibility_results(self, headers, params=None):
        return self._request("GET", "/stewardship/susceptibility-results", headers=headers, params=params)

    def get_susceptibility_result(self, result_id, headers):
        return self._request("GET", f"/stewardship/susceptibility-results/{result_id}", headers=headers)

    def recommend_for_culture(self, culture_id, headers):
        return self._request("POST", f"/stewardship/culture-reports/{culture_id}/recommend", {}, headers)

    # --- Antibiotic orders ---
    def create_antibiotic_order(self, payload, headers):
        return self._request("POST", "/stewardship/antibiotic-orders", payload, headers)

    def get_antibiotic_order(self, order_id, headers):
        return self._request("GET", f"/stewardship/antibiotic-orders/{order_id}", headers=headers)

    def list_antibiotic_orders(self, headers, params=None):
        return self._request("GET", "/stewardship/antibiotic-orders", headers=headers, params=params)

    def record_administration(self, order_id, payload, headers):
        return self._request("POST", f"/stewardship/antibiotic-orders/{order_id}/administrations", payload, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/stewardship/antibiotic-orders/{order_id}/complete", {}, headers)

    def discontinue_order(self, order_id, headers):
        return self._request("POST", f"/stewardship/antibiotic-orders/{order_id}/discontinue", {}, headers)

    # --- Approval requests ---
    def create_approval_request(self, payload, headers):
        return self._request("POST", "/stewardship/approval-requests", payload, headers)

    def get_approval_request(self, request_id, headers):
        return self._request("GET", f"/stewardship/approval-requests/{request_id}", headers=headers)

    def list_approval_requests(self, headers, params=None):
        return self._request("GET", "/stewardship/approval-requests", headers=headers, params=params)

    def decide_approval_request(self, request_id, payload, headers):
        return self._request("POST", f"/stewardship/approval-requests/{request_id}/decide", payload, headers)

    def escalate_approval_request(self, request_id, payload, headers):
        return self._request("POST", f"/stewardship/approval-requests/{request_id}/escalate", payload, headers)

    def withdraw_approval_request(self, request_id, payload, headers):
        return self._request("POST", f"/stewardship/approval-requests/{request_id}/withdraw", payload, headers)

    # --- Audit interventions ---
    def create_audit_intervention(self, payload, headers):
        return self._request("POST", "/stewardship/audit-interventions", payload, headers)

    def get_audit_intervention(self, intervention_id, headers):
        return self._request("GET", f"/stewardship/audit-interventions/{intervention_id}", headers=headers)

    def list_audit_interventions(self, headers, params=None):
        return self._request("GET", "/stewardship/audit-interventions", headers=headers, params=params)

    def issue_audit_intervention(self, intervention_id, headers):
        return self._request("POST", f"/stewardship/audit-interventions/{intervention_id}/issue", {}, headers)

    def respond_audit_intervention(self, intervention_id, payload, headers):
        return self._request("POST", f"/stewardship/audit-interventions/{intervention_id}/respond", payload, headers)

    def appeal_audit_intervention(self, intervention_id, payload, headers):
        return self._request("POST", f"/stewardship/audit-interventions/{intervention_id}/appeal", payload, headers)

    def adjudicate_audit_intervention(self, intervention_id, payload, headers):
        return self._request("POST", f"/stewardship/audit-interventions/{intervention_id}/adjudicate", payload, headers)

    # --- Conversion opportunities ---
    def detect_conversion_opportunity(self, payload, headers):
        return self._request("POST", "/stewardship/conversion-opportunities/detect", payload, headers)

    def get_conversion_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/stewardship/conversion-opportunities/{opportunity_id}", headers=headers)

    def list_conversion_opportunities(self, headers, params=None):
        return self._request("GET", "/stewardship/conversion-opportunities", headers=headers, params=params)

    def accept_conversion_opportunity(self, opportunity_id, payload, headers):
        return self._request("POST", f"/stewardship/conversion-opportunities/{opportunity_id}/accept", payload, headers)

    def decline_conversion_opportunity(self, opportunity_id, payload, headers):
        return self._request("POST", f"/stewardship/conversion-opportunities/{opportunity_id}/decline", payload, headers)

    # --- Antibiograms ---
    def create_antibiogram(self, payload, headers):
        return self._request("POST", "/stewardship/antibiograms", payload, headers)

    def get_antibiogram(self, antibiogram_id, headers):
        return self._request("GET", f"/stewardship/antibiograms/{antibiogram_id}", headers=headers)

    def list_antibiograms(self, headers, params=None):
        return self._request("GET", "/stewardship/antibiograms", headers=headers, params=params)

    def list_antibiogram_rows_for(self, antibiogram_id, headers):
        return self._request("GET", f"/stewardship/antibiograms/{antibiogram_id}/rows", headers=headers)

    def list_antibiogram_rows(self, headers, params=None):
        return self._request("GET", "/stewardship/antibiogram-rows", headers=headers, params=params)

    def get_antibiogram_row(self, row_id, headers):
        return self._request("GET", f"/stewardship/antibiogram-rows/{row_id}", headers=headers)

    def publish_antibiogram(self, antibiogram_id, payload, headers):
        return self._request("POST", f"/stewardship/antibiograms/{antibiogram_id}/publish", payload, headers)

    # --- Empiric guidelines ---
    def create_empiric_guideline(self, payload, headers):
        return self._request("POST", "/stewardship/empiric-guidelines", payload, headers)

    def get_empiric_guideline(self, guideline_id, headers):
        return self._request("GET", f"/stewardship/empiric-guidelines/{guideline_id}", headers=headers)

    def list_empiric_guidelines(self, headers, params=None):
        return self._request("GET", "/stewardship/empiric-guidelines", headers=headers, params=params)

    def adopt_empiric_guideline(self, guideline_id, payload, headers):
        return self._request("POST", f"/stewardship/empiric-guidelines/{guideline_id}/adopt", payload, headers)

    def retire_empiric_guideline(self, guideline_id, headers):
        return self._request("POST", f"/stewardship/empiric-guidelines/{guideline_id}/retire", {}, headers)

    # --- DOT metric snapshots ---
    def create_dot_snapshot(self, payload, headers):
        return self._request("POST", "/stewardship/dot-snapshots", payload, headers)

    def get_dot_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/stewardship/dot-snapshots/{snapshot_id}", headers=headers)

    def list_dot_snapshots(self, headers, params=None):
        return self._request("GET", "/stewardship/dot-snapshots", headers=headers, params=params)

    def finalize_dot_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/stewardship/dot-snapshots/{snapshot_id}/finalize", {}, headers)

    def reopen_dot_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/stewardship/dot-snapshots/{snapshot_id}/reopen", {}, headers)

    # --- Regulatory reports ---
    def create_regulatory_report(self, payload, headers):
        return self._request("POST", "/stewardship/regulatory-reports", payload, headers)

    def get_regulatory_report(self, report_id, headers):
        return self._request("GET", f"/stewardship/regulatory-reports/{report_id}", headers=headers)

    def list_regulatory_reports(self, headers, params=None):
        return self._request("GET", "/stewardship/regulatory-reports", headers=headers, params=params)

    def submit_regulatory_report(self, report_id, headers):
        return self._request("POST", f"/stewardship/regulatory-reports/{report_id}/submit", {}, headers)

    def acknowledge_regulatory_report(self, report_id, payload, headers):
        return self._request("POST", f"/stewardship/regulatory-reports/{report_id}/acknowledge", payload, headers)


api_client = ApiClient()
