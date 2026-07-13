"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/api/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/api/properties/{property_id}", headers=headers)

    def update_property(self, property_id, payload, headers):
        return self._request("PATCH", f"/api/properties/{property_id}", payload, headers)

    # ---- PermitApplication ----
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/api/permit-applications", payload, headers)

    def get_permit_application(self, application_id, headers):
        return self._request("GET", f"/api/permit-applications/{application_id}", headers=headers)

    def list_permit_applications(self, headers, params=None):
        return self._request("GET", "/api/permit-applications", headers=headers, params=params)

    def submit_permit_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/api/permit-applications/{application_id}/submit", payload or {}, headers)

    def pay_fee(self, application_id, payload, headers):
        return self._request("POST", f"/api/permit-applications/{application_id}/pay-fee", payload, headers)

    # ---- PlanReview ----
    def get_plan_review(self, plan_review_id, headers):
        return self._request("GET", f"/api/plan-reviews/{plan_review_id}", headers=headers)

    def list_plan_reviews(self, headers, params=None):
        return self._request("GET", "/api/plan-reviews", headers=headers, params=params)

    def discipline_decision(self, plan_review_id, payload, headers):
        return self._request("POST", f"/api/plan-reviews/{plan_review_id}/discipline-decision", payload, headers)

    def resubmit_corrections(self, plan_review_id, headers, payload=None):
        return self._request("POST", f"/api/plan-reviews/{plan_review_id}/resubmit-corrections", payload or {}, headers)

    # ---- Permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/api/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/api/permits", headers=headers, params=params)

    def revoke_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/api/permits/{permit_id}/revoke", payload or {}, headers)

    # ---- Certificate ----
    def create_certificate(self, payload, headers):
        return self._request("POST", "/api/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/api/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/api/certificates", headers=headers, params=params)

    def reinstate_certificate(self, certificate_id, headers, payload=None):
        return self._request("POST", f"/api/certificates/{certificate_id}/reinstate", payload or {}, headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/api/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/api/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/api/inspections", headers=headers, params=params)

    def record_result(self, inspection_id, payload, headers):
        return self._request("POST", f"/api/inspections/{inspection_id}/record-result", payload, headers)

    # ---- Violation ----
    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/api/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/api/violations", headers=headers, params=params)

    def create_abatement_order(self, violation_id, payload, headers):
        return self._request("POST", f"/api/violations/{violation_id}/abatement-orders", payload, headers)

    # ---- AbatementOrder ----
    def get_abatement_order(self, abatement_order_id, headers):
        return self._request("GET", f"/api/abatement-orders/{abatement_order_id}", headers=headers)

    def list_abatement_orders(self, headers, params=None):
        return self._request("GET", "/api/abatement-orders", headers=headers, params=params)

    def comply_abatement_order(self, abatement_order_id, headers, payload=None):
        return self._request("POST", f"/api/abatement-orders/{abatement_order_id}/comply", payload or {}, headers)

    # ---- Hydrant ----
    def create_hydrant(self, payload, headers):
        return self._request("POST", "/api/hydrants", payload, headers)

    def get_hydrant(self, hydrant_id, headers):
        return self._request("GET", f"/api/hydrants/{hydrant_id}", headers=headers)

    def list_hydrants(self, headers, params=None):
        return self._request("GET", "/api/hydrants", headers=headers, params=params)

    # ---- FlowTest ----
    def create_flow_test(self, payload, headers):
        return self._request("POST", "/api/flow-tests", payload, headers)

    def get_flow_test(self, flow_test_id, headers):
        return self._request("GET", f"/api/flow-tests/{flow_test_id}", headers=headers)

    def list_flow_tests(self, headers, params=None):
        return self._request("GET", "/api/flow-tests", headers=headers, params=params)

    # ---- Ops / logical clock (test-driving) ----
    def process_overdue_orders(self, headers, payload=None):
        return self._request("POST", "/api/_ops/process-overdue-orders", payload or {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
