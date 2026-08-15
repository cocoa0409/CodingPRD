"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/motion/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/motion/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/motion/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/motion/products/{product_id}", headers=headers)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/motion/products/{product_id}", payload, headers)

    # --- Interchange records ---
    def create_interchange_record(self, payload, headers):
        return self._request("POST", "/motion/interchange-records", payload, headers)

    def list_interchange_records(self, headers, params=None):
        return self._request("GET", "/motion/interchange-records", headers=headers, params=params)

    def get_interchange_record(self, record_id, headers):
        return self._request("GET", f"/motion/interchange-records/{record_id}", headers=headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/motion/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/motion/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/motion/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/motion/customers/{customer_id}", payload, headers)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/motion/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/motion/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/motion/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/motion/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/motion/contracts/{contract_id}/terminate", {}, headers)

    # --- Branches ---
    def create_branch(self, payload, headers):
        return self._request("POST", "/motion/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/motion/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/motion/branches/{branch_id}", headers=headers)

    def patch_branch(self, branch_id, payload, headers):
        return self._request("PATCH", f"/motion/branches/{branch_id}", payload, headers)

    # --- Branch stock ---
    def create_branch_stock(self, payload, headers):
        return self._request("POST", "/motion/branch-stocks", payload, headers)

    def list_branch_stocks(self, headers, params=None):
        return self._request("GET", "/motion/branch-stocks", headers=headers, params=params)

    def get_branch_stock(self, stock_id, headers):
        return self._request("GET", f"/motion/branch-stocks/{stock_id}", headers=headers)

    def adjust_branch_stock(self, stock_id, payload, headers):
        return self._request("POST", f"/motion/branch-stocks/{stock_id}/adjust", payload, headers)

    # --- Price files ---
    def create_price_file(self, payload, headers):
        return self._request("POST", "/motion/price-files", payload, headers)

    def list_price_files(self, headers, params=None):
        return self._request("GET", "/motion/price-files", headers=headers, params=params)

    def get_price_file(self, price_file_id, headers):
        return self._request("GET", f"/motion/price-files/{price_file_id}", headers=headers)

    def cancel_price_file(self, price_file_id, headers):
        return self._request("POST", f"/motion/price-files/{price_file_id}/cancel", {}, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/motion/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/motion/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/motion/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/motion/orders/{order_id}/lines", payload, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/motion/orders/{order_id}/confirm", {}, headers)

    def reprice_order(self, order_id, payload, headers):
        return self._request("POST", f"/motion/orders/{order_id}/reprice", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/motion/orders/{order_id}/cancel", {}, headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/motion/orders/{order_id}/invoice", {}, headers)

    def record_payment(self, order_id, payload, headers):
        return self._request("POST", f"/motion/orders/{order_id}/record-payment", payload, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/motion/orders/{order_id}/close", {}, headers)

    # --- Order lines ---
    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/motion/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/motion/order-lines/{line_id}", headers=headers)

    def change_expedite_tier(self, line_id, payload, headers):
        return self._request("POST", f"/motion/order-lines/{line_id}/expedite", payload, headers)

    def reserve_line(self, line_id, payload, headers):
        return self._request("POST", f"/motion/order-lines/{line_id}/reserve", payload, headers)

    def place_factory_order(self, line_id, headers):
        return self._request("POST", f"/motion/order-lines/{line_id}/place-factory-order", {}, headers)

    def receive_factory(self, line_id, headers):
        return self._request("POST", f"/motion/order-lines/{line_id}/receive-factory", {}, headers)

    def allocate_line(self, line_id, headers):
        return self._request("POST", f"/motion/order-lines/{line_id}/allocate", {}, headers)

    def ship_line(self, line_id, headers):
        return self._request("POST", f"/motion/order-lines/{line_id}/ship", {}, headers)

    # --- Stock reservations ---
    def list_stock_reservations(self, headers, params=None):
        return self._request("GET", "/motion/stock-reservations", headers=headers, params=params)

    def get_stock_reservation(self, reservation_id, headers):
        return self._request("GET", f"/motion/stock-reservations/{reservation_id}", headers=headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/motion/stock-reservations/{reservation_id}/release", {}, headers)

    # --- Call-outs ---
    def create_call_out(self, payload, headers):
        return self._request("POST", "/motion/call-outs", payload, headers)

    def list_call_outs(self, headers, params=None):
        return self._request("GET", "/motion/call-outs", headers=headers, params=params)

    def get_call_out(self, call_out_id, headers):
        return self._request("GET", f"/motion/call-outs/{call_out_id}", headers=headers)

    def dispatch_call_out(self, call_out_id, headers):
        return self._request("POST", f"/motion/call-outs/{call_out_id}/dispatch", {}, headers)

    def fulfill_call_out(self, call_out_id, headers):
        return self._request("POST", f"/motion/call-outs/{call_out_id}/fulfill", {}, headers)

    def cancel_call_out(self, call_out_id, headers):
        return self._request("POST", f"/motion/call-outs/{call_out_id}/cancel", {}, headers)

    # --- Consignment agreements ---
    def create_consignment_agreement(self, payload, headers):
        return self._request("POST", "/motion/consignment-agreements", payload, headers)

    def list_consignment_agreements(self, headers, params=None):
        return self._request("GET", "/motion/consignment-agreements", headers=headers, params=params)

    def get_consignment_agreement(self, agreement_id, headers):
        return self._request("GET", f"/motion/consignment-agreements/{agreement_id}", headers=headers)

    def amend_consignment_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/motion/consignment-agreements/{agreement_id}", payload, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/motion/consignment-agreements/{agreement_id}/suspend", {}, headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/motion/consignment-agreements/{agreement_id}/resume", {}, headers)

    def close_agreement(self, agreement_id, headers):
        return self._request("POST", f"/motion/consignment-agreements/{agreement_id}/close", {}, headers)

    # --- Consignment consumptions ---
    def report_consumption(self, agreement_id, payload, headers):
        return self._request("POST", f"/motion/consignment-agreements/{agreement_id}/consumptions",
                             payload, headers)

    def list_consumptions(self, headers, params=None):
        return self._request("GET", "/motion/consignment-consumptions", headers=headers, params=params)

    def get_consumption(self, consumption_id, headers):
        return self._request("GET", f"/motion/consignment-consumptions/{consumption_id}", headers=headers)

    def invoice_consumption(self, consumption_id, headers):
        return self._request("POST", f"/motion/consignment-consumptions/{consumption_id}/invoice", {}, headers)

    def dispute_consumption(self, consumption_id, headers):
        return self._request("POST", f"/motion/consignment-consumptions/{consumption_id}/dispute", {}, headers)

    def credit_consumption(self, consumption_id, headers):
        return self._request("POST", f"/motion/consignment-consumptions/{consumption_id}/credit", {}, headers)

    # --- Warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/motion/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/motion/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/motion/warranty-claims/{claim_id}", headers=headers)

    def begin_analysis(self, claim_id, headers):
        return self._request("POST", f"/motion/warranty-claims/{claim_id}/begin-analysis", {}, headers)

    def request_info(self, claim_id, headers):
        return self._request("POST", f"/motion/warranty-claims/{claim_id}/request-info", {}, headers)

    def render_verdict(self, claim_id, payload, headers):
        return self._request("POST", f"/motion/warranty-claims/{claim_id}/verdict", payload, headers)

    def issue_warranty_credit(self, claim_id, headers):
        return self._request("POST", f"/motion/warranty-claims/{claim_id}/issue-credit", {}, headers)

    # --- Return authorizations ---
    def create_return_authorization(self, payload, headers):
        return self._request("POST", "/motion/return-authorizations", payload, headers)

    def list_return_authorizations(self, headers, params=None):
        return self._request("GET", "/motion/return-authorizations", headers=headers, params=params)

    def get_return_authorization(self, return_id, headers):
        return self._request("GET", f"/motion/return-authorizations/{return_id}", headers=headers)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/motion/return-authorizations/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/motion/return-authorizations/{return_id}/reject", {}, headers)

    def receive_return(self, return_id, payload, headers):
        return self._request("POST", f"/motion/return-authorizations/{return_id}/receive", payload, headers)

    def issue_return_credit(self, return_id, headers):
        return self._request("POST", f"/motion/return-authorizations/{return_id}/issue-credit", {}, headers)

    # --- Service shops ---
    def create_service_shop(self, payload, headers):
        return self._request("POST", "/motion/service-shops", payload, headers)

    def list_service_shops(self, headers, params=None):
        return self._request("GET", "/motion/service-shops", headers=headers, params=params)

    def get_service_shop(self, shop_id, headers):
        return self._request("GET", f"/motion/service-shops/{shop_id}", headers=headers)

    def patch_service_shop(self, shop_id, payload, headers):
        return self._request("PATCH", f"/motion/service-shops/{shop_id}", payload, headers)

    # --- Service referrals ---
    def create_service_referral(self, payload, headers):
        return self._request("POST", "/motion/service-referrals", payload, headers)

    def list_service_referrals(self, headers, params=None):
        return self._request("GET", "/motion/service-referrals", headers=headers, params=params)

    def get_service_referral(self, referral_id, headers):
        return self._request("GET", f"/motion/service-referrals/{referral_id}", headers=headers)

    def accept_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/motion/service-referrals/{referral_id}/accept", payload, headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/motion/service-referrals/{referral_id}/decline", {}, headers)

    def complete_referral(self, referral_id, headers):
        return self._request("POST", f"/motion/service-referrals/{referral_id}/complete", {}, headers)


api_client = ApiClient()
