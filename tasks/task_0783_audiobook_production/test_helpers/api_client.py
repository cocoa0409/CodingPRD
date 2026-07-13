"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Author / Narrator onboarding ----
    def create_author(self, payload, headers):
        return self._request("POST", "/authors", payload, headers)

    def get_author(self, author_id, headers):
        return self._request("GET", f"/authors/{author_id}", headers=headers)

    def create_narrator(self, payload, headers):
        return self._request("POST", "/narrators", payload, headers)

    def get_narrator(self, narrator_id, headers):
        return self._request("GET", f"/narrators/{narrator_id}", headers=headers)

    # ---- Title ----
    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/titles", headers=headers, params=params)

    def open_title(self, title_id, headers):
        return self._request("POST", f"/titles/{title_id}/open", {}, headers)

    def set_retail_sample(self, title_id, payload, headers):
        return self._request("POST", f"/titles/{title_id}/retail-sample", payload, headers)

    def publish_title(self, title_id, headers):
        return self._request("POST", f"/titles/{title_id}/publish", {}, headers)

    def revert_rights(self, title_id, headers):
        return self._request("POST", f"/titles/{title_id}/revert-rights", {}, headers)

    # ---- Audition ----
    def create_audition(self, payload, headers):
        return self._request("POST", "/auditions", payload, headers)

    def get_audition(self, audition_id, headers):
        return self._request("GET", f"/auditions/{audition_id}", headers=headers)

    def list_auditions(self, headers, params=None):
        return self._request("GET", "/auditions", headers=headers, params=params)

    def decide_audition(self, audition_id, payload, headers):
        return self._request("POST", f"/auditions/{audition_id}/decision", payload, headers)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def respond_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/respond", payload, headers)

    # ---- Production booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/production-bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/production-bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/production-bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/production-bookings/{booking_id}/cancel", {}, headers)

    # ---- Production milestone ----
    def create_milestone(self, payload, headers):
        return self._request("POST", "/production-milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/production-milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/production-milestones", headers=headers, params=params)

    def resubmit_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/production-milestones/{milestone_id}/resubmit", payload, headers)

    # ---- QC review ----
    def create_qc_review(self, milestone_id, payload, headers):
        return self._request("POST", f"/production-milestones/{milestone_id}/qc-reviews", payload, headers)

    def get_qc_review(self, review_id, headers):
        return self._request("GET", f"/qc-reviews/{review_id}", headers=headers)

    def list_qc_reviews(self, headers, params=None):
        return self._request("GET", "/qc-reviews", headers=headers, params=params)

    # ---- Distribution channel ----
    def create_channel(self, payload, headers):
        return self._request("POST", "/distribution-channels", payload, headers)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/distribution-channels/{channel_id}", headers=headers)

    # ---- Distribution listing ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/distribution-listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/distribution-listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/distribution-listings", headers=headers, params=params)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/distribution-listings/{listing_id}/withdraw", {}, headers)

    # ---- Sales events ----
    def create_sales_event(self, payload, headers):
        return self._request("POST", "/sales-events", payload, headers)

    def get_sales_event(self, event_id, headers):
        return self._request("GET", f"/sales-events/{event_id}", headers=headers)

    def list_sales_events(self, headers, params=None):
        return self._request("GET", "/sales-events", headers=headers, params=params)

    # ---- Royalty statements ----
    def create_statement(self, payload, headers):
        return self._request("POST", "/royalty-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/royalty-statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/royalty-statements", headers=headers, params=params)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/finalize", {}, headers)

    def pay_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/pay", {}, headers)

    def reverse_statement(self, statement_id, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/reverse", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
