"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

All endpoints are mounted under the /liquidity prefix. Payloads are passed as
JSON bodies for POST/PATCH; query params for GET.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/liquidity/_clock/set_current_utc", payload, headers)

    # ---------------------------------------------------------- scenarios
    def create_scenario(self, payload, headers):
        return self._request("POST", "/liquidity/stress-scenarios", payload, headers)

    def list_scenarios(self, headers, params=None):
        return self._request("GET", "/liquidity/stress-scenarios", headers=headers, params=params)

    def get_scenario(self, scenario_id, headers):
        return self._request("GET", f"/liquidity/stress-scenarios/{scenario_id}", headers=headers)

    def retire_scenario(self, scenario_id, headers):
        return self._request("POST", f"/liquidity/stress-scenarios/{scenario_id}/retire", headers=headers)

    # ------------------------------------------------------ projection runs
    def list_projection_runs(self, scenario_id, headers, params=None):
        return self._request(
            "GET", f"/liquidity/stress-scenarios/{scenario_id}/projection-runs",
            headers=headers, params=params,
        )

    def create_projection_run(self, scenario_id, payload, headers):
        return self._request(
            "POST", f"/liquidity/stress-scenarios/{scenario_id}/projection-runs",
            payload, headers,
        )

    def get_projection_run(self, run_id, headers):
        return self._request("GET", f"/liquidity/projection-runs/{run_id}", headers=headers)

    def finalize_projection_run(self, run_id, headers):
        return self._request("POST", f"/liquidity/projection-runs/{run_id}/finalize", headers=headers)

    # ---------------------------------------------------------- liquid assets
    def create_liquid_asset(self, payload, headers):
        return self._request("POST", "/liquidity/liquid-assets", payload, headers)

    def list_liquid_assets(self, headers, params=None):
        return self._request("GET", "/liquidity/liquid-assets", headers=headers, params=params)

    def reprice_liquid_asset(self, asset_id, payload, headers):
        return self._request("PATCH", f"/liquidity/liquid-assets/{asset_id}", payload, headers)

    def get_hqla_summary(self, scenario_id, headers):
        return self._request(
            "GET", "/liquidity/hqla-summary", headers=headers, params={"scenario_id": scenario_id},
        )

    # ---------------------------------------------------------- funding
    def create_funding_source(self, payload, headers):
        return self._request("POST", "/liquidity/funding-sources", payload, headers)

    def run_funding_evaluation(self, headers):
        return self._request("POST", "/liquidity/funding-evaluations", headers=headers)

    # ---------------------------------------------------------- EWI metrics
    def create_ewi_metric(self, payload, headers):
        return self._request("POST", "/liquidity/ewi-metrics", payload, headers)

    def list_ewi_metrics(self, headers, params=None):
        return self._request("GET", "/liquidity/ewi-metrics", headers=headers, params=params)

    def get_ewi_metric(self, metric_id, headers):
        return self._request("GET", f"/liquidity/ewi-metrics/{metric_id}", headers=headers)

    def post_metric_reading(self, metric_id, payload, headers):
        return self._request(
            "POST", f"/liquidity/ewi-metrics/{metric_id}/readings", payload, headers,
        )

    def list_metric_readings(self, metric_id, headers, params=None):
        return self._request(
            "GET", f"/liquidity/ewi-metrics/{metric_id}/readings",
            headers=headers, params=params,
        )

    def get_ewi_dashboard(self, headers):
        return self._request("GET", "/liquidity/ewi-dashboard", headers=headers)

    # ---------------------------------------------------------- posture
    def run_posture_evaluation(self, headers):
        return self._request("POST", "/liquidity/posture-evaluations", headers=headers)

    def list_posture_snapshots(self, headers, params=None):
        return self._request("GET", "/liquidity/posture-snapshots", headers=headers, params=params)

    # ---------------------------------------------------------- playbooks
    def create_playbook(self, payload, headers):
        return self._request("POST", "/liquidity/contingency-playbooks", payload, headers)

    def list_playbooks(self, headers, params=None):
        return self._request("GET", "/liquidity/contingency-playbooks", headers=headers, params=params)

    def get_playbook(self, playbook_id, headers):
        return self._request(
            "GET", f"/liquidity/contingency-playbooks/{playbook_id}", headers=headers,
        )

    def patch_playbook(self, playbook_id, payload, headers):
        return self._request(
            "PATCH", f"/liquidity/contingency-playbooks/{playbook_id}", payload, headers,
        )

    def add_playbook_action(self, playbook_id, payload, headers):
        return self._request(
            "POST", f"/liquidity/contingency-playbooks/{playbook_id}/actions", payload, headers,
        )

    def list_playbook_actions(self, playbook_id, headers, params=None):
        return self._request(
            "GET", f"/liquidity/contingency-playbooks/{playbook_id}/actions",
            headers=headers, params=params,
        )

    def get_playbook_action(self, action_id, headers):
        return self._request("GET", f"/liquidity/playbook-actions/{action_id}", headers=headers)

    def list_all_playbook_actions(self, headers, params=None):
        return self._request("GET", "/liquidity/playbook-actions", headers=headers, params=params)

    def run_capacity_test(self, playbook_id, headers):
        return self._request(
            "POST", f"/liquidity/contingency-playbooks/{playbook_id}/capacity-test",
            headers=headers,
        )

    def approve_playbook(self, playbook_id, headers):
        return self._request(
            "POST", f"/liquidity/contingency-playbooks/{playbook_id}/approve", headers=headers,
        )

    def activate_playbook(self, playbook_id, headers):
        return self._request(
            "POST", f"/liquidity/contingency-playbooks/{playbook_id}/activate", headers=headers,
        )

    def stand_down_playbook(self, playbook_id, headers):
        return self._request(
            "POST", f"/liquidity/contingency-playbooks/{playbook_id}/stand-down", headers=headers,
        )

    def revise_playbook(self, playbook_id, headers):
        return self._request(
            "POST", f"/liquidity/contingency-playbooks/{playbook_id}/revise", headers=headers,
        )

    def complete_playbook(self, playbook_id, headers):
        return self._request(
            "POST", f"/liquidity/contingency-playbooks/{playbook_id}/complete", headers=headers,
        )

    def execute_playbook_action(self, action_id, headers):
        return self._request(
            "POST", f"/liquidity/playbook-actions/{action_id}/execute", headers=headers,
        )

    def settle_playbook_action(self, action_id, headers):
        return self._request(
            "POST", f"/liquidity/playbook-actions/{action_id}/settle", headers=headers,
        )

    def fail_playbook_action(self, action_id, headers):
        return self._request(
            "POST", f"/liquidity/playbook-actions/{action_id}/fail", headers=headers,
        )

    # ---------------------------------------------------------- borrowing lines
    def create_borrowing_line(self, payload, headers):
        return self._request("POST", "/liquidity/borrowing-lines", payload, headers)

    def get_borrowing_line(self, line_id, headers):
        return self._request("GET", f"/liquidity/borrowing-lines/{line_id}", headers=headers)

    def suspend_borrowing_line(self, line_id, headers):
        return self._request(
            "POST", f"/liquidity/borrowing-lines/{line_id}/suspend", headers=headers,
        )

    def reinstate_borrowing_line(self, line_id, headers):
        return self._request(
            "POST", f"/liquidity/borrowing-lines/{line_id}/reinstate", headers=headers,
        )

    def draw_borrowing_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/liquidity/borrowing-lines/{line_id}/draw", payload, headers,
        )

    def repay_borrowing_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/liquidity/borrowing-lines/{line_id}/repay", payload, headers,
        )

    # ---------------------------------------------------------- pledges
    def create_collateral_pledge(self, payload, headers):
        return self._request("POST", "/liquidity/collateral-pledges", payload, headers)

    def list_collateral_pledges(self, headers, params=None):
        return self._request("GET", "/liquidity/collateral-pledges", headers=headers, params=params)

    def get_collateral_pledge(self, pledge_id, headers):
        return self._request("GET", f"/liquidity/collateral-pledges/{pledge_id}", headers=headers)

    def release_collateral_pledge(self, pledge_id, headers):
        return self._request(
            "POST", f"/liquidity/collateral-pledges/{pledge_id}/release", headers=headers,
        )

    # ---------------------------------------------------------- board limits & breaches
    def create_board_limit(self, payload, headers):
        return self._request("POST", "/liquidity/board-limits", payload, headers)

    def list_board_limits(self, headers, params=None):
        return self._request("GET", "/liquidity/board-limits", headers=headers, params=params)

    def get_board_limit(self, limit_id, headers):
        return self._request("GET", f"/liquidity/board-limits/{limit_id}", headers=headers)

    def list_limit_breaches(self, limit_id, headers, params=None):
        return self._request(
            "GET", f"/liquidity/board-limits/{limit_id}/breaches",
            headers=headers, params=params,
        )

    def get_breach(self, breach_id, headers):
        return self._request("GET", f"/liquidity/breaches/{breach_id}", headers=headers)

    def acknowledge_breach(self, breach_id, headers):
        return self._request(
            "POST", f"/liquidity/breaches/{breach_id}/acknowledge", headers=headers,
        )

    def escalate_breach(self, breach_id, headers):
        return self._request(
            "POST", f"/liquidity/breaches/{breach_id}/escalate", headers=headers,
        )

    def remediate_breach(self, breach_id, payload, headers):
        return self._request(
            "POST", f"/liquidity/breaches/{breach_id}/remediate", payload, headers,
        )

    # ---------------------------------------------------------- intraday
    def post_intraday_snapshot(self, payload, headers):
        return self._request("POST", "/liquidity/intraday-snapshots", payload, headers)

    def list_intraday_snapshots(self, headers, params=None):
        return self._request("GET", "/liquidity/intraday-snapshots", headers=headers, params=params)


api_client = ApiClient()
