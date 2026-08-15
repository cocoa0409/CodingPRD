"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Owners ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/api/owners", payload, headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/api/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/api/owners/{owner_id}", headers=headers)

    def list_owner_aircraft(self, owner_id, headers):
        return self._request("GET", f"/api/owners/{owner_id}/aircraft", headers=headers)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/api/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/api/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/api/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft_directives(self, aircraft_id, headers, params=None):
        return self._request(
            "GET", f"/api/aircraft/{aircraft_id}/directives", headers=headers, params=params
        )

    def list_aircraft_logbook_entries(self, aircraft_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/aircraft/{aircraft_id}/logbook-entries",
            headers=headers,
            params=params,
        )

    # --- Mechanics ---
    def create_mechanic(self, payload, headers):
        return self._request("POST", "/api/mechanics", payload, headers)

    def list_mechanics(self, headers, params=None):
        return self._request("GET", "/api/mechanics", headers=headers, params=params)

    def get_mechanic(self, mechanic_id, headers):
        return self._request("GET", f"/api/mechanics/{mechanic_id}", headers=headers)

    # --- Hangar slots ---
    def create_hangar_slot(self, payload, headers):
        return self._request("POST", "/api/hangar-slots", payload, headers)

    def list_hangar_slots(self, headers, params=None):
        return self._request("GET", "/api/hangar-slots", headers=headers, params=params)

    def get_hangar_slot(self, slot_id, headers):
        return self._request("GET", f"/api/hangar-slots/{slot_id}", headers=headers)

    # --- Work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/api/work-orders", headers=headers, params=params)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/api/work-orders/{wo_id}", headers=headers)

    def schedule_work_order(self, wo_id, headers):
        return self._request("POST", f"/api/work-orders/{wo_id}/schedule", {}, headers)

    def start_work_order(self, wo_id, headers):
        return self._request("POST", f"/api/work-orders/{wo_id}/start", {}, headers)

    def complete_inspection(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/complete-inspection", {}, headers
        )

    def submit_for_approval(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/submit-for-approval", {}, headers
        )

    def reopen_inspection(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/reopen-inspection", {}, headers
        )

    def begin_work(self, wo_id, headers):
        return self._request("POST", f"/api/work-orders/{wo_id}/begin-work", {}, headers)

    def ready_for_rts(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/ready-for-rts", {}, headers
        )

    def return_to_service(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/return-to-service", {}, headers
        )

    def close_work_order(self, wo_id, headers):
        return self._request("POST", f"/api/work-orders/{wo_id}/close", {}, headers)

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/api/work-orders/{wo_id}/cancel", {}, headers)

    # --- Checklist items ---
    def create_checklist_item(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/checklist-items", payload, headers
        )

    def list_checklist_items(self, wo_id, headers, params=None):
        return self._request(
            "GET", f"/api/work-orders/{wo_id}/checklist-items", headers=headers, params=params
        )

    def get_checklist_item(self, item_id, headers):
        return self._request("GET", f"/api/checklist-items/{item_id}", headers=headers)

    def list_checklist_items_global(self, headers, params=None):
        return self._request("GET", "/api/checklist-items", headers=headers, params=params)

    def record_checklist_item(self, wo_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"/api/work-orders/{wo_id}/checklist-items/{item_id}/record",
            payload,
            headers,
        )

    # --- Labor entries ---
    def create_labor_entry(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/labor-entries", payload, headers
        )

    def list_labor_entries(self, wo_id, headers, params=None):
        return self._request(
            "GET", f"/api/work-orders/{wo_id}/labor-entries", headers=headers, params=params
        )

    def get_labor_entry(self, entry_id, headers):
        return self._request("GET", f"/api/labor-entries/{entry_id}", headers=headers)

    def list_labor_entries_global(self, headers, params=None):
        return self._request("GET", "/api/labor-entries", headers=headers, params=params)

    # --- Discrepancies ---
    def get_discrepancy(self, discrepancy_id, headers):
        return self._request("GET", f"/api/discrepancies/{discrepancy_id}", headers=headers)

    def list_discrepancies(self, headers, params=None):
        return self._request("GET", "/api/discrepancies", headers=headers, params=params)

    def list_work_order_discrepancies(self, wo_id, headers, params=None):
        return self._request(
            "GET", f"/api/work-orders/{wo_id}/discrepancies", headers=headers, params=params
        )

    def decide_discrepancy(self, discrepancy_id, payload, headers):
        return self._request(
            "POST", f"/api/discrepancies/{discrepancy_id}/decide", payload, headers
        )

    def rectify_discrepancy(self, discrepancy_id, headers):
        return self._request(
            "POST", f"/api/discrepancies/{discrepancy_id}/rectify", {}, headers
        )

    def verify_discrepancy(self, discrepancy_id, payload, headers):
        return self._request(
            "POST", f"/api/discrepancies/{discrepancy_id}/verify", payload, headers
        )

    # --- Directives ---
    def create_directive(self, payload, headers):
        return self._request("POST", "/api/directives", payload, headers)

    def evaluate_directive(self, directive_id, payload, headers):
        return self._request(
            "POST", f"/api/directives/{directive_id}/evaluate", payload, headers
        )

    def list_directives(self, headers, params=None):
        return self._request("GET", "/api/directives", headers=headers, params=params)

    def get_directive(self, directive_id, headers):
        return self._request("GET", f"/api/directives/{directive_id}", headers=headers)

    # --- Parts ---
    def create_part(self, payload, headers):
        return self._request("POST", "/api/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/api/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/api/parts/{part_id}", headers=headers)

    def mark_part_sourced(self, part_id, headers):
        return self._request("POST", f"/api/parts/{part_id}/mark-sourced", {}, headers)

    def receive_part(self, part_id, headers):
        return self._request("POST", f"/api/parts/{part_id}/receive", {}, headers)

    def install_part(self, part_id, headers):
        return self._request("POST", f"/api/parts/{part_id}/install", {}, headers)

    def return_part(self, part_id, headers):
        return self._request("POST", f"/api/parts/{part_id}/return", {}, headers)

    # --- Logbook entries ---
    def create_logbook_entry(self, payload, headers):
        return self._request("POST", "/api/logbook-entries", payload, headers)

    def list_logbook_entries(self, headers, params=None):
        return self._request("GET", "/api/logbook-entries", headers=headers, params=params)

    def get_logbook_entry(self, entry_id, headers):
        return self._request("GET", f"/api/logbook-entries/{entry_id}", headers=headers)

    # --- Invoices ---
    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def get_work_order_invoice(self, wo_id, headers):
        return self._request("GET", f"/api/work-orders/{wo_id}/invoice", headers=headers)


api_client = ApiClient()
