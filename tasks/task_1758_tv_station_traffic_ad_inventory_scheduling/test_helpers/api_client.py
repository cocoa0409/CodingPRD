"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Advertisers
    # ------------------------------------------------------------------
    def create_advertiser(self, payload, headers):
        return self._request("POST", "/traffic/advertisers", payload, headers)

    def list_advertisers(self, headers, params=None):
        return self._request("GET", "/traffic/advertisers", headers=headers, params=params)

    def get_advertiser(self, advertiser_id, headers):
        return self._request("GET", f"/traffic/advertisers/{advertiser_id}", headers=headers)

    def list_advertiser_orders(self, advertiser_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/advertisers/{advertiser_id}/orders", headers=headers, params=params
        )

    def list_advertiser_copy_instructions(self, advertiser_id, headers, params=None):
        return self._request(
            "GET",
            f"/traffic/advertisers/{advertiser_id}/copy-instructions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/traffic/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/traffic/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/traffic/programs/{program_id}", headers=headers)

    def list_program_order_lines(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/programs/{program_id}/order-lines", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Avail weeks / avail units
    # ------------------------------------------------------------------
    def create_avail_week(self, payload, headers):
        return self._request("POST", "/traffic/avail-weeks", payload, headers)

    def list_avail_weeks(self, headers, params=None):
        return self._request("GET", "/traffic/avail-weeks", headers=headers, params=params)

    def get_avail_week(self, week_id, headers):
        return self._request("GET", f"/traffic/avail-weeks/{week_id}", headers=headers)

    def create_avail_unit(self, week_id, payload, headers):
        return self._request("POST", f"/traffic/avail-weeks/{week_id}/avail-units", payload, headers)

    def list_avail_units_of_week(self, week_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/avail-weeks/{week_id}/avail-units", headers=headers, params=params
        )

    def get_avail_unit(self, unit_id, headers):
        return self._request("GET", f"/traffic/avail-units/{unit_id}", headers=headers)

    def list_avail_units(self, headers, params=None):
        return self._request("GET", "/traffic/avail-units", headers=headers, params=params)

    def list_unit_spots(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/avail-units/{unit_id}/spots", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Log days
    # ------------------------------------------------------------------
    def create_log_day(self, week_id, payload, headers):
        return self._request("POST", f"/traffic/avail-weeks/{week_id}/log-days", payload, headers)

    def list_log_days_of_week(self, week_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/avail-weeks/{week_id}/log-days", headers=headers, params=params
        )

    def get_log_day(self, log_day_id, headers):
        return self._request("GET", f"/traffic/log-days/{log_day_id}", headers=headers)

    def finalize_log_day(self, log_day_id, headers):
        return self._request("POST", f"/traffic/log-days/{log_day_id}/finalize", {}, headers)

    def reconcile_log_day(self, log_day_id, payload, headers):
        return self._request("POST", f"/traffic/log-days/{log_day_id}/reconcile", payload, headers)

    def list_log_day_as_run_entries(self, log_day_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/log-days/{log_day_id}/as-run-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Orders / order lines
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/traffic/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/traffic/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/traffic/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/traffic/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/orders/{order_id}/lines", headers=headers, params=params
        )

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/traffic/order-lines/{line_id}", headers=headers)

    def cancel_order_line(self, line_id, headers):
        return self._request("POST", f"/traffic/order-lines/{line_id}/cancel", {}, headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/traffic/orders/{order_id}/submit", {}, headers)

    def approve_order(self, order_id, payload, headers):
        return self._request("POST", f"/traffic/orders/{order_id}/approve", payload, headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/traffic/orders/{order_id}/reject", {}, headers)

    def revise_order(self, order_id, headers):
        return self._request("POST", f"/traffic/orders/{order_id}/revise", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/traffic/orders/{order_id}/cancel", {}, headers)

    def get_post_buy(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/orders/{order_id}/post-buy", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Copy instructions
    # ------------------------------------------------------------------
    def create_copy_instruction(self, payload, headers):
        return self._request("POST", "/traffic/copy-instructions", payload, headers)

    def get_copy_instruction(self, copy_id, headers):
        return self._request("GET", f"/traffic/copy-instructions/{copy_id}", headers=headers)

    def receive_copy(self, copy_id, headers):
        return self._request("POST", f"/traffic/copy-instructions/{copy_id}/receive", {}, headers)

    def expire_copy(self, copy_id, headers):
        return self._request("POST", f"/traffic/copy-instructions/{copy_id}/expire", {}, headers)

    def list_copy_instruction_spots(self, copy_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/copy-instructions/{copy_id}/spots", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Spots
    # ------------------------------------------------------------------
    def get_spot(self, spot_id, headers):
        return self._request("GET", f"/traffic/spots/{spot_id}", headers=headers)

    def list_line_spots(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/order-lines/{line_id}/spots", headers=headers, params=params
        )

    def list_spot_make_goods(self, spot_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/spots/{spot_id}/make-goods", headers=headers, params=params
        )

    def list_spot_as_run_entries(self, spot_id, headers, params=None):
        return self._request(
            "GET", f"/traffic/spots/{spot_id}/as-run-entries", headers=headers, params=params
        )

    def place_spot(self, spot_id, payload, headers):
        return self._request("POST", f"/traffic/spots/{spot_id}/place", payload, headers)

    def preempt_spot(self, spot_id, payload, headers):
        return self._request("POST", f"/traffic/spots/{spot_id}/preempt", payload, headers)

    def offer_make_good(self, spot_id, headers):
        return self._request("POST", f"/traffic/spots/{spot_id}/offer-make-good", {}, headers)

    def decline_make_good(self, spot_id, headers):
        return self._request("POST", f"/traffic/spots/{spot_id}/decline-make-good", {}, headers)

    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/traffic/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
