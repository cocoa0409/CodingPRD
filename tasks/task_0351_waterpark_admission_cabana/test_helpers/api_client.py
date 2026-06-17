"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Park ----
    def create_park(self, payload, headers):
        return self._request("POST", "/parks", payload, headers)

    def get_park(self, park_id, headers):
        return self._request("GET", f"/parks/{park_id}", headers=headers)

    def list_parks(self, headers, params=None):
        return self._request("GET", "/parks", headers=headers, params=params)

    def set_park_weather(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/weather", payload, headers)

    # ---- PricingPolicy ----
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/pricing-policies", payload, headers)

    def list_pricing_policies(self, headers, params=None):
        return self._request("GET", "/pricing-policies", headers=headers, params=params)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/pricing-policies/{policy_id}", headers=headers)

    # ---- EntryWindow ----
    def create_entry_window(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/entry-windows", payload, headers)

    def list_park_entry_windows(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/entry-windows", headers=headers, params=params)

    def get_entry_window(self, window_id, headers):
        return self._request("GET", f"/entry-windows/{window_id}", headers=headers)

    def restrict_entry_window(self, window_id, headers):
        return self._request("POST", f"/entry-windows/{window_id}/restrict", {}, headers)

    def reopen_entry_window(self, window_id, headers):
        return self._request("POST", f"/entry-windows/{window_id}/reopen", {}, headers)

    def close_entry_window(self, window_id, payload, headers):
        return self._request("POST", f"/entry-windows/{window_id}/close", payload, headers)

    def rain_out_entry_window(self, window_id, headers):
        return self._request("POST", f"/entry-windows/{window_id}/rain-out", {}, headers)

    # ---- Cabana / Locker inventory ----
    def create_cabana(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/cabanas", payload, headers)

    def list_park_cabanas(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/cabanas", headers=headers, params=params)

    def get_cabana(self, cabana_id, headers):
        return self._request("GET", f"/cabanas/{cabana_id}", headers=headers)

    def create_locker(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/lockers", payload, headers)

    def list_park_lockers(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/lockers", headers=headers, params=params)

    def get_locker(self, locker_id, headers):
        return self._request("GET", f"/lockers/{locker_id}", headers=headers)

    # ---- Guest ----
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    # ---- Order lifecycle ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/refund", {}, headers)

    def list_order_admissions(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/admissions", headers=headers, params=params)

    def list_order_cabana_rentals(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/cabana-rentals", headers=headers, params=params)

    def list_order_locker_rentals(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/locker-rentals", headers=headers, params=params)

    # ---- Admission lifecycle ----
    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/admissions/{admission_id}", headers=headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/admissions", headers=headers, params=params)

    def bind_guest(self, admission_id, payload, headers):
        return self._request("POST", f"/admissions/{admission_id}/bind-guest", payload, headers)

    def assign_window(self, admission_id, payload, headers):
        return self._request("POST", f"/admissions/{admission_id}/assign-window", payload, headers)

    def check_in_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/check-in", {}, headers)

    def freeze_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/freeze", {}, headers)

    def unfreeze_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/unfreeze", {}, headers)

    def cancel_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/cancel", {}, headers)

    # ---- Cabana / Locker rentals ----
    def create_cabana_rental(self, payload, headers):
        return self._request("POST", "/cabana-rentals", payload, headers)

    def get_cabana_rental(self, rental_id, headers):
        return self._request("GET", f"/cabana-rentals/{rental_id}", headers=headers)

    def list_cabana_rentals(self, headers, params=None):
        return self._request("GET", "/cabana-rentals", headers=headers, params=params)

    def list_cabana_cabana_rentals(self, cabana_id, headers, params=None):
        return self._request("GET", f"/cabanas/{cabana_id}/cabana-rentals", headers=headers, params=params)

    def cancel_cabana_rental(self, rental_id, headers):
        return self._request("POST", f"/cabana-rentals/{rental_id}/cancel", {}, headers)

    def create_locker_rental(self, payload, headers):
        return self._request("POST", "/locker-rentals", payload, headers)

    def get_locker_rental(self, rental_id, headers):
        return self._request("GET", f"/locker-rentals/{rental_id}", headers=headers)

    def list_locker_locker_rentals(self, locker_id, headers, params=None):
        return self._request("GET", f"/lockers/{locker_id}/locker-rentals", headers=headers, params=params)

    # ---- RainCheck ----
    def get_rain_check(self, rain_check_id, headers):
        return self._request("GET", f"/rain-checks/{rain_check_id}", headers=headers)

    def list_rain_checks(self, headers, params=None):
        return self._request("GET", "/rain-checks", headers=headers, params=params)

    def settle_rain_check(self, rain_check_id, headers):
        return self._request("POST", f"/rain-checks/{rain_check_id}/settle", {}, headers)

    def expire_rain_check(self, rain_check_id, headers):
        return self._request("POST", f"/rain-checks/{rain_check_id}/expire", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
