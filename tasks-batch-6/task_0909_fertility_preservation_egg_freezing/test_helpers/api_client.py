"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers=headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- Provider / Room / Tank ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers=headers)

    def create_procedure_room(self, payload, headers):
        return self._request("POST", "/procedure-rooms", payload, headers=headers)

    def create_storage_tank(self, payload, headers):
        return self._request("POST", "/storage-tanks", payload, headers=headers)

    def get_storage_tank(self, tank_id, headers):
        return self._request("GET", f"/storage-tanks/{tank_id}", headers=headers)

    # ---- Consultation ----
    def create_consultation(self, payload, headers):
        return self._request("POST", "/consultations", payload, headers=headers)

    def get_consultation(self, consultation_id, headers):
        return self._request("GET", f"/consultations/{consultation_id}", headers=headers)

    def list_consultations(self, headers, params=None):
        return self._request("GET", "/consultations", headers=headers, params=params)

    def complete_consultation(self, consultation_id, headers):
        return self._request("POST", f"/consultations/{consultation_id}/complete", {}, headers=headers)

    # ---- StimulationCycle ----
    def create_stimulation_cycle(self, payload, headers):
        return self._request("POST", "/stimulation-cycles", payload, headers=headers)

    def get_stimulation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/stimulation-cycles/{cycle_id}", headers=headers)

    def list_stimulation_cycles(self, headers, params=None):
        return self._request("GET", "/stimulation-cycles", headers=headers, params=params)

    def schedule_cycle(self, cycle_id, headers):
        return self._request("POST", f"/stimulation-cycles/{cycle_id}/schedule", {}, headers=headers)

    def suspend_cycle(self, cycle_id, headers):
        return self._request("POST", f"/stimulation-cycles/{cycle_id}/suspend", {}, headers=headers)

    def resume_cycle(self, cycle_id, headers):
        return self._request("POST", f"/stimulation-cycles/{cycle_id}/resume", {}, headers=headers)

    def trigger_cycle(self, cycle_id, headers):
        return self._request("POST", f"/stimulation-cycles/{cycle_id}/trigger", {}, headers=headers)

    def retrieve_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/stimulation-cycles/{cycle_id}/retrieve", payload, headers=headers)

    def cancel_cycle(self, cycle_id, headers):
        return self._request("POST", f"/stimulation-cycles/{cycle_id}/cancel", {}, headers=headers)

    # ---- MonitoringAppointment ----
    def create_monitoring_appointment(self, payload, headers):
        return self._request("POST", "/monitoring-appointments", payload, headers=headers)

    def get_monitoring_appointment(self, appt_id, headers):
        return self._request("GET", f"/monitoring-appointments/{appt_id}", headers=headers)

    def list_monitoring_appointments(self, headers, params=None):
        return self._request("GET", "/monitoring-appointments", headers=headers, params=params)

    # ---- CryoSpecimen ----
    def get_cryo_specimen(self, specimen_id, headers):
        return self._request("GET", f"/cryo-specimens/{specimen_id}", headers=headers)

    def list_cryo_specimens(self, headers, params=None):
        return self._request("GET", "/cryo-specimens", headers=headers, params=params)

    # ---- StorageSubscription ----
    def create_storage_subscription(self, payload, headers):
        return self._request("POST", "/storage-subscriptions", payload, headers=headers)

    def get_storage_subscription(self, sub_id, headers):
        return self._request("GET", f"/storage-subscriptions/{sub_id}", headers=headers)

    def list_storage_subscriptions(self, headers, params=None):
        return self._request("GET", "/storage-subscriptions", headers=headers, params=params)

    def record_subscription_payment(self, sub_id, headers):
        return self._request("POST", f"/storage-subscriptions/{sub_id}/record-payment", {}, headers=headers)

    def renew_subscription(self, sub_id, headers):
        return self._request("POST", f"/storage-subscriptions/{sub_id}/renew", {}, headers=headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/storage-subscriptions/{sub_id}/cancel", {}, headers=headers)

    # ---- BenefitCoverage ----
    def create_benefit_coverage(self, payload, headers):
        return self._request("POST", "/benefit-coverages", payload, headers=headers)

    def get_benefit_coverage(self, benefit_id, headers):
        return self._request("GET", f"/benefit-coverages/{benefit_id}", headers=headers)

    def list_benefit_coverages(self, headers, params=None):
        return self._request("GET", "/benefit-coverages", headers=headers, params=params)

    # ---- Directive ----
    def create_directive(self, payload, headers):
        return self._request("POST", "/directives", payload, headers=headers)

    def get_directive(self, directive_id, headers):
        return self._request("GET", f"/directives/{directive_id}", headers=headers)

    def list_directives(self, headers, params=None):
        return self._request("GET", "/directives", headers=headers, params=params)

    def revoke_directive(self, directive_id, headers):
        return self._request("POST", f"/directives/{directive_id}/revoke", {}, headers=headers)

    # ---- ThawTransferAuthorization ----
    def create_thaw_authorization(self, payload, headers):
        return self._request("POST", "/thaw-transfer-authorizations", payload, headers=headers)

    def get_thaw_authorization(self, auth_id, headers):
        return self._request("GET", f"/thaw-transfer-authorizations/{auth_id}", headers=headers)

    def list_thaw_authorizations(self, headers, params=None):
        return self._request("GET", "/thaw-transfer-authorizations", headers=headers, params=params)

    def authorize_thaw(self, auth_id, headers):
        return self._request("POST", f"/thaw-transfer-authorizations/{auth_id}/authorize", {}, headers=headers)

    def execute_thaw(self, auth_id, headers):
        return self._request("POST", f"/thaw-transfer-authorizations/{auth_id}/execute", {}, headers=headers)

    def deny_thaw(self, auth_id, headers):
        return self._request("POST", f"/thaw-transfer-authorizations/{auth_id}/deny", {}, headers=headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers=headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
