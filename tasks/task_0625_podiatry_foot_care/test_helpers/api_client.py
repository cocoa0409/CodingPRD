"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ─── Practices ────────────────────────────────────────────────────────
    def create_practice(self, payload, headers):
        return self._request("POST", "/podiatry/practices", payload, headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/podiatry/practices/{practice_id}", headers=headers)

    # ─── Providers ────────────────────────────────────────────────────────
    def create_provider(self, payload, headers):
        return self._request("POST", "/podiatry/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/podiatry/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/podiatry/providers/{provider_id}", headers=headers)

    # ─── Modalities ───────────────────────────────────────────────────────
    def create_modality(self, payload, headers):
        return self._request("POST", "/podiatry/modalities", payload, headers)

    def list_modalities(self, headers, params=None):
        return self._request("GET", "/podiatry/modalities", headers=headers, params=params)

    def get_modality(self, modality_id, headers):
        return self._request("GET", f"/podiatry/modalities/{modality_id}", headers=headers)

    # ─── Patients ─────────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/podiatry/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/podiatry/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/podiatry/patients/{patient_id}", headers=headers)

    def update_patient_risk_factors(self, patient_id, payload, headers):
        return self._request("PATCH", f"/podiatry/patients/{patient_id}/risk-factors",
                             payload, headers)

    # ─── Prior Authorizations ─────────────────────────────────────────────
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/podiatry/prior-authorizations", payload, headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", "/podiatry/prior-authorizations", headers=headers, params=params)

    def get_prior_authorization(self, pa_id, headers):
        return self._request("GET", f"/podiatry/prior-authorizations/{pa_id}", headers=headers)

    def approve_prior_authorization(self, pa_id, headers):
        return self._request("POST", f"/podiatry/prior-authorizations/{pa_id}/approve", headers=headers)

    def deny_prior_authorization(self, pa_id, headers):
        return self._request("POST", f"/podiatry/prior-authorizations/{pa_id}/deny", headers=headers)

    # ─── Encounters ───────────────────────────────────────────────────────
    def create_encounter(self, payload, headers):
        return self._request("POST", "/podiatry/encounters", payload, headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/podiatry/encounters", headers=headers, params=params)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/podiatry/encounters/{encounter_id}", headers=headers)

    def complete_exam(self, encounter_id, headers):
        return self._request("POST", f"/podiatry/encounters/{encounter_id}/complete-exam", headers=headers)

    def code_encounter(self, encounter_id, headers):
        return self._request("POST", f"/podiatry/encounters/{encounter_id}/code", headers=headers)

    def recode_encounter(self, encounter_id, headers):
        return self._request("POST", f"/podiatry/encounters/{encounter_id}/recode", headers=headers)

    def submit_encounter(self, encounter_id, headers):
        return self._request("POST", f"/podiatry/encounters/{encounter_id}/submit", headers=headers)

    def adjudicate_encounter(self, encounter_id, headers):
        return self._request("POST", f"/podiatry/encounters/{encounter_id}/adjudicate", headers=headers)

    def void_encounter(self, encounter_id, headers):
        return self._request("POST", f"/podiatry/encounters/{encounter_id}/void", headers=headers)

    # ─── Procedures ───────────────────────────────────────────────────────
    def create_procedure(self, payload, headers):
        return self._request("POST", "/podiatry/procedures", payload, headers)

    def list_procedures(self, headers, params=None):
        return self._request("GET", "/podiatry/procedures", headers=headers, params=params)

    def get_procedure(self, procedure_id, headers):
        return self._request("GET", f"/podiatry/procedures/{procedure_id}", headers=headers)

    # ─── Orthotic Rxs ─────────────────────────────────────────────────────
    def create_orthotic_rx(self, payload, headers):
        return self._request("POST", "/podiatry/orthotic-rxs", payload, headers)

    def list_orthotic_rxs(self, headers, params=None):
        return self._request("GET", "/podiatry/orthotic-rxs", headers=headers, params=params)

    def get_orthotic_rx(self, rx_id, headers):
        return self._request("GET", f"/podiatry/orthotic-rxs/{rx_id}", headers=headers)

    def submit_orthotic_rx_to_payer(self, rx_id, headers):
        return self._request("POST", f"/podiatry/orthotic-rxs/{rx_id}/submit-to-payer", headers=headers)

    def orthotic_rx_payer_decision(self, rx_id, payload, headers):
        return self._request("POST", f"/podiatry/orthotic-rxs/{rx_id}/payer-decision", payload, headers)

    def cancel_orthotic_rx(self, rx_id, headers):
        return self._request("POST", f"/podiatry/orthotic-rxs/{rx_id}/cancel", headers=headers)

    # ─── Lab Orders ───────────────────────────────────────────────────────
    def create_lab_order(self, payload, headers):
        return self._request("POST", "/podiatry/lab-orders", payload, headers)

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/podiatry/lab-orders", headers=headers, params=params)

    def get_lab_order(self, lab_order_id, headers):
        return self._request("GET", f"/podiatry/lab-orders/{lab_order_id}", headers=headers)

    def ship_lab_order(self, lab_order_id, headers):
        return self._request("POST", f"/podiatry/lab-orders/{lab_order_id}/ship", headers=headers)

    def receive_lab_order(self, lab_order_id, headers):
        return self._request("POST", f"/podiatry/lab-orders/{lab_order_id}/receive", headers=headers)

    def cancel_lab_order(self, lab_order_id, headers):
        return self._request("POST", f"/podiatry/lab-orders/{lab_order_id}/cancel", headers=headers)

    # ─── DME Dispenses ────────────────────────────────────────────────────
    def create_dme_dispense(self, payload, headers):
        return self._request("POST", "/podiatry/dme-dispenses", payload, headers)

    def list_dme_dispenses(self, headers, params=None):
        return self._request("GET", "/podiatry/dme-dispenses", headers=headers, params=params)

    def get_dme_dispense(self, dispense_id, headers):
        return self._request("GET", f"/podiatry/dme-dispenses/{dispense_id}", headers=headers)

    def return_dme_dispense(self, dispense_id, headers):
        return self._request("POST", f"/podiatry/dme-dispenses/{dispense_id}/return", headers=headers)

    # ─── Imaging Orders ───────────────────────────────────────────────────
    def create_imaging_order(self, payload, headers):
        return self._request("POST", "/podiatry/imaging-orders", payload, headers)

    def list_imaging_orders(self, headers, params=None):
        return self._request("GET", "/podiatry/imaging-orders", headers=headers, params=params)

    def get_imaging_order(self, imaging_order_id, headers):
        return self._request("GET", f"/podiatry/imaging-orders/{imaging_order_id}", headers=headers)

    def complete_imaging_order(self, imaging_order_id, headers):
        return self._request("POST", f"/podiatry/imaging-orders/{imaging_order_id}/complete", headers=headers)

    def cancel_imaging_order(self, imaging_order_id, headers):
        return self._request("POST", f"/podiatry/imaging-orders/{imaging_order_id}/cancel", headers=headers)

    # ─── Referrals ────────────────────────────────────────────────────────
    def create_referral(self, payload, headers):
        return self._request("POST", "/podiatry/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/podiatry/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/podiatry/referrals/{referral_id}", headers=headers)

    # ─── Recalls ──────────────────────────────────────────────────────────
    def create_recall(self, payload, headers):
        return self._request("POST", "/podiatry/recalls", payload, headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/podiatry/recalls", headers=headers, params=params)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/podiatry/recalls/{recall_id}", headers=headers)

    def complete_recall(self, recall_id, headers):
        return self._request("POST", f"/podiatry/recalls/{recall_id}/complete", headers=headers)

    def cancel_recall(self, recall_id, headers):
        return self._request("POST", f"/podiatry/recalls/{recall_id}/cancel", headers=headers)


api_client = ApiClient()
