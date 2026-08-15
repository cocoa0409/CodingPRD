"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §1) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Market ---
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/markets", headers=headers, params=params)

    def open_market(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/open_market", payload, headers)

    def clear_weather_alert(self, market_id, headers):
        return self._request("POST", f"/markets/{market_id}/clear_weather_alert", {}, headers)

    def cancel_market(self, market_id, headers):
        return self._request("POST", f"/markets/{market_id}/cancel", {}, headers)

    def run_ops(self, market_id, headers):
        return self._request("POST", f"/markets/{market_id}/run_ops", {}, headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    # --- VendorApplication (nested under market) ---
    def create_application(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/applications", payload, headers)

    def get_application(self, market_id, application_id, headers):
        return self._request("GET", f"/markets/{market_id}/applications/{application_id}",
                             headers=headers)

    def list_applications(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/applications",
                             headers=headers, params=params)

    def submit_application(self, market_id, application_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/applications/{application_id}/submit",
                             {}, headers)

    def score_application(self, market_id, application_id, payload, headers):
        return self._request("POST",
                             f"/markets/{market_id}/applications/{application_id}/score",
                             payload, headers)

    def decide_application(self, market_id, application_id, payload, headers):
        return self._request("POST",
                             f"/markets/{market_id}/applications/{application_id}/decide",
                             payload, headers)

    def withdraw_application(self, market_id, application_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/applications/{application_id}/withdraw",
                             {}, headers)

    # --- Booth ---
    def create_booth(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/booths", payload, headers)

    def get_booth(self, market_id, booth_id, headers):
        return self._request("GET", f"/markets/{market_id}/booths/{booth_id}", headers=headers)

    def list_booths(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/booths",
                             headers=headers, params=params)

    # --- BoothAssignment ---
    def create_assignment(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/assignments", payload, headers)

    def get_assignment(self, market_id, assignment_id, headers):
        return self._request("GET", f"/markets/{market_id}/assignments/{assignment_id}",
                             headers=headers)

    def list_assignments(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/assignments",
                             headers=headers, params=params)

    def activate_assignment(self, market_id, assignment_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/assignments/{assignment_id}/activate",
                             {}, headers)

    def release_assignment(self, market_id, assignment_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/assignments/{assignment_id}/release",
                             {}, headers)

    def forfeit_assignment(self, market_id, assignment_id, payload, headers):
        return self._request("POST",
                             f"/markets/{market_id}/assignments/{assignment_id}/forfeit",
                             payload, headers)

    # --- Permit ---
    def create_permit(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/permits", payload, headers)

    def get_permit(self, market_id, permit_id, headers):
        return self._request("GET", f"/markets/{market_id}/permits/{permit_id}", headers=headers)

    def list_permits(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/permits",
                             headers=headers, params=params)

    def revoke_permit(self, market_id, permit_id, headers):
        return self._request("POST", f"/markets/{market_id}/permits/{permit_id}/revoke",
                             {}, headers)

    # --- UtilityHookup ---
    def create_hookup(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/hookups", payload, headers)

    def get_hookup(self, market_id, hookup_id, headers):
        return self._request("GET", f"/markets/{market_id}/hookups/{hookup_id}", headers=headers)

    def list_hookups(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/hookups",
                             headers=headers, params=params)

    def install_hookup(self, market_id, hookup_id, headers):
        return self._request("POST", f"/markets/{market_id}/hookups/{hookup_id}/install",
                             {}, headers)

    def energize_hookup(self, market_id, hookup_id, headers):
        return self._request("POST", f"/markets/{market_id}/hookups/{hookup_id}/energize",
                             {}, headers)

    def decommission_hookup(self, market_id, hookup_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/hookups/{hookup_id}/decommission",
                             {}, headers)

    # --- PosDevice ---
    def create_pos_device(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/pos_devices", payload, headers)

    def get_pos_device(self, market_id, pos_device_id, headers):
        return self._request("GET", f"/markets/{market_id}/pos_devices/{pos_device_id}",
                             headers=headers)

    def list_pos_devices(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/pos_devices",
                             headers=headers, params=params)

    def activate_pos_device(self, market_id, pos_device_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/pos_devices/{pos_device_id}/activate",
                             {}, headers)

    def suspend_pos_device(self, market_id, pos_device_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/pos_devices/{pos_device_id}/suspend",
                             {}, headers)

    def return_pos_device(self, market_id, pos_device_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/pos_devices/{pos_device_id}/return_device",
                             {}, headers)

    # --- SalesSettlement ---
    def create_settlement(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/settlements", payload, headers)

    def get_settlement(self, market_id, settlement_id, headers):
        return self._request("GET", f"/markets/{market_id}/settlements/{settlement_id}",
                             headers=headers)

    def list_settlements(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/settlements",
                             headers=headers, params=params)

    def update_settlement(self, market_id, settlement_id, payload, headers):
        return self._request("PUT", f"/markets/{market_id}/settlements/{settlement_id}",
                             payload, headers)

    def submit_settlement(self, market_id, settlement_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/settlements/{settlement_id}/submit",
                             {}, headers)

    def reconcile_settlement(self, market_id, settlement_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/settlements/{settlement_id}/reconcile",
                             {}, headers)

    def dispute_settlement(self, market_id, settlement_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/settlements/{settlement_id}/dispute",
                             {}, headers)

    def pay_settlement(self, market_id, settlement_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/settlements/{settlement_id}/pay",
                             {}, headers)

    # --- ProgrammingSlot ---
    def create_programming_slot(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/programming", payload, headers)

    def get_programming_slot(self, market_id, slot_id, headers):
        return self._request("GET", f"/markets/{market_id}/programming/{slot_id}",
                             headers=headers)

    def list_programming_slots(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/programming",
                             headers=headers, params=params)

    def cancel_programming_slot(self, market_id, slot_id, headers):
        return self._request("POST", f"/markets/{market_id}/programming/{slot_id}/cancel",
                             {}, headers)

    # --- LoadSlot ---
    def create_load_slot(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/load_slots", payload, headers)

    def get_load_slot(self, market_id, load_slot_id, headers):
        return self._request("GET", f"/markets/{market_id}/load_slots/{load_slot_id}",
                             headers=headers)

    def list_load_slots(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/load_slots",
                             headers=headers, params=params)

    def check_in_load_slot(self, market_id, load_slot_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/load_slots/{load_slot_id}/check_in",
                             {}, headers)

    def complete_load_slot(self, market_id, load_slot_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/load_slots/{load_slot_id}/complete",
                             {}, headers)

    # --- WeatherEvent ---
    def create_weather_event(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/weather_events", payload, headers)

    def get_weather_event(self, market_id, weather_event_id, headers):
        return self._request("GET", f"/markets/{market_id}/weather_events/{weather_event_id}",
                             headers=headers)

    def list_weather_events(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/weather_events",
                             headers=headers, params=params)

    # --- RenewalOffer ---
    def create_renewal_offer(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/renewal_offers", payload, headers)

    def get_renewal_offer(self, market_id, offer_id, headers):
        return self._request("GET", f"/markets/{market_id}/renewal_offers/{offer_id}",
                             headers=headers)

    def list_renewal_offers(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/renewal_offers",
                             headers=headers, params=params)

    def accept_renewal_offer(self, market_id, offer_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/renewal_offers/{offer_id}/accept",
                             {}, headers)

    def decline_renewal_offer(self, market_id, offer_id, headers):
        return self._request("POST",
                             f"/markets/{market_id}/renewal_offers/{offer_id}/decline",
                             {}, headers)

    # --- Top-level filtered lists (PRD §4) ---
    def list_all_applications(self, headers, params=None):
        return self._request("GET", "/markets/applications", headers=headers, params=params)

    def list_all_booths(self, headers, params=None):
        return self._request("GET", "/markets/booths", headers=headers, params=params)

    def list_all_assignments(self, headers, params=None):
        return self._request("GET", "/markets/assignments", headers=headers, params=params)

    def list_all_permits(self, headers, params=None):
        return self._request("GET", "/markets/permits", headers=headers, params=params)

    def list_all_hookups(self, headers, params=None):
        return self._request("GET", "/markets/hookups", headers=headers, params=params)

    def list_all_pos_devices(self, headers, params=None):
        return self._request("GET", "/markets/pos_devices", headers=headers, params=params)

    def list_all_settlements(self, headers, params=None):
        return self._request("GET", "/markets/settlements", headers=headers, params=params)

    def list_all_programming(self, headers, params=None):
        return self._request("GET", "/markets/programming", headers=headers, params=params)

    def list_all_load_slots(self, headers, params=None):
        return self._request("GET", "/markets/load_slots", headers=headers, params=params)

    def list_all_weather_events(self, headers, params=None):
        return self._request("GET", "/markets/weather_events", headers=headers, params=params)

    def list_all_renewal_offers(self, headers, params=None):
        return self._request("GET", "/markets/renewal_offers", headers=headers, params=params)

    # --- Top-level single-resource GETs (PRD §4) ---
    def get_application_by_id(self, application_id, headers):
        return self._request("GET", f"/markets/applications/{application_id}", headers=headers)

    def get_booth_by_id(self, booth_id, headers):
        return self._request("GET", f"/markets/booths/{booth_id}", headers=headers)

    def get_assignment_by_id(self, assignment_id, headers):
        return self._request("GET", f"/markets/assignments/{assignment_id}", headers=headers)

    def get_permit_by_id(self, permit_id, headers):
        return self._request("GET", f"/markets/permits/{permit_id}", headers=headers)

    def get_hookup_by_id(self, hookup_id, headers):
        return self._request("GET", f"/markets/hookups/{hookup_id}", headers=headers)

    def get_pos_device_by_id(self, pos_device_id, headers):
        return self._request("GET", f"/markets/pos_devices/{pos_device_id}", headers=headers)

    def get_settlement_by_id(self, settlement_id, headers):
        return self._request("GET", f"/markets/settlements/{settlement_id}", headers=headers)

    def get_programming_slot_by_id(self, slot_id, headers):
        return self._request("GET", f"/markets/programming/{slot_id}", headers=headers)

    def get_load_slot_by_id(self, load_slot_id, headers):
        return self._request("GET", f"/markets/load_slots/{load_slot_id}", headers=headers)

    def get_weather_event_by_id(self, weather_event_id, headers):
        return self._request("GET", f"/markets/weather_events/{weather_event_id}",
                             headers=headers)

    def get_renewal_offer_by_id(self, offer_id, headers):
        return self._request("GET", f"/markets/renewal_offers/{offer_id}", headers=headers)


api_client = ApiClient()
