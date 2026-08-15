"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- EndowmentPool ---
    def create_pool(self, payload, headers):
        return self._request("POST", "/endowment/pools", payload, headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/endowment/pools", headers=headers, params=params)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/endowment/pools/{pool_id}", headers=headers)

    def suspend_pool(self, pool_id, headers):
        return self._request("POST", f"/endowment/pools/{pool_id}/suspend", {}, headers)

    def resume_pool(self, pool_id, headers):
        return self._request("POST", f"/endowment/pools/{pool_id}/resume", {}, headers)

    def terminate_pool(self, pool_id, headers):
        return self._request("POST", f"/endowment/pools/{pool_id}/terminate", {}, headers)

    # --- SpendingPolicyVersion ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/endowment/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/endowment/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/endowment/policies/{policy_id}", headers=headers)

    def adopt_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/endowment/policies/{policy_id}/adopt", payload, headers)

    def withdraw_policy(self, policy_id, headers):
        return self._request("POST", f"/endowment/policies/{policy_id}/withdraw", {}, headers)

    # --- UnitValuation ---
    def create_valuation(self, payload, headers):
        return self._request("POST", "/endowment/valuations", payload, headers)

    def list_valuations(self, headers, params=None):
        return self._request("GET", "/endowment/valuations", headers=headers, params=params)

    def get_valuation(self, valuation_id, headers):
        return self._request("GET", f"/endowment/valuations/{valuation_id}", headers=headers)

    def finalize_valuation(self, valuation_id, payload, headers):
        return self._request("POST", f"/endowment/valuations/{valuation_id}/finalize", payload, headers)

    def supersede_valuation(self, valuation_id, payload, headers):
        return self._request("POST", f"/endowment/valuations/{valuation_id}/supersede", payload, headers)

    # --- Donor ---
    def create_donor(self, payload, headers):
        return self._request("POST", "/endowment/donors", payload, headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/endowment/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/endowment/donors/{donor_id}", headers=headers)

    # --- Fund ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/endowment/funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/endowment/funds", headers=headers, params=params)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/endowment/funds/{fund_id}", headers=headers)

    def activate_fund(self, fund_id, headers):
        return self._request("POST", f"/endowment/funds/{fund_id}/activate", {}, headers)

    def terminate_fund(self, fund_id, headers):
        return self._request("POST", f"/endowment/funds/{fund_id}/terminate", {}, headers)

    def redeem_corpus(self, fund_id, payload, headers):
        return self._request("POST", f"/endowment/funds/{fund_id}/redeem_corpus", payload, headers)

    # --- GiftContribution ---
    def create_gift(self, payload, headers):
        return self._request("POST", "/endowment/gifts", payload, headers)

    def list_gifts(self, headers, params=None):
        return self._request("GET", "/endowment/gifts", headers=headers, params=params)

    def get_gift(self, gift_id, headers):
        return self._request("GET", f"/endowment/gifts/{gift_id}", headers=headers)

    def receive_gift(self, gift_id, headers):
        return self._request("POST", f"/endowment/gifts/{gift_id}/receive", {}, headers)

    def cancel_gift(self, gift_id, headers):
        return self._request("POST", f"/endowment/gifts/{gift_id}/cancel", {}, headers)

    def rescind_gift(self, gift_id, headers):
        return self._request("POST", f"/endowment/gifts/{gift_id}/rescind", {}, headers)

    # --- SpendingDistribution ---
    def create_distribution(self, payload, headers):
        return self._request("POST", "/endowment/distributions", payload, headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/endowment/distributions", headers=headers, params=params)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/endowment/distributions/{distribution_id}", headers=headers)

    def propose_distribution(self, distribution_id, headers):
        return self._request("POST", f"/endowment/distributions/{distribution_id}/propose", {}, headers)

    def request_revision_distribution(self, distribution_id, headers):
        return self._request("POST", f"/endowment/distributions/{distribution_id}/request_revision", {}, headers)

    def repropose_distribution(self, distribution_id, headers):
        return self._request("POST", f"/endowment/distributions/{distribution_id}/repropose", {}, headers)

    def approve_distribution(self, distribution_id, headers):
        return self._request("POST", f"/endowment/distributions/{distribution_id}/approve", {}, headers)

    def distribute_distribution(self, distribution_id, headers):
        return self._request("POST", f"/endowment/distributions/{distribution_id}/distribute", {}, headers)

    def cancel_distribution(self, distribution_id, headers):
        return self._request("POST", f"/endowment/distributions/{distribution_id}/cancel", {}, headers)

    # --- PolicyException ---
    def create_exception(self, payload, headers):
        return self._request("POST", "/endowment/exceptions", payload, headers)

    def list_exceptions(self, headers, params=None):
        return self._request("GET", "/endowment/exceptions", headers=headers, params=params)

    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/endowment/exceptions/{exception_id}", headers=headers)

    def endorse_exception(self, exception_id, headers):
        return self._request("POST", f"/endowment/exceptions/{exception_id}/endorse", {}, headers)

    def approve_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/endowment/exceptions/{exception_id}/approve", payload, headers)

    def reject_exception(self, exception_id, headers):
        return self._request("POST", f"/endowment/exceptions/{exception_id}/reject", {}, headers)

    def rescind_exception(self, exception_id, headers):
        return self._request("POST", f"/endowment/exceptions/{exception_id}/rescind", {}, headers)

    # --- ProgramPayout ---
    def create_payout(self, payload, headers):
        return self._request("POST", "/endowment/payouts", payload, headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/endowment/payouts", headers=headers, params=params)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/endowment/payouts/{payout_id}", headers=headers)

    def disburse_payout(self, payout_id, headers):
        return self._request("POST", f"/endowment/payouts/{payout_id}/disburse", {}, headers)

    def report_spending(self, payout_id, payload, headers):
        return self._request("POST", f"/endowment/payouts/{payout_id}/report_spending", payload, headers)

    # --- AssetClassAllocation ---
    def bulk_upsert_allocations(self, payload, headers):
        return self._request("POST", "/endowment/allocations/bulk_upsert", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/endowment/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/endowment/allocations/{allocation_id}", headers=headers)

    def acknowledge_drift(self, allocation_id, headers):
        return self._request("POST", f"/endowment/allocations/{allocation_id}/acknowledge_drift", {}, headers)

    # --- InvestmentManager ---
    def create_manager(self, payload, headers):
        return self._request("POST", "/endowment/managers", payload, headers)

    def list_managers(self, headers, params=None):
        return self._request("GET", "/endowment/managers", headers=headers, params=params)

    def get_manager(self, manager_id, headers):
        return self._request("GET", f"/endowment/managers/{manager_id}", headers=headers)

    def engage_manager(self, manager_id, headers):
        return self._request("POST", f"/endowment/managers/{manager_id}/engage", {}, headers)

    def decline_manager(self, manager_id, headers):
        return self._request("POST", f"/endowment/managers/{manager_id}/decline", {}, headers)

    def terminate_manager(self, manager_id, headers):
        return self._request("POST", f"/endowment/managers/{manager_id}/terminate", {}, headers)

    # --- ManagerQuarterReport ---
    def create_manager_report(self, payload, headers):
        return self._request("POST", "/endowment/manager-quarter-reports", payload, headers)

    def list_manager_reports(self, headers, params=None):
        return self._request("GET", "/endowment/manager-quarter-reports", headers=headers, params=params)

    def get_manager_report(self, report_id, headers):
        return self._request("GET", f"/endowment/manager-quarter-reports/{report_id}", headers=headers)

    # --- AnnualReport ---
    def create_report(self, payload, headers):
        return self._request("POST", "/endowment/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/endowment/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/endowment/reports/{report_id}", headers=headers)

    def submit_review_report(self, report_id, headers):
        return self._request("POST", f"/endowment/reports/{report_id}/submit_review", {}, headers)

    def return_for_revision_report(self, report_id, headers):
        return self._request("POST", f"/endowment/reports/{report_id}/return_for_revision", {}, headers)

    def publish_report(self, report_id, headers):
        return self._request("POST", f"/endowment/reports/{report_id}/publish", {}, headers)

    # --- UnitLedgerEntry ---
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/endowment/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/endowment/ledger-entries/{entry_id}", headers=headers)


api_client = ApiClient()
