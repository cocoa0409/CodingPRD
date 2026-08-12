"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Owners / Pets ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def update_owner(self, owner_id, payload, headers):
        return self._request("PATCH", f"/owners/{owner_id}", payload, headers)

    def list_owner_pets(self, owner_id, headers, params=None):
        return self._request("GET", f"/owners/{owner_id}/pets", headers=headers, params=params)

    def create_pet(self, owner_id, payload, headers):
        return self._request("POST", f"/owners/{owner_id}/pets", payload, headers)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/pets/{pet_id}", headers=headers)

    def update_pet(self, pet_id, payload, headers):
        return self._request("PATCH", f"/pets/{pet_id}", payload, headers)

    # --- Veterinarians ---
    def create_veterinarian(self, payload, headers):
        return self._request("POST", "/veterinarians", payload, headers)

    def get_veterinarian(self, vet_id, headers):
        return self._request("GET", f"/veterinarians/{vet_id}", headers=headers)

    def verify_veterinarian(self, vet_id, headers):
        return self._request("POST", f"/veterinarians/{vet_id}/verify", {}, headers)

    def suspend_veterinarian(self, vet_id, headers):
        return self._request("POST", f"/veterinarians/{vet_id}/suspend", {}, headers)

    def reinstate_veterinarian(self, vet_id, headers):
        return self._request("POST", f"/veterinarians/{vet_id}/reinstate", {}, headers)

    def revoke_veterinarian(self, vet_id, headers):
        return self._request("POST", f"/veterinarians/{vet_id}/revoke", {}, headers)

    # --- Catalog / Flavorings / Formulas ---
    def create_drug_catalog_item(self, payload, headers):
        return self._request("POST", "/drug-catalog-items", payload, headers)

    def list_drug_catalog_items(self, headers, params=None):
        return self._request("GET", "/drug-catalog-items", headers=headers, params=params)

    def get_drug_catalog_item(self, drug_id, headers):
        return self._request("GET", f"/drug-catalog-items/{drug_id}", headers=headers)

    def update_drug_catalog_item(self, drug_id, payload, headers):
        return self._request("PATCH", f"/drug-catalog-items/{drug_id}", payload, headers)

    def list_drug_formulas(self, drug_id, headers, params=None):
        return self._request("GET", f"/drug-catalog-items/{drug_id}/formulas", headers=headers, params=params)

    def create_flavoring(self, payload, headers):
        return self._request("POST", "/flavorings", payload, headers)

    def list_flavorings(self, headers, params=None):
        return self._request("GET", "/flavorings", headers=headers, params=params)

    def get_flavoring(self, flavoring_id, headers):
        return self._request("GET", f"/flavorings/{flavoring_id}", headers=headers)

    def create_formula(self, payload, headers):
        return self._request("POST", "/formulas", payload, headers)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/formulas/{formula_id}", headers=headers)

    # --- Lots / DEA log ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def waste_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/waste", payload, headers)

    def list_controlled_substance_entries(self, headers, params=None):
        return self._request("GET", "/controlled-substance-entries", headers=headers, params=params)

    def get_controlled_substance_entry(self, entry_id, headers):
        return self._request("GET", f"/controlled-substance-entries/{entry_id}", headers=headers)

    # --- Prescriptions ---
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    def get_prescription(self, rx_id, headers):
        return self._request("GET", f"/prescriptions/{rx_id}", headers=headers)

    def submit_verification(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/submit-verification", {}, headers)

    def vet_confirm(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/vet-confirm", {}, headers)

    def vet_reject(self, rx_id, payload, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/vet-reject", payload, headers)

    def request_clarification(self, rx_id, payload, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/request-clarification", payload, headers)

    def resubmit_prescription(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/resubmit", {}, headers)

    def create_compound_order(self, rx_id, payload, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/compound-orders", payload, headers)

    def list_prescription_compound_orders(self, rx_id, headers, params=None):
        return self._request("GET", f"/prescriptions/{rx_id}/compound-orders", headers=headers, params=params)

    # --- Compound orders ---
    def list_compound_orders(self, headers, params=None):
        return self._request("GET", "/compound-orders", headers=headers, params=params)

    def get_compound_order(self, order_id, headers):
        return self._request("GET", f"/compound-orders/{order_id}", headers=headers)

    def list_order_allocations(self, order_id, headers, params=None):
        return self._request("GET", f"/compound-orders/{order_id}/allocations", headers=headers, params=params)

    def list_lot_allocations(self, headers, params=None):
        return self._request("GET", "/lot-allocations", headers=headers, params=params)

    def get_lot_allocation(self, allocation_id, headers):
        return self._request("GET", f"/lot-allocations/{allocation_id}", headers=headers)

    def allocate_order(self, order_id, headers):
        return self._request("POST", f"/compound-orders/{order_id}/allocate", {}, headers)

    def start_compounding(self, order_id, payload, headers):
        return self._request("POST", f"/compound-orders/{order_id}/start-compounding", payload, headers)

    def complete_compounding(self, order_id, headers):
        return self._request("POST", f"/compound-orders/{order_id}/complete-compounding", {}, headers)

    def complete_flavoring(self, order_id, headers):
        return self._request("POST", f"/compound-orders/{order_id}/complete-flavoring", {}, headers)

    def qa_pass(self, order_id, headers):
        return self._request("POST", f"/compound-orders/{order_id}/qa-pass", {}, headers)

    def qa_fail(self, order_id, payload, headers):
        return self._request("POST", f"/compound-orders/{order_id}/qa-fail", payload, headers)

    def resume_order(self, order_id, headers):
        return self._request("POST", f"/compound-orders/{order_id}/resume", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/compound-orders/{order_id}/cancel", {}, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/compound-orders/{order_id}/pay", payload, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/compound-orders/{order_id}/refund", {}, headers)

    # --- Shipments ---
    def create_shipment(self, order_id, payload, headers):
        return self._request("POST", f"/compound-orders/{order_id}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def add_temperature_reading(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/temperature-readings", payload, headers)

    def list_temperature_readings(self, shipment_id, headers, params=None):
        return self._request("GET", f"/shipments/{shipment_id}/temperature-readings", headers=headers, params=params)

    def mark_picked_up(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/mark-picked-up", {}, headers)

    def mark_in_transit(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/mark-in-transit", {}, headers)

    def mark_out_for_delivery(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/mark-out-for-delivery", {}, headers)

    def mark_delivered(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/mark-delivered", {}, headers)

    def report_exception(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/report-exception", payload, headers)

    def mark_returned(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/mark-returned", {}, headers)

    # --- Benches / Coolers ---
    def create_bench(self, payload, headers):
        return self._request("POST", "/compounding-benches", payload, headers)

    def get_bench(self, bench_id, headers):
        return self._request("GET", f"/compounding-benches/{bench_id}", headers=headers)

    def update_bench(self, bench_id, payload, headers):
        return self._request("PATCH", f"/compounding-benches/{bench_id}", payload, headers)

    def list_bench_reservations(self, headers, params=None):
        return self._request("GET", "/bench-reservations", headers=headers, params=params)

    def get_bench_reservation(self, reservation_id, headers):
        return self._request("GET", f"/bench-reservations/{reservation_id}", headers=headers)

    def create_cooler(self, payload, headers):
        return self._request("POST", "/cooler-assets", payload, headers)

    def get_cooler(self, cooler_id, headers):
        return self._request("GET", f"/cooler-assets/{cooler_id}", headers=headers)

    def list_coolers(self, headers, params=None):
        return self._request("GET", "/cooler-assets", headers=headers, params=params)

    def update_cooler(self, cooler_id, payload, headers):
        return self._request("PATCH", f"/cooler-assets/{cooler_id}", payload, headers)

    # --- Wellness ---
    def create_wellness_plan(self, payload, headers):
        return self._request("POST", "/wellness-plans", payload, headers)

    def list_wellness_plans(self, headers, params=None):
        return self._request("GET", "/wellness-plans", headers=headers, params=params)

    def get_wellness_plan(self, plan_id, headers):
        return self._request("GET", f"/wellness-plans/{plan_id}", headers=headers)

    def update_wellness_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/wellness-plans/{plan_id}", payload, headers)

    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def suspend_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/suspend", {}, headers)

    def resume_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/resume", {}, headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel", {}, headers)

    # --- Insurance ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/lapse", {}, headers)

    def create_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/appeal", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/pay", {}, headers)

    # --- Auto-ship ---
    def create_auto_ship_schedule(self, payload, headers):
        return self._request("POST", "/auto-ship-schedules", payload, headers)

    def get_auto_ship_schedule(self, schedule_id, headers):
        return self._request("GET", f"/auto-ship-schedules/{schedule_id}", headers=headers)

    def list_auto_ship_schedules(self, headers, params=None):
        return self._request("GET", "/auto-ship-schedules", headers=headers, params=params)

    def pause_auto_ship(self, schedule_id, headers):
        return self._request("POST", f"/auto-ship-schedules/{schedule_id}/pause", {}, headers)

    def resume_auto_ship(self, schedule_id, headers):
        return self._request("POST", f"/auto-ship-schedules/{schedule_id}/resume", {}, headers)

    def cancel_auto_ship(self, schedule_id, headers):
        return self._request("POST", f"/auto-ship-schedules/{schedule_id}/cancel", {}, headers)

    # --- Recalls ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def activate_recall(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/activate", {}, headers)

    def complete_recall(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/complete", {}, headers)

    def list_recall_tasks(self, recall_id, headers, params=None):
        return self._request("GET", f"/recalls/{recall_id}/tasks", headers=headers, params=params)

    def list_all_recall_tasks(self, headers, params=None):
        return self._request("GET", "/recall-tasks", headers=headers, params=params)

    def get_recall_task(self, task_id, headers):
        return self._request("GET", f"/recall-tasks/{task_id}", headers=headers)

    def mark_task_notified(self, task_id, headers):
        return self._request("POST", f"/recall-tasks/{task_id}/mark-notified", {}, headers)

    def mark_task_failed(self, task_id, headers):
        return self._request("POST", f"/recall-tasks/{task_id}/mark-failed", {}, headers)

    def acknowledge_task(self, task_id, headers):
        return self._request("POST", f"/recall-tasks/{task_id}/acknowledge", {}, headers)

    # --- Test-driving ops (PRD §3.8) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_auto_ship(self, headers):
        return self._request("POST", "/_ops/auto_ship_run", {}, headers)

    def run_expiration_sweep(self, headers):
        return self._request("POST", "/_ops/expiration_sweep", {}, headers)


api_client = ApiClient()
