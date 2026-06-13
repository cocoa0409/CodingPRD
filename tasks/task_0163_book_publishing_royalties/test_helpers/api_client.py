"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Authors ----
    def create_author(self, payload, headers):
        return self._request("POST", "/authors", payload, headers)

    def get_author(self, author_id, headers):
        return self._request("GET", f"/authors/{author_id}", headers=headers)

    def list_authors(self, headers, params=None):
        return self._request("GET", "/authors", headers=headers, params=params)

    # ---- Agents ----
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    # ---- Contracts ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate", payload or {}, headers
        )

    def terminate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/terminate", payload or {}, headers
        )

    # ---- Royalty tiers ----
    def create_royalty_tier(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/royalty-tiers", payload, headers
        )

    def list_royalty_tiers(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/royalty-tiers", headers=headers, params=params
        )

    # ---- Titles ----
    def create_title(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/titles", payload, headers
        )

    def list_titles(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/titles", headers=headers, params=params
        )

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    def publish_title(self, title_id, headers, payload=None):
        return self._request("POST", f"/titles/{title_id}/publish", payload or {}, headers)

    def retire_title(self, title_id, headers, payload=None):
        return self._request("POST", f"/titles/{title_id}/retire", payload or {}, headers)

    # ---- Formats ----
    def create_format(self, title_id, payload, headers):
        return self._request("POST", f"/titles/{title_id}/formats", payload, headers)

    def list_formats(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/titles/{title_id}/formats", headers=headers, params=params
        )

    # ---- Sales periods ----
    def create_sales_period(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/sales-periods", payload, headers
        )

    def list_sales_periods(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/sales-periods", headers=headers, params=params
        )

    def get_sales_period(self, period_id, headers):
        return self._request("GET", f"/sales-periods/{period_id}", headers=headers)

    def close_sales_period(self, period_id, headers, payload=None):
        return self._request(
            "POST", f"/sales-periods/{period_id}/close", payload or {}, headers
        )

    # ---- Sales records ----
    def create_sales_record(self, period_id, payload, headers):
        return self._request(
            "POST", f"/sales-periods/{period_id}/sales-records", payload, headers
        )

    def list_period_sales_records(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/sales-periods/{period_id}/sales-records", headers=headers, params=params
        )

    def list_sales_records(self, headers, params=None):
        return self._request("GET", "/sales-records", headers=headers, params=params)

    def get_sales_record(self, record_id, headers):
        return self._request("GET", f"/sales-records/{record_id}", headers=headers)

    # ---- Subsidiary rights ----
    def create_subsidiary_right(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/subsidiary-rights", payload, headers
        )

    def list_contract_subsidiary_rights(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/subsidiary-rights", headers=headers, params=params
        )

    def get_subsidiary_right(self, right_id, headers):
        return self._request("GET", f"/subsidiary-rights/{right_id}", headers=headers)

    def void_subsidiary_right(self, right_id, headers, payload=None):
        return self._request(
            "POST", f"/subsidiary-rights/{right_id}/void", payload or {}, headers
        )

    # ---- Statements ----
    def generate_statement(self, period_id, headers, payload=None):
        return self._request(
            "POST", f"/sales-periods/{period_id}/generate-statement", payload or {}, headers
        )

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def get_period_statement(self, period_id, headers):
        return self._request("GET", f"/sales-periods/{period_id}/statement", headers=headers)

    def list_contract_statements(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/statements", headers=headers, params=params
        )

    def finalize_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/finalize", payload, headers
        )

    def pay_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/statements/{statement_id}/pay", payload, headers)

    def list_statement_lines(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/statements/{statement_id}/lines", headers=headers, params=params
        )

    # ---- Reserves ----
    def list_contract_reserves(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/reserves", headers=headers, params=params
        )

    def get_reserve(self, reserve_id, headers):
        return self._request("GET", f"/reserves/{reserve_id}", headers=headers)

    def list_statement_reserves(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/statements/{statement_id}/reserves", headers=headers, params=params
        )

    def list_statement_subsidiary_rights(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/statements/{statement_id}/subsidiary-rights", headers=headers, params=params
        )


api_client = ApiClient()
