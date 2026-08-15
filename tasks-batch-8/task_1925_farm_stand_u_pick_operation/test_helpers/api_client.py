"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/farm/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------
    def create_season(self, payload, headers):
        return self._request("POST", "/farm/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/farm/seasons/{season_id}", headers=headers)

    def activate_season(self, season_id, headers):
        return self._request("POST", f"/farm/seasons/{season_id}/activate", {}, headers)

    def archive_season(self, season_id, headers):
        return self._request("POST", f"/farm/seasons/{season_id}/archive", {}, headers)

    def config_season(self, season_id, payload, headers):
        return self._request("POST", f"/farm/seasons/{season_id}/config", payload, headers)

    # ------------------------------------------------------------------
    # Crops
    # ------------------------------------------------------------------
    def create_crop(self, payload, headers):
        return self._request("POST", "/farm/crops", payload, headers)

    def get_crop(self, crop_id, headers):
        return self._request("GET", f"/farm/crops/{crop_id}", headers=headers)

    def list_crops(self, headers, params=None):
        return self._request("GET", "/farm/crops", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    def create_field(self, payload, headers):
        return self._request("POST", "/farm/fields", payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/farm/fields/{field_id}", headers=headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/farm/fields", headers=headers, params=params)

    def patch_field(self, field_id, payload, headers):
        return self._request("PATCH", f"/farm/fields/{field_id}", payload, headers)

    def open_field(self, field_id, headers):
        return self._request("POST", f"/farm/fields/{field_id}/open", {}, headers)

    def retire_field(self, field_id, headers):
        return self._request("POST", f"/farm/fields/{field_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Field day windows
    # ------------------------------------------------------------------
    def create_window(self, payload, headers):
        return self._request("POST", "/farm/field-day-windows", payload, headers)

    def get_window(self, window_id, headers):
        return self._request("GET", f"/farm/field-day-windows/{window_id}", headers=headers)

    def list_windows(self, headers, params=None):
        return self._request("GET", "/farm/field-day-windows", headers=headers, params=params)

    def open_window(self, window_id, headers):
        return self._request("POST", f"/farm/field-day-windows/{window_id}/open", {}, headers)

    def cancel_window(self, window_id, headers):
        return self._request("POST", f"/farm/field-day-windows/{window_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Pricing policies
    # ------------------------------------------------------------------
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/farm/pricing-policies", payload, headers)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/farm/pricing-policies/{policy_id}", headers=headers)

    def list_pricing_policies(self, headers, params=None):
        return self._request("GET", "/farm/pricing-policies", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Waivers
    # ------------------------------------------------------------------
    def create_waiver(self, payload, headers):
        return self._request("POST", "/farm/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/farm/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/farm/waivers", headers=headers, params=params)

    def void_waiver(self, waiver_id, headers):
        return self._request("POST", f"/farm/waivers/{waiver_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Visit sessions
    # ------------------------------------------------------------------
    def create_visit_session(self, payload, headers):
        return self._request("POST", "/farm/visit-sessions", payload, headers)

    def get_visit_session(self, session_id, headers):
        return self._request("GET", f"/farm/visit-sessions/{session_id}", headers=headers)

    def list_visit_sessions(self, headers, params=None):
        return self._request("GET", "/farm/visit-sessions", headers=headers, params=params)

    def enter_field(self, session_id, headers):
        return self._request("POST", f"/farm/visit-sessions/{session_id}/enter-field", {}, headers)

    def checkout_session(self, session_id, headers):
        return self._request("POST", f"/farm/visit-sessions/{session_id}/checkout", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/farm/visit-sessions/{session_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Harvest lines
    # ------------------------------------------------------------------
    def create_harvest_line(self, payload, headers):
        return self._request("POST", "/farm/harvest-lines", payload, headers)

    def get_harvest_line(self, line_id, headers):
        return self._request("GET", f"/farm/harvest-lines/{line_id}", headers=headers)

    def list_harvest_lines(self, headers, params=None):
        return self._request("GET", "/farm/harvest-lines", headers=headers, params=params)

    def finalize_harvest_line(self, line_id, headers):
        return self._request("POST", f"/farm/harvest-lines/{line_id}/finalize", {}, headers)

    def void_harvest_line(self, line_id, headers):
        return self._request("POST", f"/farm/harvest-lines/{line_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Add-on products
    # ------------------------------------------------------------------
    def create_addon_product(self, payload, headers):
        return self._request("POST", "/farm/addon-products", payload, headers)

    def get_addon_product(self, product_id, headers):
        return self._request("GET", f"/farm/addon-products/{product_id}", headers=headers)

    def list_addon_products(self, headers, params=None):
        return self._request("GET", "/farm/addon-products", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Add-on bookings
    # ------------------------------------------------------------------
    def create_addon_booking(self, payload, headers):
        return self._request("POST", "/farm/addon-bookings", payload, headers)

    def get_addon_booking(self, booking_id, headers):
        return self._request("GET", f"/farm/addon-bookings/{booking_id}", headers=headers)

    def list_addon_bookings(self, headers, params=None):
        return self._request("GET", "/farm/addon-bookings", headers=headers, params=params)

    def redeem_addon_booking(self, booking_id, headers):
        return self._request("POST", f"/farm/addon-bookings/{booking_id}/redeem", {}, headers)

    def release_addon_booking(self, booking_id, headers):
        return self._request("POST", f"/farm/addon-bookings/{booking_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/farm/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/farm/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/farm/payments", headers=headers, params=params)

    def refund_payment(self, payment_id, amount_cents, headers):
        return self._request("POST", f"/farm/payments/{payment_id}/refund",
                             {"amount_cents": amount_cents}, headers)

    # ------------------------------------------------------------------
    # Sales days
    # ------------------------------------------------------------------
    def create_sales_day(self, payload, headers):
        return self._request("POST", "/farm/sales-days", payload, headers)

    def get_sales_day(self, day_id, headers):
        return self._request("GET", f"/farm/sales-days/{day_id}", headers=headers)

    def list_sales_days(self, headers, params=None):
        return self._request("GET", "/farm/sales-days", headers=headers, params=params)

    def open_day(self, day_id, headers):
        return self._request("POST", f"/farm/sales-days/{day_id}/open-day", {}, headers)

    def close_day(self, day_id, headers):
        return self._request("POST", f"/farm/sales-days/{day_id}/close-day", {}, headers)

    def close_weather(self, day_id, headers):
        return self._request("POST", f"/farm/sales-days/{day_id}/close-weather", {}, headers)

    # ------------------------------------------------------------------
    # Offline batches
    # ------------------------------------------------------------------
    def create_offline_batch(self, payload, headers):
        return self._request("POST", "/farm/offline-batches", payload, headers)

    def get_offline_batch(self, batch_pk, headers):
        return self._request("GET", f"/farm/offline-batches/{batch_pk}", headers=headers)

    # ------------------------------------------------------------------
    # Availability calendar
    # ------------------------------------------------------------------
    def get_availability_calendar(self, headers, params=None):
        return self._request("GET", "/farm/availability-calendar",
                             headers=headers, params=params)


api_client = ApiClient()
