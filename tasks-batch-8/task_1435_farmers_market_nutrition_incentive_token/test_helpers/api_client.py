"""API client: one method per endpoint defined in the PRD.

Every write endpoint requires an Idempotency-Key header (PRD "Idempotency of
Write Operations"), so all POST helpers inject a fresh key by default; tests
that exercise idempotency pass an explicit ``idempotency_key``. ``post_raw``
sends a POST without injecting the key (used by the missing-key test).
"""
import uuid

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -- low-level helpers -------------------------------------------------
    def _post(self, path, payload=None, headers=None, idempotency_key=None):
        hdrs = dict(headers or {})
        if idempotency_key is None:
            idempotency_key = f"idem-{uuid.uuid4()}"
        hdrs["Idempotency-Key"] = idempotency_key
        return self._request("POST", path, payload if payload is not None else {}, hdrs)

    def post_raw(self, path, payload=None, headers=None):
        """POST without Idempotency-Key injection (negative-path tests)."""
        return self._request("POST", path, payload if payload is not None else {}, headers or {})

    # -- logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers=None, idempotency_key=None):
        return self._post("/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers, idempotency_key)

    # -- programs -----------------------------------------------------------
    def create_program(self, payload, headers=None, idempotency_key=None):
        return self._post("/programs", payload, headers, idempotency_key)

    def get_program(self, program_id, headers=None):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def get_funder_report(self, program_id, headers=None, params=None):
        return self._request("GET", f"/programs/{program_id}/funder-report", headers=headers, params=params)

    def list_program_markets(self, program_id, headers=None, params=None):
        return self._request("GET", f"/programs/{program_id}/markets", headers=headers, params=params)

    def list_program_shoppers(self, program_id, headers=None, params=None):
        return self._request("GET", f"/programs/{program_id}/shoppers", headers=headers, params=params)

    # -- markets ------------------------------------------------------------
    def create_market(self, payload, headers=None, idempotency_key=None):
        return self._post("/markets", payload, headers, idempotency_key)

    # -- vendors ------------------------------------------------------------
    def create_vendor(self, payload, headers=None, idempotency_key=None):
        return self._post("/vendors", payload, headers, idempotency_key)

    def get_vendor(self, vendor_id, headers=None):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers=None, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def approve_vendor(self, vendor_id, headers=None, idempotency_key=None):
        return self._post(f"/vendors/{vendor_id}/approve", {}, headers, idempotency_key)

    def set_vendor_status(self, vendor_id, to, headers=None, idempotency_key=None):
        return self._post(f"/vendors/{vendor_id}/set-status", {"to": to}, headers, idempotency_key)

    # -- shoppers -----------------------------------------------------------
    def create_shopper(self, payload, headers=None, idempotency_key=None):
        return self._post("/shoppers", payload, headers, idempotency_key)

    def get_shopper(self, shopper_id, headers=None):
        return self._request("GET", f"/shoppers/{shopper_id}", headers=headers)

    def verify_shopper(self, shopper_id, headers=None, idempotency_key=None):
        return self._post(f"/shoppers/{shopper_id}/verify", {}, headers, idempotency_key)

    def suspend_shopper(self, shopper_id, headers=None, idempotency_key=None):
        return self._post(f"/shoppers/{shopper_id}/suspend", {}, headers, idempotency_key)

    # -- market days --------------------------------------------------------
    def create_market_day(self, payload, headers=None, idempotency_key=None):
        return self._post("/market-days", payload, headers, idempotency_key)

    def get_market_day(self, market_day_id, headers=None):
        return self._request("GET", f"/market-days/{market_day_id}", headers=headers)

    def list_market_days(self, headers=None, params=None):
        return self._request("GET", "/market-days", headers=headers, params=params)

    def open_market_day(self, market_day_id, headers=None, idempotency_key=None):
        return self._post(f"/market-days/{market_day_id}/open", {}, headers, idempotency_key)

    def close_market_day(self, market_day_id, headers=None, idempotency_key=None):
        return self._post(f"/market-days/{market_day_id}/close", {}, headers, idempotency_key)

    def reconcile_market_day(self, market_day_id, headers=None, payload=None, idempotency_key=None):
        return self._post(f"/market-days/{market_day_id}/reconcile",
                          payload if payload is not None else {}, headers, idempotency_key)

    # -- token batches ------------------------------------------------------
    def create_token_batch(self, payload, headers=None, idempotency_key=None):
        return self._post("/token-batches", payload, headers, idempotency_key)

    def get_token_batch(self, batch_id, headers=None):
        return self._request("GET", f"/token-batches/{batch_id}", headers=headers)

    def list_token_batches(self, headers=None, params=None):
        return self._request("GET", "/token-batches", headers=headers, params=params)

    def activate_token_batch(self, batch_id, headers=None, idempotency_key=None):
        return self._post(f"/token-batches/{batch_id}/activate", {}, headers, idempotency_key)

    def recall_token_batch(self, batch_id, headers=None, idempotency_key=None):
        return self._post(f"/token-batches/{batch_id}/recall", {}, headers, idempotency_key)

    # -- issuances ----------------------------------------------------------
    def create_issuance(self, payload, headers=None, idempotency_key=None):
        return self._post("/issuances", payload, headers, idempotency_key)

    def get_issuance(self, issuance_id, headers=None):
        return self._request("GET", f"/issuances/{issuance_id}", headers=headers)

    def list_issuances(self, headers=None, params=None):
        return self._request("GET", "/issuances", headers=headers, params=params)

    def void_issuance(self, issuance_id, headers=None, idempotency_key=None):
        return self._post(f"/issuances/{issuance_id}/void", {}, headers, idempotency_key)

    # -- tokens -------------------------------------------------------------
    def get_token(self, token_id, headers=None):
        return self._request("GET", f"/tokens/{token_id}", headers=headers)

    def list_tokens(self, headers=None, params=None):
        return self._request("GET", "/tokens", headers=headers, params=params)

    def redeem_token(self, serial_number, headers=None, idempotency_key=None):
        return self._post("/tokens/redeem", {"serial_number": serial_number}, headers, idempotency_key)

    def reverse_redemption(self, token_id, headers=None, idempotency_key=None):
        return self._post(f"/tokens/{token_id}/reverse-redemption", {}, headers, idempotency_key)

    # -- redemption submissions --------------------------------------------
    def create_submission(self, payload, headers=None, idempotency_key=None):
        return self._post("/redemption-submissions", payload, headers, idempotency_key)

    def get_submission(self, submission_id, headers=None):
        return self._request("GET", f"/redemption-submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers=None, params=None):
        return self._request("GET", "/redemption-submissions", headers=headers, params=params)

    def verify_submission(self, submission_id, outcome, headers=None, idempotency_key=None):
        return self._post(f"/redemption-submissions/{submission_id}/verify",
                          {"outcome": outcome}, headers, idempotency_key)

    def resubmit_submission(self, submission_id, token_ids, headers=None, idempotency_key=None):
        return self._post(f"/redemption-submissions/{submission_id}/resubmit",
                          {"token_ids": token_ids}, headers, idempotency_key)

    def decide_submission(self, submission_id, outcome, headers=None, idempotency_key=None):
        return self._post(f"/redemption-submissions/{submission_id}/decide",
                          {"outcome": outcome}, headers, idempotency_key)

    # -- fraud cases --------------------------------------------------------
    def create_fraud_case(self, payload, headers=None, idempotency_key=None):
        return self._post("/fraud-cases", payload, headers, idempotency_key)

    def get_fraud_case(self, case_id, headers=None):
        return self._request("GET", f"/fraud-cases/{case_id}", headers=headers)

    def list_fraud_cases(self, headers=None, params=None):
        return self._request("GET", "/fraud-cases", headers=headers, params=params)

    def confirm_fraud_case(self, case_id, headers=None, idempotency_key=None):
        return self._post(f"/fraud-cases/{case_id}/confirm", {}, headers, idempotency_key)

    def clear_fraud_case(self, case_id, headers=None, idempotency_key=None):
        return self._post(f"/fraud-cases/{case_id}/clear", {}, headers, idempotency_key)

    # -- settlement runs ----------------------------------------------------
    def create_settlement_run(self, payload, headers=None, idempotency_key=None):
        return self._post("/settlement-runs", payload, headers, idempotency_key)

    def get_settlement_run(self, run_id, headers=None):
        return self._request("GET", f"/settlement-runs/{run_id}", headers=headers)

    def list_settlement_runs(self, headers=None, params=None):
        return self._request("GET", "/settlement-runs", headers=headers, params=params)


api_client = ApiClient()
