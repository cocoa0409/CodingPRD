"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Season ---
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def patch_season(self, season_id, payload, headers):
        return self._request("PATCH", f"/seasons/{season_id}", payload, headers)

    def begin_build(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/begin-build", {}, headers)

    def open_season(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/open", {}, headers)

    def begin_strike(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/begin-strike", {}, headers)

    def close_season(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/close", {}, headers)

    # --- FaireDay ---
    def create_faire_day(self, payload, headers):
        return self._request("POST", "/faire-days", payload, headers)

    def list_faire_days(self, headers, params=None):
        return self._request("GET", "/faire-days", headers=headers, params=params)

    def get_faire_day(self, day_id, headers):
        return self._request("GET", f"/faire-days/{day_id}", headers=headers)

    def open_sales(self, day_id, headers):
        return self._request("POST", f"/faire-days/{day_id}/open-sales", {}, headers)

    def weather_hold(self, day_id, headers):
        return self._request("POST", f"/faire-days/{day_id}/weather-hold", {}, headers)

    def release_hold(self, day_id, headers):
        return self._request("POST", f"/faire-days/{day_id}/release-hold", {}, headers)

    def cancel_weather(self, day_id, headers):
        return self._request("POST", f"/faire-days/{day_id}/cancel-weather", {}, headers)

    def open_gates(self, day_id, headers):
        return self._request("POST", f"/faire-days/{day_id}/open-gates", {}, headers)

    def complete_day(self, day_id, headers):
        return self._request("POST", f"/faire-days/{day_id}/complete", {}, headers)

    # --- Performer ---
    def create_performer(self, payload, headers):
        return self._request("POST", "/performers", payload, headers)

    def list_performers(self, headers, params=None):
        return self._request("GET", "/performers", headers=headers, params=params)

    def get_performer(self, performer_id, headers):
        return self._request("GET", f"/performers/{performer_id}", headers=headers)

    # --- CastContract ---
    def create_cast_contract(self, payload, headers):
        return self._request("POST", "/cast-contracts", payload, headers)

    def list_cast_contracts(self, headers, params=None):
        return self._request("GET", "/cast-contracts", headers=headers, params=params)

    def get_cast_contract(self, contract_id, headers):
        return self._request("GET", f"/cast-contracts/{contract_id}", headers=headers)

    def offer_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/cast-contracts/{contract_id}/offer", payload, headers)

    def counter_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/cast-contracts/{contract_id}/counter", payload, headers)

    def accept_contract(self, contract_id, headers):
        return self._request("POST", f"/cast-contracts/{contract_id}/accept", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/cast-contracts/{contract_id}/terminate", {}, headers)

    # --- RehearsalSlot ---
    def create_rehearsal_slot(self, payload, headers):
        return self._request("POST", "/rehearsal-slots", payload, headers)

    def list_rehearsal_slots(self, headers, params=None):
        return self._request("GET", "/rehearsal-slots", headers=headers, params=params)

    def get_rehearsal_slot(self, slot_id, headers):
        return self._request("GET", f"/rehearsal-slots/{slot_id}", headers=headers)

    def record_attendance(self, slot_id, payload, headers):
        return self._request("POST", f"/rehearsal-slots/{slot_id}/record-attendance", payload, headers)

    def cancel_slot(self, slot_id, headers):
        return self._request("POST", f"/rehearsal-slots/{slot_id}/cancel", {}, headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    # --- VendorApplication ---
    def create_vendor_application(self, payload, headers):
        return self._request("POST", "/vendor-applications", payload, headers)

    def list_vendor_applications(self, headers, params=None):
        return self._request("GET", "/vendor-applications", headers=headers, params=params)

    def get_vendor_application(self, application_id, headers):
        return self._request("GET", f"/vendor-applications/{application_id}", headers=headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/decide", payload, headers)

    def appeal_application(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/appeal", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/withdraw", {}, headers)

    # --- BoothAssignment ---
    def create_booth_assignment(self, payload, headers):
        return self._request("POST", "/booth-assignments", payload, headers)

    def list_booth_assignments(self, headers, params=None):
        return self._request("GET", "/booth-assignments", headers=headers, params=params)

    def get_booth_assignment(self, booth_id, headers):
        return self._request("GET", f"/booth-assignments/{booth_id}", headers=headers)

    def confirm_booth(self, booth_id, headers):
        return self._request("POST", f"/booth-assignments/{booth_id}/confirm", {}, headers)

    def release_booth(self, booth_id, headers):
        return self._request("POST", f"/booth-assignments/{booth_id}/release", {}, headers)

    def settle_booth(self, booth_id, headers):
        return self._request("POST", f"/booth-assignments/{booth_id}/settle", {}, headers)

    # --- FoodPermit ---
    def create_food_permit(self, payload, headers):
        return self._request("POST", "/food-permits", payload, headers)

    def list_food_permits(self, headers, params=None):
        return self._request("GET", "/food-permits", headers=headers, params=params)

    def get_food_permit(self, permit_id, headers):
        return self._request("GET", f"/food-permits/{permit_id}", headers=headers)

    def inspect_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/food-permits/{permit_id}/inspect", payload, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/food-permits/{permit_id}/revoke", {}, headers)

    # --- TicketOrder ---
    def create_ticket_order(self, payload, headers):
        return self._request("POST", "/ticket-orders", payload, headers)

    def list_ticket_orders(self, headers, params=None):
        return self._request("GET", "/ticket-orders", headers=headers, params=params)

    def get_ticket_order(self, order_id, headers):
        return self._request("GET", f"/ticket-orders/{order_id}", headers=headers)

    def patch_ticket_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/ticket-orders/{order_id}", payload, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/ticket-orders/{order_id}/pay", {}, headers)

    def refund_order(self, order_id, payload, headers):
        return self._request("POST", f"/ticket-orders/{order_id}/refund", payload, headers)

    # --- Ticket ---
    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def redeem_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/redeem", {}, headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/void", {}, headers)

    # --- RainCheck ---
    def list_rain_checks(self, headers, params=None):
        return self._request("GET", "/rain-checks", headers=headers, params=params)

    def get_rain_check(self, rain_check_id, headers):
        return self._request("GET", f"/rain-checks/{rain_check_id}", headers=headers)

    def redeem_rain_check(self, rain_check_id, payload, headers):
        return self._request("POST", f"/rain-checks/{rain_check_id}/redeem", payload, headers)

    # --- VolunteerShift ---
    def create_volunteer_shift(self, payload, headers):
        return self._request("POST", "/volunteer-shifts", payload, headers)

    def list_volunteer_shifts(self, headers, params=None):
        return self._request("GET", "/volunteer-shifts", headers=headers, params=params)

    def get_volunteer_shift(self, shift_id, headers):
        return self._request("GET", f"/volunteer-shifts/{shift_id}", headers=headers)

    def confirm_shift(self, shift_id, headers):
        return self._request("POST", f"/volunteer-shifts/{shift_id}/confirm", {}, headers)

    def close_out_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/volunteer-shifts/{shift_id}/close-out", payload, headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/volunteer-shifts/{shift_id}/cancel", {}, headers)

    # --- ConductCase ---
    def create_conduct_case(self, payload, headers):
        return self._request("POST", "/conduct-cases", payload, headers)

    def list_conduct_cases(self, headers, params=None):
        return self._request("GET", "/conduct-cases", headers=headers, params=params)

    def get_conduct_case(self, case_id, headers):
        return self._request("GET", f"/conduct-cases/{case_id}", headers=headers)

    def resolve_conduct_case(self, case_id, payload, headers):
        return self._request("POST", f"/conduct-cases/{case_id}/resolve", payload, headers)

    # --- BuildTask ---
    def create_build_task(self, payload, headers):
        return self._request("POST", "/build-tasks", payload, headers)

    def list_build_tasks(self, headers, params=None):
        return self._request("GET", "/build-tasks", headers=headers, params=params)

    def get_build_task(self, task_id, headers):
        return self._request("GET", f"/build-tasks/{task_id}", headers=headers)

    def list_task_dependents(self, task_id, headers):
        return self._request("GET", f"/build-tasks/{task_id}/dependents", headers=headers)

    def add_task_dependencies(self, task_id, payload, headers):
        return self._request("POST", f"/build-tasks/{task_id}/dependencies", payload, headers)

    def advance_task(self, task_id, payload, headers):
        return self._request("POST", f"/build-tasks/{task_id}/advance", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
