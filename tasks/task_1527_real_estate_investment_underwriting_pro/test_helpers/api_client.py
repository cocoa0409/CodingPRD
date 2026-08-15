"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/re-underwriting"


class ApiClient(GenericApiClient):
    # --- Deals ---
    def create_deal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deals", payload, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"{PREFIX}/deals/{deal_id}", headers=headers)

    def submit_underwriting(self, deal_id, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/submit-underwriting", {}, headers)

    def submit_ic(self, deal_id, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/submit-ic", {}, headers)

    def reopen_deal(self, deal_id, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/reopen", {}, headers)

    def mark_dead(self, deal_id, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/mark-dead", {}, headers)

    # --- Properties ---
    def create_property(self, deal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/properties", payload, headers)

    def list_properties(self, deal_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/deals/{deal_id}/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{PREFIX}/properties/{property_id}", headers=headers)

    # --- Rent roll ---
    def create_rent_roll(self, property_id, payload, headers):
        return self._request("POST", f"{PREFIX}/properties/{property_id}/rent-roll", payload, headers)

    def list_rent_roll(self, property_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/properties/{property_id}/rent-roll", headers=headers, params=params)

    # --- Operating expenses ---
    def create_operating_expense(self, property_id, payload, headers):
        return self._request("POST", f"{PREFIX}/properties/{property_id}/operating-expenses", payload, headers)

    def list_operating_expenses(self, property_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/properties/{property_id}/operating-expenses", headers=headers, params=params)

    # --- Market assumptions ---
    def create_assumption(self, deal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/assumptions", payload, headers)

    def activate_assumption(self, assumption_id, headers):
        return self._request("POST", f"{PREFIX}/assumptions/{assumption_id}/activate", {}, headers)

    def list_assumptions(self, deal_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/deals/{deal_id}/assumptions", headers=headers, params=params)

    def get_assumption(self, assumption_id, headers):
        return self._request("GET", f"{PREFIX}/assumptions/{assumption_id}", headers=headers)

    # --- Scenarios ---
    def create_scenario(self, deal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/scenarios", payload, headers)

    def list_scenarios(self, deal_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/deals/{deal_id}/scenarios", headers=headers, params=params)

    def list_all_scenarios(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/scenarios", headers=headers, params=params)

    def get_scenario(self, scenario_id, headers):
        return self._request("GET", f"{PREFIX}/scenarios/{scenario_id}", headers=headers)

    def compute_scenario(self, scenario_id, headers):
        return self._request("POST", f"{PREFIX}/scenarios/{scenario_id}/compute", {}, headers)

    # --- Debt sizing ---
    def create_debt_sizing(self, scenario_id, payload, headers):
        return self._request("POST", f"{PREFIX}/scenarios/{scenario_id}/debt-sizing", payload, headers)

    def list_debt_sizings(self, scenario_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/scenarios/{scenario_id}/debt-sizing", headers=headers, params=params)

    # --- Waterfall ---
    def create_waterfall(self, scenario_id, payload, headers):
        return self._request("POST", f"{PREFIX}/scenarios/{scenario_id}/waterfall", payload, headers)

    def list_waterfalls(self, scenario_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/scenarios/{scenario_id}/waterfall", headers=headers, params=params)

    # --- IC memos ---
    def create_ic_memo(self, deal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deals/{deal_id}/ic-memos", payload, headers)

    def list_ic_memos(self, deal_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/deals/{deal_id}/ic-memos", headers=headers, params=params)

    def list_all_ic_memos(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ic-memos", headers=headers, params=params)

    def get_ic_memo(self, memo_id, headers):
        return self._request("GET", f"{PREFIX}/ic-memos/{memo_id}", headers=headers)

    def submit_ic_memo(self, memo_id, headers):
        return self._request("POST", f"{PREFIX}/ic-memos/{memo_id}/submit", {}, headers)

    def vote_ic_memo(self, memo_id, payload, headers):
        return self._request("POST", f"{PREFIX}/ic-memos/{memo_id}/vote", payload, headers)

    def reject_ic_memo(self, memo_id, payload, headers):
        return self._request("POST", f"{PREFIX}/ic-memos/{memo_id}/reject", payload, headers)

    def list_votes(self, memo_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/ic-memos/{memo_id}/votes", headers=headers, params=params)

    # --- Test-driving logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
