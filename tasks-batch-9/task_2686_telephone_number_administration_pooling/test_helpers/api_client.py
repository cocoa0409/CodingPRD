"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/numbering"


class ApiClient(GenericApiClient):
    # --- logical clock -------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- carriers ------------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{PREFIX}/carriers/{carrier_id}", headers=headers)

    def create_license_action(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/carriers/{carrier_id}/license-actions", payload, headers
        )

    def create_readiness_event(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/carriers/{carrier_id}/readiness-events", payload, headers
        )

    # --- NPAs ----------------------------------------------------------------
    def create_npa(self, payload, headers):
        return self._request("POST", f"{PREFIX}/npas", payload, headers)

    def list_npas(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/npas", headers=headers, params=params)

    def get_npa(self, npa_id, headers):
        return self._request("GET", f"{PREFIX}/npas/{npa_id}", headers=headers)

    def list_npa_rate_centers(self, npa_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/npas/{npa_id}/rate-centers", headers=headers, params=params
        )

    def declare_jeopardy(self, npa_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/npas/{npa_id}/jeopardy-declarations", payload, headers
        )

    def create_relief_plan(self, npa_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/npas/{npa_id}/relief-plans", payload, headers
        )

    def list_npa_relief_plans(self, npa_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/npas/{npa_id}/relief-plans", headers=headers, params=params
        )

    # --- rate centers --------------------------------------------------------
    def create_rate_center(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-centers", payload, headers)

    def list_rate_centers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rate-centers", headers=headers, params=params
        )

    def get_rate_center(self, rate_center_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rate-centers/{rate_center_id}", headers=headers
        )

    def list_rate_center_blocks(self, rate_center_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/rate-centers/{rate_center_id}/blocks",
            headers=headers,
            params=params,
        )

    def create_pooling_transition(self, rate_center_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rate-centers/{rate_center_id}/pooling-transitions",
            payload,
            headers,
        )

    # --- number blocks -------------------------------------------------------
    def create_block(self, payload, headers):
        return self._request("POST", f"{PREFIX}/blocks", payload, headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/blocks", headers=headers, params=params)

    def get_block(self, block_id, headers):
        return self._request("GET", f"{PREFIX}/blocks/{block_id}", headers=headers)

    def create_activation_confirmation(self, block_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/blocks/{block_id}/activation-confirmations",
            payload,
            headers,
        )

    def create_routing_record(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/blocks/{block_id}/routing-records", payload, headers
        )

    def list_block_routing_records(self, block_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/blocks/{block_id}/routing-records",
            headers=headers,
            params=params,
        )

    # --- allocation requests -------------------------------------------------
    def create_allocation_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/allocation-requests", payload, headers)

    def list_allocation_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/allocation-requests", headers=headers, params=params
        )

    def get_allocation_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/allocation-requests/{request_id}", headers=headers
        )

    def create_review(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/allocation-requests/{request_id}/reviews",
            payload,
            headers,
        )

    def create_resubmission(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/allocation-requests/{request_id}/resubmissions",
            payload,
            headers,
        )

    # --- utilization filings -------------------------------------------------
    def create_utilization_filing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/utilization-filings", payload, headers)

    def create_filing_submission(self, filing_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/utilization-filings/{filing_id}/submissions",
            payload,
            headers,
        )

    def list_utilization_filings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/utilization-filings", headers=headers, params=params
        )

    def get_utilization_filing(self, filing_id, headers):
        return self._request(
            "GET", f"{PREFIX}/utilization-filings/{filing_id}", headers=headers
        )

    # --- audit findings ------------------------------------------------------
    def create_audit_finding(self, filing_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/utilization-filings/{filing_id}/audit-findings",
            payload,
            headers,
        )

    def list_filing_audit_findings(self, filing_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/utilization-filings/{filing_id}/audit-findings",
            headers=headers,
            params=params,
        )

    def get_audit_finding(self, finding_id, headers):
        return self._request(
            "GET", f"{PREFIX}/audit-findings/{finding_id}", headers=headers
        )

    def create_disposition(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-findings/{finding_id}/dispositions", payload, headers
        )

    # --- reclamation ---------------------------------------------------------
    def create_reclamation_sweep(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reclamation-sweeps", payload, headers)

    def list_reclamation_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reclamation-orders", headers=headers, params=params
        )

    def get_reclamation_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reclamation-orders/{order_id}", headers=headers
        )

    def create_reclamation_transition(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/reclamation-orders/{order_id}/transitions",
            payload,
            headers,
        )

    # --- relief plans and comments -------------------------------------------
    def list_relief_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/relief-plans", headers=headers, params=params
        )

    def get_relief_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/relief-plans/{plan_id}", headers=headers)

    def create_public_comment(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/relief-plans/{plan_id}/comments", payload, headers
        )

    def list_relief_plan_comments(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/relief-plans/{plan_id}/comments",
            headers=headers,
            params=params,
        )

    def create_relief_transition(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/relief-plans/{plan_id}/transitions", payload, headers
        )

    # --- port requests -------------------------------------------------------
    def create_port_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/port-requests", payload, headers)

    def list_port_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/port-requests", headers=headers, params=params
        )

    def get_port_request(self, port_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/port-requests/{port_request_id}", headers=headers
        )

    def create_port_transition(self, port_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/port-requests/{port_request_id}/transitions",
            payload,
            headers,
        )


api_client = ApiClient()
