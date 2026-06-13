"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
envelope, headers, and HTTP plumbing. Every method below maps one row of the
PRD endpoint table to a Python call.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Market ----------
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    # ---------- Vendor ----------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    # ---------- Permit ----------
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def verify_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/verify", payload, headers)

    # ---------- Application ----------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def start_review_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/start-review", {}, headers)

    def approve_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/approve", payload, headers)

    def reject_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/reject", payload, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/resubmit", {}, headers)

    # ---------- Booth ----------
    def create_booth(self, payload, headers):
        return self._request("POST", "/booths", payload, headers)

    def get_booth(self, booth_id, headers):
        return self._request("GET", f"/booths/{booth_id}", headers=headers)

    def list_booths(self, headers, params=None):
        return self._request("GET", "/booths", headers=headers, params=params)

    def set_service_booth(self, booth_id, payload, headers):
        return self._request("POST", f"/booths/{booth_id}/set-service", payload, headers)

    # ---------- MarketDay ----------
    def create_market_day(self, payload, headers):
        return self._request("POST", "/market-days", payload, headers)

    def get_market_day(self, market_day_id, headers):
        return self._request("GET", f"/market-days/{market_day_id}", headers=headers)

    def list_market_days(self, headers, params=None):
        return self._request("GET", "/market-days", headers=headers, params=params)

    def open_market_day(self, market_day_id, headers):
        return self._request("POST", f"/market-days/{market_day_id}/open", {}, headers)

    def close_market_day(self, market_day_id, headers):
        return self._request("POST", f"/market-days/{market_day_id}/close", {}, headers)

    def cancel_market_day(self, market_day_id, payload, headers):
        return self._request("POST", f"/market-days/{market_day_id}/cancel", payload, headers)

    # ---------- BoothAssignment ----------
    def create_booth_assignment(self, payload, headers):
        return self._request("POST", "/booth-assignments", payload, headers)

    def get_booth_assignment(self, assignment_id, headers):
        return self._request("GET", f"/booth-assignments/{assignment_id}", headers=headers)

    def list_booth_assignments(self, headers, params=None):
        return self._request("GET", "/booth-assignments", headers=headers, params=params)

    def activate_booth_assignment(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/activate", {}, headers)

    def complete_booth_assignment(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/complete", {}, headers)

    def cancel_booth_assignment(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/cancel", {}, headers)

    def promote_booth_assignment(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/promote", {}, headers)

    # ---------- CheckIn ----------
    def create_check_in(self, payload, headers):
        return self._request("POST", "/check-ins", payload, headers)

    def get_check_in(self, check_in_id, headers):
        return self._request("GET", f"/check-ins/{check_in_id}", headers=headers)

    def list_check_ins(self, headers, params=None):
        return self._request("GET", "/check-ins", headers=headers, params=params)

    def arrive_check_in(self, check_in_id, headers):
        return self._request("POST", f"/check-ins/{check_in_id}/arrive", {}, headers)

    # ---------- SalesReport ----------
    def create_sales_report(self, payload, headers):
        return self._request("POST", "/sales-reports", payload, headers)

    def get_sales_report(self, sales_report_id, headers):
        return self._request("GET", f"/sales-reports/{sales_report_id}", headers=headers)

    def list_sales_reports(self, headers, params=None):
        return self._request("GET", "/sales-reports", headers=headers, params=params)

    def submit_sales_report(self, sales_report_id, payload, headers):
        return self._request("POST", f"/sales-reports/{sales_report_id}/submit", payload, headers)

    def dispute_sales_report(self, sales_report_id, headers):
        return self._request("POST", f"/sales-reports/{sales_report_id}/dispute", {}, headers)

    def reconcile_sales_report(self, sales_report_id, headers):
        return self._request("POST", f"/sales-reports/{sales_report_id}/reconcile", {}, headers)

    # ---------- VoucherBatch ----------
    def create_voucher_batch(self, payload, headers):
        return self._request("POST", "/voucher-batches", payload, headers)

    def get_voucher_batch(self, voucher_batch_id, headers):
        return self._request("GET", f"/voucher-batches/{voucher_batch_id}", headers=headers)

    def list_voucher_batches(self, headers, params=None):
        return self._request("GET", "/voucher-batches", headers=headers, params=params)

    # ---------- VoucherRedemption ----------
    def create_voucher_redemption(self, payload, headers):
        return self._request("POST", "/voucher-redemptions", payload, headers)

    def get_voucher_redemption(self, redemption_id, headers):
        return self._request("GET", f"/voucher-redemptions/{redemption_id}", headers=headers)

    def list_voucher_redemptions(self, headers, params=None):
        return self._request("GET", "/voucher-redemptions", headers=headers, params=params)

    def reconcile_voucher_redemption(self, redemption_id, headers):
        return self._request("POST", f"/voucher-redemptions/{redemption_id}/reconcile", {}, headers)

    # ---------- Test-driving clock ----------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
