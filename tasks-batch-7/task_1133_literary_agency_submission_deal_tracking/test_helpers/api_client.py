"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Agency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def close_period(self, agency_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/close-period", headers=headers)

    def close_books(self, agency_id, headers):
        return self._request("POST", f"/agencies/{agency_id}/close-books", headers=headers)

    # --- Agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def deactivate_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/deactivate", headers=headers)

    def activate_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/activate", headers=headers)

    # --- Authors ---
    def create_author(self, payload, headers):
        return self._request("POST", "/authors", payload, headers)

    def get_author(self, author_id, headers):
        return self._request("GET", f"/authors/{author_id}", headers=headers)

    def list_authors(self, headers, params=None):
        return self._request("GET", "/authors", headers=headers, params=params)

    # --- Editors ---
    def create_editor(self, payload, headers):
        return self._request("POST", "/editors", payload, headers)

    def get_editor(self, editor_id, headers):
        return self._request("GET", f"/editors/{editor_id}", headers=headers)

    def list_editors(self, headers, params=None):
        return self._request("GET", "/editors", headers=headers, params=params)

    def deactivate_editor(self, editor_id, headers):
        return self._request("POST", f"/editors/{editor_id}/deactivate", headers=headers)

    def activate_editor(self, editor_id, headers):
        return self._request("POST", f"/editors/{editor_id}/activate", headers=headers)

    # --- QueryLetters ---
    def create_query_letter(self, payload, headers):
        return self._request("POST", "/query-letters", payload, headers)

    def get_query_letter(self, query_letter_id, headers):
        return self._request("GET", f"/query-letters/{query_letter_id}", headers=headers)

    def list_query_letters(self, headers, params=None):
        return self._request("GET", "/query-letters", headers=headers, params=params)

    def assign_query(self, query_letter_id, payload, headers):
        return self._request("POST", f"/query-letters/{query_letter_id}/assign", payload, headers)

    def request_manuscript(self, query_letter_id, payload, headers):
        return self._request("POST", f"/query-letters/{query_letter_id}/request-manuscript", payload, headers)

    def reject_query(self, query_letter_id, headers):
        return self._request("POST", f"/query-letters/{query_letter_id}/reject", headers=headers)

    def withdraw_query(self, query_letter_id, headers):
        return self._request("POST", f"/query-letters/{query_letter_id}/withdraw", headers=headers)

    # --- Manuscripts ---
    def get_manuscript(self, manuscript_id, headers):
        return self._request("GET", f"/manuscripts/{manuscript_id}", headers=headers)

    def list_manuscripts(self, headers, params=None):
        return self._request("GET", "/manuscripts", headers=headers, params=params)

    def assign_reader(self, manuscript_id, payload, headers):
        return self._request("POST", f"/manuscripts/{manuscript_id}/assign-reader", payload, headers)

    def evaluate_manuscript(self, manuscript_id, payload, headers):
        return self._request("POST", f"/manuscripts/{manuscript_id}/evaluate", payload, headers)

    def request_revision(self, manuscript_id, headers):
        return self._request("POST", f"/manuscripts/{manuscript_id}/request-revision", headers=headers)

    def resubmit_manuscript(self, manuscript_id, headers):
        return self._request("POST", f"/manuscripts/{manuscript_id}/resubmit", headers=headers)

    def accept_manuscript(self, manuscript_id, headers):
        return self._request("POST", f"/manuscripts/{manuscript_id}/accept", headers=headers)

    def decline_manuscript(self, manuscript_id, headers):
        return self._request("POST", f"/manuscripts/{manuscript_id}/decline", headers=headers)

    # --- ClientAgreements ---
    def create_client_agreement(self, payload, headers):
        return self._request("POST", "/client-agreements", payload, headers)

    def get_client_agreement(self, agreement_id, headers):
        return self._request("GET", f"/client-agreements/{agreement_id}", headers=headers)

    def list_client_agreements(self, headers, params=None):
        return self._request("GET", "/client-agreements", headers=headers, params=params)

    def offer_agreement(self, agreement_id, headers):
        return self._request("POST", f"/client-agreements/{agreement_id}/offer", headers=headers)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/client-agreements/{agreement_id}/sign", headers=headers)

    def decline_agreement(self, agreement_id, headers):
        return self._request("POST", f"/client-agreements/{agreement_id}/decline", headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/client-agreements/{agreement_id}/terminate", headers=headers)

    # --- SubmissionRounds ---
    def create_submission_round(self, payload, headers):
        return self._request("POST", "/submission-rounds", payload, headers)

    def get_submission_round(self, round_id, headers):
        return self._request("GET", f"/submission-rounds/{round_id}", headers=headers)

    def list_submission_rounds(self, headers, params=None):
        return self._request("GET", "/submission-rounds", headers=headers, params=params)

    def open_submission_round(self, round_id, payload, headers):
        return self._request("POST", f"/submission-rounds/{round_id}/open", payload, headers)

    def close_submission_round(self, round_id, headers):
        return self._request("POST", f"/submission-rounds/{round_id}/close", headers=headers)

    # --- Submissions ---
    def create_submission(self, payload, headers):
        return self._request("POST", "/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def send_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/send", headers=headers)

    def mark_under_consideration(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/mark-under-consideration", headers=headers)

    def pass_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/pass", headers=headers)

    def withdraw_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/withdraw", headers=headers)

    # --- Offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def negotiate_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/negotiate", headers=headers)

    def revise_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/revise", payload, headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", headers=headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", headers=headers)

    def editor_withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/editor-withdraw", headers=headers)

    # --- Deals ---
    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def patch_deal(self, deal_id, payload, headers):
        return self._request("PATCH", f"/deals/{deal_id}", payload, headers)

    def execute_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/execute", payload, headers)

    def terminate_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/terminate", headers=headers)

    # --- RoyaltyStatements ---
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/royalty-statements/{statement_id}", headers=headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/royalty-statements", headers=headers, params=params)

    def reconcile_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/reconcile", headers=headers)

    def open_audit(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/open-audit", headers=headers)

    def resolve_audit(self, statement_id, payload, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/resolve-audit", payload, headers)

    def clear_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/clear", headers=headers)

    # --- AdvanceInstallments ---
    def get_advance_installment(self, installment_id, headers):
        return self._request("GET", f"/advance-installments/{installment_id}", headers=headers)

    def list_advance_installments(self, headers, params=None):
        return self._request("GET", "/advance-installments", headers=headers, params=params)

    def mark_installment_paid(self, installment_id, headers):
        return self._request("POST", f"/advance-installments/{installment_id}/mark-paid", headers=headers)


api_client = ApiClient()
