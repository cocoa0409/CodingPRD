"""One method per ROI endpoint, all returning the raw requests.Response."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class RoiApiClient(GenericApiClient):
    """Thin endpoint-per-method wrapper over the release-of-information API."""

    # ------------------------------------------------------------ logical clock
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------ state fee rules
    def create_state_fee_rule(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/state-fee-rules", payload, headers)

    def list_state_fee_rules(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/state-fee-rules", params, headers)

    # ------------------------------------------------------------ facilities
    def create_facility(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/facilities/{facility_id}", None, headers)

    def list_facilities(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/facilities", params, headers)

    def set_facility_status(self, facility_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/facilities/{facility_id}/status", payload, headers)

    # ------------------------------------------------------------ patients
    def create_patient(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/patients/{patient_id}", None, headers)

    def list_patients(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/patients", params, headers)

    # ------------------------------------------------------------ requesters
    def create_requester(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requesters", payload, headers)

    def get_requester(self, requester_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/requesters/{requester_id}", None, headers)

    def list_requesters(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/requesters", params, headers)

    # ------------------------------------------------------------ authorizations
    def create_authorization(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/authorizations", payload, headers)

    def get_authorization(self, authorization_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/authorizations/{authorization_id}", None, headers)

    def list_authorizations(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/authorizations", params, headers)

    def revoke_authorization(self, authorization_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/authorizations/{authorization_id}/revoke", payload, headers)

    def cure_authorization(self, authorization_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/authorizations/{authorization_id}/cure", payload, headers)

    # ------------------------------------------------------------ requests
    def create_request(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requests", payload, headers)

    def get_request(self, request_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/requests/{request_id}", None, headers)

    def list_requests(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/requests", params, headers)

    def get_turnaround(self, request_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/requests/{request_id}/turnaround", None, headers)

    def intake_decision(self, request_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requests/{request_id}/intake-decision", payload, headers)

    def notice_extension(self, request_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requests/{request_id}/extension", payload, headers)

    def complete_compilation(self, request_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requests/{request_id}/complete-compilation", payload, headers)

    def sensitive_review(self, request_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requests/{request_id}/sensitive-review", payload, headers)

    def release_request(self, request_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requests/{request_id}/release", payload, headers)

    def withdraw_request(self, request_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/requests/{request_id}/withdraw", payload, headers)

    def list_compliance_events(self, request_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/requests/{request_id}/compliance-events", params, headers
        )

    # ------------------------------------------------------------ record segments
    def create_record_segment(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/record-segments", payload, headers)

    def get_record_segment(self, segment_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/record-segments/{segment_id}", None, headers)

    def list_record_segments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/record-segments", params, headers)

    def segment_disposition(self, segment_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/record-segments/{segment_id}/disposition", payload, headers)

    def apply_redaction(self, segment_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/record-segments/{segment_id}/redaction", payload, headers)

    def redaction_decision(self, segment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/record-segments/{segment_id}/redaction-decision", payload, headers
        )

    # ------------------------------------------------------------ invoices
    def create_invoice(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/invoices", params, headers)

    def list_invoice_lines(self, invoice_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/invoices/{invoice_id}/lines", params, headers)

    def issue_invoice(self, invoice_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/invoices/{invoice_id}/issue", payload, headers)

    def settle_invoice(self, invoice_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/invoices/{invoice_id}/settlement", payload, headers)

    # ------------------------------------------------------------ deliveries
    def create_delivery(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/deliveries", payload, headers)

    def get_delivery(self, delivery_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/deliveries/{delivery_id}", None, headers)

    def list_deliveries(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/deliveries", params, headers)

    def record_transmission(self, delivery_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/deliveries/{delivery_id}/transmission", payload, headers)

    def confirm_delivery(self, delivery_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/deliveries/{delivery_id}/confirm", payload, headers)

    # ------------------------------------------------------------ denials
    def create_denial(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/denials", payload, headers)

    def get_denial(self, denial_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/denials/{denial_id}", None, headers)

    def list_denials(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/denials", params, headers)

    def review_denial(self, denial_id: str, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/denials/{denial_id}/review", payload, headers)

    # ------------------------------------------------------------ amendment requests
    def create_amendment_request(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/amendment-requests", payload, headers)

    def get_amendment_request(self, amendment_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/amendment-requests/{amendment_id}", None, headers)

    def list_amendment_requests(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{API_PREFIX}/amendment-requests", params, headers)

    def amendment_decision(self, amendment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/amendment-requests/{amendment_id}/decision", payload, headers
        )

    def amendment_resubmission(self, amendment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/amendment-requests/{amendment_id}/resubmission", payload, headers
        )

    # ------------------------------------------------------------ compliance sweep
    def run_compliance_sweep(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/compliance-sweeps", payload, headers)
