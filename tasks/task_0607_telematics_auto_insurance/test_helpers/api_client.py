"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Rate plans ----
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/rate-plans", payload, headers)

    def list_rate_plans(self, headers, params=None):
        return self._request("GET", "/rate-plans", headers=headers, params=params)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/rate-plans/{rate_plan_id}", headers=headers)

    def retire_rate_plan(self, rate_plan_id, headers):
        return self._request("POST", f"/rate-plans/{rate_plan_id}/retire", {}, headers)

    # ---- Drivers ----
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    # ---- Privacy consents ----
    def create_privacy_consent(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/privacy-consents", payload, headers)

    def list_privacy_consents(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/privacy-consents", headers=headers, params=params)

    # ---- Discount banks ----
    def list_discount_banks(self, headers, params=None):
        return self._request("GET", "/discount-banks", headers=headers, params=params)

    def get_discount_bank(self, bank_id, headers):
        return self._request("GET", f"/discount-banks/{bank_id}", headers=headers)

    def list_discount_grants(self, bank_id, headers, params=None):
        return self._request("GET", f"/discount-banks/{bank_id}/grants", headers=headers, params=params)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def finalize_scoring(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/finalize-scoring", {}, headers)

    def reopen_scoring(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/reopen-scoring", {}, headers)

    def abandon_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/abandon", {}, headers)

    def expire_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/expire", {}, headers)

    # ---- Quotes ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", {}, headers)

    def expire_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/expire", {}, headers)

    # ---- Policies ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/lapse", {}, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    def advance_period(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/advance-period", {}, headers)

    def list_risk_snapshots(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/risk-snapshots", headers=headers, params=params)

    # ---- Trips ----
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def create_trip_event(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/events", payload, headers)

    def list_trip_events(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/events", headers=headers, params=params)

    def accept_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/accept", {}, headers)

    def reject_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/reject", {}, headers)

    def void_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/void", {}, headers)

    # ---- Statements ----
    def create_statement(self, payload, headers):
        return self._request("POST", "/statements", payload, headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def issue_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/issue", {}, headers)

    def settle_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/settle", {}, headers)

    # ---- Renewals ----
    def create_renewal(self, payload, headers):
        return self._request("POST", "/renewals", payload, headers)

    def list_renewals(self, headers, params=None):
        return self._request("GET", "/renewals", headers=headers, params=params)

    def get_renewal(self, renewal_id, headers):
        return self._request("GET", f"/renewals/{renewal_id}", headers=headers)

    def accept_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/accept", {}, headers)

    def decline_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/decline", {}, headers)

    # ---- Claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def triage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/triage", payload, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    def reopen_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reopen", payload, headers)


api_client = ApiClient()
