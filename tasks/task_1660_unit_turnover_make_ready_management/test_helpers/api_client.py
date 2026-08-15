"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ApiClient(GenericApiClient):
    # --- Platform / logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/make-ready/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/make-ready/properties", payload, headers)

    def get_turn_benchmark(self, property_id, headers):
        return self._request(
            "GET", f"/make-ready/properties/{property_id}/turn-benchmark",
            headers=headers,
        )

    # --- Unit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/make-ready/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/make-ready/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/make-ready/units", headers=headers,
                             params=params)

    def record_move_in(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/make-ready/units/{unit_id}/record-move-in", payload, headers,
        )

    def list_unit_lease_commitments(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/make-ready/units/{unit_id}/lease-commitments",
            headers=headers, params=params,
        )

    # --- Turn ---
    def create_turn(self, payload, headers):
        return self._request("POST", "/make-ready/turns", payload, headers)

    def get_turn(self, turn_id, headers):
        return self._request("GET", f"/make-ready/turns/{turn_id}", headers=headers)

    def list_turns(self, headers, params=None):
        return self._request("GET", "/make-ready/turns", headers=headers,
                             params=params)

    def finalize_scope(self, turn_id, headers):
        return self._request(
            "POST", f"/make-ready/turns/{turn_id}/finalize-scope", {}, headers,
        )

    def close_turn(self, turn_id, headers):
        return self._request(
            "POST", f"/make-ready/turns/{turn_id}/close", {}, headers,
        )

    def cancel_turn(self, turn_id, headers):
        return self._request(
            "POST", f"/make-ready/turns/{turn_id}/cancel", {}, headers,
        )

    # --- Inspection (nested under Turn) ---
    def submit_inspection(self, turn_id, payload, headers):
        return self._request(
            "POST", f"/make-ready/turns/{turn_id}/inspections", payload, headers,
        )

    def list_inspections(self, turn_id, headers):
        return self._request(
            "GET", f"/make-ready/turns/{turn_id}/inspections", headers=headers,
        )

    # --- ReplacementDecision ---
    def create_replacement_decision(self, turn_id, payload, headers):
        return self._request(
            "POST", f"/make-ready/turns/{turn_id}/replacement-decisions",
            payload, headers,
        )

    def list_turn_replacement_decisions(self, turn_id, headers):
        return self._request(
            "GET", f"/make-ready/turns/{turn_id}/replacement-decisions",
            headers=headers,
        )

    def list_item_replacement_decisions(self, scope_item_id, headers):
        return self._request(
            "GET", f"/make-ready/scope-items/{scope_item_id}/replacement-decisions",
            headers=headers,
        )

    # --- ScopeItem ---
    def create_scope_item(self, payload, headers):
        return self._request("POST", "/make-ready/scope-items", payload, headers)

    def get_scope_item(self, item_id, headers):
        return self._request(
            "GET", f"/make-ready/scope-items/{item_id}", headers=headers,
        )

    def list_scope_items(self, headers, params=None):
        return self._request("GET", "/make-ready/scope-items", headers=headers,
                             params=params)

    def approve_scope_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/make-ready/scope-items/{item_id}/approve", payload, headers,
        )

    def reject_scope_item(self, item_id, headers):
        return self._request(
            "POST", f"/make-ready/scope-items/{item_id}/reject", {}, headers,
        )

    def void_scope_item(self, item_id, headers):
        return self._request(
            "POST", f"/make-ready/scope-items/{item_id}/void", {}, headers,
        )

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/make-ready/vendors", payload, headers)

    # --- VendorAssignment ---
    def create_vendor_assignment(self, payload, headers):
        return self._request(
            "POST", "/make-ready/vendor-assignments", payload, headers,
        )

    def get_vendor_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/make-ready/vendor-assignments/{assignment_id}",
            headers=headers,
        )

    def list_vendor_assignments(self, headers, params=None):
        return self._request(
            "GET", "/make-ready/vendor-assignments", headers=headers, params=params,
        )

    def accept_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/make-ready/vendor-assignments/{assignment_id}/accept",
            {}, headers,
        )

    def decline_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/make-ready/vendor-assignments/{assignment_id}/decline",
            {}, headers,
        )

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/make-ready/vendor-assignments/{assignment_id}/complete",
            payload, headers,
        )

    # --- LeaseCommitment ---
    def create_lease_commitment(self, payload, headers):
        return self._request(
            "POST", "/make-ready/lease-commitments", payload, headers,
        )

    def cancel_lease_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/make-ready/lease-commitments/{commitment_id}/cancel",
            {}, headers,
        )


api_client = ApiClient()

# --- Transport resilience under per-test-server isolation -------------------
# The runner kills and restarts the API server on the same port before every
# test. A keep-alive connection pooled from the previous server instance is
# dead the next time it is used, and the kernel answers the write with RST
# ("Connection reset by peer"). Two guards, neither of which touches any
# request/response semantics:
#  1. Connection: close — every request uses a fresh TCP connection, so no
#     stale pooled connection can ever be reused across a server restart.
#  2. A retry adapter covering transport-level failures only (connection
#     errors, remote disconnects — never HTTP status codes). Retrying is
#     safe: an RST/reset on a dead or closing pooled socket means the
#     request bytes never reached a live server, so nothing is re-executed.
_RETRY = Retry(
    total=5,
    connect=5,
    read=5,
    status=0,
    other=0,
    backoff_factor=0.05,
    allowed_methods=None,  # transport retries only; see note above
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_RETRY)
api_client.session.mount("http://", _adapter)
api_client.session.mount("https://", _adapter)
api_client.session.headers["Connection"] = "close"
