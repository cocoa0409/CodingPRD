"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

V1 = "/api/v1"


class ApiClient(GenericApiClient):
    # --- RateCase ---
    def create_rate_case(self, payload, headers=None):
        return self._request("POST", f"{V1}/rate-cases", payload, headers)

    def list_rate_cases(self, headers=None, params=None):
        return self._request("GET", f"{V1}/rate-cases", headers=headers, params=params)

    def get_rate_case(self, case_id, headers=None):
        return self._request("GET", f"{V1}/rate-cases/{case_id}", headers=headers)

    def submit_filing(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/submit-filing", {}, headers)

    def deficiency_review(self, case_id, payload, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/deficiency-review", payload, headers)

    def open_discovery(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/open-discovery", {}, headers)

    def advance_to_hearing(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/advance-to-hearing", {}, headers)

    def open_settlement_window(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/open-settlement-window", {}, headers)

    def advance_to_order_pending(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/advance-to-order-pending", {}, headers)

    def issue_order(self, case_id, payload, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/issue-order", payload, headers)

    def implement_rates(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/implement-rates", {}, headers)

    def begin_compliance_monitoring(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/begin-compliance-monitoring", {}, headers)

    def close_case(self, case_id, headers=None):
        return self._request("POST", f"{V1}/rate-cases/{case_id}/close", {}, headers)

    def get_revenue_requirement(self, case_id, headers=None, params=None):
        return self._request("GET", f"{V1}/rate-cases/{case_id}/revenue-requirement", headers=headers, params=params)

    def get_cost_allocation(self, case_id, headers=None, params=None):
        return self._request("GET", f"{V1}/rate-cases/{case_id}/cost-allocation", headers=headers, params=params)

    def get_bill_impact(self, case_id, headers=None, params=None):
        return self._request("GET", f"{V1}/rate-cases/{case_id}/bill-impact", headers=headers, params=params)

    # --- Intervenor ---
    def create_intervenor(self, payload, headers=None):
        return self._request("POST", f"{V1}/intervenors", payload, headers)

    def list_intervenors(self, headers=None, params=None):
        return self._request("GET", f"{V1}/intervenors", headers=headers, params=params)

    def get_intervenor(self, intervenor_id, headers=None):
        return self._request("GET", f"{V1}/intervenors/{intervenor_id}", headers=headers)

    def withdraw_intervenor(self, intervenor_id, headers=None):
        return self._request("POST", f"{V1}/intervenors/{intervenor_id}/withdraw", {}, headers)

    # --- TestYearEntry ---
    def create_test_year_entry(self, payload, headers=None):
        return self._request("POST", f"{V1}/test-year-entries", payload, headers)

    def list_test_year_entries(self, headers=None, params=None):
        return self._request("GET", f"{V1}/test-year-entries", headers=headers, params=params)

    def get_test_year_entry(self, entry_id, headers=None):
        return self._request("GET", f"{V1}/test-year-entries/{entry_id}", headers=headers)

    def submit_entry(self, entry_id, headers=None):
        return self._request("POST", f"{V1}/test-year-entries/{entry_id}/submit", {}, headers)

    def reopen_entry(self, entry_id, headers=None):
        return self._request("POST", f"{V1}/test-year-entries/{entry_id}/reopen", {}, headers)

    def lock_entry(self, entry_id, headers=None):
        return self._request("POST", f"{V1}/test-year-entries/{entry_id}/lock", {}, headers)

    # --- Adjustment ---
    def create_adjustment(self, payload, headers=None):
        return self._request("POST", f"{V1}/adjustments", payload, headers)

    def list_adjustments(self, headers=None, params=None):
        return self._request("GET", f"{V1}/adjustments", headers=headers, params=params)

    def get_adjustment(self, adjustment_id, headers=None):
        return self._request("GET", f"{V1}/adjustments/{adjustment_id}", headers=headers)

    def verify_adjustment(self, adjustment_id, headers=None):
        return self._request("POST", f"{V1}/adjustments/{adjustment_id}/verify", {}, headers)

    def withdraw_adjustment(self, adjustment_id, headers=None):
        return self._request("POST", f"{V1}/adjustments/{adjustment_id}/withdraw", {}, headers)

    def dispute_adjustment(self, adjustment_id, headers=None):
        return self._request("POST", f"{V1}/adjustments/{adjustment_id}/dispute", {}, headers)

    def reject_adjustment(self, adjustment_id, headers=None):
        return self._request("POST", f"{V1}/adjustments/{adjustment_id}/reject", {}, headers)

    # --- RateBaseItem ---
    def create_rate_base_item(self, payload, headers=None):
        return self._request("POST", f"{V1}/rate-base-items", payload, headers)

    def list_rate_base_items(self, headers=None, params=None):
        return self._request("GET", f"{V1}/rate-base-items", headers=headers, params=params)

    def get_rate_base_item(self, item_id, headers=None):
        return self._request("GET", f"{V1}/rate-base-items/{item_id}", headers=headers)

    def submit_rate_base_item(self, item_id, headers=None):
        return self._request("POST", f"{V1}/rate-base-items/{item_id}/submit", {}, headers)

    def audit_rate_base_item(self, item_id, payload, headers=None):
        return self._request("POST", f"{V1}/rate-base-items/{item_id}/audit", payload, headers)

    def revise_rate_base_item(self, item_id, payload, headers=None):
        return self._request("POST", f"{V1}/rate-base-items/{item_id}/revise", payload, headers)

    # --- CustomerClass ---
    def create_customer_class(self, payload, headers=None):
        return self._request("POST", f"{V1}/customer-classes", payload, headers)

    def list_customer_classes(self, headers=None, params=None):
        return self._request("GET", f"{V1}/customer-classes", headers=headers, params=params)

    def get_customer_class(self, class_id, headers=None):
        return self._request("GET", f"{V1}/customer-classes/{class_id}", headers=headers)

    # --- DataRequest ---
    def create_data_request(self, payload, headers=None):
        return self._request("POST", f"{V1}/data-requests", payload, headers)

    def list_data_requests(self, headers=None, params=None):
        return self._request("GET", f"{V1}/data-requests", headers=headers, params=params)

    def get_data_request(self, request_id, headers=None):
        return self._request("GET", f"{V1}/data-requests/{request_id}", headers=headers)

    def respond_data_request(self, request_id, payload, headers=None):
        return self._request("POST", f"{V1}/data-requests/{request_id}/respond", payload, headers)

    def object_data_request(self, request_id, payload, headers=None):
        return self._request("POST", f"{V1}/data-requests/{request_id}/object", payload, headers)

    def rule_data_request(self, request_id, payload, headers=None):
        return self._request("POST", f"{V1}/data-requests/{request_id}/rule", payload, headers)

    def withdraw_data_request(self, request_id, headers=None):
        return self._request("POST", f"{V1}/data-requests/{request_id}/withdraw", {}, headers)

    # --- SettlementProposal ---
    def create_settlement_proposal(self, payload, headers=None):
        return self._request("POST", f"{V1}/settlement-proposals", payload, headers)

    def list_settlement_proposals(self, headers=None, params=None):
        return self._request("GET", f"{V1}/settlement-proposals", headers=headers, params=params)

    def get_settlement_proposal(self, proposal_id, headers=None):
        return self._request("GET", f"{V1}/settlement-proposals/{proposal_id}", headers=headers)

    def circulate_proposal(self, proposal_id, headers=None):
        return self._request("POST", f"{V1}/settlement-proposals/{proposal_id}/circulate", {}, headers)

    def recommend_proposal(self, proposal_id, headers=None):
        return self._request("POST", f"{V1}/settlement-proposals/{proposal_id}/recommend", {}, headers)

    def remand_proposal(self, proposal_id, payload, headers=None):
        return self._request("POST", f"{V1}/settlement-proposals/{proposal_id}/remand", payload, headers)

    # --- SettlementSignatory ---
    def list_settlement_signatories(self, headers=None, params=None):
        return self._request("GET", f"{V1}/settlement-signatories", headers=headers, params=params)

    def get_settlement_signatory(self, signatory_id, headers=None):
        return self._request("GET", f"{V1}/settlement-signatories/{signatory_id}", headers=headers)

    def sign_signatory(self, signatory_id, headers=None):
        return self._request("POST", f"{V1}/settlement-signatories/{signatory_id}/sign", {}, headers)

    def decline_signatory(self, signatory_id, headers=None):
        return self._request("POST", f"{V1}/settlement-signatories/{signatory_id}/decline", {}, headers)

    def rescind_signatory(self, signatory_id, headers=None):
        return self._request("POST", f"{V1}/settlement-signatories/{signatory_id}/rescind", {}, headers)

    # --- RegulatoryAsset ---
    def create_regulatory_asset(self, payload, headers=None):
        return self._request("POST", f"{V1}/regulatory-assets", payload, headers)

    def list_regulatory_assets(self, headers=None, params=None):
        return self._request("GET", f"{V1}/regulatory-assets", headers=headers, params=params)

    def get_regulatory_asset(self, asset_id, headers=None):
        return self._request("GET", f"{V1}/regulatory-assets/{asset_id}", headers=headers)

    # --- AmortizationEntry ---
    def list_amortization_entries(self, headers=None, params=None):
        return self._request("GET", f"{V1}/amortization-entries", headers=headers, params=params)

    def get_amortization_entry(self, entry_id, headers=None):
        return self._request("GET", f"{V1}/amortization-entries/{entry_id}", headers=headers)

    def post_amortization_entry(self, entry_id, headers=None):
        return self._request("POST", f"{V1}/amortization-entries/{entry_id}/post", {}, headers)

    def reverse_amortization_entry(self, entry_id, headers=None):
        return self._request("POST", f"{V1}/amortization-entries/{entry_id}/reverse", {}, headers)

    # --- TariffRate ---
    def create_tariff_rate(self, payload, headers=None):
        return self._request("POST", f"{V1}/tariff-rates", payload, headers)

    def list_tariff_rates(self, headers=None, params=None):
        return self._request("GET", f"{V1}/tariff-rates", headers=headers, params=params)

    def get_tariff_rate(self, tariff_id, headers=None):
        return self._request("GET", f"{V1}/tariff-rates/{tariff_id}", headers=headers)

    # --- ComplianceFiling ---
    def create_compliance_filing(self, payload, headers=None):
        return self._request("POST", f"{V1}/compliance-filings", payload, headers)

    def list_compliance_filings(self, headers=None, params=None):
        return self._request("GET", f"{V1}/compliance-filings", headers=headers, params=params)

    def get_compliance_filing(self, filing_id, headers=None):
        return self._request("GET", f"{V1}/compliance-filings/{filing_id}", headers=headers)

    def submit_compliance_filing(self, filing_id, headers=None):
        return self._request("POST", f"{V1}/compliance-filings/{filing_id}/submit", {}, headers)

    def review_compliance_filing(self, filing_id, payload, headers=None):
        return self._request("POST", f"{V1}/compliance-filings/{filing_id}/review", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
