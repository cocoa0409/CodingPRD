"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -----------------------------------------------------------------
    # Speakers
    # -----------------------------------------------------------------
    def create_speaker(self, payload, headers):
        return self._request("POST", "/speakers", payload, headers)

    def list_speakers(self, headers, params=None):
        return self._request("GET", "/speakers", headers=headers, params=params)

    def get_speaker(self, speaker_id, headers):
        return self._request("GET", f"/speakers/{speaker_id}", headers=headers)

    def update_speaker(self, speaker_id, payload, headers):
        return self._request("PATCH", f"/speakers/{speaker_id}", payload, headers)

    def get_speaker_performance(self, speaker_id, headers, params=None):
        return self._request(
            "GET", f"/speakers/{speaker_id}/performance", headers=headers, params=params
        )

    # -----------------------------------------------------------------
    # Clients
    # -----------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def update_client(self, client_id, payload, headers):
        return self._request("PATCH", f"/clients/{client_id}", payload, headers)

    # -----------------------------------------------------------------
    # Speaker calendar holds
    # -----------------------------------------------------------------
    def create_speaker_hold(self, payload, headers):
        return self._request("POST", "/speaker-holds", payload, headers)

    def list_speaker_holds(self, headers, params=None):
        return self._request("GET", "/speaker-holds", headers=headers, params=params)

    def get_speaker_hold(self, hold_id, headers):
        return self._request("GET", f"/speaker-holds/{hold_id}", headers=headers)

    # -----------------------------------------------------------------
    # Inquiries
    # -----------------------------------------------------------------
    def create_inquiry(self, payload, headers):
        return self._request("POST", "/inquiries", payload, headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/inquiries", headers=headers, params=params)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/inquiries/{inquiry_id}", headers=headers)

    def qualify_inquiry(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/inquiries/{inquiry_id}/qualify", payload, headers
        )

    def create_proposal(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/inquiries/{inquiry_id}/proposals", payload, headers
        )

    # -----------------------------------------------------------------
    # Proposals
    # -----------------------------------------------------------------
    def list_proposals(self, headers, params=None):
        return self._request("GET", "/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def present_proposal(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"/proposals/{proposal_id}/present", payload or {}, headers
        )

    def request_proposal_revision(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/proposals/{proposal_id}/request-revision", payload, headers
        )

    def decline_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/proposals/{proposal_id}/decline", payload, headers
        )

    def select_proposal_option(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/proposals/{proposal_id}/select", payload, headers
        )

    # -----------------------------------------------------------------
    # Proposal options
    # -----------------------------------------------------------------
    def create_proposal_option(self, payload, headers):
        return self._request("POST", "/proposal-options", payload, headers)

    def list_proposal_options(self, headers, params=None):
        return self._request("GET", "/proposal-options", headers=headers, params=params)

    def get_proposal_option(self, option_id, headers):
        return self._request("GET", f"/proposal-options/{option_id}", headers=headers)

    # -----------------------------------------------------------------
    # Engagements
    # -----------------------------------------------------------------
    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def confirm_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/confirm", payload or {}, headers
        )

    def decline_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/decline", payload, headers
        )

    def create_contract(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/contracts", payload, headers
        )

    def create_travel_expense(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/travel-expenses", payload, headers
        )

    def deliver_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST", f"/engagements/{engagement_id}/deliver", payload or {}, headers
        )

    def cancel_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/cancel", payload, headers
        )

    def create_feedback(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/feedback", payload, headers
        )

    def create_commission_adjustment(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/commission-adjustments",
            payload,
            headers,
        )

    # -----------------------------------------------------------------
    # Contracts
    # -----------------------------------------------------------------
    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def send_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/send", payload or {}, headers
        )

    def sign_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/sign", payload, headers)

    # -----------------------------------------------------------------
    # Travel expenses
    # -----------------------------------------------------------------
    def list_travel_expenses(self, headers, params=None):
        return self._request("GET", "/travel-expenses", headers=headers, params=params)

    def get_travel_expense(self, expense_id, headers):
        return self._request("GET", f"/travel-expenses/{expense_id}", headers=headers)

    def approve_travel_expense(self, expense_id, headers, payload=None):
        return self._request(
            "POST", f"/travel-expenses/{expense_id}/approve", payload or {}, headers
        )

    def reject_travel_expense(self, expense_id, payload, headers):
        return self._request(
            "POST", f"/travel-expenses/{expense_id}/reject", payload, headers
        )

    # -----------------------------------------------------------------
    # Feedback
    # -----------------------------------------------------------------
    def list_feedback(self, headers, params=None):
        return self._request("GET", "/feedback", headers=headers, params=params)

    def get_feedback(self, feedback_id, headers):
        return self._request("GET", f"/feedback/{feedback_id}", headers=headers)

    # -----------------------------------------------------------------
    # Invoices
    # -----------------------------------------------------------------
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def create_invoice_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/payments", payload, headers
        )

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    # -----------------------------------------------------------------
    # Remittances
    # -----------------------------------------------------------------
    def list_remittances(self, headers, params=None):
        return self._request("GET", "/remittances", headers=headers, params=params)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/remittances/{remittance_id}", headers=headers)

    def pay_remittance(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/remittances/{remittance_id}/pay", payload, headers
        )

    # -----------------------------------------------------------------
    # Exclusivity grants
    # -----------------------------------------------------------------
    def list_exclusivity_grants(self, headers, params=None):
        return self._request(
            "GET", "/exclusivity-grants", headers=headers, params=params
        )

    def get_exclusivity_grant(self, grant_id, headers):
        return self._request(
            "GET", f"/exclusivity-grants/{grant_id}", headers=headers
        )

    def waive_exclusivity_grant(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/exclusivity-grants/{grant_id}/waive", payload, headers
        )

    # -----------------------------------------------------------------
    # Circumvention claims
    # -----------------------------------------------------------------
    def create_circumvention_claim(self, payload, headers):
        return self._request("POST", "/circumvention-claims", payload, headers)

    def list_circumvention_claims(self, headers, params=None):
        return self._request(
            "GET", "/circumvention-claims", headers=headers, params=params
        )

    def get_circumvention_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/circumvention-claims/{claim_id}", headers=headers
        )

    def resolve_circumvention_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/circumvention-claims/{claim_id}/resolve", payload, headers
        )


api_client = ApiClient()
