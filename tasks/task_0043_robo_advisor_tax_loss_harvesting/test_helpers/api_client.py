"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Securities (PRD §3.1) ──────────────────────────────────────
    def create_security(self, payload, headers):
        return self._request("POST", "/securities", payload, headers)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/securities/{security_id}", headers=headers)

    def list_securities(self, headers, params=None):
        return self._request("GET", "/securities", headers=headers, params=params)

    def update_security_price(self, security_id, payload, headers):
        return self._request(
            "PATCH", f"/securities/{security_id}/price", payload, headers
        )

    def delist_security(self, security_id, headers):
        return self._request(
            "POST", f"/securities/{security_id}/delist", headers=headers
        )

    # ─── Model Portfolios (PRD §3.1) ────────────────────────────────
    def create_model_portfolio(self, payload, headers):
        return self._request("POST", "/model-portfolios", payload, headers)

    def get_model_portfolio(self, model_id, headers):
        return self._request("GET", f"/model-portfolios/{model_id}", headers=headers)

    def list_model_portfolios(self, headers, params=None):
        return self._request(
            "GET", "/model-portfolios", headers=headers, params=params
        )

    def retire_model_portfolio(self, model_id, headers):
        return self._request(
            "POST", f"/model-portfolios/{model_id}/retire", headers=headers
        )

    # ─── Accounts (PRD §3.2, §3.7, §3.8) ────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def freeze_account(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/freeze", headers=headers
        )

    def unfreeze_account(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/unfreeze", headers=headers
        )

    def close_account(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/close", headers=headers
        )

    # ─── Risk Questionnaires (PRD §3.2) ─────────────────────────────
    def create_questionnaire(self, payload, headers):
        return self._request("POST", "/questionnaires", payload, headers)

    def get_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "GET", f"/questionnaires/{questionnaire_id}", headers=headers
        )

    def list_questionnaires(self, headers, params=None):
        return self._request(
            "GET", "/questionnaires", headers=headers, params=params
        )

    def accept_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "POST", f"/questionnaires/{questionnaire_id}/accept", headers=headers
        )

    # ─── Tax Lots (PRD §3.3) ────────────────────────────────────────
    def create_tax_lot(self, payload, headers):
        return self._request("POST", "/tax-lots", payload, headers)

    def get_tax_lot(self, lot_id, headers):
        return self._request("GET", f"/tax-lots/{lot_id}", headers=headers)

    def list_tax_lots(self, headers, params=None):
        return self._request("GET", "/tax-lots", headers=headers, params=params)

    # ─── Harvest Events (PRD §3.4, §3.7) ────────────────────────────
    def create_harvest_event(self, payload, headers):
        return self._request("POST", "/harvest-events", payload, headers)

    def get_harvest_event(self, harvest_id, headers):
        return self._request("GET", f"/harvest-events/{harvest_id}", headers=headers)

    def list_harvest_events(self, headers, params=None):
        return self._request(
            "GET", "/harvest-events", headers=headers, params=params
        )

    def execute_harvest_event(self, harvest_id, headers):
        return self._request(
            "POST", f"/harvest-events/{harvest_id}/execute", headers=headers
        )

    def reject_harvest_event(self, harvest_id, headers):
        return self._request(
            "POST", f"/harvest-events/{harvest_id}/reject", headers=headers
        )

    def reverse_harvest_event(self, harvest_id, headers):
        return self._request(
            "POST", f"/harvest-events/{harvest_id}/reverse", headers=headers
        )

    # ─── Rebalance Events (PRD §3.6) ────────────────────────────────
    def create_rebalance_event(self, payload, headers):
        return self._request("POST", "/rebalance-events", payload, headers)

    def get_rebalance_event(self, rebalance_id, headers):
        return self._request(
            "GET", f"/rebalance-events/{rebalance_id}", headers=headers
        )

    def list_rebalance_events(self, headers, params=None):
        return self._request(
            "GET", "/rebalance-events", headers=headers, params=params
        )

    def execute_rebalance_event(self, rebalance_id, headers):
        return self._request(
            "POST", f"/rebalance-events/{rebalance_id}/execute", headers=headers
        )

    def cancel_rebalance_event(self, rebalance_id, headers):
        return self._request(
            "POST", f"/rebalance-events/{rebalance_id}/cancel", headers=headers
        )

    # ─── Tax Forms (1099-B) (PRD §3.9) ──────────────────────────────
    def create_tax_form(self, payload, headers):
        return self._request("POST", "/tax-forms", payload, headers)

    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/tax-forms/{form_id}", headers=headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/tax-forms", headers=headers, params=params)

    def finalize_tax_form(self, form_id, headers):
        return self._request(
            "POST", f"/tax-forms/{form_id}/finalize", headers=headers
        )

    # ─── Test-driving clock (PRD §3.10) ─────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
