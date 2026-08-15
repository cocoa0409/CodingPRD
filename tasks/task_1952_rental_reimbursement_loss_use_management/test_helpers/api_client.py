"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- policyholders ---
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/policyholders", payload, headers)

    def get_policyholder(self, policyholder_id, headers):
        return self._request("GET", f"/policyholders/{policyholder_id}", headers=headers)

    def list_policyholder_claims(self, policyholder_id, headers, params=None):
        return self._request("GET", f"/policyholders/{policyholder_id}/claims",
                             headers=headers, params=params)

    # --- repair shops ---
    def create_repair_shop(self, payload, headers):
        return self._request("POST", "/repair-shops", payload, headers)

    def get_repair_shop(self, shop_id, headers):
        return self._request("GET", f"/repair-shops/{shop_id}", headers=headers)

    # --- rental partners ---
    def create_rental_partner(self, payload, headers):
        return self._request("POST", "/rental-partners", payload, headers)

    def get_rental_partner(self, partner_id, headers):
        return self._request("GET", f"/rental-partners/{partner_id}", headers=headers)

    def suspend_rental_partner(self, partner_id, headers):
        return self._request("POST", f"/rental-partners/{partner_id}/suspend", {}, headers)

    def reactivate_rental_partner(self, partner_id, headers):
        return self._request("POST", f"/rental-partners/{partner_id}/reactivate", {}, headers)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/settle", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    def list_claim_coverage_verifications(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/coverage-verifications",
                             headers=headers, params=params)

    def list_claim_repair_orders(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/repair-orders",
                             headers=headers, params=params)

    def list_claim_rental_reservations(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/rental-reservations",
                             headers=headers, params=params)

    def list_claim_loss_of_use_claims(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/loss-of-use-claims",
                             headers=headers, params=params)

    def list_claim_recovery_cases(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/recovery-cases",
                             headers=headers, params=params)

    def list_claim_communication_logs(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/communication-logs",
                             headers=headers, params=params)

    # --- coverage verifications ---
    def create_coverage_verification(self, payload, headers):
        return self._request("POST", "/coverage-verifications", payload, headers)

    def decide_coverage_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/coverage-verifications/{verification_id}/decide",
                             payload, headers)

    # --- repair orders / milestones ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def approve_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/approve", {}, headers)

    def start_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/start", {}, headers)

    def complete_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/complete", {}, headers)

    def create_milestone(self, repair_order_id, payload, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/milestones",
                             payload, headers)

    def list_milestones(self, repair_order_id, headers, params=None):
        return self._request("GET", f"/repair-orders/{repair_order_id}/milestones",
                             headers=headers, params=params)

    # --- rental reservations ---
    def create_rental_reservation(self, payload, headers):
        return self._request("POST", "/rental-reservations", payload, headers)

    def list_rental_reservations(self, headers, params=None):
        return self._request("GET", "/rental-reservations", headers=headers, params=params)

    def get_rental_reservation(self, reservation_id, headers):
        return self._request("GET", f"/rental-reservations/{reservation_id}", headers=headers)

    def authorize_rental_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{reservation_id}/authorize",
                             {}, headers)

    def activate_rental_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{reservation_id}/activate",
                             {}, headers)

    def return_rental_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{reservation_id}/return",
                             {}, headers)

    def close_rental_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{reservation_id}/close",
                             {}, headers)

    def cancel_rental_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{reservation_id}/cancel",
                             {}, headers)

    def list_reservation_extension_requests(self, reservation_id, headers, params=None):
        return self._request("GET", f"/rental-reservations/{reservation_id}/extension-requests",
                             headers=headers, params=params)

    def list_reservation_class_changes(self, reservation_id, headers, params=None):
        return self._request("GET", f"/rental-reservations/{reservation_id}/class-changes",
                             headers=headers, params=params)

    def list_reservation_invoices(self, reservation_id, headers, params=None):
        return self._request("GET", f"/rental-reservations/{reservation_id}/invoices",
                             headers=headers, params=params)

    # --- extension requests ---
    def create_extension_request(self, payload, headers):
        return self._request("POST", "/extension-requests", payload, headers)

    def list_extension_requests(self, headers, params=None):
        return self._request("GET", "/extension-requests", headers=headers, params=params)

    def get_extension_request(self, extension_request_id, headers):
        return self._request("GET", f"/extension-requests/{extension_request_id}",
                             headers=headers)

    def approve_extension_request(self, extension_request_id, headers):
        return self._request("POST", f"/extension-requests/{extension_request_id}/approve",
                             {}, headers)

    def deny_extension_request(self, extension_request_id, payload, headers):
        return self._request("POST", f"/extension-requests/{extension_request_id}/deny",
                             payload, headers)

    # --- class changes ---
    def create_class_change(self, payload, headers):
        return self._request("POST", "/class-changes", payload, headers)

    # --- loss-of-use claims ---
    def create_loss_of_use_claim(self, payload, headers):
        return self._request("POST", "/loss-of-use-claims", payload, headers)

    def get_loss_of_use_claim(self, lou_id, headers):
        return self._request("GET", f"/loss-of-use-claims/{lou_id}", headers=headers)

    def attach_lou_documentation(self, lou_id, headers):
        return self._request("POST", f"/loss-of-use-claims/{lou_id}/attach-documentation",
                             {}, headers)

    def approve_loss_of_use_claim(self, lou_id, headers):
        return self._request("POST", f"/loss-of-use-claims/{lou_id}/approve", {}, headers)

    def deny_loss_of_use_claim(self, lou_id, payload, headers):
        return self._request("POST", f"/loss-of-use-claims/{lou_id}/deny", payload, headers)

    def pay_loss_of_use_claim(self, lou_id, headers):
        return self._request("POST", f"/loss-of-use-claims/{lou_id}/pay", {}, headers)

    # --- invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def decide_invoice_audit(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/audit-decision",
                             payload, headers)

    def settle_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/settle", {}, headers)

    # --- recovery cases ---
    def list_recovery_cases(self, headers, params=None):
        return self._request("GET", "/recovery-cases", headers=headers, params=params)

    def get_recovery_case(self, recovery_case_id, headers):
        return self._request("GET", f"/recovery-cases/{recovery_case_id}", headers=headers)

    def record_recovery_payment(self, recovery_case_id, payload, headers):
        return self._request("POST", f"/recovery-cases/{recovery_case_id}/record-payment",
                             payload, headers)

    def waive_recovery_case(self, recovery_case_id, headers):
        return self._request("POST", f"/recovery-cases/{recovery_case_id}/waive", {}, headers)

    # --- communication logs ---
    def create_communication_log(self, payload, headers):
        return self._request("POST", "/communication-logs", payload, headers)


api_client = ApiClient()
