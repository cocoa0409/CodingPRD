"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, center_id, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"center_id": center_id, "to_iso8601": to_iso8601}, headers,
        )

    # ---- Center ----
    def create_center(self, payload, headers):
        return self._request("POST", "/wound-care/centers", payload, headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/wound-care/centers", headers=headers, params=params)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/wound-care/centers/{center_id}", headers=headers)

    # ---- Clinician ----
    def create_clinician(self, payload, headers):
        return self._request("POST", "/wound-care/clinicians", payload, headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/wound-care/clinicians", headers=headers, params=params)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/wound-care/clinicians/{clinician_id}", headers=headers)

    # ---- Chamber ----
    def create_chamber(self, payload, headers):
        return self._request("POST", "/wound-care/chambers", payload, headers)

    def list_chambers(self, headers, params=None):
        return self._request("GET", "/wound-care/chambers", headers=headers, params=params)

    def get_chamber(self, chamber_id, headers):
        return self._request("GET", f"/wound-care/chambers/{chamber_id}", headers=headers)

    # ---- PayerPolicy ----
    def create_payer_policy(self, payload, headers):
        return self._request("POST", "/wound-care/payer-policies", payload, headers)

    def list_payer_policies(self, headers, params=None):
        return self._request("GET", "/wound-care/payer-policies", headers=headers, params=params)

    def get_payer_policy(self, policy_id, headers):
        return self._request("GET", f"/wound-care/payer-policies/{policy_id}", headers=headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/wound-care/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/wound-care/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/wound-care/patients/{patient_id}", headers=headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/wound-care/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/wound-care/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/wound-care/referrals/{referral_id}", headers=headers)

    def request_info_referral(self, referral_id, headers):
        return self._request("POST", f"/wound-care/referrals/{referral_id}/request-info", headers=headers)

    def resubmit_referral(self, referral_id, headers):
        return self._request("POST", f"/wound-care/referrals/{referral_id}/resubmit", headers=headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/wound-care/referrals/{referral_id}/accept", headers=headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/wound-care/referrals/{referral_id}/decline", headers=headers)

    # ---- WoundAssessment ----
    def create_wound_assessment(self, payload, headers):
        return self._request("POST", "/wound-care/wound-assessments", payload, headers)

    def list_wound_assessments(self, headers, params=None):
        return self._request("GET", "/wound-care/wound-assessments", headers=headers, params=params)

    def get_wound_assessment(self, assessment_id, headers):
        return self._request("GET", f"/wound-care/wound-assessments/{assessment_id}", headers=headers)

    # ---- PhotoDocument ----
    def create_photo_document(self, payload, headers):
        return self._request("POST", "/wound-care/photo-documents", payload, headers)

    def list_photo_documents(self, headers, params=None):
        return self._request("GET", "/wound-care/photo-documents", headers=headers, params=params)

    def get_photo_document(self, photo_id, headers):
        return self._request("GET", f"/wound-care/photo-documents/{photo_id}", headers=headers)

    # ---- TreatmentPlan ----
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/wound-care/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/wound-care/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/wound-care/treatment-plans/{plan_id}", headers=headers)

    def activate_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/wound-care/treatment-plans/{plan_id}/activate", headers=headers)

    def suspend_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/wound-care/treatment-plans/{plan_id}/suspend", headers=headers)

    def resume_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/wound-care/treatment-plans/{plan_id}/resume", headers=headers)

    def outcome_report_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/wound-care/treatment-plans/{plan_id}/outcome-report", headers=headers)

    # ---- PriorAuthorization ----
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/wound-care/prior-authorizations", payload, headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", "/wound-care/prior-authorizations", headers=headers, params=params)

    def get_prior_authorization(self, auth_id, headers):
        return self._request("GET", f"/wound-care/prior-authorizations/{auth_id}", headers=headers)

    def request_info_prior_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"/wound-care/prior-authorizations/{auth_id}/request-info", payload, headers)

    def resubmit_prior_authorization(self, auth_id, headers):
        return self._request("POST", f"/wound-care/prior-authorizations/{auth_id}/resubmit", headers=headers)

    def approve_prior_authorization(self, auth_id, headers):
        return self._request("POST", f"/wound-care/prior-authorizations/{auth_id}/approve", headers=headers)

    def deny_prior_authorization(self, auth_id, headers):
        return self._request("POST", f"/wound-care/prior-authorizations/{auth_id}/deny", headers=headers)

    # ---- DebridementProcedure ----
    def create_debridement_procedure(self, payload, headers):
        return self._request("POST", "/wound-care/debridement-procedures", payload, headers)

    def list_debridement_procedures(self, headers, params=None):
        return self._request("GET", "/wound-care/debridement-procedures", headers=headers, params=params)

    def get_debridement_procedure(self, proc_id, headers):
        return self._request("GET", f"/wound-care/debridement-procedures/{proc_id}", headers=headers)

    def complete_debridement_procedure(self, proc_id, headers):
        return self._request("POST", f"/wound-care/debridement-procedures/{proc_id}/complete", headers=headers)

    def cancel_debridement_procedure(self, proc_id, headers):
        return self._request("POST", f"/wound-care/debridement-procedures/{proc_id}/cancel", headers=headers)

    # ---- HboSession ----
    def create_hbo_session(self, payload, headers):
        return self._request("POST", "/wound-care/hbo-sessions", payload, headers)

    def list_hbo_sessions(self, headers, params=None):
        return self._request("GET", "/wound-care/hbo-sessions", headers=headers, params=params)

    def get_hbo_session(self, session_id, headers):
        return self._request("GET", f"/wound-care/hbo-sessions/{session_id}", headers=headers)

    def complete_hbo_session(self, session_id, payload, headers):
        return self._request("POST", f"/wound-care/hbo-sessions/{session_id}/complete", payload, headers)

    def cancel_hbo_session(self, session_id, headers):
        return self._request("POST", f"/wound-care/hbo-sessions/{session_id}/cancel", headers=headers)

    # ---- SupplyOrder ----
    def create_supply_order(self, payload, headers):
        return self._request("POST", "/wound-care/supply-orders", payload, headers)

    def list_supply_orders(self, headers, params=None):
        return self._request("GET", "/wound-care/supply-orders", headers=headers, params=params)

    def get_supply_order(self, order_id, headers):
        return self._request("GET", f"/wound-care/supply-orders/{order_id}", headers=headers)

    def approve_supply_order(self, order_id, headers):
        return self._request("POST", f"/wound-care/supply-orders/{order_id}/approve", headers=headers)

    def reject_supply_order(self, order_id, headers):
        return self._request("POST", f"/wound-care/supply-orders/{order_id}/reject", headers=headers)

    def cancel_supply_order(self, order_id, headers):
        return self._request("POST", f"/wound-care/supply-orders/{order_id}/cancel", headers=headers)

    # ---- AcuteTransfer ----
    def create_acute_transfer(self, payload, headers):
        return self._request("POST", "/wound-care/acute-transfers", payload, headers)

    def list_acute_transfers(self, headers, params=None):
        return self._request("GET", "/wound-care/acute-transfers", headers=headers, params=params)

    def get_acute_transfer(self, transfer_id, headers):
        return self._request("GET", f"/wound-care/acute-transfers/{transfer_id}", headers=headers)

    def accept_acute_transfer(self, transfer_id, headers):
        return self._request("POST", f"/wound-care/acute-transfers/{transfer_id}/accept", headers=headers)

    def cancel_acute_transfer(self, transfer_id, headers):
        return self._request("POST", f"/wound-care/acute-transfers/{transfer_id}/cancel", headers=headers)

    # ---- OutcomeReport ----
    def list_outcome_reports(self, headers, params=None):
        return self._request("GET", "/wound-care/outcome-reports", headers=headers, params=params)

    def get_outcome_report(self, report_id, headers):
        return self._request("GET", f"/wound-care/outcome-reports/{report_id}", headers=headers)


api_client = ApiClient()
