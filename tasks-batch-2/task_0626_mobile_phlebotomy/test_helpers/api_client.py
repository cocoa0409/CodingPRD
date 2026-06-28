"""API client: one method per endpoint defined in the Mobile Phlebotomy PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test Panels ---
    def create_test_panel(self, payload, headers):
        return self._request("POST", "/test-panels", payload, headers)

    def list_test_panels(self, headers, params=None):
        return self._request("GET", "/test-panels", headers=headers, params=params)

    def get_test_panel(self, panel_id, headers):
        return self._request("GET", f"/test-panels/{panel_id}", headers=headers)

    def retire_test_panel(self, panel_id, headers):
        return self._request("POST", f"/test-panels/{panel_id}/retire", {}, headers)

    # --- Lab Partners ---
    def create_lab_partner(self, payload, headers):
        return self._request("POST", "/lab-partners", payload, headers)

    def list_lab_partners(self, headers, params=None):
        return self._request("GET", "/lab-partners", headers=headers, params=params)

    def get_lab_partner(self, partner_id, headers):
        return self._request("GET", f"/lab-partners/{partner_id}", headers=headers)

    def suspend_lab_partner(self, partner_id, headers):
        return self._request("POST", f"/lab-partners/{partner_id}/suspend", {}, headers)

    # --- Phlebotomists & Route Days ---
    def create_phlebotomist(self, payload, headers):
        return self._request("POST", "/phlebotomists", payload, headers)

    def list_phlebotomists(self, headers, params=None):
        return self._request("GET", "/phlebotomists", headers=headers, params=params)

    def get_phlebotomist(self, phleb_id, headers):
        return self._request("GET", f"/phlebotomists/{phleb_id}", headers=headers)

    def create_route_day(self, phleb_id, payload, headers):
        return self._request("POST", f"/phlebotomists/{phleb_id}/route-days", payload, headers)

    def list_phlebotomist_route_days(self, phleb_id, headers, params=None):
        return self._request("GET", f"/phlebotomists/{phleb_id}/route-days", headers=headers, params=params)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/route-days/{route_day_id}", headers=headers)

    def list_route_day_appointments(self, route_day_id, headers, params=None):
        return self._request("GET", f"/route-days/{route_day_id}/appointments", headers=headers, params=params)

    def close_route_day(self, route_day_id, headers):
        return self._request("POST", f"/route-days/{route_day_id}/close", {}, headers)

    # --- Lab Orders ---
    def create_lab_order(self, payload, headers):
        return self._request("POST", "/lab-orders", payload, headers)

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/lab-orders", headers=headers, params=params)

    def get_lab_order(self, order_id, headers):
        return self._request("GET", f"/lab-orders/{order_id}", headers=headers)

    def book_appointment(self, order_id, payload, headers):
        return self._request("POST", f"/lab-orders/{order_id}/appointments", payload, headers)

    def list_order_appointments(self, order_id, headers, params=None):
        return self._request("GET", f"/lab-orders/{order_id}/appointments", headers=headers, params=params)

    def list_order_specimens(self, order_id, headers, params=None):
        return self._request("GET", f"/lab-orders/{order_id}/specimens", headers=headers, params=params)

    def list_order_results(self, order_id, headers, params=None):
        return self._request("GET", f"/lab-orders/{order_id}/results", headers=headers, params=params)

    def list_order_invoices(self, order_id, headers, params=None):
        return self._request("GET", f"/lab-orders/{order_id}/invoices", headers=headers, params=params)

    def post_results(self, order_id, payload, headers):
        return self._request("POST", f"/lab-orders/{order_id}/results", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/lab-orders/{order_id}/cancel", {}, headers)

    # --- Appointments ---
    def get_appointment(self, appt_id, headers):
        return self._request("GET", f"/appointments/{appt_id}", headers=headers)

    def assign_kit(self, appt_id, payload, headers):
        return self._request("POST", f"/appointments/{appt_id}/kit", payload, headers)

    def list_appointment_kits(self, appt_id, headers):
        return self._request("GET", f"/appointments/{appt_id}/kit", headers=headers)

    def dispatch_appointment(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/dispatch", {}, headers)

    def recall_appointment(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/recall", {}, headers)

    def arrive_appointment(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/arrive", {}, headers)

    def collect_specimen(self, appt_id, payload, headers):
        return self._request("POST", f"/appointments/{appt_id}/specimens", payload, headers)

    def list_appointment_specimens(self, appt_id, headers, params=None):
        return self._request("GET", f"/appointments/{appt_id}/specimens", headers=headers, params=params)

    def complete_draw(self, appt_id, headers):
        return self._request("POST", f"/appointments/{appt_id}/complete-draw", {}, headers)

    # --- Specimens & Custody ---
    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/specimens/{specimen_id}", headers=headers)

    def list_specimen_custody_events(self, specimen_id, headers, params=None):
        return self._request("GET", f"/specimens/{specimen_id}/custody-events", headers=headers, params=params)

    def get_custody_event(self, event_id, headers):
        return self._request("GET", f"/custody-events/{event_id}", headers=headers)

    def list_custody_events(self, headers, params=None):
        return self._request("GET", "/custody-events", headers=headers, params=params)

    def accession_specimen(self, specimen_id, headers):
        return self._request("POST", f"/specimens/{specimen_id}/accession", {}, headers)

    def reject_qns(self, specimen_id, headers):
        return self._request("POST", f"/specimens/{specimen_id}/reject-qns", {}, headers)

    # --- Courier Manifests ---
    def create_manifest(self, payload, headers):
        return self._request("POST", "/courier-manifests", payload, headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/courier-manifests", headers=headers, params=params)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/courier-manifests/{manifest_id}", headers=headers)

    def list_manifest_specimens(self, manifest_id, headers, params=None):
        return self._request("GET", f"/courier-manifests/{manifest_id}/specimens", headers=headers, params=params)

    def add_specimen_to_manifest(self, manifest_id, payload, headers):
        return self._request("POST", f"/courier-manifests/{manifest_id}/add-specimen", payload, headers)

    def pickup_manifest(self, manifest_id, headers):
        return self._request("POST", f"/courier-manifests/{manifest_id}/pickup", {}, headers)

    # --- Lab Results ---
    def get_lab_result(self, result_id, headers):
        return self._request("GET", f"/lab-results/{result_id}", headers=headers)

    def list_lab_results(self, headers, params=None):
        return self._request("GET", "/lab-results", headers=headers, params=params)

    # --- Invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # --- Logical clock (test-driving capability, PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
