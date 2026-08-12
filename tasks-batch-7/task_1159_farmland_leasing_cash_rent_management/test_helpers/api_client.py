"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Landlords ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    def list_landlords(self, headers, params=None):
        return self._request("GET", "/landlords", headers=headers, params=params)

    # --- Tenants ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/tenants", headers=headers, params=params)

    def approve_tenant(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/approve", headers=headers)

    def suspend_tenant(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/suspend", headers=headers)

    # --- Fields ---
    def create_field(self, payload, headers):
        return self._request("POST", "/fields", payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/fields/{field_id}", headers=headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/fields", headers=headers, params=params)

    # --- Offerings ---
    def create_offering(self, payload, headers):
        return self._request("POST", "/offerings", payload, headers)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/offerings", headers=headers, params=params)

    def close_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/close", headers=headers)

    def award_offering(self, offering_id, payload, headers):
        return self._request("POST", f"/offerings/{offering_id}/award", payload, headers)

    def cancel_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/cancel", headers=headers)

    # --- Bids ---
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def revise_bid(self, bid_id, payload, headers):
        return self._request("PATCH", f"/bids/{bid_id}", payload, headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/withdraw", headers=headers)

    def shortlist_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/shortlist", headers=headers)

    def demote_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/demote", headers=headers)

    # --- Leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def amend_lease(self, lease_id, payload, headers):
        return self._request("PATCH", f"/leases/{lease_id}", payload, headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/activate", headers=headers)

    def cancel_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/cancel", headers=headers)

    # --- Installments ---
    def get_installment(self, installment_id, headers):
        return self._request("GET", f"/installments/{installment_id}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", "/installments", headers=headers, params=params)

    def record_payment(self, installment_id, payload, headers):
        return self._request(
            "POST", f"/installments/{installment_id}/record_payment", payload, headers
        )

    def reverse_payment(self, installment_id, headers):
        return self._request(
            "POST", f"/installments/{installment_id}/reverse_payment", headers=headers
        )

    def waive_installment(self, installment_id, payload, headers):
        return self._request(
            "POST", f"/installments/{installment_id}/waive", payload, headers
        )

    # --- Settlements ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/finalize", headers=headers
        )

    def countersign_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/countersign", headers=headers
        )

    def dispute_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/dispute", headers=headers
        )

    def refinalize_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/refinalize", payload, headers
        )

    # --- Expenses ---
    def create_expense(self, payload, headers):
        return self._request("POST", "/expenses", payload, headers)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/expenses/{expense_id}", headers=headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/expenses", headers=headers, params=params)

    def approve_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/approve", headers=headers)

    def reject_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/reject", headers=headers)

    # --- Compliance records ---
    def get_compliance_record(self, record_id, headers):
        return self._request(
            "GET", f"/compliance-records/{record_id}", headers=headers
        )

    def list_compliance_records(self, headers, params=None):
        return self._request("GET", "/compliance-records", headers=headers, params=params)

    def submit_evidence(self, record_id, payload, headers):
        return self._request(
            "POST", f"/compliance-records/{record_id}/submit_evidence", payload, headers
        )

    def verify_compliance_record(self, record_id, headers):
        return self._request(
            "POST", f"/compliance-records/{record_id}/verify", headers=headers
        )

    def reject_evidence(self, record_id, payload, headers):
        return self._request(
            "POST", f"/compliance-records/{record_id}/reject_evidence", payload, headers
        )

    def waive_compliance_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/compliance-records/{record_id}/waive", payload, headers
        )

    # --- Improvements ---
    def create_improvement(self, payload, headers):
        return self._request("POST", "/improvements", payload, headers)

    def get_improvement(self, improvement_id, headers):
        return self._request("GET", f"/improvements/{improvement_id}", headers=headers)

    def list_improvements(self, headers, params=None):
        return self._request("GET", "/improvements", headers=headers, params=params)

    def approve_improvement(self, improvement_id, headers):
        return self._request(
            "POST", f"/improvements/{improvement_id}/approve", headers=headers
        )

    def reject_improvement(self, improvement_id, headers):
        return self._request(
            "POST", f"/improvements/{improvement_id}/reject", headers=headers
        )

    def complete_improvement(self, improvement_id, headers):
        return self._request(
            "POST", f"/improvements/{improvement_id}/complete", headers=headers
        )

    def cancel_improvement(self, improvement_id, headers):
        return self._request(
            "POST", f"/improvements/{improvement_id}/cancel", headers=headers
        )

    def mark_reimbursed(self, improvement_id, headers):
        return self._request(
            "POST", f"/improvements/{improvement_id}/mark_reimbursed", headers=headers
        )

    # --- Termination notices ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/notices", headers=headers, params=params)

    def withdraw_notice(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/withdraw", headers=headers)

    # --- Owner reports ---
    def create_report(self, payload, headers):
        return self._request("POST", "/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def send_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/send", headers=headers)

    def acknowledge_report(self, report_id, headers):
        return self._request(
            "POST", f"/reports/{report_id}/acknowledge", headers=headers
        )


api_client = ApiClient()
