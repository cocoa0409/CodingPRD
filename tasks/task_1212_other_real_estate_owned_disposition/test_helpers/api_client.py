"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- OREO Properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/api/oreo-properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/api/oreo-properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/api/oreo-properties/{property_id}", headers=headers)

    def get_property_summary(self, property_id, headers):
        return self._request(
            "GET", f"/api/oreo-properties/{property_id}/summary", headers=headers
        )

    def charge_off_property(self, property_id, headers):
        return self._request(
            "POST", f"/api/oreo-properties/{property_id}/charge-off", {}, headers
        )

    def broker_recommendation(self, property_id, headers):
        return self._request(
            "GET",
            f"/api/oreo-properties/{property_id}/broker-recommendation",
            headers=headers,
        )

    # --- Carrying Costs ---
    def create_carrying_cost(self, payload, headers):
        return self._request("POST", "/api/carrying-costs", payload, headers)

    def list_carrying_costs(self, headers, params=None):
        return self._request("GET", "/api/carrying-costs", headers=headers, params=params)

    def get_carrying_cost(self, cost_id, headers):
        return self._request("GET", f"/api/carrying-costs/{cost_id}", headers=headers)

    # --- Appraisers ---
    def create_appraiser(self, payload, headers):
        return self._request("POST", "/api/appraisers", payload, headers)

    def list_appraisers(self, headers, params=None):
        return self._request("GET", "/api/appraisers", headers=headers, params=params)

    def get_appraiser(self, appraiser_id, headers):
        return self._request("GET", f"/api/appraisers/{appraiser_id}", headers=headers)

    # --- Appraisals ---
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/api/appraisals", payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/api/appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/api/appraisals/{appraisal_id}", headers=headers)

    def submit_appraisal(self, appraisal_id, headers):
        return self._request(
            "POST", f"/api/appraisals/{appraisal_id}/submit", {}, headers
        )

    def certify_appraisal(self, appraisal_id, headers):
        return self._request(
            "POST", f"/api/appraisals/{appraisal_id}/certify", {}, headers
        )

    def reject_appraisal(self, appraisal_id, payload, headers):
        return self._request(
            "POST", f"/api/appraisals/{appraisal_id}/reject", payload, headers
        )

    # --- Brokers ---
    def create_broker(self, payload, headers):
        return self._request("POST", "/api/brokers", payload, headers)

    def list_brokers(self, headers, params=None):
        return self._request("GET", "/api/brokers", headers=headers, params=params)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/api/brokers/{broker_id}", headers=headers)

    def patch_broker(self, broker_id, payload, headers):
        return self._request("PATCH", f"/api/brokers/{broker_id}", payload, headers)

    # --- Listing Agreements ---
    def create_listing_agreement(self, payload, headers):
        return self._request("POST", "/api/listing-agreements", payload, headers)

    def list_listing_agreements(self, headers, params=None):
        return self._request("GET", "/api/listing-agreements", headers=headers, params=params)

    def get_listing_agreement(self, listing_id, headers):
        return self._request("GET", f"/api/listing-agreements/{listing_id}", headers=headers)

    def activate_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/api/listing-agreements/{listing_id}/activate", {}, headers
        )

    def terminate_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/api/listing-agreements/{listing_id}/terminate", {}, headers
        )

    # --- Offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/api/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/api/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}", headers=headers)

    def submit_offer_review(self, offer_id, headers):
        return self._request(
            "POST", f"/api/offers/{offer_id}/submit-review", {}, headers
        )

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/counter", payload, headers)

    def resume_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/resume", {}, headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/accept", {}, headers)

    def reject_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/reject", {}, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/withdraw", {}, headers)

    def rescind_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/rescind", {}, headers)

    # --- Issues ---
    def create_issue(self, payload, headers):
        return self._request("POST", "/api/issues", payload, headers)

    def list_issues(self, headers, params=None):
        return self._request("GET", "/api/issues", headers=headers, params=params)

    def get_issue(self, issue_id, headers):
        return self._request("GET", f"/api/issues/{issue_id}", headers=headers)

    def start_remediation(self, issue_id, headers):
        return self._request(
            "POST", f"/api/issues/{issue_id}/start-remediation", {}, headers
        )

    def resolve_issue(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/api/issues/{issue_id}/resolve", payload, headers
        )

    def waive_issue(self, issue_id, headers):
        return self._request("POST", f"/api/issues/{issue_id}/waive", {}, headers)

    # --- Write-Downs ---
    def create_write_down(self, payload, headers):
        return self._request("POST", "/api/write-downs", payload, headers)

    def list_write_downs(self, headers, params=None):
        return self._request("GET", "/api/write-downs", headers=headers, params=params)

    def get_write_down(self, write_down_id, headers):
        return self._request("GET", f"/api/write-downs/{write_down_id}", headers=headers)

    def approve_write_down(self, write_down_id, headers):
        return self._request(
            "POST", f"/api/write-downs/{write_down_id}/approve", {}, headers
        )

    def reject_write_down(self, write_down_id, headers):
        return self._request(
            "POST", f"/api/write-downs/{write_down_id}/reject", {}, headers
        )

    # --- Closing Statements ---
    def create_closing_statement(self, payload, headers):
        return self._request("POST", "/api/closing-statements", payload, headers)

    def list_closing_statements(self, headers, params=None):
        return self._request(
            "GET", "/api/closing-statements", headers=headers, params=params
        )

    def get_closing_statement(self, closing_id, headers):
        return self._request(
            "GET", f"/api/closing-statements/{closing_id}", headers=headers
        )

    def settle_closing(self, closing_id, headers):
        return self._request(
            "POST", f"/api/closing-statements/{closing_id}/settle", {}, headers
        )

    def void_closing(self, closing_id, headers):
        return self._request(
            "POST", f"/api/closing-statements/{closing_id}/void", {}, headers
        )

    # --- Extension Requests ---
    def create_extension_request(self, payload, headers):
        return self._request("POST", "/api/extension-requests", payload, headers)

    def list_extension_requests(self, headers, params=None):
        return self._request(
            "GET", "/api/extension-requests", headers=headers, params=params
        )

    def get_extension_request(self, ext_id, headers):
        return self._request("GET", f"/api/extension-requests/{ext_id}", headers=headers)

    def submit_extension_request(self, ext_id, headers):
        return self._request(
            "POST", f"/api/extension-requests/{ext_id}/submit", {}, headers
        )

    def approve_extension_request(self, ext_id, headers):
        return self._request(
            "POST", f"/api/extension-requests/{ext_id}/approve", {}, headers
        )

    def deny_extension_request(self, ext_id, headers):
        return self._request(
            "POST", f"/api/extension-requests/{ext_id}/deny", {}, headers
        )

    def revise_extension_request(self, ext_id, payload, headers):
        return self._request(
            "POST", f"/api/extension-requests/{ext_id}/revise", payload, headers
        )

    # --- Ledger ---
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/api/ledger-entries/{entry_id}", headers=headers)

    # --- Approval Tiers ---
    def create_approval_tier(self, payload, headers):
        return self._request("POST", "/api/approval-tiers", payload, headers)

    def list_approval_tiers(self, headers, params=None):
        return self._request("GET", "/api/approval-tiers", headers=headers, params=params)

    # --- Logical Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
