"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/reit-compliance"


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.7) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- REITs ---
    def create_reit(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/reits", payload, headers)

    def get_reit(self, reit_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/reits/{reit_id}", headers=headers)

    def list_reits(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/reits", headers=headers, params=params)

    def get_ep_balance(self, reit_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/reits/{reit_id}/ep-balance", headers=headers, params=params
        )

    def get_dividend_characterization_preview(
        self, reit_id: str, headers: Dict, params: Dict
    ):
        return self._request(
            "GET",
            f"{PREFIX}/reits/{reit_id}/dividend-characterization-preview",
            headers=headers,
            params=params,
        )

    # --- asset holdings ---
    def create_asset_holding(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/asset-holdings", payload, headers)

    def get_asset_holding(self, holding_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/asset-holdings/{holding_id}", headers=headers
        )

    def list_asset_holdings(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/asset-holdings", headers=headers, params=params
        )

    def update_asset_holding(self, holding_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"{PREFIX}/asset-holdings/{holding_id}", payload, headers
        )

    # --- quarters ---
    def create_quarter(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/quarters", payload, headers)

    def get_quarter(self, quarter_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/quarters/{quarter_id}", headers=headers)

    def list_quarters(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/quarters", headers=headers, params=params)

    # --- income items ---
    def create_income_item(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/income-items", payload, headers)

    def get_income_item(self, item_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/income-items/{item_id}", headers=headers
        )

    def list_income_items(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/income-items", headers=headers, params=params
        )

    def update_income_item(self, item_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"{PREFIX}/income-items/{item_id}", payload, headers
        )

    # --- asset test reports ---
    def create_asset_test_report(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/asset-test-reports", payload, headers)

    def get_asset_test_report(self, report_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/asset-test-reports/{report_id}", headers=headers
        )

    def list_asset_test_reports(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/asset-test-reports", headers=headers, params=params
        )

    def lock_asset_test_report(self, report_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/asset-test-reports/{report_id}/lock", {}, headers
        )

    # --- income test reports ---
    def create_income_test_report(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/income-test-reports", payload, headers)

    def get_income_test_report(self, report_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/income-test-reports/{report_id}", headers=headers
        )

    def list_income_test_reports(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/income-test-reports", headers=headers, params=params
        )

    def lock_income_test_report(self, report_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/income-test-reports/{report_id}/lock", {}, headers
        )

    # --- shareholders ---
    def create_shareholder(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/shareholders", payload, headers)

    def get_shareholder(self, shareholder_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/shareholders/{shareholder_id}", headers=headers
        )

    def list_shareholders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/shareholders", headers=headers, params=params
        )

    def unfreeze_shareholder(self, shareholder_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/shareholders/{shareholder_id}/unfreeze", {}, headers
        )

    # --- shareholder snapshots ---
    def create_shareholder_snapshot(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/shareholder-snapshots", payload, headers
        )

    def get_shareholder_snapshot(self, snapshot_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/shareholder-snapshots/{snapshot_id}", headers=headers
        )

    def list_shareholder_snapshots(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/shareholder-snapshots", headers=headers, params=params
        )

    def finalize_shareholder_snapshot(self, snapshot_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/shareholder-snapshots/{snapshot_id}/finalize",
            {},
            headers,
        )

    # --- shareholder positions ---
    def create_shareholder_position(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/shareholder-positions", payload, headers
        )

    def get_shareholder_position(self, position_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/shareholder-positions/{position_id}", headers=headers
        )

    def list_shareholder_positions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/shareholder-positions", headers=headers, params=params
        )

    # --- distribution requirements ---
    def create_distribution_requirement(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/distribution-requirements", payload, headers
        )

    def get_distribution_requirement(self, requirement_id: str, headers: Dict):
        return self._request(
            "GET",
            f"{PREFIX}/distribution-requirements/{requirement_id}",
            headers=headers,
        )

    def list_distribution_requirements(
        self, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/distribution-requirements", headers=headers, params=params
        )

    def post_distribution_requirement(self, requirement_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/distribution-requirements/{requirement_id}/post",
            {},
            headers,
        )

    def close_distribution_requirement(self, requirement_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/distribution-requirements/{requirement_id}/close",
            {},
            headers,
        )

    # --- dividend declarations ---
    def create_dividend_declaration(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/dividend-declarations", payload, headers
        )

    def get_dividend_declaration(self, declaration_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/dividend-declarations/{declaration_id}", headers=headers
        )

    def list_dividend_declarations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/dividend-declarations", headers=headers, params=params
        )

    def approve_dividend_declaration(self, declaration_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/dividend-declarations/{declaration_id}/approve",
            {},
            headers,
        )

    def declare_dividend_declaration(self, declaration_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/dividend-declarations/{declaration_id}/declare",
            {},
            headers,
        )

    def pay_dividend_declaration(self, declaration_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/dividend-declarations/{declaration_id}/pay", {}, headers
        )

    def void_dividend_declaration(self, declaration_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/dividend-declarations/{declaration_id}/void", {}, headers
        )

    # --- E&P adjustments ---
    def create_ep_adjustment(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/ep-adjustments", payload, headers)

    def get_ep_adjustment(self, adjustment_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/ep-adjustments/{adjustment_id}", headers=headers
        )

    def list_ep_adjustments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/ep-adjustments", headers=headers, params=params
        )

    def post_ep_adjustment(self, adjustment_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/ep-adjustments/{adjustment_id}/post", {}, headers
        )

    # --- asset sales ---
    def create_asset_sale(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/asset-sales", payload, headers)

    def get_asset_sale(self, sale_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/asset-sales/{sale_id}", headers=headers)

    def list_asset_sales(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/asset-sales", headers=headers, params=params
        )

    def analyze_asset_sale(self, sale_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/asset-sales/{sale_id}/analyze", {}, headers
        )

    def confirm_asset_sale(self, sale_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/asset-sales/{sale_id}/confirm", {}, headers
        )

    def void_asset_sale(self, sale_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/asset-sales/{sale_id}/void", {}, headers)

    # --- compliance disclosures ---
    def create_compliance_disclosure(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/compliance-disclosures", payload, headers
        )

    def get_compliance_disclosure(self, disclosure_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/compliance-disclosures/{disclosure_id}", headers=headers
        )

    def list_compliance_disclosures(
        self, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/compliance-disclosures", headers=headers, params=params
        )

    def submit_compliance_disclosure(self, disclosure_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/compliance-disclosures/{disclosure_id}/submit",
            {},
            headers,
        )

    def approve_compliance_disclosure(self, disclosure_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/compliance-disclosures/{disclosure_id}/approve",
            {},
            headers,
        )

    def reject_compliance_disclosure(self, disclosure_id: str, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/compliance-disclosures/{disclosure_id}/reject",
            {},
            headers,
        )


api_client = ApiClient()
