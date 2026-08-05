"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Public Pool & Spa Health Permit API."""

    # ---------------- logical clock ----------------

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- operators & ledger ----------------

    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    def create_payment(self, operator_id, payload, headers):
        return self._request(
            "POST", f"/operators/{operator_id}/payments", payload, headers
        )

    def get_fee_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/fee-ledger-entries/{entry_id}", headers=headers)

    def list_fee_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/fee-ledger-entries", headers=headers, params=params
        )

    # ---------------- facilities ----------------

    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def patch_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"/facilities/{facility_id}", payload, headers)

    # ---------------- plan reviews ----------------

    def create_plan_review(self, payload, headers):
        return self._request("POST", "/plan-reviews", payload, headers)

    def create_plan_review_revision(self, plan_review_id, payload, headers):
        return self._request(
            "POST", f"/plan-reviews/{plan_review_id}/revisions", payload, headers
        )

    def get_plan_review(self, plan_review_id, headers):
        return self._request("GET", f"/plan-reviews/{plan_review_id}", headers=headers)

    def list_plan_reviews(self, headers, params=None):
        return self._request("GET", "/plan-reviews", headers=headers, params=params)

    def transition_plan_review(self, plan_review_id, payload, headers):
        return self._request(
            "POST", f"/plan-reviews/{plan_review_id}/transition", payload, headers
        )

    # ---------------- permits ----------------

    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def transition_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permits/{permit_id}/transition", payload, headers
        )

    # ---------------- inspections ----------------

    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def transition_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/transition", payload, headers
        )

    def enforce_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/enforcement", payload, headers
        )

    # ---------------- violations ----------------

    def create_violation(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/violations", payload, headers
        )

    def list_violations(self, inspection_id, headers, params=None):
        return self._request(
            "GET", f"/inspections/{inspection_id}/violations", headers=headers,
            params=params,
        )

    def correct_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/correct", payload, headers
        )

    def verify_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/verify", payload, headers
        )

    # ---------------- water chemistry ----------------

    def create_water_reading(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/water-readings", payload, headers
        )

    def list_water_readings(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/water-readings", headers=headers,
            params=params,
        )

    # ---------------- closure orders / reopen ----------------

    def create_closure_order(self, payload, headers):
        return self._request("POST", "/closure-orders", payload, headers)

    def get_closure_order(self, closure_order_id, headers):
        return self._request(
            "GET", f"/closure-orders/{closure_order_id}", headers=headers
        )

    def list_closure_orders(self, headers, params=None):
        return self._request("GET", "/closure-orders", headers=headers, params=params)

    def request_reopen(self, closure_order_id, payload, headers):
        return self._request(
            "POST", f"/closure-orders/{closure_order_id}/reopen-request", payload,
            headers,
        )

    def decide_reopen(self, closure_order_id, payload, headers):
        return self._request(
            "POST", f"/closure-orders/{closure_order_id}/reopen-decision", payload,
            headers,
        )

    # ---------------- staffing ----------------

    def create_staff_assignment(self, payload, headers):
        return self._request("POST", "/staff-assignments", payload, headers)

    def list_staff_assignments(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/staff-assignments", headers=headers,
            params=params,
        )

    def cancel_staff_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/staff-assignments/{assignment_id}/cancel", {}, headers
        )

    # ---------------- signage & drain certification ----------------

    def create_compliance_artifact(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/compliance-artifacts", payload, headers
        )

    def list_compliance_artifacts(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/compliance-artifacts", headers=headers,
            params=params,
        )

    # ---------------- complaints ----------------

    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def transition_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/transition", payload, headers
        )


api_client = ApiClient()
