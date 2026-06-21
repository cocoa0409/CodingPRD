"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clinic ----
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/clinics", headers=headers, params=params)

    def run_ops(self, clinic_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/run-ops", {}, headers)

    # ---- ExamRoom ----
    def create_exam_room(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/exam-rooms", payload, headers)

    def list_clinic_exam_rooms(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/exam-rooms", headers=headers, params=params)

    def get_exam_room(self, room_id, headers):
        return self._request("GET", f"/exam-rooms/{room_id}", headers=headers)

    def list_exam_rooms(self, headers, params=None):
        return self._request("GET", "/exam-rooms", headers=headers, params=params)

    def mark_room_clean(self, clinic_id, room_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/exam-rooms/{room_id}/mark-clean", {}, headers)

    def take_room_offline(self, clinic_id, room_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/exam-rooms/{room_id}/take-offline", {}, headers)

    def return_room_online(self, clinic_id, room_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/exam-rooms/{room_id}/return-online", {}, headers)

    # ---- Provider ----
    def create_provider(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/providers", payload, headers)

    def list_clinic_providers(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    # ---- QueueEntry ----
    def create_queue_entry(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/queue-entries", payload, headers)

    def list_clinic_queue_entries(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/queue-entries", headers=headers, params=params)

    def get_queue_entry(self, queue_entry_id, headers):
        return self._request("GET", f"/queue-entries/{queue_entry_id}", headers=headers)

    def list_queue_entries(self, headers, params=None):
        return self._request("GET", "/queue-entries", headers=headers, params=params)

    def arrive_queue_entry(self, clinic_id, queue_entry_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/queue-entries/{queue_entry_id}/arrive", {}, headers)

    def triage_queue_entry(self, clinic_id, queue_entry_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/queue-entries/{queue_entry_id}/triage", payload, headers)

    def re_triage_queue_entry(self, clinic_id, queue_entry_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/queue-entries/{queue_entry_id}/re-triage", payload, headers)

    def mark_ready_queue_entry(self, clinic_id, queue_entry_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/queue-entries/{queue_entry_id}/mark-ready", {}, headers)

    def lwbs_queue_entry(self, clinic_id, queue_entry_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/queue-entries/{queue_entry_id}/lwbs", {}, headers)

    def cancel_queue_entry(self, clinic_id, queue_entry_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/queue-entries/{queue_entry_id}/cancel", {}, headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ---- Coverage ----
    def create_coverage(self, payload, headers):
        return self._request("POST", "/coverages", payload, headers)

    def list_coverages(self, headers, params=None):
        return self._request("GET", "/coverages", headers=headers, params=params)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"/coverages/{coverage_id}", headers=headers)

    def verify_coverage(self, coverage_id, payload, headers):
        return self._request("POST", f"/coverages/{coverage_id}/verify", payload, headers)

    # ---- Visit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def start_charting(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/start-charting", {}, headers)

    def complete_charting(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/complete-charting", payload, headers)

    def discharge_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/discharge", {}, headers)

    def transfer_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/transfer", payload, headers)

    def post_charges(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/post-charges", {}, headers)

    def invoice_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/invoice", {}, headers)

    def settle_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/settle", payload, headers)

    # ---- Charge ----
    def create_charge(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/charges", payload, headers)

    def list_charges(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/charges", headers=headers, params=params)

    def void_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/void", {}, headers)

    # ---- OccHealthOrder ----
    def create_occ_health_order(self, payload, headers):
        return self._request("POST", "/occ-health-orders", payload, headers)

    def list_occ_health_orders(self, headers, params=None):
        return self._request("GET", "/occ-health-orders", headers=headers, params=params)

    def get_occ_health_order(self, order_id, headers):
        return self._request("GET", f"/occ-health-orders/{order_id}", headers=headers)

    def start_occ_health_order(self, order_id, headers):
        return self._request("POST", f"/occ-health-orders/{order_id}/start", {}, headers)

    def result_occ_health_order(self, order_id, payload, headers):
        return self._request("POST", f"/occ-health-orders/{order_id}/result", payload, headers)

    def cancel_occ_health_order(self, order_id, headers):
        return self._request("POST", f"/occ-health-orders/{order_id}/cancel", {}, headers)

    # ---- Referral ----
    def list_visit_referrals(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/accept", {}, headers)

    def cancel_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/cancel", {}, headers)

    # ---- DischargeInstruction ----
    def create_discharge_instruction(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/discharge-instructions", payload, headers)

    def list_discharge_instructions(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/discharge-instructions", headers=headers, params=params)

    def get_discharge_instruction(self, di_id, headers):
        return self._request("GET", f"/discharge-instructions/{di_id}", headers=headers)

    # ---- Test-driving (clock + seed) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def seed_queue_depth(self, payload, headers):
        return self._request("POST", "/_seed/queue-depth", payload, headers)


api_client = ApiClient()
