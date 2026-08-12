"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Principals ---
    def create_principal(self, payload, headers):
        return self._request("POST", "/principals", payload, headers)

    def list_principals(self, headers, params=None):
        return self._request("GET", "/principals", headers=headers, params=params)

    def get_principal(self, principal_id, headers):
        return self._request("GET", f"/principals/{principal_id}", headers=headers)

    def suspend_principal(self, principal_id, headers):
        return self._request("POST", f"/principals/{principal_id}/suspend", headers=headers)

    def reinstate_principal(self, principal_id, headers):
        return self._request("POST", f"/principals/{principal_id}/reinstate", headers=headers)

    def get_principal_exposure(self, principal_id, headers):
        return self._request("GET", f"/principals/{principal_id}/exposure", headers=headers)

    # --- Port calls ---
    def create_port_call(self, payload, headers):
        return self._request("POST", "/port-calls", payload, headers)

    def list_port_calls(self, headers, params=None):
        return self._request("GET", "/port-calls", headers=headers, params=params)

    def get_port_call(self, port_call_id, headers):
        return self._request("GET", f"/port-calls/{port_call_id}", headers=headers)

    def patch_port_call(self, port_call_id, payload, headers):
        return self._request("PATCH", f"/port-calls/{port_call_id}", payload, headers)

    def file_pre_arrival(self, port_call_id, headers):
        return self._request("POST", f"/port-calls/{port_call_id}/file-pre-arrival", headers=headers)

    def grant_clearance(self, port_call_id, headers):
        return self._request("POST", f"/port-calls/{port_call_id}/grant-clearance", headers=headers)

    def record_arrival(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-calls/{port_call_id}/record-arrival", payload, headers)

    def record_sailing(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-calls/{port_call_id}/record-sailing", payload, headers)

    def close_port_call(self, port_call_id, headers):
        return self._request("POST", f"/port-calls/{port_call_id}/close", headers=headers)

    def cancel_port_call(self, port_call_id, headers):
        return self._request("POST", f"/port-calls/{port_call_id}/cancel", headers=headers)

    # --- Authority notifications ---
    def create_authority_notification(self, payload, headers):
        return self._request("POST", "/authority-notifications", payload, headers)

    def list_authority_notifications(self, headers, params=None):
        return self._request("GET", "/authority-notifications", headers=headers, params=params)

    def get_authority_notification(self, notification_id, headers):
        return self._request("GET", f"/authority-notifications/{notification_id}", headers=headers)

    def submit_notification(self, notification_id, headers):
        return self._request("POST", f"/authority-notifications/{notification_id}/submit", headers=headers)

    def acknowledge_notification(self, notification_id, payload, headers):
        return self._request("POST", f"/authority-notifications/{notification_id}/acknowledge", payload, headers)

    def reject_notification(self, notification_id, payload, headers):
        return self._request("POST", f"/authority-notifications/{notification_id}/reject", payload, headers)

    def resubmit_notification(self, notification_id, headers):
        return self._request("POST", f"/authority-notifications/{notification_id}/resubmit", headers=headers)

    # --- Berth windows ---
    def create_berth_window(self, payload, headers):
        return self._request("POST", "/berth-windows", payload, headers)

    def list_berth_windows(self, headers, params=None):
        return self._request("GET", "/berth-windows", headers=headers, params=params)

    def get_berth_window(self, window_id, headers):
        return self._request("GET", f"/berth-windows/{window_id}", headers=headers)

    def confirm_berth_window(self, window_id, headers):
        return self._request("POST", f"/berth-windows/{window_id}/confirm", headers=headers)

    def occupy_berth_window(self, window_id, headers):
        return self._request("POST", f"/berth-windows/{window_id}/occupy", headers=headers)

    def release_berth_window(self, window_id, headers):
        return self._request("POST", f"/berth-windows/{window_id}/release", headers=headers)

    def cancel_berth_window(self, window_id, headers):
        return self._request("POST", f"/berth-windows/{window_id}/cancel", headers=headers)

    # --- Service orders ---
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def confirm_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/confirm", headers=headers)

    def start_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/start", headers=headers)

    def complete_service_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/complete", payload, headers)

    def cancel_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/cancel", headers=headers)

    # --- Crew changes ---
    def create_crew_change(self, payload, headers):
        return self._request("POST", "/crew-changes", payload, headers)

    def list_crew_changes(self, headers, params=None):
        return self._request("GET", "/crew-changes", headers=headers, params=params)

    def get_crew_change(self, crew_change_id, headers):
        return self._request("GET", f"/crew-changes/{crew_change_id}", headers=headers)

    def verify_docs(self, crew_change_id, headers):
        return self._request("POST", f"/crew-changes/{crew_change_id}/verify-docs", headers=headers)

    def request_visa(self, crew_change_id, headers):
        return self._request("POST", f"/crew-changes/{crew_change_id}/request-visa", headers=headers)

    def grant_visa(self, crew_change_id, payload, headers):
        return self._request("POST", f"/crew-changes/{crew_change_id}/grant-visa", payload, headers)

    def issue_shore_pass(self, crew_change_id, payload, headers):
        return self._request("POST", f"/crew-changes/{crew_change_id}/issue-shore-pass", payload, headers)

    def complete_crew_change(self, crew_change_id, headers):
        return self._request("POST", f"/crew-changes/{crew_change_id}/complete", headers=headers)

    def cancel_crew_change(self, crew_change_id, headers):
        return self._request("POST", f"/crew-changes/{crew_change_id}/cancel", headers=headers)

    # --- Vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", headers=headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reinstate", headers=headers)

    # --- Purchase orders ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, order_id, headers):
        return self._request("GET", f"/purchase-orders/{order_id}", headers=headers)

    def send_purchase_order(self, order_id, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/send", headers=headers)

    def acknowledge_purchase_order(self, order_id, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/acknowledge", headers=headers)

    def deliver_purchase_order(self, order_id, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/deliver", headers=headers)

    def invoice_purchase_order(self, order_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/invoice", payload, headers)

    def reinvoice_purchase_order(self, order_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/reinvoice", payload, headers)

    def match_purchase_order(self, order_id, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/match", headers=headers)

    def cancel_purchase_order(self, order_id, headers):
        return self._request("POST", f"/purchase-orders/{order_id}/cancel", headers=headers)

    # --- Cargo documents ---
    def create_cargo_document(self, payload, headers):
        return self._request("POST", "/cargo-documents", payload, headers)

    def list_cargo_documents(self, headers, params=None):
        return self._request("GET", "/cargo-documents", headers=headers, params=params)

    def get_cargo_document(self, doc_id, headers):
        return self._request("GET", f"/cargo-documents/{doc_id}", headers=headers)

    def verify_cargo_document(self, doc_id, headers):
        return self._request("POST", f"/cargo-documents/{doc_id}/verify", headers=headers)

    def hold_cargo_document(self, doc_id, headers):
        return self._request("POST", f"/cargo-documents/{doc_id}/hold", headers=headers)

    def release_hold_cargo_document(self, doc_id, headers):
        return self._request("POST", f"/cargo-documents/{doc_id}/release-hold", headers=headers)

    def release_cargo_document(self, doc_id, headers):
        return self._request("POST", f"/cargo-documents/{doc_id}/release", headers=headers)

    # --- Tariffs ---
    def create_tariff(self, payload, headers):
        return self._request("POST", "/tariffs", payload, headers)

    def list_tariffs(self, headers, params=None):
        return self._request("GET", "/tariffs", headers=headers, params=params)

    def get_tariff(self, tariff_id, headers):
        return self._request("GET", f"/tariffs/{tariff_id}", headers=headers)

    def list_tariff_da_lines(self, tariff_id, headers, params=None):
        return self._request("GET", f"/tariffs/{tariff_id}/da-lines", headers=headers, params=params)

    # --- Disbursement accounts / lines ---
    def create_disbursement_account(self, payload, headers):
        return self._request("POST", "/disbursement-accounts", payload, headers)

    def list_disbursement_accounts(self, headers, params=None):
        return self._request("GET", "/disbursement-accounts", headers=headers, params=params)

    def get_disbursement_account(self, da_id, headers):
        return self._request("GET", f"/disbursement-accounts/{da_id}", headers=headers)

    def send_disbursement_account(self, da_id, headers):
        return self._request("POST", f"/disbursement-accounts/{da_id}/send", headers=headers)

    def list_da_lines(self, da_id, headers, params=None):
        return self._request("GET", f"/disbursement-accounts/{da_id}/lines", headers=headers, params=params)

    def create_da_line(self, da_id, payload, headers):
        return self._request("POST", f"/disbursement-accounts/{da_id}/lines", payload, headers)

    def finalize_disbursement_account(self, da_id, headers):
        return self._request("POST", f"/disbursement-accounts/{da_id}/finalize", headers=headers)

    def refinalize_disbursement_account(self, da_id, headers):
        return self._request("POST", f"/disbursement-accounts/{da_id}/refinalize", headers=headers)

    def settle_disbursement_account(self, da_id, headers):
        return self._request("POST", f"/disbursement-accounts/{da_id}/settle", headers=headers)

    def create_funding_advance(self, da_id, payload, headers):
        return self._request("POST", f"/disbursement-accounts/{da_id}/advances", payload, headers)

    # --- Funding advances ---
    def list_funding_advances(self, headers, params=None):
        return self._request("GET", "/funding-advances", headers=headers, params=params)

    def get_funding_advance(self, advance_id, headers):
        return self._request("GET", f"/funding-advances/{advance_id}", headers=headers)

    def apply_funding_advance(self, advance_id, payload, headers):
        return self._request("POST", f"/funding-advances/{advance_id}/apply", payload, headers)

    def refund_funding_advance(self, advance_id, headers):
        return self._request("POST", f"/funding-advances/{advance_id}/refund", headers=headers)

    # --- Cost disputes ---
    def create_cost_dispute(self, payload, headers):
        return self._request("POST", "/cost-disputes", payload, headers)

    def list_cost_disputes(self, headers, params=None):
        return self._request("GET", "/cost-disputes", headers=headers, params=params)

    def get_cost_dispute(self, dispute_id, headers):
        return self._request("GET", f"/cost-disputes/{dispute_id}", headers=headers)

    def start_review_cost_dispute(self, dispute_id, headers):
        return self._request("POST", f"/cost-disputes/{dispute_id}/start-review", headers=headers)

    def uphold_cost_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/cost-disputes/{dispute_id}/uphold", payload, headers)

    def reject_cost_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/cost-disputes/{dispute_id}/reject", payload, headers)

    def escalate_cost_dispute(self, dispute_id, headers):
        return self._request("POST", f"/cost-disputes/{dispute_id}/escalate", headers=headers)

    def resolve_cost_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/cost-disputes/{dispute_id}/resolve", payload, headers)

    # --- Husbandry cases ---
    def create_husbandry_case(self, payload, headers):
        return self._request("POST", "/husbandry-cases", payload, headers)

    def list_husbandry_cases(self, headers, params=None):
        return self._request("GET", "/husbandry-cases", headers=headers, params=params)

    def get_husbandry_case(self, case_id, headers):
        return self._request("GET", f"/husbandry-cases/{case_id}", headers=headers)

    def begin_treatment_husbandry_case(self, case_id, headers):
        return self._request("POST", f"/husbandry-cases/{case_id}/begin-treatment", headers=headers)

    def clear_husbandry_case(self, case_id, headers):
        return self._request("POST", f"/husbandry-cases/{case_id}/clear", headers=headers)

    def repatriate_husbandry_case(self, case_id, headers):
        return self._request("POST", f"/husbandry-cases/{case_id}/repatriate", headers=headers)

    def waive_departure_hold(self, case_id, headers):
        return self._request("POST", f"/husbandry-cases/{case_id}/waive-departure-hold", headers=headers)


api_client = ApiClient()
