"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving capabilities (PRD §3.17) ----------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def inject_client_state(self, payload, headers):
        return self._request("POST", "/_inject/client_state", payload, headers)

    def inject_appointment_deposit(self, payload, headers):
        return self._request("POST", "/_inject/appointment_deposit", payload, headers)

    # ---- Technicians ------------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def suspend_technician(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/suspend", headers=headers)

    def reinstate_technician(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/reinstate", headers=headers)

    def terminate_technician(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/terminate", headers=headers)

    def list_technician_appointments(self, technician_id, headers, params=None):
        return self._request(
            "GET", f"/technicians/{technician_id}/appointments", headers=headers, params=params
        )

    def list_technician_commission_statements(self, technician_id, headers, params=None):
        return self._request(
            "GET", f"/technicians/{technician_id}/commission-statements",
            headers=headers, params=params,
        )

    # ---- Stations ---------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_station_sanitation_logs(self, station_id, headers, params=None):
        return self._request(
            "GET", f"/stations/{station_id}/sanitation-logs", headers=headers, params=params
        )

    # ---- Sanitation logs --------------------------------------------------
    def create_sanitation_log(self, payload, headers):
        return self._request("POST", "/sanitation-logs", payload, headers)

    def list_sanitation_logs(self, headers, params=None):
        return self._request("GET", "/sanitation-logs", headers=headers, params=params)

    def get_sanitation_log(self, log_id, headers):
        return self._request("GET", f"/sanitation-logs/{log_id}", headers=headers)

    # ---- Menu items -------------------------------------------------------
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/menu-items/{item_id}", headers=headers)

    def retire_menu_item(self, item_id, headers):
        return self._request("POST", f"/menu-items/{item_id}/retire", headers=headers)

    # ---- Add-ons ----------------------------------------------------------
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    # ---- Clients ----------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_client_appointments(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/appointments", headers=headers, params=params
        )

    def list_client_gift_cards(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/gift-cards", headers=headers, params=params
        )

    # ---- Appointments -----------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def attach_add_on(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/add-ons", payload, headers
        )

    def list_appointment_add_ons(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/add-ons", headers=headers, params=params
        )

    def list_all_appointment_add_ons(self, headers, params=None):
        return self._request("GET", "/appointment-add-ons", headers=headers, params=params)

    def get_appointment_add_on(self, junction_id, headers):
        return self._request("GET", f"/appointment-add-ons/{junction_id}", headers=headers)

    def pay_deposit(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/pay-deposit", headers=headers)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/confirm", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", headers=headers)

    def start_service(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/start-service", headers=headers
        )

    def checkout_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/checkout", payload, headers
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", headers=headers)

    def mark_no_show(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/mark-no-show", headers=headers
        )

    def refund_settled(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/refund-settled", headers=headers
        )

    # ---- Gift cards -------------------------------------------------------
    def create_gift_card(self, payload, headers):
        return self._request("POST", "/gift-cards", payload, headers)

    def list_gift_cards(self, headers, params=None):
        return self._request("GET", "/gift-cards", headers=headers, params=params)

    def get_gift_card(self, gift_card_id, headers):
        return self._request("GET", f"/gift-cards/{gift_card_id}", headers=headers)

    def redeem_gift_card(self, gift_card_id, payload, headers):
        return self._request(
            "POST", f"/gift-cards/{gift_card_id}/redeem", payload, headers
        )

    def void_gift_card(self, gift_card_id, headers):
        return self._request("POST", f"/gift-cards/{gift_card_id}/void", headers=headers)

    # ---- Commission statements --------------------------------------------
    def create_commission_statement(self, payload, headers):
        return self._request("POST", "/commission-statements", payload, headers)

    def list_commission_statements(self, headers, params=None):
        return self._request("GET", "/commission-statements", headers=headers, params=params)

    def get_commission_statement(self, statement_id, headers):
        return self._request("GET", f"/commission-statements/{statement_id}", headers=headers)

    def settle_commission_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/settle", headers=headers
        )

    def void_commission_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/void", headers=headers
        )


api_client = ApiClient()
