"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Underwriting Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/underwriting-cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/underwriting-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/underwriting-cases/{case_id}", headers=headers)

    def submit_for_census(self, case_id, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/submit-for-census", {}, headers)

    def request_claims(self, case_id, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/request-claims", {}, headers)

    def decline_case(self, case_id, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/decline", {}, headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/withdraw", {}, headers)

    # --- Brokers ---
    def create_broker(self, payload, headers):
        return self._request("POST", "/brokers", payload, headers)

    def list_brokers(self, headers, params=None):
        return self._request("GET", "/brokers", headers=headers, params=params)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/brokers/{broker_id}", headers=headers)

    def update_broker(self, broker_id, payload, headers):
        return self._request("PUT", f"/brokers/{broker_id}", payload, headers)

    # --- Census Snapshots ---
    def create_census_snapshot(self, case_id, payload, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/census-snapshots", payload, headers)

    def list_census_snapshots(self, case_id, headers):
        return self._request("GET", f"/underwriting-cases/{case_id}/census-snapshots", headers=headers)

    def get_census_snapshot(self, census_id, headers):
        return self._request("GET", f"/census-snapshots/{census_id}", headers=headers)

    def validate_census(self, census_id, headers):
        return self._request("POST", f"/census-snapshots/{census_id}/validate", {}, headers)

    def reject_census(self, census_id, headers):
        return self._request("POST", f"/census-snapshots/{census_id}/reject", {}, headers)

    # --- Claims Experiences ---
    def create_claims_experience(self, case_id, payload, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/claims-experiences", payload, headers)

    def list_claims_experiences(self, case_id, headers):
        return self._request("GET", f"/underwriting-cases/{case_id}/claims-experiences", headers=headers)

    def get_claims_experience(self, claims_id, headers):
        return self._request("GET", f"/claims-experiences/{claims_id}", headers=headers)

    def submit_claims(self, claims_id, headers):
        return self._request("POST", f"/claims-experiences/{claims_id}/submit", {}, headers)

    def review_claims(self, claims_id, headers):
        return self._request("POST", f"/claims-experiences/{claims_id}/review", {}, headers)

    def reject_claims(self, claims_id, headers):
        return self._request("POST", f"/claims-experiences/{claims_id}/reject", {}, headers)

    # --- Benefit Plan Designs ---
    def create_plan_design(self, case_id, payload, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/plan-designs", payload, headers)

    def list_plan_designs(self, case_id, headers):
        return self._request("GET", f"/underwriting-cases/{case_id}/plan-designs", headers=headers)

    def get_plan_design(self, plan_id, headers):
        return self._request("GET", f"/plan-designs/{plan_id}", headers=headers)

    def model_plan(self, plan_id, headers):
        return self._request("POST", f"/plan-designs/{plan_id}/model", {}, headers)

    def reject_plan(self, plan_id, headers):
        return self._request("POST", f"/plan-designs/{plan_id}/reject", {}, headers)

    # --- Quotes ---
    def create_quote(self, case_id, payload, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/quotes", payload, headers)

    def list_quotes(self, case_id, headers):
        return self._request("GET", f"/underwriting-cases/{case_id}/quotes", headers=headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def propose_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/propose", {}, headers)

    def counter_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/counter", payload, headers)

    def respond_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/respond", payload, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", {}, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject-quote", {}, headers)

    # --- Stop-Loss Quotes ---
    def create_stop_loss_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/stop-loss-quotes", payload, headers)

    def list_stop_loss_quotes(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}/stop-loss-quotes", headers=headers)

    def get_stop_loss_quote(self, slq_id, headers):
        return self._request("GET", f"/stop-loss-quotes/{slq_id}", headers=headers)

    def quote_stop_loss(self, slq_id, headers):
        return self._request("POST", f"/stop-loss-quotes/{slq_id}/quote", {}, headers)

    def bind_stop_loss(self, slq_id, headers):
        return self._request("POST", f"/stop-loss-quotes/{slq_id}/bind", {}, headers)

    def decline_stop_loss(self, slq_id, headers):
        return self._request("POST", f"/stop-loss-quotes/{slq_id}/decline-slq", {}, headers)

    # --- Negotiation Rounds ---
    def list_negotiation_rounds(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}/negotiation-rounds", headers=headers)

    def get_negotiation_round(self, round_id, headers):
        return self._request("GET", f"/negotiation-rounds/{round_id}", headers=headers)

    def withdraw_round(self, round_id, headers):
        return self._request("POST", f"/negotiation-rounds/{round_id}/withdraw-round", {}, headers)

    # --- Enrollment Change Events ---
    def create_enrollment_change(self, case_id, payload, headers):
        return self._request("POST", f"/underwriting-cases/{case_id}/enrollment-changes", payload, headers)

    def list_enrollment_changes(self, case_id, headers):
        return self._request("GET", f"/underwriting-cases/{case_id}/enrollment-changes", headers=headers)

    def get_enrollment_change(self, event_id, headers):
        return self._request("GET", f"/enrollment-changes/{event_id}", headers=headers)

    def process_enrollment_change(self, event_id, headers):
        return self._request("POST", f"/enrollment-changes/{event_id}/process", {}, headers)

    # --- Commission Disclosures ---
    def list_commission_disclosures(self, case_id, headers):
        return self._request("GET", f"/underwriting-cases/{case_id}/commission-disclosures", headers=headers)

    def get_commission_disclosure(self, disc_id, headers):
        return self._request("GET", f"/commission-disclosures/{disc_id}", headers=headers)

    def disclose_commission(self, disc_id, headers):
        return self._request("POST", f"/commission-disclosures/{disc_id}/disclose", {}, headers)

    def acknowledge_disclosure(self, disc_id, headers):
        return self._request("POST", f"/commission-disclosures/{disc_id}/acknowledge", {}, headers)

    # --- Logical Clock ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
