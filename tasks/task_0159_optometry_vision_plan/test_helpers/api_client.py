"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Simulated clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- Providers ----------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    # ---------------- Patients ----------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient_statement(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}/statement", headers=headers)

    # ---------------- Encounters ----------------
    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def finalize_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/finalize", {}, headers)

    def void_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/void", {}, headers)

    # ---------------- Prescriptions ----------------
    def create_prescription(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/prescriptions/{prescription_id}", headers=headers)

    def list_patient_prescriptions(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/prescriptions", headers=headers, params=params)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    def revoke_prescription(self, prescription_id, headers):
        return self._request("POST", f"/prescriptions/{prescription_id}/revoke", {}, headers)

    # ---------------- Eligibility & BenefitPool ----------------
    def create_eligibility(self, payload, headers):
        return self._request("POST", "/eligibilities", payload, headers)

    def get_eligibility(self, eligibility_id, headers):
        return self._request("GET", f"/eligibilities/{eligibility_id}", headers=headers)

    def list_eligibilities(self, headers, params=None):
        return self._request("GET", "/eligibilities", headers=headers, params=params)

    def list_eligibility_benefit_pools(self, eligibility_id, headers, params=None):
        return self._request("GET", f"/eligibilities/{eligibility_id}/benefit-pools", headers=headers, params=params)

    def get_benefit_pool(self, benefit_pool_id, headers):
        return self._request("GET", f"/benefit-pools/{benefit_pool_id}", headers=headers)

    def list_benefit_pools(self, headers, params=None):
        return self._request("GET", "/benefit-pools", headers=headers, params=params)

    def terminate_eligibility(self, eligibility_id, headers):
        return self._request("POST", f"/eligibilities/{eligibility_id}/terminate", {}, headers)

    # ---------------- LabOrders ----------------
    def create_lab_order(self, payload, headers):
        return self._request("POST", "/lab-orders", payload, headers)

    def get_lab_order(self, lab_order_id, headers):
        return self._request("GET", f"/lab-orders/{lab_order_id}", headers=headers)

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/lab-orders", headers=headers, params=params)

    def send_lab_order_to_lab(self, lab_order_id, headers):
        return self._request("POST", f"/lab-orders/{lab_order_id}/send-to-lab", {}, headers)

    def dispense_lab_order(self, lab_order_id, payload, headers):
        return self._request("POST", f"/lab-orders/{lab_order_id}/dispense", payload, headers)

    def request_lab_order_remake(self, lab_order_id, payload, headers):
        return self._request("POST", f"/lab-orders/{lab_order_id}/request-remake", payload, headers)

    def cancel_lab_order(self, lab_order_id, headers):
        return self._request("POST", f"/lab-orders/{lab_order_id}/cancel", {}, headers)

    # ---------------- Claims ----------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", {}, headers)

    def pay_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/payments", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/void", {}, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", {}, headers)

    def carrier_ack_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/carrier-ack", payload, headers)

    # ---------------- RecallReminders ----------------
    def create_recall_reminder(self, payload, headers):
        return self._request("POST", "/recall-reminders", payload, headers)

    def get_recall_reminder(self, reminder_id, headers):
        return self._request("GET", f"/recall-reminders/{reminder_id}", headers=headers)

    def list_recall_reminders(self, headers, params=None):
        return self._request("GET", "/recall-reminders", headers=headers, params=params)

    def send_recall_reminder(self, reminder_id, headers):
        return self._request("POST", f"/recall-reminders/{reminder_id}/send", {}, headers)

    def cancel_recall_reminder(self, reminder_id, headers):
        return self._request("POST", f"/recall-reminders/{reminder_id}/cancel", {}, headers)


api_client = ApiClient()
