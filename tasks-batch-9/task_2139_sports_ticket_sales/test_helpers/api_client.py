"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ticketing"


class ApiClient(GenericApiClient):
    # ---- Logical clock -------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Seasons -------------------------------------------------------
    def create_season(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"{PREFIX}/seasons/{season_id}", headers=headers)

    def open_renewal(self, season_id, headers):
        return self._request(
            "POST", f"{PREFIX}/seasons/{season_id}/open-renewal", {}, headers
        )

    def run_ops(self, season_id, headers):
        return self._request(
            "POST", f"{PREFIX}/seasons/{season_id}/run-ops", {}, headers
        )

    # ---- Games ---------------------------------------------------------
    def create_game(self, payload, headers):
        return self._request("POST", f"{PREFIX}/games", payload, headers)

    def get_game(self, game_id, headers):
        return self._request("GET", f"{PREFIX}/games/{game_id}", headers=headers)

    def list_games(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/games", headers=headers, params=params)

    def create_scan(self, game_id, payload, headers):
        return self._request("POST", f"{PREFIX}/games/{game_id}/scans", payload, headers)

    # ---- Seats ---------------------------------------------------------
    def create_seats(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seats", payload, headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"{PREFIX}/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/seats", headers=headers, params=params)

    # ---- Season plans --------------------------------------------------
    def create_season_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/season-plans", payload, headers)

    def publish_season_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/season-plans/{plan_id}/publish", {}, headers
        )

    def get_season_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/season-plans/{plan_id}", headers=headers)

    def list_season_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/season-plans", headers=headers, params=params
        )

    # ---- Service reps --------------------------------------------------
    def create_service_rep(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-reps", payload, headers)

    def get_service_rep(self, rep_id, headers):
        return self._request("GET", f"{PREFIX}/service-reps/{rep_id}", headers=headers)

    def list_service_reps(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-reps", headers=headers, params=params
        )

    # ---- Ticket accounts -----------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/accounts", headers=headers, params=params)

    def assign_rep(self, account_id, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/assign-rep", {}, headers
        )

    def log_touchpoint(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/touchpoints", payload, headers
        )

    def get_renewal_quote(self, account_id, plan_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/accounts/{account_id}/renewal-quote",
            headers=headers,
            params={"plan_id": plan_id},
        )

    # ---- Seat holds ----------------------------------------------------
    def create_seat_hold(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seat-holds", payload, headers)

    def release_seat_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/seat-holds/{hold_id}/release", payload, headers
        )

    def get_seat_hold(self, hold_id, headers):
        return self._request("GET", f"{PREFIX}/seat-holds/{hold_id}", headers=headers)

    def list_seat_holds(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/seat-holds", headers=headers, params=params
        )

    # ---- Plan orders ---------------------------------------------------
    def create_plan_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plan-orders", payload, headers)

    def submit_plan_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-orders/{order_id}/submit", {}, headers
        )

    def review_plan_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-orders/{order_id}/review", payload, headers
        )

    def confirm_plan_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-orders/{order_id}/confirm", payload, headers
        )

    def cancel_plan_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-orders/{order_id}/cancel", payload, headers
        )

    def relocate_plan_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-orders/{order_id}/relocate", payload, headers
        )

    def pay_plan_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-orders/{order_id}/payments", payload, headers
        )

    def get_plan_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/plan-orders/{order_id}", headers=headers)

    def list_plan_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/plan-orders", headers=headers, params=params
        )

    # ---- Hospitality packages ------------------------------------------
    def create_hospitality_package(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hospitality-packages", payload, headers)

    def get_hospitality_package(self, package_id, headers):
        return self._request(
            "GET", f"{PREFIX}/hospitality-packages/{package_id}", headers=headers
        )

    def list_hospitality_packages(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitality-packages", headers=headers, params=params
        )

    # ---- Ticket transfers ----------------------------------------------
    def create_ticket_transfer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ticket-transfers", payload, headers)

    def decide_ticket_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ticket-transfers/{transfer_id}/decision", payload, headers
        )

    def get_ticket_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ticket-transfers/{transfer_id}", headers=headers
        )

    def list_ticket_transfers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ticket-transfers", headers=headers, params=params
        )


api_client = ApiClient()
