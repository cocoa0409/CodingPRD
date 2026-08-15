"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/market/_clock/set_current_utc", payload, headers)

    # --- MarketParticipant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/market/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/market/participants/{participant_id}", headers=headers)

    def evaluate_credit(self, participant_id, headers):
        return self._request("POST", f"/market/participants/{participant_id}/evaluate-credit", headers=headers)

    # --- GeneratorAsset ---
    def create_generator(self, payload, headers):
        return self._request("POST", "/market/generators", payload, headers)

    def get_generator(self, generator_id, headers):
        return self._request("GET", f"/market/generators/{generator_id}", headers=headers)

    def list_generators(self, headers, params=None):
        return self._request("GET", "/market/generators", headers=headers, params=params)

    def decommission_generator(self, generator_id, headers):
        return self._request("POST", f"/market/generators/{generator_id}/decommission", headers=headers)

    # --- OperatingDay / market runs ---
    def create_operating_day(self, payload, headers):
        return self._request("POST", "/market/operating-days", payload, headers)

    def get_operating_day(self, operating_day_id, headers):
        return self._request("GET", f"/market/operating-days/{operating_day_id}", headers=headers)

    def run_day_ahead_market(self, operating_day_id, payload, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/run-day-ahead-market", payload, headers)

    def close_real_time(self, operating_day_id, payload, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/close-real-time", payload, headers)

    def run_preliminary_settlement(self, operating_day_id, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/run-preliminary-settlement", headers=headers)

    def run_final_settlement(self, operating_day_id, payload, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/run-final-settlement", payload, headers)

    def close_operating_day(self, operating_day_id, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/close", headers=headers)

    def list_price_nodes(self, operating_day_id, headers):
        return self._request("GET", f"/market/operating-days/{operating_day_id}/price-nodes", headers=headers)

    # --- DayAheadOffer ---
    def create_offer(self, operating_day_id, payload, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/offers", payload, headers)

    def submit_offer(self, offer_id, headers):
        return self._request("POST", f"/market/offers/{offer_id}/submit", headers=headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/market/offers/{offer_id}/withdraw", headers=headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/market/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/market/offers", headers=headers, params=params)

    # --- RealTimeTelemetry ---
    def submit_telemetry(self, generator_id, payload, headers):
        return self._request("POST", f"/market/generators/{generator_id}/telemetry", payload, headers)

    def get_telemetry(self, telemetry_id, headers):
        return self._request("GET", f"/market/telemetry/{telemetry_id}", headers=headers)

    def list_telemetry(self, headers, params=None):
        return self._request("GET", "/market/telemetry", headers=headers, params=params)

    # --- OutageReport ---
    def create_outage(self, generator_id, payload, headers):
        return self._request("POST", f"/market/generators/{generator_id}/outages", payload, headers)

    def get_outage(self, outage_id, headers):
        return self._request("GET", f"/market/outages/{outage_id}", headers=headers)

    def list_outages(self, headers, params=None):
        return self._request("GET", "/market/outages", headers=headers, params=params)

    def acknowledge_outage(self, outage_id, headers):
        return self._request("POST", f"/market/outages/{outage_id}/acknowledge", headers=headers)

    def approve_outage(self, outage_id, headers):
        return self._request("POST", f"/market/outages/{outage_id}/approve", headers=headers)

    def deny_outage(self, outage_id, payload, headers):
        return self._request("POST", f"/market/outages/{outage_id}/deny", payload, headers)

    def resubmit_outage(self, outage_id, payload, headers):
        return self._request("POST", f"/market/outages/{outage_id}/resubmit", payload, headers)

    def cancel_outage(self, outage_id, headers):
        return self._request("POST", f"/market/outages/{outage_id}/cancel", headers=headers)

    # --- SettlementStatement / SettlementLine ---
    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/market/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/market/statements", headers=headers, params=params)

    def list_statement_lines(self, statement_id, headers):
        return self._request("GET", f"/market/statements/{statement_id}/lines", headers=headers)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/market/lines/{line_id}", headers=headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/market/lines", headers=headers, params=params)

    # --- SettlementDispute ---
    def create_dispute(self, statement_id, payload, headers):
        return self._request("POST", f"/market/statements/{statement_id}/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/market/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/market/disputes", headers=headers, params=params)

    def start_review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/market/disputes/{dispute_id}/start-review", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/market/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/market/disputes/{dispute_id}/withdraw", headers=headers)

    # --- AncillaryServiceAward ---
    def create_award(self, operating_day_id, payload, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/market/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/market/awards", headers=headers, params=params)

    def cancel_award(self, award_id, headers):
        return self._request("POST", f"/market/awards/{award_id}/cancel", headers=headers)

    # --- CapacityObligation ---
    def create_obligation(self, payload, headers):
        return self._request("POST", "/market/obligations", payload, headers)

    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/market/obligations/{obligation_id}", headers=headers)

    def list_obligations(self, headers, params=None):
        return self._request("GET", "/market/obligations", headers=headers, params=params)

    def close_obligation(self, obligation_id, headers):
        return self._request("POST", f"/market/obligations/{obligation_id}/close", headers=headers)

    # --- CapacityPerformanceEvent ---
    def create_performance_event(self, operating_day_id, payload, headers):
        return self._request("POST", f"/market/operating-days/{operating_day_id}/performance-events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/market/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/market/events", headers=headers, params=params)

    def activate_event(self, event_id, headers):
        return self._request("POST", f"/market/events/{event_id}/activate", headers=headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/market/events/{event_id}/complete", headers=headers)

    # --- CollateralPosting ---
    def create_posting(self, participant_id, payload, headers):
        return self._request("POST", f"/market/participants/{participant_id}/postings", payload, headers)

    def get_posting(self, posting_id, headers):
        return self._request("GET", f"/market/postings/{posting_id}", headers=headers)

    def list_postings(self, headers, params=None):
        return self._request("GET", "/market/postings", headers=headers, params=params)

    def release_posting(self, posting_id, headers):
        return self._request("POST", f"/market/postings/{posting_id}/release", headers=headers)

    def draw_posting(self, posting_id, headers):
        return self._request("POST", f"/market/postings/{posting_id}/draw", headers=headers)

    # --- MarginCall ---
    def get_margin_call(self, margin_call_id, headers):
        return self._request("GET", f"/market/margin-calls/{margin_call_id}", headers=headers)

    def list_margin_calls(self, headers, params=None):
        return self._request("GET", "/market/margin-calls", headers=headers, params=params)


api_client = ApiClient()
