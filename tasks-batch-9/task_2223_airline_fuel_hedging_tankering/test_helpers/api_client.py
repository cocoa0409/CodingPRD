"""Endpoint-per-method HTTP client for the Airline Fuel Hedging & Tankering API.

Calling convention, uniform across every method:

* write endpoints  -> ``method(*path_ids, payload=None, headers=None)``
* read endpoints   -> ``method(*path_ids, headers=None, params=None)``

``headers`` is always passed by keyword so that a body-less action such as
``execute_hedge_instrument(instrument_id, headers=TREASURY)`` never accidentally
supplies the payload slot. Every method returns the raw ``requests.Response``
so a test can assert on the status code itself.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """One method per PRD endpoint, plus the logical-clock test hook."""

    # ─── Logical clock (all six roles) ────────────────

    def set_clock(self, current_utc: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", CLOCK_PATH, {"current_utc": current_utc}, headers
        )

    # ─── Hedging policies ─────────────────────────────

    def create_hedge_policy(self, payload: Any = None, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/hedge-policies", payload, headers)

    def get_hedge_policy(
        self, policy_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/hedge-policies/{policy_id}", params, headers
        )

    # ─── Counterparties ───────────────────────────────

    def create_counterparty(self, payload: Any = None, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/counterparties", payload, headers)

    def get_counterparty(
        self,
        counterparty_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"{API_PREFIX}/counterparties/{counterparty_id}", params, headers
        )

    def record_credit_review(
        self, counterparty_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/counterparties/{counterparty_id}/credit-review",
            payload,
            headers,
        )

    def create_collateral_posting(
        self, counterparty_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/counterparties/{counterparty_id}/collateral-postings",
            payload,
            headers,
        )

    def list_counterparty_collateral_postings(
        self,
        counterparty_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/counterparties/{counterparty_id}/collateral-postings",
            params,
            headers,
        )

    # ─── Stations, contracts and inventory ────────────

    def create_station(self, payload: Any = None, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/stations", payload, headers)

    def get_station(
        self, station_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/stations/{station_id}", params, headers
        )

    def create_supply_contract(
        self, station_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/stations/{station_id}/supply-contracts",
            payload,
            headers,
        )

    def list_supply_contracts(
        self,
        station_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/stations/{station_id}/supply-contracts",
            params,
            headers,
        )

    def adjust_station_inventory(
        self, station_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/stations/{station_id}/inventory-adjustments",
            payload,
            headers,
        )

    # ─── Consumption forecasts ────────────────────────

    def create_consumption_forecast(
        self, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/consumption-forecasts", payload, headers
        )

    def list_consumption_forecasts(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/consumption-forecasts", params, headers
        )

    def publish_consumption_forecast(
        self, forecast_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/consumption-forecasts/{forecast_id}/publish",
            payload,
            headers,
        )

    # ─── Hedge programmes ─────────────────────────────

    def create_hedge_program(self, payload: Any = None, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/hedge-programs", payload, headers)

    def get_hedge_program(
        self, program_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/hedge-programs/{program_id}", params, headers
        )

    def list_hedge_programs(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/hedge-programs", params, headers)

    def size_hedge_program(
        self, program_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/hedge-programs/{program_id}/size", payload, headers
        )

    def submit_hedge_program(
        self, program_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/hedge-programs/{program_id}/submit", payload, headers
        )

    def return_hedge_program(
        self, program_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/hedge-programs/{program_id}/return", payload, headers
        )

    def activate_hedge_program(
        self, program_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/hedge-programs/{program_id}/activate",
            payload,
            headers,
        )

    def close_hedge_program(
        self, program_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/hedge-programs/{program_id}/close", payload, headers
        )

    def create_hedge_instrument(
        self, program_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/hedge-programs/{program_id}/instruments",
            payload,
            headers,
        )

    def list_program_instruments(
        self,
        program_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/hedge-programs/{program_id}/instruments",
            params,
            headers,
        )

    # ─── Hedge instruments ────────────────────────────

    def get_hedge_instrument(
        self,
        instrument_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"{API_PREFIX}/hedge-instruments/{instrument_id}", params, headers
        )

    def list_hedge_instruments(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/hedge-instruments", params, headers)

    def execute_hedge_instrument(
        self, instrument_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/hedge-instruments/{instrument_id}/execute",
            payload,
            headers,
        )

    def designate_hedge_instrument(
        self, instrument_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/hedge-instruments/{instrument_id}/designate",
            payload,
            headers,
        )

    def terminate_hedge_instrument(
        self, instrument_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/hedge-instruments/{instrument_id}/terminate",
            payload,
            headers,
        )

    def create_effectiveness_test(
        self, instrument_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/hedge-instruments/{instrument_id}/effectiveness-tests",
            payload,
            headers,
        )

    def list_effectiveness_tests(
        self,
        instrument_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/hedge-instruments/{instrument_id}/effectiveness-tests",
            params,
            headers,
        )

    def list_instrument_collateral_postings(
        self,
        instrument_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/hedge-instruments/{instrument_id}/collateral-postings",
            params,
            headers,
        )

    # ─── Collateral postings ──────────────────────────

    def post_collateral(
        self, posting_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/collateral-postings/{posting_id}/post",
            payload,
            headers,
        )

    def return_collateral(
        self, posting_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/collateral-postings/{posting_id}/return",
            payload,
            headers,
        )

    # ─── Mark-to-market runs ──────────────────────────

    def create_mtm_run(self, payload: Any = None, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/mark-to-market-runs", payload, headers
        )

    def get_mtm_run(
        self, run_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/mark-to-market-runs/{run_id}", params, headers
        )

    def compute_mtm_run(
        self, run_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/mark-to-market-runs/{run_id}/compute",
            payload,
            headers,
        )

    def publish_mtm_run(
        self, run_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/mark-to-market-runs/{run_id}/publish",
            payload,
            headers,
        )

    # ─── Flight legs ──────────────────────────────────

    def create_flight_leg(self, payload: Any = None, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/flight-legs", payload, headers)

    def get_flight_leg(
        self, leg_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/flight-legs/{leg_id}", params, headers
        )

    def list_flight_legs(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/flight-legs", params, headers)

    def create_tankering_directive(
        self, leg_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/flight-legs/{leg_id}/tankering-directives",
            payload,
            headers,
        )

    def list_leg_tankering_directives(
        self, leg_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/flight-legs/{leg_id}/tankering-directives",
            params,
            headers,
        )

    # ─── Tankering directives ─────────────────────────

    def get_tankering_directive(
        self,
        directive_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"{API_PREFIX}/tankering-directives/{directive_id}", params, headers
        )

    def approve_tankering_directive(
        self, directive_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/tankering-directives/{directive_id}/approve",
            payload,
            headers,
        )

    def reject_tankering_directive(
        self, directive_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/tankering-directives/{directive_id}/reject",
            payload,
            headers,
        )

    def request_directive_revision(
        self, directive_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/tankering-directives/{directive_id}/request-revision",
            payload,
            headers,
        )

    def revise_tankering_directive(
        self, directive_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/tankering-directives/{directive_id}/revise",
            payload,
            headers,
        )

    def execute_tankering_directive(
        self, directive_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/tankering-directives/{directive_id}/execute",
            payload,
            headers,
        )

    def reconcile_tankering_directive(
        self, directive_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/tankering-directives/{directive_id}/reconcile",
            payload,
            headers,
        )

    # ─── Policy exceptions ────────────────────────────

    def create_policy_exception(
        self, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request("POST", f"{API_PREFIX}/policy-exceptions", payload, headers)

    def get_policy_exception(
        self,
        exception_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"{API_PREFIX}/policy-exceptions/{exception_id}", params, headers
        )

    def list_policy_exceptions(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/policy-exceptions", params, headers)

    def approve_policy_exception(
        self, exception_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/policy-exceptions/{exception_id}/approve",
            payload,
            headers,
        )

    def deny_policy_exception(
        self, exception_id: str, payload: Any = None, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/policy-exceptions/{exception_id}/deny",
            payload,
            headers,
        )


#: Module-level singleton the pytest `api` fixture hands to every test.
api_client = ApiClient()
