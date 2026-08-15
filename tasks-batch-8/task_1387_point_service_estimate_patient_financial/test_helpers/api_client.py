"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Configuration (SystemAdmin) ---
    def create_charge_item(self, payload, headers):
        return self._request("POST", "/clearance/charge-items", payload, headers)

    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/clearance/payer-contracts", payload, headers)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/clearance/payer-contracts/{contract_id}",
                             headers=headers)

    def list_payer_contracts(self, headers, params=None):
        return self._request("GET", "/clearance/payer-contracts",
                             headers=headers, params=params)

    def add_contract_rate(self, contract_id, payload, headers):
        return self._request("POST", f"/clearance/payer-contracts/{contract_id}/rates",
                             payload, headers)

    def list_contract_rates(self, contract_id, headers, params=None):
        return self._request("GET", f"/clearance/payer-contracts/{contract_id}/rates",
                             headers=headers, params=params)

    # --- Patients & eligibility ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/clearance/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/clearance/patients/{patient_id}", headers=headers)

    def create_eligibility_snapshot(self, patient_id, payload, headers):
        return self._request("POST",
                             f"/clearance/patients/{patient_id}/eligibility-snapshots",
                             payload, headers)

    def get_eligibility_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/clearance/eligibility-snapshots/{snapshot_id}",
                             headers=headers)

    def list_eligibility_snapshots(self, headers, params=None):
        return self._request("GET", "/clearance/eligibility-snapshots",
                             headers=headers, params=params)

    # --- Cases ---
    def create_case(self, patient_id, payload, headers):
        return self._request("POST", f"/clearance/patients/{patient_id}/cases",
                             payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/clearance/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/clearance/cases", headers=headers, params=params)

    def clear_case(self, case_id, headers):
        return self._request("POST", f"/clearance/cases/{case_id}/clear", headers=headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/clearance/cases/{case_id}/cancel", headers=headers)

    # --- Estimates ---
    def create_estimate(self, case_id, payload, headers):
        return self._request("POST", f"/clearance/cases/{case_id}/estimates",
                             payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/clearance/estimates/{estimate_id}", headers=headers)

    def list_case_estimates(self, case_id, headers, params=None):
        return self._request("GET", f"/clearance/cases/{case_id}/estimates",
                             headers=headers, params=params)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/clearance/estimates", headers=headers, params=params)

    def price_estimate(self, estimate_id, headers):
        return self._request("POST", f"/clearance/estimates/{estimate_id}/price",
                             headers=headers)

    def present_estimate(self, estimate_id, headers):
        return self._request("POST", f"/clearance/estimates/{estimate_id}/present",
                             headers=headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/clearance/estimates/{estimate_id}/accept",
                             headers=headers)

    def finalize_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/clearance/estimates/{estimate_id}/finalize",
                             payload, headers)

    # --- Authorizations ---
    def create_authorization(self, case_id, payload, headers):
        return self._request("POST", f"/clearance/cases/{case_id}/authorizations",
                             payload, headers)

    def list_case_authorizations(self, case_id, headers, params=None):
        return self._request("GET", f"/clearance/cases/{case_id}/authorizations",
                             headers=headers, params=params)

    def decide_authorization(self, authorization_id, payload, headers):
        return self._request("POST", f"/clearance/authorizations/{authorization_id}/decide",
                             payload, headers)

    def appeal_authorization(self, authorization_id, headers):
        return self._request("POST", f"/clearance/authorizations/{authorization_id}/appeal",
                             headers=headers)

    # --- Payment plans ---
    def create_payment_plan(self, case_id, payload, headers):
        return self._request("POST", f"/clearance/cases/{case_id}/payment-plans",
                             payload, headers)

    def list_case_payment_plans(self, case_id, headers, params=None):
        return self._request("GET", f"/clearance/cases/{case_id}/payment-plans",
                             headers=headers, params=params)

    def activate_payment_plan(self, plan_id, headers):
        return self._request("POST", f"/clearance/payment-plans/{plan_id}/activate",
                             headers=headers)

    def record_plan_payment(self, plan_id, payload, headers):
        return self._request("POST", f"/clearance/payment-plans/{plan_id}/payments",
                             payload, headers)

    def reinstate_payment_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/clearance/payment-plans/{plan_id}/reinstate",
                             payload, headers)

    # --- Deposits ---
    def create_deposit(self, case_id, payload, headers):
        return self._request("POST", f"/clearance/cases/{case_id}/deposits",
                             payload, headers)

    def list_case_deposits(self, case_id, headers, params=None):
        return self._request("GET", f"/clearance/cases/{case_id}/deposits",
                             headers=headers, params=params)

    def post_deposit(self, deposit_id, headers):
        return self._request("POST", f"/clearance/deposits/{deposit_id}/post",
                             headers=headers)

    def refund_deposit(self, deposit_id, headers):
        return self._request("POST", f"/clearance/deposits/{deposit_id}/refund",
                             headers=headers)

    # --- Variance tracking ---
    def list_estimate_variance_records(self, estimate_id, headers, params=None):
        return self._request("GET", f"/clearance/estimates/{estimate_id}/variance-records",
                             headers=headers, params=params)

    def review_variance_record(self, variance_record_id, payload, headers):
        return self._request("POST",
                             f"/clearance/variance-records/{variance_record_id}/review",
                             payload, headers)

    # --- Escalations ---
    def create_escalation(self, case_id, payload, headers):
        return self._request("POST", f"/clearance/cases/{case_id}/escalations",
                             payload, headers)

    def list_case_escalations(self, case_id, headers, params=None):
        return self._request("GET", f"/clearance/cases/{case_id}/escalations",
                             headers=headers, params=params)

    def list_estimate_escalations(self, estimate_id, headers, params=None):
        return self._request("GET", f"/clearance/estimates/{estimate_id}/escalations",
                             headers=headers, params=params)

    def approve_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/clearance/escalations/{escalation_id}/approve",
                             payload, headers)

    def reject_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/clearance/escalations/{escalation_id}/reject",
                             payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/clearance/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
