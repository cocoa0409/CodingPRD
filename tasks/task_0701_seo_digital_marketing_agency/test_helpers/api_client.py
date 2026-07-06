"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Reseller ----
    def create_reseller(self, payload, headers):
        return self._request("POST", "/resellers", payload, headers)

    def get_reseller(self, reseller_id, headers):
        return self._request("GET", f"/resellers/{reseller_id}", headers=headers)

    def list_resellers(self, headers, params=None):
        return self._request("GET", "/resellers", headers=headers, params=params)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def pause_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/pause", {}, headers)

    def resume_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/resume", {}, headers)

    def churn_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/churn", {}, headers)

    # ---- SiteAudit ----
    def create_audit(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def list_client_audits(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/audits", headers=headers, params=params
        )

    # ---- KeywordTarget ----
    def create_keyword_target(self, payload, headers):
        return self._request("POST", "/keyword-targets", payload, headers)

    def get_keyword_target(self, keyword_id, headers):
        return self._request("GET", f"/keyword-targets/{keyword_id}", headers=headers)

    def list_keyword_targets(self, headers, params=None):
        return self._request("GET", "/keyword-targets", headers=headers, params=params)

    def activate_tracking(self, keyword_id, headers):
        return self._request(
            "POST", f"/keyword-targets/{keyword_id}/activate-tracking", {}, headers
        )

    def drop_keyword_target(self, keyword_id, headers):
        return self._request(
            "POST", f"/keyword-targets/{keyword_id}/drop", {}, headers
        )

    # ---- RankSnapshot ----
    def create_snapshot(self, keyword_id, payload, headers):
        return self._request(
            "POST", f"/keyword-targets/{keyword_id}/snapshots", payload, headers
        )

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/snapshots/{snapshot_id}", headers=headers)

    def list_keyword_snapshots(self, keyword_id, headers, params=None):
        return self._request(
            "GET", f"/keyword-targets/{keyword_id}/snapshots", headers=headers,
            params=params,
        )

    # ---- Retainer ----
    def create_retainer(self, payload, headers):
        return self._request("POST", "/retainers", payload, headers)

    def get_retainer(self, retainer_id, headers):
        return self._request("GET", f"/retainers/{retainer_id}", headers=headers)

    def list_retainers(self, headers, params=None):
        return self._request("GET", "/retainers", headers=headers, params=params)

    def activate_retainer(self, retainer_id, headers):
        return self._request(
            "POST", f"/retainers/{retainer_id}/activate", {}, headers
        )

    def suspend_retainer(self, retainer_id, headers):
        return self._request(
            "POST", f"/retainers/{retainer_id}/suspend", {}, headers
        )

    def close_retainer(self, retainer_id, headers):
        return self._request("POST", f"/retainers/{retainer_id}/close", {}, headers)

    def rollover_retainer(self, retainer_id, payload, headers):
        return self._request(
            "POST", f"/retainers/{retainer_id}/rollover", payload, headers
        )

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/sign", {}, headers)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate", {}, headers
        )

    def renew_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/renew", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/terminate", {}, headers
        )

    # ---- Sprint ----
    def create_sprint(self, payload, headers):
        return self._request("POST", "/sprints", payload, headers)

    def get_sprint(self, sprint_id, headers):
        return self._request("GET", f"/sprints/{sprint_id}", headers=headers)

    def list_sprints(self, headers, params=None):
        return self._request("GET", "/sprints", headers=headers, params=params)

    def start_sprint(self, sprint_id, headers):
        return self._request("POST", f"/sprints/{sprint_id}/start", {}, headers)

    def close_sprint(self, sprint_id, headers):
        return self._request("POST", f"/sprints/{sprint_id}/close", {}, headers)

    # ---- Deliverable ----
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/deliverables", payload, headers)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/deliverables", headers=headers, params=params)

    def assign_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/assign", payload, headers
        )

    def start_deliverable(self, deliverable_id, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/start", {}, headers
        )

    def submit_deliverable(self, deliverable_id, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/submit", {}, headers
        )

    def request_revision(self, deliverable_id, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/request_revision", {}, headers
        )

    def approve_deliverable(self, deliverable_id, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/approve", {}, headers
        )

    def reject_deliverable(self, deliverable_id, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/reject", {}, headers
        )

    def cancel_deliverable(self, deliverable_id, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/cancel", {}, headers
        )

    # ---- AdCampaign ----
    def create_ad_campaign(self, payload, headers):
        return self._request("POST", "/ad-campaigns", payload, headers)

    def get_ad_campaign(self, campaign_id, headers):
        return self._request("GET", f"/ad-campaigns/{campaign_id}", headers=headers)

    def list_ad_campaigns(self, headers, params=None):
        return self._request("GET", "/ad-campaigns", headers=headers, params=params)

    def launch_ad_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/ad-campaigns/{campaign_id}/launch", {}, headers
        )

    def pause_ad_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/ad-campaigns/{campaign_id}/pause", {}, headers
        )

    def end_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/ad-campaigns/{campaign_id}/end", {}, headers)

    def record_spend(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/ad-campaigns/{campaign_id}/record-spend", payload, headers
        )

    def invoice_ad_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/ad-campaigns/{campaign_id}/invoice", {}, headers
        )

    def settle_ad_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/ad-campaigns/{campaign_id}/settle", {}, headers
        )

    # ---- AdSpendDispute ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/ad-spend-disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/ad-spend-disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/ad-spend-disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/ad-spend-disputes/{dispute_id}/review", {}, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ad-spend-disputes/{dispute_id}/resolve", payload, headers
        )

    def withdraw_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/ad-spend-disputes/{dispute_id}/withdraw", {}, headers
        )

    # ---- GbpListing ----
    def create_gbp_listing(self, payload, headers):
        return self._request("POST", "/gbp-listings", payload, headers)

    def get_gbp_listing(self, listing_id, headers):
        return self._request("GET", f"/gbp-listings/{listing_id}", headers=headers)

    def list_gbp_listings(self, headers, params=None):
        return self._request("GET", "/gbp-listings", headers=headers, params=params)

    def verify_gbp_listing(self, listing_id, headers):
        return self._request("POST", f"/gbp-listings/{listing_id}/verify", {}, headers)

    def optimize_gbp_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/gbp-listings/{listing_id}/optimize", {}, headers
        )

    def suspend_gbp_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/gbp-listings/{listing_id}/suspend", {}, headers
        )

    # ---- Report ----
    def create_report(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_client_reports(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/reports", headers=headers, params=params
        )


api_client = ApiClient()
