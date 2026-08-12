"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


def _clean_params(params):
    return {k: v for k, v in (params or {}).items() if v is not None}


class ApiClient(GenericApiClient):
    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/pap/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/pap/programs", headers=headers, params=_clean_params(params))

    def get_program(self, program_id, headers):
        return self._request("GET", f"/pap/programs/{program_id}", headers=headers)

    def update_program(self, program_id, payload, headers):
        return self._request("PUT", f"/pap/programs/{program_id}", payload, headers)

    def get_program_utilization(self, program_id, headers):
        return self._request("GET", f"/pap/programs/{program_id}/utilization", headers=headers)

    # --- Budget periods ---
    def create_budget_period(self, payload, headers):
        return self._request("POST", "/pap/budget-periods", payload, headers)

    def list_budget_periods(self, headers, params=None):
        return self._request("GET", "/pap/budget-periods", headers=headers, params=_clean_params(params))

    def get_budget_period(self, period_id, headers):
        return self._request("GET", f"/pap/budget-periods/{period_id}", headers=headers)

    def close_budget_period(self, period_id, headers):
        return self._request("POST", f"/pap/budget-periods/{period_id}/close", {}, headers)

    # --- Patients / Prescribers ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/pap/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/pap/patients/{patient_id}", headers=headers)

    def create_prescriber(self, payload, headers):
        return self._request("POST", "/pap/prescribers", payload, headers)

    def get_prescriber(self, prescriber_id, headers):
        return self._request("GET", f"/pap/prescribers/{prescriber_id}", headers=headers)

    # --- Screenings ---
    def create_screening(self, payload, headers):
        return self._request("POST", "/pap/screenings", payload, headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/pap/screenings", headers=headers, params=_clean_params(params))

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/pap/screenings/{screening_id}", headers=headers)

    def submit_screening(self, screening_id, headers):
        return self._request("POST", f"/pap/screenings/{screening_id}/submit", {}, headers)

    def decide_screening(self, screening_id, payload, headers):
        return self._request("POST", f"/pap/screenings/{screening_id}/decision", payload, headers)

    def revise_screening(self, screening_id, headers):
        return self._request("POST", f"/pap/screenings/{screening_id}/revise", {}, headers)

    # --- Screening documents ---
    def upload_screening_document(self, screening_id, payload, headers):
        return self._request("POST", f"/pap/screenings/{screening_id}/documents", payload, headers)

    def list_screening_documents(self, screening_id, headers, params=None):
        return self._request("GET", f"/pap/screenings/{screening_id}/documents", headers=headers, params=_clean_params(params))

    def review_document(self, document_id, payload, headers):
        return self._request("POST", f"/pap/documents/{document_id}/review", payload, headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/pap/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/pap/applications", headers=headers, params=_clean_params(params))

    def get_application(self, application_id, headers):
        return self._request("GET", f"/pap/applications/{application_id}", headers=headers)

    def claim_application(self, application_id, headers):
        return self._request("POST", f"/pap/applications/{application_id}/claim", {}, headers)

    def request_info(self, application_id, payload, headers):
        return self._request("POST", f"/pap/applications/{application_id}/request-info", payload, headers)

    def resubmit_application(self, application_id, payload, headers):
        return self._request("POST", f"/pap/applications/{application_id}/resubmit", payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/pap/applications/{application_id}/decision", payload, headers)

    def create_appeal(self, application_id, payload, headers):
        return self._request("POST", f"/pap/applications/{application_id}/appeals", payload, headers)

    # --- Appeals ---
    def list_appeals(self, headers, params=None):
        return self._request("GET", "/pap/appeals", headers=headers, params=_clean_params(params))

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/pap/appeals/{appeal_id}", headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/pap/appeals/{appeal_id}/decision", payload, headers)

    # --- Enrollments ---
    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/pap/enrollments", headers=headers, params=_clean_params(params))

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/pap/enrollments/{enrollment_id}", headers=headers)

    def create_renewal_application(self, enrollment_id, payload, headers):
        return self._request("POST", f"/pap/enrollments/{enrollment_id}/renewal-applications", payload, headers)

    def terminate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/pap/enrollments/{enrollment_id}/terminate", payload, headers)

    def reinstate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/pap/enrollments/{enrollment_id}/reinstate", payload, headers)

    # --- Changes of circumstance ---
    def report_circumstance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/pap/enrollments/{enrollment_id}/circumstances", payload, headers)

    def list_circumstances(self, headers, params=None):
        return self._request("GET", "/pap/circumstances", headers=headers, params=_clean_params(params))

    def get_circumstance(self, circumstance_id, headers):
        return self._request("GET", f"/pap/circumstances/{circumstance_id}", headers=headers)

    def review_circumstance(self, circumstance_id, payload, headers):
        return self._request("POST", f"/pap/circumstances/{circumstance_id}/review", payload, headers)

    # --- Copay cards ---
    def create_copay_card(self, payload, headers):
        return self._request("POST", "/pap/copay-cards", payload, headers)

    def list_copay_cards(self, headers, params=None):
        return self._request("GET", "/pap/copay-cards", headers=headers, params=_clean_params(params))

    def get_copay_card(self, card_id, headers):
        return self._request("GET", f"/pap/copay-cards/{card_id}", headers=headers)

    def suspend_copay_card(self, card_id, headers):
        return self._request("POST", f"/pap/copay-cards/{card_id}/suspend", {}, headers)

    def terminate_copay_card(self, card_id, payload, headers):
        return self._request("POST", f"/pap/copay-cards/{card_id}/terminate", payload, headers)

    # --- Inventory ---
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/pap/inventory-lots", payload, headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/pap/inventory-lots", headers=headers, params=_clean_params(params))

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/pap/inventory-lots/{lot_id}", headers=headers)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/pap/inventory-lots/{lot_id}/quarantine", payload, headers)

    def list_lot_lines(self, lot_id, headers, params=None):
        return self._request("GET", f"/pap/inventory-lots/{lot_id}/lines", headers=headers, params=_clean_params(params))

    def list_lot_dispense_events(self, lot_id, headers, params=None):
        return self._request("GET", f"/pap/inventory-lots/{lot_id}/dispense-events", headers=headers, params=_clean_params(params))

    # --- Shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/pap/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/pap/shipments", headers=headers, params=_clean_params(params))

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/pap/shipments/{shipment_id}", headers=headers)

    def list_shipment_lines(self, shipment_id, headers, params=None):
        return self._request("GET", f"/pap/shipments/{shipment_id}/lines", headers=headers, params=_clean_params(params))

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/pap/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/pap/shipments/{shipment_id}/deliver", {}, headers)

    def cancel_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/pap/shipments/{shipment_id}/cancel", payload, headers)

    def return_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/pap/shipments/{shipment_id}/return", payload, headers)

    # --- Dispensing ---
    def create_dispense_event(self, shipment_id, payload, headers):
        return self._request("POST", f"/pap/shipments/{shipment_id}/dispense-events", payload, headers)

    def list_shipment_dispense_events(self, shipment_id, headers, params=None):
        return self._request("GET", f"/pap/shipments/{shipment_id}/dispense-events", headers=headers, params=_clean_params(params))

    # --- Reconciliation ---
    def create_reconciliation_run(self, payload, headers):
        return self._request("POST", "/pap/reconciliation-runs", payload, headers)

    def list_reconciliation_runs(self, headers, params=None):
        return self._request("GET", "/pap/reconciliation-runs", headers=headers, params=_clean_params(params))

    def get_reconciliation_run(self, run_id, headers):
        return self._request("GET", f"/pap/reconciliation-runs/{run_id}", headers=headers)

    # --- Test-driving endpoints ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_daily_sweep(self, headers, payload=None):
        return self._request("POST", "/_system/run-daily-sweep", payload or {}, headers)


api_client = ApiClient()
