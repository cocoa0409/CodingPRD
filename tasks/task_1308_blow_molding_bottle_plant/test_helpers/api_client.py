"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/plant/_clock/set_current_utc", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/plant/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/plant/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/plant/customers/{customer_id}/suspend", headers=headers)

    def reactivate_customer(self, customer_id, headers):
        return self._request("POST", f"/plant/customers/{customer_id}/reactivate", headers=headers)

    def list_customer_bottle_specs(self, customer_id, headers, params=None):
        return self._request("GET", f"/plant/customers/{customer_id}/bottle-specs",
                             headers=headers, params=params)

    # --- freight rate cards & quotes ---
    def create_freight_rate_card(self, payload, headers):
        return self._request("POST", "/plant/freight-rate-cards", payload, headers)

    def get_freight_rate_card(self, card_id, headers):
        return self._request("GET", f"/plant/freight-rate-cards/{card_id}", headers=headers)

    def create_freight_quote(self, payload, headers):
        return self._request("POST", "/plant/freight-quotes", payload, headers)

    # --- machine lines ---
    def create_machine_line(self, payload, headers):
        return self._request("POST", "/plant/machine-lines", payload, headers)

    def get_machine_line(self, line_id, headers):
        return self._request("GET", f"/plant/machine-lines/{line_id}", headers=headers)

    def list_machine_line_molds(self, line_id, headers):
        return self._request("GET", f"/plant/machine-lines/{line_id}/molds", headers=headers)

    def list_machine_line_schedule_slots(self, line_id, headers, params=None):
        return self._request("GET", f"/plant/machine-lines/{line_id}/schedule-slots",
                             headers=headers, params=params)

    def get_throughput_preview(self, line_id, headers, params=None):
        return self._request("GET", f"/plant/machine-lines/{line_id}/throughput-preview",
                             headers=headers, params=params)

    # --- molds ---
    def create_mold(self, payload, headers):
        return self._request("POST", "/plant/molds", payload, headers)

    def get_mold(self, mold_id, headers):
        return self._request("GET", f"/plant/molds/{mold_id}", headers=headers)

    def install_mold(self, mold_id, payload, headers):
        return self._request("POST", f"/plant/molds/{mold_id}/install", payload, headers)

    def remove_mold(self, mold_id, headers):
        return self._request("POST", f"/plant/molds/{mold_id}/remove", headers=headers)

    def list_mold_schedule_slots(self, mold_id, headers, params=None):
        return self._request("GET", f"/plant/molds/{mold_id}/schedule-slots",
                             headers=headers, params=params)

    # --- cavity blockouts ---
    def create_cavity_blockout(self, mold_id, payload, headers):
        return self._request("POST", f"/plant/molds/{mold_id}/cavity-blockouts", payload, headers)

    def list_mold_cavity_blockouts(self, mold_id, headers, params=None):
        return self._request("GET", f"/plant/molds/{mold_id}/cavity-blockouts",
                             headers=headers, params=params)

    def get_cavity_blockout(self, blockout_id, headers):
        return self._request("GET", f"/plant/cavity-blockouts/{blockout_id}", headers=headers)

    def clear_cavity_blockout(self, blockout_id, headers):
        return self._request("POST", f"/plant/cavity-blockouts/{blockout_id}/clear", headers=headers)

    # --- bottle specs ---
    def create_bottle_spec(self, payload, headers):
        return self._request("POST", "/plant/bottle-specs", payload, headers)

    def get_bottle_spec(self, spec_id, headers):
        return self._request("GET", f"/plant/bottle-specs/{spec_id}", headers=headers)

    def patch_bottle_spec(self, spec_id, payload, headers):
        return self._request("PATCH", f"/plant/bottle-specs/{spec_id}", payload, headers)

    def submit_bottle_spec(self, spec_id, headers):
        return self._request("POST", f"/plant/bottle-specs/{spec_id}/submit", headers=headers)

    def begin_qualification(self, spec_id, headers):
        return self._request("POST", f"/plant/bottle-specs/{spec_id}/begin-qualification",
                             headers=headers)

    def retire_bottle_spec(self, spec_id, headers):
        return self._request("POST", f"/plant/bottle-specs/{spec_id}/retire", headers=headers)

    def list_bottle_spec_qualification_runs(self, spec_id, headers, params=None):
        return self._request("GET", f"/plant/bottle-specs/{spec_id}/qualification-runs",
                             headers=headers, params=params)

    def get_logistics_comparison(self, spec_id, headers, params=None):
        return self._request("GET", f"/plant/bottle-specs/{spec_id}/logistics-comparison",
                             headers=headers, params=params)

    # --- qualification runs ---
    def create_qualification_run(self, payload, headers):
        return self._request("POST", "/plant/qualification-runs", payload, headers)

    def get_qualification_run(self, run_id, headers):
        return self._request("GET", f"/plant/qualification-runs/{run_id}", headers=headers)

    def execute_qualification_run(self, run_id, payload, headers):
        return self._request("POST", f"/plant/qualification-runs/{run_id}/execute",
                             payload, headers)

    def submit_qualification_review(self, run_id, headers):
        return self._request("POST", f"/plant/qualification-runs/{run_id}/submit-review",
                             headers=headers)

    def review_qualification_run(self, run_id, payload, headers):
        return self._request("POST", f"/plant/qualification-runs/{run_id}/review",
                             payload, headers)

    # --- material lots ---
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/plant/material-lots", payload, headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/plant/material-lots", headers=headers, params=params)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/plant/material-lots/{lot_id}", headers=headers)

    def release_material_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/material-lots/{lot_id}/release", headers=headers)

    def hold_material_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/material-lots/{lot_id}/hold", headers=headers)

    def reject_material_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/material-lots/{lot_id}/reject", headers=headers)

    # --- production orders ---
    def create_production_order(self, payload, headers):
        return self._request("POST", "/plant/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        return self._request("GET", "/plant/production-orders", headers=headers, params=params)

    def get_production_order(self, order_id, headers):
        return self._request("GET", f"/plant/production-orders/{order_id}", headers=headers)

    def get_production_order_summary(self, order_id, headers):
        return self._request("GET", f"/plant/production-orders/{order_id}/summary",
                             headers=headers)

    def schedule_production_order(self, order_id, payload, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/schedule",
                             payload, headers)

    def reschedule_production_order(self, order_id, payload, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/reschedule",
                             payload, headers)

    def release_production_order(self, order_id, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/release",
                             headers=headers)

    def hold_production_order(self, order_id, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/hold", headers=headers)

    def cancel_production_order(self, order_id, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/cancel", headers=headers)

    def complete_production_order(self, order_id, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/complete",
                             headers=headers)

    def list_order_schedule_slots(self, order_id, headers, params=None):
        return self._request("GET", f"/plant/production-orders/{order_id}/schedule-slots",
                             headers=headers, params=params)

    # --- production runs ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/plant/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/plant/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/plant/production-runs/{run_id}", headers=headers)

    def close_production_run(self, run_id, payload, headers):
        return self._request("POST", f"/plant/production-runs/{run_id}/close", payload, headers)

    def void_production_run(self, run_id, headers):
        return self._request("POST", f"/plant/production-runs/{run_id}/void", headers=headers)

    # --- quality test lots ---
    def list_quality_test_lots(self, headers, params=None):
        return self._request("GET", "/plant/quality-test-lots", headers=headers, params=params)

    def get_quality_test_lot(self, lot_id, headers):
        return self._request("GET", f"/plant/quality-test-lots/{lot_id}", headers=headers)

    def sample_quality_test_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/quality-test-lots/{lot_id}/sample", headers=headers)

    def record_quality_test_results(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/quality-test-lots/{lot_id}/record-results",
                             payload, headers)

    def disposition_quality_test_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/quality-test-lots/{lot_id}/disposition",
                             payload, headers)

    # --- shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/plant/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/plant/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/plant/shipments/{shipment_id}", headers=headers)

    def book_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/plant/shipments/{shipment_id}/book", payload, headers)

    def load_shipment(self, shipment_id, headers):
        return self._request("POST", f"/plant/shipments/{shipment_id}/load", headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/plant/shipments/{shipment_id}/dispatch", headers=headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/plant/shipments/{shipment_id}/deliver", headers=headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/plant/shipments/{shipment_id}/cancel", headers=headers)

    # --- dock appointments ---
    def create_dock_appointment(self, payload, headers):
        return self._request("POST", "/plant/dock-appointments", payload, headers)

    def list_dock_appointments(self, headers, params=None):
        return self._request("GET", "/plant/dock-appointments", headers=headers, params=params)

    def get_dock_appointment(self, appointment_id, headers):
        return self._request("GET", f"/plant/dock-appointments/{appointment_id}", headers=headers)

    def list_appointment_shipments(self, appointment_id, headers):
        return self._request("GET", f"/plant/dock-appointments/{appointment_id}/shipments",
                             headers=headers)

    def no_show_dock_appointment(self, appointment_id, headers):
        return self._request("POST", f"/plant/dock-appointments/{appointment_id}/no-show",
                             headers=headers)

    def cancel_dock_appointment(self, appointment_id, headers):
        return self._request("POST", f"/plant/dock-appointments/{appointment_id}/cancel",
                             headers=headers)

    # --- schedule slots ---
    def get_schedule_slot(self, slot_id, headers):
        return self._request("GET", f"/plant/schedule-slots/{slot_id}", headers=headers)

    def cancel_schedule_slot(self, slot_id, headers):
        return self._request("POST", f"/plant/schedule-slots/{slot_id}/cancel", headers=headers)


api_client = ApiClient()
