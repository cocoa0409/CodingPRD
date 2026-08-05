"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Procedure ---
    def create_procedure(self, payload, headers):
        return self._request("POST", "/procedures", payload, headers)

    def get_procedure(self, procedure_id, headers):
        return self._request("GET", f"/procedures/{procedure_id}", headers=headers)

    def list_procedures(self, headers, params=None):
        return self._request("GET", "/procedures", headers=headers, params=params)

    def get_comparison(self, procedure_id, headers, params=None):
        return self._request("GET", f"/procedures/{procedure_id}/comparison",
                             headers=headers, params=params)

    # --- PayerContract ---
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/payer-contracts", payload, headers)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/payer-contracts/{contract_id}", headers=headers)

    def activate_payer_contract(self, contract_id, headers):
        return self._request("POST", f"/payer-contracts/{contract_id}/activate",
                             {}, headers)

    # --- NegotiatedRate ---
    def create_negotiated_rate(self, payload, headers):
        return self._request("POST", "/negotiated-rates", payload, headers)

    def get_negotiated_rate(self, rate_id, headers):
        return self._request("GET", f"/negotiated-rates/{rate_id}", headers=headers)

    def list_negotiated_rates(self, headers, params=None):
        return self._request("GET", "/negotiated-rates", headers=headers, params=params)

    # --- BenefitPlan ---
    def create_benefit_plan(self, payload, headers):
        return self._request("POST", "/benefit-plans", payload, headers)

    def get_benefit_plan(self, plan_id, headers):
        return self._request("GET", f"/benefit-plans/{plan_id}", headers=headers)

    # --- Patient ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def create_accumulation_adjustment(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/accumulation-adjustments",
                             payload, headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    # --- Room ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # --- Estimate ---
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def add_estimate_line(self, estimate_id, payload, headers):
        return self._request("POST", f"/estimates/{estimate_id}/lines", payload, headers)

    def issue_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/issue", {}, headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/accept", {}, headers)

    def void_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/void", {}, headers)

    # --- EstimateLine ---
    def get_estimate_line(self, line_id, headers):
        return self._request("GET", f"/estimate-lines/{line_id}", headers=headers)

    def list_estimate_lines(self, headers, params=None):
        return self._request("GET", "/estimate-lines", headers=headers, params=params)

    # --- PriorAuthorization ---
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/prior-authorizations", payload, headers)

    def get_prior_authorization(self, prior_auth_id, headers):
        return self._request("GET", f"/prior-authorizations/{prior_auth_id}", headers=headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", "/prior-authorizations", headers=headers, params=params)

    def approve_prior_authorization(self, prior_auth_id, payload, headers):
        return self._request("POST", f"/prior-authorizations/{prior_auth_id}/approve",
                             payload, headers)

    def deny_prior_authorization(self, prior_auth_id, payload, headers):
        return self._request("POST", f"/prior-authorizations/{prior_auth_id}/deny",
                             payload, headers)

    # --- Appointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def assign_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/assign", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # --- Reporting ---
    def get_price_transparency_report(self, headers, params=None):
        return self._request("GET", "/reports/price-transparency",
                             headers=headers, params=params)


api_client = ApiClient()
