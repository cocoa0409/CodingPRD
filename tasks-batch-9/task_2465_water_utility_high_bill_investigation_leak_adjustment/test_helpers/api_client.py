"""One method per endpoint of the water-utility high-bill service (PRD §4).

Every method returns the raw ``requests.Response`` so tests can assert on both
the status code and the response envelope.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """HTTP surface of the service under test."""

    # -----------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # -----------------------------------------------------------------
    def set_clock(self, current_utc: str) -> requests.Response:
        """Move the logical clock. Requires no authentication headers."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            {"Content-Type": "application/json"},
        )

    def set_clock_raw(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        """Call the clock setter with an arbitrary payload and headers."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -----------------------------------------------------------------
    # Rate schedules (PRD §3.1)
    # -----------------------------------------------------------------
    def create_rate_schedule(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/rate-schedules", payload, headers)

    def list_rate_schedules(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/rate-schedules", params, headers)

    def get_rate_schedule(
        self, rate_schedule_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/rate-schedules/{rate_schedule_id}", None, headers)

    # -----------------------------------------------------------------
    # Billing periods (PRD §2.10)
    # -----------------------------------------------------------------
    def create_billing_period(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/billing-periods", payload, headers)

    def list_billing_periods(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/billing-periods", params, headers)

    def get_billing_period(
        self, period_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/billing-periods/{period_id}", None, headers)

    def close_billing_period(
        self, period_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/billing-periods/{period_id}/close", payload, headers
        )

    def lock_billing_period(
        self, period_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/billing-periods/{period_id}/lock", payload, headers
        )

    # -----------------------------------------------------------------
    # Service accounts (PRD §3.1, §3.8)
    # -----------------------------------------------------------------
    def create_service_account(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/service-accounts", payload, headers)

    def list_service_accounts(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/service-accounts", params, headers)

    def get_service_account(
        self, account_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/service-accounts/{account_id}", None, headers)

    def list_account_ledger_entries(
        self, account_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/service-accounts/{account_id}/ledger-entries", params, headers
        )

    def schedule_shutoff(
        self, account_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/service-accounts/{account_id}/schedule-shutoff", payload, headers
        )

    def execute_shutoff(
        self, account_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/service-accounts/{account_id}/execute-shutoff", payload, headers
        )

    def record_account_payment(
        self, account_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/service-accounts/{account_id}/payments", payload, headers
        )

    # -----------------------------------------------------------------
    # Meters and readings (PRD §3.1)
    # -----------------------------------------------------------------
    def create_meter(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/meters", payload, headers)

    def list_meters(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/meters", params, headers)

    def get_meter(self, meter_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/meters/{meter_id}", None, headers)

    def create_meter_reading(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/meter-readings", payload, headers)

    def list_meter_readings(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/meter-readings", params, headers)

    def get_meter_reading(
        self, reading_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/meter-readings/{reading_id}", None, headers)

    # -----------------------------------------------------------------
    # Bills (PRD §3.2, §3.5)
    # -----------------------------------------------------------------
    def create_bill(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/bills", payload, headers)

    def list_bills(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/bills", params, headers)

    def get_bill(self, bill_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/bills/{bill_id}", None, headers)

    def list_bill_ledger_entries(
        self, bill_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/bills/{bill_id}/ledger-entries", params, headers)

    def get_adjustment_preview(
        self, bill_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/bills/{bill_id}/adjustment-preview", params, headers
        )

    def issue_bill(
        self, bill_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request("POST", f"/bills/{bill_id}/issue", payload, headers)

    def rebill_bill(
        self, bill_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request("POST", f"/bills/{bill_id}/rebill", payload, headers)

    # -----------------------------------------------------------------
    # Investigations (PRD §3.3, §3.6)
    # -----------------------------------------------------------------
    def create_investigation(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/investigations", payload, headers)

    def list_investigations(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/investigations", params, headers)

    def get_investigation(
        self, investigation_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/investigations/{investigation_id}", None, headers)

    def request_evidence(
        self, investigation_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/investigations/{investigation_id}/request-evidence", payload, headers
        )

    def determine_investigation(
        self, investigation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/investigations/{investigation_id}/determine", payload, headers
        )

    def close_investigation_no_adjustment(
        self, investigation_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/investigations/{investigation_id}/close-no-adjustment",
            payload,
            headers,
        )

    # -----------------------------------------------------------------
    # Meter test requests (PRD §3.4)
    # -----------------------------------------------------------------
    def create_meter_test_request(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/meter-test-requests", payload, headers)

    def list_meter_test_requests(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/meter-test-requests", params, headers)

    def get_meter_test_request(
        self, request_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/meter-test-requests/{request_id}", None, headers)

    def schedule_field_test(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/meter-test-requests/{request_id}/schedule-field-test", payload, headers
        )

    def record_field_result(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/meter-test-requests/{request_id}/record-field-result", payload, headers
        )

    def record_bench_result(
        self, request_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/meter-test-requests/{request_id}/record-bench-result", payload, headers
        )

    # -----------------------------------------------------------------
    # Repair proofs (PRD §3.3)
    # -----------------------------------------------------------------
    def create_repair_proof(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/repair-proofs", payload, headers)

    def list_repair_proofs(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/repair-proofs", params, headers)

    def get_repair_proof(
        self, proof_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/repair-proofs/{proof_id}", None, headers)

    def verify_repair_proof(
        self, proof_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/repair-proofs/{proof_id}/verify", payload, headers
        )

    def reject_repair_proof(
        self, proof_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/repair-proofs/{proof_id}/reject", payload, headers
        )

    # -----------------------------------------------------------------
    # Leak adjustments (PRD §3.6, §3.7)
    # -----------------------------------------------------------------
    def create_leak_adjustment(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/leak-adjustments", payload, headers)

    def list_leak_adjustments(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/leak-adjustments", params, headers)

    def get_leak_adjustment(
        self, adjustment_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/leak-adjustments/{adjustment_id}", None, headers)

    def submit_leak_adjustment(
        self, adjustment_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/leak-adjustments/{adjustment_id}/submit", payload, headers
        )

    def return_leak_adjustment(
        self, adjustment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/leak-adjustments/{adjustment_id}/return", payload, headers
        )

    def approve_leak_adjustment(
        self, adjustment_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/leak-adjustments/{adjustment_id}/approve", payload, headers
        )

    def deny_leak_adjustment(
        self, adjustment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/leak-adjustments/{adjustment_id}/deny", payload, headers
        )

    def reverse_leak_adjustment(
        self, adjustment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/leak-adjustments/{adjustment_id}/reverse", payload, headers
        )

    # -----------------------------------------------------------------
    # Payment arrangements (PRD §3.8)
    # -----------------------------------------------------------------
    def create_payment_arrangement(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/payment-arrangements", payload, headers)

    def list_payment_arrangements(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/payment-arrangements", params, headers)

    def get_payment_arrangement(
        self, arrangement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/payment-arrangements/{arrangement_id}", None, headers
        )

    def activate_payment_arrangement(
        self, arrangement_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/payment-arrangements/{arrangement_id}/activate", payload, headers
        )

    def record_installment_payment(
        self, arrangement_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/payment-arrangements/{arrangement_id}/record-payment",
            payload,
            headers,
        )

    def reinstate_payment_arrangement(
        self, arrangement_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/payment-arrangements/{arrangement_id}/reinstate", payload, headers
        )

    # -----------------------------------------------------------------
    # Board appeals (PRD §3.9)
    # -----------------------------------------------------------------
    def create_board_appeal(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/board-appeals", payload, headers)

    def list_board_appeals(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/board-appeals", params, headers)

    def get_board_appeal(
        self, appeal_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/board-appeals/{appeal_id}", None, headers)

    def schedule_hearing(
        self, appeal_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/board-appeals/{appeal_id}/schedule", payload, headers
        )

    def record_board_decision(
        self, appeal_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/board-appeals/{appeal_id}/record-decision", payload, headers
        )


# Module-level singleton consumed by the session-scoped ``api`` fixture.
api_client = ApiClient()
