"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Facility ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def license_action(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/license-action", payload, headers=headers)

    # ---- Unit ----
    def create_unit(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/units", payload, headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def mark_clean_unit(self, facility_id, unit_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/units/{unit_id}/mark-clean", {}, headers=headers)

    def retire_unit(self, facility_id, unit_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/units/{unit_id}/retire", {}, headers=headers)

    # ---- Resident ----
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/residents", headers=headers, params=params)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    def admit_resident(self, resident_id, headers):
        return self._request("POST", f"/residents/{resident_id}/admit", {}, headers=headers)

    def initiate_discharge(self, resident_id, headers):
        return self._request("POST", f"/residents/{resident_id}/initiate-discharge", {}, headers=headers)

    def rescind_discharge(self, resident_id, headers):
        return self._request("POST", f"/residents/{resident_id}/rescind-discharge", {}, headers=headers)

    def finalize_discharge(self, resident_id, payload, headers):
        return self._request("POST", f"/residents/{resident_id}/finalize-discharge", payload, headers=headers)

    # ---- Assessment ----
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def finalize_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/assessments/{assessment_id}/finalize", payload, headers=headers)

    # ---- CarePlan ----
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/care-plans", payload, headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/care-plans", headers=headers, params=params)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/care-plans/{care_plan_id}", headers=headers)

    def activate_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/activate", {}, headers=headers)

    # ---- MedicationOrder + eMAR ----
    def create_medication_order(self, payload, headers):
        return self._request("POST", "/medication-orders", payload, headers=headers)

    def list_medication_orders(self, headers, params=None):
        return self._request("GET", "/medication-orders", headers=headers, params=params)

    def get_medication_order(self, medication_order_id, headers):
        return self._request("GET", f"/medication-orders/{medication_order_id}", headers=headers)

    def discontinue_medication_order(self, medication_order_id, headers):
        return self._request("POST", f"/medication-orders/{medication_order_id}/discontinue", {}, headers=headers)

    def record_administration(self, medication_order_id, payload, headers):
        return self._request("POST", f"/medication-orders/{medication_order_id}/administrations", payload, headers=headers)

    def list_administrations(self, headers, params=None):
        return self._request("GET", "/administrations", headers=headers, params=params)

    def get_administration(self, administration_id, headers):
        return self._request("GET", f"/administrations/{administration_id}", headers=headers)

    # ---- MoveInAgreement ----
    def create_move_in_agreement(self, payload, headers):
        return self._request("POST", "/move-in-agreements", payload, headers=headers)

    def list_move_in_agreements(self, headers, params=None):
        return self._request("GET", "/move-in-agreements", headers=headers, params=params)

    def get_move_in_agreement(self, agreement_id, headers):
        return self._request("GET", f"/move-in-agreements/{agreement_id}", headers=headers)

    def activate_move_in_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/move-in-agreements/{agreement_id}/activate", payload, headers=headers)

    def cancel_move_in_agreement(self, agreement_id, headers):
        return self._request("POST", f"/move-in-agreements/{agreement_id}/cancel", {}, headers=headers)

    # ---- BillingStatement ----
    def create_billing_statement(self, payload, headers):
        return self._request("POST", "/billing-statements", payload, headers=headers)

    def list_billing_statements(self, headers, params=None):
        return self._request("GET", "/billing-statements", headers=headers, params=params)

    def get_billing_statement(self, statement_id, headers):
        return self._request("GET", f"/billing-statements/{statement_id}", headers=headers)

    def issue_billing_statement(self, statement_id, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/issue", {}, headers=headers)

    def record_payment(self, statement_id, payload, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/payments", payload, headers=headers)

    def void_billing_statement(self, statement_id, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/void", {}, headers=headers)

    # ---- IncidentReport ----
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers=headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def investigate_incident(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/investigate", {}, headers=headers)

    def resolve_incident(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/resolve", {}, headers=headers)

    def escalate_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/escalate", payload, headers=headers)

    # ---- SurveyDeficiency ----
    def create_deficiency(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/deficiencies", payload, headers=headers)

    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/deficiencies", headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/deficiencies/{deficiency_id}", headers=headers)

    def submit_poc(self, facility_id, deficiency_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/deficiencies/{deficiency_id}/submit-poc", payload, headers=headers)

    def review_poc(self, facility_id, deficiency_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/deficiencies/{deficiency_id}/review-poc", payload, headers=headers)

    def mark_corrected(self, facility_id, deficiency_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/deficiencies/{deficiency_id}/mark-corrected", {}, headers=headers)


api_client = ApiClient()
