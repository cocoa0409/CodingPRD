"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def get_diversity_report(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/departments/{department_id}/diversity-report",
            headers=headers, params=params,
        )

    # --- vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendor_quotes(self, vendor_id, headers, params=None):
        return self._request(
            "GET", f"/vendors/{vendor_id}/quotes", headers=headers, params=params
        )

    def suspend_vendor(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", payload, headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reinstate", headers=headers)

    # --- grants ---
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def get_grant_budget_ledger(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}/budget-ledger", headers=headers)

    def suspend_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/suspend", headers=headers)

    def reinstate_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/reinstate", headers=headers)

    def close_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/close", headers=headers)

    # --- contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def submit_contract_review(self, contract_id, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/submit-review", headers=headers
        )

    def negotiate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/negotiate", payload, headers
        )

    def approve_contract_review(self, contract_id, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/approve-review", headers=headers
        )

    def execute_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/execute", headers=headers)

    def amend_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/amend", payload, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/terminate", payload, headers
        )

    # --- requisitions ---
    def create_requisition(self, payload, headers):
        return self._request("POST", "/requisitions", payload, headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/requisitions", headers=headers, params=params)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/requisitions/{requisition_id}", headers=headers)

    def patch_requisition(self, requisition_id, payload, headers):
        return self._request("PATCH", f"/requisitions/{requisition_id}", payload, headers)

    def submit_requisition(self, requisition_id, headers):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/submit", headers=headers
        )

    def approve_requisition_step(self, requisition_id, payload, headers):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/approve-step", payload, headers
        )

    def return_requisition_step(self, requisition_id, payload, headers):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/return-step", payload, headers
        )

    def cancel_requisition(self, requisition_id, headers):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/cancel", headers=headers
        )

    def list_requisition_approvals(self, requisition_id, headers, params=None):
        return self._request(
            "GET", f"/requisitions/{requisition_id}/approvals",
            headers=headers, params=params,
        )

    def issue_po(self, requisition_id, headers):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/issue-po", headers=headers
        )

    # --- solicitations & quotes ---
    def create_solicitation(self, requisition_id, payload, headers):
        return self._request(
            "POST", f"/requisitions/{requisition_id}/solicitations", payload, headers
        )

    def list_requisition_solicitations(self, requisition_id, headers, params=None):
        return self._request(
            "GET", f"/requisitions/{requisition_id}/solicitations",
            headers=headers, params=params,
        )

    def get_solicitation(self, solicitation_id, headers):
        return self._request("GET", f"/solicitations/{solicitation_id}", headers=headers)

    def create_quote(self, solicitation_id, payload, headers):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/quotes", payload, headers
        )

    def list_solicitation_quotes(self, solicitation_id, headers, params=None):
        return self._request(
            "GET", f"/solicitations/{solicitation_id}/quotes",
            headers=headers, params=params,
        )

    def close_solicitation(self, solicitation_id, headers):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/close", headers=headers
        )

    def award_solicitation(self, solicitation_id, payload, headers):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/award", payload, headers
        )

    def cancel_solicitation(self, solicitation_id, headers):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/cancel", headers=headers
        )

    # --- purchase orders, receipts, invoices ---
    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", headers=headers)

    def create_receipt(self, po_id, payload, headers):
        return self._request(
            "POST", f"/purchase-orders/{po_id}/receipts", payload, headers
        )

    def list_po_receipts(self, po_id, headers, params=None):
        return self._request(
            "GET", f"/purchase-orders/{po_id}/receipts", headers=headers, params=params
        )

    def void_receipt(self, receipt_id, headers):
        return self._request("POST", f"/receipts/{receipt_id}/void", headers=headers)

    def create_invoice(self, po_id, payload, headers):
        return self._request(
            "POST", f"/purchase-orders/{po_id}/invoices", payload, headers
        )

    def list_po_invoices(self, po_id, headers, params=None):
        return self._request(
            "GET", f"/purchase-orders/{po_id}/invoices", headers=headers, params=params
        )

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def resolve_invoice_exception(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/resolve-exception", payload, headers
        )

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", headers=headers)

    # --- p-cards ---
    def create_pcard(self, payload, headers):
        return self._request("POST", "/pcards", payload, headers)

    def list_pcards(self, headers, params=None):
        return self._request("GET", "/pcards", headers=headers, params=params)

    def get_pcard(self, pcard_id, headers):
        return self._request("GET", f"/pcards/{pcard_id}", headers=headers)

    def patch_pcard_limits(self, pcard_id, payload, headers):
        return self._request("PATCH", f"/pcards/{pcard_id}/limits", payload, headers)

    def suspend_pcard(self, pcard_id, headers):
        return self._request("POST", f"/pcards/{pcard_id}/suspend", headers=headers)

    def reinstate_pcard(self, pcard_id, headers):
        return self._request("POST", f"/pcards/{pcard_id}/reinstate", headers=headers)

    def close_pcard(self, pcard_id, headers):
        return self._request("POST", f"/pcards/{pcard_id}/close", headers=headers)

    def close_pcard_cycle(self, pcard_id, headers):
        return self._request("POST", f"/pcards/{pcard_id}/close-cycle", headers=headers)

    def create_elevation(self, pcard_id, payload, headers):
        return self._request("POST", f"/pcards/{pcard_id}/elevations", payload, headers)

    def list_pcard_elevations(self, pcard_id, headers, params=None):
        return self._request(
            "GET", f"/pcards/{pcard_id}/elevations", headers=headers, params=params
        )

    def cancel_elevation(self, elevation_id, headers):
        return self._request(
            "POST", f"/pcard-elevations/{elevation_id}/cancel", headers=headers
        )

    # --- p-card transactions ---
    def create_pcard_transaction(self, pcard_id, payload, headers):
        return self._request(
            "POST", f"/pcards/{pcard_id}/transactions", payload, headers
        )

    def list_pcard_transactions(self, pcard_id, headers, params=None):
        return self._request(
            "GET", f"/pcards/{pcard_id}/transactions", headers=headers, params=params
        )

    def list_all_pcard_transactions(self, headers, params=None):
        return self._request("GET", "/pcard-transactions", headers=headers, params=params)

    def get_pcard_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/pcard-transactions/{transaction_id}", headers=headers
        )

    def reconcile_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/pcard-transactions/{transaction_id}/reconcile", payload, headers
        )

    def dispute_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/pcard-transactions/{transaction_id}/dispute", payload, headers
        )

    def resolve_dispute(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/pcard-transactions/{transaction_id}/resolve-dispute",
            payload, headers,
        )

    # --- surplus ---
    def create_surplus_asset(self, payload, headers):
        return self._request("POST", "/surplus-assets", payload, headers)

    def list_surplus_assets(self, headers, params=None):
        return self._request("GET", "/surplus-assets", headers=headers, params=params)

    def get_surplus_asset(self, asset_id, headers):
        return self._request("GET", f"/surplus-assets/{asset_id}", headers=headers)

    def claim_surplus_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/surplus-assets/{asset_id}/claim", payload, headers
        )

    def list_surplus_asset_for_sale(self, asset_id, headers):
        return self._request(
            "POST", f"/surplus-assets/{asset_id}/list-for-sale", headers=headers
        )

    def sell_surplus_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/surplus-assets/{asset_id}/sell", payload, headers)

    def donate_surplus_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/surplus-assets/{asset_id}/donate", payload, headers
        )

    def scrap_surplus_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/surplus-assets/{asset_id}/scrap", payload, headers
        )


api_client = ApiClient()
