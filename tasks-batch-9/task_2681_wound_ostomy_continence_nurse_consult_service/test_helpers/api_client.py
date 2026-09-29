"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Units ---------------------------------------------------------------
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def create_budget_adjustment(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/units/{unit_id}/budget-adjustments", payload, headers
        )

    # --- Patients ------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def discharge_patient(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/discharge", payload, headers
        )

    # --- WOC nurses ----------------------------------------------------------
    def create_woc_nurse(self, payload, headers):
        return self._request("POST", "/woc-nurses", payload, headers)

    def list_woc_nurses(self, headers, params=None):
        return self._request("GET", "/woc-nurses", headers=headers, params=params)

    def get_woc_nurse(self, nurse_id, headers):
        return self._request("GET", f"/woc-nurses/{nurse_id}", headers=headers)

    def create_competency_signoff(self, nurse_id, payload, headers):
        return self._request(
            "POST", f"/woc-nurses/{nurse_id}/competency-signoffs", payload, headers
        )

    def advance_woc_nurse(self, nurse_id, payload, headers):
        return self._request(
            "POST", f"/woc-nurses/{nurse_id}/advance", payload, headers
        )

    def certify_woc_nurse(self, nurse_id, payload, headers):
        return self._request(
            "POST", f"/woc-nurses/{nurse_id}/certify", payload, headers
        )

    def lapse_woc_nurse(self, nurse_id, payload, headers):
        return self._request("POST", f"/woc-nurses/{nurse_id}/lapse", payload, headers)

    # --- Consult requests ----------------------------------------------------
    def create_consult_request(self, payload, headers):
        return self._request("POST", "/consult-requests", payload, headers)

    def list_consult_requests(self, headers, params=None):
        return self._request(
            "GET", "/consult-requests", headers=headers, params=params
        )

    def get_consult_request(self, consult_id, headers):
        return self._request(
            "GET", f"/consult-requests/{consult_id}", headers=headers
        )

    def triage_consult_request(self, consult_id, headers, payload=None):
        return self._request(
            "POST", f"/consult-requests/{consult_id}/triage", payload, headers
        )

    def return_consult_request(self, consult_id, payload, headers):
        return self._request(
            "POST", f"/consult-requests/{consult_id}/return", payload, headers
        )

    def resubmit_consult_request(self, consult_id, payload, headers):
        return self._request(
            "POST", f"/consult-requests/{consult_id}/resubmit", payload, headers
        )

    def assign_consult_request(self, consult_id, payload, headers):
        return self._request(
            "POST", f"/consult-requests/{consult_id}/assign", payload, headers
        )

    def escalate_consult_request(self, consult_id, payload, headers):
        return self._request(
            "POST", f"/consult-requests/{consult_id}/escalate", payload, headers
        )

    def close_consult_request(self, consult_id, payload, headers):
        return self._request(
            "POST", f"/consult-requests/{consult_id}/close", payload, headers
        )

    def cancel_consult_request(self, consult_id, payload, headers):
        return self._request(
            "POST", f"/consult-requests/{consult_id}/cancel", payload, headers
        )

    # --- Skin assessments ----------------------------------------------------
    def create_skin_assessment(self, payload, headers):
        return self._request("POST", "/skin-assessments", payload, headers)

    def list_skin_assessments(self, headers, params=None):
        return self._request("GET", "/skin-assessments", headers=headers, params=params)

    def get_skin_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/skin-assessments/{assessment_id}", headers=headers
        )

    def validate_skin_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/skin-assessments/{assessment_id}/validate", payload, headers
        )

    def dispute_skin_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/skin-assessments/{assessment_id}/dispute", payload, headers
        )

    def restage_skin_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/skin-assessments/{assessment_id}/restage", payload, headers
        )

    # --- Pressure injury cases ----------------------------------------------
    def list_pressure_injury_cases(self, headers, params=None):
        return self._request(
            "GET", "/pressure-injury-cases", headers=headers, params=params
        )

    def get_pressure_injury_case(self, case_id, headers):
        return self._request(
            "GET", f"/pressure-injury-cases/{case_id}", headers=headers
        )

    def rca_start(self, case_id, payload, headers):
        return self._request(
            "POST", f"/pressure-injury-cases/{case_id}/rca-start", payload, headers
        )

    def rca_complete(self, case_id, payload, headers):
        return self._request(
            "POST", f"/pressure-injury-cases/{case_id}/rca-complete", payload, headers
        )

    def close_pressure_injury_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/pressure-injury-cases/{case_id}/close", payload, headers
        )

    # --- Survey rounds -------------------------------------------------------
    def create_survey_round(self, payload, headers):
        return self._request("POST", "/survey-rounds", payload, headers)

    def list_survey_rounds(self, headers, params=None):
        return self._request("GET", "/survey-rounds", headers=headers, params=params)

    def get_survey_round(self, round_id, headers):
        return self._request("GET", f"/survey-rounds/{round_id}", headers=headers)

    def open_survey_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/survey-rounds/{round_id}/open", payload, headers
        )

    def lock_survey_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/survey-rounds/{round_id}/lock", payload, headers
        )

    def publish_survey_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/survey-rounds/{round_id}/publish", payload, headers
        )

    def cancel_survey_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/survey-rounds/{round_id}/cancel", payload, headers
        )

    def get_survey_round_unit_report(self, round_id, headers):
        return self._request(
            "GET", f"/survey-rounds/{round_id}/unit-report", headers=headers
        )

    # --- Survey observations -------------------------------------------------
    def create_survey_observation(self, payload, headers):
        return self._request("POST", "/survey-observations", payload, headers)

    def list_survey_observations(self, headers, params=None):
        return self._request(
            "GET", "/survey-observations", headers=headers, params=params
        )

    def get_survey_observation(self, observation_id, headers):
        return self._request(
            "GET", f"/survey-observations/{observation_id}", headers=headers
        )

    # --- Support surfaces ----------------------------------------------------
    def create_support_surface(self, payload, headers):
        return self._request("POST", "/support-surfaces", payload, headers)

    def list_support_surfaces(self, headers, params=None):
        return self._request(
            "GET", "/support-surfaces", headers=headers, params=params
        )

    def get_support_surface(self, surface_id, headers):
        return self._request("GET", f"/support-surfaces/{surface_id}", headers=headers)

    def retire_support_surface(self, surface_id, payload, headers):
        return self._request(
            "POST", f"/support-surfaces/{surface_id}/retire", payload, headers
        )

    # --- Support surface orders ---------------------------------------------
    def create_support_surface_order(self, payload, headers):
        return self._request("POST", "/support-surface-orders", payload, headers)

    def list_support_surface_orders(self, headers, params=None):
        return self._request(
            "GET", "/support-surface-orders", headers=headers, params=params
        )

    def get_support_surface_order(self, order_id, headers):
        return self._request(
            "GET", f"/support-surface-orders/{order_id}", headers=headers
        )

    def approve_support_surface_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/support-surface-orders/{order_id}/approve", payload, headers
        )

    def deny_support_surface_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/support-surface-orders/{order_id}/deny", payload, headers
        )

    def deliver_support_surface_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/support-surface-orders/{order_id}/deliver", payload, headers
        )

    def return_support_surface_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/support-surface-orders/{order_id}/return", payload, headers
        )

    def reconcile_support_surface_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/support-surface-orders/{order_id}/reconcile", payload, headers
        )

    # --- Formulary products --------------------------------------------------
    def create_formulary_product(self, payload, headers):
        return self._request("POST", "/formulary-products", payload, headers)

    def list_formulary_products(self, headers, params=None):
        return self._request(
            "GET", "/formulary-products", headers=headers, params=params
        )

    def get_formulary_product(self, product_id, headers):
        return self._request(
            "GET", f"/formulary-products/{product_id}", headers=headers
        )

    def archive_formulary_product(self, product_id, payload, headers):
        return self._request(
            "POST", f"/formulary-products/{product_id}/archive", payload, headers
        )

    # --- Dressing protocols --------------------------------------------------
    def create_dressing_protocol(self, payload, headers):
        return self._request("POST", "/dressing-protocols", payload, headers)

    def list_dressing_protocols(self, headers, params=None):
        return self._request(
            "GET", "/dressing-protocols", headers=headers, params=params
        )

    def get_dressing_protocol(self, protocol_id, headers):
        return self._request(
            "GET", f"/dressing-protocols/{protocol_id}", headers=headers
        )

    # --- Ostomy education plans ---------------------------------------------
    def create_ostomy_education_plan(self, payload, headers):
        return self._request("POST", "/ostomy-education-plans", payload, headers)

    def list_ostomy_education_plans(self, headers, params=None):
        return self._request(
            "GET", "/ostomy-education-plans", headers=headers, params=params
        )

    def get_ostomy_education_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/ostomy-education-plans/{plan_id}", headers=headers
        )

    def create_education_session(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/ostomy-education-plans/{plan_id}/sessions", payload, headers
        )

    def transition_supplies(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/ostomy-education-plans/{plan_id}/transition-supplies",
            payload,
            headers,
        )

    # --- Logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
