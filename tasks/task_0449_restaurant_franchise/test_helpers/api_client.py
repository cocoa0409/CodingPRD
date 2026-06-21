"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions).

Subclasses GenericApiClient; the base _request(method, path, payload, headers, params)
is inherited. The system is a flat topology — entities are peer top-level collections
under /franchise, linked by foreign keys carried in request bodies.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Brand & clock -----------------------------------------------------
    def create_brand(self, payload, headers):
        return self._request("POST", "/franchise/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/franchise/brands/{brand_id}", headers=headers)

    def close_period(self, brand_id, headers):
        return self._request(
            "POST", f"/franchise/brands/{brand_id}/close-period", {}, headers
        )

    def set_clock(self, brand_id, to_iso8601, headers):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"brand_id": brand_id, "to_iso8601": to_iso8601},
            headers,
        )

    # ---- Territory ---------------------------------------------------------
    def create_territory(self, payload, headers):
        return self._request("POST", "/franchise/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request(
            "GET", f"/franchise/territories/{territory_id}", headers=headers
        )

    def list_territories(self, headers, params=None):
        return self._request(
            "GET", "/franchise/territories", headers=headers, params=params
        )

    def assign_territory(self, territory_id, payload, headers):
        return self._request(
            "POST", f"/franchise/territories/{territory_id}/assign", payload, headers
        )

    # ---- Franchisee --------------------------------------------------------
    def create_franchisee(self, payload, headers):
        return self._request("POST", "/franchise/franchisees", payload, headers)

    def get_franchisee(self, franchisee_id, headers):
        return self._request(
            "GET", f"/franchise/franchisees/{franchisee_id}", headers=headers
        )

    def list_franchisees(self, headers, params=None):
        return self._request(
            "GET", "/franchise/franchisees", headers=headers, params=params
        )

    def approve_franchisee(self, franchisee_id, headers):
        return self._request(
            "POST", f"/franchise/franchisees/{franchisee_id}/approve", {}, headers
        )

    def terminate_franchisee(self, franchisee_id, headers):
        return self._request(
            "POST", f"/franchise/franchisees/{franchisee_id}/terminate", {}, headers
        )

    # ---- FranchiseAgreement ------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/franchise/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/franchise/agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/franchise/agreements", headers=headers, params=params
        )

    def execute_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/execute", {}, headers
        )

    def begin_renewal(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/begin-renewal", {}, headers
        )

    def renew_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/renew", payload, headers
        )

    def transfer_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/transfer", payload, headers
        )

    def decline_renewal(self, agreement_id, headers):
        return self._request(
            "POST",
            f"/franchise/agreements/{agreement_id}/decline-renewal",
            {},
            headers,
        )

    # ---- DevelopmentSchedule -----------------------------------------------
    def create_development_schedule(self, payload, headers):
        return self._request(
            "POST", "/franchise/development-schedules", payload, headers
        )

    def get_development_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/franchise/development-schedules/{schedule_id}", headers=headers
        )

    def list_development_schedules(self, headers, params=None):
        return self._request(
            "GET", "/franchise/development-schedules", headers=headers, params=params
        )

    def declare_breach(self, schedule_id, headers):
        return self._request(
            "POST",
            f"/franchise/development-schedules/{schedule_id}/declare-breach",
            {},
            headers,
        )

    # ---- Unit --------------------------------------------------------------
    def create_unit(self, payload, headers):
        return self._request("POST", "/franchise/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/franchise/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/franchise/units", headers=headers, params=params)

    def open_unit(self, unit_id, headers):
        return self._request("POST", f"/franchise/units/{unit_id}/open", {}, headers)

    def close_unit(self, unit_id, headers):
        return self._request("POST", f"/franchise/units/{unit_id}/close", {}, headers)

    def reinstate_unit(self, unit_id, headers):
        return self._request(
            "POST", f"/franchise/units/{unit_id}/reinstate", {}, headers
        )

    # ---- SalesReport -------------------------------------------------------
    def create_sales_report(self, payload, headers):
        return self._request("POST", "/franchise/sales-reports", payload, headers)

    def accept_sales_report(self, sales_report_id, headers):
        return self._request(
            "POST", f"/franchise/sales-reports/{sales_report_id}/accept", {}, headers
        )

    def get_sales_report(self, sales_report_id, headers):
        return self._request(
            "GET", f"/franchise/sales-reports/{sales_report_id}", headers=headers
        )

    def list_sales_reports(self, headers, params=None):
        return self._request(
            "GET", "/franchise/sales-reports", headers=headers, params=params
        )

    # ---- RoyaltyStatement --------------------------------------------------
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/franchise/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/franchise/royalty-statements/{statement_id}", headers=headers
        )

    def list_royalty_statements(self, headers, params=None):
        return self._request(
            "GET", "/franchise/royalty-statements", headers=headers, params=params
        )

    def issue_royalty_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/franchise/royalty-statements/{statement_id}/issue", {}, headers
        )

    def pay_royalty_statement(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"/franchise/royalty-statements/{statement_id}/payments",
            payload,
            headers,
        )

    def write_off_royalty_statement(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"/franchise/royalty-statements/{statement_id}/write-off",
            payload,
            headers,
        )

    # ---- Vendor ------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/franchise/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/franchise/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request(
            "GET", "/franchise/vendors", headers=headers, params=params
        )

    def approve_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/franchise/vendors/{vendor_id}/approve", {}, headers
        )

    def revoke_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/franchise/vendors/{vendor_id}/revoke", {}, headers
        )

    # ---- VendorAuthorization -----------------------------------------------
    def create_vendor_authorization(self, payload, headers):
        return self._request(
            "POST", "/franchise/vendor-authorizations", payload, headers
        )

    def get_vendor_authorization(self, authorization_id, headers):
        return self._request(
            "GET",
            f"/franchise/vendor-authorizations/{authorization_id}",
            headers=headers,
        )

    def list_vendor_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/franchise/vendor-authorizations", headers=headers, params=params
        )

    # ---- BrandAudit --------------------------------------------------------
    def create_audit(self, payload, headers):
        return self._request("POST", "/franchise/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/franchise/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/franchise/audits", headers=headers, params=params)

    def start_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/franchise/audits/{audit_id}/start", {}, headers
        )

    def finalize_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/franchise/audits/{audit_id}/finalize", payload, headers
        )

    def open_remediation(self, audit_id, headers):
        return self._request(
            "POST", f"/franchise/audits/{audit_id}/open-remediation", {}, headers
        )

    def close_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/franchise/audits/{audit_id}/close", {}, headers
        )

    # ---- NationalAccount ---------------------------------------------------
    def create_national_account(self, payload, headers):
        return self._request("POST", "/franchise/national-accounts", payload, headers)

    def get_national_account(self, account_id, headers):
        return self._request(
            "GET", f"/franchise/national-accounts/{account_id}", headers=headers
        )

    def list_national_accounts(self, headers, params=None):
        return self._request(
            "GET", "/franchise/national-accounts", headers=headers, params=params
        )

    def distribute_national_account(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"/franchise/national-accounts/{account_id}/distribute",
            payload,
            headers,
        )


api_client = ApiClient()
