"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- Clinicians ----
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    # ---- Cases ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def create_intake_record(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/intake-records", payload, headers)

    def list_intake_records(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/intake-records", headers=headers, params=params)

    def record_guardian_consent(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/guardian-consent", payload, headers)

    def submit_for_review(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/submit-for-review", {}, headers)

    def activate_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/activate", {}, headers)

    def resume_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/resume", {}, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/complete", {}, headers)

    def list_case_aligner_steps(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/aligner-steps", headers=headers, params=params)

    def list_case_checkins(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/checkins", headers=headers, params=params)

    def list_case_refinements(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/refinements", headers=headers, params=params)

    # ---- Plans ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/submit", {}, headers)

    def request_changes_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/request-changes", {}, headers)

    def resubmit_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/resubmit", payload, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/approve", {}, headers)

    def decline_eligibility(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/decline-eligibility", {}, headers)

    # ---- Aligner steps ----
    def get_aligner_step(self, step_id, headers):
        return self._request("GET", f"/aligner-steps/{step_id}", headers=headers)

    def list_aligner_steps(self, headers, params=None):
        return self._request("GET", "/aligner-steps", headers=headers, params=params)

    def start_production(self, step_id, headers):
        return self._request("POST", f"/aligner-steps/{step_id}/start-production", {}, headers)

    def complete_production(self, step_id, headers):
        return self._request("POST", f"/aligner-steps/{step_id}/complete-production", {}, headers)

    # ---- Shipments ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", {}, headers)

    def mark_delivered(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/mark-delivered", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel", {}, headers)

    # ---- Progress check-ins ----
    def create_checkin(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/checkins", payload, headers)

    def assess_checkin(self, checkin_id, payload, headers):
        return self._request("POST", f"/checkins/{checkin_id}/assess", payload, headers)

    def get_checkin(self, checkin_id, headers):
        return self._request("GET", f"/checkins/{checkin_id}", headers=headers)

    # ---- Refinements ----
    def create_refinement(self, payload, headers):
        return self._request("POST", "/refinements", payload, headers)

    def get_refinement(self, refinement_id, headers):
        return self._request("GET", f"/refinements/{refinement_id}", headers=headers)

    def list_refinements(self, headers, params=None):
        return self._request("GET", "/refinements", headers=headers, params=params)

    def grant_refinement(self, refinement_id, headers):
        return self._request("POST", f"/refinements/{refinement_id}/grant", {}, headers)

    def deny_refinement(self, refinement_id, headers):
        return self._request("POST", f"/refinements/{refinement_id}/deny", {}, headers)

    # ---- Financing ----
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/financing-plans", payload, headers)

    def get_financing_plan(self, plan_id, headers):
        return self._request("GET", f"/financing-plans/{plan_id}", headers=headers)

    def list_financing_plans(self, headers, params=None):
        return self._request("GET", "/financing-plans", headers=headers, params=params)

    def activate_financing_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/activate", payload, headers)

    def list_installments(self, plan_id, headers, params=None):
        return self._request("GET", f"/financing-plans/{plan_id}/installments", headers=headers, params=params)

    def post_installment_payment(self, plan_id, seq, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/installments/{seq}/post-payment", {}, headers)

    def run_delinquency_sweep(self, plan_id, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/run-delinquency-sweep", {}, headers)

    # ---- Refunds ----
    def create_refund(self, payload, headers):
        return self._request("POST", "/refunds", payload, headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    def approve_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/approve", {}, headers)

    def reject_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/reject", {}, headers)

    def settle_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/settle", {}, headers)

    # ---- Retainers ----
    def create_retainer(self, payload, headers):
        return self._request("POST", "/retainers", payload, headers)

    def get_retainer(self, retainer_id, headers):
        return self._request("GET", f"/retainers/{retainer_id}", headers=headers)

    def list_retainers(self, headers, params=None):
        return self._request("GET", "/retainers", headers=headers, params=params)

    def pause_retainer(self, retainer_id, headers):
        return self._request("POST", f"/retainers/{retainer_id}/pause", {}, headers)

    def resume_retainer(self, retainer_id, headers):
        return self._request("POST", f"/retainers/{retainer_id}/resume", {}, headers)

    def cancel_retainer(self, retainer_id, headers):
        return self._request("POST", f"/retainers/{retainer_id}/cancel", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
