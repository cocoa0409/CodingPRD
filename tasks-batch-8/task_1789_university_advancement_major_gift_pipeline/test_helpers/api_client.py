"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/advancement/_clock/set_current_utc", payload, headers)

    # --- Fundraisers & assignments ---
    def create_fundraiser(self, payload, headers):
        return self._request("POST", "/advancement/fundraisers", payload, headers)

    def get_fundraiser(self, fundraiser_id, headers):
        return self._request("GET", f"/advancement/fundraisers/{fundraiser_id}", headers=headers)

    def deactivate_fundraiser(self, fundraiser_id, headers):
        return self._request("POST", f"/advancement/fundraisers/{fundraiser_id}/deactivate", {}, headers)

    def create_assignment(self, fundraiser_id, payload, headers):
        return self._request("POST", f"/advancement/fundraisers/{fundraiser_id}/assignments", payload, headers)

    def list_fundraiser_assignments(self, fundraiser_id, headers, params=None):
        return self._request("GET", f"/advancement/fundraisers/{fundraiser_id}/assignments", headers=headers, params=params)

    def release_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/advancement/assignments/{assignment_id}/release", payload, headers)

    # --- Prospects ---
    def create_prospect(self, payload, headers):
        return self._request("POST", "/advancement/prospects", payload, headers)

    def get_prospect(self, prospect_id, headers):
        return self._request("GET", f"/advancement/prospects/{prospect_id}", headers=headers)

    def list_prospects(self, headers, params=None):
        return self._request("GET", "/advancement/prospects", headers=headers, params=params)

    def disqualify_prospect(self, prospect_id, headers):
        return self._request("POST", f"/advancement/prospects/{prospect_id}/disqualify", {}, headers)

    def move_prospect(self, prospect_id, payload, headers):
        return self._request("POST", f"/advancement/prospects/{prospect_id}/moves", payload, headers)

    def list_prospect_assignments(self, prospect_id, headers, params=None):
        return self._request("GET", f"/advancement/prospects/{prospect_id}/assignments", headers=headers, params=params)

    def list_prospect_credit_splits(self, prospect_id, headers, params=None):
        return self._request("GET", f"/advancement/prospects/{prospect_id}/credit-splits", headers=headers, params=params)

    def get_recognition(self, prospect_id, headers):
        return self._request("GET", f"/advancement/prospects/{prospect_id}/recognition", headers=headers)

    def create_assessment(self, prospect_id, payload, headers):
        return self._request("POST", f"/advancement/prospects/{prospect_id}/assessments", payload, headers)

    def list_prospect_assessments(self, prospect_id, headers, params=None):
        return self._request("GET", f"/advancement/prospects/{prospect_id}/assessments", headers=headers, params=params)

    def list_prospect_proposals(self, prospect_id, headers, params=None):
        return self._request("GET", f"/advancement/prospects/{prospect_id}/proposals", headers=headers, params=params)

    # --- Assessments ---
    def review_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/advancement/assessments/{assessment_id}/review", payload, headers)

    # --- Proposals ---
    def create_proposal(self, payload, headers):
        return self._request("POST", "/advancement/proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/advancement/proposals/{proposal_id}", headers=headers)

    def patch_proposal(self, proposal_id, payload, headers):
        return self._request("PATCH", f"/advancement/proposals/{proposal_id}", payload, headers)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST", f"/advancement/proposals/{proposal_id}/submit", {}, headers)

    def review_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/advancement/proposals/{proposal_id}/review", payload, headers)

    # --- Gift agreements ---
    def create_agreement(self, proposal_id, payload, headers):
        return self._request("POST", f"/advancement/proposals/{proposal_id}/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/advancement/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/advancement/agreements", headers=headers, params=params)

    def present_agreement(self, agreement_id, headers):
        return self._request("POST", f"/advancement/agreements/{agreement_id}/present", {}, headers)

    def execute_agreement(self, agreement_id, headers):
        return self._request("POST", f"/advancement/agreements/{agreement_id}/execute", {}, headers)

    def rescind_agreement(self, agreement_id, headers):
        return self._request("POST", f"/advancement/agreements/{agreement_id}/rescind", {}, headers)

    def list_agreement_naming_reservations(self, agreement_id, headers, params=None):
        return self._request("GET", f"/advancement/agreements/{agreement_id}/naming-reservations", headers=headers, params=params)

    # --- Naming opportunities ---
    def create_naming_opportunity(self, payload, headers):
        return self._request("POST", "/advancement/naming-opportunities", payload, headers)

    def get_naming_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/advancement/naming-opportunities/{opportunity_id}", headers=headers)

    def retire_naming_opportunity(self, opportunity_id, headers):
        return self._request("POST", f"/advancement/naming-opportunities/{opportunity_id}/retire", {}, headers)

    # --- Pledges, installments, write-offs ---
    def create_pledge(self, payload, headers):
        return self._request("POST", "/advancement/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/advancement/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/advancement/pledges", headers=headers, params=params)

    def list_installments(self, pledge_id, headers, params=None):
        return self._request("GET", f"/advancement/pledges/{pledge_id}/installments", headers=headers, params=params)

    def remind_installment(self, installment_id, headers):
        return self._request("POST", f"/advancement/installments/{installment_id}/remind", {}, headers)

    def create_write_off(self, pledge_id, payload, headers):
        return self._request("POST", f"/advancement/pledges/{pledge_id}/write-offs", payload, headers)

    def list_write_offs(self, pledge_id, headers, params=None):
        return self._request("GET", f"/advancement/pledges/{pledge_id}/write-offs", headers=headers, params=params)

    def review_write_off(self, write_off_id, payload, headers):
        return self._request("POST", f"/advancement/write-offs/{write_off_id}/review", payload, headers)

    # --- Gift payments ---
    def create_gift_payment(self, payload, headers):
        return self._request("POST", "/advancement/gift-payments", payload, headers)

    def get_gift_payment(self, payment_id, headers):
        return self._request("GET", f"/advancement/gift-payments/{payment_id}", headers=headers)

    def list_gift_payments(self, headers, params=None):
        return self._request("GET", "/advancement/gift-payments", headers=headers, params=params)

    def reverse_gift_payment(self, payment_id, headers):
        return self._request("POST", f"/advancement/gift-payments/{payment_id}/reverse", {}, headers)

    def list_payment_credit_splits(self, payment_id, headers, params=None):
        return self._request("GET", f"/advancement/gift-payments/{payment_id}/credit-splits", headers=headers, params=params)

    # --- Restricted funds ---
    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/advancement/funds/{fund_id}", headers=headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/advancement/funds", headers=headers, params=params)

    def create_valuation(self, fund_id, payload, headers):
        return self._request("POST", f"/advancement/funds/{fund_id}/valuations", payload, headers)

    def disburse_fund(self, fund_id, payload, headers):
        return self._request("POST", f"/advancement/funds/{fund_id}/disburse", payload, headers)

    def create_report(self, fund_id, payload, headers):
        return self._request("POST", f"/advancement/funds/{fund_id}/reports", payload, headers)

    def list_fund_reports(self, fund_id, headers, params=None):
        return self._request("GET", f"/advancement/funds/{fund_id}/reports", headers=headers, params=params)

    # --- Stewardship reports ---
    def submit_report(self, report_id, headers):
        return self._request("POST", f"/advancement/stewardship-reports/{report_id}/submit", {}, headers)

    def deliver_report(self, report_id, headers):
        return self._request("POST", f"/advancement/stewardship-reports/{report_id}/deliver", {}, headers)

    # --- Campaigns ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/advancement/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/advancement/campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/advancement/campaigns/{campaign_id}/activate", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/advancement/campaigns/{campaign_id}/close", {}, headers)

    def report_campaign(self, campaign_id, headers):
        return self._request("POST", f"/advancement/campaigns/{campaign_id}/report", {}, headers)

    def get_campaign_totals(self, campaign_id, headers):
        return self._request("GET", f"/advancement/campaigns/{campaign_id}/totals", headers=headers)

    def list_campaign_credit_splits(self, campaign_id, headers, params=None):
        return self._request("GET", f"/advancement/campaigns/{campaign_id}/credit-splits", headers=headers, params=params)

    # --- Recognition societies ---
    def create_recognition_society(self, payload, headers):
        return self._request("POST", "/advancement/recognition-societies", payload, headers)

    def list_recognition_societies(self, headers, params=None):
        return self._request("GET", "/advancement/recognition-societies", headers=headers, params=params)


api_client = ApiClient()
