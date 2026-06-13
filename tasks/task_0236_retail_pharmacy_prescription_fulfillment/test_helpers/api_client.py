"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test driving) ----
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set", {"current_utc": current_utc}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- DrugProduct ----
    def create_drug_product(self, payload, headers):
        return self._request("POST", "/drug-products", payload, headers)

    def list_drug_products(self, headers, params=None):
        return self._request("GET", "/drug-products", headers=headers, params=params)

    def get_drug_product(self, drug_id, headers):
        return self._request("GET", f"/drug-products/{drug_id}", headers=headers)

    def discontinue_drug_product(self, drug_id, headers):
        return self._request("POST", f"/drug-products/{drug_id}/discontinue", {}, headers)

    # ---- InsurancePlan ----
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    def list_insurance_plans(self, headers, params=None):
        return self._request("GET", "/insurance-plans", headers=headers, params=params)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    # ---- FormularyEntry ----
    def create_formulary_entry(self, payload, headers):
        return self._request("POST", "/formulary-entries", payload, headers)

    def list_formulary_entries(self, headers, params=None):
        return self._request("GET", "/formulary-entries", headers=headers, params=params)

    def get_formulary_entry(self, entry_id, headers):
        return self._request("GET", f"/formulary-entries/{entry_id}", headers=headers)

    # ---- InteractionRule ----
    def create_interaction_rule(self, payload, headers):
        return self._request("POST", "/interaction-rules", payload, headers)

    def list_interaction_rules(self, headers, params=None):
        return self._request("GET", "/interaction-rules", headers=headers, params=params)

    def get_interaction_rule(self, rule_id, headers):
        return self._request("GET", f"/interaction-rules/{rule_id}", headers=headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def clear_pdmp_block(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/clear-pdmp-block", payload, headers
        )

    # ---- Prescriber ----
    def create_prescriber(self, payload, headers):
        return self._request("POST", "/prescribers", payload, headers)

    def list_prescribers(self, headers, params=None):
        return self._request("GET", "/prescribers", headers=headers, params=params)

    def get_prescriber(self, prescriber_id, headers):
        return self._request("GET", f"/prescribers/{prescriber_id}", headers=headers)

    # ---- Prescription ----
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/prescriptions/{prescription_id}", headers=headers)

    def discontinue_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/discontinue", {}, headers
        )

    def expire_scan_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/expire-scan", {}, headers
        )

    # ---- Fill ----
    def create_fill(self, payload, headers):
        return self._request("POST", "/fills", payload, headers)

    def list_fills(self, headers, params=None):
        return self._request("GET", "/fills", headers=headers, params=params)

    def get_fill(self, fill_id, headers):
        return self._request("GET", f"/fills/{fill_id}", headers=headers)

    def run_dur(self, fill_id, headers):
        return self._request("POST", f"/fills/{fill_id}/run-dur", {}, headers)

    def override_dur(self, fill_id, payload, headers):
        return self._request("POST", f"/fills/{fill_id}/override-dur", payload, headers)

    def submit_claim(self, fill_id, payload, headers):
        return self._request("POST", f"/fills/{fill_id}/submit-claim", payload, headers)

    def reverse_claim(self, fill_id, headers):
        return self._request("POST", f"/fills/{fill_id}/reverse-claim", {}, headers)

    def stage_will_call(self, fill_id, headers):
        return self._request("POST", f"/fills/{fill_id}/stage-will-call", {}, headers)

    def dispense(self, fill_id, headers):
        return self._request("POST", f"/fills/{fill_id}/dispense", {}, headers)

    def cancel_fill(self, fill_id, headers):
        return self._request("POST", f"/fills/{fill_id}/cancel", {}, headers)

    def expire_will_call(self, fill_id, headers):
        return self._request("POST", f"/fills/{fill_id}/expire-will-call", {}, headers)

    # ---- DurAlert ----
    def list_dur_alerts(self, headers, params=None):
        return self._request("GET", "/dur-alerts", headers=headers, params=params)

    def get_dur_alert(self, alert_id, headers):
        return self._request("GET", f"/dur-alerts/{alert_id}", headers=headers)

    # ---- PriorAuthRequest ----
    def list_prior_auth_requests(self, headers, params=None):
        return self._request("GET", "/prior-auth-requests", headers=headers, params=params)

    def get_prior_auth_request(self, pa_id, headers):
        return self._request("GET", f"/prior-auth-requests/{pa_id}", headers=headers)

    def approve_prior_auth(self, pa_id, payload, headers):
        return self._request(
            "POST", f"/prior-auth-requests/{pa_id}/approve", payload, headers
        )

    def deny_prior_auth(self, pa_id, payload, headers):
        return self._request(
            "POST", f"/prior-auth-requests/{pa_id}/deny", payload, headers
        )

    def expire_scan_prior_auth(self, pa_id, headers):
        return self._request(
            "POST", f"/prior-auth-requests/{pa_id}/expire-scan", {}, headers
        )

    # ---- PdmpReport ----
    def create_pdmp_report(self, payload, headers):
        return self._request("POST", "/pdmp-reports", payload, headers)

    def list_pdmp_reports(self, headers, params=None):
        return self._request("GET", "/pdmp-reports", headers=headers, params=params)

    def get_pdmp_report(self, report_id, headers):
        return self._request("GET", f"/pdmp-reports/{report_id}", headers=headers)

    # ---- PaymentRecord ----
    def create_payment_record(self, payload, headers):
        return self._request("POST", "/payment-records", payload, headers)

    def list_payment_records(self, headers, params=None):
        return self._request("GET", "/payment-records", headers=headers, params=params)

    def get_payment_record(self, payment_id, headers):
        return self._request("GET", f"/payment-records/{payment_id}", headers=headers)


api_client = ApiClient()
