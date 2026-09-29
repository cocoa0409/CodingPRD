"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def update_branch(self, branch_id, payload, headers):
        return self._request("PATCH", f"/branches/{branch_id}", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    # ------------------------------------------------------------------
    # Parts
    # ------------------------------------------------------------------
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def record_supersession(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/supersession", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    # ------------------------------------------------------------------
    # Model-part cross-references
    # ------------------------------------------------------------------
    def create_model_part_xref(self, payload, headers):
        return self._request("POST", "/model-part-xrefs", payload, headers)

    def list_model_part_xrefs(self, headers, params=None):
        return self._request("GET", "/model-part-xrefs", headers=headers, params=params)

    def get_model_part_xref(self, xref_id, headers):
        return self._request("GET", f"/model-part-xrefs/{xref_id}", headers=headers)

    # ------------------------------------------------------------------
    # Pricing tiers
    # ------------------------------------------------------------------
    def create_pricing_tier(self, payload, headers):
        return self._request("POST", "/pricing-tiers", payload, headers)

    def list_pricing_tiers(self, headers, params=None):
        return self._request("GET", "/pricing-tiers", headers=headers, params=params)

    def get_pricing_tier(self, tier_id, headers):
        return self._request("GET", f"/pricing-tiers/{tier_id}", headers=headers)

    # ------------------------------------------------------------------
    # Servicer accounts
    # ------------------------------------------------------------------
    def create_servicer_account(self, payload, headers):
        return self._request("POST", "/servicer-accounts", payload, headers)

    def update_servicer_account(self, account_id, payload, headers):
        return self._request(
            "PATCH", f"/servicer-accounts/{account_id}", payload, headers
        )

    def tier_review(self, account_id, headers):
        return self._request(
            "POST", f"/servicer-accounts/{account_id}/tier-review", None, headers
        )

    def list_servicer_accounts(self, headers, params=None):
        return self._request(
            "GET", "/servicer-accounts", headers=headers, params=params
        )

    def get_servicer_account(self, account_id, headers):
        return self._request(
            "GET", f"/servicer-accounts/{account_id}", headers=headers
        )

    def get_credit_summary(self, account_id, headers):
        return self._request(
            "GET", f"/servicer-accounts/{account_id}/credit-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # Technician certifications
    # ------------------------------------------------------------------
    def create_technician_certification(self, payload, headers):
        return self._request("POST", "/technician-certifications", payload, headers)

    def revoke_technician_certification(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/technician-certifications/{cert_id}/revoke", payload, headers
        )

    def list_technician_certifications(self, headers, params=None):
        return self._request(
            "GET", "/technician-certifications", headers=headers, params=params
        )

    def get_technician_certification(self, cert_id, headers):
        return self._request(
            "GET", f"/technician-certifications/{cert_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Inventory records
    # ------------------------------------------------------------------
    def create_inventory_record(self, payload, headers):
        return self._request("POST", "/inventory-records", payload, headers)

    def adjust_inventory_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/inventory-records/{record_id}/adjustments", payload, headers
        )

    def list_inventory_records(self, headers, params=None):
        return self._request(
            "GET", "/inventory-records", headers=headers, params=params
        )

    def get_inventory_record(self, record_id, headers):
        return self._request(
            "GET", f"/inventory-records/{record_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Price files
    # ------------------------------------------------------------------
    def create_price_file(self, payload, headers):
        return self._request("POST", "/price-files", payload, headers)

    def create_price_file_line(self, price_file_id, payload, headers):
        return self._request(
            "POST", f"/price-files/{price_file_id}/lines", payload, headers
        )

    def publish_price_file(self, price_file_id, headers):
        return self._request(
            "POST", f"/price-files/{price_file_id}/publish", None, headers
        )

    def rollback_price_file(self, price_file_id, payload, headers):
        return self._request(
            "POST", f"/price-files/{price_file_id}/rollback", payload, headers
        )

    def list_price_files(self, headers, params=None):
        return self._request("GET", "/price-files", headers=headers, params=params)

    def get_price_file(self, price_file_id, headers):
        return self._request("GET", f"/price-files/{price_file_id}", headers=headers)

    def list_price_file_lines(self, headers, params=None):
        return self._request(
            "GET", "/price-file-lines", headers=headers, params=params
        )

    def get_price_file_line(self, line_id, headers):
        return self._request("GET", f"/price-file-lines/{line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Part orders and order lines
    # ------------------------------------------------------------------
    def create_part_order(self, payload, headers):
        return self._request("POST", "/part-orders", payload, headers)

    def add_order_line(self, part_order_id, payload, headers):
        return self._request(
            "POST", f"/part-orders/{part_order_id}/lines", payload, headers
        )

    def cancel_order_line(self, order_line_id, payload, headers):
        return self._request(
            "POST", f"/order-lines/{order_line_id}/cancel", payload, headers
        )

    def credit_decision(self, part_order_id, payload, headers):
        return self._request(
            "POST", f"/part-orders/{part_order_id}/credit-decision", payload, headers
        )

    def allocate_part_order(self, part_order_id, headers):
        return self._request(
            "POST", f"/part-orders/{part_order_id}/allocate", None, headers
        )

    def fulfill_part_order(self, part_order_id, payload, headers):
        return self._request(
            "POST", f"/part-orders/{part_order_id}/fulfill", payload, headers
        )

    def cancel_part_order(self, part_order_id, payload, headers):
        return self._request(
            "POST", f"/part-orders/{part_order_id}/cancel", payload, headers
        )

    def post_payment(self, part_order_id, payload, headers):
        return self._request(
            "POST", f"/part-orders/{part_order_id}/payments", payload, headers
        )

    def list_part_orders(self, headers, params=None):
        return self._request("GET", "/part-orders", headers=headers, params=params)

    def get_part_order(self, part_order_id, headers):
        return self._request("GET", f"/part-orders/{part_order_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Substitute requests
    # ------------------------------------------------------------------
    def decide_substitute_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/substitute-requests/{request_id}/decision", payload, headers
        )

    def withdraw_substitute_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/substitute-requests/{request_id}/withdraw", payload, headers
        )

    def list_substitute_requests(self, headers, params=None):
        return self._request(
            "GET", "/substitute-requests", headers=headers, params=params
        )

    def get_substitute_request(self, request_id, headers):
        return self._request(
            "GET", f"/substitute-requests/{request_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def submit_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/submit", payload, headers
        )

    def record_oem_response(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/oem-response", payload, headers
        )

    def resubmit_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/resubmit", payload, headers
        )

    def credit_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/credit", None, headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    # ------------------------------------------------------------------
    # Return authorizations
    # ------------------------------------------------------------------
    def create_return_authorization(self, payload, headers):
        return self._request("POST", "/return-authorizations", payload, headers)

    def decide_return_authorization(self, ra_id, payload, headers):
        return self._request(
            "POST", f"/return-authorizations/{ra_id}/decision", payload, headers
        )

    def receive_return_authorization(self, ra_id, headers):
        return self._request(
            "POST", f"/return-authorizations/{ra_id}/receive", None, headers
        )

    def list_return_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/return-authorizations", headers=headers, params=params
        )

    def get_return_authorization(self, ra_id, headers):
        return self._request(
            "GET", f"/return-authorizations/{ra_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()
