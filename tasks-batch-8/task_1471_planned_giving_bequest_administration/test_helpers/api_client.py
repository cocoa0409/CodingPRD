"""API client: one method per endpoint defined in the PRD (all under /giving)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/giving/_clock/set_current_utc", payload, headers)

    # ---- donors ----
    def create_donor(self, payload, headers):
        return self._request("POST", "/giving/donors", payload, headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/giving/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/giving/donors/{donor_id}", headers=headers)

    def record_death(self, donor_id, payload, headers):
        return self._request("POST", f"/giving/donors/{donor_id}/record-death", payload, headers)

    def legacy_society_transition(self, donor_id, payload, headers):
        return self._request(
            "POST", f"/giving/donors/{donor_id}/legacy-society-transition", payload, headers
        )

    # ---- rate tables ----
    def create_rate_table(self, payload, headers):
        return self._request("POST", "/giving/rate-tables", payload, headers)

    def get_rate_table(self, rate_table_id, headers):
        return self._request("GET", f"/giving/rate-tables/{rate_table_id}", headers=headers)

    def transition_rate_table(self, rate_table_id, payload, headers):
        return self._request(
            "POST", f"/giving/rate-tables/{rate_table_id}/transition", payload, headers
        )

    # ---- illustrations ----
    def create_illustration(self, payload, headers):
        return self._request("POST", "/giving/illustrations", payload, headers)

    def list_illustrations(self, headers, params=None):
        return self._request("GET", "/giving/illustrations", headers=headers, params=params)

    def get_illustration(self, illustration_id, headers):
        return self._request("GET", f"/giving/illustrations/{illustration_id}", headers=headers)

    def book_illustration(self, illustration_id, headers):
        return self._request(
            "POST", f"/giving/illustrations/{illustration_id}/book", {}, headers
        )

    # ---- gift agreements ----
    def create_gift_agreement(self, payload, headers):
        return self._request("POST", "/giving/gift-agreements", payload, headers)

    def list_gift_agreements(self, headers, params=None):
        return self._request("GET", "/giving/gift-agreements", headers=headers, params=params)

    def get_gift_agreement(self, agreement_id, headers):
        return self._request("GET", f"/giving/gift-agreements/{agreement_id}", headers=headers)

    def amend_gift_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/giving/gift-agreements/{agreement_id}/amend", payload, headers
        )

    def execute_gift_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/giving/gift-agreements/{agreement_id}/execute", {}, headers
        )

    def transition_gift_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/giving/gift-agreements/{agreement_id}/transition", payload, headers
        )

    def terminate_gift_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/giving/gift-agreements/{agreement_id}/terminate", {}, headers
        )

    def settle_gift_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/giving/gift-agreements/{agreement_id}/settle", {}, headers
        )

    def generate_payment_schedule(self, agreement_id, headers):
        return self._request(
            "POST", f"/giving/gift-agreements/{agreement_id}/generate-payment-schedule", {}, headers
        )

    # ---- beneficiary designations ----
    def create_beneficiary_designation(self, payload, headers):
        return self._request("POST", "/giving/beneficiary-designations", payload, headers)

    def list_beneficiary_designations(self, headers, params=None):
        return self._request(
            "GET", "/giving/beneficiary-designations", headers=headers, params=params
        )

    def get_beneficiary_designation(self, designation_id, headers):
        return self._request(
            "GET", f"/giving/beneficiary-designations/{designation_id}", headers=headers
        )

    def transition_beneficiary_designation(self, designation_id, payload, headers):
        return self._request(
            "POST",
            f"/giving/beneficiary-designations/{designation_id}/transition",
            payload,
            headers,
        )

    # ---- gift assets ----
    def create_gift_asset(self, payload, headers):
        return self._request("POST", "/giving/gift-assets", payload, headers)

    def list_gift_assets(self, headers, params=None):
        return self._request("GET", "/giving/gift-assets", headers=headers, params=params)

    def get_gift_asset(self, asset_id, headers):
        return self._request("GET", f"/giving/gift-assets/{asset_id}", headers=headers)

    def transition_gift_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/giving/gift-assets/{asset_id}/transition", payload, headers
        )

    # ---- annuity payments ----
    def list_annuity_payments(self, headers, params=None):
        return self._request("GET", "/giving/annuity-payments", headers=headers, params=params)

    def get_annuity_payment(self, payment_id, headers):
        return self._request("GET", f"/giving/annuity-payments/{payment_id}", headers=headers)

    def transition_annuity_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/giving/annuity-payments/{payment_id}/transition", payload, headers
        )

    # ---- reserve fund (singleton) ----
    def get_reserve_fund(self, headers):
        return self._request("GET", "/giving/reserve-fund", headers=headers)

    def create_reserve_adjustment(self, payload, headers):
        return self._request("POST", "/giving/reserve-fund/adjustments", payload, headers)

    # ---- estates & probate ----
    def create_estate(self, payload, headers):
        return self._request("POST", "/giving/estates", payload, headers)

    def list_estates(self, headers, params=None):
        return self._request("GET", "/giving/estates", headers=headers, params=params)

    def get_estate(self, estate_id, headers):
        return self._request("GET", f"/giving/estates/{estate_id}", headers=headers)

    def transition_estate(self, estate_id, payload, headers):
        return self._request("POST", f"/giving/estates/{estate_id}/transition", payload, headers)

    def create_probate_milestone(self, payload, headers):
        return self._request("POST", "/giving/probate-milestones", payload, headers)

    def list_probate_milestones(self, headers, params=None):
        return self._request("GET", "/giving/probate-milestones", headers=headers, params=params)

    def get_probate_milestone(self, milestone_id, headers):
        return self._request("GET", f"/giving/probate-milestones/{milestone_id}", headers=headers)

    def transition_probate_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/giving/probate-milestones/{milestone_id}/transition", payload, headers
        )

    # ---- funds ----
    def create_fund(self, payload, headers):
        return self._request("POST", "/giving/funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/giving/funds", headers=headers, params=params)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/giving/funds/{fund_id}", headers=headers)

    def transition_fund(self, fund_id, payload, headers):
        return self._request("POST", f"/giving/funds/{fund_id}/transition", payload, headers)

    # ---- valuation runs ----
    def create_valuation_run(self, payload, headers):
        return self._request("POST", "/giving/valuation-runs", payload, headers)

    def get_valuation_run(self, valuation_run_id, headers):
        return self._request("GET", f"/giving/valuation-runs/{valuation_run_id}", headers=headers)

    def post_valuation_run(self, valuation_run_id, headers):
        return self._request(
            "POST", f"/giving/valuation-runs/{valuation_run_id}/post", {}, headers
        )


api_client = ApiClient()
