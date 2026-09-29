"""One client method per declared endpoint of the service.

The service is mounted directly at the root with no version or product prefix, so
every path below is written exactly as the PRD declares it. Methods return the raw
`requests.Response` so that tests can assert on status codes as well as bodies.
"""

from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json


class ApiClient(GenericApiClient):
    """Typed access to the fifty-four endpoints of the rail service."""

    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ housekeeping
    def run_network_sweep(self, headers: Headers, payload: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/network-sweeps", payload, headers)

    # ------------------------------------------------------------ participants
    def create_participant(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/participants/{participant_id}", None, headers)

    def change_participation_model(self, participant_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("PATCH", f"/participants/{participant_id}/participation-model", payload, headers)

    def file_attestation(self, participant_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/participants/{participant_id}/attestation", payload, headers)

    def open_certification_window(self, participant_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/participants/{participant_id}/certification-window", payload, headers)

    def record_certification_result(self, participant_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/participants/{participant_id}/certification-results", payload, headers)

    def activate_participant(self, participant_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/participants/{participant_id}/activation", payload, headers)

    def change_participant_status(self, participant_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/participants/{participant_id}/status-change", payload, headers)

    def list_participant_position_accounts(
        self, participant_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/participants/{participant_id}/position-accounts", params, headers)

    def list_participant_segment_policies(
        self, participant_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/participants/{participant_id}/segment-policies", params, headers)

    def list_participant_customer_accounts(
        self, participant_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/participants/{participant_id}/customer-accounts", params, headers)

    def list_participant_outage_events(
        self, participant_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/participants/{participant_id}/outage-events", params, headers)

    # ------------------------------------------------------- position accounts
    def create_position_account(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/position-accounts", payload, headers)

    def get_position_account(self, account_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/position-accounts/{account_id}", None, headers)

    def post_ledger_adjustment(self, account_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/position-accounts/{account_id}/ledger-adjustments", payload, headers)

    def list_ledger_entries(
        self, account_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/position-accounts/{account_id}/ledger-entries", params, headers)

    def list_account_alerts(
        self, account_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/position-accounts/{account_id}/alerts", params, headers)

    def get_liquidity_projection(self, account_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/position-accounts/{account_id}/liquidity-projection", None, headers)

    # ------------------------------------------------------------ alerts
    def acknowledge_alert(self, alert_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/liquidity-alerts/{alert_id}/acknowledgement", payload, headers)

    # ------------------------------------------------------- policies/customers
    def create_segment_policy(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/segment-policies", payload, headers)

    def create_customer_account(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/customer-accounts", payload, headers)

    def get_customer_account(self, customer_account_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/customer-accounts/{customer_account_id}", None, headers)

    # ------------------------------------------------------------ credit transfers
    def create_credit_transfer(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/credit-transfers", payload, headers)

    def get_credit_transfer(self, transfer_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/credit-transfers/{transfer_id}", None, headers)

    def list_credit_transfers(self, headers: Headers, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/credit-transfers", params, headers)

    def accept_credit_transfer(
        self, transfer_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/credit-transfers/{transfer_id}/acceptance", payload, headers)

    def settle_credit_transfer(
        self, transfer_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/credit-transfers/{transfer_id}/settlement", payload, headers)

    def divert_credit_transfer(self, transfer_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/credit-transfers/{transfer_id}/diversion", payload, headers)

    def list_transfer_ledger_entries(
        self, transfer_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/credit-transfers/{transfer_id}/ledger-entries", params, headers)

    def list_transfer_fraud_reviews(
        self, transfer_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/credit-transfers/{transfer_id}/fraud-reviews", params, headers)

    # ------------------------------------------------------------ fraud reviews
    def assign_fraud_review(
        self, review_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/fraud-reviews/{review_id}/assignment", payload, headers)

    def decide_fraud_review(self, review_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/fraud-reviews/{review_id}/decision", payload, headers)

    # ------------------------------------------------------- requests for payment
    def create_request_for_payment(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/request-for-payments", payload, headers)

    def get_request_for_payment(self, rfp_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/request-for-payments/{rfp_id}", None, headers)

    def list_requests_for_payment(self, headers: Headers, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/request-for-payments", params, headers)

    def deliver_request_for_payment(
        self, rfp_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/request-for-payments/{rfp_id}/delivery", payload, headers)

    def respond_to_request_for_payment(self, rfp_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/request-for-payments/{rfp_id}/response", payload, headers)

    def amend_request_for_payment(self, rfp_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/request-for-payments/{rfp_id}/amendment", payload, headers)

    # ------------------------------------------------------------ return requests
    def create_return_request(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/return-requests", payload, headers)

    def get_return_request(self, return_request_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/return-requests/{return_request_id}", None, headers)

    def list_return_requests(self, headers: Headers, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/return-requests", params, headers)

    def honor_return_request(
        self, return_request_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/return-requests/{return_request_id}/honor", payload, headers)

    def decline_return_request(self, return_request_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/return-requests/{return_request_id}/decline", payload, headers)

    # ------------------------------------------------------------ settlement cycles
    def create_settlement_cycle(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/settlement-cycles", payload, headers)

    def get_settlement_cycle(self, cycle_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/settlement-cycles/{cycle_id}", None, headers)

    def cutoff_settlement_cycle(
        self, cycle_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/settlement-cycles/{cycle_id}/cutoff", payload, headers)

    def close_settlement_cycle(
        self, cycle_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/settlement-cycles/{cycle_id}/reconciliation-closure", payload, headers)

    # ------------------------------------------------------- reconciliation runs
    def create_reconciliation_run(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/reconciliation-runs", payload, headers)

    def get_reconciliation_run(self, run_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/reconciliation-runs/{run_id}", None, headers)

    def list_reconciliation_runs(self, headers: Headers, params: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/reconciliation-runs", params, headers)

    # ------------------------------------------------------------ outage events
    def create_outage_event(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/outage-events", payload, headers)

    def resolve_outage_event(self, event_id: str, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"/outage-events/{event_id}/resolution", payload, headers)
