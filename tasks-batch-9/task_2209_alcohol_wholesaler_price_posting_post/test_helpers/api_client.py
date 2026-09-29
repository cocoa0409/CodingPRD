"""API client: one method per endpoint defined in the PRD.

Every path is mounted at the service root; there is no shared API prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Alcohol Price Posting API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # State programs
    # ------------------------------------------------------------------
    def create_state_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/state-programs", payload, headers)

    def get_state_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/state-programs/{program_id}", headers=headers)

    def list_state_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/state-programs", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Wholesalers
    # ------------------------------------------------------------------
    def create_wholesaler(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/wholesalers", payload, headers)

    def set_wholesaler_license_status(
        self, wholesaler_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/wholesalers/{wholesaler_id}/license-status", payload, headers
        )

    def get_wholesaler(self, wholesaler_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/wholesalers/{wholesaler_id}", headers=headers)

    def list_wholesalers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/wholesalers", headers=headers, params=params)

    def get_penalty_exposure(
        self, wholesaler_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/wholesalers/{wholesaler_id}/penalty-exposure",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Licensee users
    # ------------------------------------------------------------------
    def create_licensee_user(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/licensee-users", payload, headers)

    def get_licensee_user(self, user_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/licensee-users/{user_id}", headers=headers)

    def list_licensee_users(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/licensee-users", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Brands
    # ------------------------------------------------------------------
    def create_brand(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/brands", payload, headers)

    def approve_brand(self, brand_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/brands/{brand_id}/approve", payload, headers)

    def reject_brand(self, brand_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/brands/{brand_id}/reject", payload, headers)

    def get_brand(self, brand_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def list_brands(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/brands", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Price schedules
    # ------------------------------------------------------------------
    def create_price_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/price-schedules", payload, headers)

    def submit_price_schedule(
        self, schedule_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/price-schedules/{schedule_id}/submit", payload, headers
        )

    def return_price_schedule_for_correction(
        self, schedule_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/price-schedules/{schedule_id}/return-for-correction", payload, headers
        )

    def certify_price_schedule(
        self, schedule_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/price-schedules/{schedule_id}/certify", payload, headers
        )

    def withdraw_price_schedule(
        self, schedule_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/price-schedules/{schedule_id}/withdraw", payload, headers
        )

    def get_price_schedule(self, schedule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/price-schedules/{schedule_id}", headers=headers)

    def list_price_schedules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/price-schedules", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Price schedule items
    # ------------------------------------------------------------------
    def create_price_schedule_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/price-schedule-items", payload, headers)

    def get_price_schedule_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/price-schedule-items/{item_id}", headers=headers)

    def list_price_schedule_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/price-schedule-items", headers=headers, params=params)

    def get_posted_price(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/price-schedule-items/{item_id}/posted-price",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Quantity discount tiers
    # ------------------------------------------------------------------
    def create_quantity_discount_tier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/quantity-discount-tiers", payload, headers)

    def get_quantity_discount_tier(self, tier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/quantity-discount-tiers/{tier_id}", headers=headers)

    def list_quantity_discount_tiers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/quantity-discount-tiers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Combination sales
    # ------------------------------------------------------------------
    def create_combination_sale(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/combination-sales", payload, headers)

    def get_combination_sale(self, combination_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/combination-sales/{combination_id}", headers=headers)

    def list_combination_sales(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/combination-sales", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Hold amendments
    # ------------------------------------------------------------------
    def create_hold_amendment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hold-amendments", payload, headers)

    def accept_hold_amendment(
        self, amendment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/hold-amendments/{amendment_id}/accept", payload, headers
        )

    def reject_hold_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hold-amendments/{amendment_id}/reject", payload, headers
        )

    def revoke_hold_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hold-amendments/{amendment_id}/revoke", payload, headers
        )

    def get_hold_amendment(self, amendment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hold-amendments/{amendment_id}", headers=headers)

    def list_hold_amendments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/hold-amendments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Error corrections
    # ------------------------------------------------------------------
    def create_error_correction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/error-corrections", payload, headers)

    def approve_error_correction(
        self, correction_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/error-corrections/{correction_id}/approve", payload, headers
        )

    def deny_error_correction(
        self, correction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/error-corrections/{correction_id}/deny", payload, headers
        )

    def get_error_correction(self, correction_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/error-corrections/{correction_id}", headers=headers)

    def list_error_corrections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/error-corrections", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Retailer invoices
    # ------------------------------------------------------------------
    def create_retailer_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/retailer-invoices", payload, headers)

    def validate_retailer_invoice(
        self, invoice_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/retailer-invoices/{invoice_id}/validate", payload, headers
        )

    def get_retailer_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/retailer-invoices/{invoice_id}", headers=headers)

    def list_retailer_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/retailer-invoices", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Invoice lines
    # ------------------------------------------------------------------
    def create_invoice_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/invoice-lines", payload, headers)

    def get_invoice_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/invoice-lines/{line_id}", headers=headers)

    def list_invoice_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Compliance audits
    # ------------------------------------------------------------------
    def create_compliance_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/compliance-audits", payload, headers)

    def collect_compliance_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/compliance-audits/{audit_id}/collect", payload, headers
        )

    def assess_compliance_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/compliance-audits/{audit_id}/assess", payload, headers
        )

    def close_compliance_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/compliance-audits/{audit_id}/close", payload, headers
        )

    def void_compliance_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/compliance-audits/{audit_id}/void", payload, headers
        )

    def get_compliance_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/compliance-audits/{audit_id}", headers=headers)

    def list_compliance_audits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/compliance-audits", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Audit findings
    # ------------------------------------------------------------------
    def get_audit_finding(self, finding_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/audit-findings/{finding_id}", headers=headers)

    def list_audit_findings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-findings", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Posting runs
    # ------------------------------------------------------------------
    def create_posting_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/posting-runs", payload, headers)


api_client = ApiClient()
