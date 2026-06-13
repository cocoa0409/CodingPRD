"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the /sdu prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CustodialParty ----
    def create_custodial_party(self, payload, headers):
        return self._request("POST", "/sdu/custodial-parties", payload, headers)

    def get_custodial_party(self, cp_id, headers):
        return self._request("GET", f"/sdu/custodial-parties/{cp_id}", headers=headers)

    def hold_custodial_party(self, cp_id, payload, headers):
        return self._request("POST", f"/sdu/custodial-parties/{cp_id}/hold", payload, headers)

    # ---- NoncustodialParty ----
    def create_noncustodial_party(self, payload, headers):
        return self._request("POST", "/sdu/noncustodial-parties", payload, headers)

    def get_noncustodial_party(self, ncp_id, headers):
        return self._request("GET", f"/sdu/noncustodial-parties/{ncp_id}", headers=headers)

    # ---- Employer ----
    def create_employer(self, payload, headers):
        return self._request("POST", "/sdu/employers", payload, headers)

    def get_employer(self, emp_id, headers):
        return self._request("GET", f"/sdu/employers/{emp_id}", headers=headers)

    # ---- SupportOrder ----
    def create_support_order(self, payload, headers):
        return self._request("POST", "/sdu/support-orders", payload, headers)

    def get_support_order(self, order_id, headers):
        return self._request("GET", f"/sdu/support-orders/{order_id}", headers=headers)

    def list_support_orders(self, headers, params=None):
        return self._request("GET", "/sdu/support-orders", headers=headers, params=params)

    def activate_support_order(self, order_id, headers):
        return self._request("POST", f"/sdu/support-orders/{order_id}/activate", {}, headers)

    def suspend_support_order(self, order_id, headers):
        return self._request("POST", f"/sdu/support-orders/{order_id}/suspend", {}, headers)

    def terminate_support_order(self, order_id, headers):
        return self._request("POST", f"/sdu/support-orders/{order_id}/terminate", {}, headers)

    def accrue_interest(self, order_id, headers):
        return self._request("POST", f"/sdu/support-orders/{order_id}/accrue-interest", {}, headers)

    def post_charge(self, order_id, headers):
        return self._request("POST", f"/sdu/support-orders/{order_id}/post-charge", {}, headers)

    # ---- LedgerEntry ----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/sdu/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, le_id, headers):
        return self._request("GET", f"/sdu/ledger-entries/{le_id}", headers=headers)

    # ---- IncomeWithholdingOrder ----
    def create_iwo(self, payload, headers):
        return self._request("POST", "/sdu/income-withholding-orders", payload, headers)

    def get_iwo(self, iwo_id, headers):
        return self._request("GET", f"/sdu/income-withholding-orders/{iwo_id}", headers=headers)

    def list_iwos(self, headers, params=None):
        return self._request("GET", "/sdu/income-withholding-orders", headers=headers, params=params)

    def acknowledge_iwo(self, iwo_id, headers):
        return self._request("POST", f"/sdu/income-withholding-orders/{iwo_id}/acknowledge", {}, headers)

    def terminate_iwo(self, iwo_id, headers):
        return self._request("POST", f"/sdu/income-withholding-orders/{iwo_id}/terminate", {}, headers)

    # ---- Remittance ----
    def create_remittance(self, payload, headers):
        return self._request("POST", "/sdu/remittances", payload, headers)

    def get_remittance(self, rem_id, headers):
        return self._request("GET", f"/sdu/remittances/{rem_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/sdu/remittances", headers=headers, params=params)

    def allocate_remittance(self, rem_id, headers):
        return self._request("POST", f"/sdu/remittances/{rem_id}/allocate", {}, headers)

    def return_remittance(self, rem_id, headers):
        return self._request("POST", f"/sdu/remittances/{rem_id}/return", {}, headers)

    # ---- Allocation ----
    def list_allocations(self, headers, params=None):
        return self._request("GET", "/sdu/allocations", headers=headers, params=params)

    def get_allocation(self, alloc_id, headers):
        return self._request("GET", f"/sdu/allocations/{alloc_id}", headers=headers)

    # ---- Disbursement ----
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/sdu/disbursements", payload, headers)

    def get_disbursement(self, disb_id, headers):
        return self._request("GET", f"/sdu/disbursements/{disb_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/sdu/disbursements", headers=headers, params=params)

    def send_disbursement(self, disb_id, headers):
        return self._request("POST", f"/sdu/disbursements/{disb_id}/send", {}, headers)

    def return_disbursement(self, disb_id, headers):
        return self._request("POST", f"/sdu/disbursements/{disb_id}/return", {}, headers)

    # ---- Modification ----
    def create_modification(self, payload, headers):
        return self._request("POST", "/sdu/modifications", payload, headers)

    def get_modification(self, mod_id, headers):
        return self._request("GET", f"/sdu/modifications/{mod_id}", headers=headers)

    def list_modifications(self, headers, params=None):
        return self._request("GET", "/sdu/modifications", headers=headers, params=params)

    def submit_modification(self, mod_id, headers):
        return self._request("POST", f"/sdu/modifications/{mod_id}/submit", {}, headers)

    def decide_modification(self, mod_id, payload, headers):
        return self._request("POST", f"/sdu/modifications/{mod_id}/decide", payload, headers)

    def revise_modification(self, mod_id, headers):
        return self._request("POST", f"/sdu/modifications/{mod_id}/revise", {}, headers)

    def apply_modification(self, mod_id, payload, headers):
        return self._request("POST", f"/sdu/modifications/{mod_id}/apply", payload, headers)

    # ---- EnforcementAction ----
    def create_enforcement_action(self, payload, headers):
        return self._request("POST", "/sdu/enforcement-actions", payload, headers)

    def get_enforcement_action(self, enf_id, headers):
        return self._request("GET", f"/sdu/enforcement-actions/{enf_id}", headers=headers)

    def list_enforcement_actions(self, headers, params=None):
        return self._request("GET", "/sdu/enforcement-actions", headers=headers, params=params)

    def certify_enforcement_action(self, enf_id, headers):
        return self._request("POST", f"/sdu/enforcement-actions/{enf_id}/certify", {}, headers)

    def withdraw_enforcement_action(self, enf_id, headers):
        return self._request("POST", f"/sdu/enforcement-actions/{enf_id}/withdraw", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/sdu/_clock/set", payload, headers)


api_client = ApiClient()
