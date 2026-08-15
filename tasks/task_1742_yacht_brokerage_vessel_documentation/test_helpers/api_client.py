"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- brokerages ---
    def create_brokerage(self, payload, headers):
        return self._request("POST", "/yacht/brokerages", payload, headers)

    def get_brokerage(self, brokerage_id, headers):
        return self._request("GET", f"/yacht/brokerages/{brokerage_id}", headers=headers)

    # --- agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/yacht/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/yacht/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/yacht/agents", headers=headers, params=params)

    # --- clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/yacht/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/yacht/clients/{client_id}", headers=headers)

    # --- vessels ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/yacht/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/yacht/vessels/{vessel_id}", headers=headers)

    def update_vessel(self, vessel_id, payload, headers):
        return self._request("PUT", f"/yacht/vessels/{vessel_id}", payload, headers)

    # --- liens ---
    def list_liens(self, vessel_id, headers):
        return self._request("GET", f"/yacht/vessels/{vessel_id}/liens", headers=headers)

    def create_lien(self, vessel_id, payload, headers):
        return self._request("POST", f"/yacht/vessels/{vessel_id}/liens", payload, headers)

    def release_lien(self, lien_id, payload, headers):
        return self._request("POST", f"/yacht/liens/{lien_id}/release", payload, headers)

    # --- documentation records ---
    def list_documentation_records(self, vessel_id, headers):
        return self._request(
            "GET", f"/yacht/vessels/{vessel_id}/documentation-records", headers=headers
        )

    def create_documentation_record(self, vessel_id, payload, headers):
        return self._request(
            "POST", f"/yacht/vessels/{vessel_id}/documentation-records", payload, headers
        )

    # --- listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/yacht/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/yacht/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/yacht/listings", headers=headers, params=params)

    def activate_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/yacht/listings/{listing_id}/activate", headers=headers
        )

    def suspend_listing(self, listing_id, headers):
        return self._request("POST", f"/yacht/listings/{listing_id}/suspend", headers=headers)

    def cancel_listing(self, listing_id, headers):
        return self._request("POST", f"/yacht/listings/{listing_id}/cancel", headers=headers)

    def update_listing_price(self, listing_id, payload, headers):
        return self._request("PUT", f"/yacht/listings/{listing_id}/price", payload, headers)

    def create_syndication_event(self, listing_id, payload, headers):
        return self._request(
            "POST", f"/yacht/listings/{listing_id}/syndication-events", payload, headers
        )

    def list_syndication_events(self, listing_id, headers):
        return self._request(
            "GET", f"/yacht/listings/{listing_id}/syndication-events", headers=headers
        )

    def list_listing_offers(self, listing_id, headers):
        return self._request("GET", f"/yacht/listings/{listing_id}/offers", headers=headers)

    # --- offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/yacht/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/yacht/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/yacht/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/yacht/offers/{offer_id}/accept", payload, headers)

    def reject_offer(self, offer_id, headers):
        return self._request("POST", f"/yacht/offers/{offer_id}/reject", headers=headers)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/yacht/offers/{offer_id}/counter", payload, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/yacht/offers/{offer_id}/withdraw", headers=headers)

    def fail_offer(self, offer_id, headers):
        return self._request("POST", f"/yacht/offers/{offer_id}/fail", headers=headers)

    # --- contingencies ---
    def list_contingencies(self, offer_id, headers):
        return self._request("GET", f"/yacht/offers/{offer_id}/contingencies", headers=headers)

    def satisfy_contingency(self, contingency_id, headers):
        return self._request(
            "POST", f"/yacht/contingencies/{contingency_id}/satisfy", headers=headers
        )

    def waive_contingency(self, contingency_id, headers):
        return self._request(
            "POST", f"/yacht/contingencies/{contingency_id}/waive", headers=headers
        )

    def object_contingency(self, contingency_id, payload, headers):
        return self._request(
            "POST", f"/yacht/contingencies/{contingency_id}/object", payload, headers
        )

    def renegotiate_contingency(self, contingency_id, payload, headers):
        return self._request(
            "POST", f"/yacht/contingencies/{contingency_id}/renegotiate", payload, headers
        )

    # --- escrow ledger ---
    def create_escrow_entry(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/yacht/offers/{offer_id}/escrow-entries", payload, headers
        )

    def list_escrow_entries(self, offer_id, headers):
        return self._request("GET", f"/yacht/offers/{offer_id}/escrow-entries", headers=headers)

    def clear_escrow_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/yacht/escrow-entries/{entry_id}/clear", headers=headers
        )

    def void_escrow_entry(self, entry_id, headers):
        return self._request("POST", f"/yacht/escrow-entries/{entry_id}/void", headers=headers)

    def release_escrow_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/yacht/escrow-entries/{entry_id}/release", headers=headers
        )

    def refund_escrow_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/yacht/escrow-entries/{entry_id}/refund", headers=headers
        )

    def forfeit_escrow_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/yacht/escrow-entries/{entry_id}/forfeit", headers=headers
        )

    # --- closing statements ---
    def create_closing_statement(self, payload, headers):
        return self._request("POST", "/yacht/closing-statements", payload, headers)

    def get_closing_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/yacht/closing-statements/{statement_id}", headers=headers
        )

    def list_closing_statements(self, headers, params=None):
        return self._request("GET", "/yacht/closing-statements", headers=headers, params=params)

    def build_closing_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/yacht/closing-statements/{statement_id}/build", payload, headers
        )

    def approve_closing_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/yacht/closing-statements/{statement_id}/approve", payload, headers
        )

    def reopen_closing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/yacht/closing-statements/{statement_id}/reopen", headers=headers
        )

    def void_closing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/yacht/closing-statements/{statement_id}/void", headers=headers
        )

    def disburse_closing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/yacht/closing-statements/{statement_id}/disburse", headers=headers
        )

    def list_tax_assessments(self, statement_id, headers):
        return self._request(
            "GET", f"/yacht/closing-statements/{statement_id}/tax-assessments", headers=headers
        )

    # --- title transfers ---
    def create_title_transfer(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/yacht/closing-statements/{statement_id}/title-transfers",
            payload, headers,
        )

    def get_title_transfer(self, transfer_id, headers):
        return self._request("GET", f"/yacht/title-transfers/{transfer_id}", headers=headers)

    def list_title_transfers(self, headers, params=None):
        return self._request("GET", "/yacht/title-transfers", headers=headers, params=params)

    def execute_title_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/yacht/title-transfers/{transfer_id}/execute", headers=headers
        )

    def revoke_title_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/yacht/title-transfers/{transfer_id}/revoke", headers=headers
        )

    # --- audit log ---
    def list_domain_events(self, headers, params=None):
        return self._request("GET", "/yacht/domain-events", headers=headers, params=params)


api_client = ApiClient()
