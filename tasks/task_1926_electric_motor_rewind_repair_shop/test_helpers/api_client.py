"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Shop ---
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    # --- Customer ---
    def create_customer(self, shop_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/customers", payload, headers)

    def list_customers(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/customers", headers=headers, params=params)

    def get_customer(self, shop_id, customer_id, headers):
        return self._request("GET", f"/shops/{shop_id}/customers/{customer_id}", headers=headers)

    # --- Motor ---
    def create_motor(self, shop_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/motors", payload, headers)

    def list_motors(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/motors", headers=headers, params=params)

    def get_motor(self, shop_id, motor_id, headers):
        return self._request("GET", f"/shops/{shop_id}/motors/{motor_id}", headers=headers)

    # --- WorkOrder ---
    def create_work_order(self, shop_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders", payload, headers)

    def list_work_orders(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/work-orders", headers=headers, params=params)

    def get_work_order(self, shop_id, wo_id, headers):
        return self._request("GET", f"/shops/{shop_id}/work-orders/{wo_id}", headers=headers)

    def record_test(self, shop_id, wo_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/tests", payload, headers)

    def list_tests(self, shop_id, wo_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/work-orders/{wo_id}/tests", headers=headers, params=params)

    def diagnose_work_order(self, shop_id, wo_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/diagnose", payload, headers)

    def scrap_work_order(self, shop_id, wo_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/scrap", headers=headers)

    # --- Quote ---
    def issue_quote(self, shop_id, wo_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/quotes", payload, headers)

    def list_quotes(self, shop_id, wo_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/work-orders/{wo_id}/quotes", headers=headers, params=params)

    def get_quote(self, shop_id, wo_id, quote_id, headers):
        return self._request("GET", f"/shops/{shop_id}/work-orders/{wo_id}/quotes/{quote_id}", headers=headers)

    def send_quote(self, shop_id, wo_id, quote_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/quotes/{quote_id}/send", headers=headers)

    def accept_quote(self, shop_id, wo_id, quote_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/quotes/{quote_id}/accept", headers=headers)

    def decline_quote(self, shop_id, wo_id, quote_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/quotes/{quote_id}/decline", headers=headers)

    def revise_quote(self, shop_id, wo_id, quote_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/quotes/{quote_id}/revise", headers=headers)

    # --- Rewind process ---
    def start_rewind(self, shop_id, wo_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/start-rewind", headers=headers)

    def create_coil_data(self, shop_id, wo_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/coil-data", payload, headers)

    def list_coil_data(self, shop_id, wo_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/work-orders/{wo_id}/coil-data", headers=headers, params=params)

    def release_work_order(self, shop_id, wo_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/release", headers=headers)

    def deliver_work_order(self, shop_id, wo_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/deliver", payload, headers)

    def close_work_order(self, shop_id, wo_id, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/close", headers=headers)

    # --- Invoice / payments ---
    def list_invoices(self, shop_id, wo_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/work-orders/{wo_id}/invoices", headers=headers, params=params)

    def get_invoice(self, shop_id, invoice_id, headers):
        return self._request("GET", f"/shops/{shop_id}/invoices/{invoice_id}", headers=headers)

    def void_invoice(self, shop_id, invoice_id, headers):
        return self._request("POST", f"/shops/{shop_id}/invoices/{invoice_id}/void", headers=headers)

    def record_payment(self, shop_id, customer_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/customers/{customer_id}/payments", payload, headers)

    # --- Spare pool ---
    def create_pool_contract(self, shop_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/pool-contracts", payload, headers)

    def list_pool_contracts(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/pool-contracts", headers=headers, params=params)

    def get_pool_contract(self, shop_id, contract_id, headers):
        return self._request("GET", f"/shops/{shop_id}/pool-contracts/{contract_id}", headers=headers)

    def suspend_pool_contract(self, shop_id, contract_id, headers):
        return self._request("POST", f"/shops/{shop_id}/pool-contracts/{contract_id}/suspend", headers=headers)

    def resume_pool_contract(self, shop_id, contract_id, headers):
        return self._request("POST", f"/shops/{shop_id}/pool-contracts/{contract_id}/resume", headers=headers)

    def terminate_pool_contract(self, shop_id, contract_id, headers):
        return self._request("POST", f"/shops/{shop_id}/pool-contracts/{contract_id}/terminate", headers=headers)

    def checkout_loan(self, shop_id, contract_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/pool-contracts/{contract_id}/loans", payload, headers)

    def list_loans(self, shop_id, contract_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/pool-contracts/{contract_id}/loans", headers=headers, params=params)

    def return_loan(self, shop_id, contract_id, loan_id, headers):
        return self._request("POST", f"/shops/{shop_id}/pool-contracts/{contract_id}/loans/{loan_id}/return", headers=headers)

    # --- Warranty ---
    def file_warranty_claim(self, shop_id, wo_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/work-orders/{wo_id}/warranty-claims", payload, headers)

    def list_warranty_claims(self, shop_id, wo_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/work-orders/{wo_id}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, shop_id, claim_id, headers):
        return self._request("GET", f"/shops/{shop_id}/warranty-claims/{claim_id}", headers=headers)

    def start_review_claim(self, shop_id, claim_id, headers):
        return self._request("POST", f"/shops/{shop_id}/warranty-claims/{claim_id}/start-review", headers=headers)

    def approve_claim(self, shop_id, claim_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/warranty-claims/{claim_id}/approve", payload, headers)

    def deny_claim(self, shop_id, claim_id, headers):
        return self._request("POST", f"/shops/{shop_id}/warranty-claims/{claim_id}/deny", headers=headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Flat read aliases ---
    def flat_get_customer(self, customer_id, headers):
        return self._request("GET", f"/shops/customers/{customer_id}", headers=headers)

    def flat_list_customers(self, headers, params=None):
        return self._request("GET", "/shops/customers", headers=headers, params=params)

    def flat_get_motor(self, motor_id, headers):
        return self._request("GET", f"/shops/motors/{motor_id}", headers=headers)

    def flat_list_motors(self, headers, params=None):
        return self._request("GET", "/shops/motors", headers=headers, params=params)

    def flat_get_work_order(self, wo_id, headers):
        return self._request("GET", f"/shops/work-orders/{wo_id}", headers=headers)

    def flat_list_work_orders(self, headers, params=None):
        return self._request("GET", "/shops/work-orders", headers=headers, params=params)

    def flat_get_test_record(self, test_record_id, headers):
        return self._request("GET", f"/shops/test-records/{test_record_id}", headers=headers)

    def flat_list_test_records(self, headers, params=None):
        return self._request("GET", "/shops/test-records", headers=headers, params=params)

    def flat_get_quote(self, quote_id, headers):
        return self._request("GET", f"/shops/quotes/{quote_id}", headers=headers)

    def flat_list_quotes(self, headers, params=None):
        return self._request("GET", "/shops/quotes", headers=headers, params=params)

    def flat_get_coil_data_record(self, coil_data_record_id, headers):
        return self._request("GET", f"/shops/coil-data-records/{coil_data_record_id}", headers=headers)

    def flat_list_coil_data_records(self, headers, params=None):
        return self._request("GET", "/shops/coil-data-records", headers=headers, params=params)

    def flat_get_pool_contract(self, contract_id, headers):
        return self._request("GET", f"/shops/pool-contracts-flat/{contract_id}", headers=headers)

    def flat_list_pool_contracts(self, headers, params=None):
        return self._request("GET", "/shops/pool-contracts-flat", headers=headers, params=params)

    def flat_get_pool_loan(self, loan_id, headers):
        return self._request("GET", f"/shops/pool-loans/{loan_id}", headers=headers)

    def flat_list_pool_loans(self, headers, params=None):
        return self._request("GET", "/shops/pool-loans", headers=headers, params=params)

    def flat_get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/shops/invoices-flat/{invoice_id}", headers=headers)

    def flat_list_invoices(self, headers, params=None):
        return self._request("GET", "/shops/invoices-flat", headers=headers, params=params)

    def flat_get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/shops/warranty-claims-flat/{claim_id}", headers=headers)

    def flat_list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/shops/warranty-claims-flat", headers=headers, params=params)


api_client = ApiClient()
