"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- TradeAccount ----
    def create_trade_account(self, payload, headers):
        return self._request("POST", "/trade-accounts", payload, headers)

    def get_trade_account(self, account_id, headers):
        return self._request("GET", f"/trade-accounts/{account_id}", headers=headers)

    def patch_trade_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/trade-accounts/{account_id}", payload, headers)

    # ---- FixtureModel ----
    def create_fixture_model(self, payload, headers):
        return self._request("POST", "/fixture-models", payload, headers)

    def get_fixture_model(self, fixture_id, headers):
        return self._request("GET", f"/fixture-models/{fixture_id}", headers=headers)

    # ---- Config resources ----
    def create_installer(self, payload, headers):
        return self._request("POST", "/installers", payload, headers)

    def get_installer(self, installer_id, headers):
        return self._request("GET", f"/installers/{installer_id}", headers=headers)

    def create_delivery_truck(self, payload, headers):
        return self._request("POST", "/delivery-trucks", payload, headers)

    def create_rebate_program(self, payload, headers):
        return self._request("POST", "/rebate-programs", payload, headers)

    def get_rebate_program(self, program_id, headers):
        return self._request("GET", f"/rebate-programs/{program_id}", headers=headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def quote_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/quote", payload, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/payments", payload, headers)

    # ---- SpecialOrder ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def confirm_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/confirm", {}, headers)

    def complete_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/complete", {}, headers)

    # ---- DesignConsult ----
    def create_design_consult(self, payload, headers):
        return self._request("POST", "/design-consults", payload, headers)

    def get_design_consult(self, consult_id, headers):
        return self._request("GET", f"/design-consults/{consult_id}", headers=headers)

    def list_design_consults(self, headers, params=None):
        return self._request("GET", "/design-consults", headers=headers, params=params)

    def submit_review_design_consult(self, consult_id, headers):
        return self._request("POST", f"/design-consults/{consult_id}/submit-review", {}, headers)

    def request_revision_design_consult(self, consult_id, headers):
        return self._request("POST", f"/design-consults/{consult_id}/request-revision", {}, headers)

    def approve_design_consult(self, consult_id, headers):
        return self._request("POST", f"/design-consults/{consult_id}/approve", {}, headers)

    # ---- DeliveryJob ----
    def create_delivery_job(self, payload, headers):
        return self._request("POST", "/delivery-jobs", payload, headers)

    def get_delivery_job(self, job_id, headers):
        return self._request("GET", f"/delivery-jobs/{job_id}", headers=headers)

    def list_delivery_jobs(self, headers, params=None):
        return self._request("GET", "/delivery-jobs", headers=headers, params=params)

    def deliver_delivery_job(self, job_id, headers):
        return self._request("POST", f"/delivery-jobs/{job_id}/deliver", {}, headers)

    # ---- InstallReferral ----
    def create_install_referral(self, payload, headers):
        return self._request("POST", "/install-referrals", payload, headers)

    def get_install_referral(self, referral_id, headers):
        return self._request("GET", f"/install-referrals/{referral_id}", headers=headers)

    def list_install_referrals(self, headers, params=None):
        return self._request("GET", "/install-referrals", headers=headers, params=params)

    def schedule_install_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/install-referrals/{referral_id}/schedule", payload, headers)

    def complete_install_referral(self, referral_id, headers):
        return self._request("POST", f"/install-referrals/{referral_id}/complete", {}, headers)

    # ---- ReturnRequest ----
    def create_return_request(self, payload, headers):
        return self._request("POST", "/return-requests", payload, headers)

    def get_return_request(self, request_id, headers):
        return self._request("GET", f"/return-requests/{request_id}", headers=headers)

    def list_return_requests(self, headers, params=None):
        return self._request("GET", "/return-requests", headers=headers, params=params)

    def approve_return_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/return-requests/{request_id}/approve", payload or {}, headers)

    def refund_return_request(self, request_id, headers):
        return self._request("POST", f"/return-requests/{request_id}/refund", {}, headers)

    # ---- RebateClaim ----
    def create_rebate_claim(self, payload, headers):
        return self._request("POST", "/rebate-claims", payload, headers)

    def get_rebate_claim(self, claim_id, headers):
        return self._request("GET", f"/rebate-claims/{claim_id}", headers=headers)

    def list_rebate_claims(self, headers, params=None):
        return self._request("GET", "/rebate-claims", headers=headers, params=params)

    def approve_rebate_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/rebate-claims/{claim_id}/approve", payload or {}, headers)

    def void_rebate_claim(self, claim_id, headers):
        return self._request("POST", f"/rebate-claims/{claim_id}/void", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
