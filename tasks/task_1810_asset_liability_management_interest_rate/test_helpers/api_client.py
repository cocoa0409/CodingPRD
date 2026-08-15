"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- AlmBook ---
    def create_book(self, payload: Dict, headers: Dict):
        return self._request("POST", "/books", payload, headers)

    def get_book(self, book_id: str, headers: Dict):
        return self._request("GET", f"/books/{book_id}", headers=headers)

    def activate_book(self, book_id: str, headers: Dict):
        return self._request("POST", f"/books/{book_id}/activate", {}, headers)

    # --- Position ---
    def create_position(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/positions", payload,
                             headers)

    def list_positions(self, book_id: str, headers: Dict,
                       params: Optional[Dict] = None):
        return self._request("GET", f"/books/{book_id}/positions",
                             headers=headers, params=params)

    def get_position(self, position_id: str, headers: Dict):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    def patch_position(self, position_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/positions/{position_id}", payload,
                             headers)

    def retire_position(self, position_id: str, headers: Dict):
        return self._request("POST", f"/positions/{position_id}/retire", {},
                             headers)

    # --- AssumptionSet ---
    def create_assumption_set(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/assumption-sets",
                             payload, headers)

    def list_assumption_sets(self, book_id: str, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request("GET", f"/books/{book_id}/assumption-sets",
                             headers=headers, params=params)

    def get_assumption_set(self, set_id: str, headers: Dict):
        return self._request("GET", f"/assumption-sets/{set_id}",
                             headers=headers)

    def patch_assumption_set(self, set_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/assumption-sets/{set_id}", payload,
                             headers)

    def submit_assumption_set(self, set_id: str, headers: Dict):
        return self._request("POST", f"/assumption-sets/{set_id}/submit", {},
                             headers)

    def approve_assumption_set(self, set_id: str, headers: Dict):
        return self._request("POST", f"/assumption-sets/{set_id}/approve", {},
                             headers)

    def reject_assumption_set(self, set_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/assumption-sets/{set_id}/reject",
                             payload, headers)

    # --- RateScenario ---
    def create_scenario(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/scenarios", payload,
                             headers)

    def list_scenarios(self, book_id: str, headers: Dict,
                       params: Optional[Dict] = None):
        return self._request("GET", f"/books/{book_id}/scenarios",
                             headers=headers, params=params)

    def get_scenario(self, scenario_id: str, headers: Dict):
        return self._request("GET", f"/scenarios/{scenario_id}", headers=headers)

    def archive_scenario(self, scenario_id: str, headers: Dict):
        return self._request("POST", f"/scenarios/{scenario_id}/archive", {},
                             headers)

    # --- SimulationRun ---
    def create_simulation_run(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/simulation-runs",
                             payload, headers)

    def list_simulation_runs(self, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request("GET", "/simulation-runs", headers=headers,
                             params=params)

    def get_simulation_run(self, run_id: str, headers: Dict):
        return self._request("GET", f"/simulation-runs/{run_id}",
                             headers=headers)

    def publish_simulation_run(self, run_id: str, headers: Dict):
        return self._request("POST", f"/simulation-runs/{run_id}/publish", {},
                             headers)

    # --- PolicyLimit ---
    def create_policy_limit(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/policy-limits", payload,
                             headers)

    def list_policy_limits(self, book_id: str, headers: Dict,
                           params: Optional[Dict] = None):
        return self._request("GET", f"/books/{book_id}/policy-limits",
                             headers=headers, params=params)

    def get_policy_limit(self, limit_id: str, headers: Dict):
        return self._request("GET", f"/policy-limits/{limit_id}",
                             headers=headers)

    def patch_policy_limit(self, limit_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/policy-limits/{limit_id}", payload,
                             headers)

    # --- LimitBreach ---
    def list_breaches(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/breaches", headers=headers, params=params)

    def get_breach(self, breach_id: str, headers: Dict):
        return self._request("GET", f"/breaches/{breach_id}", headers=headers)

    def acknowledge_breach(self, breach_id: str, headers: Dict):
        return self._request("POST", f"/breaches/{breach_id}/acknowledge", {},
                             headers)

    def plan_breach_remediation(self, breach_id: str, payload: Dict,
                                headers: Dict):
        return self._request("POST", f"/breaches/{breach_id}/remediation-plan",
                             payload, headers)

    def close_breach(self, breach_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/breaches/{breach_id}/close", payload,
                             headers)

    # --- HedgeRelationship ---
    def create_hedge(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/hedges", payload,
                             headers)

    def list_book_hedges(self, book_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request("GET", f"/books/{book_id}/hedges", headers=headers,
                             params=params)

    def list_position_hedges(self, position_id: str, headers: Dict):
        return self._request("GET", f"/positions/{position_id}/hedges",
                             headers=headers)

    def get_hedge(self, hedge_id: str, headers: Dict):
        return self._request("GET", f"/hedges/{hedge_id}", headers=headers)

    def designate_hedge(self, hedge_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hedges/{hedge_id}/designate", payload,
                             headers)

    def activate_hedge(self, hedge_id: str, headers: Dict):
        return self._request("POST", f"/hedges/{hedge_id}/activate", {},
                             headers)

    def dedesignate_hedge(self, hedge_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hedges/{hedge_id}/dedesignate",
                             payload, headers)

    def terminate_hedge(self, hedge_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hedges/{hedge_id}/terminate", payload,
                             headers)

    def create_effectiveness_test(self, hedge_id: str, payload: Dict,
                                  headers: Dict):
        return self._request(
            "POST", f"/hedges/{hedge_id}/effectiveness-tests", payload, headers)

    def list_effectiveness_tests(self, hedge_id: str, headers: Dict):
        return self._request("GET", f"/hedges/{hedge_id}/effectiveness-tests",
                             headers=headers)

    # --- BacktestReview ---
    def create_backtest(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/backtests", payload,
                             headers)

    def list_backtests(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/backtests", headers=headers,
                             params=params)

    def get_backtest(self, backtest_id: str, headers: Dict):
        return self._request("GET", f"/backtests/{backtest_id}",
                             headers=headers)

    def close_backtest(self, backtest_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/backtests/{backtest_id}/close",
                             payload, headers)

    # --- AlcoReport ---
    def create_alco_report(self, book_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/books/{book_id}/alco-reports", payload,
                             headers)

    def list_alco_reports(self, book_id: str, headers: Dict,
                          params: Optional[Dict] = None):
        return self._request("GET", f"/books/{book_id}/alco-reports",
                             headers=headers, params=params)

    def get_alco_report(self, report_id: str, headers: Dict):
        return self._request("GET", f"/alco-reports/{report_id}",
                             headers=headers)

    def submit_alco_report(self, report_id: str, headers: Dict):
        return self._request("POST", f"/alco-reports/{report_id}/submit", {},
                             headers)

    def acknowledge_alco_report(self, report_id: str, headers: Dict):
        return self._request("POST", f"/alco-reports/{report_id}/acknowledge",
                             {}, headers)


api_client = ApiClient()
