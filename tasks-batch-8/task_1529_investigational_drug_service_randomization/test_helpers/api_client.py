"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Studies ---
    def create_study(self, payload, headers):
        return self._request("POST", "/api/studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/api/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/api/studies/{study_id}", headers=headers)

    def transition_study(self, study_id, payload, headers):
        return self._request("POST", f"/api/studies/{study_id}/transition", payload, headers)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def transition_site(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/transition", payload, headers)

    # --- Pharmacy staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/api/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/api/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/api/staff/{staff_id}", headers=headers)

    # --- Lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/api/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/api/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    # --- Shipments / kits ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def list_kits(self, headers, params=None):
        return self._request("GET", "/api/kits", headers=headers, params=params)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/api/kits/{kit_id}", headers=headers)

    def receive_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/api/kits/{kit_id}/receive", payload, headers)

    def release_kit(self, kit_id, headers):
        return self._request("POST", f"/api/kits/{kit_id}/release", headers=headers)

    # --- Temperature logs / excursions ---
    def create_temperature_log(self, payload, headers):
        return self._request("POST", "/api/temperature-logs", payload, headers)

    def list_temperature_logs(self, headers, params=None):
        return self._request("GET", "/api/temperature-logs", headers=headers, params=params)

    def get_temperature_log(self, log_id, headers):
        return self._request("GET", f"/api/temperature-logs/{log_id}", headers=headers)

    def list_temperature_excursions(self, headers, params=None):
        return self._request("GET", "/api/temperature-excursions", headers=headers, params=params)

    def get_temperature_excursion(self, excursion_id, headers):
        return self._request("GET", f"/api/temperature-excursions/{excursion_id}", headers=headers)

    def assess_temperature_excursion(self, excursion_id, payload, headers):
        return self._request("POST", f"/api/temperature-excursions/{excursion_id}/assess", payload, headers)

    # --- Subjects / randomization ---
    def create_subject(self, payload, headers):
        return self._request("POST", "/api/subjects", payload, headers)

    def list_subjects(self, headers, params=None):
        return self._request("GET", "/api/subjects", headers=headers, params=params)

    def get_subject(self, subject_id, headers):
        return self._request("GET", f"/api/subjects/{subject_id}", headers=headers)

    def transition_subject(self, subject_id, payload, headers):
        return self._request("POST", f"/api/subjects/{subject_id}/transition", payload, headers)

    def randomize_subject(self, subject_id, headers):
        return self._request("POST", f"/api/subjects/{subject_id}/randomize", headers=headers)

    def allocate_kit(self, subject_id, headers):
        return self._request("POST", f"/api/subjects/{subject_id}/allocate-kit", headers=headers)

    def replace_randomization_slots(self, study_id, payload, headers):
        return self._request(
            "POST", f"/api/studies/{study_id}/randomization-slots/replace", payload, headers
        )

    def list_randomization_slots(self, headers, params=None):
        return self._request("GET", "/api/randomization-slots", headers=headers, params=params)

    def get_randomization_slot(self, slot_id, headers):
        return self._request("GET", f"/api/randomization-slots/{slot_id}", headers=headers)

    # --- Dispensing / returns ---
    def create_dispensing_record(self, payload, headers):
        return self._request("POST", "/api/dispensing-records", payload, headers)

    def list_dispensing_records(self, headers, params=None):
        return self._request("GET", "/api/dispensing-records", headers=headers, params=params)

    def get_dispensing_record(self, record_id, headers):
        return self._request("GET", f"/api/dispensing-records/{record_id}", headers=headers)

    def create_return(self, payload, headers):
        return self._request("POST", "/api/returns", payload, headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/api/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/api/returns/{return_id}", headers=headers)

    def verify_return(self, return_id, headers):
        return self._request("POST", f"/api/returns/{return_id}/verify", headers=headers)

    # --- Destruction ---
    def create_destruction_record(self, payload, headers):
        return self._request("POST", "/api/destruction-records", payload, headers)

    def list_destruction_records(self, headers, params=None):
        return self._request("GET", "/api/destruction-records", headers=headers, params=params)

    def get_destruction_record(self, record_id, headers):
        return self._request("GET", f"/api/destruction-records/{record_id}", headers=headers)

    def attest_destruction_record(self, record_id, payload, headers):
        return self._request("POST", f"/api/destruction-records/{record_id}/attest", payload, headers)

    def finalize_destruction_record(self, record_id, headers):
        return self._request("POST", f"/api/destruction-records/{record_id}/finalize", headers=headers)

    # --- Unblinding ---
    def create_unblinding_request(self, payload, headers):
        return self._request("POST", "/api/unblinding-requests", payload, headers)

    def list_unblinding_requests(self, headers, params=None):
        return self._request("GET", "/api/unblinding-requests", headers=headers, params=params)

    def get_unblinding_request(self, request_id, headers):
        return self._request("GET", f"/api/unblinding-requests/{request_id}", headers=headers)

    def decide_unblinding_request(self, request_id, payload, headers):
        return self._request("POST", f"/api/unblinding-requests/{request_id}/decide", payload, headers)

    def execute_unblinding_request(self, request_id, headers):
        return self._request("POST", f"/api/unblinding-requests/{request_id}/execute", headers=headers)

    # --- Monitor visits ---
    def create_monitor_visit(self, payload, headers):
        return self._request("POST", "/api/monitor-visits", payload, headers)

    def list_monitor_visits(self, headers, params=None):
        return self._request("GET", "/api/monitor-visits", headers=headers, params=params)

    def get_monitor_visit(self, visit_id, headers):
        return self._request("GET", f"/api/monitor-visits/{visit_id}", headers=headers)

    def start_monitor_visit(self, visit_id, headers):
        return self._request("POST", f"/api/monitor-visits/{visit_id}/start", headers=headers)

    def close_monitor_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/api/monitor-visits/{visit_id}/close", payload, headers)

    # --- Fee schedules / invoice ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/api/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/api/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/api/fee-schedules/{schedule_id}", headers=headers)

    def approve_fee_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/api/fee-schedules/{schedule_id}/approve", payload, headers)

    def get_site_invoice(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/invoice", headers=headers, params=params)

    # --- Test-driving ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_expiry_sweep(self, headers):
        return self._request("POST", "/api/_ops/expiry_sweep", headers=headers)


api_client = ApiClient()
