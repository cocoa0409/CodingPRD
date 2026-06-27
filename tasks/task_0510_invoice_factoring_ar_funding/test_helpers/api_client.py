"""API client: one method per endpoint defined in the PRD.

All resources are flat collections under /factoring. The logical clock is
driven through the administrative /_clock/set_current_utc endpoint.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── FactoringProgram ────────────────────────────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/factoring/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/factoring/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/factoring/programs/{program_id}", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/factoring/programs/{program_id}/suspend", headers=headers)

    # ─── Client ──────────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/factoring/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/factoring/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/factoring/clients/{client_id}", headers=headers)

    def client_credit_decision(self, client_id, payload, headers):
        return self._request("POST", f"/factoring/clients/{client_id}/credit-decision", payload, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/factoring/clients/{client_id}/suspend", headers=headers)

    def reinstate_client(self, client_id, headers):
        return self._request("POST", f"/factoring/clients/{client_id}/reinstate", headers=headers)

    def close_client(self, client_id, headers):
        return self._request("POST", f"/factoring/clients/{client_id}/close", headers=headers)

    # ─── LedgerEntry ─────────────────────────────────────────────────────────
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/factoring/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/factoring/ledger-entries/{ledger_entry_id}", headers=headers)

    # ─── Debtor ──────────────────────────────────────────────────────────────
    def create_debtor(self, payload, headers):
        return self._request("POST", "/factoring/debtors", payload, headers)

    def list_debtors(self, headers, params=None):
        return self._request("GET", "/factoring/debtors", headers=headers, params=params)

    def get_debtor(self, debtor_id, headers):
        return self._request("GET", f"/factoring/debtors/{debtor_id}", headers=headers)

    def debtor_credit_decision(self, debtor_id, payload, headers):
        return self._request("POST", f"/factoring/debtors/{debtor_id}/credit-decision", payload, headers)

    def declare_insolvent(self, debtor_id, headers):
        return self._request("POST", f"/factoring/debtors/{debtor_id}/declare-insolvent", headers=headers)

    # ─── ClientDebtorRelationship ────────────────────────────────────────────
    def create_relationship(self, payload, headers):
        return self._request("POST", "/factoring/relationships", payload, headers)

    def list_relationships(self, headers, params=None):
        return self._request("GET", "/factoring/relationships", headers=headers, params=params)

    def get_relationship(self, relationship_id, headers):
        return self._request("GET", f"/factoring/relationships/{relationship_id}", headers=headers)

    def send_notice(self, relationship_id, headers):
        return self._request("POST", f"/factoring/relationships/{relationship_id}/send-notice", headers=headers)

    def suspend_relationship(self, relationship_id, headers):
        return self._request("POST", f"/factoring/relationships/{relationship_id}/suspend", headers=headers)

    def resume_relationship(self, relationship_id, headers):
        return self._request("POST", f"/factoring/relationships/{relationship_id}/resume", headers=headers)

    # ─── Invoice ─────────────────────────────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/factoring/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/factoring/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/factoring/invoices/{invoice_id}", headers=headers)

    def verify_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/factoring/invoices/{invoice_id}/verify", payload, headers)

    def reject_invoice(self, invoice_id, headers):
        return self._request("POST", f"/factoring/invoices/{invoice_id}/reject", headers=headers)

    # ─── Verification ────────────────────────────────────────────────────────
    def list_verifications(self, headers, params=None):
        return self._request("GET", "/factoring/verifications", headers=headers, params=params)

    def get_verification(self, verification_id, headers):
        return self._request("GET", f"/factoring/verifications/{verification_id}", headers=headers)

    # ─── CollectionPosting ───────────────────────────────────────────────────
    def create_posting(self, invoice_id, payload, headers):
        return self._request("POST", f"/factoring/invoices/{invoice_id}/postings", payload, headers)

    def list_postings(self, headers, params=None):
        return self._request("GET", "/factoring/collection-postings", headers=headers, params=params)

    def get_posting(self, posting_id, headers):
        return self._request("GET", f"/factoring/collection-postings/{posting_id}", headers=headers)

    def reverse_posting(self, posting_id, headers):
        return self._request("POST", f"/factoring/postings/{posting_id}/reverse", headers=headers)

    # ─── Adjustment ──────────────────────────────────────────────────────────
    def create_adjustment(self, invoice_id, payload, headers):
        return self._request("POST", f"/factoring/invoices/{invoice_id}/adjustments", payload, headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/factoring/adjustments", headers=headers, params=params)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/factoring/adjustments/{adjustment_id}", headers=headers)

    # ─── Invoice terminalization ─────────────────────────────────────────────
    def close_collection(self, invoice_id, headers):
        return self._request("POST", f"/factoring/invoices/{invoice_id}/close-collection", headers=headers)

    def buyback_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/factoring/invoices/{invoice_id}/buyback", payload, headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"/factoring/invoices/{invoice_id}/write-off", headers=headers)

    # ─── Buyback ─────────────────────────────────────────────────────────────
    def list_buybacks(self, headers, params=None):
        return self._request("GET", "/factoring/buybacks", headers=headers, params=params)

    def get_buyback(self, buyback_id, headers):
        return self._request("GET", f"/factoring/buybacks/{buyback_id}", headers=headers)

    # ─── Settlement ──────────────────────────────────────────────────────────
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/factoring/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/factoring/settlements/{settlement_id}", headers=headers)

    # ─── PurchaseBatch ───────────────────────────────────────────────────────
    def create_batch(self, payload, headers):
        return self._request("POST", "/factoring/purchase-batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/factoring/purchase-batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/factoring/purchase-batches/{batch_id}", headers=headers)

    def fund_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/factoring/purchase-batches/{batch_id}/fund", payload, headers)

    # ─── Logical clock (test-driving) ────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
