"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability, PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Emission permits ---
    def create_emission_permit(self, payload, headers):
        return self._request("POST", "/emission-permits", payload, headers)

    def get_emission_permit(self, permit_id, headers):
        return self._request("GET", f"/emission-permits/{permit_id}", headers=headers)

    def close_emission_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/emission-permits/{permit_id}/close", {}, headers
        )

    # --- Molds ---
    def create_mold(self, payload, headers):
        return self._request("POST", "/molds", payload, headers)

    def get_mold(self, mold_id, headers):
        return self._request("GET", f"/molds/{mold_id}", headers=headers)

    def patch_mold(self, mold_id, payload, headers):
        return self._request("PATCH", f"/molds/{mold_id}", payload, headers)

    def start_mold_maintenance(self, mold_id, headers):
        return self._request(
            "POST", f"/molds/{mold_id}/start-maintenance", {}, headers
        )

    def complete_mold_maintenance(self, mold_id, headers):
        return self._request(
            "POST", f"/molds/{mold_id}/complete-maintenance", {}, headers
        )

    def transition_mold_phase(self, mold_id, target_phase, headers):
        return self._request(
            "POST",
            f"/molds/{mold_id}/transition-phase",
            {"target_phase": target_phase},
            headers,
        )

    def retire_mold(self, mold_id, headers):
        return self._request("POST", f"/molds/{mold_id}/retire", {}, headers)

    # --- Ply books ---
    def create_ply_book(self, payload, headers):
        return self._request("POST", "/ply-books", payload, headers)

    def get_ply_book(self, ply_book_id, headers):
        return self._request("GET", f"/ply-books/{ply_book_id}", headers=headers)

    def patch_ply_book(self, ply_book_id, payload, headers):
        return self._request("PATCH", f"/ply-books/{ply_book_id}", payload, headers)

    def approve_ply_book(self, ply_book_id, headers):
        return self._request("POST", f"/ply-books/{ply_book_id}/approve", {}, headers)

    # --- Work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def start_layup(self, work_order_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/start-layup", {}, headers
        )

    def complete_layup(self, work_order_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/complete-layup", {}, headers
        )

    def demold_work_order(self, work_order_id, actual_part_weight_g, headers):
        return self._request(
            "POST",
            f"/work-orders/{work_order_id}/demold",
            {"actual_part_weight_g": actual_part_weight_g},
            headers,
        )

    def scrap_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/scrap", {}, headers
        )

    # --- Resin batches ---
    def create_resin_batch(self, payload, headers):
        return self._request("POST", "/resin-batches", payload, headers)

    def get_resin_batch(self, batch_id, headers):
        return self._request("GET", f"/resin-batches/{batch_id}", headers=headers)

    def quench_resin_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/resin-batches/{batch_id}/quench", {}, headers
        )

    # --- Layup sessions ---
    def create_layup_session(self, payload, headers):
        return self._request("POST", "/layup-sessions", payload, headers)

    def get_layup_session(self, session_id, headers):
        return self._request("GET", f"/layup-sessions/{session_id}", headers=headers)

    def list_layup_sessions(self, headers, params=None):
        return self._request("GET", "/layup-sessions", headers=headers, params=params)

    def void_layup_session(self, session_id, headers):
        return self._request(
            "POST", f"/layup-sessions/{session_id}/void", {}, headers
        )

    # --- Cure equipment ---
    def create_cure_equipment(self, payload, headers):
        return self._request("POST", "/cure-equipment", payload, headers)

    def get_cure_equipment(self, equipment_id, headers):
        return self._request("GET", f"/cure-equipment/{equipment_id}", headers=headers)

    def equipment_out_of_service(self, equipment_id, headers):
        return self._request(
            "POST", f"/cure-equipment/{equipment_id}/out-of-service", {}, headers
        )

    def equipment_return_to_service(self, equipment_id, headers):
        return self._request(
            "POST", f"/cure-equipment/{equipment_id}/return-to-service", {}, headers
        )

    # --- Cure cycles ---
    def create_cure_cycle(self, payload, headers):
        return self._request("POST", "/cure-cycles", payload, headers)

    def get_cure_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cure-cycles/{cycle_id}", headers=headers)

    def list_cure_cycles(self, headers, params=None):
        return self._request("GET", "/cure-cycles", headers=headers, params=params)

    def start_cure_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cure-cycles/{cycle_id}/start", {}, headers)

    def complete_cure_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/cure-cycles/{cycle_id}/complete", payload, headers
        )

    def abort_cure_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cure-cycles/{cycle_id}/abort", {}, headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    # --- Repairs ---
    def get_repair(self, repair_id, headers):
        return self._request("GET", f"/repairs/{repair_id}", headers=headers)

    def list_repairs(self, headers, params=None):
        return self._request("GET", "/repairs", headers=headers, params=params)


api_client = ApiClient()
