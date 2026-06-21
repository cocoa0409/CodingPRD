"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Owner ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def fund_trust(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/trust-deposits", payload, headers
        )

    # ---- Unit ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # ---- Applicant ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    def screen_applicant(self, applicant_id, headers):
        return self._request(
            "POST", f"/applicants/{applicant_id}/screen", {}, headers
        )

    def decide_applicant(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"/applicants/{applicant_id}/decide", payload, headers
        )

    def withdraw_applicant(self, applicant_id, headers):
        return self._request(
            "POST", f"/applicants/{applicant_id}/withdraw", {}, headers
        )

    # ---- Lease ----
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def sign_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/sign", {}, headers)

    def offer_renewal(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/offer-renewal", payload, headers
        )

    def expire_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/expire", payload, headers)

    def assess_late_fees(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/assess-late-fees", payload, headers
        )

    # ---- RentCharge ----
    def create_rent_charge(self, payload, headers):
        return self._request("POST", "/rent-charges", payload, headers)

    def get_rent_charge(self, charge_id, headers):
        return self._request("GET", f"/rent-charges/{charge_id}", headers=headers)

    def list_rent_charges(self, headers, params=None):
        return self._request("GET", "/rent-charges", headers=headers, params=params)

    def waive_rent_charge(self, charge_id, headers):
        return self._request("POST", f"/rent-charges/{charge_id}/waive", {}, headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ---- SecurityDeposit ----
    def create_security_deposit(self, payload, headers):
        return self._request("POST", "/security-deposits", payload, headers)

    def get_security_deposit(self, deposit_id, headers):
        return self._request(
            "GET", f"/security-deposits/{deposit_id}", headers=headers
        )

    def list_security_deposits(self, headers, params=None):
        return self._request(
            "GET", "/security-deposits", headers=headers, params=params
        )

    def settle_security_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"/security-deposits/{deposit_id}/settle", payload, headers
        )

    # ---- WorkOrder ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def assign_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/assign", {}, headers
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/complete", payload, headers
        )

    def cancel_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/cancel", {}, headers
        )

    # ---- EvictionCase ----
    def create_eviction(self, payload, headers):
        return self._request("POST", "/evictions", payload, headers)

    def get_eviction(self, eviction_id, headers):
        return self._request("GET", f"/evictions/{eviction_id}", headers=headers)

    def list_evictions(self, headers, params=None):
        return self._request("GET", "/evictions", headers=headers, params=params)

    def cure_eviction(self, eviction_id, payload, headers):
        return self._request(
            "POST", f"/evictions/{eviction_id}/cure", payload, headers
        )

    def file_eviction(self, eviction_id, payload, headers):
        return self._request(
            "POST", f"/evictions/{eviction_id}/file", payload, headers
        )

    def enforce_eviction(self, eviction_id, headers):
        return self._request(
            "POST", f"/evictions/{eviction_id}/enforce", {}, headers
        )

    def dismiss_eviction(self, eviction_id, headers):
        return self._request(
            "POST", f"/evictions/{eviction_id}/dismiss", {}, headers
        )

    # ---- OwnerStatement ----
    def create_owner_statement(self, payload, headers):
        return self._request("POST", "/owner-statements", payload, headers)

    def get_owner_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/owner-statements/{statement_id}", headers=headers
        )

    def list_owner_statements(self, headers, params=None):
        return self._request(
            "GET", "/owner-statements", headers=headers, params=params
        )

    def finalize_owner_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/owner-statements/{statement_id}/finalize", {}, headers
        )

    def distribute_owner_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/owner-statements/{statement_id}/distribute", payload, headers
        )

    # ---- TurnoverProject ----
    def create_turnover(self, payload, headers):
        return self._request("POST", "/turnovers", payload, headers)

    def get_turnover(self, turnover_id, headers):
        return self._request("GET", f"/turnovers/{turnover_id}", headers=headers)

    def list_turnovers(self, headers, params=None):
        return self._request("GET", "/turnovers", headers=headers, params=params)

    def start_turnover(self, turnover_id, headers):
        return self._request("POST", f"/turnovers/{turnover_id}/start", {}, headers)

    def complete_turnover(self, turnover_id, headers):
        return self._request(
            "POST", f"/turnovers/{turnover_id}/complete", {}, headers
        )

    # ---- Tenant ----
    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/tenants", headers=headers, params=params)


api_client = ApiClient()
