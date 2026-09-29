"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the warranty claim adjudication service."""

    # --- Logical clock (unprefixed control endpoint) ---

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- State law profiles ---

    def create_state_law_profile(self, payload, headers):
        return self._request("POST", "/warranty/state-law-profiles", payload, headers)

    def get_state_law_profile(self, profile_id, headers):
        return self._request(
            "GET", f"/warranty/state-law-profiles/{profile_id}", headers=headers
        )

    # --- Dealers ---

    def create_dealer(self, payload, headers):
        return self._request("POST", "/warranty/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/warranty/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/warranty/dealers", headers=headers, params=params)

    def list_dealer_ledger_entries(self, dealer_id, headers, params=None):
        return self._request(
            "GET",
            f"/warranty/dealers/{dealer_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    def get_dealer_expense_analytics(self, dealer_id, headers, params=None):
        return self._request(
            "GET",
            f"/warranty/dealers/{dealer_id}/expense-analytics",
            headers=headers,
            params=params,
        )

    # --- Vehicles ---

    def create_vehicle(self, payload, headers):
        return self._request("POST", "/warranty/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/warranty/vehicles/{vehicle_id}", headers=headers)

    # --- Labor operations ---

    def create_labor_operation(self, payload, headers):
        return self._request("POST", "/warranty/labor-operations", payload, headers)

    def get_labor_operation(self, operation_id, headers):
        return self._request(
            "GET", f"/warranty/labor-operations/{operation_id}", headers=headers
        )

    # --- Catalog parts ---

    def create_part(self, payload, headers):
        return self._request("POST", "/warranty/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/warranty/parts/{part_id}", headers=headers)

    # --- Labor rate requests ---

    def create_labor_rate_request(self, payload, headers):
        return self._request("POST", "/warranty/labor-rate-requests", payload, headers)

    def get_labor_rate_request(self, request_id, headers):
        return self._request(
            "GET", f"/warranty/labor-rate-requests/{request_id}", headers=headers
        )

    def list_labor_rate_requests(self, headers, params=None):
        return self._request(
            "GET", "/warranty/labor-rate-requests", headers=headers, params=params
        )

    def review_labor_rate_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/warranty/labor-rate-requests/{request_id}/review", payload, headers
        )

    def decide_labor_rate_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/warranty/labor-rate-requests/{request_id}/decision",
            payload,
            headers,
        )

    def run_deemed_approval(self, headers, payload=None):
        return self._request(
            "POST",
            "/warranty/labor-rate-requests/deemed-approval-run",
            payload if payload is not None else {},
            headers,
        )

    # --- Warranty claims ---

    def create_claim(self, payload, headers):
        return self._request("POST", "/warranty/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/warranty/claims", headers=headers, params=params)

    def list_claim_edits(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/warranty/claims/{claim_id}/edits", headers=headers, params=params
        )

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/resubmit", payload, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/adjudicate", payload, headers
        )

    def void_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty/claims/{claim_id}/void", payload, headers)

    def pay_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"/warranty/claims/{claim_id}/pay",
            payload if payload is not None else {},
            headers,
        )

    # --- Goodwill authorizations ---

    def create_goodwill_authorization(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/goodwill-authorizations", payload, headers
        )

    def get_goodwill_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/warranty/goodwill-authorizations/{authorization_id}", headers=headers
        )

    def list_goodwill_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/warranty/goodwill-authorizations", headers=headers, params=params
        )

    def decide_goodwill_authorization(self, authorization_id, payload, headers):
        return self._request(
            "POST",
            f"/warranty/goodwill-authorizations/{authorization_id}/decision",
            payload,
            headers,
        )

    # --- Parts returns ---

    def get_parts_return(self, parts_return_id, headers):
        return self._request(
            "GET", f"/warranty/parts-returns/{parts_return_id}", headers=headers
        )

    def list_parts_returns(self, headers, params=None):
        return self._request(
            "GET", "/warranty/parts-returns", headers=headers, params=params
        )

    def receive_parts_return(self, parts_return_id, payload, headers):
        return self._request(
            "POST", f"/warranty/parts-returns/{parts_return_id}/receive", payload, headers
        )

    def analyze_parts_return(self, parts_return_id, payload, headers):
        return self._request(
            "POST", f"/warranty/parts-returns/{parts_return_id}/analysis", payload, headers
        )

    def run_non_return_sweep(self, headers, payload=None):
        return self._request(
            "POST",
            "/warranty/parts-returns/non-return-sweep",
            payload if payload is not None else {},
            headers,
        )

    # --- Dealer audits ---

    def create_audit(self, payload, headers):
        return self._request("POST", "/warranty/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/warranty/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/warranty/audits", headers=headers, params=params)

    def start_audit(self, audit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/warranty/audits/{audit_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def create_audit_finding(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/warranty/audits/{audit_id}/findings", payload, headers
        )

    def issue_audit_findings(self, audit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/warranty/audits/{audit_id}/issue-findings",
            payload if payload is not None else {},
            headers,
        )

    def close_audit(self, audit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/warranty/audits/{audit_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # --- Audit findings ---

    def get_audit_finding(self, finding_id, headers):
        return self._request(
            "GET", f"/warranty/audit-findings/{finding_id}", headers=headers
        )

    def list_audit_findings(self, headers, params=None):
        return self._request(
            "GET", "/warranty/audit-findings", headers=headers, params=params
        )

    # --- Audit appeals ---

    def create_appeal(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/warranty/audits/{audit_id}/appeals", payload, headers
        )

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/warranty/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/warranty/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/warranty/appeals/{appeal_id}/decision", payload, headers
        )


api_client = ApiClient()
