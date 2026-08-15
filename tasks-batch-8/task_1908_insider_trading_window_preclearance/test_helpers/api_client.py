"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- CoveredPerson ---
    def create_covered_person(self, payload, headers):
        return self._request("POST", "/covered-persons", payload, headers)

    def get_covered_person(self, person_id, headers):
        return self._request("GET", f"/covered-persons/{person_id}", headers=headers)

    def list_covered_persons(self, headers, params=None):
        return self._request("GET", "/covered-persons", headers=headers, params=params)

    # --- Deal ---
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def activate_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/activate", None, headers)

    def close_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/close", payload, headers)

    def list_deal_restricted_list_entries(self, deal_id, headers):
        return self._request(
            "GET", f"/deals/{deal_id}/restricted-list-entries", headers=headers
        )

    # --- RestrictedListEntry ---
    def create_restricted_list_entry(self, payload, headers):
        return self._request("POST", "/restricted-list-entries", payload, headers)

    def list_restricted_list_entries(self, headers, params=None):
        return self._request(
            "GET", "/restricted-list-entries", headers=headers, params=params
        )

    def remove_restricted_list_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/restricted-list-entries/{entry_id}/remove", None, headers
        )

    # --- BlackoutWindow ---
    def create_blackout_window(self, payload, headers):
        return self._request("POST", "/blackout-windows", payload, headers)

    def get_blackout_window(self, window_id, headers):
        return self._request("GET", f"/blackout-windows/{window_id}", headers=headers)

    def list_blackout_windows(self, headers, params=None):
        return self._request("GET", "/blackout-windows", headers=headers, params=params)

    def cancel_blackout_window(self, window_id, headers):
        return self._request(
            "POST", f"/blackout-windows/{window_id}/cancel", None, headers
        )

    def extend_blackout_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/blackout-windows/{window_id}/extend", payload, headers
        )

    # --- PreclearanceRequest ---
    def create_preclearance_request(self, payload, headers):
        return self._request("POST", "/preclearance-requests", payload, headers)

    def get_preclearance_request(self, request_id, headers):
        return self._request(
            "GET", f"/preclearance-requests/{request_id}", headers=headers
        )

    def list_preclearance_requests(self, headers, params=None):
        return self._request(
            "GET", "/preclearance-requests", headers=headers, params=params
        )

    def review_preclearance_request(self, request_id, headers):
        return self._request(
            "POST", f"/preclearance-requests/{request_id}/review", None, headers
        )

    def decide_preclearance_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/preclearance-requests/{request_id}/decision", payload, headers
        )

    def withdraw_preclearance_request(self, request_id, headers):
        return self._request(
            "POST", f"/preclearance-requests/{request_id}/withdraw", None, headers
        )

    def list_request_trade_confirmations(self, request_id, headers):
        return self._request(
            "GET",
            f"/preclearance-requests/{request_id}/trade-confirmations",
            headers=headers,
        )

    # --- ExceptionRequest ---
    def create_exception_request(self, payload, headers):
        return self._request("POST", "/exception-requests", payload, headers)

    def get_exception_request(self, exception_id, headers):
        return self._request(
            "GET", f"/exception-requests/{exception_id}", headers=headers
        )

    def list_exception_requests(self, headers, params=None):
        return self._request("GET", "/exception-requests", headers=headers, params=params)

    def vote_exception_request(self, exception_id, payload, headers):
        return self._request(
            "POST", f"/exception-requests/{exception_id}/vote", payload, headers
        )

    def withdraw_exception_request(self, exception_id, headers):
        return self._request(
            "POST", f"/exception-requests/{exception_id}/withdraw", None, headers
        )

    def list_exception_preclearance_requests(self, exception_id, headers):
        return self._request(
            "GET",
            f"/exception-requests/{exception_id}/preclearance-requests",
            headers=headers,
        )

    # --- TenB5Plan ---
    def create_tenb5_plan(self, payload, headers):
        return self._request("POST", "/tenb5-plans", payload, headers)

    def get_tenb5_plan(self, plan_id, headers):
        return self._request("GET", f"/tenb5-plans/{plan_id}", headers=headers)

    def list_tenb5_plans(self, headers, params=None):
        return self._request("GET", "/tenb5-plans", headers=headers, params=params)

    def submit_tenb5_plan(self, plan_id, headers):
        return self._request("POST", f"/tenb5-plans/{plan_id}/submit", None, headers)

    def decide_tenb5_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/tenb5-plans/{plan_id}/decision", payload, headers)

    def act_on_tenb5_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/tenb5-plans/{plan_id}/action", payload, headers)

    # --- TradeConfirmation ---
    def create_trade_confirmation(self, payload, headers):
        return self._request("POST", "/trade-confirmations", payload, headers)

    def get_trade_confirmation(self, confirmation_id, headers):
        return self._request(
            "GET", f"/trade-confirmations/{confirmation_id}", headers=headers
        )

    def list_trade_confirmations(self, headers, params=None):
        return self._request(
            "GET", "/trade-confirmations", headers=headers, params=params
        )

    # --- ViolationCase ---
    def create_violation_case(self, payload, headers):
        return self._request("POST", "/violation-cases", payload, headers)

    def get_violation_case(self, case_id, headers):
        return self._request("GET", f"/violation-cases/{case_id}", headers=headers)

    def list_violation_cases(self, headers, params=None):
        return self._request("GET", "/violation-cases", headers=headers, params=params)

    def act_on_violation_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/violation-cases/{case_id}/action", payload, headers
        )

    # --- Attestation ---
    def create_attestation(self, payload, headers):
        return self._request("POST", "/attestations", payload, headers)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"/attestations/{attestation_id}", headers=headers)

    def list_attestations(self, headers, params=None):
        return self._request("GET", "/attestations", headers=headers, params=params)

    def complete_attestation(self, attestation_id, headers):
        return self._request(
            "POST", f"/attestations/{attestation_id}/complete", None, headers
        )

    # --- Compliance sweep ---
    def run_compliance_sweep(self, headers):
        return self._request("POST", "/compliance-sweeps", None, headers)


api_client = ApiClient()

# Per-test-server isolation restarts the API server on the SAME port before
# every test. A keep-alive connection pooled from the previous test's server
# process is silently dead after the restart, and reusing it for a POST fails
# with ConnectionResetError (urllib3 does not retry non-idempotent requests).
# Forcing Connection: close gives every request a fresh TCP connection to the
# current server process — transport hardening only; request semantics,
# payloads, and assertions are untouched.
api_client.session.headers["Connection"] = "close"
