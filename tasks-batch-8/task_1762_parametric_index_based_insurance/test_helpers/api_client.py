"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- InsuranceProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", {}, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/resume", {}, headers)

    def close_program(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/close", payload, headers)

    def advance_reporting_epoch(self, program_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/advance-reporting-epoch", {}, headers
        )

    def get_financial_summary(self, program_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/financial-summary", headers=headers
        )

    # --- IndexDefinition ---
    def create_index_definition(self, program_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/index-definitions", payload, headers
        )

    def list_index_definitions(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/index-definitions", headers=headers, params=params
        )

    def get_index_definition(self, program_id, index_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/index-definitions/{index_id}", headers=headers
        )

    def activate_index(self, program_id, index_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/index-definitions/{index_id}/activate", {}, headers
        )

    def suspend_index(self, program_id, index_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/index-definitions/{index_id}/suspend", {}, headers
        )

    def resume_index(self, program_id, index_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/index-definitions/{index_id}/resume", {}, headers
        )

    def decommission_index(self, program_id, index_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/index-definitions/{index_id}/decommission",
            {},
            headers,
        )

    def list_index_definitions_flat(self, headers, params=None):
        return self._request("GET", "/programs/index-definitions", headers=headers, params=params)

    def get_index_definition_flat(self, index_id, headers):
        return self._request("GET", f"/programs/index-definitions/{index_id}", headers=headers)

    # --- MeasurementStation ---
    def create_station(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/stations", payload, headers)

    def list_stations(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/stations", headers=headers, params=params
        )

    def get_station(self, program_id, station_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/stations/{station_id}", headers=headers
        )

    def take_station_offline(self, program_id, station_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/stations/{station_id}/take-offline", {}, headers
        )

    def recommission_station(self, program_id, station_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/stations/{station_id}/recommission", {}, headers
        )

    def decommission_station(self, program_id, station_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/stations/{station_id}/decommission", {}, headers
        )

    def list_stations_flat(self, headers, params=None):
        return self._request("GET", "/programs/stations", headers=headers, params=params)

    def get_station_flat(self, station_id, headers):
        return self._request("GET", f"/programs/stations/{station_id}", headers=headers)

    # --- IndexObservation (append-only) ---
    def create_observation(self, program_id, index_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/index-definitions/{index_id}/observations",
            payload,
            headers,
        )

    def list_observations(self, program_id, index_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/index-definitions/{index_id}/observations",
            headers=headers,
            params=params,
        )

    def list_observations_flat(self, headers, params=None):
        return self._request("GET", "/programs/observations", headers=headers, params=params)

    def get_observation_flat(self, observation_id, headers):
        return self._request("GET", f"/programs/observations/{observation_id}", headers=headers)

    # --- Policyholder ---
    def create_policyholder(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/policyholders", payload, headers)

    def list_policyholders(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/policyholders", headers=headers, params=params
        )

    def get_policyholder(self, program_id, holder_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/policyholders/{holder_id}", headers=headers
        )

    def update_policyholder(self, program_id, holder_id, payload, headers):
        return self._request(
            "PATCH", f"/programs/{program_id}/policyholders/{holder_id}", payload, headers
        )

    def blacklist_policyholder(self, program_id, holder_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/policyholders/{holder_id}/blacklist", {}, headers
        )

    def flag_fraud(self, program_id, holder_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/policyholders/{holder_id}/flag-fraud", {}, headers
        )

    def list_policyholders_flat(self, headers, params=None):
        return self._request("GET", "/programs/policyholders", headers=headers, params=params)

    def get_policyholder_flat(self, holder_id, headers):
        return self._request("GET", f"/programs/policyholders/{holder_id}", headers=headers)

    # --- ParametricPolicy ---
    def create_policy(self, program_id, holder_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/policyholders/{holder_id}/policies",
            payload,
            headers,
        )

    def list_policies(self, program_id, holder_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/policyholders/{holder_id}/policies",
            headers=headers,
            params=params,
        )

    def get_policy(self, program_id, holder_id, policy_id, headers):
        return self._request(
            "GET",
            f"/programs/{program_id}/policyholders/{holder_id}/policies/{policy_id}",
            headers=headers,
        )

    def bind_policy(self, program_id, holder_id, policy_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/policyholders/{holder_id}/policies/{policy_id}/bind",
            {},
            headers,
        )

    def cancel_policy(self, program_id, holder_id, policy_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/policyholders/{holder_id}/policies/{policy_id}/cancel",
            {},
            headers,
        )

    def list_policies_in_program(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/policies", headers=headers, params=params
        )

    def list_policies_flat(self, headers, params=None):
        return self._request("GET", "/programs/policies", headers=headers, params=params)

    def get_policy_flat(self, policy_id, headers):
        return self._request("GET", f"/programs/policies/{policy_id}", headers=headers)

    # --- PremiumInvoice ---
    def list_invoices(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/invoices", headers=headers, params=params
        )

    def get_invoice(self, program_id, invoice_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/invoices/{invoice_id}", headers=headers
        )

    def pay_invoice(self, program_id, invoice_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/invoices/{invoice_id}/payments",
            payload,
            headers,
        )

    def list_invoices_flat(self, headers, params=None):
        return self._request("GET", "/programs/invoices", headers=headers, params=params)

    def get_invoice_flat(self, invoice_id, headers):
        return self._request("GET", f"/programs/invoices/{invoice_id}", headers=headers)

    # --- TriggerEvent ---
    def list_trigger_events(self, program_id, index_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/index-definitions/{index_id}/trigger-events",
            headers=headers,
            params=params,
        )

    def get_trigger_event(self, program_id, index_id, event_id, headers):
        return self._request(
            "GET",
            f"/programs/{program_id}/index-definitions/{index_id}/trigger-events/{event_id}",
            headers=headers,
        )

    def list_trigger_events_in_program(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/trigger-events", headers=headers, params=params
        )

    def open_event_review(self, program_id, index_id, event_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/index-definitions/{index_id}/trigger-events/{event_id}/open-review",
            {},
            headers,
        )

    def verify_event(self, program_id, index_id, event_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/index-definitions/{index_id}/trigger-events/{event_id}/verify",
            {},
            headers,
        )

    def reject_event(self, program_id, index_id, event_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/index-definitions/{index_id}/trigger-events/{event_id}/reject",
            {},
            headers,
        )

    def list_trigger_events_flat(self, headers, params=None):
        return self._request("GET", "/programs/trigger-events", headers=headers, params=params)

    def get_trigger_event_flat(self, event_id, headers):
        return self._request("GET", f"/programs/trigger-events/{event_id}", headers=headers)

    # --- PayoutClaim ---
    def list_claims(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/claims", headers=headers, params=params
        )

    def get_claim(self, program_id, claim_id, headers):
        return self._request("GET", f"/programs/{program_id}/claims/{claim_id}", headers=headers)

    def list_claims_of_policy(self, program_id, holder_id, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/policyholders/{holder_id}/policies/{policy_id}/claims",
            headers=headers,
            params=params,
        )

    def adjust_claim(self, program_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/claims/{claim_id}/adjust", payload, headers
        )

    def approve_claim(self, program_id, claim_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/claims/{claim_id}/approve", {}, headers
        )

    def decline_claim(self, program_id, claim_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/claims/{claim_id}/decline", {}, headers
        )

    def clear_fraud_hold(self, program_id, claim_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/claims/{claim_id}/clear-fraud-hold", {}, headers
        )

    def release_payment(self, program_id, claim_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/claims/{claim_id}/release-payment", {}, headers
        )

    def list_claims_flat(self, headers, params=None):
        return self._request("GET", "/programs/claims", headers=headers, params=params)

    def get_claim_flat(self, claim_id, headers):
        return self._request("GET", f"/programs/claims/{claim_id}", headers=headers)

    # --- DisputeCase ---
    def create_dispute(self, program_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/claims/{claim_id}/disputes", payload, headers
        )

    def list_disputes(self, program_id, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/claims/{claim_id}/disputes",
            headers=headers,
            params=params,
        )

    def get_dispute(self, program_id, claim_id, dispute_id, headers):
        return self._request(
            "GET",
            f"/programs/{program_id}/claims/{claim_id}/disputes/{dispute_id}",
            headers=headers,
        )

    def request_dispute_info(self, program_id, claim_id, dispute_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/claims/{claim_id}/disputes/{dispute_id}/request-info",
            {},
            headers,
        )

    def submit_dispute_info(self, program_id, claim_id, dispute_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/claims/{claim_id}/disputes/{dispute_id}/submit-info",
            {},
            headers,
        )

    def resolve_dispute(self, program_id, claim_id, dispute_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/claims/{claim_id}/disputes/{dispute_id}/resolve",
            payload,
            headers,
        )

    def withdraw_dispute(self, program_id, claim_id, dispute_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/claims/{claim_id}/disputes/{dispute_id}/withdraw",
            {},
            headers,
        )

    def list_disputes_flat(self, headers, params=None):
        return self._request("GET", "/programs/disputes", headers=headers, params=params)

    def get_dispute_flat(self, dispute_id, headers):
        return self._request("GET", f"/programs/disputes/{dispute_id}", headers=headers)

    # --- ReinsuranceTreaty ---
    def create_treaty(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/treaties", payload, headers)

    def list_treaties(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/treaties", headers=headers, params=params
        )

    def get_treaty(self, program_id, treaty_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/treaties/{treaty_id}", headers=headers
        )

    def bind_treaty(self, program_id, treaty_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/treaties/{treaty_id}/bind-treaty",
            payload,
            headers,
        )

    def list_treaties_flat(self, headers, params=None):
        return self._request("GET", "/programs/treaties", headers=headers, params=params)

    def get_treaty_flat(self, treaty_id, headers):
        return self._request("GET", f"/programs/treaties/{treaty_id}", headers=headers)


api_client = ApiClient()
