"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Brand ----
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def list_brand_campaigns(self, brand_id, headers, params=None):
        return self._request("GET", f"/brands/{brand_id}/campaigns", headers=headers, params=params)

    # ---- Creator + discovery + audience ----
    def create_creator(self, payload, headers):
        return self._request("POST", "/creators", payload, headers)

    def get_creator(self, creator_id, headers):
        return self._request("GET", f"/creators/{creator_id}", headers=headers)

    def update_creator(self, creator_id, payload, headers):
        return self._request("PATCH", f"/creators/{creator_id}", payload, headers)

    def list_creators(self, headers, params=None):
        return self._request("GET", "/creators", headers=headers, params=params)

    def create_audience_snapshot(self, creator_id, payload, headers):
        return self._request("POST", f"/creators/{creator_id}/audience-snapshots", payload, headers)

    def list_audience_snapshots(self, creator_id, headers, params=None):
        return self._request("GET", f"/creators/{creator_id}/audience-snapshots", headers=headers, params=params)

    # ---- Brand-safety ----
    def create_brand_safety_flag(self, creator_id, payload, headers):
        return self._request("POST", f"/creators/{creator_id}/brand-safety-flags", payload, headers)

    def list_brand_safety_flags(self, creator_id, headers, params=None):
        return self._request("GET", f"/creators/{creator_id}/brand-safety-flags", headers=headers, params=params)

    def resolve_brand_safety_flag(self, flag_id, headers):
        return self._request("POST", f"/brand-safety-flags/{flag_id}/resolve", {}, headers)

    # ---- Campaign + deliverables ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def create_deliverable(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/deliverables", payload, headers)

    def list_deliverables(self, campaign_id, headers, params=None):
        return self._request("GET", f"/campaigns/{campaign_id}/deliverables", headers=headers, params=params)

    def open_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/open", payload, headers)

    def close_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/close", payload, headers)

    def cancel_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/cancel", payload, headers)

    # ---- Offers (negotiation) ----
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/counter", payload, headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", {}, headers)

    # ---- Contracts ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def cancel_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/cancel", payload, headers)

    def get_contract_performance(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/performance", headers=headers)

    # ---- Content submission & approval ----
    def create_content_submission(self, payload, headers):
        return self._request("POST", "/content-submissions", payload, headers)

    def get_content_submission(self, submission_id, headers):
        return self._request("GET", f"/content-submissions/{submission_id}", headers=headers)

    def list_content_submissions(self, headers, params=None):
        return self._request("GET", "/content-submissions", headers=headers, params=params)

    def start_review(self, submission_id, headers):
        return self._request("POST", f"/content-submissions/{submission_id}/start-review", {}, headers)

    def request_changes(self, submission_id, headers):
        return self._request("POST", f"/content-submissions/{submission_id}/request-changes", {}, headers)

    def resubmit_content(self, submission_id, payload, headers):
        return self._request("POST", f"/content-submissions/{submission_id}/resubmit", payload, headers)

    def approve_content(self, submission_id, headers):
        return self._request("POST", f"/content-submissions/{submission_id}/approve", {}, headers)

    def reject_content(self, submission_id, headers):
        return self._request("POST", f"/content-submissions/{submission_id}/reject", {}, headers)

    # ---- Attribution + conversions ----
    def create_attribution_asset(self, payload, headers):
        return self._request("POST", "/attribution-assets", payload, headers)

    def get_attribution_asset(self, asset_id, headers):
        return self._request("GET", f"/attribution-assets/{asset_id}", headers=headers)

    def list_contract_attribution_assets(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/attribution-assets", headers=headers, params=params)

    def create_conversion(self, asset_id, payload, headers):
        return self._request("POST", f"/attribution-assets/{asset_id}/conversions", payload, headers)

    def list_conversions(self, asset_id, headers, params=None):
        return self._request("GET", f"/attribution-assets/{asset_id}/conversions", headers=headers, params=params)

    # ---- Payouts ----
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_contract_payouts(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/payouts", headers=headers, params=params)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/release", {}, headers)

    def settle_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/settle", {}, headers)

    def fail_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/fail", {}, headers)

    # ---- Tax 1099 ----
    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/tax-forms/{form_id}", headers=headers)

    def list_creator_tax_forms(self, creator_id, headers, params=None):
        return self._request("GET", f"/creators/{creator_id}/tax-forms", headers=headers, params=params)

    def file_tax_form(self, form_id, headers):
        return self._request("POST", f"/tax-forms/{form_id}/file", {}, headers)

    def void_tax_form(self, form_id, headers):
        return self._request("POST", f"/tax-forms/{form_id}/void", {}, headers)

    # ---- Test-driving (logical clock) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
