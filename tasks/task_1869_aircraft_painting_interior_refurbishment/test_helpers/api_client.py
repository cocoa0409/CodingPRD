"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions).

Every method returns the raw requests.Response so tests can assert status codes
and pick apart the envelope via the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/completion/_clock/set_current_utc", payload, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/completion/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/completion/customers", headers=headers, params=params)

    def set_customer_credit_status(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/completion/customers/{customer_id}/credit-status", payload, headers
        )

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/completion/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/completion/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/completion/aircraft", headers=headers, params=params)

    # --- RefurbProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/completion/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/completion/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/completion/programs", headers=headers, params=params)

    def advance_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/completion/programs/{program_id}/advance", payload, headers
        )

    def cancel_program(self, program_id, headers):
        return self._request(
            "POST", f"/completion/programs/{program_id}/cancel", {}, headers
        )

    # --- PaintScheme ---
    def create_paint_scheme(self, payload, headers):
        return self._request("POST", "/completion/paint-schemes", payload, headers)

    def get_paint_scheme(self, scheme_id, headers):
        return self._request("GET", f"/completion/paint-schemes/{scheme_id}", headers=headers)

    def list_paint_schemes(self, headers, params=None):
        return self._request("GET", "/completion/paint-schemes", headers=headers, params=params)

    def submit_paint_scheme(self, scheme_id, headers):
        return self._request(
            "POST", f"/completion/paint-schemes/{scheme_id}/submit", {}, headers
        )

    def approve_paint_scheme(self, scheme_id, payload, headers):
        return self._request(
            "POST", f"/completion/paint-schemes/{scheme_id}/approve", payload, headers
        )

    def reject_paint_scheme(self, scheme_id, headers):
        return self._request(
            "POST", f"/completion/paint-schemes/{scheme_id}/reject", {}, headers
        )

    def revise_paint_scheme(self, scheme_id, headers):
        return self._request(
            "POST", f"/completion/paint-schemes/{scheme_id}/revise", {}, headers
        )

    # --- SurfaceAssessment ---
    def create_surface_assessment(self, payload, headers):
        return self._request("POST", "/completion/surface-assessments", payload, headers)

    def get_surface_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/completion/surface-assessments/{assessment_id}", headers=headers
        )

    def list_surface_assessments(self, headers, params=None):
        return self._request(
            "GET", "/completion/surface-assessments", headers=headers, params=params
        )

    def decide_surface_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/completion/surface-assessments/{assessment_id}/decide", payload, headers
        )

    def amend_surface_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/completion/surface-assessments/{assessment_id}/amend", payload, headers
        )

    # --- DiscoveryItem ---
    def create_discovery_item(self, payload, headers):
        return self._request("POST", "/completion/discovery-items", payload, headers)

    def get_discovery_item(self, item_id, headers):
        return self._request("GET", f"/completion/discovery-items/{item_id}", headers=headers)

    def list_discovery_items(self, headers, params=None):
        return self._request("GET", "/completion/discovery-items", headers=headers, params=params)

    def estimate_discovery_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/completion/discovery-items/{item_id}/estimate", payload, headers
        )

    def approve_discovery_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/completion/discovery-items/{item_id}/approve", payload, headers
        )

    def reject_discovery_item(self, item_id, headers):
        return self._request(
            "POST", f"/completion/discovery-items/{item_id}/reject", {}, headers
        )

    def defer_discovery_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/completion/discovery-items/{item_id}/defer", payload, headers
        )

    def complete_discovery_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/completion/discovery-items/{item_id}/complete", payload, headers
        )

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/completion/change-orders", payload, headers)

    def get_change_order(self, order_id, headers):
        return self._request("GET", f"/completion/change-orders/{order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/completion/change-orders", headers=headers, params=params)

    def submit_change_order(self, order_id, headers):
        return self._request(
            "POST", f"/completion/change-orders/{order_id}/submit", {}, headers
        )

    def approve_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/completion/change-orders/{order_id}/approve", payload, headers
        )

    def reject_change_order(self, order_id, headers):
        return self._request(
            "POST", f"/completion/change-orders/{order_id}/reject", {}, headers
        )

    def counter_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/completion/change-orders/{order_id}/counter", payload, headers
        )

    def revise_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/completion/change-orders/{order_id}/revise", payload, headers
        )

    # --- HangarBay / HangarSlot ---
    def create_hangar_bay(self, payload, headers):
        return self._request("POST", "/completion/hangar-bays", payload, headers)

    def list_hangar_bays(self, headers, params=None):
        return self._request("GET", "/completion/hangar-bays", headers=headers, params=params)

    def deactivate_hangar_bay(self, bay_id, headers):
        return self._request(
            "POST", f"/completion/hangar-bays/{bay_id}/deactivate", {}, headers
        )

    def create_hangar_slot(self, payload, headers):
        return self._request("POST", "/completion/hangar-slots", payload, headers)

    def get_hangar_slot(self, slot_id, headers):
        return self._request("GET", f"/completion/hangar-slots/{slot_id}", headers=headers)

    def list_hangar_slots(self, headers, params=None):
        return self._request("GET", "/completion/hangar-slots", headers=headers, params=params)

    def activate_hangar_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/completion/hangar-slots/{slot_id}/activate", {}, headers
        )

    def release_hangar_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/completion/hangar-slots/{slot_id}/release", {}, headers
        )

    def cancel_hangar_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/completion/hangar-slots/{slot_id}/cancel", {}, headers
        )

    # --- PaintBooth / BoothBooking ---
    def create_paint_booth(self, payload, headers):
        return self._request("POST", "/completion/paint-booths", payload, headers)

    def list_paint_booths(self, headers, params=None):
        return self._request("GET", "/completion/paint-booths", headers=headers, params=params)

    def create_booth_booking(self, payload, headers):
        return self._request("POST", "/completion/booth-bookings", payload, headers)

    def get_booth_booking(self, booking_id, headers):
        return self._request("GET", f"/completion/booth-bookings/{booking_id}", headers=headers)

    def list_booth_bookings(self, headers, params=None):
        return self._request("GET", "/completion/booth-bookings", headers=headers, params=params)

    def complete_booth_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/completion/booth-bookings/{booking_id}/complete", payload, headers
        )

    def cancel_booth_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/completion/booth-bookings/{booking_id}/cancel", {}, headers
        )

    # --- SoftGoodLot / BurnTest ---
    def create_soft_good_lot(self, payload, headers):
        return self._request("POST", "/completion/soft-good-lots", payload, headers)

    def get_soft_good_lot(self, lot_id, headers):
        return self._request("GET", f"/completion/soft-good-lots/{lot_id}", headers=headers)

    def list_soft_good_lots(self, headers, params=None):
        return self._request("GET", "/completion/soft-good-lots", headers=headers, params=params)

    def record_burn_test(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/completion/soft-good-lots/{lot_id}/burn-tests", payload, headers
        )

    def list_burn_tests(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/completion/soft-good-lots/{lot_id}/burn-tests", headers=headers, params=params
        )

    # --- WeightBalanceRecord ---
    def create_weight_balance_record(self, payload, headers):
        return self._request("POST", "/completion/weight-balance-records", payload, headers)

    def get_weight_balance_record(self, record_id, headers):
        return self._request(
            "GET", f"/completion/weight-balance-records/{record_id}", headers=headers
        )

    def list_weight_balance_records(self, headers, params=None):
        return self._request(
            "GET", "/completion/weight-balance-records", headers=headers, params=params
        )

    def sign_off_weight_balance_record(self, record_id, headers):
        return self._request(
            "POST", f"/completion/weight-balance-records/{record_id}/sign-off", {}, headers
        )

    # --- QualityInspection ---
    def create_quality_inspection(self, payload, headers):
        return self._request("POST", "/completion/quality-inspections", payload, headers)

    def get_quality_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/completion/quality-inspections/{inspection_id}", headers=headers
        )

    def list_quality_inspections(self, headers, params=None):
        return self._request(
            "GET", "/completion/quality-inspections", headers=headers, params=params
        )

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"/completion/quality-inspections/{inspection_id}/record-result",
            payload,
            headers,
        )

    # --- DelayEvent ---
    def create_delay_event(self, payload, headers):
        return self._request("POST", "/completion/delay-events", payload, headers)

    def get_delay_event(self, event_id, headers):
        return self._request("GET", f"/completion/delay-events/{event_id}", headers=headers)

    def list_delay_events(self, headers, params=None):
        return self._request("GET", "/completion/delay-events", headers=headers, params=params)

    def confirm_delay_event(self, event_id, headers):
        return self._request(
            "POST", f"/completion/delay-events/{event_id}/confirm", {}, headers
        )

    def dispute_delay_event(self, event_id, headers):
        return self._request(
            "POST", f"/completion/delay-events/{event_id}/dispute", {}, headers
        )

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/completion/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/completion/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/completion/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/completion/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/completion/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/completion/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
