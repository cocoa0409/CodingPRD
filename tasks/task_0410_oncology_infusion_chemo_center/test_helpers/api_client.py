"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /infusion-center prefix (PRD §2).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/infusion-center"


class ApiClient(GenericApiClient):
    # ---------- Patients ----------
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/patients/{patient_id}", payload, headers)

    def mark_patient_deceased(self, patient_id, headers):
        return self._request("POST", f"{PREFIX}/patients/{patient_id}/mark-deceased", headers=headers)

    # ---------- Regimen Protocols ----------
    def create_regimen_protocol(self, payload, headers):
        return self._request("POST", f"{PREFIX}/regimen-protocols", payload, headers)

    def list_regimen_protocols(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/regimen-protocols", headers=headers, params=params)

    def get_regimen_protocol(self, protocol_id, headers):
        return self._request("GET", f"{PREFIX}/regimen-protocols/{protocol_id}", headers=headers)

    def publish_regimen_protocol(self, protocol_id, headers):
        return self._request("POST", f"{PREFIX}/regimen-protocols/{protocol_id}/publish", headers=headers)

    # ---------- Order Set Items ----------
    def create_order_set_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/order-set-items", payload, headers)

    def list_order_set_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/order-set-items", headers=headers, params=params)

    def get_order_set_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/order-set-items/{item_id}", headers=headers)

    # ---------- Chairs ----------
    def create_chair(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chairs", payload, headers)

    def list_chairs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/chairs", headers=headers, params=params)

    def get_chair(self, chair_id, headers):
        return self._request("GET", f"{PREFIX}/chairs/{chair_id}", headers=headers)

    def close_chair(self, chair_id, headers):
        return self._request("POST", f"{PREFIX}/chairs/{chair_id}/close", headers=headers)

    # ---------- Nurses ----------
    def create_nurse(self, payload, headers):
        return self._request("POST", f"{PREFIX}/nurses", payload, headers)

    def list_nurses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/nurses", headers=headers, params=params)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"{PREFIX}/nurses/{nurse_id}", headers=headers)

    # ---------- Prior Authorizations ----------
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prior-authorizations", payload, headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prior-authorizations", headers=headers, params=params)

    def get_prior_authorization(self, pa_id, headers):
        return self._request("GET", f"{PREFIX}/prior-authorizations/{pa_id}", headers=headers)

    def decide_prior_authorization(self, pa_id, payload, headers):
        return self._request("POST", f"{PREFIX}/prior-authorizations/{pa_id}/decide", payload, headers)

    # ---------- Treatment Cycles ----------
    def create_treatment_cycle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/treatment-cycles", payload, headers)

    def list_treatment_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/treatment-cycles", headers=headers, params=params)

    def get_treatment_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/treatment-cycles/{cycle_id}", headers=headers)

    def get_treatment_cycle_calendar(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/treatment-cycles/{cycle_id}/calendar", headers=headers)

    def activate_treatment_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-cycles/{cycle_id}/activate", headers=headers)

    def hold_treatment_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-cycles/{cycle_id}/hold", headers=headers)

    def resume_treatment_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-cycles/{cycle_id}/resume", headers=headers)

    def advance_treatment_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-cycles/{cycle_id}/advance-cycle", headers=headers)

    def abandon_treatment_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-cycles/{cycle_id}/abandon", headers=headers)

    # ---------- Drug Orders ----------
    def create_drug_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/drug-orders", payload, headers)

    def list_drug_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/drug-orders", headers=headers, params=params)

    def get_drug_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/drug-orders/{order_id}", headers=headers)

    def prepare_drug_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/drug-orders/{order_id}/prepare", headers=headers)

    def verify_drug_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/drug-orders/{order_id}/verify", payload, headers)

    def reject_drug_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/drug-orders/{order_id}/reject", headers=headers)

    def administer_drug_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/drug-orders/{order_id}/administer", headers=headers)

    def cancel_drug_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/drug-orders/{order_id}/cancel", headers=headers)

    # ---------- Infusion Appointments ----------
    def create_infusion_appointment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/infusion-appointments", payload, headers)

    def list_infusion_appointments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/infusion-appointments", headers=headers, params=params)

    def get_infusion_appointment(self, appointment_id, headers):
        return self._request("GET", f"{PREFIX}/infusion-appointments/{appointment_id}", headers=headers)

    def check_in_infusion_appointment(self, appointment_id, headers):
        return self._request("POST", f"{PREFIX}/infusion-appointments/{appointment_id}/check-in", headers=headers)

    def complete_infusion_appointment(self, appointment_id, headers):
        return self._request("POST", f"{PREFIX}/infusion-appointments/{appointment_id}/complete", headers=headers)

    def cancel_infusion_appointment(self, appointment_id, headers):
        return self._request("POST", f"{PREFIX}/infusion-appointments/{appointment_id}/cancel", headers=headers)

    # ---------- Toxicity Events ----------
    def create_toxicity_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/toxicity-events", payload, headers)

    def list_toxicity_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/toxicity-events", headers=headers, params=params)

    def get_toxicity_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/toxicity-events/{event_id}", headers=headers)


api_client = ApiClient()
