"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
envelope, headers, and HTTP plumbing. Every method takes a `headers` dict
(built by test_users.build_user_headers / make_*_headers) so the caller's role
and X-User-ID travel with the request.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Clock (test-driving) ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ─── Consignor ──────────────────────────────────────────────────────────
    def create_consignor(self, payload, headers):
        return self._request("POST", "/consignors", payload, headers=headers)

    def get_consignor(self, consignor_id, headers):
        return self._request("GET", f"/consignors/{consignor_id}", headers=headers)

    def list_consignors(self, headers, params=None):
        return self._request("GET", "/consignors", headers=headers, params=params)

    def update_consignor(self, consignor_id, payload, headers):
        return self._request("PATCH", f"/consignors/{consignor_id}", payload, headers=headers)

    def list_consignor_agreements(self, consignor_id, headers, params=None):
        return self._request("GET", f"/consignors/{consignor_id}/agreements",
                             headers=headers, params=params)

    def list_consignor_ledger_entries(self, consignor_id, headers, params=None):
        return self._request("GET", f"/consignors/{consignor_id}/ledger-entries",
                             headers=headers, params=params)

    def list_consignor_store_credit_transactions(self, consignor_id, headers, params=None):
        return self._request("GET", f"/consignors/{consignor_id}/store-credit/transactions",
                             headers=headers, params=params)

    def list_consignor_sale_lines(self, consignor_id, headers, params=None):
        return self._request("GET", f"/consignors/{consignor_id}/sale-lines",
                             headers=headers, params=params)

    def redeem_store_credit(self, consignor_id, payload, headers):
        return self._request("POST", f"/consignors/{consignor_id}/store-credit/redeem",
                             payload, headers=headers)

    # ─── MarkdownSchedule ───────────────────────────────────────────────────
    def create_markdown_schedule(self, payload, headers):
        return self._request("POST", "/markdown-schedules", payload, headers=headers)

    def get_markdown_schedule(self, schedule_id, headers):
        return self._request("GET", f"/markdown-schedules/{schedule_id}", headers=headers)

    def archive_markdown_schedule(self, schedule_id, headers):
        return self._request("POST", f"/markdown-schedules/{schedule_id}/archive",
                             {}, headers=headers)

    # ─── ConsignorAgreement ─────────────────────────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers=headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/terminate",
                             {}, headers=headers)

    def list_agreement_intake_batches(self, agreement_id, headers, params=None):
        return self._request("GET", f"/agreements/{agreement_id}/intake-batches",
                             headers=headers, params=params)

    # ─── IntakeBatch ────────────────────────────────────────────────────────
    def create_intake_batch(self, payload, headers):
        return self._request("POST", "/intake-batches", payload, headers=headers)

    def get_intake_batch(self, batch_id, headers):
        return self._request("GET", f"/intake-batches/{batch_id}", headers=headers)

    def close_intake_batch(self, batch_id, headers):
        return self._request("POST", f"/intake-batches/{batch_id}/close", {}, headers=headers)

    def list_batch_items(self, batch_id, headers, params=None):
        return self._request("GET", f"/intake-batches/{batch_id}/items",
                             headers=headers, params=params)

    # ─── Item ───────────────────────────────────────────────────────────────
    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers=headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/items", headers=headers, params=params)

    def grade_item(self, item_id, payload, headers):
        return self._request("POST", f"/items/{item_id}/grade", payload, headers=headers)

    def list_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/list", {}, headers=headers)

    def pull_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/pull", {}, headers=headers)

    def dispose_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/dispose", {}, headers=headers)

    def list_item_authentication_reviews(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/authentication-reviews",
                             headers=headers, params=params)

    def get_item_donation_record(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/donation-record",
                             headers=headers, params=params)

    def list_item_sale_lines(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/sale-lines",
                             headers=headers, params=params)

    # ─── AuthenticationReview ───────────────────────────────────────────────
    def create_authentication_review(self, payload, headers):
        return self._request("POST", "/authentication-reviews", payload, headers=headers)

    def get_authentication_review(self, review_id, headers):
        return self._request("GET", f"/authentication-reviews/{review_id}", headers=headers)

    def review_verdict(self, review_id, payload, headers):
        return self._request("POST", f"/authentication-reviews/{review_id}/verdict",
                             payload, headers=headers)

    def review_dispute(self, review_id, headers):
        return self._request("POST", f"/authentication-reviews/{review_id}/dispute",
                             {}, headers=headers)

    def review_reopen(self, review_id, headers):
        return self._request("POST", f"/authentication-reviews/{review_id}/reopen",
                             {}, headers=headers)

    # ─── Sale ───────────────────────────────────────────────────────────────
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers=headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def list_sale_lines(self, sale_id, headers, params=None):
        return self._request("GET", f"/sales/{sale_id}/lines", headers=headers, params=params)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers=headers)

    # ─── DailySettlement ────────────────────────────────────────────────────
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers=headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/finalize",
                             payload, headers=headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/void", {}, headers=headers)

    def list_settlement_sales(self, settlement_id, headers, params=None):
        return self._request("GET", f"/settlements/{settlement_id}/sales",
                             headers=headers, params=params)

    def list_settlement_ledger_entries(self, settlement_id, headers, params=None):
        return self._request("GET", f"/settlements/{settlement_id}/ledger-entries",
                             headers=headers, params=params)

    # ─── DonationRecord ─────────────────────────────────────────────────────
    def get_donation_record(self, record_id, headers):
        return self._request("GET", f"/donation-records/{record_id}", headers=headers)

    def list_donation_records(self, headers, params=None):
        return self._request("GET", "/donation-records", headers=headers, params=params)


api_client = ApiClient()
