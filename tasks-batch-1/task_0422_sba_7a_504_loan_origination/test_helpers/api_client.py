"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Lender ---
    def create_lender(self, payload, headers):
        return self._request("POST", "/sba/lenders", payload, headers)

    def get_lender(self, lender_id, headers):
        return self._request("GET", f"/sba/lenders/{lender_id}", headers=headers)

    def list_lender_borrowers(self, lender_id, headers, params=None):
        return self._request("GET", f"/sba/lenders/{lender_id}/borrowers", headers=headers, params=params)

    def list_lender_guaranty_sales(self, lender_id, headers, params=None):
        return self._request("GET", f"/sba/lenders/{lender_id}/guaranty-sales", headers=headers, params=params)

    # --- Borrower ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/sba/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/sba/borrowers/{borrower_id}", headers=headers)

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/sba/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/sba/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/sba/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/submit", {}, headers)

    def request_revision(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/request-revision", {}, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/resubmit", {}, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/approve", {}, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/decline", {}, headers)

    def authorize_application(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/authorize", {}, headers)

    def close_application(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/close", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/withdraw", {}, headers)

    def declare_default(self, application_id, headers):
        return self._request("POST", f"/sba/applications/{application_id}/declare-default", {}, headers)

    # --- ProceedsLineItem ---
    def create_proceeds(self, payload, headers):
        return self._request("POST", "/sba/proceeds", payload, headers)

    def list_proceeds(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/proceeds", headers=headers, params=params)

    # --- CollateralItem ---
    def create_collateral(self, payload, headers):
        return self._request("POST", "/sba/collateral", payload, headers)

    def list_collateral(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/collateral", headers=headers, params=params)

    # --- FormPackage ---
    def create_form_package(self, payload, headers):
        return self._request("POST", "/sba/form-packages", payload, headers)

    def list_form_packages(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/form-packages", headers=headers, params=params)

    def submit_form_package(self, form_package_id, headers):
        return self._request("POST", f"/sba/form-packages/{form_package_id}/submit", {}, headers)

    def review_form_package(self, form_package_id, headers):
        return self._request("POST", f"/sba/form-packages/{form_package_id}/review", {}, headers)

    def reopen_form_package(self, form_package_id, headers, payload=None):
        return self._request("POST", f"/sba/form-packages/{form_package_id}/reopen", payload or {}, headers)

    # --- CreditMemo ---
    def create_credit_memo(self, payload, headers):
        return self._request("POST", "/sba/credit-memos", payload, headers)

    def list_credit_memos(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/credit-memos", headers=headers, params=params)

    def submit_credit_memo(self, credit_memo_id, headers):
        return self._request("POST", f"/sba/credit-memos/{credit_memo_id}/submit", {}, headers)

    # --- Disbursement ---
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/sba/disbursements", payload, headers)

    def list_disbursements(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/disbursements", headers=headers, params=params)

    def post_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/sba/disbursements/{disbursement_id}/post", {}, headers)

    def reverse_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/sba/disbursements/{disbursement_id}/reverse", {}, headers)

    # --- GuarantySale ---
    def create_guaranty_sale(self, payload, headers):
        return self._request("POST", "/sba/guaranty-sales", payload, headers)

    def list_application_guaranty_sales(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/guaranty-sales", headers=headers, params=params)

    def settle_guaranty_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sba/guaranty-sales/{sale_id}/settle", payload, headers)

    def repurchase_guaranty_sale(self, sale_id, headers):
        return self._request("POST", f"/sba/guaranty-sales/{sale_id}/repurchase", {}, headers)

    # --- ServicingReport ---
    def create_servicing_report(self, payload, headers):
        return self._request("POST", "/sba/servicing-reports", payload, headers)

    def list_servicing_reports(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/servicing-reports", headers=headers, params=params)

    def accept_servicing_report(self, report_id, headers):
        return self._request("POST", f"/sba/servicing-reports/{report_id}/accept", {}, headers)

    def reject_servicing_report(self, report_id, headers):
        return self._request("POST", f"/sba/servicing-reports/{report_id}/reject", {}, headers)

    # --- LiquidationEvent ---
    def create_liquidation(self, payload, headers):
        return self._request("POST", "/sba/liquidations", payload, headers)

    def list_liquidations(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/liquidations", headers=headers, params=params)

    def settle_liquidation(self, liquidation_id, headers):
        return self._request("POST", f"/sba/liquidations/{liquidation_id}/settle", {}, headers)

    # --- GuarantyPurchase ---
    def create_guaranty_purchase(self, payload, headers):
        return self._request("POST", "/sba/guaranty-purchases", payload, headers)

    def list_guaranty_purchases(self, application_id, headers, params=None):
        return self._request("GET", f"/sba/applications/{application_id}/guaranty-purchases", headers=headers, params=params)

    def pay_guaranty_purchase(self, purchase_id, headers):
        return self._request("POST", f"/sba/guaranty-purchases/{purchase_id}/pay", {}, headers)

    def deny_guaranty_purchase(self, purchase_id, headers):
        return self._request("POST", f"/sba/guaranty-purchases/{purchase_id}/deny", {}, headers)


api_client = ApiClient()
