"""API client: one method per endpoint defined in PRD section 4."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Barns ----------------
    def create_barn(self, payload, headers):
        return self._request("POST", "/barns", payload, headers)

    def list_barns(self, headers, params=None):
        return self._request("GET", "/barns", headers=headers, params=params)

    def get_barn(self, barn_id, headers):
        return self._request("GET", f"/barns/{barn_id}", headers=headers)

    # ---------------- Clients ----------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def post_deposit(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/deposits", payload, headers)

    def apply_payment(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/payments", payload, headers)

    # ---------------- Horses ----------------
    def create_horse(self, payload, headers):
        return self._request("POST", "/horses", payload, headers)

    def list_horses(self, headers, params=None):
        return self._request("GET", "/horses", headers=headers, params=params)

    def get_horse(self, horse_id, headers):
        return self._request("GET", f"/horses/{horse_id}", headers=headers)

    def patch_horse(self, horse_id, payload, headers):
        return self._request("PATCH", f"/horses/{horse_id}", payload, headers)

    def retire_horse(self, horse_id, headers):
        return self._request("POST", f"/horses/{horse_id}/retire", {}, headers)

    def reinstate_horse(self, horse_id, headers):
        return self._request("POST", f"/horses/{horse_id}/reinstate", {}, headers)

    def list_limb_states(self, horse_id, headers, params=None):
        return self._request(
            "GET", f"/horses/{horse_id}/limb-states", headers=headers, params=params
        )

    # ---------------- Farriers ----------------
    def create_farrier(self, payload, headers):
        return self._request("POST", "/farriers", payload, headers)

    def list_farriers(self, headers, params=None):
        return self._request("GET", "/farriers", headers=headers, params=params)

    def get_farrier(self, farrier_id, headers):
        return self._request("GET", f"/farriers/{farrier_id}", headers=headers)

    def deactivate_farrier(self, farrier_id, payload, headers):
        return self._request(
            "POST", f"/farriers/{farrier_id}/deactivate", payload, headers
        )

    def reactivate_farrier(self, farrier_id, headers):
        return self._request("POST", f"/farriers/{farrier_id}/reactivate", {}, headers)

    def recertify_farrier(self, farrier_id, payload, headers):
        return self._request(
            "POST", f"/farriers/{farrier_id}/recertify", payload, headers
        )

    # ---------------- Shoe SKUs ----------------
    def create_shoe_sku(self, payload, headers):
        return self._request("POST", "/shoe-skus", payload, headers)

    def list_shoe_skus(self, headers, params=None):
        return self._request("GET", "/shoe-skus", headers=headers, params=params)

    def get_shoe_sku(self, sku_id, headers):
        return self._request("GET", f"/shoe-skus/{sku_id}", headers=headers)

    # ---------------- Inventory buckets ----------------
    def list_inventory_buckets(self, headers, params=None):
        return self._request(
            "GET", "/inventory-buckets", headers=headers, params=params
        )

    def get_inventory_bucket(self, bucket_id, headers):
        return self._request("GET", f"/inventory-buckets/{bucket_id}", headers=headers)

    def adjust_inventory_bucket(self, bucket_id, payload, headers):
        return self._request(
            "POST", f"/inventory-buckets/{bucket_id}/adjust", payload, headers
        )

    # ---------------- Stock transfers ----------------
    def create_stock_transfer(self, payload, headers):
        return self._request("POST", "/stock-transfers", payload, headers)

    def list_stock_transfers(self, headers, params=None):
        return self._request("GET", "/stock-transfers", headers=headers, params=params)

    def get_stock_transfer(self, transfer_id, headers):
        return self._request("GET", f"/stock-transfers/{transfer_id}", headers=headers)

    def dispatch_stock_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/stock-transfers/{transfer_id}/dispatch", {}, headers
        )

    def receive_stock_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/stock-transfers/{transfer_id}/receive", {}, headers
        )

    def abort_stock_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/stock-transfers/{transfer_id}/abort", {}, headers
        )

    # ---------------- Shoe reservations ----------------
    def list_shoe_reservations(self, headers, params=None):
        return self._request(
            "GET", "/shoe-reservations", headers=headers, params=params
        )

    def get_shoe_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/shoe-reservations/{reservation_id}", headers=headers
        )

    # ---------------- Rate cards ----------------
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rate-cards", headers=headers, params=params)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rate-cards/{rate_card_id}", headers=headers)

    def activate_rate_card(self, rate_card_id, headers):
        return self._request(
            "POST", f"/rate-cards/{rate_card_id}/activate", {}, headers
        )

    # ---------------- Routes ----------------
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def plan_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/plan", {}, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/cancel", {}, headers)

    def create_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    # ---------------- Route stops ----------------
    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def reorder_route_stop(self, stop_id, payload, headers):
        return self._request(
            "POST", f"/route-stops/{stop_id}/reorder", payload, headers
        )

    def arrive_route_stop(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/arrive", {}, headers)

    def complete_route_stop(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/complete", {}, headers)

    def attach_appointment(self, stop_id, payload, headers):
        return self._request(
            "POST", f"/route-stops/{stop_id}/appointments", payload, headers
        )

    def detach_appointment(self, stop_id, appointment_id, headers):
        return self._request(
            "DELETE",
            f"/route-stops/{stop_id}/appointments/{appointment_id}",
            headers=headers,
        )

    # ---------------- Appointments ----------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def add_service_lines(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/service-lines", payload, headers
        )

    def start_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/start", {}, headers
        )

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/complete", payload, headers
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", {}, headers
        )

    def record_no_show(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/no-show", {}, headers
        )

    def create_warranty_revisit(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"/appointments/{appointment_id}/warranty-revisit",
            payload,
            headers,
        )

    # ---------------- Service lines ----------------
    def list_service_lines(self, headers, params=None):
        return self._request("GET", "/service-lines", headers=headers, params=params)

    def get_service_line(self, line_id, headers):
        return self._request("GET", f"/service-lines/{line_id}", headers=headers)

    def delete_service_line(self, line_id, headers):
        return self._request("DELETE", f"/service-lines/{line_id}", headers=headers)

    # ---------------- Lameness cases ----------------
    def create_lameness_case(self, payload, headers):
        return self._request("POST", "/lameness-cases", payload, headers)

    def list_lameness_cases(self, headers, params=None):
        return self._request("GET", "/lameness-cases", headers=headers, params=params)

    def get_lameness_case(self, case_id, headers):
        return self._request("GET", f"/lameness-cases/{case_id}", headers=headers)

    def resolve_lameness_case(self, case_id, headers):
        return self._request("POST", f"/lameness-cases/{case_id}/resolve", {}, headers)

    def reopen_lameness_case(self, case_id, headers):
        return self._request("POST", f"/lameness-cases/{case_id}/reopen", {}, headers)

    # ---------------- Vet prescriptions ----------------
    def create_prescription(self, payload, headers):
        return self._request("POST", "/vet-prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request(
            "GET", "/vet-prescriptions", headers=headers, params=params
        )

    def get_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"/vet-prescriptions/{prescription_id}", headers=headers
        )

    def activate_prescription(self, prescription_id, payload, headers):
        return self._request(
            "POST", f"/vet-prescriptions/{prescription_id}/activate", payload, headers
        )

    def revoke_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/vet-prescriptions/{prescription_id}/revoke", {}, headers
        )

    # ---------------- Invoices ----------------
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/invoices/{invoice_id}/lines", headers=headers, params=params
        )

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ---------------- Reminders ----------------
    def list_reminders(self, headers, params=None):
        return self._request("GET", "/reminders", headers=headers, params=params)

    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/reminders/{reminder_id}", headers=headers)

    def send_reminder(self, reminder_id, payload, headers):
        return self._request(
            "POST", f"/reminders/{reminder_id}/send", payload, headers
        )

    def acknowledge_reminder(self, reminder_id, headers):
        return self._request(
            "POST", f"/reminders/{reminder_id}/acknowledge", {}, headers
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
