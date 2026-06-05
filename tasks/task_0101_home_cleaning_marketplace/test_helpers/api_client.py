"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/cleaning/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/cleaning/customers/{customer_id}", headers=headers)

    def create_credit_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/cleaning/customers/{customer_id}/credit-adjustments", payload, headers)

    # --- Addresses ---
    def create_address(self, payload, headers):
        return self._request("POST", "/cleaning/addresses", payload, headers)

    def get_address(self, address_id, headers):
        return self._request("GET", f"/cleaning/addresses/{address_id}", headers=headers)

    def list_addresses(self, headers, params=None):
        return self._request("GET", "/cleaning/addresses", headers=headers, params=params)

    def archive_address(self, address_id, headers):
        return self._request("POST", f"/cleaning/addresses/{address_id}/archive", {}, headers)

    # --- Cleaners & onboarding ---
    def create_cleaner(self, payload, headers):
        return self._request("POST", "/cleaning/cleaners", payload, headers)

    def get_cleaner(self, cleaner_id, headers):
        return self._request("GET", f"/cleaning/cleaners/{cleaner_id}", headers=headers)

    def list_cleaners(self, headers, params=None):
        return self._request("GET", "/cleaning/cleaners", headers=headers, params=params)

    def create_background_check(self, cleaner_id, payload, headers):
        return self._request("POST", f"/cleaning/cleaners/{cleaner_id}/background-checks", payload, headers)

    def list_cleaner_background_checks(self, cleaner_id, headers, params=None):
        return self._request("GET", f"/cleaning/cleaners/{cleaner_id}/background-checks", headers=headers, params=params)

    def get_background_check(self, check_id, headers):
        return self._request("GET", f"/cleaning/background-checks/{check_id}", headers=headers)

    def adjudicate_background_check(self, check_id, payload, headers):
        return self._request("POST", f"/cleaning/background-checks/{check_id}/adjudicate", payload, headers)

    def activate_cleaner(self, cleaner_id, headers):
        return self._request("POST", f"/cleaning/cleaners/{cleaner_id}/activate", {}, headers)

    def suspend_cleaner(self, cleaner_id, headers):
        return self._request("POST", f"/cleaning/cleaners/{cleaner_id}/suspend", {}, headers)

    # --- Pricing plans ---
    def create_pricing_plan(self, payload, headers):
        return self._request("POST", "/cleaning/pricing-plans", payload, headers)

    def get_pricing_plan(self, plan_id, headers):
        return self._request("GET", f"/cleaning/pricing-plans/{plan_id}", headers=headers)

    def activate_pricing_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/cleaning/pricing-plans/{plan_id}/activate", payload, headers)

    # --- Preferred pros ---
    def create_preferred_pro(self, payload, headers):
        return self._request("POST", "/cleaning/preferred-pros", payload, headers)

    def get_preferred_pro(self, pp_id, headers):
        return self._request("GET", f"/cleaning/preferred-pros/{pp_id}", headers=headers)

    def list_preferred_pros(self, headers, params=None):
        return self._request("GET", "/cleaning/preferred-pros", headers=headers, params=params)

    # --- Booking series ---
    def create_booking_series(self, payload, headers):
        return self._request("POST", "/cleaning/booking-series", payload, headers)

    def get_booking_series(self, series_id, headers):
        return self._request("GET", f"/cleaning/booking-series/{series_id}", headers=headers)

    def list_booking_series(self, headers, params=None):
        return self._request("GET", "/cleaning/booking-series", headers=headers, params=params)

    def generate_occurrence(self, series_id, payload, headers):
        return self._request("POST", f"/cleaning/booking-series/{series_id}/generate", payload, headers)

    def pause_series(self, series_id, headers):
        return self._request("POST", f"/cleaning/booking-series/{series_id}/pause", {}, headers)

    def resume_series(self, series_id, headers):
        return self._request("POST", f"/cleaning/booking-series/{series_id}/resume", {}, headers)

    def cancel_series(self, series_id, headers):
        return self._request("POST", f"/cleaning/booking-series/{series_id}/cancel", {}, headers)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/cleaning/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/cleaning/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/cleaning/bookings", headers=headers, params=params)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/cleaning/bookings/{booking_id}/reschedule", payload, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/cleaning/bookings/{booking_id}/cancel", {}, headers)

    def complete_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/cleaning/bookings/{booking_id}/complete", payload, headers)

    def request_reclean(self, booking_id, headers):
        return self._request("POST", f"/cleaning/bookings/{booking_id}/request-reclean", {}, headers)

    def schedule_reclean(self, booking_id, payload, headers):
        return self._request("POST", f"/cleaning/bookings/{booking_id}/schedule-reclean", payload, headers)

    # --- Tips ---
    def create_tip(self, payload, headers):
        return self._request("POST", "/cleaning/tips", payload, headers)

    def get_tip(self, tip_id, headers):
        return self._request("GET", f"/cleaning/tips/{tip_id}", headers=headers)

    def list_tips(self, headers, params=None):
        return self._request("GET", "/cleaning/tips", headers=headers, params=params)

    # --- Payouts ---
    def get_cleaner_payout(self, payout_id, headers):
        return self._request("GET", f"/cleaning/cleaner-payouts/{payout_id}", headers=headers)

    def list_cleaner_payouts(self, headers, params=None):
        return self._request("GET", "/cleaning/cleaner-payouts", headers=headers, params=params)

    # --- Ledger ---
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/cleaning/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/cleaning/ledger-entries", headers=headers, params=params)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/cleaning/_clock/set_current_utc", payload, headers)

    # --- Test-driving loyalty seed ---
    def set_loyalty_count(self, payload, headers):
        return self._request("POST", "/cleaning/_loyalty/set_count", payload, headers)


api_client = ApiClient()
