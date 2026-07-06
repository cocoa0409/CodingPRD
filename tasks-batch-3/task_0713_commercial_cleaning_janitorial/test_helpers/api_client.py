"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request(method, path, payload=None,
headers=None, params=None) is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Account ──────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    # ─── SiteContact ──────────────────────────────────────────────────
    def create_site_contact(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/site-contacts", payload, headers)

    def list_site_contacts(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/site-contacts", headers=headers, params=params)

    # ─── RfpOpportunity ───────────────────────────────────────────────
    def create_rfp(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps", payload, headers)

    def get_rfp(self, account_id, rfp_id, headers):
        return self._request("GET", f"/accounts/{account_id}/rfps/{rfp_id}", headers=headers)

    def list_rfps(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/rfps", headers=headers, params=params)

    # ─── Walkthrough ──────────────────────────────────────────────────
    def create_walkthrough(self, account_id, rfp_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/walkthroughs", payload, headers)

    def list_walkthroughs(self, account_id, rfp_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/rfps/{rfp_id}/walkthroughs", headers=headers, params=params)

    def complete_walkthrough(self, account_id, rfp_id, wt_id, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/walkthroughs/{wt_id}/complete", {}, headers)

    # ─── ServiceArea ──────────────────────────────────────────────────
    def create_service_area(self, account_id, rfp_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/service-areas", payload, headers)

    def list_service_areas(self, account_id, rfp_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/rfps/{rfp_id}/service-areas", headers=headers, params=params)

    # ─── BidEstimate ──────────────────────────────────────────────────
    def create_bid_estimate(self, account_id, rfp_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/bid-estimates", payload, headers)

    def get_bid_estimate(self, account_id, rfp_id, bid_id, headers):
        return self._request("GET", f"/accounts/{account_id}/rfps/{rfp_id}/bid-estimates/{bid_id}", headers=headers)

    def list_bid_estimates(self, account_id, rfp_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/rfps/{rfp_id}/bid-estimates", headers=headers, params=params)

    def price_bid_estimate(self, account_id, rfp_id, bid_id, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/bid-estimates/{bid_id}/price", {}, headers)

    # ─── Proposal ─────────────────────────────────────────────────────
    def create_proposal(self, account_id, rfp_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/proposals", payload, headers)

    def get_proposal(self, account_id, rfp_id, proposal_id, headers):
        return self._request("GET", f"/accounts/{account_id}/rfps/{rfp_id}/proposals/{proposal_id}", headers=headers)

    def list_proposals(self, account_id, rfp_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/rfps/{rfp_id}/proposals", headers=headers, params=params)

    def send_proposal(self, account_id, rfp_id, proposal_id, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/proposals/{proposal_id}/send", {}, headers)

    def revise_proposal(self, account_id, rfp_id, proposal_id, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/proposals/{proposal_id}/revise", {}, headers)

    def accept_proposal(self, account_id, rfp_id, proposal_id, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/proposals/{proposal_id}/accept", {}, headers)

    def decline_proposal(self, account_id, rfp_id, proposal_id, headers):
        return self._request("POST", f"/accounts/{account_id}/rfps/{rfp_id}/proposals/{proposal_id}/decline", {}, headers)

    # ─── CleaningContract ─────────────────────────────────────────────
    def create_contract(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts", payload, headers)

    def get_contract(self, account_id, contract_id, headers):
        return self._request("GET", f"/accounts/{account_id}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/contracts", headers=headers, params=params)

    def sign_contract(self, account_id, contract_id, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts/{contract_id}/sign", {}, headers)

    def end_contract(self, account_id, contract_id, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts/{contract_id}/end", {}, headers)

    def suspend_billing(self, account_id, contract_id, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts/{contract_id}/billing/suspend", {}, headers)

    def resume_billing(self, account_id, contract_id, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts/{contract_id}/billing/resume", {}, headers)

    def upsell_contract(self, account_id, contract_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts/{contract_id}/upsell", payload, headers)

    # ─── StartupPlan ──────────────────────────────────────────────────
    def get_startup_plan(self, account_id, plan_id, headers):
        return self._request("GET", f"/accounts/{account_id}/startup-plans/{plan_id}", headers=headers)

    def list_startup_plans(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/startup-plans", headers=headers, params=params)

    def assign_crew_shift(self, account_id, plan_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/startup-plans/{plan_id}/crew", payload, headers)

    def mark_ready(self, account_id, plan_id, headers):
        return self._request("POST", f"/accounts/{account_id}/startup-plans/{plan_id}/mark-ready", {}, headers)

    def go_live(self, account_id, plan_id, headers):
        return self._request("POST", f"/accounts/{account_id}/startup-plans/{plan_id}/go-live", {}, headers)

    def abort_plan(self, account_id, plan_id, headers):
        return self._request("POST", f"/accounts/{account_id}/startup-plans/{plan_id}/abort", {}, headers)

    # ─── Crew ─────────────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def retire_crew(self, crew_id, headers):
        return self._request("POST", f"/crews/{crew_id}/retire", {}, headers)

    # ─── CrewShift ────────────────────────────────────────────────────
    def list_plan_crew_shifts(self, account_id, plan_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/startup-plans/{plan_id}/crew-shifts", headers=headers, params=params)

    def list_crew_shifts(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/crew-shifts", headers=headers, params=params)

    def cancel_crew_shift(self, account_id, shift_id, headers):
        return self._request("POST", f"/accounts/{account_id}/crew-shifts/{shift_id}/cancel", {}, headers)

    # ─── SupplyBudget ─────────────────────────────────────────────────
    def create_supply_budget(self, account_id, contract_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts/{contract_id}/supply-budget", payload, headers)

    def list_contract_supply_budgets(self, account_id, contract_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/contracts/{contract_id}/supply-budget", headers=headers, params=params)

    def get_supply_budget(self, account_id, budget_id, headers):
        return self._request("GET", f"/accounts/{account_id}/supply-budgets/{budget_id}", headers=headers)

    # ─── SupplyRequisition ────────────────────────────────────────────
    def create_requisition(self, account_id, budget_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/supply-budgets/{budget_id}/requisitions", payload, headers)

    def list_requisitions(self, account_id, budget_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/supply-budgets/{budget_id}/requisitions", headers=headers, params=params)

    def get_requisition(self, account_id, req_id, headers):
        return self._request("GET", f"/accounts/{account_id}/supply-requisitions/{req_id}", headers=headers)

    def approve_requisition(self, account_id, req_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/supply-requisitions/{req_id}/approve", payload, headers)

    def cancel_requisition(self, account_id, req_id, headers):
        return self._request("POST", f"/accounts/{account_id}/supply-requisitions/{req_id}/cancel", {}, headers)

    # ─── RenewalCycle ─────────────────────────────────────────────────
    def create_renewal_cycle(self, account_id, contract_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/contracts/{contract_id}/renewal-cycles", payload, headers)

    def list_renewal_cycles(self, account_id, contract_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/contracts/{contract_id}/renewal-cycles", headers=headers, params=params)

    def get_renewal_cycle(self, account_id, cycle_id, headers):
        return self._request("GET", f"/accounts/{account_id}/renewal-cycles/{cycle_id}", headers=headers)

    def offer_renewal(self, account_id, cycle_id, headers):
        return self._request("POST", f"/accounts/{account_id}/renewal-cycles/{cycle_id}/offer", {}, headers)

    def accept_renewal(self, account_id, cycle_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/renewal-cycles/{cycle_id}/accept", payload, headers)

    def lapse_renewal(self, account_id, cycle_id, headers):
        return self._request("POST", f"/accounts/{account_id}/renewal-cycles/{cycle_id}/lapse", {}, headers)

    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
