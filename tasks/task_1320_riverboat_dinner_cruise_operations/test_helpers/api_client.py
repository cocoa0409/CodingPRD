"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Vessel ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def set_vessel_out_of_service(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/set-out-of-service",
                             headers=headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    # --- Dock ---
    def create_dock(self, payload, headers):
        return self._request("POST", "/docks", payload, headers)

    def list_docks(self, headers, params=None):
        return self._request("GET", "/docks", headers=headers, params=params)

    def get_dock(self, dock_id, headers):
        return self._request("GET", f"/docks/{dock_id}", headers=headers)

    def list_dock_vessels(self, dock_id, headers, params=None):
        return self._request("GET", f"/docks/{dock_id}/vessels",
                             headers=headers, params=params)

    def list_dock_dock_slots(self, dock_id, headers, params=None):
        return self._request("GET", f"/docks/{dock_id}/dock-slots",
                             headers=headers, params=params)

    def list_dock_parking_passes(self, dock_id, headers, params=None):
        return self._request("GET", f"/docks/{dock_id}/parking-passes",
                             headers=headers, params=params)

    # --- MenuTier ---
    def create_menu_tier(self, payload, headers):
        return self._request("POST", "/menu-tiers", payload, headers)

    def list_menu_tiers(self, headers, params=None):
        return self._request("GET", "/menu-tiers", headers=headers, params=params)

    def get_menu_tier(self, tier_id, headers):
        return self._request("GET", f"/menu-tiers/{tier_id}", headers=headers)

    def list_menu_tier_cruises(self, tier_id, headers, params=None):
        return self._request("GET", f"/menu-tiers/{tier_id}/cruises",
                             headers=headers, params=params)

    # --- CruiseInstance ---
    def create_cruise(self, payload, headers):
        return self._request("POST", "/cruises", payload, headers)

    def list_cruises(self, headers, params=None):
        return self._request("GET", "/cruises", headers=headers, params=params)

    def get_cruise(self, cruise_id, headers):
        return self._request("GET", f"/cruises/{cruise_id}", headers=headers)

    def open_boarding(self, cruise_id, headers):
        return self._request("POST", f"/cruises/{cruise_id}/open-boarding",
                             headers=headers)

    def depart_cruise(self, cruise_id, headers):
        return self._request("POST", f"/cruises/{cruise_id}/depart", headers=headers)

    def complete_cruise(self, cruise_id, headers):
        return self._request("POST", f"/cruises/{cruise_id}/complete", headers=headers)

    def clear_weather_hold(self, cruise_id, headers):
        return self._request("POST", f"/cruises/{cruise_id}/clear-weather-hold",
                             headers=headers)

    def weather_cancel_cruise(self, cruise_id, headers):
        return self._request("POST", f"/cruises/{cruise_id}/weather-cancel",
                             headers=headers)

    # --- Booking ---
    def create_booking(self, cruise_id, payload, headers):
        return self._request("POST", f"/cruises/{cruise_id}/bookings",
                             payload, headers)

    def list_cruise_bookings(self, cruise_id, headers, params=None):
        return self._request("GET", f"/cruises/{cruise_id}/bookings",
                             headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_booking_passengers(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/passengers",
                             headers=headers, params=params)

    def add_booking_passenger(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/passengers",
                             payload, headers)

    def pay_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/pay", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    def check_in_passenger(self, booking_id, passenger_id, headers):
        return self._request(
            "POST",
            f"/bookings/{booking_id}/passengers/{passenger_id}/check-in",
            headers=headers)

    # --- BoardingManifest ---
    def get_cruise_manifest(self, cruise_id, headers):
        return self._request("GET", f"/cruises/{cruise_id}/manifest", headers=headers)

    def freeze_manifest(self, cruise_id, headers):
        return self._request("POST", f"/cruises/{cruise_id}/manifest/freeze",
                             headers=headers)

    def amend_manifest(self, cruise_id, headers):
        return self._request("POST", f"/cruises/{cruise_id}/manifest/amend",
                             headers=headers)

    # --- GalleyProvisionOrder ---
    def create_provision_order(self, cruise_id, payload, headers):
        return self._request("POST", f"/cruises/{cruise_id}/provision-orders",
                             payload, headers)

    def list_provision_orders(self, cruise_id, headers, params=None):
        return self._request("GET", f"/cruises/{cruise_id}/provision-orders",
                             headers=headers, params=params)

    def place_provision_order(self, cruise_id, order_id, headers):
        return self._request(
            "POST", f"/cruises/{cruise_id}/provision-orders/{order_id}/place",
            headers=headers)

    def receive_provision_order(self, cruise_id, order_id, headers):
        return self._request(
            "POST", f"/cruises/{cruise_id}/provision-orders/{order_id}/receive",
            headers=headers)

    # --- Staff ---
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def list_staff_member_assignments(self, staff_id, headers, params=None):
        return self._request("GET", f"/staff-members/{staff_id}/assignments",
                             headers=headers, params=params)

    def create_staff_assignment(self, cruise_id, payload, headers):
        return self._request("POST", f"/cruises/{cruise_id}/staff-assignments",
                             payload, headers)

    def list_staff_assignments(self, cruise_id, headers, params=None):
        return self._request("GET", f"/cruises/{cruise_id}/staff-assignments",
                             headers=headers, params=params)

    def confirm_staff_assignment(self, cruise_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/cruises/{cruise_id}/staff-assignments/{assignment_id}/confirm",
            headers=headers)

    def release_staff_assignment(self, cruise_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/cruises/{cruise_id}/staff-assignments/{assignment_id}/release",
            headers=headers)

    # --- Customer / Credit ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_bookings(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/bookings",
                             headers=headers, params=params)

    def list_customer_credits(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/credits",
                             headers=headers, params=params)

    def redeem_credit(self, credit_id, headers):
        return self._request("POST", f"/credits/{credit_id}/redeem", headers=headers)

    def get_credit(self, credit_id, headers):
        return self._request("GET", f"/credits/{credit_id}", headers=headers)

    def list_booking_credits(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/credits",
                             headers=headers, params=params)

    # --- Charter ---
    def create_charter_inquiry(self, payload, headers):
        return self._request("POST", "/charter-inquiries", payload, headers)

    def list_charter_inquiries(self, headers, params=None):
        return self._request("GET", "/charter-inquiries", headers=headers,
                             params=params)

    def get_charter_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/charter-inquiries/{inquiry_id}",
                             headers=headers)

    def quote_charter_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/charter-inquiries/{inquiry_id}/quote",
                             payload, headers)

    def counter_charter_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/charter-inquiries/{inquiry_id}/counter",
                             headers=headers)

    def accept_charter_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/charter-inquiries/{inquiry_id}/accept",
                             headers=headers)

    def decline_charter_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/charter-inquiries/{inquiry_id}/decline",
                             headers=headers)

    def convert_charter_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/charter-inquiries/{inquiry_id}/convert",
                             headers=headers)

    # --- Weather ---
    def create_weather_event(self, payload, headers):
        return self._request("POST", "/weather-events", payload, headers)

    def list_weather_events(self, headers, params=None):
        return self._request("GET", "/weather-events", headers=headers, params=params)

    def get_weather_event(self, event_id, headers):
        return self._request("GET", f"/weather-events/{event_id}", headers=headers)

    def settle_weather_event_credits(self, event_id, headers):
        return self._request("POST", f"/weather-events/{event_id}/settle-credits",
                             headers=headers)

    def close_weather_event(self, event_id, headers):
        return self._request("POST", f"/weather-events/{event_id}/close",
                             headers=headers)

    # --- Dock slots & parking ---
    def create_dock_slot(self, dock_id, payload, headers):
        return self._request("POST", f"/docks/{dock_id}/dock-slots", payload, headers)

    def get_dock_slot(self, slot_id, headers):
        return self._request("GET", f"/dock-slots/{slot_id}", headers=headers)

    def list_vessel_dock_slots(self, vessel_id, headers, params=None):
        return self._request("GET", f"/vessels/{vessel_id}/dock-slots",
                             headers=headers, params=params)

    def create_parking_pass(self, dock_id, payload, headers):
        return self._request("POST", f"/docks/{dock_id}/parking-passes",
                             payload, headers)

    def get_parking_pass(self, pass_id, headers):
        return self._request("GET", f"/parking-passes/{pass_id}", headers=headers)

    def list_booking_parking_passes(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/parking-passes",
                             headers=headers, params=params)

    def list_cruise_parking_passes(self, cruise_id, headers, params=None):
        return self._request("GET", f"/cruises/{cruise_id}/parking-passes",
                             headers=headers, params=params)

    def redeem_parking_pass(self, pass_id, headers):
        return self._request("POST", f"/parking-passes/{pass_id}/redeem",
                             headers=headers)

    def release_parking_pass(self, pass_id, headers):
        return self._request("POST", f"/parking-passes/{pass_id}/release",
                             headers=headers)

    # --- FK reverse-reachability reads ---
    def list_booking_charter_cruises(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/charter-cruises",
                             headers=headers, params=params)


api_client = ApiClient()
