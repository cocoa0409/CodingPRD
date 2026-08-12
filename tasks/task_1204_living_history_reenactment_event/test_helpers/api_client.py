"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Event lifecycle ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def patch_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/events/{event_id}", payload, headers)

    def open_registration(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open-registration", headers=headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/publish", headers=headers)

    def open_gates(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open-gates", headers=headers)

    def restrict_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/restrict", payload, headers)

    def lift_restriction(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/lift-restriction", headers=headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", headers=headers)

    def cancel_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/cancel", payload, headers)

    # ---- Agreements ----
    def create_agreement(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/agreements", payload, headers)

    def sign_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/sign", payload, headers)

    def list_agreements(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/agreements", headers=headers)

    # ---- Units ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def vet_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/vet", payload, headers)

    def suspend_unit(self, unit_id, headers, payload=None):
        return self._request("POST", f"/units/{unit_id}/suspend", payload, headers)

    def list_units(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/units", headers=headers)

    # ---- Participants ----
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def submit_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/submit", headers=headers)

    def vet_participant(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/vet", payload, headers)

    def check_in_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/check-in", headers=headers)

    def withdraw_participant(self, participant_id, headers, payload=None):
        return self._request("POST", f"/participants/{participant_id}/withdraw", payload, headers)

    # ---- Equipment & inspections ----
    def create_equipment_item(self, payload, headers):
        return self._request("POST", "/equipment-items", payload, headers)

    def get_equipment_item(self, item_id, headers):
        return self._request("GET", f"/equipment-items/{item_id}", headers=headers)

    def list_participant_equipment(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}/equipment-items", headers=headers)

    def withdraw_equipment_item(self, item_id, headers):
        return self._request("POST", f"/equipment-items/{item_id}/withdraw", headers=headers)

    def schedule_inspection(self, item_id, payload, headers):
        return self._request("POST", f"/equipment-items/{item_id}/inspections", payload, headers)

    def list_item_inspections(self, item_id, headers):
        return self._request("GET", f"/equipment-items/{item_id}/inspections", headers=headers)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/record", payload, headers)

    def waive_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/waive", payload, headers)

    # ---- Site areas & allocations ----
    def create_site_area(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/site-areas", payload, headers)

    def get_site_area(self, area_id, headers):
        return self._request("GET", f"/site-areas/{area_id}", headers=headers)

    def list_site_areas(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/site-areas", headers=headers, params=params)

    def close_site_area(self, area_id, headers):
        return self._request("POST", f"/site-areas/{area_id}/close", headers=headers)

    def create_allocation(self, area_id, payload, headers):
        return self._request("POST", f"/site-areas/{area_id}/allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/release", headers=headers)

    # ---- Program slots ----
    def create_program_slot(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/program-slots", payload, headers)

    def list_event_program_slots(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/program-slots", headers=headers)

    def list_area_program_slots(self, area_id, headers):
        return self._request("GET", f"/site-areas/{area_id}/program-slots", headers=headers)

    def confirm_program_slot(self, slot_id, headers):
        return self._request("POST", f"/program-slots/{slot_id}/confirm", headers=headers)

    def cancel_program_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"/program-slots/{slot_id}/cancel", payload, headers)

    # ---- Ticket orders & parking ----
    def create_ticket_order(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/ticket-orders", payload, headers)

    def list_ticket_orders(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/ticket-orders", headers=headers, params=params)

    def get_ticket_order(self, order_id, headers):
        return self._request("GET", f"/ticket-orders/{order_id}", headers=headers)

    def pay_ticket_order(self, order_id, payload, headers):
        return self._request("POST", f"/ticket-orders/{order_id}/pay", payload, headers)

    def refund_ticket_order(self, order_id, payload, headers):
        return self._request("POST", f"/ticket-orders/{order_id}/refund", payload, headers)

    def check_in_ticket_order(self, order_id, headers):
        return self._request("POST", f"/ticket-orders/{order_id}/check-in", headers=headers)

    def issue_parking_pass(self, order_id, payload, headers):
        return self._request("POST", f"/ticket-orders/{order_id}/parking-passes", payload, headers)

    def list_order_parking_passes(self, order_id, headers):
        return self._request("GET", f"/ticket-orders/{order_id}/parking-passes", headers=headers)

    def list_lot_parking_passes(self, area_id, headers):
        return self._request("GET", f"/site-areas/{area_id}/parking-passes", headers=headers)

    def void_parking_pass(self, pass_id, headers):
        return self._request("POST", f"/parking-passes/{pass_id}/void", headers=headers)

    # ---- Vendors (sutler row) ----
    def create_vendor(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/vendors", payload, headers)

    def list_vendors(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/vendors", headers=headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def approve_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/approve", headers=headers)

    def contract_vendor(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/contract", payload, headers)

    def revoke_vendor(self, vendor_id, headers, payload=None):
        return self._request("POST", f"/vendors/{vendor_id}/revoke", payload, headers)

    def settle_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/settle", headers=headers)

    # ---- Contingency alerts ----
    def create_contingency_alert(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/contingency-alerts", payload, headers)

    def list_contingency_alerts(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/contingency-alerts", headers=headers)

    def resolve_contingency_alert(self, alert_id, headers):
        return self._request("POST", f"/contingency-alerts/{alert_id}/resolve", headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
