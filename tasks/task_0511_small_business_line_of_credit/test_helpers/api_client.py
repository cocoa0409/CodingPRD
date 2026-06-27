"""API client: one method per endpoint defined in the Small-Business Line of Credit PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Merchant ───────────────────────────────────────────────
    def create_merchant(self, payload, headers=None):
        return self._request("POST", "/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def blocklist_merchant(self, merchant_id, headers, payload=None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/blocklist", payload or {}, headers
        )

    # ─── BankFeed ───────────────────────────────────────────────
    def create_bank_feed(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/merchants/{merchant_id}/bank-feeds", payload, headers
        )

    def list_bank_feeds(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/bank-feeds", headers=headers, params=params
        )

    def mark_bank_feed_stale(self, bank_feed_id, headers, payload=None):
        return self._request(
            "POST", f"/bank-feeds/{bank_feed_id}/mark-stale", payload or {}, headers
        )

    # ─── Application ────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/submit", payload or {}, headers
        )

    def approve_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/approve", payload or {}, headers
        )

    def request_revision_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/applications/{application_id}/request-revision",
            payload or {},
            headers,
        )

    def decline_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/decline", payload, headers
        )

    # ─── CreditLine ─────────────────────────────────────────────
    def create_credit_line(self, payload, headers):
        return self._request("POST", "/credit-lines", payload, headers)

    def get_credit_line(self, credit_line_id, headers):
        return self._request("GET", f"/credit-lines/{credit_line_id}", headers=headers)

    def list_credit_lines(self, headers, params=None):
        return self._request("GET", "/credit-lines", headers=headers, params=params)

    def freeze_credit_line(self, credit_line_id, headers, payload=None):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/freeze", payload or {}, headers
        )

    def unfreeze_credit_line(self, credit_line_id, headers, payload=None):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/unfreeze", payload or {}, headers
        )

    def declare_default(self, credit_line_id, payload, headers):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/declare-default", payload, headers
        )

    def charge_off(self, credit_line_id, payload, headers):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/charge-off", payload, headers
        )

    def close_credit_line(self, credit_line_id, headers, payload=None):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/close", payload or {}, headers
        )

    # ─── Draw ───────────────────────────────────────────────────
    def create_draw(self, credit_line_id, payload, headers):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/draws", payload, headers
        )

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"/draws/{draw_id}", headers=headers)

    def list_draws(self, credit_line_id, headers, params=None):
        return self._request(
            "GET", f"/credit-lines/{credit_line_id}/draws", headers=headers, params=params
        )

    # ─── Remittance ─────────────────────────────────────────────
    def create_remittance(self, credit_line_id, payload, headers):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/remittances", payload, headers
        )

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/remittances/{remittance_id}", headers=headers)

    def list_remittances(self, credit_line_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit-lines/{credit_line_id}/remittances",
            headers=headers,
            params=params,
        )

    def settle_remittance(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/remittances/{remittance_id}/settle", payload, headers
        )

    def cancel_remittance(self, remittance_id, headers, payload=None):
        return self._request(
            "POST", f"/remittances/{remittance_id}/cancel", payload or {}, headers
        )

    # ─── LineIncreaseRequest ────────────────────────────────────
    def create_line_increase_request(self, credit_line_id, payload, headers):
        return self._request(
            "POST",
            f"/credit-lines/{credit_line_id}/line-increase-requests",
            payload,
            headers,
        )

    def get_line_increase_request(self, lir_id, headers):
        return self._request(
            "GET", f"/line-increase-requests/{lir_id}", headers=headers
        )

    def list_line_increase_requests_for_line(self, credit_line_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit-lines/{credit_line_id}/line-increase-requests",
            headers=headers,
            params=params,
        )

    def list_line_increase_requests(self, headers, params=None):
        return self._request(
            "GET", "/line-increase-requests", headers=headers, params=params
        )

    def approve_line_increase_request(self, lir_id, payload, headers):
        return self._request(
            "POST", f"/line-increase-requests/{lir_id}/approve", payload, headers
        )

    def deny_line_increase_request(self, lir_id, payload, headers):
        return self._request(
            "POST", f"/line-increase-requests/{lir_id}/deny", payload, headers
        )

    # ─── RenewalOffer ───────────────────────────────────────────
    def create_renewal_offer(self, credit_line_id, payload, headers):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/renewal-offers", payload, headers
        )

    def get_renewal_offer(self, offer_id, headers):
        return self._request("GET", f"/renewal-offers/{offer_id}", headers=headers)

    def list_renewal_offers(self, credit_line_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit-lines/{credit_line_id}/renewal-offers",
            headers=headers,
            params=params,
        )

    def accept_renewal_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/renewal-offers/{offer_id}/accept", payload or {}, headers
        )

    def decline_renewal_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/renewal-offers/{offer_id}/decline", payload or {}, headers
        )

    # ─── Statement ──────────────────────────────────────────────
    def create_statement(self, credit_line_id, payload, headers):
        return self._request(
            "POST", f"/credit-lines/{credit_line_id}/statements", payload, headers
        )

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_statements(self, credit_line_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit-lines/{credit_line_id}/statements",
            headers=headers,
            params=params,
        )

    def finalize_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"/statements/{statement_id}/finalize", payload or {}, headers
        )

    # ─── LedgerEntry (read-only) ────────────────────────────────
    def list_ledger_entries_for_line(self, credit_line_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit-lines/{credit_line_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ─── Ops / test-driving ─────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def expire_applications(self, headers, payload=None):
        return self._request(
            "POST", "/_ops/expire-applications", payload or {}, headers
        )

    def expire_renewals(self, headers, payload=None):
        return self._request("POST", "/_ops/expire-renewals", payload or {}, headers)

    # ─── Raw helper for header-less / malformed-auth tests ──────
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
