"""API client: one method per endpoint defined in the PRD.

Every collection is a peer at the API root, so each child record carries its
parent identifiers in its request body rather than in its path.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical plant clock ──────────────────────────────────────────────

    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Apparatus programs ───────────────────────────────────────────────

    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/suspend", headers=headers)

    def reactivate_program(self, program_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/reactivate", headers=headers
        )

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", headers=headers)

    def ops_run(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/ops-run", headers=headers)

    # ─── Bid specifications and clauses ───────────────────────────────────

    def create_specification(self, payload, headers):
        return self._request("POST", "/specifications", payload, headers)

    def list_specifications(self, headers, params=None):
        return self._request("GET", "/specifications", headers=headers, params=params)

    def get_specification(self, specification_id, headers):
        return self._request(
            "GET", f"/specifications/{specification_id}", headers=headers
        )

    def submit_specification_for_review(self, specification_id, headers):
        return self._request(
            "POST", f"/specifications/{specification_id}/submit-review", headers=headers
        )

    def rework_specification(self, specification_id, headers):
        return self._request(
            "POST", f"/specifications/{specification_id}/rework", headers=headers
        )

    def release_specification(self, specification_id, headers):
        return self._request(
            "POST", f"/specifications/{specification_id}/release", headers=headers
        )

    def add_clause(self, specification_id, payload, headers):
        return self._request(
            "POST", f"/specifications/{specification_id}/clauses", payload, headers
        )

    def list_clauses(self, headers, params=None):
        return self._request("GET", "/clauses", headers=headers, params=params)

    def get_clause(self, clause_id, headers):
        return self._request("GET", f"/clauses/{clause_id}", headers=headers)

    # ─── Compliance matrix ────────────────────────────────────────────────

    def create_compliance_entry(self, payload, headers):
        return self._request("POST", "/compliance-entries", payload, headers)

    def list_compliance_entries(self, headers, params=None):
        return self._request(
            "GET", "/compliance-entries", headers=headers, params=params
        )

    def get_compliance_entry(self, compliance_entry_id, headers):
        return self._request(
            "GET", f"/compliance-entries/{compliance_entry_id}", headers=headers
        )

    def dispose_compliance_entry(self, compliance_entry_id, payload, headers):
        return self._request(
            "POST",
            f"/compliance-entries/{compliance_entry_id}/dispose",
            payload,
            headers,
        )

    # ─── Unit orders ──────────────────────────────────────────────────────

    def create_unit_order(self, payload, headers):
        return self._request("POST", "/unit-orders", payload, headers)

    def list_unit_orders(self, headers, params=None):
        return self._request("GET", "/unit-orders", headers=headers, params=params)

    def get_unit_order(self, unit_order_id, headers):
        return self._request("GET", f"/unit-orders/{unit_order_id}", headers=headers)

    def start_production(self, unit_order_id, headers):
        return self._request(
            "POST", f"/unit-orders/{unit_order_id}/start-production", headers=headers
        )

    def final_inspection(self, unit_order_id, headers):
        return self._request(
            "POST", f"/unit-orders/{unit_order_id}/final-inspection", headers=headers
        )

    def deliver_unit_order(self, unit_order_id, payload, headers):
        return self._request(
            "POST", f"/unit-orders/{unit_order_id}/deliver", payload, headers
        )

    def cancel_unit_order(self, unit_order_id, headers):
        return self._request(
            "POST", f"/unit-orders/{unit_order_id}/cancel", headers=headers
        )

    # ─── Supplier slot lines ──────────────────────────────────────────────

    def create_slot_line(self, payload, headers):
        return self._request("POST", "/slot-lines", payload, headers)

    def list_slot_lines(self, headers, params=None):
        return self._request("GET", "/slot-lines", headers=headers, params=params)

    def get_slot_line(self, slot_line_id, headers):
        return self._request("GET", f"/slot-lines/{slot_line_id}", headers=headers)

    # ─── Chassis reservations ─────────────────────────────────────────────

    def create_chassis_reservation(self, payload, headers):
        return self._request("POST", "/chassis-reservations", payload, headers)

    def list_chassis_reservations(self, headers, params=None):
        return self._request(
            "GET", "/chassis-reservations", headers=headers, params=params
        )

    def get_chassis_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/chassis-reservations/{reservation_id}", headers=headers
        )

    def confirm_chassis_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/chassis-reservations/{reservation_id}/confirm", headers=headers
        )

    def release_chassis_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/chassis-reservations/{reservation_id}/release", headers=headers
        )

    # ─── Plant bays ───────────────────────────────────────────────────────

    def create_plant_bay(self, payload, headers):
        return self._request("POST", "/plant-bays", payload, headers)

    def list_plant_bays(self, headers, params=None):
        return self._request("GET", "/plant-bays", headers=headers, params=params)

    def get_plant_bay(self, plant_bay_id, headers):
        return self._request("GET", f"/plant-bays/{plant_bay_id}", headers=headers)

    # ─── Inspection trips ─────────────────────────────────────────────────

    def create_inspection_trip(self, payload, headers):
        return self._request("POST", "/inspection-trips", payload, headers)

    def list_inspection_trips(self, headers, params=None):
        return self._request("GET", "/inspection-trips", headers=headers, params=params)

    def get_inspection_trip(self, inspection_trip_id, headers):
        return self._request(
            "GET", f"/inspection-trips/{inspection_trip_id}", headers=headers
        )

    def hold_inspection_trip(self, inspection_trip_id, headers):
        return self._request(
            "POST", f"/inspection-trips/{inspection_trip_id}/hold", headers=headers
        )

    def cancel_inspection_trip(self, inspection_trip_id, headers):
        return self._request(
            "POST", f"/inspection-trips/{inspection_trip_id}/cancel", headers=headers
        )

    # ─── Change orders ────────────────────────────────────────────────────

    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def submit_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/submit", headers=headers
        )

    def negotiate_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/negotiate", headers=headers
        )

    def revise_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/revise", payload, headers
        )

    def approve_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/approve", headers=headers
        )

    def reject_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/reject", headers=headers
        )

    def rescind_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/rescind", headers=headers
        )

    # ─── Certification tests ──────────────────────────────────────────────

    def create_certification_test(self, payload, headers):
        return self._request("POST", "/certification-tests", payload, headers)

    def list_certification_tests(self, headers, params=None):
        return self._request(
            "GET", "/certification-tests", headers=headers, params=params
        )

    def get_certification_test(self, certification_test_id, headers):
        return self._request(
            "GET", f"/certification-tests/{certification_test_id}", headers=headers
        )

    def record_test_result(self, certification_test_id, payload, headers):
        return self._request(
            "POST",
            f"/certification-tests/{certification_test_id}/record-result",
            payload,
            headers,
        )

    # ─── Warranty startups ────────────────────────────────────────────────

    def list_warranty_startups(self, headers, params=None):
        return self._request("GET", "/warranty-startups", headers=headers, params=params)

    def get_warranty_startup(self, warranty_startup_id, headers):
        return self._request(
            "GET", f"/warranty-startups/{warranty_startup_id}", headers=headers
        )

    def complete_training(self, warranty_startup_id, payload, headers):
        return self._request(
            "POST",
            f"/warranty-startups/{warranty_startup_id}/complete-training",
            payload,
            headers,
        )


api_client = ApiClient()
