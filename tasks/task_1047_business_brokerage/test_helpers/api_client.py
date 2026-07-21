"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Actors ----
    def create_broker(self, payload, headers):
        return self._request("POST", "/brokerage/brokers", payload, headers)

    def create_seller(self, payload, headers):
        return self._request("POST", "/brokerage/sellers", payload, headers)

    def create_buyer(self, payload, headers):
        return self._request("POST", "/brokerage/buyers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/brokerage/brokers/{broker_id}", headers=headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/brokerage/buyers/{buyer_id}", headers=headers)

    # ---- Listing ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/brokerage/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/brokerage/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/brokerage/listings/{listing_id}", headers=headers)

    def activate_listing(self, listing_id, headers):
        return self._request("POST", f"/brokerage/listings/{listing_id}/activate", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/brokerage/listings/{listing_id}/withdraw", {}, headers)

    # ---- CIM ----
    def create_cim(self, listing_id, payload, headers):
        return self._request("POST", f"/brokerage/listings/{listing_id}/cims", payload, headers)

    def list_cims(self, listing_id, headers, params=None):
        return self._request("GET", f"/brokerage/listings/{listing_id}/cims", headers=headers, params=params)

    def publish_cim(self, cim_id, headers):
        return self._request("POST", f"/brokerage/cims/{cim_id}/publish", {}, headers)

    # ---- NDA ----
    def sign_nda(self, listing_id, headers, payload=None):
        return self._request("POST", f"/brokerage/listings/{listing_id}/ndas", payload or {}, headers)

    def list_listing_ndas(self, listing_id, headers, params=None):
        return self._request("GET", f"/brokerage/listings/{listing_id}/ndas", headers=headers, params=params)

    def list_buyer_ndas(self, buyer_id, headers, params=None):
        return self._request("GET", f"/brokerage/buyers/{buyer_id}/ndas", headers=headers, params=params)

    # ---- Data-room documents ----
    def upload_document(self, listing_id, payload, headers):
        return self._request("POST", f"/brokerage/listings/{listing_id}/documents", payload, headers)

    def list_documents(self, listing_id, headers, params=None):
        return self._request("GET", f"/brokerage/listings/{listing_id}/documents", headers=headers, params=params)

    # ---- Management meetings ----
    def schedule_meeting(self, listing_id, payload, headers):
        return self._request("POST", f"/brokerage/listings/{listing_id}/meetings", payload, headers)

    def list_listing_meetings(self, listing_id, headers, params=None):
        return self._request("GET", f"/brokerage/listings/{listing_id}/meetings", headers=headers, params=params)

    def list_buyer_meetings(self, buyer_id, headers, params=None):
        return self._request("GET", f"/brokerage/buyers/{buyer_id}/meetings", headers=headers, params=params)

    # ---- Deal ----
    def create_deal(self, payload, headers):
        return self._request("POST", "/brokerage/deals", payload, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/brokerage/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/brokerage/deals/{deal_id}", headers=headers)

    def qualify_deal(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/qualify", {}, headers)

    def open_diligence(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/open-diligence", {}, headers)

    def enter_financing(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/enter-financing", {}, headers)

    def withdraw_deal(self, deal_id, headers, payload=None):
        return self._request("POST", f"/brokerage/deals/{deal_id}/withdraw", payload or {}, headers)

    def record_earnout_period(self, deal_id, payload, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/record-earnout-period", payload, headers)

    # ---- LOI ----
    def submit_loi(self, deal_id, payload, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/lois", payload, headers)

    def list_lois(self, deal_id, headers, params=None):
        return self._request("GET", f"/brokerage/deals/{deal_id}/lois", headers=headers, params=params)

    def counter_loi(self, loi_id, payload, headers):
        return self._request("POST", f"/brokerage/lois/{loi_id}/counter", payload, headers)

    def revise_loi(self, loi_id, payload, headers):
        return self._request("POST", f"/brokerage/lois/{loi_id}/revise", payload, headers)

    def accept_loi(self, loi_id, headers):
        return self._request("POST", f"/brokerage/lois/{loi_id}/accept", {}, headers)

    def reject_loi(self, loi_id, headers):
        return self._request("POST", f"/brokerage/lois/{loi_id}/reject", {}, headers)

    def withdraw_loi(self, loi_id, headers):
        return self._request("POST", f"/brokerage/lois/{loi_id}/withdraw", {}, headers)

    # ---- SBA financing ----
    def submit_loan_application(self, deal_id, payload, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/loan-applications", payload, headers)

    def list_loan_applications(self, deal_id, headers, params=None):
        return self._request("GET", f"/brokerage/deals/{deal_id}/loan-applications", headers=headers, params=params)

    def decide_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/brokerage/loan-applications/{loan_id}/decision", payload, headers)

    def finalize_loan_conditions(self, loan_id, payload, headers):
        return self._request("POST", f"/brokerage/loan-applications/{loan_id}/finalize-conditions", payload, headers)

    # ---- Escrow / closing ----
    def open_escrow(self, deal_id, payload, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/escrow", payload, headers)

    def list_escrow(self, deal_id, headers, params=None):
        return self._request("GET", f"/brokerage/deals/{deal_id}/escrow", headers=headers, params=params)

    def deposit_escrow(self, escrow_id, payload, headers):
        return self._request("POST", f"/brokerage/escrow-accounts/{escrow_id}/deposit", payload, headers)

    def close_escrow(self, escrow_id, headers):
        return self._request("POST", f"/brokerage/escrow-accounts/{escrow_id}/close", {}, headers)


api_client = ApiClient()
