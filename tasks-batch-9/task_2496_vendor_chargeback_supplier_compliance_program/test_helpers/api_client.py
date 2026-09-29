"""API client: one method per endpoint declared in the PRD.

Every programme path is rooted at the `/compliance` prefix.  The logical-clock
control endpoint is the single exception: the PRD publishes it at
`/_clock/set_current_utc`, outside the prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/compliance"
CLOCK_PATH = "/_clock/set_current_utc"


class ApiClient(GenericApiClient):
    """Endpoint methods for the vendor chargeback and supplier compliance API."""

    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ---------------------------------------------------------------- vendors
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vendors", headers=headers, params=params)

    # ---------------------------------------------------------- routing guides
    def create_routing_guide(self, payload, headers):
        return self._request("POST", f"{PREFIX}/routing-guides", payload, headers)

    def get_routing_guide(self, guide_id, headers):
        return self._request(
            "GET", f"{PREFIX}/routing-guides/{guide_id}", headers=headers
        )

    def list_routing_guides(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/routing-guides", headers=headers, params=params
        )

    def create_requirement(self, guide_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/routing-guides/{guide_id}/requirements", payload, headers
        )

    def list_requirements(self, guide_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/routing-guides/{guide_id}/requirements",
            headers=headers,
            params=params,
        )

    def publish_routing_guide(self, guide_id, headers):
        return self._request(
            "POST", f"{PREFIX}/routing-guides/{guide_id}/publish", {}, headers
        )

    # -------------------------------------------------------- purchase orders
    def create_purchase_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request(
            "GET", f"{PREFIX}/purchase-orders/{po_id}", headers=headers
        )

    def list_purchase_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/purchase-orders", headers=headers, params=params
        )

    # -------------------------------------------------------------- shipments
    def create_shipment(self, po_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/purchase-orders/{po_id}/shipments", payload, headers
        )

    def list_po_shipments(self, po_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/purchase-orders/{po_id}/shipments",
            headers=headers,
            params=params,
        )

    def get_shipment(self, shipment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers
        )

    def receive_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/receive", payload, headers
        )

    # ------------------------------------------------------------- violations
    def create_violation(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/violations", payload, headers
        )

    def get_violation(self, violation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/violations/{violation_id}", headers=headers
        )

    def list_violations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/violations", headers=headers, params=params
        )

    def add_violation_evidence(self, violation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violations/{violation_id}/evidence", payload, headers
        )

    def list_violation_evidence(self, violation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/violations/{violation_id}/evidence",
            headers=headers,
            params=params,
        )

    def assess_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violations/{violation_id}/assess", payload, headers
        )

    def void_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violations/{violation_id}/void", payload, headers
        )

    # ------------------------------------------------------------ chargebacks
    def get_chargeback(self, chargeback_id, headers):
        return self._request(
            "GET", f"{PREFIX}/chargebacks/{chargeback_id}", headers=headers
        )

    def list_chargebacks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/chargebacks", headers=headers, params=params
        )

    def create_dispute(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{chargeback_id}/disputes", payload, headers
        )

    def apply_cash(self, chargeback_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/chargebacks/{chargeback_id}/cash-applications",
            payload,
            headers,
        )

    # --------------------------------------------------------------- disputes
    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{PREFIX}/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/disputes", headers=headers, params=params
        )

    def add_dispute_evidence(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/evidence", payload, headers
        )

    def list_dispute_evidence(self, dispute_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/disputes/{dispute_id}/evidence",
            headers=headers,
            params=params,
        )

    def request_dispute_info(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/request-info", payload, headers
        )

    def resubmit_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/resubmit", payload, headers
        )

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/decide", payload, headers
        )

    # ------------------------------------------------------------- scorecards
    def create_scorecard(self, payload, headers):
        return self._request("POST", f"{PREFIX}/scorecards", payload, headers)

    def get_scorecard(self, scorecard_id, headers):
        return self._request(
            "GET", f"{PREFIX}/scorecards/{scorecard_id}", headers=headers
        )

    def list_scorecards(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/scorecards", headers=headers, params=params
        )

    def measure_scorecard(self, scorecard_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/scorecards/{scorecard_id}/measure", payload, headers
        )

    def finalize_scorecard(self, scorecard_id, headers):
        return self._request(
            "POST", f"{PREFIX}/scorecards/{scorecard_id}/finalize", {}, headers
        )

    # -------------------------------------------------- corrective action plans
    def get_cap(self, cap_id, headers):
        return self._request(
            "GET", f"{PREFIX}/corrective-action-plans/{cap_id}", headers=headers
        )

    def list_caps(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/corrective-action-plans", headers=headers, params=params
        )

    def submit_cap(self, cap_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corrective-action-plans/{cap_id}/submit",
            payload,
            headers,
        )

    def decide_cap(self, cap_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corrective-action-plans/{cap_id}/decide",
            payload,
            headers,
        )

    def escalate_cap(self, cap_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corrective-action-plans/{cap_id}/escalate",
            payload,
            headers,
        )

    def close_cap(self, cap_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corrective-action-plans/{cap_id}/close",
            payload,
            headers,
        )

    # ------------------------------------------------------------- deductions
    def create_deduction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deductions", payload, headers)

    def get_deduction(self, deduction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/deductions/{deduction_id}", headers=headers
        )

    def list_deductions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/deductions", headers=headers, params=params
        )

    def create_allocation(self, deduction_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deductions/{deduction_id}/allocations", payload, headers
        )

    def post_deduction(self, deduction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/deductions/{deduction_id}/post", {}, headers
        )

    def reverse_deduction(self, deduction_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deductions/{deduction_id}/reverse", payload, headers
        )

    # ---------------------------------------------------- recovery allocations
    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/recovery-allocations/{allocation_id}", headers=headers
        )

    def list_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/recovery-allocations", headers=headers, params=params
        )


api_client = ApiClient()
