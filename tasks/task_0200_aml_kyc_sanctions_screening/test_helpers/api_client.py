"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer CRUD + CDD lifecycle ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def create_risk_assessment(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/risk-assessments", payload, headers)

    def list_risk_assessments(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/risk-assessments", headers=headers, params=params)

    def apply_rating(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/apply-rating", payload, headers)

    def clear_screening(self, customer_id, headers, payload=None):
        return self._request("POST", f"/customers/{customer_id}/clear-screening", payload or {}, headers)

    def approve_customer(self, customer_id, headers, payload=None):
        return self._request("POST", f"/customers/{customer_id}/approve", payload or {}, headers)

    def complete_edd(self, customer_id, headers, payload=None):
        return self._request("POST", f"/customers/{customer_id}/complete-edd", payload or {}, headers)

    def offboard_customer(self, customer_id, headers, payload=None):
        return self._request("POST", f"/customers/{customer_id}/offboard", payload or {}, headers)

    # ---- Beneficial owners ----
    def create_beneficial_owner(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/beneficial-owners", payload, headers)

    def list_beneficial_owners(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/beneficial-owners", headers=headers, params=params)

    def get_beneficial_owner(self, bo_id, headers):
        return self._request("GET", f"/beneficial-owners/{bo_id}", headers=headers)

    def screen_beneficial_owner(self, bo_id, payload, headers):
        return self._request("POST", f"/beneficial-owners/{bo_id}/screen", payload, headers)

    def list_bo_screening_hits(self, bo_id, headers, params=None):
        return self._request("GET", f"/beneficial-owners/{bo_id}/screening-hits", headers=headers, params=params)

    # ---- Screening hits ----
    def create_screening_hit(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/screening-hits", payload, headers)

    def list_screening_hits(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/screening-hits", headers=headers, params=params)

    def disposition_hit(self, hit_id, payload, headers):
        return self._request("POST", f"/screening-hits/{hit_id}/disposition", payload, headers)

    def reopen_hit(self, hit_id, headers, payload=None):
        return self._request("POST", f"/screening-hits/{hit_id}/reopen", payload or {}, headers)

    # ---- Accounts + transactions ----
    def create_account(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/accounts", payload, headers)

    def list_accounts(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def post_transaction(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/transactions", payload, headers)

    def list_transactions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/transactions", headers=headers, params=params)

    def freeze_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/accounts/{account_id}/freeze", payload or {}, headers)

    # ---- Alerts ----
    def list_account_alerts(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/alerts", headers=headers, params=params)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/alerts/{alert_id}", headers=headers)

    # ---- Cases ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def link_alert(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/alerts", payload, headers)

    def disposition_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/disposition", payload, headers)

    def list_case_alerts(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/alerts", headers=headers, params=params)

    # ---- Filings ----
    def create_filing(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/filings", payload, headers)

    def list_case_filings(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def approve_filing(self, filing_id, headers, payload=None):
        return self._request("POST", f"/filings/{filing_id}/approve", payload or {}, headers)

    def submit_filing(self, filing_id, headers, payload=None):
        return self._request("POST", f"/filings/{filing_id}/submit", payload or {}, headers)

    def acknowledge_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/filings/{filing_id}/acknowledge", payload, headers)

    def revise_filing(self, filing_id, headers, payload=None):
        return self._request("POST", f"/filings/{filing_id}/revise", payload or {}, headers)

    # ---- Lookback review ----
    def create_lookback_review(self, payload, headers):
        return self._request("POST", "/lookback-reviews", payload, headers)

    def get_lookback_review(self, review_id, headers):
        return self._request("GET", f"/lookback-reviews/{review_id}", headers=headers)

    def enqueue_lookback_review(self, review_id, headers, payload=None):
        return self._request("POST", f"/lookback-reviews/{review_id}/enqueue", payload or {}, headers)

    def cancel_lookback_review(self, review_id, headers, payload=None):
        return self._request("POST", f"/lookback-reviews/{review_id}/cancel", payload or {}, headers)

    def list_lookback_items(self, review_id, headers, params=None):
        return self._request("GET", f"/lookback-reviews/{review_id}/items", headers=headers, params=params)

    def get_lookback_item(self, item_id, headers):
        return self._request("GET", f"/lookback-items/{item_id}", headers=headers)

    def list_all_lookback_items(self, headers, params=None):
        return self._request("GET", "/lookback-items", headers=headers, params=params)

    def disposition_lookback_item(self, item_id, payload, headers):
        return self._request("POST", f"/lookback-items/{item_id}/disposition", payload, headers)

    # ---- Audit + test-driving ----
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
