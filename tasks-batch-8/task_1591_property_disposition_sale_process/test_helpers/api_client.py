"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the /disposition prefix (PRD Endpoint
Definitions).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/disposition"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------
    def create_asset(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}", headers=headers)

    def list_asset_for_sale(self, asset_id, headers):
        return self._request("POST", f"{PREFIX}/assets/{asset_id}/list", {}, headers)

    def open_asset_offers(self, asset_id, offers_deadline, headers):
        return self._request("POST", f"{PREFIX}/assets/{asset_id}/open_offers",
                             {"offers_deadline": offers_deadline}, headers)

    def close_asset_offers(self, asset_id, headers):
        return self._request("POST", f"{PREFIX}/assets/{asset_id}/close_offers", {}, headers)

    def withdraw_asset(self, asset_id, headers):
        return self._request("POST", f"{PREFIX}/assets/{asset_id}/withdraw", {}, headers)

    def list_asset_analyses(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}/analyses", headers=headers)

    def list_asset_engagements(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}/engagements", headers=headers)

    def list_asset_packages(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}/packages", headers=headers)

    def list_asset_bidders(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}/bidders", headers=headers)

    def list_asset_bids(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}/bids", headers=headers)

    def list_asset_psas(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}/psas", headers=headers)

    def list_asset_payoffs(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}/payoffs", headers=headers)

    # ------------------------------------------------------------------
    # Hold/sell analyses
    # ------------------------------------------------------------------
    def create_analysis(self, payload, headers):
        return self._request("POST", f"{PREFIX}/analyses", payload, headers)

    def submit_analysis(self, analysis_id, headers):
        return self._request("POST", f"{PREFIX}/analyses/{analysis_id}/submit", {}, headers)

    def decide_analysis(self, analysis_id, decision, headers):
        return self._request("POST", f"{PREFIX}/analyses/{analysis_id}/decide",
                             {"decision": decision}, headers)

    def revise_analysis(self, analysis_id, headers):
        return self._request("POST", f"{PREFIX}/analyses/{analysis_id}/revise", {}, headers)

    # ------------------------------------------------------------------
    # Broker engagements
    # ------------------------------------------------------------------
    def create_engagement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/engagements", payload, headers)

    def activate_engagement(self, engagement_id, headers):
        return self._request("POST", f"{PREFIX}/engagements/{engagement_id}/activate", {}, headers)

    def terminate_engagement(self, engagement_id, headers):
        return self._request("POST", f"{PREFIX}/engagements/{engagement_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Offering packages (data room)
    # ------------------------------------------------------------------
    def create_package(self, payload, headers):
        return self._request("POST", f"{PREFIX}/packages", payload, headers)

    def upload_documents(self, package_id, documents, headers):
        return self._request("POST", f"{PREFIX}/packages/{package_id}/upload_document",
                             {"documents": documents}, headers)

    def verify_documents(self, package_id, categories, headers):
        return self._request("POST", f"{PREFIX}/packages/{package_id}/verify_document",
                             {"categories": categories}, headers)

    def publish_package(self, package_id, headers):
        return self._request("POST", f"{PREFIX}/packages/{package_id}/publish", {}, headers)

    # ------------------------------------------------------------------
    # Bidders
    # ------------------------------------------------------------------
    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"{PREFIX}/bidders/{bidder_id}", headers=headers)

    def create_bidder(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bidders", payload, headers)

    def qualify_bidder(self, bidder_id, headers):
        return self._request("POST", f"{PREFIX}/bidders/{bidder_id}/qualify", {}, headers)

    def reapply_bidder(self, bidder_id, proof_of_funds_cents, headers):
        return self._request("POST", f"{PREFIX}/bidders/{bidder_id}/reapply",
                             {"proof_of_funds_cents": proof_of_funds_cents}, headers)

    def grant_access(self, bidder_id, window_start, window_end, headers):
        return self._request("POST", f"{PREFIX}/bidders/{bidder_id}/grant_access",
                             {"window_start": window_start, "window_end": window_end},
                             headers)

    # ------------------------------------------------------------------
    # Bids
    # ------------------------------------------------------------------
    def create_bid(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"{PREFIX}/bids/{bid_id}", headers=headers)

    def list_bidder_bids(self, bidder_id, headers):
        return self._request("GET", f"{PREFIX}/bidders/{bidder_id}/bids", headers=headers)

    def improve_bid(self, bid_id, price_cents, headers):
        return self._request("POST", f"{PREFIX}/bids/{bid_id}/improve",
                             {"price_cents": price_cents}, headers)

    def shortlist_bid(self, bid_id, headers):
        return self._request("POST", f"{PREFIX}/bids/{bid_id}/shortlist", {}, headers)

    def select_bid(self, bid_id, headers):
        return self._request("POST", f"{PREFIX}/bids/{bid_id}/select", {}, headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"{PREFIX}/bids/{bid_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Purchase agreements
    # ------------------------------------------------------------------
    def create_psa(self, payload, headers):
        return self._request("POST", f"{PREFIX}/psas", payload, headers)

    def get_psa(self, psa_id, headers):
        return self._request("GET", f"{PREFIX}/psas/{psa_id}", headers=headers)

    def list_bid_psas(self, bid_id, headers):
        return self._request("GET", f"{PREFIX}/bids/{bid_id}/psas", headers=headers)

    def execute_psa(self, psa_id, closing_date, headers):
        return self._request("POST", f"{PREFIX}/psas/{psa_id}/execute",
                             {"closing_date": closing_date}, headers)

    def open_dd(self, psa_id, headers):
        return self._request("POST", f"{PREFIX}/psas/{psa_id}/open_dd", {}, headers)

    def lapse_dd(self, psa_id, headers):
        return self._request("POST", f"{PREFIX}/psas/{psa_id}/lapse_dd", {}, headers)

    def begin_closing(self, psa_id, headers):
        return self._request("POST", f"{PREFIX}/psas/{psa_id}/begin_closing", {}, headers)

    def terminate_psa(self, psa_id, reason, headers):
        return self._request("POST", f"{PREFIX}/psas/{psa_id}/terminate",
                             {"reason": reason}, headers)

    def record_closing(self, psa_id, headers):
        return self._request("POST", f"{PREFIX}/psas/{psa_id}/record_closing", {}, headers)

    def list_psa_deposits(self, psa_id, headers):
        return self._request("GET", f"{PREFIX}/psas/{psa_id}/deposits", headers=headers)

    def list_psa_dd_items(self, psa_id, headers):
        return self._request("GET", f"{PREFIX}/psas/{psa_id}/dd-items", headers=headers)

    def list_psa_statements(self, psa_id, headers):
        return self._request("GET", f"{PREFIX}/psas/{psa_id}/statements", headers=headers)

    def list_psa_escrows(self, psa_id, headers):
        return self._request("GET", f"{PREFIX}/psas/{psa_id}/escrows", headers=headers)

    # ------------------------------------------------------------------
    # Deposits
    # ------------------------------------------------------------------
    def post_deposit(self, deposit_id, headers):
        return self._request("POST", f"{PREFIX}/deposits/{deposit_id}/post", {}, headers)

    # ------------------------------------------------------------------
    # Due-diligence items
    # ------------------------------------------------------------------
    def create_dd_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dd-items", payload, headers)

    def respond_dd_item(self, item_id, decision, headers):
        return self._request("POST", f"{PREFIX}/dd-items/{item_id}/respond",
                             {"decision": decision}, headers)

    def supplement_dd_item(self, item_id, headers, requested_reduction_cents=None):
        payload = {}
        if requested_reduction_cents is not None:
            payload["requested_reduction_cents"] = requested_reduction_cents
        return self._request("POST", f"{PREFIX}/dd-items/{item_id}/supplement",
                             payload, headers)

    def rescind_dd_item(self, item_id, headers):
        return self._request("POST", f"{PREFIX}/dd-items/{item_id}/rescind", {}, headers)

    # ------------------------------------------------------------------
    # Loan payoffs / defeasance
    # ------------------------------------------------------------------
    def create_payoff(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payoffs", payload, headers)

    def confirm_payoff(self, payoff_id, headers):
        return self._request("POST", f"{PREFIX}/payoffs/{payoff_id}/confirm", {}, headers)

    def requote_payoff(self, payoff_id, payload, headers):
        return self._request("POST", f"{PREFIX}/payoffs/{payoff_id}/requote", payload, headers)

    def settle_payoff(self, payoff_id, headers):
        return self._request("POST", f"{PREFIX}/payoffs/{payoff_id}/settle", {}, headers)

    # ------------------------------------------------------------------
    # Closing statements
    # ------------------------------------------------------------------
    def create_statement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/statements", payload, headers)

    def submit_statement(self, statement_id, headers):
        return self._request("POST", f"{PREFIX}/statements/{statement_id}/submit", {}, headers)

    def approve_statement(self, statement_id, headers):
        return self._request("POST", f"{PREFIX}/statements/{statement_id}/approve", {}, headers)

    def dispute_statement(self, statement_id, headers):
        return self._request("POST", f"{PREFIX}/statements/{statement_id}/dispute", {}, headers)

    # ------------------------------------------------------------------
    # Escrow holdbacks
    # ------------------------------------------------------------------
    def get_escrow(self, escrow_id, headers):
        return self._request("GET", f"{PREFIX}/escrows/{escrow_id}", headers=headers)

    def release_escrow(self, escrow_id, headers, amount_cents=None):
        payload = {}
        if amount_cents is not None:
            payload["amount_cents"] = amount_cents
        return self._request("POST", f"{PREFIX}/escrows/{escrow_id}/release",
                             payload, headers)

    def file_claim(self, escrow_id, amount_cents, reason, headers):
        return self._request("POST", f"{PREFIX}/escrows/{escrow_id}/file_claim",
                             {"amount_cents": amount_cents, "reason": reason}, headers)

    def decide_claim(self, escrow_id, claim_id, decision, headers, paid_amount_cents=None):
        payload = {"claim_id": claim_id, "decision": decision}
        if paid_amount_cents is not None:
            payload["paid_amount_cents"] = paid_amount_cents
        return self._request("POST", f"{PREFIX}/escrows/{escrow_id}/decide_claim",
                             payload, headers)


api_client = ApiClient()
